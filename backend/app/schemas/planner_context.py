"""Task Planning Context, Symbol Blast Radius & Test Execution Plan Schemas.

Owner: Prit Zania — Week 3 Day 2 Deliverable (Docs/week3.md §6 F32, F33 & Docs/daily_tasks.md line 614)
Reference: Docs/week3.md §6 (F32 Task Planner and Human Approval, F33 Isolated Workspace), §7 (Task Lifecycle)

Responsibilities:
1. Define inclusive 1-indexed LineRange and FileDiffRange for AST symbol matching.
2. Define AffectedSymbol data model capturing directly modified and transitively affected symbols.
3. Define multi-tier RiskAssessment model (low, medium, high, critical) with deterministic scores and explanations.
4. Define TestExecutionPlan model mapping existing tests, discovering untested symbols, and proposing test files.
5. Define TaskImpactAssessment and TaskPlanningContext canonical schemas consumed by Meet's TaskPlanner.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, Field, field_validator, model_validator

from app.core.input_security import UnsafePathError, validate_repo_relative_path


# ---------------------------------------------------------------------------
# 1. Diff Line Range Models (AST Symbol Matching Input)
# ---------------------------------------------------------------------------

class LineRange(BaseModel):
    """Inclusive 1-indexed line range affected by a diff hunk.

    Used by AST symbol mappers to match diff hunks with symbols:
    symbol.start_line <= range.end_line AND symbol.end_line >= range.start_line.
    """

    start_line: int = Field(..., ge=1, description="First modified line in new file (1-indexed, inclusive).")
    end_line: int = Field(..., ge=1, description="Last modified line in new file (1-indexed, inclusive).")
    change_type: str = Field(default="modified", description="Type of change: added, modified, deleted.")

    @field_validator("end_line")
    @classmethod
    def _validate_end_ge_start(cls, v: int, info: Any) -> int:
        start = info.data.get("start_line")
        if start is not None and v < start:
            raise ValueError(f"end_line ({v}) must be >= start_line ({start})")
        return v


class FileDiffRange(BaseModel):
    """File-level diff details with exact modified line ranges for AST symbol mapping."""

    file_path: str = Field(..., description="Target file path relative to repo root.")
    status: str = Field(default="modified", description="Diff status: added, modified, deleted, renamed.")
    diff_ranges: list[LineRange] = Field(default_factory=list, description="List of inclusive line ranges modified.")
    additions: int = Field(default=0, ge=0)
    deletions: int = Field(default=0, ge=0)
    patch: str | None = Field(default=None, description="Optional raw unified diff patch hunk.")

    @field_validator("file_path")
    @classmethod
    def _validate_file_path(cls, path: str) -> str:
        try:
            return validate_repo_relative_path(path)
        except UnsafePathError as exc:
            raise ValueError(f"Unsafe file_path '{path}': {exc}") from exc


class TaskDiffRanges(BaseModel):
    """Collection of modified files and line ranges for an agent task."""

    task_id: UUID = Field(default_factory=uuid4)
    repository_id: UUID | None = None
    base_branch: str = "main"
    head_branch: str = ""
    files: list[FileDiffRange] = Field(default_factory=list)
    total_files_changed: int = 0
    total_additions: int = 0
    total_deletions: int = 0

    @model_validator(mode="after")
    def _calculate_totals(self) -> "TaskDiffRanges":
        self.total_files_changed = len(self.files)
        self.total_additions = sum(f.additions for f in self.files)
        self.total_deletions = sum(f.deletions for f in self.files)
        return self


# ---------------------------------------------------------------------------
# 2. Affected Symbol Models (Graph Traversal Output)
# ---------------------------------------------------------------------------

SymbolImpactType = Literal["modified", "caller", "subclass", "importer", "indirect"]


class AffectedSymbol(BaseModel):
    """Structural code symbol impacted directly or transitively by proposed task changes."""

    symbol_id: UUID = Field(default_factory=uuid4, description="Symbol unique identifier.")
    name: str = Field(..., min_length=1, description="Symbol name (e.g. 'verify_token', 'UserService').")
    kind: str = Field(..., description="Symbol kind: class, function, method, interface, constant.")
    file_path: str = Field(..., description="Repository-relative file path where symbol is defined.")
    start_line: int = Field(..., ge=1, description="1-indexed starting line.")
    end_line: int = Field(..., ge=1, description="1-indexed ending line (inclusive).")
    is_direct_target: bool = Field(default=False, description="True if symbol is directly within modified diff lines.")
    depth: int = Field(default=0, ge=0, description="Hops from direct modification (0 = direct target).")
    impact_type: SymbolImpactType = Field(default="modified", description="Relationship to modified code.")
    signature: str = Field(default="", description="First declaration line / function signature.")
    callers_count: int = Field(default=0, ge=0, description="Number of direct callers in repository graph.")

    @field_validator("file_path")
    @classmethod
    def _validate_path(cls, path: str) -> str:
        try:
            return validate_repo_relative_path(path)
        except UnsafePathError as exc:
            raise ValueError(f"Unsafe symbol file_path '{path}': {exc}") from exc


# ---------------------------------------------------------------------------
# 3. Risk Assessment Models
# ---------------------------------------------------------------------------

class RiskLevel(str, Enum):
    """Deterministic risk levels for task planning and blast radius."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class RiskAssessment(BaseModel):
    """Quantitative and qualitative risk score for proposed code changes."""

    risk_level: RiskLevel = Field(default=RiskLevel.LOW, description="Categorical risk rating.")
    score: float = Field(default=0.1, ge=0.0, le=1.0, description="Normalized risk score from 0.0 to 1.0.")
    summary: str = Field(..., min_length=1, description="Human-readable risk executive summary.")
    reasons: list[str] = Field(default_factory=list, description="Deterministic justifications for risk score.")
    requires_human_review: bool = Field(default=False, description="True if risk exceeds automated safety baseline.")


