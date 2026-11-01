"""Failure Traceback Diagnoser and Repair Patch Validator Engines.

Owner: Dev — Week 3 Day 4 Deliverable (Docs/daily_tasks.md line 637 & Docs/week3.md §6 F35)
Reference: Docs/week3.md §6 (F35 - Test Runner and Bounded Repair Loop)

Key Responsibilities:
1. FailureTracebackAnalyzer:
   - Parses raw test runner outputs across Pytest, Unittest, and Jest.
   - Extracts structured failure locations (test_name, file_path, line_number, error_type, message).
   - Distinguishes test failures from infrastructure/environment errors.
   - Cleans and redacts sensitive material from stack traces.
2. RepairPatchValidator:
   - Parses unified diffs to identify modified files.
   - Enforces path traversal security and constraint boundary disjointness.
   - Enforces the hard ceiling of 3 task-level repair attempts (Docs/week3.md §6).
   - Detects and rejects identical repeat patches using SHA-256 content hashing.
   - Scans diffs for leaked credentials using secret redaction rules.
"""

from __future__ import annotations

import hashlib
import re
from typing import Any

from app.core.input_security import UnsafePathError, validate_repo_relative_path
from app.core.secret_redaction import redact, redact_secrets
from app.schemas.repair import (
    DiagnosedFailure,
    FailureCategory,
    MAX_DIFF_CHARS,
    PatchValidationResult,
    RepairPatchPayload,
    TestFrameworkName,
    TracebackDiagnosisResult,
)

# ---------------------------------------------------------------------------
# Regex Patterns for Test Runners & Stack Traces
# ---------------------------------------------------------------------------

# Pytest patterns
_PYTEST_FAILED_LINE_RE = re.compile(
    r"FAILED\s+([^\s:]+)::([^\s]+)\s+-\s+([A-Za-z0-9_.]+(?:Error|Exception|Failure)):\s*(.*)",
    re.MULTILINE,
)
_PYTEST_FILE_LINE_RE = re.compile(
    r"^(?:[A-Za-z]:)?([^\s:]+\.py):(\d+):\s+([A-Za-z0-9_.]+(?:Error|Exception|Failure))",
    re.MULTILINE,
)
_PYTEST_ERROR_COLLECTING_RE = re.compile(
    r"ERROR\s+(?:collecting\s+)?([^\s:]+)\s*-\s*([A-Za-z0-9_.]+(?:Error|Exception|Failure)):\s*(.*)",
    re.MULTILINE,
)

# Unittest patterns
_UNITTEST_FAIL_LINE_RE = re.compile(
    r"^(?:FAIL|ERROR):\s+([^\s(]+)\s*\((?:[^\s)]+\.)?([^\s)]+)\)",
    re.MULTILINE,
)
_TRACEBACK_FILE_LINE_RE = re.compile(
    r'File\s+["\']([^"\']+)["\'],\s+line\s+(\d+)(?:,\s+in\s+([A-Za-z0-9_]+))?',
    re.MULTILINE,
)

# Jest patterns
_JEST_FAIL_TEST_RE = re.compile(r"●\s+(.*?)\s*›\s*(.+)", re.MULTILINE)
_JEST_AT_FILE_RE = re.compile(r"at\s+.*?\((.*?):(\d+):(\d+)\)", re.MULTILINE)

# Infrastructure error indicators (unrepairable by code fixes)
_INFRASTRUCTURE_PATTERNS = [
    (re.compile(r"TimeoutExpired|timed out|execution timed out", re.IGNORECASE), "TIMEOUT", "Command timed out during test execution."),
    (re.compile(r"command not found|did not find executable|is not recognized as", re.IGNORECASE), "ENVIRONMENT_ERROR", "Test runner command or binary not found in execution environment."),
    (re.compile(r"PermissionDenied|Access is denied|PermissionError", re.IGNORECASE), "ENVIRONMENT_ERROR", "File or process permission denied in sandbox."),
    (re.compile(r"OutOfMemory|MemoryError|heap out of memory", re.IGNORECASE), "ENVIRONMENT_ERROR", "Process exceeded memory limits during test run."),
    (re.compile(r"ConnectionRefused|ECONNREFUSED|network is unreachable", re.IGNORECASE), "ENVIRONMENT_ERROR", "Network connection refused; network access is restricted."),
]

