"""Independent Verification & Review Contract Schemas.

Owner: Dev — Week 3 Day 1 Deliverable (Docs/daily_tasks.md line 608 & Docs/week3.md §6 F36)
Reference: Docs/week3.md §6 (F36 — Independent Verification and Final Review)

Responsibilities:
1. Define VerificationCheckItem schema tracking tests, static analysis, security scans, and AI reviews.
2. Define VerificationFinding with severity, rule metadata, and file path safety.
3. Enforce strict verification policies:
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

_COMMIT_SHA_RE = re.compile(r"^[0-9a-fA-F]{7,64}$")

VerificationCheckStatus = Literal["PASSED", "FAILED", "SKIPPED", "UNAVAILABLE", "COMPLETED"]
VerificationOverallStatus = Literal["PASS", "FAIL", "INCONCLUSIVE", "REQUIRES_HUMAN_REVIEW"]


class VerificationFinding(BaseModel):
    """Normalized finding discovered during verification checks."""

    model_config = ConfigDict(from_attributes=True)

    id: str = Field(..., min_length=1, max_length=128, description="Unique finding ID.")
    severity: FindingSeverity = Field(
        default="MEDIUM",
        description="Finding severity: CRITICAL, HIGH, MEDIUM, LOW, or INFO.",
    )
    category: str = Field(
        ...,
        min_length=1,
        max_length=64,
        description="Category, e.g. security, correctness, lint, policy, or test_failure.",
    )
    message: str = Field(..., min_length=1, description="Descriptive explanation of the finding.")
    file_path: str | None = Field(
        default=None,
        description="Repository-relative file path if bound to a file.",
    )
    line_number: int | None = Field(
        default=None,
        ge=1,
        description="1-indexed line number if traceable to a line.",
    )
    rule_id: str | None = Field(
        default=None,
        max_length=128,
        description="Linter or scanner rule ID, e.g. 'B101' (Bandit) or 'F401' (Flake8).",
    )
    blocking: bool = Field(
        default=False,
        description="True if this finding strictly blocks publication.",
    )

    @field_validator("file_path")
    @classmethod
    def _validate_file_path(cls, value: str | None) -> str | None:
        if value is None:
            return None
        try:
            return validate_repo_relative_path(value)
        except UnsafePathError as exc:
            raise ValueError(f"Unsafe finding file_path '{value}': {exc}") from exc


class VerificationCheckItem(BaseModel):
    """Individual verification gate check (tests, static analysis, review, etc.)."""

    name: str = Field(
        ...,
        min_length=1,
        max_length=64,
        description="Name of the check, e.g. 'tests', 'static_analysis', 'ai_code_review', 'secret_scan'.",
    )
    status: VerificationCheckStatus = Field(
        ...,
        description="Status: PASSED, FAILED, SKIPPED, UNAVAILABLE, or COMPLETED.",
    )
    duration_ms: int = Field(
        default=0,
        ge=0,
        description="Execution duration in milliseconds.",
    )
    message: str = Field(
        default="",
        description="Summary result, failure reason, or skip explanation.",
    )
    findings_count: int = Field(
        default=0,
        ge=0,
        description="Number of findings discovered during this check.",
    )
    details: dict[str, Any] = Field(
        default_factory=dict,
        description="Structured check-specific diagnostic telemetry.",
    )


class VerificationResult(BaseModel):
    """Independent verification result envelope matching Docs/week3.md §6 F36."""

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
        value = value.strip()
        if not _COMMIT_SHA_RE.match(value):
            raise ValueError(f"Invalid verified_revision commit SHA format: '{value}'")
        return value

    @model_validator(mode="after")
    def _enforce_verification_policies(self) -> "VerificationResult":
        """Enforce strict verification policies per Docs/week3.md §6.

        Rules:
        1. A check marked UNAVAILABLE or SKIPPED cannot be counted as PASSED.
        2. If any check is FAILED, overall status CANNOT be PASS.
        3. If any check is UNAVAILABLE or SKIPPED, overall status CANNOT be PASS.
        4. If blocking_findings is not empty, overall status CANNOT be PASS.
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
        """Derive the canonical VerificationOverallStatus from check outcomes and findings."""
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
    "VerificationFinding",
    "VerificationOverallStatus",
    "VerificationResult",
]