# ---------------------------------------------------------------------------
# 4. Test Execution Plan Models (Framework Detection & Test Discovery)
# ---------------------------------------------------------------------------

class ProposedTest(BaseModel):
    """A proposed test suite or test case for uncovered modified symbols."""

    target_symbol: str = Field(..., description="Name of symbol requiring test coverage.")
    target_file: str = Field(..., description="Path of target source file.")
    suggested_test_file: str = Field(..., description="Recommended test file path.")
    suggested_test_name: str = Field(..., description="Recommended test function or method name.")
    framework: str = Field(default="pytest", description="Test framework syntax to adhere to.")


class TestExecutionPlan(BaseModel):
    """Test suites to execute and new test cases to add for task verification."""

    __test__ = False  # Prevent pytest from mistaking this Pydantic schema for a test case

    framework: str = Field(default="pytest", description="Detected repository test framework (pytest, unittest, jest).")
    existing_test_files: list[str] = Field(
        default_factory=list,
        description="Existing test files covering modified or affected symbols.",
    )
    existing_test_cases: list[str] = Field(
        default_factory=list,
        description="Specific test function/method names that exercise affected symbols.",
    )
    untested_symbols: list[str] = Field(
        default_factory=list,
        description="Directly modified symbols that lack test coverage.",
    )
    proposed_new_tests: list[ProposedTest] = Field(
        default_factory=list,
        description="Suggested new test files and cases to generate.",
    )
    recommended_test_command: str = Field(
        default="pytest",
        description="CLI command for Restricted Test Runner execution in Day 4 sandbox.",
    )
    test_budget_timeout_seconds: int = Field(
        default=60,
        ge=5,
        le=300,
        description="Maximum execution timeout for the test suite.",
    )


# ---------------------------------------------------------------------------
# 5. Task Impact Assessment Envelope (F32 Planning Contract)
# ---------------------------------------------------------------------------

class TaskImpactAssessment(BaseModel):
    """Complete blast radius and test discovery assessment for a planned task."""

    task_id: str = Field(default_factory=lambda: str(uuid4()), description="Task UUID or identifier.")
    repository_id: str | None = None
    target_files: list[str] = Field(..., description="Files directly targeted by requirements or diffs.")
    affected_files: list[str] = Field(
        default_factory=list,
        description="All files directly or transitively affected by blast radius.",
    )
    total_affected_files: int = Field(default=0, ge=0)
    directly_modified_symbols: list[AffectedSymbol] = Field(default_factory=list)
    transitively_affected_symbols: list[AffectedSymbol] = Field(default_factory=list)
    total_affected_symbols: int = Field(default=0, ge=0)
    risk: RiskAssessment
    test_plan: TestExecutionPlan

    @model_validator(mode="after")
    def _compute_aggregates(self) -> "TaskImpactAssessment":
        self.total_affected_files = len(self.affected_files)
        self.total_affected_symbols = len(self.directly_modified_symbols) + len(self.transitively_affected_symbols)
        return self


# ---------------------------------------------------------------------------
# 6. Task Planning Context (Bridge to Meet's TaskPlanner)
# ---------------------------------------------------------------------------

class TaskPlanningContext(BaseModel):
    """Enriched context bundle provided to Meet's TaskPlanner for plan generation."""

    task_id: str
    repository_id: str
    base_revision: str
    impact_assessment: TaskImpactAssessment
    workspace_ready: bool = Field(default=True, description="True if workspace base revision is verified.")
    detected_framework: str = "pytest"
    primary_language: str = "python"
    resource_limits: dict[str, Any] = Field(default_factory=dict)