# Code collection error indicators (repairable by code fixes)
_CODE_ERROR_PATTERNS = [
    (re.compile(r"SyntaxError:\s*(.+)", re.IGNORECASE), "SYNTAX_ERROR", "Source code syntax error detected."),
    (re.compile(r"(?:ModuleNotFoundError|ImportError):\s*(.+)", re.IGNORECASE), "IMPORT_ERROR", "Missing module or import error."),
]


# ---------------------------------------------------------------------------
# Diff Parsing Helpers
# ---------------------------------------------------------------------------

def extract_modified_files_from_diff(diff_text: str) -> list[str]:
    """Parse a unified diff and extract unique repo-relative file paths.

    Correctly handles '+++ b/path', '--- a/path', timestamps, and /dev/null.

    Args:
        diff_text: Raw unified diff string.

    Returns:
        list[str]: Cleaned list of repo-relative modified file paths.
    """
    files: set[str] = set()
    for line in diff_text.splitlines():
        if line.startswith("+++ ") or line.startswith("--- "):
            parts = line.split()
            if len(parts) >= 2:
                raw_path = parts[1].strip()
                if raw_path.startswith("a/") or raw_path.startswith("b/"):
                    raw_path = raw_path[2:]
                raw_path = raw_path.replace("\\", "/").lstrip("/")
                if raw_path and raw_path != "dev/null":
                    files.add(raw_path)

    return sorted(files)


def compute_normalized_patch_hash(diff_text: str) -> str:
    """Compute a deterministic SHA-256 hash of a normalized diff.

    Whitespace is collapsed so trivial indentation or newline differences in
    identical code repairs are caught by loop detection.
    """
    normalized = re.sub(r"\s+", " ", diff_text.strip())
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# 1. Failure Traceback Analyzer
# ---------------------------------------------------------------------------

