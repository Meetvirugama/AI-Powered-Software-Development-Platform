"""Shared request and response contracts for the Week 2 Developer Intelligence Suite.

Owner: Yug (API contracts) & Dev (AI output schemas) — W2, Day 1

Covers:
1. Shared source references, targets, options, and lifecycle statuses (Docs/week2.md §4.1–§4.4)
2. Code Explanation (`POST /api/v1/repositories/{id}/explain`)
3. Dedicated Bug Detection (`POST /api/v1/repositories/{id}/detect-bugs`)
4. Framework-Aware Test Generation (`POST /api/v1/repositories/{id}/generate-tests`)
5. Standalone AI Code Review (`POST /api/v1/repositories/{id}/review`)
6. Analysis Run History (`GET /api/v1/repositories/{id}/analysis-runs`, `GET /api/v1/analysis-runs/{run_id}`)

Line-Range Convention:
    All `start_line` and `end_line` fields are 1-indexed and INCLUSIVE.
    When a finding or reference cannot be mapped to exact lines, `start_line`
    and `end_line` are explicitly `None` (never fabricated line numbers).
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.core.input_security import UnsafePathError, validate_repo_relative_path

# ---------------------------------------------------------------------------
# Constants & Shared Type Aliases
# ---------------------------------------------------------------------------

MAX_LINE_RANGE_SPAN = 5_000
MAX_DIFF_CHARS = 200_000
_COMMIT_SHA_RE = re.compile(r"^[0-9a-fA-F]{7,64}$")

AnalysisFeatureType = Literal["explain", "detect_bugs", "generate_tests", "review", "bugs", "tests"]
CodeTargetType = Literal["file", "symbol", "range"]
ReviewTargetType = Literal["file", "commit", "diff", "pr"]
AnalysisStatus = Literal["PENDING", "RUNNING", "COMPLETED", "FAILED", "CANCELLED"]
FindingSeverity = Literal["CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO"]
FindingSourceType = Literal["STATIC", "AI", "COMBINED", "HYBRID"]
ConfidenceLevel = Literal["high", "medium", "low"]
SupportedTestFramework = Literal["pytest", "unittest", "jest"]

BugCategory = Literal[
    "off_by_one",
    "null_safety",
    "unhandled_exception",
    "boundary_condition",
    "resource_leak",
    "race_condition",
    "logic_error",
    "security",
    "other",
]

ReviewCategory = Literal[
    "correctness",
    "security",
    "performance",
    "reliability",
    "maintainability",
]


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# 4.2 Shared Source Reference
# ---------------------------------------------------------------------------

class AnalysisSourceReference(BaseModel):
    """Consistent representation for source evidence across all Week 2 features.

    Line ranges (`start_line`, `end_line`) are 1-indexed and inclusive.
    When an exact line mapping is unavailable, `start_line` and `end_line` must
    remain `None` rather than inventing line numbers.
    """

    model_config = ConfigDict(from_attributes=True)

    repository_id: str | None = Field(
        default=None,
        description="UUID of the repository, if bound to a persisted record.",
    )
    file_path: str = Field(
        ...,
        min_length=1,
        max_length=1024,
        description="Repository-relative file path, e.g. 'backend/app/main.py'.",
    )
    start_line: int | None = Field(
        default=None,
        ge=1,
        description="1-indexed inclusive start line, or None if unavailable.",
    )
    end_line: int | None = Field(
        default=None,
        ge=1,
        description="1-indexed inclusive end line, or None if unavailable.",
    )
    revision: str | None = Field(
        default=None,
        max_length=128,
        description="Git commit SHA or branch revision analysed.",
    )
    symbol_name: str | None = Field(
        default=None,
        max_length=256,
        description="Optional function, class, or method name at this location.",
    )

    @field_validator("file_path")
    @classmethod
    def _clean_file_path(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("file_path must not be empty.")
        return value

    @model_validator(mode="after")
    def _validate_line_bounds(self) -> "AnalysisSourceReference":
        if self.end_line is not None and self.start_line is None:
            raise ValueError("start_line is required when end_line is specified.")
        if self.start_line is not None and self.end_line is not None:
            if self.end_line < self.start_line:
                raise ValueError("end_line must be greater than or equal to start_line.")
        return self


# ---------------------------------------------------------------------------
# 4.1 Shared Target & Analysis Options
# ---------------------------------------------------------------------------

class AnalysisTarget(BaseModel):
    """Identifies the file, symbol, or line range within an authorized repository."""

    type: CodeTargetType = Field(
        default="file",
        description="Target granularity: 'file', 'symbol', or 'range'.",
    )
    path: str = Field(
        ...,
        min_length=1,
        max_length=1024,
        description="Repository-relative file path, e.g. 'src/example.py'.",
    )
    start_line: int | None = Field(
        default=None,
        ge=1,
        le=100_000,
        description="1-indexed inclusive start line.",
    )
    end_line: int | None = Field(
        default=None,
        ge=1,
        le=100_000,
        description="1-indexed inclusive end line.",
    )
    symbol: str | None = Field(
        default=None,
        max_length=256,
        description="Target function, method, or class name when type='symbol'.",
    )
    revision: str | None = Field(
        default=None,
        max_length=128,
        description="Optional source revision / commit SHA.",
    )

    @field_validator("path")
    @classmethod
    def _validate_path_not_blank(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("target.path must contain non-whitespace characters.")
        return cleaned

    @field_validator("symbol")
    @classmethod
    def _clean_symbol(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        return cleaned or None

    @model_validator(mode="after")
    def _validate_target_invariants(self) -> "AnalysisTarget":
        if self.end_line is not None and self.start_line is None:
            raise ValueError("start_line is required when end_line is provided.")
        if self.start_line is not None and self.end_line is not None:
            if self.end_line < self.start_line:
                raise ValueError("end_line must be greater than or equal to start_line.")
            if (self.end_line - self.start_line) > MAX_LINE_RANGE_SPAN:
                raise ValueError(
                    f"Selected line range cannot exceed {MAX_LINE_RANGE_SPAN} lines."
                )
        if self.type == "symbol" and not self.symbol:
            raise ValueError("symbol name is required when target.type is 'symbol'.")
        if self.type == "range" and (self.start_line is None or self.end_line is None):
            raise ValueError(
                "Both start_line and end_line are required when target.type is 'range'."
            )
        return self


class AnalysisOptions(BaseModel):
    """Bounded execution and context options shared by intelligence endpoints."""

    include_context: bool = Field(
        default=True,
        description="Whether to enrich analysis with related symbols and RAG chunks.",
    )
    max_context_tokens: int = Field(
        default=10_000,
        ge=500,
        le=100_000,
        description="Maximum token budget allocated for intelligence context.",
    )
    persist_run: bool = Field(
        default=True,
        description="Whether to record the analysis run in history persistence.",
    )


def _normalize_code_target_payload(data: Any) -> Any:
    """Allow callers to supply either nested `target` or flat `file_path`/`path` fields."""
    if not isinstance(data, dict) or "target" in data:
        return data
    path_val = data.get("file_path") if "file_path" in data else data.get("path")
    if path_val is None:
        return data
    start_line = data.get("start_line")
    end_line = data.get("end_line")
    symbol = data.get("symbol")
    revision = data.get("revision")

    inferred_type: CodeTargetType = "file"
    if data.get("type") in ("file", "symbol", "range"):
        inferred_type = data["type"]
    elif symbol and start_line is None and end_line is None:
        inferred_type = "symbol"
    elif start_line is not None and end_line is not None and not symbol:
        inferred_type = "range"

    normalized = dict(data)
    normalized["target"] = {
        "type": inferred_type,
        "path": path_val,
        "start_line": start_line,
        "end_line": end_line,
        "symbol": symbol,
        "revision": revision,
    }
    return normalized


# ---------------------------------------------------------------------------
# Feature 1: Code Explanation Schemas (Day 2 Contract)
# ---------------------------------------------------------------------------

class ExplainCodeRequest(BaseModel):
    """Request body for `POST /api/v1/repositories/{repository_id}/explain`."""

    target: AnalysisTarget
    options: AnalysisOptions = Field(default_factory=AnalysisOptions)

    @model_validator(mode="before")
    @classmethod
    def _coerce_flat_request(cls, data: Any) -> Any:
        return _normalize_code_target_payload(data)


class SymbolSummary(BaseModel):
    """Description of an important symbol within an explained code target."""

    name: str = Field(..., min_length=1, max_length=256)
    kind: str = Field(
        default="symbol",
        description="Symbol kind, e.g. 'function', 'class', 'method', 'variable', 'type'.",
    )
    role: str = Field(..., min_length=1, description="How this symbol contributes to the code.")
    start_line: int | None = Field(default=None, ge=1)
    end_line: int | None = Field(default=None, ge=1)


class CodeExplanation(BaseModel):
    """Structured explanation output validated against Dev's CodeExplanationService."""

    purpose: str = Field(
        ...,
        min_length=1,
        description="What the selected code is intended to do.",
    )
    logic_flow: list[str] = Field(
        default_factory=list,
        description="Major execution steps in chronological order.",
    )
    key_symbols: list[SymbolSummary] = Field(
        default_factory=list,
        description="Important functions, classes, variables, and types.",
    )
    inputs_and_outputs: str = Field(
        ...,
        min_length=1,
        description="Parameters, return values, and side effects.",
    )
    dependencies: list[str] = Field(
        default_factory=list,
        description="Imports, callers, and related components grounded in context.",
    )
    assumptions_and_limitations: list[str] = Field(
        default_factory=list,
        description="What cannot be confirmed from the available repository context.",
    )
    sources: list[AnalysisSourceReference] = Field(
        default_factory=list,
        description="Grounded file and line citations supporting the explanation.",
    )
    confidence: ConfidenceLevel = Field(
        default="medium",
        description="Grounding confidence level ('high', 'medium', 'low').",
    )
    missing_context: list[str] = Field(
        default_factory=list,
        description="Explicit list of unavailable files, callers, or context items.",
    )

    @field_validator("purpose", "inputs_and_outputs")
    @classmethod
    def _non_blank_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Explanation text fields must not be empty.")
        return value


