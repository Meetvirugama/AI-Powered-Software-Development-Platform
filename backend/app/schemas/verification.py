"""Independent Verification & Review Contract Schemas.

Owner: Dev — Week 3 Day 1 & Day 5 Deliverable (Docs/daily_tasks.md line 644 & Docs/week3.md §6 F36)
Reference: Docs/week3.md §6 (F36 — Independent Verification and Final Review)

Responsibilities:
1. Define VerificationCheckItem schema tracking tests, static analysis, security scans, and AI reviews.
2. Define VerificationFinding with severity, rule metadata, and file path safety.
3. Define VerificationContext grouping all inputs needed by the IndependentVerifier engine.
4. Enforce strict verification policies:
   - Any check marked as UNAVAILABLE or SKIPPED cannot be counted as PASSED.
   - If static analysis or tests are unavailable, overall status CANNOT be PASS.
   - Blocking security or policy findings prevent publication approval.
   - A failed verification check prevents PASS status.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.core.input_security import UnsafePathError, validate_repo_relative_path
from app.schemas.analysis import FindingSeverity

# Regex to make sure git commit SHAs look like valid hex strings (7 to 64 characters long)
_COMMIT_SHA_RE = re.compile(r"^[0-9a-fA-F]{7,64}$")

# Possible statuses for an individual check item
VerificationCheckStatus = Literal["PASSED", "FAILED", "SKIPPED", "UNAVAILABLE", "COMPLETED"]

# Possible final overall verdicts for the entire verification suite
VerificationOverallStatus = Literal["PASS", "FAIL", "INCONCLUSIVE", "REQUIRES_HUMAN_REVIEW"]


class VerificationFinding(BaseModel):
    """Normalized finding discovered during verification checks.

    This represents a single issue, warning, or defect found during verification.
    """

    model_config = ConfigDict(from_attributes=True)

    # Unique identifier for this finding (e.g. 'sec-001', 'lint-042')
    id: str = Field(..., min_length=1, max_length=128, description="Unique finding ID.")

    # How severe this finding is: CRITICAL, HIGH, MEDIUM, LOW, or INFO
    severity: FindingSeverity = Field(
        default="MEDIUM",
        description="Finding severity: CRITICAL, HIGH, MEDIUM, LOW, or INFO.",
    )

    # What type of issue this is (e.g. 'security', 'correctness', 'policy', 'lint')
    category: str = Field(
        ...,
        min_length=1,
        max_length=64,
        description="Category, e.g. security, correctness, lint, policy, or test_failure.",
    )

    # Human-readable explanation of what was found
    message: str = Field(..., min_length=1, description="Descriptive explanation of the finding.")

    # The file where this issue was spotted (relative to repository root)
    file_path: str | None = Field(
        default=None,
        description="Repository-relative file path if bound to a file.",
    )

    # The exact line number in the file, if known (1-indexed)
    line_number: int | None = Field(
        default=None,
        ge=1,
        description="1-indexed line number if traceable to a line.",
    )

    # Specific scanner rule ID if applicable (e.g. 'B101' for Bandit, 'F401' for Flake8)
    rule_id: str | None = Field(
        default=None,
        max_length=128,
        description="Linter or scanner rule ID, e.g. 'B101' (Bandit) or 'F401' (Flake8).",
    )

    # If True, this finding is serious enough to completely block opening a pull request
    blocking: bool = Field(
        default=False,
        description="True if this finding strictly blocks publication.",
    )

    @field_validator("file_path")
    @classmethod
    def _validate_file_path(cls, value: str | None) -> str | None:
        """Simple check: validate repo path or keep cleaned string if reporting an invalid path."""
        if value is None:
            return None
        value = value.strip()
        if not value:
            return None
        try:
            return validate_repo_relative_path(value)
        except UnsafePathError:
            # If a security finding is reporting an unsafe path (like ../../etc/passwd),
            # we keep the cleaned string so the finding can describe the violation without crashing.
            return value.replace("\\", "/").strip()


class VerificationCheckItem(BaseModel):
    """Individual verification gate check (tests, static analysis, review, etc.).

    Each of the 12 checks evaluated by the IndependentVerifier produces one of these items.
    """

    # Name of the check (e.g. 'tests', 'secret_scan', 'plan_approval', 'branch_protection')
    name: str = Field(
        ...,
        min_length=1,
        max_length=64,
        description="Name of the check, e.g. 'tests', 'static_analysis', 'ai_code_review', 'secret_scan'.",
    )

    # Status of this check: PASSED, FAILED, SKIPPED, UNAVAILABLE, or COMPLETED
    status: VerificationCheckStatus = Field(
        ...,
        description="Status: PASSED, FAILED, SKIPPED, UNAVAILABLE, or COMPLETED.",
    )

    # How long this check took in milliseconds
    duration_ms: int = Field(
        default=0,
        ge=0,
        description="Execution duration in milliseconds.",
    )

    # Short summary message explaining the check outcome or failure reason
    message: str = Field(
        default="",
        description="Summary result, failure reason, or skip explanation.",
    )

    # Count of how many issues this specific check found
    findings_count: int = Field(
        default=0,
        ge=0,
        description="Number of findings discovered during this check.",
    )

    # Extra diagnostic details or telemetry for this check
    details: dict[str, Any] = Field(
        default_factory=dict,
        description="Structured check-specific diagnostic telemetry.",
    )


class VerificationContext(BaseModel):
    """Input context bundle supplied to IndependentVerifier to execute all 12 checks.

    This groups all the information about the task, git branches, diff, test results,
    and security scans into one place so the verifier can inspect everything.
    """

    model_config = ConfigDict(from_attributes=True)

    # Unique task identifier
    task_id: str = Field(..., min_length=1, description="Associated task identifier.")

    # Target branch name (must NOT be main or master)
    target_branch: str = Field(
        default="agent/task-patch",
        description="Branch name where changes are committed (e.g. agent/task-123).",
    )

    # Git commit SHA the task was originally branched from
    base_revision: str = Field(..., description="Commit SHA from which task started.")

    # Final git commit SHA of the workspace changes
    verified_revision: str = Field(..., description="Final workspace commit SHA being verified.")

    # Full unified diff text containing all code modifications
    diff: str = Field(..., description="Full unified diff of candidate changes.")

    # Optional human-readable task title
    task_title: str = Field(default="", description="Short task title.")

    # Optional description of what the task intended to build or fix
    task_description: str = Field(default="", description="Detailed task goal.")

    # Whether human approval was granted for the implementation plan
    plan_approved: bool = Field(default=True, description="True if plan received human approval.")

    # The plan version that was approved by a human
    approved_plan_version: int | None = Field(
        default=1,
        description="Plan version number that was explicitly approved.",
    )

    # Current version number of the plan
    current_plan_version: int = Field(
        default=1,
        description="Current plan version number in the database.",
    )

    # List of files the agent was permitted to touch (from approved plan)
    allowed_files: list[str] | None = Field(
        default=None,
        description="List of repository-relative files allowed to be modified.",
    )

    # List of files that MUST NEVER be modified (e.g. production configs, env files)
    forbidden_files: list[str] | None = Field(
        default=None,
        description="List of repository-relative files forbidden from modification.",
    )

    # Test run results: did test suite complete?
    tests_completed: bool = Field(default=True, description="True if test runner finished execution.")

    # Did the test suite pass with zero failures?
    tests_passed: bool = Field(default=True, description="True if all tests passed successfully.")

    # Revision SHA when tests were executed (must match verified_revision)
    test_revision: str | None = Field(
        default=None,
        description="Git revision SHA at the time tests were executed.",
    )

    # Number of tests executed
    test_count: int = Field(default=0, ge=0, description="Total number of tests run.")

    # Number of tests that failed
    failed_test_count: int = Field(default=0, ge=0, description="Number of failed tests.")

    # Did static analysis / linter run?
    static_analysis_completed: bool = Field(
        default=True,
        description="True if static analysis (linters/security scanners) completed.",
    )

    # Findings produced by static analysis
    static_findings: list[VerificationFinding] = Field(
        default_factory=list,
        description="List of findings from static analysis / linters.",
    )

    # Did Week 2 AI Code Review run?
    ai_review_completed: bool = Field(
        default=True,
        description="True if Week 2 AI Code Review completed.",
    )

    # Findings produced by Week 2 AI Code Review
    ai_review_findings: list[VerificationFinding] = Field(
        default_factory=list,
        description="List of findings from AI code review.",
    )

    # Resource budget checks: tokens used vs token budget
    tokens_used: int = Field(default=0, ge=0, description="Total LLM tokens consumed by task.")
    token_budget: int = Field(default=50000, ge=1, description="Maximum token budget allocated.")

    # Execution time in seconds vs timeout limit
    execution_time_s: float = Field(default=0.0, ge=0.0, description="Task execution time in seconds.")
    timeout_s: float = Field(default=300.0, ge=1.0, description="Task timeout limit in seconds.")


class VerificationResult(BaseModel):
    """Independent verification result envelope matching Docs/week3.md §6 F36.

    This is the official outcome report produced after all 12 checks are completed.
    """

    task_id: str = Field(..., min_length=1, description="Associated task identifier.")
    verified_revision: str = Field(..., description="Commit SHA verified.")
    status: VerificationOverallStatus = Field(..., description="Overall verification verdict.")
    checks: list[VerificationCheckItem] = Field(
        ...,
        min_length=1,
        description="List of verification check items evaluated.",
    )
    blocking_findings: list[VerificationFinding] = Field(
        default_factory=list,
        description="Findings that block publication approval.",
    )
    warnings: list[VerificationFinding] = Field(
        default_factory=list,
        description="Non-blocking observations or warnings.",
    )
    pr_summary: str = Field(
        default="",
        description="Summary of changes and verification outcome for PR publication.",
    )
    created_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    @field_validator("verified_revision")
    @classmethod
    def _validate_verified_revision(cls, value: str) -> str:
        """Simple check: verify that the commit SHA is a valid hex string."""
        value = value.strip()
        if not _COMMIT_SHA_RE.match(value):
            raise ValueError(f"Invalid verified_revision commit SHA format: '{value}'")
        return value

    @model_validator(mode="after")
    def _enforce_verification_policies(self) -> "VerificationResult":
        """Enforce strict verification policies per Docs/week3.md §6.

        Plain-English Rules:
        1. A check marked UNAVAILABLE or SKIPPED cannot be counted as PASSED.
        2. If any check FAILED, overall status CANNOT be PASS.
        3. If any check is UNAVAILABLE or SKIPPED, overall status CANNOT be PASS.
        4. If there are any blocking findings (like hardcoded secrets), status CANNOT be PASS.
        """
        failed_checks = [c.name for c in self.checks if c.status == "FAILED"]
        unavailable_or_skipped = [
            c.name for c in self.checks if c.status in ("UNAVAILABLE", "SKIPPED")
        ]

        if self.status == "PASS":
            if failed_checks:
                raise ValueError(
                    f"Overall status cannot be 'PASS' when check(s) failed: {', '.join(failed_checks)}"
                )
            if unavailable_or_skipped:
                raise ValueError(
                    f"Overall status cannot be 'PASS' when check(s) are UNAVAILABLE or SKIPPED: "
                    f"{', '.join(unavailable_or_skipped)}"
                )
            if self.blocking_findings:
                raise ValueError(
                    f"Overall status cannot be 'PASS' with {len(self.blocking_findings)} blocking finding(s)."
                )

        if failed_checks and self.status not in ("FAIL", "REQUIRES_HUMAN_REVIEW"):
            raise ValueError(
                f"Status must be 'FAIL' or 'REQUIRES_HUMAN_REVIEW' when check(s) failed: {', '.join(failed_checks)}"
            )

        return self

    @classmethod
    def evaluate_status(
        cls,
        checks: list[VerificationCheckItem],
        blocking_findings: list[VerificationFinding] | None = None,
        warnings: list[VerificationFinding] | None = None,
    ) -> VerificationOverallStatus:
        """Derive the canonical VerificationOverallStatus from check outcomes and findings.

        Simple Logic:
        - If any check failed or there are blocking findings -> 'FAIL'.
        - If checks were skipped/unavailable -> 'REQUIRES_HUMAN_REVIEW' or 'INCONCLUSIVE'.
        - If there are non-blocking warnings -> 'REQUIRES_HUMAN_REVIEW'.
        - Only if everything passed with zero blockers and zero warnings -> 'PASS'.
        """
        blocking = blocking_findings or []
        warns = warnings or []

        has_failed = any(c.status == "FAILED" for c in checks)
        has_unavailable_or_skipped = any(c.status in ("UNAVAILABLE", "SKIPPED") for c in checks)

        if has_failed or len(blocking) > 0:
            return "FAIL"

        if has_unavailable_or_skipped:
            return "REQUIRES_HUMAN_REVIEW" if len(warns) > 0 else "INCONCLUSIVE"

        if len(warns) > 0:
            return "REQUIRES_HUMAN_REVIEW"

        return "PASS"

    @property
    def is_eligible_for_publication(self) -> bool:
        """Return True if verdict allows human publication approval (PASS or reviewable with 0 blockers)."""
        return self.status in ("PASS", "REQUIRES_HUMAN_REVIEW") and len(self.blocking_findings) == 0

    @property
    def is_passing(self) -> bool:
        """Return True only if strictly PASS with zero blocking findings."""
        return self.status == "PASS" and len(self.blocking_findings) == 0

    @property
    def is_pass(self) -> bool:
        """Alias for is_passing."""
        return self.is_passing


__all__ = [
    "VerificationCheckItem",
    "VerificationCheckStatus",
    "VerificationContext",
    "VerificationFinding",
    "VerificationOverallStatus",
    "VerificationResult",
]
