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
_COMMIT_SHA_RE = re.compile(r"^[0-9a-fA-F]{7,64}$")
_STEP_ID_RE = re.compile(r"^[a-zA-Z0-9_\-]+$")

StepType = Literal["inspect", "edit", "create", "test", "verify", "refactor", "command"]
RiskSeverity = Literal["low", "medium", "high", "critical"]
PlanStatus = Literal["PENDING_APPROVAL", "APPROVED", "REJECTED"]


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
    "edit",
    "refactor",
    "command",
]

PlanRiskSeverity = Literal["low", "medium", "high", "critical"]


class ValidationStrategy(BaseModel):
    """Structured verification and regression testing strategy."""

    model_config = ConfigDict(from_attributes=True)

    automated_tests: list[str] = Field(
        default_factory=list,
        description="Specific test suites or files to execute, e.g. ['pytest backend/tests/test_auth.py'].",
    )
    manual_checks: list[str] = Field(
        default_factory=list,
        description="Manual verification steps for human review.",
    )
    verification_suite: list[str] = Field(
        default_factory=lambda: ["tests", "static_analysis", "secret_scan", "ai_code_review"],
        description="Independent verification gates to run before publication.",
    )
    rollback_plan: str = Field(
        default="",
        description="Disaster recovery or branch rollback procedure if verification fails.",
    )