class CodeExplanationResponse(BaseModel):
    """Envelope returned by `POST /api/v1/repositories/{repository_id}/explain`."""

    run_id: str
    repository_id: str
    status: AnalysisStatus = "COMPLETED"
    target: AnalysisTarget
    revision: str | None = None
    explanation: CodeExplanation
    created_at: datetime = Field(default_factory=_utc_now)


# ---------------------------------------------------------------------------
# Feature 2: Dedicated Bug Detection Schemas (Day 3 Contract)
# ---------------------------------------------------------------------------

class BugDetectionRequest(BaseModel):
    """Request body for `POST /api/v1/repositories/{repository_id}/detect-bugs`."""

    target: AnalysisTarget
    options: AnalysisOptions = Field(default_factory=AnalysisOptions)
    include_static: bool = Field(
        default=True,
        description="Run configured static analysis adapters (Ruff/Bandit/secret checks).",
    )
    include_ai: bool = Field(
        default=True,
        description="Run AI-assisted defect reasoning.",
    )
    min_severity: FindingSeverity = Field(
        default="LOW",
        description="Minimum finding severity threshold to include.",
    )

    @model_validator(mode="before")
    @classmethod
    def _coerce_flat_request(cls, data: Any) -> Any:
        return _normalize_code_target_payload(data)

    @model_validator(mode="after")
    def _require_at_least_one_engine(self) -> "BugDetectionRequest":
        if not self.include_static and not self.include_ai:
            raise ValueError("At least one of include_static or include_ai must be True.")
        return self


