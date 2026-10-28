"""Week 3 Day 1 & Day 2 Schemas: GitHub Issue Integration, Task Planner & Human Approval Gate.

Owners:
- Parth & Yug (F31 GitHub Issue Integration contracts)
- Meet & Dev (F32 TaskPlanner & PlannerSchema with DAG step dependency validation)
- Sukun (Approval gate & plan hash verification contracts)
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.core.input_security import UnsafePathError, validate_repo_relative_path
from app.core.secret_redaction import redact
from app.schemas.task import TaskAssumption, TaskSourceReference, TaskStatus

_COMMIT_SHA_OR_REF_RE = re.compile(r"^[A-Za-z0-9._/-]{1,128}$")


# ---------------------------------------------------------------------------
# 1. F31 — GitHub Issue Integration Schemas (Docs/week3.md §6 F31)
# ---------------------------------------------------------------------------

class GitHubIssueImportRequest(BaseModel):
    """Request payload for POST /api/v1/repositories/{repository_id}/issues/import."""

    issue_number: int = Field(..., ge=1, le=1_000_000, description="GitHub issue number to import.")
    base_revision: str | None = Field(
        default=None,
        description="Optional base commit SHA or branch ref for the imported task.",
    )
    title: str | None = Field(
        default=None,
        max_length=256,
        description="Optional fallback issue title when importing in offline/local mode.",
    )
    body: str | None = Field(
        default=None,
        max_length=50_000,
        description="Optional fallback issue body when importing in offline/local mode.",
    )
    labels: list[str] = Field(
        default_factory=list,
        description="Optional issue labels.",
    )


class GitHubIssueCreateRequest(BaseModel):
    """Request payload for POST /api/v1/repositories/{repository_id}/issues."""

    finding_id: UUID | str | None = Field(
        default=None,
        description="Optional Week 2 AnalysisFinding ID (bug or review finding) to convert into an issue.",
    )
    title: str | None = Field(
        default=None,
        min_length=3,
        max_length=256,
        description="Issue title (auto-generated from finding if finding_id is provided).",
    )
    body: str | None = Field(
        default=None,
        max_length=50_000,
        description="Issue body markdown (auto-generated from finding if finding_id is provided).",
    )
    labels: list[str] = Field(
        default_factory=list,
        description="Labels to attach to the created GitHub issue (e.g. ['bug', 'ai-finding']).",
    )
    create_task: bool = Field(
        default=True,
        description="If True, also normalizes the created issue into an internal development task.",
    )

    @field_validator("title")
    @classmethod
    def _clean_title(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = redact(value.strip())
        if len(cleaned) < 3:
            raise ValueError("Issue title must be at least 3 characters.")
        return cleaned

    @field_validator("body")
    @classmethod
    def _clean_body(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return redact(value.strip())

    @field_validator("labels")
    @classmethod
    def _clean_labels(cls, labels: list[str]) -> list[str]:
        cleaned: list[str] = []
        for lbl in labels[:20]:
            s = lbl.strip()
            if s and len(s) <= 64:
                cleaned.append(s)
        return list(dict.fromkeys(cleaned))


class GitHubIssueResponse(BaseModel):
    """Normalized GitHub issue record returned by the API."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    repository_id: str
    issue_number: int
    title: str
    body: str = ""
    state: str = "open"
    labels: list[str] = Field(default_factory=list)
    html_url: str
    author: str | None = None
    origin_finding_id: str | None = None
    task_id: str | None = None
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class IssueImportResponse(BaseModel):
    """Normalized response for issue import & issue creation (Docs/week3.md §6 F31)."""

    task_id: str
    repository_id: str
    source: TaskSourceReference
    title: str
    status: TaskStatus = TaskStatus.CREATED
    issue: GitHubIssueResponse
    duplicate_reused: bool = False


# ---------------------------------------------------------------------------
# 2. F32 — Task Planner & Structured Implementation Plan Schemas
# ---------------------------------------------------------------------------

PlanStepActionType = Literal[
    "inspect",
    "modify",
    "create",
    "delete",
    "test",
    "verify",
]

PlanRiskSeverity = Literal["low", "medium", "high", "critical"]


