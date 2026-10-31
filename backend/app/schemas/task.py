"""Task Intake & Lifecycle Schemas.

Owner: Dev (Task Intake & Lifecycle) & Om (Persistence, Workflows & Recovery).
Reference: Docs/week3.md §7.1 (Task Lifecycle), §7.2 (State Transitions), §7.3 (Common Task Response)

Responsibilities:
1. Define TaskStatus state machine enum and transition validation rules.
2. Segregate task intake elements into requirements, assumptions, and constraints.
3. Validate repository-relative paths and prevent path traversal escapes.
4. Provide structured source references connecting tasks to GitHub issues, bug findings, or reviews.
5. Provide canonical task creation requests and task detail response models.
6. Provide plan proposals, step models, approval payloads, and recovery checkpoint schemas.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from enum import Enum
from typing import Any, List, Literal, Optional
from uuid import UUID

from pydantic import BaseModel, Field, field_validator, model_validator

from app.core.input_security import UnsafePathError, validate_repo_relative_path

_HTTP_URL_RE = re.compile(r"^https?://[^\s/$.?#].[^\s]*$", re.IGNORECASE)
_COMMIT_SHA_RE = re.compile(r"^[0-9a-fA-F]{7,64}$")


# ---------------------------------------------------------------------------
# 1. Task Lifecycle State Machine (Docs/week3.md §7.1)
# ---------------------------------------------------------------------------

class TaskStatus(str, Enum):
    """Canonical task lifecycle states matching Docs/week3.md §7.1."""

    CREATED = "CREATED"
    PLANNING = "PLANNING"
    PENDING_APPROVAL = "PENDING_APPROVAL"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    WORKSPACE_SETUP = "WORKSPACE_SETUP"
    EXECUTING = "EXECUTING"
    TESTING = "TESTING"
    REPAIRING = "REPAIRING"
    VERIFYING = "VERIFYING"
    READY_FOR_PUBLICATION = "READY_FOR_PUBLICATION"
    PUBLISHING = "PUBLISHING"
    DRAFT_PR_CREATED = "DRAFT_PR_CREATED"

    # Terminal / Exceptional states
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    RECOVERY_REQUIRED = "RECOVERY_REQUIRED"
    BLOCKED = "BLOCKED"


# Explicit state transition graph per Docs/week3.md §7.2
VALID_TASK_TRANSITIONS: dict[TaskStatus, frozenset[TaskStatus]] = {
    TaskStatus.CREATED: frozenset(
        {TaskStatus.PLANNING, TaskStatus.CANCELLED, TaskStatus.FAILED, TaskStatus.BLOCKED}
    ),
    TaskStatus.PLANNING: frozenset(
        {TaskStatus.PENDING_APPROVAL, TaskStatus.FAILED, TaskStatus.CANCELLED, TaskStatus.BLOCKED}
    ),
    TaskStatus.PENDING_APPROVAL: frozenset(
        # PENDING_APPROVAL CANNOT transition directly to EXECUTING (Docs/week3.md §7.2)
        {TaskStatus.APPROVED, TaskStatus.REJECTED, TaskStatus.PLANNING, TaskStatus.CANCELLED}
    ),
    TaskStatus.APPROVED: frozenset(
        {TaskStatus.WORKSPACE_SETUP, TaskStatus.EXECUTING, TaskStatus.CANCELLED, TaskStatus.BLOCKED}
    ),
    TaskStatus.REJECTED: frozenset(
        # Rejected plan can be re-planned, cancelled, or closed; never directly executed
        {TaskStatus.PLANNING, TaskStatus.CANCELLED}
    ),
    TaskStatus.WORKSPACE_SETUP: frozenset(
        {TaskStatus.EXECUTING, TaskStatus.FAILED, TaskStatus.CANCELLED, TaskStatus.BLOCKED}
    ),
    TaskStatus.EXECUTING: frozenset(
        {TaskStatus.TESTING, TaskStatus.FAILED, TaskStatus.CANCELLED, TaskStatus.BLOCKED, TaskStatus.RECOVERY_REQUIRED}
    ),
    TaskStatus.TESTING: frozenset(
        {TaskStatus.VERIFYING, TaskStatus.REPAIRING, TaskStatus.FAILED, TaskStatus.CANCELLED, TaskStatus.BLOCKED}
    ),
    TaskStatus.REPAIRING: frozenset(
        {TaskStatus.TESTING, TaskStatus.FAILED, TaskStatus.BLOCKED, TaskStatus.CANCELLED}
    ),
    TaskStatus.VERIFYING: frozenset(
        {TaskStatus.READY_FOR_PUBLICATION, TaskStatus.FAILED, TaskStatus.BLOCKED, TaskStatus.CANCELLED}
    ),
    TaskStatus.READY_FOR_PUBLICATION: frozenset(
        {TaskStatus.PUBLISHING, TaskStatus.CANCELLED, TaskStatus.BLOCKED}
    ),
    TaskStatus.PUBLISHING: frozenset(
        {TaskStatus.DRAFT_PR_CREATED, TaskStatus.FAILED, TaskStatus.BLOCKED}
    ),
    TaskStatus.DRAFT_PR_CREATED: frozenset(),  # Terminal happy path
    TaskStatus.FAILED: frozenset({TaskStatus.RECOVERY_REQUIRED, TaskStatus.PLANNING}),
    TaskStatus.CANCELLED: frozenset(),  # Terminal
    TaskStatus.RECOVERY_REQUIRED: frozenset(
        {TaskStatus.PLANNING, TaskStatus.APPROVED, TaskStatus.WORKSPACE_SETUP, TaskStatus.FAILED, TaskStatus.CANCELLED}
    ),
    TaskStatus.BLOCKED: frozenset(
        {TaskStatus.PLANNING, TaskStatus.PENDING_APPROVAL, TaskStatus.CANCELLED}
    ),
}


def can_transition(current: TaskStatus, target: TaskStatus) -> bool:
    """Return True if transitioning from `current` to `target` is permitted by policy."""
    if current == target:
        return True
    return target in VALID_TASK_TRANSITIONS.get(current, frozenset())


# ---------------------------------------------------------------------------
# 2. Task Source Reference
# ---------------------------------------------------------------------------

TaskSourceType = Literal["GITHUB_ISSUE", "BUG_FINDING", "REVIEW_FINDING", "USER_PROMPT"]


class TaskSourceReference(BaseModel):
    """Traceability link connecting task to GitHub issues or Week 2 findings."""

    type: TaskSourceType = Field(
        ...,
        description="Source type: GITHUB_ISSUE, BUG_FINDING, REVIEW_FINDING, or USER_PROMPT.",
    )
    issue_number: int | None = Field(
        default=None,
        ge=1,
        le=1_000_000,
        description="GitHub issue number when type='GITHUB_ISSUE'.",
    )
    issue_url: str | None = Field(
        default=None,
        max_length=2048,
        description="HTTP URL for the imported GitHub issue.",
    )
    url: str | None = Field(
        default=None,
        max_length=2048,
        description="Direct URL alias for imported issue or finding.",
    )
    finding_id: str | None = Field(
        default=None,
        max_length=128,
        description="Week 2 BugFinding.id or ReviewFinding.id when type is a finding.",
    )
    repository_id: str | None = Field(
        default=None,
        description="UUID string of the target repository.",
    )
    base_revision: str | None = Field(
        default=None,
        max_length=128,
        description="Git commit SHA from which the task branches.",
    )

    @field_validator("issue_url", "url")
    @classmethod
    def _validate_url(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if not _HTTP_URL_RE.match(value):
            raise ValueError(f"Invalid issue URL format: '{value}'")
        return value

    @field_validator("base_revision")
    @classmethod
    def _validate_base_revision(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if not _COMMIT_SHA_RE.match(value):
            raise ValueError(f"Invalid base_revision commit SHA format: '{value}'")
        return value


# ---------------------------------------------------------------------------
# 3. Segregated Task Intake Elements (Requirements, Assumptions, Constraints)
# ---------------------------------------------------------------------------

TaskRequirementCategory = Literal["functional", "bug_fix", "refactor", "security", "test"]


class TaskRequirement(BaseModel):
    """A concrete functional requirement or defect resolution objective."""

    id: str = Field(..., min_length=1, max_length=64, description="Requirement identifier, e.g. 'req-1'.")
    description: str = Field(..., min_length=1, description="What must be built, changed, or fixed.")
    category: TaskRequirementCategory = Field(default="functional")
    target_files: list[str] = Field(
        default_factory=list,
        description="Expected repository-relative file paths for this requirement.",
    )
    acceptance_criteria: list[str] = Field(
        default_factory=list,
        description="Conditions that must pass for this requirement to be satisfied.",
    )

    @field_validator("target_files")
    @classmethod
    def _validate_target_files(cls, files: list[str]) -> list[str]:
        validated: list[str] = []
        for path in files:
            try:
                validated.append(validate_repo_relative_path(path))
            except UnsafePathError as exc:
                raise ValueError(f"Unsafe target_file '{path}': {exc}") from exc
        return validated


class TaskAssumption(BaseModel):
    """An environment, dependency, or architectural assumption."""

    id: str = Field(..., min_length=1, max_length=64, description="Assumption identifier, e.g. 'asm-1'.")
    description: str = Field(..., min_length=1, description="What is assumed about existing code or behavior.")
    unresolved: bool = Field(
        default=False,
        description="True if human confirmation is required during plan approval.",
    )
    risk_level: Literal["low", "medium", "high"] = Field(
        default="low",
        description="Risk of failure if assumption proves false.",
    )


TaskConstraintType = Literal[
    "protected_file",
    "forbidden_dependency",
    "backward_compatibility",
    "resource_limit",
    "security_policy",
]


class TaskConstraint(BaseModel):
    """Non-negotiable boundaries, forbidden files, and policy constraints."""

    id: str = Field(..., min_length=1, max_length=64, description="Constraint identifier, e.g. 'cst-1'.")
    description: str = Field(..., min_length=1, description="Policy boundary or forbidden action.")
    constraint_type: TaskConstraintType = Field(...)
    forbidden_files: list[str] = Field(
        default_factory=list,
        description="Repository-relative file paths that MUST NOT be modified.",
    )
    forbidden_packages: list[str] = Field(
        default_factory=list,
        description="External package names that MUST NOT be added.",
    )
    max_budget_tokens: int | None = Field(
        default=20000,
        ge=500,
        le=100000,
        description="Token budget cap for agent planning and execution.",
    )

    @field_validator("forbidden_files")
    @classmethod
    def _validate_forbidden_files(cls, files: list[str]) -> list[str]:
        validated: list[str] = []
        for path in files:
            try:
                validated.append(validate_repo_relative_path(path))
            except UnsafePathError as exc:
                raise ValueError(f"Unsafe forbidden_file '{path}': {exc}") from exc
        return validated


# ---------------------------------------------------------------------------
# 4. Task Intake Request & Detail Envelope
# ---------------------------------------------------------------------------

class TaskIntakePayload(BaseModel):
    """Validated task intake payload separating requirements, assumptions, and constraints."""

    repository_id: UUID = Field(..., description="Target repository ID.")
    title: str = Field(..., min_length=3, max_length=256, description="Concise task title.")
    description: str = Field(..., min_length=1, description="Detailed problem or requirement statement.")
    source: TaskSourceReference = Field(..., description="Originating source metadata.")
    requirements: list[TaskRequirement] = Field(
        ...,
        min_length=1,
        description="List of functional requirements. At least one requirement is mandatory.",
    )
    assumptions: list[TaskAssumption] = Field(
        default_factory=list,
        description="Explicit technical and environment assumptions.",
    )
    constraints: list[TaskConstraint] = Field(
        default_factory=list,
        description="Non-negotiable security boundaries and forbidden files/dependencies.",
    )
    base_revision: str | None = Field(
        default=None,
        description="Git commit SHA to branch from. If omitted, uses default branch HEAD.",
    )

    @field_validator("title")
    @classmethod
    def _validate_title_not_blank(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("Task title must contain non-whitespace characters.")
        return cleaned

    @model_validator(mode="after")
    def _validate_constraint_disjointness(self) -> "TaskIntakePayload":
        """Ensure target files in requirements are not listed in forbidden_files constraints."""
        forbidden_set: set[str] = set()
        for c in self.constraints:
            forbidden_set.update(c.forbidden_files)

        for req in self.requirements:
            overlap = set(req.target_files).intersection(forbidden_set)
            if overlap:
                raise ValueError(
                    f"Requirement '{req.id}' targets forbidden file(s): {', '.join(sorted(overlap))}"
                )
        return self


# Canonical alias for API routes
TaskCreateRequest = TaskIntakePayload


class TaskDetailResponse(BaseModel):
    """Canonical task response envelope matching Docs/week3.md §7.3."""

    task_id: str = Field(..., description="Unique task identifier.")
    repository_id: str = Field(..., description="Target repository UUID.")
    title: str
    description: str
    status: TaskStatus = Field(default=TaskStatus.CREATED)
    source: TaskSourceReference
    requirements: list[TaskRequirement]
    assumptions: list[TaskAssumption] = Field(default_factory=list)
    constraints: list[TaskConstraint] = Field(default_factory=list)
    base_revision: str | None = None
    plan_version: int = Field(default=1, ge=1)
    approved_plan_version: int | None = None
    repair_attempts_used: int = Field(default=0, ge=0)
    repair_attempts_max: int = Field(default=3, ge=1, le=5)
    created_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    updated_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


# ---------------------------------------------------------------------------
# 5. Workflow Automation, Plans, Approvals & Recovery Schemas
# ---------------------------------------------------------------------------

class TaskResponse(BaseModel):
    """Canonical task response envelope for database and persistence operations."""

    task_id: str
    repository_id: str
    user_id: Optional[str] = None
    title: str
    description: Optional[str] = None
    status: str
    source_type: str
    source_id: Optional[str] = None
    source_metadata: Optional[dict[str, Any]] = None
    finding_id: Optional[str] = None
    base_revision: str
    plan_version: int
    approved_plan_version: Optional[int] = None
    repair_attempts_used: int
    repair_attempts_max: int
    context_summary: Optional[str] = None
    error_message: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class TaskListResponse(BaseModel):
    """Paginated task list envelope."""

    tasks: List[TaskResponse]
    total: int
    offset: int
    limit: int


class TaskPlanStep(BaseModel):
    """Single ordered step within an implementation plan."""

    step_id: str = Field(..., description="Unique step identifier (e.g. step_1)")
    description: str = Field(..., description="Clear explanation of the change to be made")
    expected_files: List[str] = Field(default_factory=list, description="Files to inspect or modify")
    verification: List[str] = Field(default_factory=list, description="Verification criteria for this step")


class TaskPlanCreateRequest(BaseModel):
    """Request to propose or revise an implementation plan."""

    summary: str = Field(..., max_length=512, description="High-level plan summary")
    problem_statement: Optional[str] = Field(None, description="Problem breakdown")
    steps: List[TaskPlanStep] = Field(..., min_length=1, description="Ordered implementation steps")
    expected_files: Optional[List[str]] = Field(None, description="All files expected to be changed")
    tests_to_run: Optional[List[str]] = Field(None, description="Target tests to execute")
    validation_strategy: Optional[str] = Field(None, description="Verification and safety strategy")
    risks: Optional[List[str]] = Field(None, description="Identified risks or side effects")
    base_revision: Optional[str] = Field(None, description="Target base revision")


class TaskPlanResponse(BaseModel):
    """Structured implementation plan response."""

    plan_id: str
    task_id: str
    version: int
    base_revision: str
    summary: str
    problem_statement: Optional[str] = None
    steps: List[dict[str, Any]]
    expected_files: Optional[List[str]] = None
    tests_to_run: Optional[List[str]] = None
    validation_strategy: Optional[str] = None
    risks: Optional[List[str]] = None
    status: str
    created_at: Optional[str] = None


class TaskApprovalRequest(BaseModel):
    """Request to approve or reject a plan version."""

    plan_version: int = Field(..., ge=1, description="The exact plan version being decided")
    feedback: Optional[str] = Field(None, description="Optional feedback or rejection reason")


class TaskApprovalResponse(BaseModel):
    """Immutable task approval outcome."""

    approval_id: str
    task_id: str
    plan_version: int
    user_id: Optional[str] = None
    decision: str
    feedback: Optional[str] = None
    created_at: Optional[str] = None


class TaskCheckpointResponse(BaseModel):
    """Sanitized checkpoint for worker failure recovery."""

    checkpoint_id: str
    task_id: str
    step_name: str
    state_data: dict[str, Any]
    recovery_instructions: Optional[str] = None
    created_at: Optional[str] = None


class TaskEventResponse(BaseModel):
    """Ordered event item for dashboard timeline."""

    event_id: str
    task_id: str
    event_type: str
    event_data: Optional[dict[str, Any]] = None
    user_id: Optional[str] = None
    created_at: Optional[str] = None


class VerificationResultResponse(BaseModel):
    """Independent verification check outcome."""

    verification_id: str
    task_id: str
    verified_revision: str
    status: str
    checks: Optional[List[dict[str, Any]]] = None
    blocking_findings: Optional[List[dict[str, Any]]] = None
    warnings: Optional[List[dict[str, Any]]] = None
    summary: Optional[str] = None
    created_at: Optional[str] = None


class TaskPullRequestResponse(BaseModel):
    """Created GitHub Draft PR details."""

    pr_id: str
    task_id: str
    repository_id: str
    pr_number: Optional[int] = None
    pr_url: str
    base_branch: str
    head_branch: str
    head_sha: str
    is_draft: bool
    title: str
    body: Optional[str] = None
    created_at: Optional[str] = None


__all__ = [
    # Dev (Intake & Lifecycle)
    "TaskAssumption",
    "TaskConstraint",
    "TaskConstraintType",
    "TaskCreateRequest",
    "TaskDetailResponse",
    "TaskIntakePayload",
    "TaskRequirement",
    "TaskRequirementCategory",
    "TaskSourceReference",
    "TaskSourceType",
    "TaskStatus",
    "VALID_TASK_TRANSITIONS",
    "can_transition",
    # Om (Workflows & Recovery)
    "TaskResponse",
    "TaskListResponse",
    "TaskPlanStep",
    "TaskPlanCreateRequest",
    "TaskPlanResponse",
    "TaskApprovalRequest",
    "TaskApprovalResponse",
    "TaskCheckpointResponse",
    "TaskEventResponse",
    "VerificationResultResponse",
    "TaskPullRequestResponse",
]