class BugFinding(BaseModel):
    """A single static, AI, or combined defect finding (Docs/week2.md §4.4 & §7)."""

    id: str = Field(..., min_length=1)
    category: BugCategory | str = Field(
        ...,
        min_length=1,
        description="Defect class, e.g. 'off_by_one', 'null_safety', 'unhandled_exception'.",
    )
    severity: FindingSeverity = Field(
        ...,
        description="Finding severity: CRITICAL, HIGH, MEDIUM, LOW, or INFO.",
    )
    title: str = Field(..., min_length=1, max_length=300)
    description: str = Field(
        ...,
        min_length=1,
        description="What may be wrong and why the pattern may be defective.",
    )
    source_reference: AnalysisSourceReference
    evidence: str = Field(
        ...,
        min_length=1,
        description="Concrete code or static-rule evidence supporting the finding.",
    )
    suggested_fix: str | None = Field(
        default=None,
        description="Suggested remediation when justified by evidence.",
    )
    confidence: ConfidenceLevel = Field(default="medium")
    is_uncertain: bool = Field(
        default=False,
        description="True when runtime defect confirmation requires external context.",
    )
    source_type: FindingSourceType = Field(
        default="AI",
        description="Origin of finding: STATIC, AI, or COMBINED.",
    )
    rule_id: str | None = Field(
        default=None,
        max_length=128,
        description="Static analyzer rule identifier (e.g. 'F821', 'B105') when applicable.",
    )