class PlanStep(BaseModel):
    """A single ordered implementation step in a structured task plan (Docs/week3.md §6 F32)."""

    step_id: str = Field(
        ...,
        min_length=1,
        max_length=64,
        description="Unique step identifier within the plan, e.g. 'step_1'.",
    )
    title: str = Field(
        default="",
        max_length=256,
        description="Concise step title.",
    )
    description: str = Field(
        ...,
        min_length=1,
        description="Detailed explanation of the implementation action for this step.",
    )
    action_type: PlanStepActionType = Field(
        default="modify",
        description="Step category: inspect, modify, create, delete, test, or verify.",
    )
    expected_files: list[str] = Field(
        default_factory=list,
        description="Repository-relative file paths read or modified during this step.",
    )
    target_symbols: list[str] = Field(
        default_factory=list,
        description="Functions, classes, or symbols affected in this step.",
    )
    depends_on: list[str] = Field(
        default_factory=list,
        description="Prerequisite step_ids that must complete before this step runs.",
    )
    tests_to_run: list[str] = Field(
        default_factory=list,
        description="Permitted test files or test commands to execute for this step.",
    )
    verification: list[str] = Field(
        default_factory=list,
        description="Concrete verification criteria proving this step succeeded.",
    )

    @field_validator("step_id")
    @classmethod
    def _validate_step_id(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned or not re.match(r"^[A-Za-z0-9_-]{1,64}$", cleaned):
            raise ValueError(f"Invalid step_id '{value}'. Must be alphanumeric with '_' or '-'.")
        return cleaned

    @field_validator("description")
    @classmethod
    def _clean_description(cls, value: str) -> str:
        cleaned = redact(value.strip())
        if not cleaned:
            raise ValueError("Step description cannot be empty.")
        return cleaned

    @field_validator("expected_files")
    @classmethod
    def _validate_expected_files(cls, files: list[str]) -> list[str]:
        validated: list[str] = []
        for path in files:
            try:
                validated.append(validate_repo_relative_path(path))
            except UnsafePathError as exc:
                raise ValueError(f"Unsafe expected_file '{path}': {exc}") from exc
        return validated

    @model_validator(mode="after")
    def _populate_default_title(self) -> "PlanStep":
        if not self.title.strip():
            self.title = self.description[:80]
        else:
            self.title = redact(self.title.strip())
        return self


class PlanRisk(BaseModel):
    """Identified architectural, regression, or security risk in an implementation plan."""

    id: str = Field(..., min_length=1, max_length=64, description="Risk identifier, e.g. 'risk_1'.")
    severity: PlanRiskSeverity = Field(default="medium")
    description: str = Field(..., min_length=1, description="Risk and potential side effect.")
    mitigation: str = Field(default="", description="How the plan mitigates or tests for this risk.")
    affected_files: list[str] = Field(default_factory=list)

    @field_validator("affected_files")
    @classmethod
    def _validate_affected_files(cls, files: list[str]) -> list[str]:
        validated: list[str] = []
        for path in files:
            try:
                validated.append(validate_repo_relative_path(path))
            except UnsafePathError as exc:
                raise ValueError(f"Unsafe affected_file '{path}': {exc}") from exc
        return validated


class PlanResourceBudget(BaseModel):
    """Resource budget limits enforced during plan execution (Docs/week3.md §6 F32 & F34)."""

    max_tokens: int = Field(default=20_000, ge=500, le=100_000)
    max_repair_attempts: int = Field(default=3, ge=1, le=3)
    max_execution_seconds: int = Field(default=300, ge=10, le=1800)
    max_files_modified: int = Field(default=15, ge=1, le=100)


class PlannerSchema(BaseModel):
    """Structured LLM / TaskPlanner output schema with step dependency DAG validation (Dev & Meet W3 Day 2)."""

    summary: str = Field(..., min_length=3, max_length=1000, description="High-level summary of the plan.")
    problem_statement: str = Field(
        default="",
        description="Root cause or requirement statement addressed by this plan.",
    )
    assumptions: list[TaskAssumption] = Field(
        default_factory=list,
        description="Assumptions and unresolved questions surfaced during planning.",
    )
    relevant_files: list[str] = Field(
        default_factory=list,
        description="Existing repository files inspected for context.",
    )
    relevant_symbols: list[str] = Field(
        default_factory=list,
        description="Relevant functions, classes, or symbols.",
    )
    steps: list[PlanStep] = Field(
        ...,
        min_length=1,
        max_length=25,
        description="Ordered implementation steps.",
    )
    expected_files: list[str] = Field(
        default_factory=list,
        description="All repository-relative files expected to be created or modified.",
    )
    tests_to_run: list[str] = Field(
        default_factory=list,
        description="Tests to add or execute to verify the implementation.",
    )
    validation_strategy: list[str] = Field(
        default_factory=list,
        description="Validation checks (unit tests, static analysis, AI code review).",
    )
    risks: list[PlanRisk] = Field(
        default_factory=list,
        description="Identified risks and side effects.",
    )
    required_permissions: list[str] = Field(
        default_factory=lambda: ["workspace:write", "test:execute"],
        description="Tool capabilities required by the plan.",
    )
    resource_budget: PlanResourceBudget = Field(
        default_factory=PlanResourceBudget,
        description="Resource budget for executing this plan.",
    )

    @field_validator("summary")
    @classmethod
    def _clean_summary(cls, value: str) -> str:
        cleaned = redact(value.strip())
        if len(cleaned) < 3:
            raise ValueError("Plan summary must be at least 3 characters.")
        return cleaned

    @field_validator("problem_statement")
    @classmethod
    def _clean_problem_statement(cls, value: str) -> str:
        return redact(value.strip())

    @field_validator("relevant_files", "expected_files")
    @classmethod
    def _validate_file_lists(cls, files: list[str]) -> list[str]:
        validated: list[str] = []
        for path in files:
            try:
                norm = validate_repo_relative_path(path)
                if norm not in validated:
                    validated.append(norm)
            except UnsafePathError as exc:
                raise ValueError(f"Unsafe file path '{path}' in plan: {exc}") from exc
        return validated

    @model_validator(mode="after")
    def _validate_step_dependencies_and_files(self) -> "PlannerSchema":
        """Validate step_id uniqueness, dependency existence, and DAG acyclicity."""
        step_ids: list[str] = []
        seen_ids: set[str] = set()
        for step in self.steps:
            if step.step_id in seen_ids:
                raise ValueError(f"Duplicate step_id '{step.step_id}' in plan.")
            seen_ids.add(step.step_id)
            step_ids.append(step.step_id)

        adj: dict[str, list[str]] = {sid: [] for sid in seen_ids}
        for step in self.steps:
            for dep in step.depends_on:
                if dep == step.step_id:
                    raise ValueError(f"Step '{step.step_id}' cannot depend on itself.")
                if dep not in seen_ids:
                    raise ValueError(
                        f"Step '{step.step_id}' depends on unknown step_id '{dep}'."
                    )
                adj[step.step_id].append(dep)

        # Detect cycles via DFS coloring (0=unvisited, 1=visiting, 2=visited)
        state: dict[str, int] = {sid: 0 for sid in seen_ids}

        def _has_cycle(node: str) -> bool:
            state[node] = 1
            for neighbor in adj.get(node, []):
                if state[neighbor] == 1:
                    return True
                if state[neighbor] == 0 and _has_cycle(neighbor):
                    return True
            state[node] = 2
            return False

        for sid in step_ids:
            if state[sid] == 0 and _has_cycle(sid):
                raise ValueError("Circular dependency detected in plan steps.")

        # Ensure expected_files is the union of step expected_files if not explicitly listed
        combined_expected = list(self.expected_files)
        for step in self.steps:
            for f in step.expected_files:
                if f not in combined_expected:
                    combined_expected.append(f)
        self.expected_files = combined_expected

        if not self.problem_statement:
            self.problem_statement = self.summary

        return self

    def compute_plan_hash(self, base_revision: str | None = None) -> str:
        """Compute a deterministic SHA-256 fingerprint over material plan fields and base_revision."""
        material = {
            "base_revision": base_revision or "",
            "summary": self.summary,
            "expected_files": sorted(self.expected_files),
            "steps": [
                {
                    "step_id": s.step_id,
                    "action_type": s.action_type,
                    "description": s.description,
                    "expected_files": sorted(s.expected_files),
                    "depends_on": sorted(s.depends_on),
                    "verification": list(s.verification),
                }
                for s in self.steps
            ],
        }
        canonical = json.dumps(material, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class TaskPlanGenerateRequest(BaseModel):
    """Optional parameters for POST /api/v1/tasks/{task_id}/plan."""

    base_revision: str | None = Field(
        default=None,
        description="Optional updated base revision SHA or branch ref.",
    )
    revision_notes: str | None = Field(
        default=None,
        max_length=4000,
        description="Optional human feedback or instructions for revising the plan.",
    )
    custom_plan: PlannerSchema | None = Field(
        default=None,
        description="Optional user-edited structured plan to validate and save as a new plan version.",
    )

    @field_validator("base_revision")
    @classmethod
    def _validate_base_revision(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        if not cleaned:
            return None
        if cleaned.startswith("-") or ".." in cleaned or "\x00" in cleaned or not _COMMIT_SHA_OR_REF_RE.match(cleaned):
            raise ValueError(f"Invalid base_revision: '{value}'")
        return cleaned


class TaskPlanResponse(BaseModel):
    """Persisted structured implementation plan response (Docs/week3.md §6 F32)."""

    plan_id: str
    task_id: str
    plan_version: int = Field(..., ge=1)
    base_revision: str | None = None
    plan_hash: str
    summary: str
    problem_statement: str
    assumptions: list[TaskAssumption] = Field(default_factory=list)
    relevant_files: list[str] = Field(default_factory=list)
    relevant_symbols: list[str] = Field(default_factory=list)
    steps: list[PlanStep]
    expected_files: list[str] = Field(default_factory=list)
    tests_to_run: list[str] = Field(default_factory=list)
    validation_strategy: list[str] = Field(default_factory=list)
    risks: list[PlanRisk] = Field(default_factory=list)
    required_permissions: list[str] = Field(default_factory=list)
    resource_budget: PlanResourceBudget = Field(default_factory=PlanResourceBudget)
    status: str = Field(default="PENDING_APPROVAL")
    approved_plan_version: int | None = None
    is_approved: bool = False
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


# ---------------------------------------------------------------------------
# 3. F32 — Plan Approval & Rejection Schemas
# ---------------------------------------------------------------------------

class PlanApprovalRequest(BaseModel):
    """Request payload for POST /api/v1/tasks/{task_id}/approve."""

    plan_version: int | None = Field(
        default=None,
        ge=1,
        description="Explicit plan_version being approved. Must match the task's latest plan_version.",
    )
    base_revision: str | None = Field(
        default=None,
        description="Optional base_revision assertion. If provided, must match the plan's base_revision.",
    )
    comment: str | None = Field(
        default=None,
        max_length=2000,
        description="Optional approver comment or sign-off note.",
    )


class PlanRejectionRequest(BaseModel):
    """Request payload for POST /api/v1/tasks/{task_id}/reject."""

    plan_version: int | None = Field(
        default=None,
        ge=1,
        description="Optional plan_version being rejected.",
    )
    reason: str = Field(
        default="Plan rejected by reviewer.",
        min_length=1,
        max_length=2000,
        description="Reason for rejecting the plan.",
    )


class TaskApprovalResponse(BaseModel):
    """Immutable audit record of a plan approval or rejection decision."""

    approval_id: str
    task_id: str
    plan_id: str
    plan_version: int
    approver_id: str
    decision: Literal["APPROVED", "REJECTED"]
    comment: str | None = None
    base_revision: str | None = None
    plan_hash: str
    task_status: TaskStatus
    approved_plan_version: int | None = None
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class TaskEventResponse(BaseModel):
    """Ordered timeline & audit event record (Docs/week3.md §6 F38 & F39)."""

    event_id: str
    task_id: str
    event_type: str
    actor_id: str | None = None
    from_status: str | None = None
    to_status: str | None = None
    summary: str
    payload: dict[str, Any] = Field(default_factory=dict)
    created_at: str


__all__ = [
    "GitHubIssueCreateRequest",
    "GitHubIssueImportRequest",
    "GitHubIssueResponse",
    "IssueImportResponse",
    "PlanApprovalRequest",
    "PlanRejectionRequest",
    "PlanResourceBudget",
    "PlanRisk",
    "PlanRiskSeverity",
    "PlanStep",
    "PlanStepActionType",
    "PlannerSchema",
    "TaskApprovalResponse",
    "TaskEventResponse",
    "TaskPlanGenerateRequest",
    "TaskPlanResponse",
]
