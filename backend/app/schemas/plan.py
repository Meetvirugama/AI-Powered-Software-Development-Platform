"""Week 3 Day 1 & Day 2 Schemas: GitHub Issue Integration, Task Planner, Hierarchical Localisation & Human Approval Gate.

Owners:
- Parth & Yug (F31 GitHub Issue Integration contracts)
- Meet & Dev (F32 TaskPlanner & PlannerSchema with DAG step dependency validation)
- Sukun (Approval gate & plan hash verification contracts)
- Issue 3 (Agentless-style 3-stage Hierarchical Localisation targets persisted for human review & EditSynthesizer)
"""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import re
from typing import Any, Literal, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from ai.security.provenance import DataProvenance
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

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: str
    repository_id: str
    issue_number: int
    title: str
    body: str = ""
    state: str = "open"
    labels: list[str] = Field(default_factory=list)
    html_url: str
    url: str = ""
    author: str | None = None
    origin_finding_id: str | None = None
    task_id: str | None = None
    is_imported: bool = False
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    @model_validator(mode="after")
    def _sync_issue_aliases(self) -> "GitHubIssueResponse":
        if self.html_url and not self.url:
            self.url = self.html_url
        elif self.url and not self.html_url:
            self.html_url = self.url
        if self.task_id and not self.is_imported:
            self.is_imported = True
        return self


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
# 2. F32 — Task Planner, Hierarchical Localisation & Structured Plan Schemas
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


class LocalizationTarget(BaseModel):
    """Agentless-style 3-stage hierarchical localization target (File -> Symbol -> Line Range) [Issue 3 / P-17]."""

    model_config = ConfigDict(from_attributes=True, extra="allow")

    file_path: str = Field(..., min_length=1, max_length=1024, description="Repository-relative file path.")
    symbol_name: str | None = Field(
        default=None,
        max_length=256,
        description="Localized class, method, or function name (Stage 2).",
    )
    symbol_kind: str = Field(
        default="symbol",
        max_length=64,
        description="Symbol category: function, method, class, module, etc.",
    )
    start_line: int | None = Field(
        default=None,
        ge=1,
        description="1-indexed inclusive start line of the localized edit region (Stage 3).",
    )
    end_line: int | None = Field(
        default=None,
        ge=1,
        description="1-indexed inclusive end line of the localized edit region (Stage 3).",
    )
    confidence: float = Field(
        default=0.8,
        ge=0.0,
        le=1.0,
        description="Localization confidence score in [0.0, 1.0].",
    )
    localization_stage: Literal["file", "symbol", "line_range"] = Field(
        default="line_range",
        description="Deepest completed localization stage ('file', 'symbol', or 'line_range').",
    )
    rationale: str = Field(
        default="",
        description="Evidence explaining why this file/symbol/line-range was selected.",
    )
    importance_score: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="PageRank importance score of the localized symbol or file (F05-C3).",
    )
    snippet_preview: str | None = Field(
        default=None,
        description="Optional short code snippet preview for human plan review and edit synthesis.",
    )

    @field_validator("file_path")
    @classmethod
    def _validate_safe_file_path(cls, value: str) -> str:
        try:
            return validate_repo_relative_path(value)
        except UnsafePathError as exc:
            raise ValueError(f"Unsafe localization file_path '{value}': {exc}") from exc

    @model_validator(mode="after")
    def _normalize_line_bounds(self) -> "LocalizationTarget":
        if self.end_line is not None and self.start_line is None:
            self.start_line = self.end_line
        if self.start_line is not None and self.end_line is not None and self.end_line < self.start_line:
            self.start_line, self.end_line = self.end_line, self.start_line
        return self


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


class StepVerification(BaseModel):
    """Specific verification check with observable pass criteria (task.md §5 B)."""

    model_config = ConfigDict(from_attributes=True, extra="allow")

    criterion_id: str = Field(default="", description="Unique criterion ID, e.g. 'crit-1'.")
    description: str = Field(default="", description="What this check proves.")
    verification_type: str = Field(default="test", description="Verification type: test, syntax, diff, command, or static.")
    command_or_check: str | None = Field(default=None, description="Executable command or assertion rule.")
    expected_result: str = Field(default="", description="Expected outcome string or exit code.")
    evidence_required: bool = Field(default=True, description="Whether output evidence must be captured.")


class PlanTransition(BaseModel):
    """Dynamic outcome routing transition for adaptive plan execution (task.md §3, §5 B)."""

    model_config = ConfigDict(from_attributes=True, extra="allow")

    outcome: str = Field(default="success", description="Outcome trigger: success, failure, blocked, or timeout.")
    next_step_id: str | None = Field(default=None, description="Next step to execute upon this outcome.")
    recovery_step_id: str | None = Field(default=None, description="Targeted recovery step if this step fails.")