class BugDetectionResponse(BaseModel):
    """Envelope returned by `POST /api/v1/repositories/{repository_id}/detect-bugs`."""

    run_id: str
    repository_id: str
    status: AnalysisStatus = "COMPLETED"
    target: AnalysisTarget
    revision: str | None = None
    findings: list[BugFinding] = Field(default_factory=list)
    total_findings: int = Field(default=0, ge=0)
    static_findings_count: int = Field(default=0, ge=0)
    ai_findings_count: int = Field(default=0, ge=0)
    missing_context: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=_utc_now)


# ---------------------------------------------------------------------------
# Feature 3: Framework-Aware Test Generation Schemas (Day 4 Contract)
# ---------------------------------------------------------------------------

class TestGenerationRequest(BaseModel):
    """Request body for `POST /api/v1/repositories/{repository_id}/generate-tests`."""

    target: AnalysisTarget
    options: AnalysisOptions = Field(default_factory=AnalysisOptions)
    framework: SupportedTestFramework | None = Field(
        default=None,
        description="Optional explicit test framework override ('pytest', 'unittest', 'jest').",
    )

    @model_validator(mode="before")
    @classmethod
    def _coerce_flat_request(cls, data: Any) -> Any:
        return _normalize_code_target_payload(data)


class TestScenario(BaseModel):
    """Summary of a single test scenario included in the generated test file."""

    name: str = Field(..., min_length=1, max_length=256)
    category: Literal["normal", "edge_case", "failure_path"] = Field(default="normal")
    description: str = Field(..., min_length=1)


