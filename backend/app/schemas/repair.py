"""Failure Traceback Diagnosis and Repair Patch Validation Schemas.

Owner: Dev — Week 3 Day 4 Deliverable (Docs/daily_tasks.md line 637 & Docs/week3.md §6 F35)
Reference: Docs/week3.md §6 (F35 - Test Runner and Bounded Repair Loop)

Responsibilities:
1. Define DiagnosedFailure & TracebackDiagnosisResult schema distinguishing test failures
   (assertions, exceptions) from infrastructure errors (timeouts, missing binaries, OOM).
2. Define RepairPatchPayload and PatchValidationResult for validating proposed repair diffs
   against plan constraints, path traversal guards, secret leaks, and repeat patch loop limits.
3. Define RepairLoopState enforcing the hard ceiling of 3 task-level repair attempts.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.core.input_security import UnsafePathError, validate_repo_relative_path

FailureCategory = Literal[
    "TEST_FAILURE",
    "INFRASTRUCTURE_FAILURE",
    "SYNTAX_ERROR",
    "IMPORT_ERROR",
    "TIMEOUT",
    "ENVIRONMENT_ERROR",
]

TestFrameworkName = Literal["pytest", "unittest", "jest", "unknown"]
RepairStateStatus = Literal["IDLE", "DIAGNOSING", "REPAIRING", "TESTING", "EXHAUSTED", "RESOLVED"]

MAX_DIFF_CHARS = 200_000


class DiagnosedFailure(BaseModel):
    """Normalized diagnostic record for a single test or execution failure."""

    model_config = ConfigDict(from_attributes=True)

    failure_id: str = Field(..., min_length=1, max_length=64, description="Unique identifier for this failure.")
    category: FailureCategory = Field(
        ...,
        description="Classification: TEST_FAILURE, INFRASTRUCTURE_FAILURE, SYNTAX_ERROR, IMPORT_ERROR, TIMEOUT, ENVIRONMENT_ERROR.",
    )
    test_name: str | None = Field(
        default=None,
        description="Name of the failing test method or function (e.g. 'test_auth_tokens').",
    )
    file_path: str | None = Field(
        default=None,
        description="Repository-relative file path where the failure originated.",
    )
    line_number: int | None = Field(
        default=None,
        ge=1,
        description="1-indexed line number in the source file, or None if unavailable.",
    )
    error_type: str = Field(
        default="Error",
        max_length=128,
        description="Exception class name or error type, e.g. 'AssertionError', 'ModuleNotFoundError'.",
    )
    error_message: str = Field(
        default="",
        description="Concise description of the failure message.",
    )
    is_repairable: bool = Field(
        default=True,
        description="True if automated code repair can address this defect; False for environment/infrastructure faults.",
    )
    stack_trace_snippet: str = Field(
        default="",
        description="Sanitized and bounded stack trace or failure context snippet.",
    )
    suggested_action: str | None = Field(
        default=None,
        description="Optional repair guidance or remediation hint.",
    )

    @field_validator("file_path")
    @classmethod
    def _validate_file_path(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if not value:
            return None
        try:
            return validate_repo_relative_path(value)
        except UnsafePathError:
            # For non-repo paths (e.g. system libraries), return cleaned value without failing
            return value.replace("\\", "/").strip()


class TracebackDiagnosisResult(BaseModel):
    """Aggregate result from parsing raw test runner output."""

    model_config = ConfigDict(from_attributes=True)

    framework: TestFrameworkName = Field(
        default="unknown",
        description="Detected test framework: pytest, unittest, jest, or unknown.",
    )
    total_failed: int = Field(
        default=0,
        ge=0,
        description="Total count of distinct test or step failures identified.",
    )
    failures: list[DiagnosedFailure] = Field(
        default_factory=list,
        description="List of diagnosed individual failure points.",
    )
    has_infrastructure_failure: bool = Field(
        default=False,
        description="True if an unrepairable environment/infrastructure/timeout error occurred.",
    )
    can_attempt_repair: bool = Field(
        default=True,
        description="True if at least one repairable code defect exists and no blocking infrastructure faults occurred.",
    )
    summary: str = Field(
        default="",
        description="One-sentence diagnostic summary for logging and UI display.",
    )
    raw_exit_code: int | None = Field(
        default=None,
        description="Process exit code from test command execution.",
    )


class RepairPatchPayload(BaseModel):
    """Payload representing a proposed automated repair patch."""

    model_config = ConfigDict(from_attributes=True)

    task_id: str = Field(..., min_length=1, description="Associated task identifier.")
    attempt_number: int = Field(
        ...,
        ge=1,
        le=5,
        description="1-indexed repair attempt number (1, 2, or 3).",
    )
    diff: str = Field(
        ...,
        min_length=1,
        max_length=MAX_DIFF_CHARS,
        description="Unified diff text representing the candidate fix.",
    )
    explanation: str = Field(
        default="",
        description="Explanation of what the repair addresses.",
    )
    target_files: list[str] = Field(
        default_factory=list,
        description="Repository-relative file paths intended to be modified.",
    )
    previous_patch_hashes: list[str] = Field(
        default_factory=list,
        description="SHA-256 hashes of earlier failed repair patches to prevent identical repeat attempts.",
    )

    @field_validator("diff")
    @classmethod
    def _validate_diff_not_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Repair diff cannot be empty or whitespace.")
        return value


class PatchValidationResult(BaseModel):
    """Outcome of validating a candidate repair patch before applying it to the workspace."""

    model_config = ConfigDict(from_attributes=True)

    is_valid: bool = Field(..., description="True if patch passes all safety and policy checks.")
    rejection_reason: str | None = Field(
        default=None,
        description="Explanation if patch was rejected.",
    )
    patch_hash: str = Field(
        ...,
        description="SHA-256 content hash of the normalized diff.",
    )
    modified_files: list[str] = Field(
        default_factory=list,
        description="Repository-relative file paths extracted from diff headers.",
    )
    attempt_number: int = Field(..., ge=1, description="Current repair attempt index.")
    remaining_attempts: int = Field(
        ...,
        ge=0,
        description="Remaining repair attempts before retry budget is exhausted.",
    )
    violations: list[str] = Field(
        default_factory=list,
        description="List of specific security, boundary, or policy violations detected.",
    )


class RepairLoopState(BaseModel):
    """Persisted repair budget and attempt state matching Docs/week3.md §6 F35."""

    model_config = ConfigDict(from_attributes=True)

    task_id: str = Field(..., min_length=1, description="Associated task identifier.")
    attempts_used: int = Field(
        default=0,
        ge=0,
        description="Number of repair attempts already executed.",
    )
    max_attempts: int = Field(
        default=3,
        ge=1,
        le=5,
        description="Hard ceiling of task-level repair attempts (default 3 per Docs/week3.md §6).",
    )
    patch_hashes: list[str] = Field(
        default_factory=list,
        description="History of applied patch SHA-256 hashes.",
    )
    diagnosed_failures: list[DiagnosedFailure] = Field(
        default_factory=list,
        description="History of diagnosed failure points across repair attempts.",
    )
    status: RepairStateStatus = Field(
        default="IDLE",
        description="Current stage in the repair cycle.",
    )
    created_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    updated_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    @property
    def is_exhausted(self) -> bool:
        """Return True if repair attempt budget is exhausted."""
        return self.attempts_used >= self.max_attempts

    @property
    def remaining_budget(self) -> int:
        """Return remaining repair attempts allowed."""
        return max(0, self.max_attempts - self.attempts_used)

    def record_attempt(self, patch_hash: str) -> None:
        """Record a newly applied repair attempt and decrement budget."""
        self.attempts_used += 1
        if patch_hash not in self.patch_hashes:
            self.patch_hashes.append(patch_hash)
        if self.attempts_used >= self.max_attempts:
            self.status = "EXHAUSTED"
        else:
            self.status = "REPAIRING"
        self.updated_at = datetime.now(timezone.utc).isoformat()


__all__ = [
    "DiagnosedFailure",
    "FailureCategory",
    "MAX_DIFF_CHARS",
    "PatchValidationResult",
    "RepairLoopState",
    "RepairPatchPayload",
    "RepairStateStatus",
    "TestFrameworkName",
    "TracebackDiagnosisResult",
]