class FailureTracebackAnalyzer:
    """Parser and diagnoser for test runner and execution failure tracebacks."""

    def diagnose(
        self,
        raw_output: str,
        framework: TestFrameworkName | None = None,
        exit_code: int | None = None,
    ) -> TracebackDiagnosisResult:
        """Parse raw process output and return a structured diagnostic verdict.

        Args:
            raw_output: Stdout/stderr string from test execution.
            framework: Optional hint ("pytest", "unittest", "jest", or None for auto-detect).
            exit_code: Optional process exit code.

        Returns:
            TracebackDiagnosisResult: Structured failures and repairability assessment.
        """
        sanitized_output = redact(raw_output)
        detected_framework = framework or self._detect_framework(sanitized_output)

        # 1. Check for infrastructure faults first
        infra_failure = self._detect_infrastructure_failure(sanitized_output)

        failures: list[DiagnosedFailure] = []
        if detected_framework == "pytest":
            failures = self._parse_pytest(sanitized_output)
        elif detected_framework == "unittest":
            failures = self._parse_unittest(sanitized_output)
        elif detected_framework == "jest":
            failures = self._parse_jest(sanitized_output)
        else:
            failures = self._parse_generic(sanitized_output)

        # If infrastructure failure was found, prepend it
        has_infra = infra_failure is not None
        if infra_failure and not any(f.category in ("INFRASTRUCTURE_FAILURE", "TIMEOUT", "ENVIRONMENT_ERROR") for f in failures):
            failures.insert(0, infra_failure)

        # If no specific failures parsed but exit code indicates error
        if not failures and (exit_code is not None and exit_code != 0):
            generic_cat: FailureCategory = "INFRASTRUCTURE_FAILURE" if has_infra else "TEST_FAILURE"
            failures.append(
                DiagnosedFailure(
                    failure_id="fail-generic-1",
                    category=generic_cat,
                    error_type="ExecutionError",
                    error_message=f"Process exited with non-zero exit code {exit_code}",
                    is_repairable=not has_infra,
                    stack_trace_snippet=sanitized_output[-1000:].strip(),
                )
            )

        # Repairability: Can repair only if at least one repairable failure exists and no blocking infra failure
        can_repair = (
            any(f.is_repairable for f in failures)
            and not any(f.category in ("INFRASTRUCTURE_FAILURE", "ENVIRONMENT_ERROR", "TIMEOUT") for f in failures)
        )

        total_failed = len(failures)
        summary = self._generate_summary(detected_framework, failures, has_infra, can_repair)

        return TracebackDiagnosisResult(
            framework=detected_framework,
            total_failed=total_failed,
            failures=failures,
            has_infrastructure_failure=has_infra,
            can_attempt_repair=can_repair,
            summary=summary,
            raw_exit_code=exit_code,
        )

    def _detect_framework(self, output: str) -> TestFrameworkName:
        """Infer test framework from output signatures."""
        if (
            "pytest" in output
            or "=== FAILURES ===" in output
            or "== short test summary info ==" in output
            or re.search(r"FAILED\s+[^\s:]+::", output)
            or "Interrupted: 1 error during collection" in output
        ):
            return "pytest"
        if "FAIL: " in output or ("Ran " in output and "in " in output and "FAILED (failures=" in output):
            return "unittest"
        if "● " in output or ("FAIL " in output and ("test.js" in output or "test.ts" in output or "Jest" in output)):
            return "jest"
        return "unknown"

    def _detect_infrastructure_failure(self, output: str) -> DiagnosedFailure | None:
        """Inspect output for genuine environment/infrastructure patterns."""
        for pattern, cat_name, desc in _INFRASTRUCTURE_PATTERNS:
            match = pattern.search(output)
            if match:
                matched_text = match.group(0)
                category: FailureCategory = cat_name  # type: ignore[assignment]
                return DiagnosedFailure(
                    failure_id=f"fail-{category.lower()}-1",
                    category=category,
                    error_type=matched_text,
                    error_message=desc,
                    is_repairable=False,
                    stack_trace_snippet=output[max(0, match.start() - 200) : min(len(output), match.end() + 200)].strip(),
                )
        return None

    def _parse_pytest(self, output: str) -> list[DiagnosedFailure]:
        """Parse Pytest formatted failure output."""
        failures: list[DiagnosedFailure] = []
        idx = 1

        # 1. Match short summary lines: FAILED path/to/test.py::test_fn - AssertionError: msg
        for match in _PYTEST_FAILED_LINE_RE.finditer(output):
            file_path, test_name, err_type, err_msg = match.groups()
            cat: FailureCategory = "TEST_FAILURE"
            if "SyntaxError" in err_type:
                cat = "SYNTAX_ERROR"
            elif "ImportError" in err_type or "ModuleNotFoundError" in err_type:
                cat = "IMPORT_ERROR"

            failures.append(
                DiagnosedFailure(
                    failure_id=f"pytest-{idx}",
                    category=cat,
                    test_name=test_name.strip(),
                    file_path=file_path.strip(),
                    error_type=err_type.strip(),
                    error_message=err_msg.strip(),
                    is_repairable=True,
                    stack_trace_snippet=match.group(0),
                    suggested_action=f"Inspect assertion or logic in {file_path}",
                )
            )
            idx += 1

        # 2. Match collection errors: ERROR collecting path/to/file.py - SyntaxError: msg
        for match in _PYTEST_ERROR_COLLECTING_RE.finditer(output):
            file_path, err_type, err_msg = match.groups()
            cat: FailureCategory = "TEST_FAILURE"
            if "SyntaxError" in err_type:
                cat = "SYNTAX_ERROR"
            elif "ImportError" in err_type or "ModuleNotFoundError" in err_type:
                cat = "IMPORT_ERROR"

            failures.append(
                DiagnosedFailure(
                    failure_id=f"pytest-collect-{idx}",
                    category=cat,
                    file_path=file_path.strip(),
                    error_type=err_type.strip(),
                    error_message=err_msg.strip(),
                    is_repairable=True,
                    stack_trace_snippet=match.group(0),
                    suggested_action=f"Fix syntax or dependency issue in {file_path}",
                )
            )
            idx += 1

        # 3. Match code error patterns if collection block is formatted differently
        if not failures:
            for pattern, cat_name, desc in _CODE_ERROR_PATTERNS:
                match = pattern.search(output)
                if match:
                    err_msg = match.group(1).strip()
                    failures.append(
                        DiagnosedFailure(
                            failure_id=f"pytest-code-{idx}",
                            category=cat_name,  # type: ignore[arg-type]
                            error_type=cat_name,
                            error_message=err_msg or desc,
                            is_repairable=True,
                            stack_trace_snippet=output[max(0, match.start() - 100) : min(len(output), match.end() + 200)].strip(),
                        )
                    )
                    idx += 1

        # 4. If short summary didn't catch, parse failure blocks
        if not failures:
            for match in _PYTEST_FILE_LINE_RE.finditer(output):
                file_path, line_str, err_type = match.groups()
                cat = "SYNTAX_ERROR" if "SyntaxError" in err_type else "TEST_FAILURE"
                failures.append(
                    DiagnosedFailure(
                        failure_id=f"pytest-{idx}",
                        category=cat,
                        file_path=file_path.strip(),
                        line_number=int(line_str),
                        error_type=err_type.strip(),
                        error_message="Failure indicated at file and line location.",
                        is_repairable=True,
                        stack_trace_snippet=output[max(0, match.start() - 100) : min(len(output), match.end() + 200)],
                    )
                )
                idx += 1

        return failures

    def _parse_unittest(self, output: str) -> list[DiagnosedFailure]:
        """Parse Python standard unittest output."""
        failures: list[DiagnosedFailure] = []
        idx = 1

        for match in _UNITTEST_FAIL_LINE_RE.finditer(output):
            test_name, class_or_file = match.groups()
            failures.append(
                DiagnosedFailure(
                    failure_id=f"unittest-{idx}",
                    category="TEST_FAILURE",
                    test_name=test_name.strip(),
                    error_type="AssertionError",
                    error_message=f"Test '{test_name}' failed in {class_or_file}",
                    is_repairable=True,
                    stack_trace_snippet=output[max(0, match.start() - 50) : min(len(output), match.end() + 250)],
                )
            )
            idx += 1

        # Try to locate exact files and lines from traceback lines
        tb_matches = list(_TRACEBACK_FILE_LINE_RE.finditer(output))
        if tb_matches and failures:
            last_tb = tb_matches[-1]
            file_path, line_str, _ = last_tb.groups()
            failures[0].file_path = file_path
            try:
                failures[0].line_number = int(line_str)
            except ValueError:
                pass

        return failures

    def _parse_jest(self, output: str) -> list[DiagnosedFailure]:
        """Parse Jest formatted output."""
        failures: list[DiagnosedFailure] = []
        idx = 1

        for match in _JEST_FAIL_TEST_RE.finditer(output):
            suite, test_name = match.groups()
            failures.append(
                DiagnosedFailure(
                    failure_id=f"jest-{idx}",
                    category="TEST_FAILURE",
                    test_name=test_name.strip(),
                    error_type="JestExpectationError",
                    error_message=f"Expectation failed in suite '{suite.strip()}'",
                    is_repairable=True,
                    stack_trace_snippet=output[max(0, match.start() - 50) : min(len(output), match.end() + 250)],
                )
            )
            idx += 1

        return failures

    def _parse_generic(self, output: str) -> list[DiagnosedFailure]:
        """Fallback parser for generic Python or command tracebacks."""
        failures: list[DiagnosedFailure] = []
        tb_matches = list(_TRACEBACK_FILE_LINE_RE.finditer(output))
        if tb_matches:
            last_match = tb_matches[-1]
            file_path, line_str, func_name = last_match.groups()
            failures.append(
                DiagnosedFailure(
                    failure_id="generic-tb-1",
                    category="TEST_FAILURE",
                    file_path=file_path,
                    line_number=int(line_str) if line_str.isdigit() else None,
                    error_type="TracebackError",
                    error_message=f"Exception raised in {func_name or file_path}",
                    is_repairable=True,
                    stack_trace_snippet=output[max(0, last_match.start() - 100) : min(len(output), last_match.end() + 200)],
                )
            )
        return failures

    def _generate_summary(
        self,
        framework: str,
        failures: list[DiagnosedFailure],
        has_infra: bool,
        can_repair: bool,
    ) -> str:
        """Compose a concise human-readable diagnostic summary."""
        if not failures:
            return "No failures diagnosed."
        if has_infra:
            first_infra = next(
                (f for f in failures if f.category in ("INFRASTRUCTURE_FAILURE", "TIMEOUT", "ENVIRONMENT_ERROR")),
                None,
            )
            msg = first_infra.error_message if first_infra else "Infrastructure fault occurred."
            return f"Infrastructure failure blocked test run: {msg}"
        repair_msg = "eligible for automated repair" if can_repair else "requires manual intervention"
        return f"Diagnosed {len(failures)} failure(s) under {framework} ({repair_msg})."


