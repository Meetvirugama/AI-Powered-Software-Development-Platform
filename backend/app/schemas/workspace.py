"""Workspace & Sandbox Isolation Contract Schemas.

Owner: Prit Zania — Week 3 Day 1 Deliverable (Docs/week3.md §6 F33, §7.1, §8 Day 1)
Reference: Docs/week3.md §6 (F33 — Isolated Workspace and Repository Operations)

Responsibilities:
1. Define WorkspaceStatus lifecycle state machine enum (NOT_CREATED -> CREATING -> READY -> IN_USE -> STOPPED/FAILED -> CLEANUP_PENDING -> CLEANED).
2. Validate workspace paths and enforce containment within designated .workspaces/ sandboxes.
3. Define WorkspaceResourceLimits enforcing timeouts, disk quotas, file size caps, and process boundaries.
4. Establish canonical metadata schemas for workspace creation, file operations (read, write, patch, delete), and safe cleanup.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from enum import Enum
from pathlib import PurePosixPath
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.core.input_security import UnsafePathError, validate_repo_relative_path

_COMMIT_SHA_RE = re.compile(r"^[0-9a-fA-F]{7,64}$")
_BRANCH_NAME_RE = re.compile(r"^[A-Za-z0-9._/-]{1,200}$")


# ---------------------------------------------------------------------------
# 1. Workspace Lifecycle State Machine (Docs/week3.md §6 F33)
# ---------------------------------------------------------------------------

class WorkspaceStatus(str, Enum):
    """Canonical workspace lifecycle states matching Docs/week3.md §6 F33."""

    NOT_CREATED = "NOT_CREATED"
    CREATING = "CREATING"
    READY = "READY"
    IN_USE = "IN_USE"
    STOPPED = "STOPPED"
    FAILED = "FAILED"
    CLEANUP_PENDING = "CLEANUP_PENDING"
    CLEANED = "CLEANED"


VALID_WORKSPACE_TRANSITIONS: dict[WorkspaceStatus, frozenset[WorkspaceStatus]] = {
    WorkspaceStatus.NOT_CREATED: frozenset(
        {WorkspaceStatus.CREATING, WorkspaceStatus.FAILED}
    ),
    WorkspaceStatus.CREATING: frozenset(
        {WorkspaceStatus.READY, WorkspaceStatus.FAILED}
    ),
    WorkspaceStatus.READY: frozenset(
        {
            WorkspaceStatus.IN_USE,
            WorkspaceStatus.STOPPED,
            WorkspaceStatus.CLEANUP_PENDING,
            WorkspaceStatus.FAILED,
        }
    ),
    WorkspaceStatus.IN_USE: frozenset(
        {
            WorkspaceStatus.READY,
            WorkspaceStatus.STOPPED,
            WorkspaceStatus.FAILED,
            WorkspaceStatus.CLEANUP_PENDING,
        }
    ),
    WorkspaceStatus.STOPPED: frozenset(
        {WorkspaceStatus.IN_USE, WorkspaceStatus.READY, WorkspaceStatus.CLEANUP_PENDING, WorkspaceStatus.FAILED}
    ),

    WorkspaceStatus.FAILED: frozenset(
        {WorkspaceStatus.CLEANUP_PENDING}
    ),
    WorkspaceStatus.CLEANUP_PENDING: frozenset(
        {WorkspaceStatus.CLEANED, WorkspaceStatus.FAILED}
    ),
    WorkspaceStatus.CLEANED: frozenset(),  # Terminal state
}


def can_transition_workspace(current: WorkspaceStatus, target: WorkspaceStatus) -> bool:
    """Return True if transitioning from `current` to `target` is permitted by policy."""
    if current == target:
        return True
    return target in VALID_WORKSPACE_TRANSITIONS.get(current, frozenset())


# ---------------------------------------------------------------------------
# 2. Resource Limits & Quotas (ADR-007, Docs/week3.md §6 F33)
# ---------------------------------------------------------------------------

class WorkspaceResourceLimits(BaseModel):
    """Resource constraints applied to isolated workspace execution."""

    timeout_seconds: int = Field(
        default=60,
        ge=1,
        le=300,
        description="Maximum execution timeout in seconds per command/operation.",
    )
    max_disk_bytes: int = Field(
        default=500 * 1024 * 1024,  # 500 MB
        ge=1,
        le=5 * 1024 * 1024 * 1024,
        description="Maximum allowable disk space for the workspace directory.",
    )
    max_file_size_bytes: int = Field(
        default=5 * 1024 * 1024,  # 5 MB
        ge=1,
        le=50 * 1024 * 1024,
        description="Maximum file size readable or writable in a single operation.",
    )
    max_files_modified: int = Field(
        default=50,
        ge=1,
        le=500,
        description="Upper ceiling of files modified in a single agent task.",
    )
    network_egress_allowed: bool = Field(
        default=False,
        description="Strict network egress lockdown; denied by default per ADR-007.",
    )



# ---------------------------------------------------------------------------
# 3. Workspace Metadata & Identity
# ---------------------------------------------------------------------------

WorkspaceIsolationType = Literal["git_worktree", "directory_copy"]


class WorkspaceMetadata(BaseModel):
    """Comprehensive state record for an isolated task workspace."""

    model_config = ConfigDict(from_attributes=True, extra="allow")

    workspace_id: str = Field(..., description="Unique UUID for this workspace instance.")
    task_id: str = Field(..., description="Task UUID bound to this workspace.")
    repository_id: str = Field(..., description="Target repository UUID.")
    base_revision: str = Field(..., description="Commit SHA from which isolation originated.")
    branch_name: str = Field(..., description="Agent branch checked out in workspace.")
    workspace_path: str = Field(..., description="Absolute filesystem directory path of workspace.")
    status: WorkspaceStatus = Field(default=WorkspaceStatus.NOT_CREATED)
    isolation_type: WorkspaceIsolationType = Field(default="git_worktree")
    resource_limits: WorkspaceResourceLimits = Field(default_factory=WorkspaceResourceLimits)
    created_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    updated_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    last_active_at: str | None = Field(default=None)
    cleaned_at: str | None = Field(default=None)
    error_message: str | None = Field(default=None)
    verification_diff_hash: str | None = Field(default=None)

    @field_validator("base_revision")
    @classmethod
    def _validate_base_sha(cls, value: str) -> str:
        cleaned = value.strip()
        if not _COMMIT_SHA_RE.match(cleaned):
            raise ValueError(f"Invalid base_revision commit SHA format: '{value}'")
        return cleaned

    @field_validator("branch_name")
    @classmethod
    def _validate_branch(cls, value: str) -> str:
        cleaned = value.strip()
        if not _BRANCH_NAME_RE.match(cleaned) or ".." in cleaned or cleaned.startswith("-"):
            raise ValueError(f"Invalid branch name format: '{value}'")
        return cleaned


# ---------------------------------------------------------------------------
# 4. Workspace Creation Contracts
# ---------------------------------------------------------------------------

class WorkspaceCreateRequest(BaseModel):
    """Request payload to instantiate an isolated task workspace."""

    task_id: str = Field(..., min_length=1, description="Unique task identifier.")
    repository_id: str = Field(..., min_length=1, description="Repository UUID.")
    base_revision: str = Field(..., min_length=7, description="Base commit SHA.")
    branch_name: str | None = Field(
        default=None,
        description="Optional explicit agent branch name (e.g. agent/task-<id>).",
    )
    repository_root: str | None = Field(
        default=None,
        description="Optional path to local bare or working repository clone.",
    )
    isolation_type: WorkspaceIsolationType = Field(
        default="git_worktree",
        description="Preferred isolation mechanism.",
    )
    resource_limits: WorkspaceResourceLimits = Field(
        default_factory=WorkspaceResourceLimits,
        description="Custom resource limits for this workspace.",
    )


class WorkspaceCreateResult(BaseModel):
    """Result of attempting to provision a workspace."""

    success: bool
    metadata: WorkspaceMetadata | None = None
    error: str | None = None
    duration_ms: float = 0.0


# ---------------------------------------------------------------------------
# 5. File Operation Contracts (Safe Sandbox I/O)
# ---------------------------------------------------------------------------

class WorkspaceFileReadRequest(BaseModel):
    """Request to safely read a file from the workspace."""

    file_path: str = Field(..., description="Repository-relative file path to read.")

    @field_validator("file_path")
    @classmethod
    def _validate_path(cls, value: str) -> str:
        try:
            return validate_repo_relative_path(value)
        except UnsafePathError as exc:
            raise ValueError(f"Unsafe file_path: {exc}") from exc


class WorkspaceFileReadResult(BaseModel):
    """Result of reading a file inside the sandbox."""

    success: bool
    file_path: str
    content: str | None = None
    size_bytes: int = 0
    error: str | None = None


class WorkspaceFileWriteRequest(BaseModel):
    """Request to safely write or overwrite a file within the workspace."""

    file_path: str = Field(..., description="Repository-relative file path to write.")
    content: str = Field(..., description="Text content to write.")
    create_parents: bool = Field(default=True, description="Create parent directories if absent.")

    @field_validator("file_path")
    @classmethod
    def _validate_path(cls, value: str) -> str:
        try:
            return validate_repo_relative_path(value)
        except UnsafePathError as exc:
            raise ValueError(f"Unsafe file_path: {exc}") from exc


class WorkspaceFileWriteResult(BaseModel):
    """Result of writing a file inside the sandbox."""

    success: bool
    file_path: str
    bytes_written: int = 0
    created: bool = False
    error: str | None = None


class WorkspaceFilePatchRequest(BaseModel):
    """Request to perform a targeted text patch on a file."""

    file_path: str = Field(..., description="Repository-relative file path.")
    target_content: str = Field(..., min_length=1, description="Exact substring to find.")
    replacement_content: str = Field(..., description="Replacement substring.")

    @field_validator("file_path")
    @classmethod
    def _validate_path(cls, value: str) -> str:
        try:
            return validate_repo_relative_path(value)
        except UnsafePathError as exc:
            raise ValueError(f"Unsafe file_path: {exc}") from exc


class WorkspaceFilePatchResult(BaseModel):
    """Result of applying a patch inside the workspace."""

    success: bool
    file_path: str
    occurrences_replaced: int = 0
    error: str | None = None


# ---------------------------------------------------------------------------
# 6. Cleanup Contracts
# ---------------------------------------------------------------------------

class WorkspaceCleanupResult(BaseModel):
    """Summary of workspace decommissioning."""

    success: bool
    workspace_id: str
    cleaned_path: str | None = None
    worktree_pruned: bool = False
    duration_ms: float = 0.0
    error: str | None = None


# ---------------------------------------------------------------------------
# 7. Execution Start & Lifecycle Schemas (Docs/week3.md §8 Day 3)
# ---------------------------------------------------------------------------

class WorkspaceExecutionEventType(str, Enum):
    """Event types emitted during task execution in an isolated workspace."""

    WORKSPACE_CREATED = "WORKSPACE_CREATED"
    BASE_REVISION_VERIFIED = "BASE_REVISION_VERIFIED"
    BRANCH_SETUP = "BRANCH_SETUP"
    EXECUTION_STARTED = "EXECUTION_STARTED"
    TOOL_INVOCATION = "TOOL_INVOCATION"
    EXECUTION_PAUSED = "EXECUTION_PAUSED"
    EXECUTION_RESUMED = "EXECUTION_RESUMED"
    EXECUTION_STOPPED = "EXECUTION_STOPPED"
    EXECUTION_FAILED = "EXECUTION_FAILED"
    CLEANUP_INITIATED = "CLEANUP_INITIATED"
    CLEANUP_COMPLETED = "CLEANUP_COMPLETED"
    TESTS_STARTED = "TESTS_STARTED"
    TESTS_PASSED = "TESTS_PASSED"
    TESTS_FAILED = "TESTS_FAILED"
    TEST_INFRASTRUCTURE_FAILURE = "TEST_INFRASTRUCTURE_FAILURE"
    TEST_TIMEOUT = "TEST_TIMEOUT"
    REPAIR_ATTEMPT_STARTED = "REPAIR_ATTEMPT_STARTED"
    REPAIR_ATTEMPT_COMPLETED = "REPAIR_ATTEMPT_COMPLETED"
    REPAIR_BUDGET_EXHAUSTED = "REPAIR_BUDGET_EXHAUSTED"
    # Week 3 Day 5 verification & publication timeline events
    DIFF_INSPECTED = "DIFF_INSPECTED"
    DIFF_VALIDATED = "DIFF_VALIDATED"
    DIFF_VALIDATION_FAILED = "DIFF_VALIDATION_FAILED"
    PUBLICATION_AUTHORIZED = "PUBLICATION_AUTHORIZED"
    CHANGES_COMMITTED = "CHANGES_COMMITTED"
    BRANCH_PUSHED = "BRANCH_PUSHED"
    PR_CREATED = "PR_CREATED"
    PUBLICATION_FAILED = "PUBLICATION_FAILED"
    # Week 3 Day 6 reliability, security & failure recovery timeline events
    WORKER_CRASH_RECOVERED = "WORKER_CRASH_RECOVERED"
    EXECUTION_INTERRUPTED = "EXECUTION_INTERRUPTED"
    STALE_REVISION_DETECTED = "STALE_REVISION_DETECTED"
    POST_VERIFICATION_MUTATION_DETECTED = "POST_VERIFICATION_MUTATION_DETECTED"
    ORPHANED_WORKSPACES_CLEANED = "ORPHANED_WORKSPACES_CLEANED"
    INVARIANT_VALIDATION_FAILED = "INVARIANT_VALIDATION_FAILED"
    DISK_QUOTA_EXCEEDED = "DISK_QUOTA_EXCEEDED"


class WorkspaceExecutionEvent(BaseModel):
    """Timeline event recording progress, actions, and status changes."""

    model_config = ConfigDict(from_attributes=True)

    event_id: str = Field(..., description="Unique UUID for this event.")
    task_id: str = Field(..., description="Task UUID bound to the event.")
    workspace_id: str = Field(..., description="Workspace UUID where event occurred.")
    event_type: WorkspaceExecutionEventType = Field(..., description="Classification of event.")
    timestamp: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    status: WorkspaceStatus = Field(..., description="Workspace status at event emission.")
    message: str = Field(..., description="Human-readable description of the event.")
    payload: dict[str, Any] = Field(default_factory=dict, description="Redacted event metadata.")


class WorkspaceStartExecutionRequest(BaseModel):
    """Request payload to initiate execution in an isolated workspace."""

    task_id: str = Field(..., min_length=1, description="Task identifier to start.")
    approval_token: str | None = Field(default=None, description="Optional human approval token.")
    plan_version: int = Field(default=1, ge=1, description="Approved plan version.")
    approved_base_revision: str | None = Field(
        default=None,
        description="Base revision SHA at approval time for stale-check.",
    )
    task_status: str = Field(
        ...,
        description="Current task status (must be APPROVED to enter execution).",
    )


class WorkspaceStartExecutionResult(BaseModel):
    """Result of starting workspace execution."""

    success: bool
    task_id: str
    workspace_id: str | None = None
    status: WorkspaceStatus
    branch_name: str | None = None
    base_revision: str | None = None
    error: str | None = None
    started_at: str | None = None


# ---------------------------------------------------------------------------
# 8. Command Execution & Tool Policy Schemas (F34, F35)
# ---------------------------------------------------------------------------

class WorkspaceCommandRequest(BaseModel):
    """Request to safely execute an allowlisted command in the workspace."""

    task_id: str = Field(..., min_length=1, description="Task identifier.")
    command: str = Field(..., min_length=1, description="Executable name (e.g. pytest, git, npm).")
    arguments: list[str] = Field(default_factory=list, description="Positional command arguments.")
    timeout_seconds: int | None = Field(default=None, ge=1, le=300, description="Execution timeout.")
    environment: dict[str, str] = Field(default_factory=dict, description="Optional custom env vars.")


class WorkspaceCommandResult(BaseModel):
    """Result of running a command inside the workspace sandbox."""

    success: bool
    command: str
    exit_code: int
    stdout: str = ""
    stderr: str = ""
    duration_ms: float = 0.0
    timed_out: bool = False
    error: str | None = None


class WorkspaceToolPolicyRequest(BaseModel):
    """Tool invocation payload inspected by the policy engine."""

    tool_name: str = Field(..., min_length=1, description="Registered tool name.")
    task_id: str = Field(..., min_length=1, description="Task invoking tool.")
    arguments: dict[str, Any] = Field(default_factory=dict, description="Raw tool arguments.")


class WorkspaceToolPolicyResult(BaseModel):
    """Policy authorization evaluation outcome for a tool request."""

    is_permitted: bool
    tool_name: str
    sanitized_arguments: dict[str, Any] = Field(default_factory=dict)
    violation_reason: str | None = None


# ---------------------------------------------------------------------------
# 9. Test Runner & Bounded Repair Schemas (F35, Docs/week3.md §6, §8 Day 4)
# ---------------------------------------------------------------------------

class TestOutcomeStatus(str, Enum):
    """Normalized test execution outcome."""

    __test__ = False

    PASSED = "PASSED"
    FAILED = "FAILED"
    ERROR = "ERROR"
    TIMEOUT = "TIMEOUT"
    UNSUPPORTED_FRAMEWORK = "UNSUPPORTED_FRAMEWORK"
    AMBIGUOUS = "AMBIGUOUS"
    NO_TESTS_FOUND = "NO_TESTS_FOUND"


class TestFailureClassification(str, Enum):
    """Classification of failure for repair eligibility checks."""

    __test__ = False

    NONE = "NONE"
    TEST_FAILURE = "TEST_FAILURE"  # Assertion error, failing test case -> Eligible for repair
    INFRASTRUCTURE_ERROR = "INFRASTRUCTURE_ERROR"  # Missing dependency, syntax error, runner crash -> Not eligible
    TIMEOUT = "TIMEOUT"  # Exceeded time budget -> Not eligible
    SECURITY_VIOLATION = "SECURITY_VIOLATION"  # Prohibited command or flag -> Not eligible


class WorkspaceTestExecutionRequest(BaseModel):
    """Request payload to execute tests inside the task workspace."""

    task_id: str = Field(..., min_length=1, description="Task identifier.")
    framework: str | None = Field(default=None, description="Explicit test framework (pytest, unittest, jest).")
    test_path: str | None = Field(default=None, description="Optional target test file or directory path.")
    arguments: list[str] = Field(default_factory=list, description="Additional permitted arguments for test runner.")
    timeout_seconds: int | None = Field(default=None, ge=1, le=300, description="Execution timeout.")
    environment: dict[str, str] = Field(default_factory=dict, description="Custom environment variables.")


class WorkspaceTestExecutionResult(BaseModel):
    """Comprehensive test outcome record including counts, logs, and classification."""

    model_config = ConfigDict(from_attributes=True)

    task_id: str
    workspace_id: str | None = None
    success: bool
    status: TestOutcomeStatus
    classification: TestFailureClassification = TestFailureClassification.NONE
    is_repair_eligible: bool = False
    framework: str = "pytest"
    command: str = "pytest"
    arguments: list[str] = Field(default_factory=list)
    exit_code: int = 0
    duration_ms: float = 0.0
    passed_count: int = 0
    failed_count: int = 0
    skipped_count: int = 0
    error_count: int = 0
    total_count: int = 0
    stdout: str = ""
    stderr: str = ""
    failed_test_names: list[str] = Field(default_factory=list)
    failure_details: list[str] = Field(default_factory=list)
    timed_out: bool = False
    error: str | None = None
    workspace_revision: str | None = None
    executed_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


class RepairAttemptRecord(BaseModel):
    """Historical audit record of a self-repair attempt."""

    model_config = ConfigDict(from_attributes=True)

    attempt_number: int = Field(..., ge=1, le=3, description="1-indexed repair attempt number (max 3).")
    task_id: str
    timestamp: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    patch_summary: str = Field(..., description="Summary of applied code patch.")
    patch_hash: str | None = Field(default=None, description="Hash of the patch to prevent duplicate cycles.")
    workspace_revision: str | None = Field(default=None, description="Git commit/worktree SHA after patch.")
    test_status_before: TestOutcomeStatus | None = None
    test_status_after: TestOutcomeStatus | None = None
    success: bool = False


class WorkspaceRepairBudgetStatus(BaseModel):
    """Current repair budget status for a task."""

    task_id: str
    repair_attempts_used: int = Field(default=0, ge=0, description="Number of repair attempts used so far.")
    repair_attempts_max: int = Field(default=3, description="Hard ceiling of task-level repair attempts (ADR-010).")
    is_budget_exhausted: bool = False
    is_eligible_for_repair: bool = True
    last_attempt_at: str | None = None


# ---------------------------------------------------------------------------
# 9. Week 3 Day 5 — Diff Validation, Verification, Commit, Push & Draft PR
# ---------------------------------------------------------------------------

class FileChangeType(str, Enum):
    """Type of file change in unified workspace diff."""

    MODIFIED = "MODIFIED"
    ADDED = "ADDED"
    DELETED = "DELETED"
    RENAMED = "RENAMED"


class FileDiffHunk(BaseModel):
    """A single unified diff hunk within a file diff."""

    old_start: int
    old_lines: int
    new_start: int
    new_lines: int
    lines: list[str] = Field(default_factory=list)


class FileDiffSummary(BaseModel):
    """Structured diff summary for a single file in the workspace."""

    file_path: str
    change_type: FileChangeType = FileChangeType.MODIFIED
    insertions: int = 0
    deletions: int = 0
    patch: str = ""
    hunks: list[FileDiffHunk] = Field(default_factory=list)


class WorkspaceDiffRequest(BaseModel):
    """Request to extract unified git diff from workspace."""

    task_id: str = Field(..., min_length=1)
    base_revision: str | None = Field(default=None)


class WorkspaceDiffResult(BaseModel):
    """Result of extracting and analyzing unified git diff from the workspace."""

    model_config = ConfigDict(from_attributes=True)

    task_id: str
    workspace_id: str | None = None
    base_revision: str
    head_revision: str | None = None
    total_files_changed: int = 0
    insertions: int = 0
    deletions: int = 0
    is_empty: bool = True
    files: list[FileDiffSummary] = Field(default_factory=list)
    raw_diff: str = ""
    extracted_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    error: str | None = None


class SecretScanFinding(BaseModel):
    """Finding when a potential credential or secret token is discovered in code."""

    file_path: str
    line_number: int = 0
    secret_type: str
    redacted_preview: str


class DiffValidationRequest(BaseModel):
    """Request to validate workspace diff against approved task scope."""

    task_id: str = Field(..., min_length=1)
    allowed_files: list[str] | None = Field(default=None)


class DiffValidationResult(BaseModel):
    """Result of independent diff validation against security and boundary rules."""

    model_config = ConfigDict(from_attributes=True)

    task_id: str
    is_valid: bool
    verified_revision: str | None = None
    modified_files: list[str] = Field(default_factory=list)
    unapproved_files: list[str] = Field(default_factory=list)
    deleted_critical_files: list[str] = Field(default_factory=list)
    secret_findings: list[SecretScanFinding] = Field(default_factory=list)
    blocking_findings: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    validated_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


class WorkspaceCommitRequest(BaseModel):
    """Request to stage and commit validated changes on task branch."""

    task_id: str = Field(..., min_length=1)
    message: str = Field(..., min_length=1)
    branch_name: str | None = Field(default=None)
    author_name: str = "Agent"
    author_email: str = "agent@ai-platform.local"
    files: list[str] | None = None


class WorkspaceCommitResult(BaseModel):
    """Outcome of committing task changes to dedicated branch."""

    model_config = ConfigDict(from_attributes=True)

    success: bool
    task_id: str
    commit_sha: str
    branch: str
    message: str
    files_committed: list[str] = Field(default_factory=list)
    author_name: str = "Agent"
    committed_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    error: str | None = None


class WorkspacePushRequest(BaseModel):
    """Request to push task branch to remote origin with authorization gate."""

    task_id: str = Field(..., min_length=1)
    branch_name: str = Field(..., min_length=1)
    remote_name: str = "origin"
    publication_authorized: bool = False
    remote_url: str | None = None


class WorkspacePushResult(BaseModel):
    """Outcome of pushing task branch to remote repository."""

    model_config = ConfigDict(from_attributes=True)

    success: bool
    task_id: str
    branch: str
    pushed_sha: str | None = None
    remote_name: str = "origin"
    pushed_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    error: str | None = None


class WorkspaceDraftPRRequest(BaseModel):
    """Request to synthesize and create GitHub Draft Pull Request."""

    task_id: str = Field(..., min_length=1)
    title: str = Field(..., min_length=1)
    body: str | None = None
    head_branch: str = Field(..., min_length=1)
    base_branch: str = "main"
    draft: bool = True
    repository_owner: str | None = None
    repository_name: str | None = None
    publication_authorized: bool = False


class WorkspaceDraftPRResult(BaseModel):
    """Outcome of opening or formatting GitHub Draft Pull Request."""

    model_config = ConfigDict(from_attributes=True)

    success: bool
    task_id: str
    pr_number: int | None = None
    pr_url: str | None = None
    head_branch: str
    base_branch: str
    is_draft: bool = True
    summary: str = ""
    created_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    error: str | None = None


# ---------------------------------------------------------------------------
# 11. Day 6 Reliability, Security & Failure Recovery Schemas (Docs/week3.md §8 Day 6)
# ---------------------------------------------------------------------------

class StaleRevisionCheckRequest(BaseModel):
    """Request to detect whether repository base revision has drifted."""

    task_id: str = Field(..., description="Task UUID.")
    current_remote_sha: str = Field(..., description="Latest commit SHA from remote head.")

    @field_validator("current_remote_sha")
    @classmethod
    def _validate_sha(cls, value: str) -> str:
        clean = (value or "").strip()
        if not _COMMIT_SHA_RE.match(clean):
            raise ValueError(f"Invalid remote commit SHA: {clean}")
        return clean


class StaleRevisionCheckResult(BaseModel):
    """Outcome of stale base revision verification."""

    model_config = ConfigDict(from_attributes=True, extra="allow")

    task_id: str = ""
    is_stale: bool = False
    workspace_base_revision: str = ""
    current_base_revision: str = ""
    current_remote_sha: str = ""
    commits_behind: int = 0
    remote_head: str | None = None
    remediation_suggestion: str | None = None
    message: str = ""
    checked_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    @model_validator(mode="before")
    @classmethod
    def _sync_base_revision(cls, data: Any) -> Any:
        if isinstance(data, dict):
            if "current_base_revision" in data and not data.get("workspace_base_revision"):
                data["workspace_base_revision"] = data["current_base_revision"]
            elif "workspace_base_revision" in data and not data.get("current_base_revision"):
                data["current_base_revision"] = data["workspace_base_revision"]
        return data


class DiffImmutabilityCheckRequest(BaseModel):
    """Request to verify that diff has not mutated after independent verification."""

    task_id: str = Field(..., description="Task UUID.")
    expected_diff_hash: str = Field(..., description="SHA-256 hash of verified diff.")


class DiffImmutabilityCheckResult(BaseModel):
    """Outcome of post-verification diff immutability check."""

    model_config = ConfigDict(from_attributes=True, extra="allow")

    task_id: str
    immutable: bool = True
    is_immutable: bool = True
    expected_diff_hash: str
    current_diff_hash: str
    verified_diff_hash: str = ""
    message: str = ""
    error_message: str | None = None
    checked_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    @model_validator(mode="before")
    @classmethod
    def _sync_immutable(cls, data: Any) -> Any:
        if isinstance(data, dict):
            if "is_immutable" in data and "immutable" not in data:
                data["immutable"] = data["is_immutable"]
            elif "immutable" in data and "is_immutable" not in data:
                data["is_immutable"] = data["immutable"]
            if "expected_diff_hash" in data and not data.get("verified_diff_hash"):
                data["verified_diff_hash"] = data["expected_diff_hash"]
            elif "verified_diff_hash" in data and not data.get("expected_diff_hash"):
                data["expected_diff_hash"] = data["verified_diff_hash"]
        return data


class WorkspaceRecoveryRecord(BaseModel):
    """Record of a single recovered workspace after worker crash or restart."""

    model_config = ConfigDict(from_attributes=True, extra="allow")

    task_id: str
    previous_status: WorkspaceStatus
    recovered_status: WorkspaceStatus
    new_status: WorkspaceStatus | None = None
    reconciliation_action: str = ""
    details: str = ""
    recovered_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    @model_validator(mode="before")
    @classmethod
    def _sync_recovery(cls, data: Any) -> Any:
        if isinstance(data, dict):
            if "recovered_status" in data and not data.get("new_status"):
                data["new_status"] = data["recovered_status"]
            elif "new_status" in data and not data.get("recovered_status"):
                data["recovered_status"] = data["new_status"]
            if "details" in data and not data.get("reconciliation_action"):
                data["reconciliation_action"] = data["details"]
            elif "reconciliation_action" in data and not data.get("details"):
                data["details"] = data["reconciliation_action"]
        return data


class WorkspaceRecoveryResult(BaseModel):
    """Summary of bulk workspace state recovery across worker restart."""

    model_config = ConfigDict(from_attributes=True)

    total_scanned: int = 0
    recovered_count: int = 0
    failed_count: int = 0
    unmodified_count: int = 0
    records: list[WorkspaceRecoveryRecord] = Field(default_factory=list)


class WorkspaceOrphanCleanupResult(BaseModel):
    """Summary of orphaned workspace sweeping."""

    model_config = ConfigDict(from_attributes=True)

    total_scanned: int = 0
    cleaned_count: int = 0
    failed_count: int = 0
    cleaned_task_ids: list[str] = Field(default_factory=list)
    candidate_paths: list[str] = Field(default_factory=list)
    duration_ms: float = 0.0


class WorkspaceInvariantCheckResult(BaseModel):
    """Outcome of workspace state, storage, and security invariant validation."""

    model_config = ConfigDict(from_attributes=True)

    task_id: str
    valid: bool
    violations: list[str] = Field(default_factory=list)
    checked_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    @property
    def is_valid(self) -> bool:
        return self.valid


class WorkspaceDiskUsageResult(BaseModel):
    """Workspace storage budget telemetry."""

    model_config = ConfigDict(from_attributes=True)

    task_id: str
    disk_usage_bytes: int
    max_disk_bytes: int
    within_budget: bool
    file_count: int
    error_message: str | None = None

    @property
    def is_exceeded(self) -> bool:
        return not self.within_budget

    @property
    def total_bytes(self) -> int:
        return self.disk_usage_bytes

    @property
    def total_files(self) -> int:
        return self.file_count


__all__ = [
    "DiffImmutabilityCheckRequest",
    "DiffImmutabilityCheckResult",
    "DiffValidationRequest",
    "DiffValidationResult",
    "FileChangeType",
    "FileDiffHunk",
    "FileDiffSummary",
    "RepairAttemptRecord",
    "SecretScanFinding",
    "StaleRevisionCheckRequest",
    "StaleRevisionCheckResult",
    "TestFailureClassification",
    "TestOutcomeStatus",
    "VALID_WORKSPACE_TRANSITIONS",
    "WorkspaceCleanupResult",
    "WorkspaceCommandRequest",
    "WorkspaceCommandResult",
    "WorkspaceCommitRequest",
    "WorkspaceCommitResult",
    "WorkspaceCreateRequest",
    "WorkspaceCreateResult",
    "WorkspaceDiffRequest",
    "WorkspaceDiffResult",
    "WorkspaceDiskUsageResult",
    "WorkspaceDraftPRRequest",
    "WorkspaceDraftPRResult",
    "WorkspaceExecutionEvent",
    "WorkspaceExecutionEventType",
    "WorkspaceFilePatchRequest",
    "WorkspaceFilePatchResult",
    "WorkspaceFileReadRequest",
    "WorkspaceFileReadResult",
    "WorkspaceFileWriteRequest",
    "WorkspaceFileWriteResult",
    "WorkspaceInvariantCheckResult",
    "WorkspaceIsolationType",
    "WorkspaceMetadata",
    "WorkspaceOrphanCleanupResult",
    "WorkspacePushRequest",
    "WorkspacePushResult",
    "WorkspaceRecoveryRecord",
    "WorkspaceRecoveryResult",
    "WorkspaceRepairBudgetStatus",
    "WorkspaceResourceLimits",
    "WorkspaceStartExecutionRequest",
    "WorkspaceStartExecutionResult",
    "WorkspaceStatus",
    "WorkspaceTestExecutionRequest",
    "WorkspaceTestExecutionResult",
    "WorkspaceToolPolicyRequest",
    "WorkspaceToolPolicyResult",
    "can_transition_workspace",
]