class TestGenerationResult(BaseModel):
    """Structured test generation output (Docs/week2.md §8)."""

    detected_framework: SupportedTestFramework = Field(
        ...,
        description="Detected or selected test runner ('pytest', 'unittest', 'jest').",
    )
    proposed_test_path: str = Field(
        ...,
        min_length=1,
        max_length=1024,
        description="Safe repository-relative path for the proposed test file.",
    )
    test_content: str = Field(
        ...,
        min_length=1,
        description="Complete generated test file source code.",
    )
    covered_scenarios: list[TestScenario] = Field(
        default_factory=list,
        description="Normal, edge-case, and failure-path scenarios covered.",
    )
    assumptions_and_warnings: list[str] = Field(
        default_factory=list,
        description="Assumptions, missing fixtures, or existing-file overwrite warnings.",
    )
    syntax_valid: bool = Field(
        default=True,
        description="Whether static syntax/structural validation succeeded.",
    )
    validation_errors: list[str] = Field(
        default_factory=list,
        description="Normalized syntax or structural validation errors, if any.",
    )
    sources: list[AnalysisSourceReference] = Field(
        default_factory=list,
        description="Source references used to construct the test suite.",
    )

    @field_validator("proposed_test_path")
    @classmethod
    def _validate_safe_test_path(cls, value: str) -> str:
        try:
            return validate_repo_relative_path(value)
        except UnsafePathError as exc:
            raise ValueError(f"Unsafe proposed_test_path: {exc}") from exc

    @field_validator("test_content")
    @classmethod
    def _validate_non_empty_content(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("test_content must not be empty.")
        return value


class TestGenerationResponse(BaseModel):
    """Envelope returned by `POST /api/v1/repositories/{repository_id}/generate-tests`."""

    run_id: str
    repository_id: str
    status: AnalysisStatus = "COMPLETED"
    target: AnalysisTarget
    revision: str | None = None
    result: TestGenerationResult
    created_at: datetime = Field(default_factory=_utc_now)


# ---------------------------------------------------------------------------
# Feature 4: Standalone AI Code Review Schemas (Day 5 Contract)
# ---------------------------------------------------------------------------

class ReviewTarget(BaseModel):
    """Identifies a single file, commit SHA, unified diff, or GitHub PR for review."""

    type: ReviewTargetType = Field(
        default="file",
        description="Review target kind: 'file', 'commit', 'diff', or 'pr'.",
    )
    path: str | None = Field(
        default=None,
        max_length=1024,
        description="Repository-relative file path when type='file'.",
    )
    commit_sha: str | None = Field(
        default=None,
        min_length=7,
        max_length=64,
        description="Git commit SHA when type='commit'.",
    )
    pr_number: int | None = Field(
        default=None,
        ge=1,
        le=1_000_000,
        description="GitHub Pull Request number when type='pr'.",
    )
    diff: str | None = Field(
        default=None,
        max_length=MAX_DIFF_CHARS,
        description="Unified diff text when type='diff'.",
    )
    base_revision: str | None = Field(default=None, max_length=128)
    head_revision: str | None = Field(default=None, max_length=128)

    @model_validator(mode="after")
    def _validate_review_target(self) -> "ReviewTarget":
        if self.type == "file":
            if not self.path or not self.path.strip():
                raise ValueError("target.path is required when review target.type is 'file'.")
            self.path = self.path.strip()
        elif self.type == "commit":
            if not self.commit_sha or not _COMMIT_SHA_RE.match(self.commit_sha.strip()):
                raise ValueError(
                    "target.commit_sha must be a valid 7-to-64 character hexadecimal SHA when type='commit'."
                )
            self.commit_sha = self.commit_sha.strip()
        elif self.type == "pr":
            if self.pr_number is None:
                raise ValueError("target.pr_number is required when review target.type is 'pr'.")
        elif self.type == "diff":
            if not self.diff or not self.diff.strip():
                raise ValueError("target.diff must be a non-empty unified diff when type='diff'.")
        return self


class CodeReviewRequest(BaseModel):
    """Request body for `POST /api/v1/repositories/{repository_id}/review`."""

    target: ReviewTarget
    options: AnalysisOptions = Field(default_factory=AnalysisOptions)
    include_static: bool = Field(
        default=True,
        description="Run static linters and secret checks on reviewed files.",
    )

    @model_validator(mode="before")
    @classmethod
    def _coerce_flat_review_request(cls, data: Any) -> Any:
        if not isinstance(data, dict) or "target" in data:
            return data
        normalized = dict(data)
        if "pr_number" in data and data["pr_number"] is not None:
            normalized["target"] = {
                "type": "pr",
                "pr_number": data["pr_number"],
                "base_revision": data.get("base_revision"),
                "head_revision": data.get("head_revision"),
            }
        elif "commit_sha" in data and data["commit_sha"] is not None:
            normalized["target"] = {
                "type": "commit",
                "commit_sha": data["commit_sha"],
                "base_revision": data.get("base_revision"),
                "head_revision": data.get("head_revision"),
            }
        elif "diff" in data and data["diff"] is not None:
            normalized["target"] = {
                "type": "diff",
                "diff": data["diff"],
                "path": data.get("file_path") or data.get("path"),
                "base_revision": data.get("base_revision"),
                "head_revision": data.get("head_revision"),
            }
        elif "file_path" in data or "path" in data:
            normalized["target"] = {
                "type": "file",
                "path": data.get("file_path") or data.get("path"),
                "base_revision": data.get("base_revision"),
                "head_revision": data.get("head_revision"),
            }
        return normalized


class ReviewFinding(BaseModel):
    """A single categorized finding within a standalone AI code review (Docs/week2.md §9)."""

    id: str = Field(..., min_length=1)
    category: ReviewCategory = Field(
        ...,
        description="Review dimension: correctness, security, performance, reliability, maintainability.",
    )
    severity: FindingSeverity
    title: str = Field(..., min_length=1, max_length=300)
    description: str = Field(..., min_length=1)
    source_reference: AnalysisSourceReference
    evidence: str = Field(..., min_length=1)
    suggested_fix: str | None = Field(default=None)
    confidence: ConfidenceLevel = Field(default="medium")
    is_uncertain: bool = Field(default=False)
    is_new_in_change: bool = Field(
        default=True,
        description="True when evidence indicates the issue was introduced by the target change.",
    )
    source_type: FindingSourceType = Field(default="AI")
    rule_id: str | None = Field(default=None, max_length=128)


class ReviewReport(BaseModel):
    """Structured review report returned by Dev's AICodeReviewEngine."""

    summary: str = Field(..., min_length=1)
    risk_level: Literal["CRITICAL", "HIGH", "MEDIUM", "LOW", "NONE"] = Field(default="LOW")
    findings: list[ReviewFinding] = Field(default_factory=list)
    total_findings: int = Field(default=0, ge=0)
    category_counts: dict[str, int] = Field(default_factory=dict)
    missing_context: list[str] = Field(default_factory=list)

    @field_validator("summary")
    @classmethod
    def _clean_summary(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Review summary must not be empty.")
        return value


class ReviewReportResponse(BaseModel):
    """Envelope returned by `POST /api/v1/repositories/{repository_id}/review`."""

    run_id: str
    repository_id: str
    status: AnalysisStatus = "COMPLETED"
    target: ReviewTarget
    report: ReviewReport
    created_at: datetime = Field(default_factory=_utc_now)


# ---------------------------------------------------------------------------
# Analysis Run History Schemas (Om & Yug Persistence Contract)
# ---------------------------------------------------------------------------

class AnalysisRunSummary(BaseModel):
    """Summary item for `GET /api/v1/repositories/{repository_id}/analysis-runs`."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    repository_id: str
    user_id: str | None = None
    feature_type: AnalysisFeatureType
    status: AnalysisStatus
    target_path: str | None = None
    target_symbol: str | None = None
    start_line: int | None = None
    end_line: int | None = None
    source_revision: str | None = None
    findings_count: int = 0
    error_message: str | None = None
    created_at: datetime
    completed_at: datetime | None = None


class PaginatedAnalysisRunResponse(BaseModel):
    """Paginated list of analysis runs for a repository."""

    page: int
    page_size: int
    total: int
    items: list[AnalysisRunSummary] = Field(default_factory=list)


class AnalysisRunDetailResponse(BaseModel):
    """Detailed record for `GET /api/v1/analysis-runs/{run_id}`."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    repository_id: str
    user_id: str | None = None
    feature_type: AnalysisFeatureType
    status: AnalysisStatus
    target_path: str | None = None
    target_symbol: str | None = None
    start_line: int | None = None
    end_line: int | None = None
    source_revision: str | None = None
    findings_count: int = 0
    result_payload: dict[str, Any] | None = None
    findings: list[BugFinding | ReviewFinding] = Field(default_factory=list)
    error_message: str | None = None
    created_at: datetime
    completed_at: datetime | None = None


_FEATURE_TYPE_ALIASES: dict[str, str] = {
    "bugs": "detect_bugs",
    "detect_bugs": "detect_bugs",
    "tests": "generate_tests",
    "generate_tests": "generate_tests",
    "explain": "explain",
    "review": "review",
}


def normalize_analysis_feature_type(value: str | None) -> str | None:
    """Normalize shorthand feature_type query aliases ('bugs' -> 'detect_bugs', 'tests' -> 'generate_tests')."""
    if value is None:
        return None
    raw = str(value).strip().lower()
    if raw in _FEATURE_TYPE_ALIASES:
        return _FEATURE_TYPE_ALIASES[raw]
    raise ValueError(f"Unsupported feature_type: {value}")