# ---------------------------------------------------------------------------
# 2. Repair Patch Validator
# ---------------------------------------------------------------------------

class RepairPatchValidator:
    """Validates candidate repair patches against plan scope, constraints, and safety policies."""

    def validate_patch(
        self,
        payload: RepairPatchPayload,
        allowed_files: list[str] | None = None,
        forbidden_files: list[str] | None = None,
        max_attempts: int = 3,
    ) -> PatchValidationResult:
        """Evaluate a candidate repair patch before workspace application.

        Validation Gates:
        1. Retry Budget Gate: attempt_number cannot exceed max_attempts (default 3 per §6 F35).
        2. Diff Size Gate: diff cannot exceed MAX_DIFF_CHARS (200KB).
        3. Diff Path Traversal Gate: all modified paths must be repository-relative and safe.
        4. Constraint Gate: cannot modify any file listed in forbidden_files.
        5. Scope Gate: if allowed_files is specified, modified files must be a subset.
        6. Secret Leaks Gate: patch diff cannot contain unredacted secrets or tokens.
        7. Repeat Loop Gate: patch cannot be an identical repeat of an earlier failed patch.

        Returns:
            PatchValidationResult: Detailed validation verdict and telemetry.
        """
        violations: list[str] = []
        remaining = max(0, max_attempts - payload.attempt_number)
        patch_hash = compute_normalized_patch_hash(payload.diff)

        # 1. Budget Gate
        if payload.attempt_number > max_attempts:
            violations.append(
                f"Repair attempt {payload.attempt_number} exceeds maximum allowed budget ({max_attempts} attempts)."
            )

        # 2. Diff Size Gate
        if len(payload.diff) > MAX_DIFF_CHARS:
            violations.append(
                f"Patch diff size ({len(payload.diff)} chars) exceeds maximum allowable limit ({MAX_DIFF_CHARS} chars)."
            )

        # 3. Path Extraction & Traversal Gate
        extracted_files = extract_modified_files_from_diff(payload.diff)
        if not extracted_files:
            violations.append("Unified diff does not specify any modified or created target files.")

        validated_files: list[str] = []
        for file_path in extracted_files:
            try:
                norm_path = validate_repo_relative_path(file_path)
                validated_files.append(norm_path)
            except UnsafePathError as exc:
                violations.append(f"Unsafe path traversal in patch diff '{file_path}': {exc}")

        # 4. Forbidden Files Policy Check
        if forbidden_files:
            forbidden_set = set(forbidden_files)
            target_check = validated_files if validated_files else extracted_files
            conflicts = sorted(set(target_check).intersection(forbidden_set))
            if conflicts:
                violations.append(
                    f"Patch targets forbidden file(s) under policy constraint: {', '.join(conflicts)}"
                )

        # 5. Allowed Files Scope Check
        if allowed_files:
            allowed_set = set(allowed_files)
            target_check = validated_files if validated_files else extracted_files
            out_of_scope = sorted(set(target_check).difference(allowed_set))
            if out_of_scope:
                violations.append(
                    f"Patch targets file(s) outside approved plan scope: {', '.join(out_of_scope)}"
                )

        # 6. Secret Redaction & Leak Check
        redaction_res = redact_secrets(payload.diff)
        if redaction_res.findings:
            secret_types = sorted({f.pattern for f in redaction_res.findings})
            violations.append(
                f"Patch diff contains sensitive credentials or secrets: {', '.join(secret_types)}"
            )

        # 7. Repeat Identical Patch Loop Check (Docs/week3.md §6 F35)
        if patch_hash in payload.previous_patch_hashes:
            violations.append(
                "Identical repair patch was already attempted and failed. Repeating identical failed patches is blocked."
            )

        is_valid = len(violations) == 0
        rejection_reason = "; ".join(violations) if violations else None

        return PatchValidationResult(
            is_valid=is_valid,
            rejection_reason=rejection_reason,
            patch_hash=patch_hash,
            modified_files=validated_files if is_valid else extracted_files,
            attempt_number=payload.attempt_number,
            remaining_attempts=remaining,
            violations=violations,
        )


__all__ = [
    "FailureTracebackAnalyzer",
    "RepairPatchValidator",
    "compute_normalized_patch_hash",
    "extract_modified_files_from_diff",
]