class PlanStep(BaseModel):
    """A single ordered implementation step in a structured task plan (Docs/week3.md §6 F32)."""

    model_config = ConfigDict(from_attributes=True, extra="allow")

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
    action_type: str = Field(
        default="modify",
        description="Step category: inspect, modify, create, delete, test, verify, edit, refactor, or command.",
    )
    step_type: str = Field(
        default="edit",
        description="Category of action: inspect, edit, create, test, verify, refactor, or command.",
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
    dependencies: list[str] = Field(
        default_factory=list,
        description="List of step_ids that must complete successfully before this step can run.",
    )
    tests_to_run: list[str] = Field(
        default_factory=list,
        description="Permitted test files or test commands to execute for this step.",
    )
    verification: list[str] = Field(
        default_factory=list,
        description="Concrete verification criteria proving this step succeeded.",
    )
    risk_level: str = Field(
        default="low",
        description="Risk level of this specific step.",
    )
    estimated_risk: str = Field(
        default="low",
        description="Estimated risk severity level.",
    )
    rollback_hint: str | None = Field(
        default=None,
        description="Instructions or git commands to revert this step if it fails.",
    )
    rollback_instructions: str | None = Field(
        default=None,
        description="Instructions to revert this step.",
    )
    estimated_duration_s: int | None = Field(
        default=None,
        ge=1,
        le=3600,
        description="Estimated execution time in seconds.",
    )

    @field_validator("step_id")
    @classmethod
    def _validate_step_id(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned or not _STEP_ID_RE.match(cleaned):
            raise ValueError(
                f"Invalid step_id '{value}'. Must be alphanumeric and may include '-' or '_'."
            )
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

    @field_validator("dependencies", "depends_on")
    @classmethod
    def _validate_dependencies_list(cls, deps: list[str]) -> list[str]:
        cleaned: list[str] = []
        seen: set[str] = set()
        for dep in deps:
            dep_clean = dep.strip()
            if not dep_clean:
                raise ValueError("Dependency step_id cannot be blank.")
            if dep_clean not in seen:
                cleaned.append(dep_clean)
                seen.add(dep_clean)
        return cleaned

    @model_validator(mode="after")
    def _sync_and_populate(self) -> "PlanStep":
        # Synchronize dependencies and depends_on
        merged_deps = list(dict.fromkeys(self.dependencies + self.depends_on))
        self.dependencies = merged_deps
        self.depends_on = merged_deps

        # Synchronize action_type and step_type
        if self.step_type and not self.action_type:
            self.action_type = self.step_type
        elif self.action_type and not self.step_type:
            self.step_type = self.action_type

        # Synchronize risk_level and estimated_risk
        if self.risk_level and not self.estimated_risk:
            self.estimated_risk = self.risk_level
        elif self.estimated_risk and not self.risk_level:
            self.risk_level = self.estimated_risk

        # Synchronize rollback_hint and rollback_instructions
        if self.rollback_hint and not self.rollback_instructions:
            self.rollback_instructions = self.rollback_hint
        elif self.rollback_instructions and not self.rollback_hint:
            self.rollback_hint = self.rollback_instructions

        if not self.title.strip():
            self.title = self.description[:80]
        else:
            self.title = redact(self.title.strip())
        return self


class PlanRisk(BaseModel):
    """Identified architectural, regression, or security risk in an implementation plan."""

    model_config = ConfigDict(from_attributes=True, extra="allow")

    id: str = Field(default="", max_length=64, description="Risk identifier, e.g. 'risk_1'.")
    risk_id: str = Field(default="", max_length=64, description="Unique risk ID, e.g. 'rsk-1'.")
    severity: str = Field(default="medium")
    description: str = Field(default="", description="Risk and potential side effect.")
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

    @model_validator(mode="after")
    def _sync_ids(self) -> "PlanRisk":
        if self.risk_id and not self.id:
            self.id = self.risk_id
        elif self.id and not self.risk_id:
            self.risk_id = self.id
        return self


class PlanResourceBudget(BaseModel):
    """Resource budget limits enforced during plan execution (Docs/week3.md §6 F32 & F34)."""

    max_tokens: int = Field(default=20_000, ge=500, le=100_000)
    max_repair_attempts: int = Field(default=3, ge=1, le=3)
    max_execution_seconds: int = Field(default=300, ge=10, le=1800)
    max_files_modified: int = Field(default=15, ge=1, le=100)


class PlanDependencyGraph:
    """Directed Acyclic Graph (DAG) analyzer and topological scheduler for PlanSteps."""

    def __init__(self, steps: list[PlanStep]) -> None:
        self.steps = steps
        self.step_map: dict[str, PlanStep] = {s.step_id: s for s in steps}
        self.adj_list: dict[str, list[str]] = {s.step_id: list(s.dependencies or s.depends_on) for s in steps}

    def validate(self) -> None:
        """Validate step uniqueness, self-dependencies, dangling references, and acyclicity.

        Raises:
            ValueError: If duplicate steps, self-dependencies, dangling references, or cycles are found.
        """
        if len(self.step_map) != len(self.steps):
            seen: set[str] = set()
            duplicates: set[str] = set()
            for step in self.steps:
                if step.step_id in seen:
                    duplicates.add(step.step_id)
                seen.add(step.step_id)
            raise ValueError(f"Duplicate step_id(s) found in plan: {', '.join(sorted(duplicates))}")

        for step_id, deps in self.adj_list.items():
            if step_id in deps:
                raise ValueError(
                    f"Self-dependency detected: Step '{step_id}' cannot depend on itself."
                )
            for dep in deps:
                if dep not in self.step_map:
                    raise ValueError(
                        f"Dangling dependency: Step '{step_id}' depends on unknown step '{dep}' "
                        f"(Step '{step_id}' depends on unknown step_id '{dep}')."
                    )

        visited: dict[str, int] = {s: 0 for s in self.step_map}

        def _dfs(node: str, path: list[str]) -> None:
            visited[node] = 1
            for neighbor in self.adj_list.get(node, []):
                if visited[neighbor] == 1:
                    cycle_nodes = path[path.index(neighbor):] + [neighbor]
                    cycle_str = " -> ".join(cycle_nodes)
                    raise ValueError(
                        f"Cyclic step dependency detected (Circular dependency detected): {cycle_str}"
                    )
                if visited[neighbor] == 0:
                    _dfs(neighbor, path + [neighbor])
            visited[node] = 2

        for step_id in self.step_map:
            if visited[step_id] == 0:
                _dfs(step_id, [step_id])

    def get_execution_order(self) -> list[str]:
        """Compute a valid sequential topological execution order of step IDs."""
        self.validate()

        in_degree: dict[str, int] = {s: len(self.adj_list[s]) for s in self.step_map}
        dependents: dict[str, list[str]] = {s: [] for s in self.step_map}
        for step_id, deps in self.adj_list.items():
            for dep in deps:
                dependents[dep].append(step_id)

        queue: list[str] = [s for s, deg in in_degree.items() if deg == 0]
        order_index = {step.step_id: i for i, step in enumerate(self.steps)}
        queue.sort(key=lambda s: order_index.get(s, 0))

        execution_order: list[str] = []
        while queue:
            current = queue.pop(0)
            execution_order.append(current)

            for dependent in dependents.get(current, []):
                in_degree[dependent] -= 1
                if in_degree[dependent] == 0:
                    queue.append(dependent)
            queue.sort(key=lambda s: order_index.get(s, 0))

        if len(execution_order) != len(self.step_map):
            raise ValueError("Could not resolve execution order: graph contains unresolved dependencies or cycles.")

        return execution_order

    def get_execution_stages(self) -> list[list[str]]:
        """Group steps into parallel execution waves (stages)."""
        self.validate()

        in_degree: dict[str, int] = {s: len(self.adj_list[s]) for s in self.step_map}
        dependents: dict[str, list[str]] = {s: [] for s in self.step_map}
        for step_id, deps in self.adj_list.items():
            for dep in deps:
                dependents[dep].append(step_id)

        order_index = {step.step_id: i for i, step in enumerate(self.steps)}
        stages: list[list[str]] = []
        completed: set[str] = set()

        while len(completed) < len(self.step_map):
            current_stage = [
                s for s, deg in in_degree.items()
                if deg == 0 and s not in completed
            ]
            if not current_stage:
                raise ValueError("Deadlock encountered while computing execution stages.")
            current_stage.sort(key=lambda s: order_index.get(s, 0))
            stages.append(current_stage)

            for s in current_stage:
                completed.add(s)
                for dependent in dependents.get(s, []):
                    in_degree[dependent] -= 1

        return stages


class StructuredPlan(BaseModel):
    """Structured LLM / TaskPlanner output schema with step dependency DAG validation (Dev & Meet W3 Day 2)."""

    model_config = ConfigDict(from_attributes=True, extra="allow")

    task_id: str | None = Field(default=None, description="Associated task identifier.")
    plan_version: int = Field(default=1, ge=1, description="Sequential version number of this plan.")
    base_revision: str | None = Field(default=None, description="Commit SHA from which this plan was generated.")
    summary: str = Field(
        ...,
        min_length=3,
        max_length=1000,
        description="Concise description of the proposed implementation.",
    )
    problem_statement: str = Field(
        default="",
        description="Detailed description of the issue or feature requirement being addressed.",
    )
    assumptions: list[Any] = Field(
        default_factory=list,
        description="Technical and architectural assumptions underlying the plan.",
    )
    unresolved_questions: list[str] = Field(
        default_factory=list,
        description="Open questions requiring clarification during human review.",
    )
    relevant_files: list[str] = Field(
        default_factory=list,
        description="Repository-relative file paths referenced by or relevant to the plan.",
    )
    relevant_symbols: list[str] = Field(
        default_factory=list,
        description="Key classes, methods, or functions relevant to the plan.",
    )
    steps: list[PlanStep] = Field(
        ...,
        min_length=1,
        max_length=25,
        description="Ordered list of atomic implementation steps.",
    )
    expected_files: list[str] = Field(
        default_factory=list,
        description="All repository-relative files expected to be created or modified.",
    )
    expected_files_to_modify: list[str] = Field(
        default_factory=list,
        description="Consolidated repository-relative file paths that will be created or edited.",
    )
    tests_to_run: list[str] = Field(
        default_factory=list,
        description="Tests to add or execute to verify the implementation.",
    )
    tests_to_add_or_run: list[str] = Field(
        default_factory=list,
        description="Test commands or test files that must be executed.",
    )
    validation_strategy: Any = Field(
        default_factory=list,
        description="Strategy for testing, verification gates, and rollback.",
    )
    risks: list[PlanRisk] = Field(
        default_factory=list,
        description="Identified risks and their mitigations.",
    )
    risks_and_side_effects: list[PlanRisk] = Field(
        default_factory=list,
        description="Identified risks and their mitigations.",
    )
    required_permissions: list[str] = Field(
        default_factory=lambda: ["workspace:write", "test:execute"],
        description="Tool and execution capabilities needed by the agent.",
    )
    resource_budget: PlanResourceBudget = Field(
        default_factory=PlanResourceBudget,
        description="Resource budget for executing this plan.",
    )
    estimated_tokens: int | None = Field(
        default=None,
        ge=100,
        le=100000,
        description="Estimated token consumption for planning and execution.",
    )
    status: str = Field(
        default="PENDING_APPROVAL",
        description="Governance status: PENDING_APPROVAL, APPROVED, or REJECTED.",
    )
    approved_by: str | None = Field(
        default=None,
        description="Identifier of the user who approved this plan.",
    )
    approved_at: str | None = Field(
        default=None,
        description="ISO timestamp when approval was granted.",
    )
    approval_notes: str | None = Field(
        default=None,
        description="Optional reviewer remarks.",
    )
    rejection_reason: str | None = Field(
        default=None,
        description="Explanation provided if the plan was rejected.",
    )
    rejected_by: str | None = Field(
        default=None,
        description="Identifier of the user who rejected this plan.",
    )
    rejected_at: str | None = Field(
        default=None,
        description="ISO timestamp when rejection occurred.",
    )
    created_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    updated_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    @field_validator("base_revision")
    @classmethod
    def _validate_base_revision(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        if not cleaned:
            return None
        if not _COMMIT_SHA_RE.match(cleaned):
            raise ValueError(f"Invalid base_revision commit SHA format: '{value}'")
        return cleaned

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

    @field_validator("relevant_files", "expected_files", "expected_files_to_modify")
    @classmethod
    def _validate_file_lists(cls, files: list[str]) -> list[str]:
        validated: list[str] = []
        for path in files:
            try:
                norm = validate_repo_relative_path(path)
                if norm not in validated:
                    validated.append(norm)
            except UnsafePathError as exc:
                raise ValueError(f"Unsafe path '{path}' in plan: {exc}") from exc
        return validated

    @model_validator(mode="after")
    def _validate_dag_and_sync(self) -> "StructuredPlan":
        # 1. Validate DAG
        graph = PlanDependencyGraph(self.steps)
        graph.validate()

        # 2. Consolidate expected_files
        combined: list[str] = list(self.expected_files)
        for step in self.steps:
            for f in step.expected_files:
                if f not in combined:
                    combined.append(f)
        self.expected_files = combined
        self.expected_files_to_modify = combined

        # 3. Sync tests
        if self.tests_to_run and not self.tests_to_add_or_run:
            self.tests_to_add_or_run = list(self.tests_to_run)
        elif self.tests_to_add_or_run and not self.tests_to_run:
            self.tests_to_run = list(self.tests_to_add_or_run)

        # 4. Sync risks
        if self.risks and not self.risks_and_side_effects:
            self.risks_and_side_effects = list(self.risks)
        elif self.risks_and_side_effects and not self.risks:
            self.risks = list(self.risks_and_side_effects)

        if not self.problem_statement:
            self.problem_statement = self.summary

        return self

    def get_execution_order(self) -> list[str]:
        """Compute the sequential topological execution order of steps."""
        return PlanDependencyGraph(self.steps).get_execution_order()

    def get_execution_stages(self) -> list[list[str]]:
        """Compute parallel execution waves/stages for the steps."""
        return PlanDependencyGraph(self.steps).get_execution_stages()

    def validate_against_constraints(self, forbidden_files: list[str]) -> list[str]:
        """Check if any expected files conflict with non-negotiable task constraints."""
        forbidden_set = set(forbidden_files)
        conflicts = sorted(set(self.expected_files_to_modify).intersection(forbidden_set))
        if conflicts:
            raise ValueError(
                f"Plan targets forbidden file(s) under policy constraint: {', '.join(conflicts)}"
            )
        return conflicts

    def approve(self, approved_by: str, notes: str | None = None) -> "StructuredPlan":
        """Mark plan as APPROVED with auditor attribution."""
        self.status = "APPROVED"
        self.approved_by = approved_by
        self.approval_notes = notes
        self.approved_at = datetime.now(timezone.utc).isoformat()
        self.updated_at = datetime.now(timezone.utc).isoformat()
        return self

    def reject(self, rejected_by: str, reason: str) -> "StructuredPlan":
        """Mark plan as REJECTED with mandatory justification."""
        self.status = "REJECTED"
        self.rejection_reason = reason
        self.rejected_by = rejected_by
        self.approved_by = None
        self.approved_at = None
        self.rejected_at = datetime.now(timezone.utc).isoformat()
        self.updated_at = datetime.now(timezone.utc).isoformat()
        return self

    def compute_plan_hash(self, base_revision: str | None = None) -> str:
        """Compute a deterministic SHA-256 fingerprint over material plan fields and base_revision."""
        material = {
            "base_revision": base_revision or self.base_revision or "",
            "summary": self.summary,
            "expected_files": sorted(self.expected_files),
            "steps": [
                {
                    "step_id": s.step_id,
                    "action_type": s.action_type,
                    "description": s.description,
                    "expected_files": sorted(s.expected_files),
                    "depends_on": sorted(s.depends_on or s.dependencies),
                    "verification": list(s.verification),
                }
                for s in self.steps
            ],
        }
        canonical = json.dumps(material, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


# Canonical alias matching Docs/daily_tasks.md line 616
PlannerSchema = StructuredPlan


# ---------------------------------------------------------------------------
# 3. Governance & Approval Schemas (Docs/week3.md §6 contracts)
# ---------------------------------------------------------------------------

class PlanApprovalPayload(BaseModel):
    """Payload for POST /api/v1/tasks/{id}/approve."""

    model_config = ConfigDict(from_attributes=True)

    plan_version: int = Field(..., ge=1, description="Exact plan version being approved.")
    approved_by: str = Field(..., min_length=1, description="Username or user ID of approver.")
    review_notes: str | None = Field(default=None, description="Optional reviewer remarks.")
    approved_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


class PlanRejectionPayload(BaseModel):
    """Payload for POST /api/v1/tasks/{id}/reject."""

    model_config = ConfigDict(from_attributes=True)

    plan_version: int = Field(..., ge=1, description="Exact plan version being rejected.")
    rejected_by: str = Field(..., min_length=1, description="Username or user ID of reviewer.")
    reason: str = Field(..., min_length=3, description="Detailed explanation of why the plan was rejected.")
    requested_revisions: list[str] = Field(
        default_factory=list,
        description="Specific modifications requested before re-planning.",
    )
    rejected_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


class PlanRevisionRequest(BaseModel):
    """Payload for requesting AI re-planning or submitting manual step revisions."""

    model_config = ConfigDict(from_attributes=True)

    target_plan_version: int = Field(..., ge=1, description="Current plan version being revised.")
    feedback: str = Field(..., min_length=3, description="Feedback or instructions for the revision.")
    modified_steps: list[PlanStep] | None = Field(
        default=None,
        description="Optional explicitly updated step definitions.",
    )


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
    "PlanApprovalPayload",
    "PlanApprovalRequest",
    "PlanDependencyGraph",
    "PlanRejectionPayload",
    "PlanRejectionRequest",
    "PlanResourceBudget",
    "PlanRevisionRequest",
    "PlanRisk",
    "PlanRiskSeverity",
    "PlanStatus",
    "PlanStep",
    "PlanStepActionType",
    "PlannerSchema",
    "RiskSeverity",
    "StepType",
    "StructuredPlan",
    "TaskApprovalResponse",
    "TaskEventResponse",
    "TaskPlanGenerateRequest",
    "TaskPlanResponse",
    "ValidationStrategy",
]
