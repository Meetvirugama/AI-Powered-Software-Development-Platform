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

    model_config = ConfigDict(from_attributes=True)

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
    cleaned_at: str | None = Field(default=None)
    error_message: str | None = Field(default=None)

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
        default="APPROVED",
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


__all__ = [
    "VALID_WORKSPACE_TRANSITIONS",
    "WorkspaceCleanupResult",
    "WorkspaceCommandRequest",
    "WorkspaceCommandResult",
    "WorkspaceCreateRequest",
    "WorkspaceCreateResult",
    "WorkspaceExecutionEvent",
    "WorkspaceExecutionEventType",
    "WorkspaceFilePatchRequest",
    "WorkspaceFilePatchResult",
    "WorkspaceFileReadRequest",
    "WorkspaceFileReadResult",
    "WorkspaceFileWriteRequest",
    "WorkspaceFileWriteResult",
    "WorkspaceIsolationType",
    "WorkspaceMetadata",
    "WorkspaceResourceLimits",
    "WorkspaceStartExecutionRequest",
    "WorkspaceStartExecutionResult",
    "WorkspaceStatus",
    "WorkspaceToolPolicyRequest",
    "WorkspaceToolPolicyResult",
    "can_transition_workspace",
]

