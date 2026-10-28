"""Task Intake & Lifecycle Schemas.

Owner: Dev & Yug — Week 3 Day 1–2 Deliverable (Docs/daily_tasks.md & Docs/week3.md §7)
Reference: Docs/week3.md §7.1 (Task Lifecycle), §7.2 (State Transitions), §7.3 (Common Task Response)

Responsibilities:
1. Define TaskStatus state machine enum and transition validation rules.
2. Segregate task intake elements into requirements, assumptions, and constraints.
3. Validate repository-relative paths and prevent path traversal escapes.
4. Provide structured source references connecting tasks to GitHub issues, bug findings, or reviews.
5. Provide canonical task creation requests and task detail response models.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.core.input_security import UnsafePathError, validate_repo_relative_path
from app.core.secret_redaction import redact

_HTTP_URL_RE = re.compile(r"^https?://[^\s/$.?#].[^\s]*$", re.IGNORECASE)
_COMMIT_SHA_RE = re.compile(r"^[0-9a-fA-F]{7,64}$")
_SAFE_GIT_REF_RE = re.compile(r"^[A-Za-z0-9._/-]{1,128}$")


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
        # Approved plan can enter WORKSPACE_SETUP/EXECUTING, or be re-planned if revised (which invalidates approval)
        {TaskStatus.WORKSPACE_SETUP, TaskStatus.EXECUTING, TaskStatus.PLANNING, TaskStatus.CANCELLED, TaskStatus.BLOCKED}
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

    model_config = ConfigDict(populate_by_name=True, extra="ignore")

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
        description="Alias for issue_url matching Docs/week3.md §6 F31 example.",
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

    @model_validator(mode="before")
    @classmethod
    def _sync_url_fields(cls, data: Any) -> Any:
        if isinstance(data, dict):
            d = dict(data)
            if d.get("url") and not d.get("issue_url"):
                d["issue_url"] = d["url"]
            elif d.get("issue_url") and not d.get("url"):
                d["url"] = d["issue_url"]
            return d
        return data

    @field_validator("issue_url", "url")
    @classmethod
    def _validate_issue_url(cls, value: str | None) -> str | None:
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

    @field_validator("description")
    @classmethod
    def _redact_description(cls, value: str) -> str:
        cleaned = redact(value.strip())
        if not cleaned:
            raise ValueError("Requirement description must not be empty.")
        return cleaned

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

    @field_validator("description")
    @classmethod
    def _redact_description(cls, value: str) -> str:
        return redact(value.strip())


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
        description="Git commit SHA or branch ref to branch from. If omitted, uses default branch HEAD.",
    )

    @field_validator("title")
    @classmethod
    def _validate_title_not_blank(cls, value: str) -> str:
        cleaned = redact(value.strip())
        if not cleaned:
            raise ValueError("Task title must contain non-whitespace characters.")
        return cleaned

    @field_validator("description")
    @classmethod
    def _validate_and_redact_description(cls, value: str) -> str:
        cleaned = redact(value.strip())
        if not cleaned:
            raise ValueError("Task description must contain non-whitespace characters.")
        return cleaned

    @field_validator("base_revision")
    @classmethod
    def _validate_base_revision(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        if not cleaned:
            return None
        if (
            cleaned.startswith("-")
            or ".." in cleaned
            or "\x00" in cleaned
            or not (_COMMIT_SHA_RE.match(cleaned) or _SAFE_GIT_REF_RE.match(cleaned))
        ):
            raise ValueError(f"Invalid base_revision format: '{value}'")
        return cleaned

    @model_validator(mode="after")
    def _validate_constraint_disjointness(self) -> "TaskIntakePayload":
        """Ensure target files in requirements are not listed in forbidden_files constraints (case-insensitive)."""
        forbidden_map: dict[str, str] = {}
        for c in self.constraints:
            for f_path in c.forbidden_files:
                forbidden_map[f_path.lower()] = f_path

        for req in self.requirements:
            overlaps: list[str] = []
            for t_path in req.target_files:
                if t_path.lower() in forbidden_map:
                    overlaps.append(t_path)
            if overlaps:
                raise ValueError(
                    f"Requirement '{req.id}' targets forbidden file(s): {', '.join(sorted(set(overlaps)))}"
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
    source_type: TaskSourceType = Field(default="USER_PROMPT")
    source: TaskSourceReference
    requirements: list[TaskRequirement]
    assumptions: list[TaskAssumption] = Field(default_factory=list)
    constraints: list[TaskConstraint] = Field(default_factory=list)
    base_revision: str | None = None
    plan_version: int = Field(default=1, ge=1)
    approved_plan_version: int | None = None
    repair_attempts_used: int = Field(default=0, ge=0)
    repair_attempts_max: int = Field(default=3, ge=1, le=5)
    latest_plan: dict[str, Any] | None = None
    approvals: list[dict[str, Any]] = Field(default_factory=list)
    created_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    updated_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    @model_validator(mode="after")
    def _sync_source_type(self) -> "TaskDetailResponse":
        if self.source and self.source.type:
            self.source_type = self.source.type
        return self


class TaskSummaryResponse(BaseModel):
    """Compact summary item for task list views (Docs/week3.md §6 F38 & §7.3)."""

    task_id: str
    repository_id: str
    title: str
    status: TaskStatus
    source_type: TaskSourceType
    source: TaskSourceReference
    base_revision: str | None = None
    plan_version: int = 1
    approved_plan_version: int | None = None
    repair_attempts_used: int = 0
    repair_attempts_max: int = 3
    created_at: str
    updated_at: str


class PaginatedTaskListResponse(BaseModel):
    """Paginated task list response."""

    items: list[TaskSummaryResponse] = Field(default_factory=list)
    total: int = 0
    page: int = 1
    page_size: int = 20


__all__ = [
    "PaginatedTaskListResponse",
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
    "TaskSummaryResponse",
    "VALID_TASK_TRANSITIONS",
    "can_transition",
]
