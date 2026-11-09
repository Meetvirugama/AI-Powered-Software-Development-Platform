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
SupportedTestFramework = Literal["pytest", "unittest", "jest", "vitest"]
TestVerificationStatus = Literal["VERIFIED", "UNVERIFIED", "REJECTED", "EXECUTION_ERROR"]
StabilityClassification = Literal["STABLE", "UNSTABLE", "FAILED"]


class StabilityRunResult(BaseModel):
    """Detailed result for an individual stability execution run (Phase 3)."""

    run_number: int = Field(..., ge=1, le=10)
    passed: bool = Field(...)
    exit_code: int = Field(default=0)
    duration_seconds: float = Field(default=0.0, ge=0.0)
    passed_count: int = Field(default=0, ge=0)
    failed_count: int = Field(default=0, ge=0)
    error_message: str | None = Field(default=None)


class StabilityReport(BaseModel):
    """Three-run stability report for flakiness filtering (task.md §4.6)."""

    total_runs: int = Field(default=3, ge=1)
    passed_runs: int = Field(default=0, ge=0)
    classification: StabilityClassification = Field(default="FAILED")
    is_stable: bool = Field(default=False)
    runs: list[StabilityRunResult] = Field(default_factory=list)


class CoverageReport(BaseModel):
    """Runtime coverage delta report (task.md §5)."""

    baseline_line_coverage: float | None = Field(default=None, ge=0.0, le=100.0)
    final_line_coverage: float | None = Field(default=None, ge=0.0, le=100.0)
    line_coverage_gain: float | None = Field(default=None)
    baseline_branch_coverage: float | None = Field(default=None, ge=0.0, le=100.0)
    final_branch_coverage: float | None = Field(default=None, ge=0.0, le=100.0)
    branch_coverage_gain: float | None = Field(default=None)
    newly_covered_lines: list[int] = Field(default_factory=list)
    newly_covered_branches: list[list[int]] = Field(default_factory=list)
    coverage_attributable_to_generated_tests: bool = Field(default=False)
    collection_status: Literal["SUCCESS", "PARTIAL", "FAILED", "NOT_CONFIGURED"] = Field(
        default="NOT_CONFIGURED"
    )
    warnings: list[str] = Field(default_factory=list)


class IterationRound(BaseModel):
    """Information about a single iteration round in coverage-guided feedback (task.md §6)."""

    round_number: int = Field(..., ge=1, le=10)
    scenarios_targeted: list[str] = Field(default_factory=list)
    uncovered_lines_addressed: list[int] = Field(default_factory=list)
    tests_added: int = Field(default=0, ge=0)
    line_coverage_after: float | None = Field(default=None)
    tokens_used: int | None = Field(default=None)


class IterationReport(BaseModel):
    """Report on coverage-guided iterative test generation rounds (task.md §6)."""

    total_rounds: int = Field(default=1, ge=1)
    rounds: list[IterationRound] = Field(default_factory=list)
    stopping_reason: str = Field(default="Initial generation complete")
    final_coverage_achieved: float | None = Field(default=None)

