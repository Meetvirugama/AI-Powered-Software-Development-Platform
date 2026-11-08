# API & Database Schema Changes

---

## 1. Pydantic Model Extensions (`backend/app/schemas/analysis.py`)

### 1.1 SupportedTestFramework
Extended from `Literal["pytest", "unittest", "jest"]` to:
```python
SupportedTestFramework = Literal["pytest", "unittest", "jest", "vitest"]
```

### 1.2 TestVerificationStatus
```python
TestVerificationStatus = Literal["VERIFIED", "UNVERIFIED", "REJECTED", "EXECUTION_ERROR"]
```

### 1.3 Stability Models
```python
class StabilityRunResult(BaseModel):
    run_number: int = Field(..., ge=1, le=10)
    passed: bool = Field(...)
    exit_code: int = Field(default=0)
    duration_seconds: float = Field(default=0.0, ge=0.0)
    passed_count: int = Field(default=0, ge=0)
    failed_count: int = Field(default=0, ge=0)
    error_message: str | None = Field(default=None)

class StabilityReport(BaseModel):
    total_runs: int = Field(default=3, ge=1)
    passed_runs: int = Field(default=0, ge=0)
    classification: Literal["STABLE", "UNSTABLE", "FAILED"] = Field(default="FAILED")
    is_stable: bool = Field(default=False)
    runs: list[StabilityRunResult] = Field(default_factory=list)
```

### 1.4 Coverage Report Model
```python
class CoverageReport(BaseModel):
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
```

### 1.5 Iteration Models
```python
class IterationRound(BaseModel):
    round_number: int = Field(..., ge=1, le=10)
    scenarios_targeted: list[str] = Field(default_factory=list)
    uncovered_lines_addressed: list[int] = Field(default_factory=list)
    tests_added: int = Field(default=0, ge=0)
    line_coverage_after: float | None = Field(default=None)
    tokens_used: int | None = Field(default=None)

class IterationReport(BaseModel):
    total_rounds: int = Field(default=1, ge=1)
    rounds: list[IterationRound] = Field(default_factory=list)
    stopping_reason: str = Field(default="Initial generation complete")
    final_coverage_achieved: float | None = Field(default=None)
```

### 1.6 `TestGenerationResult` New Fields
Added backward-compatible optional fields:
- `verification_status: TestVerificationStatus = "UNVERIFIED"`
- `verification_reasons: list[str] = []`
- `stability_report: StabilityReport | None = None`
- `coverage_report: CoverageReport | None = None`
- `iteration_report: IterationReport | None = None`
- `raw_execution_output: str | None = None`

---

## 2. Backward Compatibility Assessment
All added fields on `TestGenerationResult` provide safe defaults. Existing callers reading `test_content`, `detected_framework`, or `covered_scenarios` continue working without modification.
