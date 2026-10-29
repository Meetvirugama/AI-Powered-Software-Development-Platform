"""Structured Plan & Step Dependency Graph Schemas.

Owner: Dev — Week 3 Day 2 Deliverable (Docs/daily_tasks.md line 616 & Docs/week3.md §6 F32)
Reference: Docs/week3.md §6 (F32 - Task Planner and Human Approval), §7.1-§7.3

Responsibilities:
1. Define PlanStep model with action types, repo-relative file paths, dependencies, and risk ratings.
2. Provide PlanDependencyGraph engine enforcing DAG integrity:
   - Self-dependency rejection
   - Dangling dependency detection
   - Cycle detection (DFS) with informative error paths
   - Topological sorting and wave-based parallel execution staging
3. Define StructuredPlan (PlannerSchema) with problem statement, assumptions, steps, validation strategy,
   and boundary validation against forbidden files.
4. Provide PlanApprovalPayload, PlanRejectionPayload, and PlanRevisionRequest schemas for governance endpoints.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.core.input_security import UnsafePathError, validate_repo_relative_path

_COMMIT_SHA_RE = re.compile(r"^[0-9a-fA-F]{7,64}$")
_STEP_ID_RE = re.compile(r"^[a-zA-Z0-9_\-]+$")

StepType = Literal["inspect", "edit", "create", "test", "verify", "refactor", "command"]
RiskSeverity = Literal["low", "medium", "high", "critical"]
PlanStatus = Literal["PENDING_APPROVAL", "APPROVED", "REJECTED"]


# ---------------------------------------------------------------------------
# 1. Supporting Plan Element Models
# ---------------------------------------------------------------------------

class PlanRisk(BaseModel):
    """Assessed risk and mitigation strategy for an implementation plan."""

    model_config = ConfigDict(from_attributes=True)

    risk_id: str = Field(..., min_length=1, max_length=64, description="Unique risk ID, e.g. 'rsk-1'.")
    description: str = Field(..., min_length=1, description="Description of the potential risk or side effect.")
    severity: RiskSeverity = Field(default="medium", description="Risk severity level.")
    mitigation: str = Field(..., min_length=1, description="Strategy to prevent or mitigate the risk.")


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


# ---------------------------------------------------------------------------
# 2. Plan Step Model
# ---------------------------------------------------------------------------

class PlanStep(BaseModel):
    """An individual implementation step within a structured plan."""

    model_config = ConfigDict(from_attributes=True)

    step_id: str = Field(
        ...,
        min_length=1,
        max_length=64,
        description="Unique identifier for the step (alphanumeric, underscores, hyphens).",
    )
    title: str = Field(
        ...,
        min_length=1,
        max_length=256,
        description="Short summary of the action to be performed.",
    )
    description: str = Field(
        ...,
        min_length=1,
        description="Detailed technical instruction for modifying or inspecting code.",
    )
    step_type: StepType = Field(
        default="edit",
        description="Category of action: inspect, edit, create, test, verify, refactor, or command.",
    )
    expected_files: list[str] = Field(
        default_factory=list,
        description="Repository-relative file paths affected or inspected by this step.",
    )
    dependencies: list[str] = Field(
        default_factory=list,
        description="List of step_ids that must complete successfully before this step can run.",
    )
    verification: list[str] = Field(
        default_factory=list,
        description="Checks, assertions, or test commands verifying this step.",
    )
    risk_level: RiskSeverity = Field(
        default="low",
        description="Risk level of this specific step.",
    )
    rollback_hint: str | None = Field(
        default=None,
        description="Instructions or git commands to revert this step if it fails.",
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
        value = value.strip()
        if not _STEP_ID_RE.match(value):
            raise ValueError(
                f"Invalid step_id '{value}'. Must be alphanumeric and may include '-' or '_'."
            )
        return value

    @field_validator("expected_files")
    @classmethod
    def _validate_expected_files(cls, files: list[str]) -> list[str]:
        validated: list[str] = []
        for path in files:
            try:
                validated.append(validate_repo_relative_path(path))
            except UnsafePathError as exc:
                raise ValueError(f"Unsafe expected_file '{path}' in step: {exc}") from exc
        return validated

    @field_validator("dependencies")
    @classmethod
    def _validate_dependencies(cls, deps: list[str]) -> list[str]:
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


# ---------------------------------------------------------------------------
# 3. Step Dependency Graph (DAG) Engine
# ---------------------------------------------------------------------------

class PlanDependencyGraph:
    """Directed Acyclic Graph (DAG) analyzer and topological scheduler for PlanSteps."""

    def __init__(self, steps: list[PlanStep]) -> None:
        self.steps = steps
        self.step_map: dict[str, PlanStep] = {s.step_id: s for s in steps}
        self.adj_list: dict[str, list[str]] = {s.step_id: list(s.dependencies) for s in steps}

    def validate(self) -> None:
        """Validate step uniqueness, self-dependencies, dangling references, and acyclicity.

        Raises:
            ValueError: If duplicate steps, self-dependencies, dangling references, or cycles are found.
        """
        # 1. Uniqueness check
        if len(self.step_map) != len(self.steps):
            seen: set[str] = set()
            duplicates: set[str] = set()
            for step in self.steps:
                if step.step_id in seen:
                    duplicates.add(step.step_id)
                seen.add(step.step_id)
            raise ValueError(f"Duplicate step_id(s) found in plan: {', '.join(sorted(duplicates))}")

        # 2. Self-dependencies and dangling dependencies
        for step_id, deps in self.adj_list.items():
            if step_id in deps:
                raise ValueError(f"Self-dependency detected: Step '{step_id}' cannot depend on itself.")
            for dep in deps:
                if dep not in self.step_map:
                    raise ValueError(
                        f"Dangling dependency: Step '{step_id}' depends on unknown step '{dep}'."
                    )

        # 3. Cycle Detection using DFS (White=0, Gray=1, Black=2)
        # In adj_list, step -> list of dependencies (step requires dep to run before it).
        # A cycle exists if following dependencies leads back to the start node.
        visited: dict[str, int] = {s: 0 for s in self.step_map}  # 0=unvisited, 1=in-stack, 2=finished
        parent_map: dict[str, str] = {}

        def _dfs(node: str, path: list[str]) -> None:
            visited[node] = 1
            for neighbor in self.adj_list.get(node, []):
                if visited[neighbor] == 1:
                    # Found cycle: reconstruct cycle path
                    cycle_nodes = path[path.index(neighbor):] + [neighbor]
                    cycle_str = " -> ".join(cycle_nodes)
                    raise ValueError(f"Cyclic step dependency detected: {cycle_str}")
                if visited[neighbor] == 0:
                    parent_map[neighbor] = node
                    _dfs(neighbor, path + [neighbor])
            visited[node] = 2

        for step_id in self.step_map:
            if visited[step_id] == 0:
                _dfs(step_id, [step_id])

    def get_execution_order(self) -> list[str]:
        """Compute a valid sequential topological execution order of step IDs.

        Steps with no dependencies appear first, followed by steps whose dependencies are resolved.

        Returns:
            list[str]: Step IDs ordered such that each step appears after all its dependencies.

        Raises:
            ValueError: If the dependency graph is invalid or contains cycles.
        """
        self.validate()

        # In-degree: number of unresolved dependencies for each step
        in_degree: dict[str, int] = {s: len(self.adj_list[s]) for s in self.step_map}
        # Reverse adjacency: dependency -> list of steps that depend on it
        dependents: dict[str, list[str]] = {s: [] for s in self.step_map}
        for step_id, deps in self.adj_list.items():
            for dep in deps:
                dependents[dep].append(step_id)

        # Queue steps that have 0 dependencies
        queue: list[str] = [s for s, deg in in_degree.items() if deg == 0]
        # Preserve original declaration order for steps at the same dependency tier
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
        """Group steps into parallel execution waves (stages).

        Stage 0 contains all steps with 0 dependencies.
        Stage k contains steps whose dependencies are all satisfied by Stages 0..k-1.

        Returns:
            list[list[str]]: List of stages, each containing independent step IDs suitable for parallel run.
        """
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


# ---------------------------------------------------------------------------
# 4. Structured Implementation Plan (PlannerSchema)
# ---------------------------------------------------------------------------

class StructuredPlan(BaseModel):
    """Validated structured implementation plan matching Docs/week3.md §6 F32."""

    model_config = ConfigDict(from_attributes=True)

    task_id: str = Field(..., min_length=1, description="Associated task identifier.")
    plan_version: int = Field(default=1, ge=1, description="Sequential version number of this plan.")
    base_revision: str = Field(..., description="Commit SHA from which this plan was generated.")
    summary: str = Field(
        ...,
        min_length=3,
        max_length=500,
        description="Concise description of the proposed implementation.",
    )
    problem_statement: str = Field(
        ...,
        min_length=1,
        description="Detailed description of the issue or feature requirement being addressed.",
    )
    assumptions: list[str] = Field(
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
        description="Ordered list of atomic implementation steps.",
    )
    expected_files_to_modify: list[str] = Field(
        default_factory=list,
        description="Consolidated repository-relative file paths that will be created or edited.",
    )
    tests_to_add_or_run: list[str] = Field(
        default_factory=list,
        description="Test commands or test files that must be executed.",
    )
    validation_strategy: ValidationStrategy | None = Field(
        default=None,
        description="Strategy for testing, verification gates, and rollback.",
    )
    risks_and_side_effects: list[PlanRisk] = Field(
        default_factory=list,
        description="Identified risks and their mitigations.",
    )
    required_permissions: list[str] = Field(
        default_factory=lambda: ["file_read", "file_write", "test_execute"],
        description="Tool and execution capabilities needed by the agent.",
    )
    estimated_tokens: int | None = Field(
        default=None,
        ge=100,
        le=100000,
        description="Estimated token consumption for planning and execution.",
    )
    status: PlanStatus = Field(
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
    rejection_reason: str | None = Field(
        default=None,
        description="Explanation provided if the plan was rejected.",
    )
    created_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    updated_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    @field_validator("base_revision")
    @classmethod
    def _validate_base_revision(cls, value: str) -> str:
        value = value.strip()
        if not _COMMIT_SHA_RE.match(value):
            raise ValueError(f"Invalid base_revision commit SHA format: '{value}'")
        return value

    @field_validator("relevant_files", "expected_files_to_modify")
    @classmethod
    def _validate_file_paths(cls, files: list[str]) -> list[str]:
        validated: list[str] = []
        for path in files:
            try:
                validated.append(validate_repo_relative_path(path))
            except UnsafePathError as exc:
                raise ValueError(f"Unsafe path '{path}': {exc}") from exc
        return list(dict.fromkeys(validated))

    @model_validator(mode="after")
    def _validate_plan_integrity(self) -> "StructuredPlan":
        """Validate DAG acyclicity and consolidate expected files across all steps."""
        # 1. Validate step dependency graph
        graph = PlanDependencyGraph(self.steps)
        graph.validate()

        # 2. Consolidate expected_files from steps into expected_files_to_modify
        all_expected: set[str] = set(self.expected_files_to_modify)
        for step in self.steps:
            all_expected.update(step.expected_files)
        self.expected_files_to_modify = sorted(all_expected)

        return self

    def get_execution_order(self) -> list[str]:
        """Compute the sequential topological execution order of steps."""
        return PlanDependencyGraph(self.steps).get_execution_order()

    def get_execution_stages(self) -> list[list[str]]:
        """Compute parallel execution waves/stages for the steps."""
        return PlanDependencyGraph(self.steps).get_execution_stages()

    def validate_against_constraints(self, forbidden_files: list[str]) -> list[str]:
        """Check if any expected files conflict with non-negotiable task constraints.

        Args:
            forbidden_files: List of repo-relative paths that must not be modified.

        Returns:
            list[str]: Conflicting file paths.

        Raises:
            ValueError: If any expected file matches a forbidden file constraint.
        """
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
        self.approved_at = datetime.now(timezone.utc).isoformat()
        self.updated_at = datetime.now(timezone.utc).isoformat()
        return self

    def reject(self, rejected_by: str, reason: str) -> "StructuredPlan":
        """Mark plan as REJECTED with mandatory justification."""
        self.status = "REJECTED"
        self.rejection_reason = reason
        self.approved_by = None
        self.approved_at = None
        self.updated_at = datetime.now(timezone.utc).isoformat()
        return self


# Canonical alias matching Docs/daily_tasks.md line 616
PlannerSchema = StructuredPlan


# ---------------------------------------------------------------------------
# 5. Governance & Approval DTOs (Docs/week3.md §6 Suggested API contracts)
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


__all__ = [
    "PlanApprovalPayload",
    "PlanDependencyGraph",
    "PlanRejectionPayload",
    "PlanRevisionRequest",
    "PlanRisk",
    "PlanStatus",
    "PlanStep",
    "PlannerSchema",
    "RiskSeverity",
    "StepType",
    "StructuredPlan",
    "ValidationStrategy",
]