BugCategory = Literal[
    "off_by_one",
    "null_safety",
    "unhandled_exception",
    "boundary_condition",
    "resource_leak",
    "race_condition",
    "logic_error",
    "security",
    "supply_chain",
    "secrets",
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

    @model_validator(mode="before")
    @classmethod
    def _coerce_source(cls, data: Any) -> Any:
        if isinstance(data, str):
            m = re.match(r"^([^(\s:]+)(?:\s*(?:\(lines\s*|:)\s*(\d+)(?:[-–](\d+))?\s*\)?)?", data.strip())
            if m:
                path = m.group(1).strip()
                start = int(m.group(2)) if m.group(2) else None
                end = int(m.group(3)) if m.group(3) else start
                return {"file_path": path, "start_line": start, "end_line": end}
            return {"file_path": data.strip()}
        if isinstance(data, dict):
            d = dict(data)
            if "file_path" not in d:
                for alt in ("path", "file", "filename", "source", "filepath"):
                    if alt in d and d[alt]:
                        d["file_path"] = str(d[alt]).strip()
                        break
            return d
        return data

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
            self.start_line = self.end_line
        if self.start_line is not None and self.end_line is not None:
            if self.end_line < self.start_line:
                self.start_line, self.end_line = self.end_line, self.start_line
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


# Per-feature context budget defaults (Week 2 Section 12 Item 17, B-14)
DEFAULT_EXPLAIN_CONTEXT_TOKENS: int = 4_000
DEFAULT_BUGS_CONTEXT_TOKENS: int = 6_000
DEFAULT_TESTS_CONTEXT_TOKENS: int = 6_000
DEFAULT_REVIEW_CONTEXT_TOKENS: int = 8_000


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
# Feature 1: Code Explanation Schemas (Day 2 Contract & Repository Intelligence)
# ---------------------------------------------------------------------------

class ExplainContextOptions(BaseModel):
    """Context selection options for Repository Intelligence Explain Studio (task.md §6.3)."""

    include_graph_context: bool = True
    include_callers: bool = True
    include_dependencies: bool = True
    include_tests: bool = True
    include_semantic_search: bool = True
    selected_files: list[str] = Field(
        default_factory=list,
        description="User-selected related files explicitly added to context.",
    )


class ExplainCodeRequest(BaseModel):
    """Request body for `POST /api/v1/repositories/{repository_id}/explain`."""

    target: AnalysisTarget
    options: AnalysisOptions = Field(
        default_factory=lambda: AnalysisOptions(max_context_tokens=DEFAULT_EXPLAIN_CONTEXT_TOKENS)
    )
    context: ExplainContextOptions = Field(default_factory=ExplainContextOptions)
    explanation_level: Literal["concise", "detailed", "deep_technical"] = "detailed"

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
    role: str = Field(
        default="Referenced in target code",
        min_length=1,
        description="How this symbol contributes to the code.",
    )
    start_line: int | None = Field(default=None, ge=1)
    end_line: int | None = Field(default=None, ge=1)

    @model_validator(mode="before")
    @classmethod
    def _coerce_symbol(cls, data: Any) -> Any:
        if isinstance(data, str):
            clean = data.strip() or "symbol"
            return {"name": clean, "kind": "symbol", "role": "Referenced in target code"}
        if isinstance(data, dict):
            d = dict(data)
            if "name" not in d or not str(d.get("name", "")).strip():
                for alt in ("symbol", "identifier", "selector", "title", "label"):
                    if alt in d and d[alt]:
                        d["name"] = str(d[alt]).strip()
                        break
                if not d.get("name"):
                    d["name"] = "symbol"
            if not d.get("role"):
                d["role"] = d.get("description") or "Referenced in target code"
            if not d.get("kind"):
                d["kind"] = "symbol"
            return d
        return data


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
    execution_flow: list[str] = Field(
        default_factory=list,
        description="Runtime execution flow across repository components.",
    )
    related_files: list[str] = Field(
        default_factory=list,
        description="Related repository files utilized in context assembly.",
    )
    detailed_explanation: str | None = Field(
        default=None,
        description="In-depth technical and algorithmic explanation of how the code operates.",
    )
    code_output_explanation: str | None = Field(
        default=None,
        description="Detailed breakdown of code outputs, calculation formulas, field meanings, and concrete examples.",
    )
    code_issues_and_solutions: list[str] = Field(
        default_factory=list,
        description="Identified flaws, bugs, vulnerabilities, or edge cases and proposed solutions.",
    )
    corrected_code: str | None = Field(
        default=None,
        description="Corrected, production-grade refactoring of the code solving identified issues.",
    )

    @model_validator(mode="before")
    @classmethod
    def _coerce_explanation(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        d = dict(data)

        # 1. purpose
        p = d.get("purpose")
        if p is not None and isinstance(p, str):
            d["purpose"] = p.strip()

        # 2. logic_flow
        lf = d.get("logic_flow")
        if isinstance(lf, str):
            lf_str = lf.strip()
            parts = [part.strip() for part in re.split(r"(?<=[.!?])\s+", lf_str) if part.strip()]
            d["logic_flow"] = parts if parts else [lf_str]
        elif not isinstance(lf, list):
            d["logic_flow"] = []

        # 3. inputs_and_outputs
        io = d.get("inputs_and_outputs")
        if isinstance(io, dict):
            parts = []
            if "inputs" in io and io["inputs"]:
                parts.append(f"Inputs: {io['inputs']}")
            if "outputs" in io and io["outputs"]:
                parts.append(f"Outputs: {io['outputs']}")
            d["inputs_and_outputs"] = " | ".join(parts) if parts else "; ".join(f"{k}: {v}" for k, v in io.items())
        elif isinstance(io, str):
            d["inputs_and_outputs"] = io.strip()

        # 4. dependencies
        deps = d.get("dependencies")
        if isinstance(deps, dict):
            d["dependencies"] = [f"{k}: {v}" for k, v in deps.items()]
        elif isinstance(deps, str):
            d["dependencies"] = [deps.strip()] if deps.strip() else []
        elif not isinstance(deps, list):
            d["dependencies"] = []

        # 5. assumptions_and_limitations
        al = d.get("assumptions_and_limitations")
        if isinstance(al, dict):
            d["assumptions_and_limitations"] = [f"{k}: {v}" for k, v in al.items()]
        elif isinstance(al, str):
            d["assumptions_and_limitations"] = [al.strip()] if al.strip() else []
        elif not isinstance(al, list):
            d["assumptions_and_limitations"] = []

        # 6. missing_context
        mc = d.get("missing_context")
        if isinstance(mc, str):
            if mc.strip().lower() in ("none", "n/a", "no missing context", ""):
                d["missing_context"] = []
            else:
                d["missing_context"] = [mc.strip()]
        elif not isinstance(mc, list):
            d["missing_context"] = []

        # 7. confidence
        conf = str(d.get("confidence", "medium")).lower().strip()
        if conf not in ("high", "medium", "low"):
            conf = "medium"
        d["confidence"] = conf

        # 8. detailed_explanation
        de = d.get("detailed_explanation")
        if isinstance(de, list):
            d["detailed_explanation"] = "\n\n".join(str(x) for x in de if str(x).strip())
        elif isinstance(de, str):
            d["detailed_explanation"] = de.strip()

        # 9. code_output_explanation
        coe = d.get("code_output_explanation")
        if isinstance(coe, list):
            d["code_output_explanation"] = "\n\n".join(str(x) for x in coe if str(x).strip())
        elif isinstance(coe, dict):
            d["code_output_explanation"] = "\n".join(f"{k}: {v}" for k, v in coe.items())
        elif isinstance(coe, str):
            d["code_output_explanation"] = coe.strip()

        # 10. code_issues_and_solutions
        cis = d.get("code_issues_and_solutions")
        if isinstance(cis, str):
            d["code_issues_and_solutions"] = [part.strip() for part in cis.split("\n") if part.strip()]
        elif isinstance(cis, dict):
            d["code_issues_and_solutions"] = [f"{k}: {v}" for k, v in cis.items()]
        elif not isinstance(cis, list):
            d["code_issues_and_solutions"] = []

        # 11. corrected_code
        cc = d.get("corrected_code")
        if isinstance(cc, str):
            d["corrected_code"] = cc.strip()

        # 12. execution_flow & related_files
        ef = d.get("execution_flow")
        if isinstance(ef, str):
            d["execution_flow"] = [part.strip() for part in ef.split("\n") if part.strip()]
        elif not isinstance(ef, list):
            d["execution_flow"] = []

        rf = d.get("related_files")
        if isinstance(rf, str):
            d["related_files"] = [part.strip() for part in rf.split("\n") if part.strip()]
        elif not isinstance(rf, list):
            d["related_files"] = []

        return d

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
    stage_metrics: dict[str, Any] | None = None


# ---------------------------------------------------------------------------
# Feature 2: Dedicated Bug Detection Schemas (Day 3 Contract)
# ---------------------------------------------------------------------------

class BugDetectionRequest(BaseModel):
    """Request body for `POST /api/v1/repositories/{repository_id}/detect-bugs`."""

    target: AnalysisTarget
    options: AnalysisOptions = Field(
        default_factory=lambda: AnalysisOptions(max_context_tokens=DEFAULT_BUGS_CONTEXT_TOKENS)
    )
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
    scan_mode: str = Field(
        default="standard",
        description="Scan mode: 'quick', 'standard', 'deep', or 'change'.",
    )
    changed_files: list[str] = Field(
        default_factory=list,
        description="Optional list of changed files for change/regression scan scope.",
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
    provenance: str | None = Field(
        default=None,
        description="Finding origin provenance: 'static_rule', 'llm', or 'combined'.",
    )
    rule_version: str | None = Field(
        default=None,
        max_length=64,
        description="Static rule or analyzer version.",
    )
    model_version: str | None = Field(
        default=None,
        max_length=128,
        description="LLM provider or model name when AI-generated.",
    )
    deduplication_key: str | None = Field(
        default=None,
        max_length=256,
        description="Stable deduplication key across runs and engines.",
    )
    evidence_hash: str | None = Field(
        default=None,
        max_length=64,
        description="Cryptographic SHA-256 hash of the evidence snippet.",
    )
    priority_score: int | None = Field(
        default=None,
        ge=0,
        le=100,
        description="Calculated 0-100 bug priority based on severity, reachability, exploitability, blast radius, confidence.",
    )
    evidence_level: str = Field(
        default="SUSPECTED",
        description="Validation evidence level: PROVEN, STRONG, SUSPECTED, or NEEDS_CONTEXT.",
    )
    dependency_trace: list[str] = Field(
        default_factory=list,
        description="Cross-file caller/callee trace connecting source to sink.",
    )
    counterevidence: list[str] = Field(
        default_factory=list,
        description="Guards, tests, or sanitizers inspected during counterevidence validation.",
    )
    reproduction_status: str = Field(
        default="NOT_TESTED",
        description="Reproduction status: NOT_TESTED, REPRODUCED, or REPRODUCTION_FAILED.",
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
    stage_metrics: dict[str, Any] | None = None


# ---------------------------------------------------------------------------
# Feature 3: Framework-Aware Test Generation Schemas (Day 4 Contract)
# ---------------------------------------------------------------------------

TestRequirementCategory = Literal[
    "functional",
    "boundary",
    "negative",
    "exception_handling",
    "integration",
    "api_contract",
    "security",
    "state_lifecycle",
    "concurrency",
    "regression",
    "performance",
    "configuration",
    "frontend",
    "end_to_end",
]

TestRequirementStatus = Literal[
    "COVERED",
    "PARTIAL",
    "MISSING",
    "BLOCKED",
    "NOT_APPLICABLE",
]

TestRequirementPriority = Literal[
    "CRITICAL",
    "HIGH",
    "MEDIUM",
    "LOW",
]


class TestRequirement(BaseModel):
    """Repository-wide discovered test requirement (task.md §2, §3)."""

    __test__ = False

    requirement_id: str = Field(..., description="Unique requirement ID, e.g. REQ-AUTH-001")
    title: str = Field(..., min_length=1, max_length=256)
    category: TestRequirementCategory | str = Field(default="functional")
    priority: TestRequirementPriority | str = Field(default="MEDIUM")
    source_files: list[str] = Field(default_factory=list)
    source_symbols: list[str] = Field(default_factory=list)
    expected_behavior: str = Field(..., description="Expected normal or failure behavior")
    evidence: list[str] = Field(default_factory=list, description="Evidence supporting discovery or coverage")
    status: TestRequirementStatus | str = Field(
        default="MISSING",
        description="Requirement coverage status (COVERED, PARTIAL, MISSING, BLOCKED, NOT_APPLICABLE)",
    )
    target_line: int | None = Field(default=None, description="Relevant source line number if applicable")
    reason: str | None = Field(default=None, description="Explanation for status or exclusion")


class TestQualityReport(BaseModel):
    """Quality scorecard for generated and existing repository tests (task.md §8)."""

    __test__ = False

    requirement_coverage_percent: float | None = Field(default=None, ge=0.0, le=100.0)
    line_coverage_percent: float | None = Field(default=None, ge=0.0, le=100.0)
    branch_coverage_percent: float | None = Field(default=None, ge=0.0, le=100.0)
    mutation_score_percent: float | None = Field(default=None, ge=0.0, le=100.0)
    duplicate_test_count: int = Field(default=0, ge=0)
    flaky_test_count: int = Field(default=0, ge=0)
    weak_assertion_count: int = Field(default=0, ge=0)
    untested_critical_requirements: list[str] = Field(default_factory=list)
    quality_score: float | None = Field(default=None, ge=0.0, le=100.0)
    summary_notes: list[str] = Field(default_factory=list)


class TestGenerationRequest(BaseModel):
    """Request body for `POST /api/v1/repositories/{repository_id}/generate-tests`."""

    __test__ = False

    target: AnalysisTarget
    options: AnalysisOptions = Field(
        default_factory=lambda: AnalysisOptions(max_context_tokens=DEFAULT_TESTS_CONTEXT_TOKENS)
    )
    framework: SupportedTestFramework | None = Field(
        default=None,
        description="Optional explicit test framework override ('pytest', 'unittest', 'jest').",
    )
    generation_mode: Literal["full_repository", "targeted", "change_based"] = Field(
        default="targeted",
        description="Test generation scope: 'full_repository', 'targeted', or 'change_based'.",
    )
    changed_files: list[str] = Field(
        default_factory=list,
        description="Changed files to evaluate for 'change_based' mode.",
    )
    focus_categories: list[str] = Field(
        default_factory=list,
        description="Optional filter for specific requirement categories (e.g. security, boundary).",
    )
    commit_sha: str | None = Field(
        default=None,
        description="Specific commit SHA to pin analysis context.",
    )
    run_isolated_execution: bool = Field(
        default=True,
        description="Whether to execute generated tests in isolated sandbox runner.",
    )

    @model_validator(mode="before")
    @classmethod
    def _coerce_flat_request(cls, data: Any) -> Any:
        return _normalize_code_target_payload(data)


class TestScenario(BaseModel):
    """Summary of a single test scenario included in the generated test file."""

    __test__ = False

    name: str = Field(..., min_length=1, max_length=256)
    category: Literal["normal", "edge_case", "failure_path"] = Field(default="normal")
    description: str = Field(..., min_length=1)


class TestGenerationResult(BaseModel):
    """Structured test generation output (Docs/week2.md §8)."""

    __test__ = False

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
    validation_stage: str = Field(
        default="generated and statically validated",
        description="Truthful validation status: e.g. 'generated and statically validated', 'not executed', or 'verified passing' if sandboxed.",
    )
    schema_valid: bool = Field(
        default=True,
        description="Whether the generated output strictly conforms to the expected schema.",
    )
    code_syntactically_valid: bool = Field(
        default=True,
        description="Whether the generated test source parses cleanly without syntax errors.",
    )
    framework_recognized: bool = Field(
        default=True,
        description="Whether test runner conventions and imports match the detected repository framework.",
    )
    execution_attempted: bool = Field(
        default=False,
        description="Whether sandboxed test execution was attempted.",
    )
    execution_status: str = Field(
        default="NOT_EXECUTED",
        description="Outcome of execution: 'NOT_EXECUTED', 'PASSED', 'FAILED', or 'TIMED_OUT'.",
    )
    sources: list[AnalysisSourceReference] = Field(
        default_factory=list,
        description="Source references used to construct the test suite.",
    )
    requirements: list[TestRequirement] = Field(
        default_factory=list,
        description="Discovered test requirements and coverage traceability (task.md §2, §6).",
    )
    quality_report: TestQualityReport | None = Field(
        default=None,
        description="Quality scorecard evaluating requirement, assertion, and execution coverage (task.md §8).",
    )
    generated_test_files: list[str] = Field(
        default_factory=list,
        description="All generated test file paths.",
    )
    missing_requirements: list[str] = Field(
        default_factory=list,
        description="Requirements remaining uncovered after generation.",
    )
    unsupported_requirements: list[str] = Field(
        default_factory=list,
        description="Requirements unsupported by current framework or runtime.",
    )
    execution_summary: dict[str, Any] = Field(
        default_factory=dict,
        description="Detailed execution statistics from restricted test runner.",
    )
    verification_status: TestVerificationStatus = Field(
        default="UNVERIFIED",
        description="Execution-verified status: 'VERIFIED', 'UNVERIFIED', 'REJECTED', or 'EXECUTION_ERROR'.",
    )
    verification_reasons: list[str] = Field(
        default_factory=list,
        description="Specific reasons explaining the verification classification.",
    )
    stability_report: StabilityReport | None = Field(
        default=None,
        description="Three-consecutive-run stability and flakiness report (task.md §4.6).",
    )
    coverage_report: CoverageReport | None = Field(
        default=None,
        description="Runtime coverage delta report comparing baseline to post-generation (task.md §5).",
    )
    iteration_report: IterationReport | None = Field(
        default=None,
        description="Report on coverage-guided iterative test generation rounds (task.md §6).",
    )
    raw_execution_output: str | None = Field(
        default=None,
        description="Sanitized and redacted terminal output from sandboxed test execution.",
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

    __test__ = False

    run_id: str
    repository_id: str
    status: AnalysisStatus = "COMPLETED"
    target: AnalysisTarget
    revision: str | None = None
    result: TestGenerationResult
    created_at: datetime = Field(default_factory=_utc_now)
    stage_metrics: dict[str, Any] | None = None


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
            if self.diff is not None and not self.diff.strip():
                raise ValueError("target.diff must be a non-empty unified diff when type='diff'.")
        return self


class CodeReviewRequest(BaseModel):
    """Request body for `POST /api/v1/repositories/{repository_id}/review`."""

    target: ReviewTarget
    options: AnalysisOptions = Field(
        default_factory=lambda: AnalysisOptions(max_context_tokens=DEFAULT_REVIEW_CONTEXT_TOKENS)
    )
    include_static: bool = Field(
        default=True,
        description="Run static linters and secret checks on reviewed files.",
    )

    @model_validator(mode="after")
    def _require_diff_on_request(self) -> "CodeReviewRequest":
        if self.target.type == "diff" and (not self.target.diff or not self.target.diff.strip()):
            raise ValueError("target.diff must be a non-empty unified diff when type='diff'.")
        return self

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
    provenance: str | None = Field(
        default=None,
        description="Finding origin provenance: 'static_rule', 'llm', or 'combined'.",
    )
    rule_version: str | None = Field(
        default=None,
        max_length=64,
        description="Static rule or analyzer version.",
    )
    model_version: str | None = Field(
        default=None,
        max_length=128,
        description="LLM provider or model name when AI-generated.",
    )
    deduplication_key: str | None = Field(
        default=None,
        max_length=256,
        description="Stable deduplication key across runs and engines.",
    )
    evidence_hash: str | None = Field(
        default=None,
        max_length=64,
        description="Cryptographic SHA-256 hash of the evidence snippet.",
    )
    priority_score: int | None = Field(
        default=None,
        ge=0,
        le=100,
        description="Calculated 0-100 bug priority based on severity, reachability, exploitability, blast radius, confidence.",
    )
    evidence_level: str = Field(
        default="SUSPECTED",
        description="Validation evidence level: PROVEN, STRONG, SUSPECTED, or NEEDS_CONTEXT.",
    )
    dependency_trace: list[str] = Field(
        default_factory=list,
        description="Cross-file caller/callee trace connecting source to sink.",
    )
    counterevidence: list[str] = Field(
        default_factory=list,
        description="Guards, tests, or sanitizers inspected during counterevidence validation.",
    )
    reproduction_status: str = Field(
        default="NOT_TESTED",
        description="Reproduction status: NOT_TESTED, REPRODUCED, or REPRODUCTION_FAILED.",
    )


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
    stage_metrics: dict[str, Any] | None = None


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
    test_output: str | None = None
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


class AnalysisRunMetricsSummaryResponse(BaseModel):
    """Repository-scoped Day 7 summary, integrity, and retention metrics (`GET /repositories/{id}/analysis-runs/summary`)."""

    repository_id: str
    total_runs: int = 0
    by_feature: dict[str, int] = Field(default_factory=dict)
    by_status: dict[str, int] = Field(default_factory=dict)
    total_findings: int = 0
    integrity_status: str = "CLEAN"
    integrity_issues_count: int = 0
    retention: dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Code Review Publication, Feedback & Settings Schemas (F14)
# ---------------------------------------------------------------------------

class ReviewPublicationRequest(BaseModel):
    """Payload to trigger manual publication of a code review run to a GitHub PR."""

    run_id: str | None = None
    pr_number: int
    commit_sha: str | None = None
    force_publish: bool = True
    max_comments: int = Field(default=15, ge=1, le=50)
    min_confidence: str = Field(default="medium")
    changed_lines_only: bool = True


class ReviewPublicationResponse(BaseModel):
    """Result of publishing a code review run to a GitHub PR."""

    status: str
    review_id: int | None = None
    pr_number: int | None = None
    commit_sha: str | None = None
    published_comments_count: int = 0
    skipped_reason: str | None = None
    error_message: str | None = None
    published_at: datetime | None = None


class ReviewFeedbackRequest(BaseModel):
    """Developer feedback on an individual review finding (AutoCommenter)."""

    feedback_type: Literal["useful", "not_useful", "false_positive", "already_fixed", "dismissed"]
    comment: str | None = Field(default=None, max_length=1000)


class ReviewFeedbackResponse(BaseModel):
    """Feedback submission outcome with updated repository stats."""

    finding_id: str
    feedback_type: str
    user_id: str | None = None
    comment: str | None = None
    updated_at: str
    repository_stats: dict[str, Any] | None = None


class ReviewSettingsResponse(BaseModel):
    """Repository-level code review and publication configuration."""

    repository_id: str
    pr_review_enabled: bool = False
    pr_review_drafts: bool = False
    min_confidence: str = "medium"
    max_comments: int = 15
    changed_lines_only: bool = True


class UpdateReviewSettingsRequest(BaseModel):
    """Update repository-level review configuration."""

    pr_review_enabled: bool | None = None
    pr_review_drafts: bool | None = None
    min_confidence: str | None = None
    max_comments: int | None = Field(default=None, ge=1, le=50)
    changed_lines_only: bool | None = None