class ExecutionPolicy(BaseModel):
    """Execution policy constraints for a plan step or entire plan (task.md §5 B)."""

    model_config = ConfigDict(from_attributes=True, extra="allow")

    max_attempts: int = Field(default=3, ge=1, le=10)
    timeout_seconds: int = Field(default=300, ge=10, le=3600)
    require_approval: bool = Field(default=False)
    allowed_tools: list[str] = Field(default_factory=lambda: ["workspace:write", "test:execute", "read_file"])
    rollback_on_failure: bool = Field(default=True)


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
    localization_targets: list[LocalizationTarget] = Field(
        default_factory=list,
        description="Agentless 3-stage localized file/symbol/line-range targets for this step (Issue 3).",
    )
    depends_on: list[str] = Field(
        default_factory=list,
        description="Prerequisite step_ids that must complete before this step runs.",
    )
    dependencies: list[str] = Field(
        default_factory=list,
        description="List of step_ids that must complete successfully before this step can run.",
    )
    requirement_ids: list[str] = Field(
        default_factory=list,
        description="Requirement IDs satisfied or verified by this step.",
    )
    step_verifications: list[StepVerification] = Field(
        default_factory=list,
        description="Concrete verification checks with evidence requirements.",
    )
    transitions: list[PlanTransition] = Field(
        default_factory=list,
        description="Dynamic outcome routing transitions.",
    )
    execution_policy: ExecutionPolicy | None = Field(
        default=None,
        description="Step-specific execution policy and timeout constraints.",
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
    provenance: Optional[DataProvenance] = Field(
        default=None,
        description="Metadata tracking the origin and trust level of this step.",
    )
    provenance_ids: list[str] = Field(
        default_factory=list,
        description="Parent provenance IDs from which this step was derived.",
    )
    taint_status: bool = Field(
        default=False,
        description="True if this step is derived from untrusted input.",
    )
    field_provenance: dict[str, str] = Field(
        default_factory=dict,
        description="Field-level provenance mapping (e.g. {'description': 'prov-1', 'command': 'prov-2'}).",
    )
    approval_required: bool = Field(
        default=False,
        description="True if execution policy mandates explicit human approval before running this step.",
    )
    approval_id: str | None = Field(
        default=None,
        description="ID of associated ExecutionApproval record if approved.",
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
        merged_deps = list(dict.fromkeys(self.dependencies + self.depends_on))
        self.dependencies = merged_deps
        self.depends_on = merged_deps

        if self.step_type and not self.action_type:
            self.action_type = self.step_type
        elif self.action_type and not self.step_type:
            self.step_type = self.action_type

        if self.risk_level and not self.estimated_risk:
            self.estimated_risk = self.risk_level
        elif self.estimated_risk and not self.risk_level:
            self.risk_level = self.estimated_risk

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
        """Validate step uniqueness, self-dependencies, dangling references, and acyclicity."""
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

        for step in self.steps:
            for tr in getattr(step, "transitions", []) or []:
                target_next = getattr(tr, "next_step_id", None)
                if target_next and target_next not in self.step_map:
                    raise ValueError(
                        f"Dangling transition target: Step '{step.step_id}' references unknown next_step_id '{target_next}'."
                    )
                target_rec = getattr(tr, "recovery_step_id", None)
                if target_rec and target_rec not in self.step_map:
                    raise ValueError(
                        f"Dangling transition recovery: Step '{step.step_id}' references unknown recovery_step_id '{target_rec}'."
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

    def topological_sort(self) -> list[PlanStep]:
        """Compute topological sort returning ordered PlanStep instances."""
        order = self.get_execution_order()
        return [self.step_map[sid] for sid in order]

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
    localization_targets: list[LocalizationTarget] = Field(
        default_factory=list,
        description="Agentless 3-stage localized candidate files, symbols, and 1-indexed line ranges (Issue 3 / P-17).",
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
    requirements: list[Any] = Field(
        default_factory=list,
        description="Discovered task requirements matrix (task.md §2, §5 B).",
    )
    requirement_coverage: dict[str, Any] = Field(
        default_factory=dict,
        description="Summary of requirement coverage status and gaps.",
    )
    context_snapshot_id: str | None = Field(
        default=None,
        description="Repository Intelligence snapshot ID from which this plan was grounded.",
    )
    completeness_report: dict[str, Any] = Field(
        default_factory=dict,
        description="Verification report certifying completeness against mandatory requirements.",
    )
    execution_policy: ExecutionPolicy = Field(
        default_factory=ExecutionPolicy,
        description="Execution limits, tool permissions, and timeout policies.",
    )
    final_validation_strategy: list[str] = Field(
        default_factory=list,
        description="Final acceptance and regression tests required before marking task complete.",
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
        graph = PlanDependencyGraph(self.steps)
        graph.validate()

        combined: list[str] = list(self.expected_files)
        for step in self.steps:
            for f in step.expected_files:
                if f not in combined:
                    combined.append(f)
        self.expected_files = combined
        self.expected_files_to_modify = combined

        if self.tests_to_run and not self.tests_to_add_or_run:
            self.tests_to_add_or_run = list(self.tests_to_run)
        elif self.tests_to_add_or_run and not self.tests_to_run:
            self.tests_to_run = list(self.tests_to_add_or_run)

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
    notes: str | None = Field(
        default=None,
        max_length=2000,
        description="Alias for comment (used by frontend PlanReviewPanel).",
    )
    approved_by: str | None = Field(
        default=None,
        max_length=256,
        description="Optional approver username or identifier.",
    )

    @model_validator(mode="after")
    def _sync_comment_and_notes(self) -> "PlanApprovalRequest":
        if self.notes and not self.comment:
            self.comment = self.notes
        elif self.comment and not self.notes:
            self.notes = self.comment
        return self


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
    rejected_by: str | None = Field(
        default=None,
        max_length=256,
        description="Optional reviewer username or identifier.",
    )


class TaskPlanGenerateRequest(BaseModel):
    """Optional parameters for POST /api/v1/tasks/{task_id}/plan."""

    base_revision: str | None = Field(
        default=None,
        description="Optional updated base revision SHA or branch ref.",
    )
    regenerate: bool = Field(
        default=False,
        description="Flag indicating explicit plan regeneration.",
    )
    revision_notes: str | None = Field(
        default=None,
        max_length=4000,
        description="Optional human feedback or instructions for revising the plan.",
    )
    prompt_instructions: str | None = Field(
        default=None,
        max_length=4000,
        description="Alias for revision_notes (used by frontend PlanReviewPanel).",
    )
    custom_plan: PlannerSchema | None = Field(
        default=None,
        description="Optional user-edited structured plan to validate and save as a new plan version.",
    )

    @model_validator(mode="after")
    def _sync_revision_instructions(self) -> "TaskPlanGenerateRequest":
        if self.prompt_instructions and not self.revision_notes:
            self.revision_notes = self.prompt_instructions
        elif self.revision_notes and not self.prompt_instructions:
            self.prompt_instructions = self.revision_notes
        return self

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
    localization_targets: list[LocalizationTarget] = Field(
        default_factory=list,
        description="Agentless 3-stage localized candidate files, symbols, and line ranges (Issue 3).",
    )
    steps: list[PlanStep]
    expected_files: list[str] = Field(default_factory=list)
    expected_files_to_modify: list[str] = Field(default_factory=list)
    tests_to_run: list[str] = Field(default_factory=list)
    tests_to_add: list[str] = Field(default_factory=list)
    validation_strategy: list[str] = Field(default_factory=list)
    risks: list[PlanRisk] = Field(default_factory=list)
    required_permissions: list[str] = Field(default_factory=list)
    resource_budget: PlanResourceBudget = Field(default_factory=PlanResourceBudget)
    status: str = Field(default="PENDING_APPROVAL")
    approved_plan_version: int | None = None
    is_approved: bool = False
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    @model_validator(mode="after")
    def _sync_plan_response_aliases(self) -> "TaskPlanResponse":
        if self.expected_files and not self.expected_files_to_modify:
            self.expected_files_to_modify = list(self.expected_files)
        if self.tests_to_run and not self.tests_to_add:
            self.tests_to_add = list(self.tests_to_run)
        return self


class TaskApprovalResponse(BaseModel):
    """Immutable audit record of a plan approval or rejection decision."""

    model_config = ConfigDict(extra="allow")

    id: str = ""
    approval_id: str
    task_id: str
    plan_id: str
    plan_version: int
    approver_id: str
    user_id: str | None = None
    decision: Literal["APPROVED", "REJECTED"]
    comment: str | None = None
    notes: str | None = None
    reason: str | None = None
    title: str | None = None
    description: str | None = None
    repository_id: str | None = None
    base_revision: str | None = None
    plan_hash: str
    task_status: TaskStatus
    status: TaskStatus | None = None
    approved_plan_version: int | None = None
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    @model_validator(mode="after")
    def _sync_approval_aliases(self) -> "TaskApprovalResponse":
        if not self.id:
            self.id = self.approval_id
        if not self.user_id and self.approver_id:
            self.user_id = self.approver_id
        if self.comment and not self.notes:
            self.notes = self.comment
        if self.decision == "REJECTED" and self.comment and not self.reason:
            self.reason = self.comment
        if self.status is None:
            self.status = self.task_status
        return self


class TaskEventResponse(BaseModel):
    """Ordered timeline & audit event record (Docs/week3.md §6 F38 & F39)."""

    id: str = ""
    event_id: str
    task_id: str
    event_type: str
    actor_id: str | None = None
    user_id: str | None = None
    from_status: str | None = None
    to_status: str | None = None
    summary: str
    description: str = ""
    payload: dict[str, Any] = Field(default_factory=dict)
    details: dict[str, Any] = Field(default_factory=dict)
    created_at: str

    @model_validator(mode="after")
    def _sync_event_aliases(self) -> "TaskEventResponse":
        if not self.id:
            self.id = self.event_id
        if not self.user_id and self.actor_id:
            self.user_id = self.actor_id
        if not self.description and self.summary:
            self.description = self.summary
        elif not self.summary and self.description:
            self.summary = self.description
        if self.payload and not self.details:
            self.details = dict(self.payload)
        elif self.details and not self.payload:
            self.payload = dict(self.details)
        return self


__all__ = [
    "GitHubIssueCreateRequest",
    "GitHubIssueImportRequest",
    "GitHubIssueResponse",
    "IssueImportResponse",
    "LocalizationTarget",
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
