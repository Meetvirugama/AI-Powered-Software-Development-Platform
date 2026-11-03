"""Unit tests for Week 3 Day 4 Failure Traceback Diagnosis and Repair Patch Validation.

Owner: Dev — Week 3 Day 4 Deliverable (Docs/daily_tasks.md line 637 & Docs/week3.md §6 F35)
Coverage:
1. FailureTracebackAnalyzer parsing Pytest assertion failures, syntax errors, and import errors.
2. FailureTracebackAnalyzer parsing Unittest and Jest failures.
3. Distinguishing test failures from infrastructure errors (timeouts, missing binaries, permission denied).
4. Secret redaction on failure stack traces.
5. RepairPatchValidator happy path diff validation, modified file extraction, and SHA-256 hashing.
6. Path traversal security checks on diff headers.
7. Policy boundary enforcement (forbidden_files and allowed_files).
8. Secret leak detection preventing patches from introducing raw credentials.
9. Loop detection blocking identical repeat patches.
10. Task-level retry budget ceiling enforcement (hard ceiling of 3 attempts per Docs/week3.md §6).
11. RepairLoopState budget tracking and exhaustion state.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.schemas.repair import (
    DiagnosedFailure,
    MAX_DIFF_CHARS,
    PatchValidationResult,
    RepairLoopState,
    RepairPatchPayload,
    TracebackDiagnosisResult,
)
from app.services.repair_service import (
    FailureTracebackAnalyzer,
    RepairPatchValidator,
    compute_normalized_patch_hash,
    extract_modified_files_from_diff,
)


# ---------------------------------------------------------------------------
# 1. Failure Traceback Analyzer Tests (Pytest, Unittest, Jest)
# ---------------------------------------------------------------------------

def test_diagnose_pytest_assertion_failure():
    """Verify analyzer extracts failing test, file, and assertion error from Pytest output."""
    raw_output = """
============================= test session starts =============================
collecting ... collected 3 items

tests/test_auth.py .F.                                                   [100%]

================================== FAILURES ===================================
________________________ test_login_invalid_password _________________________

    def test_login_invalid_password():
>       assert response.status_code == 200
E       assert 401 == 200

tests/test_auth.py:42: AssertionError
=========================== short test summary info ===========================
FAILED tests/test_auth.py::test_login_invalid_password - AssertionError: assert 401 == 200
========================= 1 failed, 2 passed in 0.15s =========================
"""
    analyzer = FailureTracebackAnalyzer()
    result = analyzer.diagnose(raw_output, exit_code=1)

    assert result.framework == "pytest"
    assert result.total_failed == 1
    assert result.has_infrastructure_failure is False
    assert result.can_attempt_repair is True

    failure = result.failures[0]
    assert failure.category == "TEST_FAILURE"
    assert failure.test_name == "test_login_invalid_password"
    assert failure.file_path == "tests/test_auth.py"
    assert failure.error_type == "AssertionError"
    assert "assert 401 == 200" in failure.error_message
    assert failure.is_repairable is True


def test_diagnose_pytest_syntax_error():
    """Verify analyzer detects and classifies syntax errors as repairable."""
    raw_output = """
============================= test session starts =============================
collecting ... 
backend/app/calculator.py:15: in <module>
    def broken_syntax
E     SyntaxError: invalid syntax
=========================== short test summary info ===========================
ERROR collecting backend/app/calculator.py - SyntaxError: invalid syntax
!!!!!!!!!!!!!!!!!!! Interrupted: 1 error during collection !!!!!!!!!!!!!!!!!!!!
"""
    analyzer = FailureTracebackAnalyzer()
    result = analyzer.diagnose(raw_output, exit_code=2)

    assert result.total_failed >= 1
    assert result.can_attempt_repair is True
    # Syntax error is repairable by editing the syntax
    syntax_failure = next(f for f in result.failures if f.category == "SYNTAX_ERROR")
    assert syntax_failure.is_repairable is True
    assert "SyntaxError" in syntax_failure.error_type


def test_diagnose_pytest_import_error():
    """Verify analyzer detects ModuleNotFoundError as repairable import failure."""
    raw_output = """
============================= test session starts =============================
ERROR collecting backend/app/service.py
E   ModuleNotFoundError: No module named 'missing_helper'
=========================== short test summary info ===========================
ERROR backend/app/service.py - ModuleNotFoundError: No module named 'missing_helper'
"""
    analyzer = FailureTracebackAnalyzer()
    result = analyzer.diagnose(raw_output, exit_code=2)

    import_failure = next(f for f in result.failures if f.category == "IMPORT_ERROR")
    assert import_failure.is_repairable is True
    assert "missing_helper" in result.summary or "IMPORT_ERROR" in import_failure.category


def test_diagnose_unittest_failure():
    """Verify analyzer extracts test name and failure for Python unittest."""
    raw_output = """
test_addition (tests.test_math.TestMath) ... ok
test_division_by_zero (tests.test_math.TestMath) ... FAIL

======================================================================
FAIL: test_division_by_zero (tests.test_math.TestMath)
----------------------------------------------------------------------
Traceback (most recent call last):
  File "tests/test_math.py", line 25, in test_division_by_zero
    self.assertRaises(ZeroDivisionError, divide, 10, 0)
AssertionError: ZeroDivisionError not raised

----------------------------------------------------------------------
Ran 2 tests in 0.003s

FAILED (failures=1)
"""
    analyzer = FailureTracebackAnalyzer()
    result = analyzer.diagnose(raw_output, exit_code=1)

    assert result.framework == "unittest"
    assert result.total_failed >= 1
    assert result.can_attempt_repair is True
    failure = result.failures[0]
    assert failure.test_name == "test_division_by_zero"
    assert failure.is_repairable is True


def test_diagnose_jest_failure():
    """Verify analyzer extracts failures from Jest output."""
    raw_output = """
FAIL src/auth.test.js
  ● Authentication › token expiration check

    expect(received).toBe(expected) // Object.is equality

    Expected: true
    Received: false

      18 |   const isValid = checkExpiry(token);
    > 19 |   expect(isValid).toBe(true);
         |                   ^
      at Object.<anonymous> (src/auth.test.js:19:19)

Test Suites: 1 failed, 1 total
Tests:       1 failed, 2 passed, 3 total
"""
    analyzer = FailureTracebackAnalyzer()
    result = analyzer.diagnose(raw_output, exit_code=1)

    assert result.framework == "jest"
    assert result.total_failed >= 1
    assert result.can_attempt_repair is True
    assert any("token expiration check" in f.test_name for f in result.failures if f.test_name)


# ---------------------------------------------------------------------------
# 2. Infrastructure vs Test Failure Distinction Tests
# ---------------------------------------------------------------------------

def test_diagnose_infrastructure_timeout():
    """Docs/week3.md §6: Test timeout is an infrastructure error that cannot be resolved by code repair."""
    raw_output = """
subprocess.TimeoutExpired: Command '['pytest', 'tests']' timed out after 30 seconds
"""
    analyzer = FailureTracebackAnalyzer()
    result = analyzer.diagnose(raw_output, exit_code=124)

    assert result.has_infrastructure_failure is True
    assert result.can_attempt_repair is False
    assert any(f.category == "TIMEOUT" for f in result.failures)
    assert "timed out" in result.summary.lower()


def test_diagnose_infrastructure_command_not_found():
    """Verify missing binary is classified as environment error blocking repair."""
    raw_output = """
bash: pytest: command not found
"""
    analyzer = FailureTracebackAnalyzer()
    result = analyzer.diagnose(raw_output, exit_code=127)

    assert result.has_infrastructure_failure is True
    assert result.can_attempt_repair is False
    assert any(f.category == "ENVIRONMENT_ERROR" for f in result.failures)


def test_diagnose_infrastructure_permission_denied():
    """Verify permission denied in sandbox is classified as environment error."""
    raw_output = """
PermissionError: [Errno 13] Access is denied: '.workspaces/task-1/protected.db'
"""
    analyzer = FailureTracebackAnalyzer()
    result = analyzer.diagnose(raw_output, exit_code=1)

    assert result.has_infrastructure_failure is True
    assert result.can_attempt_repair is False


def test_diagnose_redacts_secrets_in_traceback():
    """Verify sensitive tokens inside error outputs are sanitized by secret redaction."""
    raw_output = """
FAILED tests/test_api.py::test_call - ValueError: Invalid authorization header 'Bearer ghp_FakeGithubPersonalAccessToken1234567890'
"""
    analyzer = FailureTracebackAnalyzer()
    result = analyzer.diagnose(raw_output)

    assert "ghp_FakeGithubPersonalAccessToken1234567890" not in result.summary
    assert "ghp_FakeGithubPersonalAccessToken1234567890" not in result.failures[0].stack_trace_snippet


# ---------------------------------------------------------------------------
# 3. Unified Diff Parsing & Helper Tests
# ---------------------------------------------------------------------------

def test_extract_modified_files_from_diff():
    """Verify diff header parser correctly identifies modified and created file paths."""
    diff_text = """
--- a/src/services/auth.py
+++ b/src/services/auth.py
@@ -10,4 +10,4 @@
-    return False
+    return True
--- /dev/null
+++ b/src/services/token.py
@@ -0,0 +1,5 @@
+def parse():
+    pass
"""
    files = extract_modified_files_from_diff(diff_text)
    assert files == ["src/services/auth.py", "src/services/token.py"]


def test_compute_normalized_patch_hash():
    """Verify SHA-256 hash ignores trivial whitespace differences in patches."""
    diff_1 = "--- a/f.py\n+++ b/f.py\n@@ -1 +1 @@\n-x\n+y\n"
    diff_2 = "--- a/f.py   \n+++ b/f.py \n@@ -1 +1 @@\n-x\n+y  \n"
    hash_1 = compute_normalized_patch_hash(diff_1)
    hash_2 = compute_normalized_patch_hash(diff_2)
    assert hash_1 == hash_2


# ---------------------------------------------------------------------------
# 4. Repair Patch Validator Security & Policy Gates
# ---------------------------------------------------------------------------

def test_repair_patch_validator_happy_path():
    """Verify valid patch within budget and allowed scope passes validation."""
    diff = """
--- a/backend/app/auth.py
+++ b/backend/app/auth.py
@@ -20,3 +20,3 @@
-    if token is None:
+    if not token:
"""
    payload = RepairPatchPayload(
        task_id="task_123",
        attempt_number=1,
        diff=diff,
        explanation="Check empty token string",
    )
    validator = RepairPatchValidator()
    result = validator.validate_patch(
        payload=payload,
        allowed_files=["backend/app/auth.py"],
        forbidden_files=["backend/app/config.py"],
        max_attempts=3,
    )
    assert result.is_valid is True
    assert result.rejection_reason is None
    assert result.modified_files == ["backend/app/auth.py"]
    assert result.attempt_number == 1
    assert result.remaining_attempts == 2
    assert result.violations == []


def test_repair_patch_validator_rejects_path_traversal():
    """Verify patch attempting relative directory traversal is rejected."""
    diff = """
--- a/../../etc/shadow
+++ b/../../etc/shadow
@@ -1 +1 @@
-root:x
+root:pwned
"""
    payload = RepairPatchPayload(
        task_id="task_123",
        attempt_number=1,
        diff=diff,
    )
    validator = RepairPatchValidator()
    result = validator.validate_patch(payload=payload)

    assert result.is_valid is False
    assert any("path traversal" in v.lower() for v in result.violations)


def test_repair_patch_validator_rejects_forbidden_files():
    """Verify patch modifying forbidden files under task constraint is blocked."""
    diff = """
--- a/backend/app/config.py
+++ b/backend/app/config.py
@@ -5,2 +5,2 @@
-DEBUG = False
+DEBUG = True
"""
    payload = RepairPatchPayload(
        task_id="task_123",
        attempt_number=1,
        diff=diff,
    )
    validator = RepairPatchValidator()
    result = validator.validate_patch(
        payload=payload,
        forbidden_files=["backend/app/config.py"],
    )
    assert result.is_valid is False
    assert any("forbidden file" in v.lower() for v in result.violations)


def test_repair_patch_validator_rejects_out_of_scope_files():
    """Verify patch modifying files outside allowed plan scope is blocked."""
    diff = """
--- a/unrelated/script.py
+++ b/unrelated/script.py
@@ -1 +1 @@
-pass
+print('hack')
"""
    payload = RepairPatchPayload(
        task_id="task_123",
        attempt_number=1,
        diff=diff,
    )
    validator = RepairPatchValidator()
    result = validator.validate_patch(
        payload=payload,
        allowed_files=["backend/app/service.py"],
    )
    assert result.is_valid is False
    assert any("outside approved plan scope" in v.lower() for v in result.violations)


def test_repair_patch_validator_blocks_leaked_secrets():
    """Verify patch containing hardcoded secrets or API keys is rejected."""
    diff = """
--- a/backend/app/service.py
+++ b/backend/app/service.py
@@ -10,1 +10,1 @@
-api_key = None
+api_key = "sk-proj-abcdef1234567890abcdef1234567890abcdef123456"
"""
    payload = RepairPatchPayload(
        task_id="task_123",
        attempt_number=1,
        diff=diff,
    )
    validator = RepairPatchValidator()
    result = validator.validate_patch(payload=payload)

    assert result.is_valid is False
    assert any("credentials or secrets" in v.lower() for v in result.violations)


def test_repair_patch_validator_loop_detection_blocks_identical_patch():
    """Docs/week3.md §6 F35: Avoid applying an identical failed patch repeatedly."""
    diff = """
--- a/backend/app/service.py
+++ b/backend/app/service.py
@@ -1 +1 @@
-a = 1
+a = 2
"""
    prior_hash = compute_normalized_patch_hash(diff)
    payload = RepairPatchPayload(
        task_id="task_123",
        attempt_number=2,
        diff=diff,
        previous_patch_hashes=[prior_hash],
    )
    validator = RepairPatchValidator()
    result = validator.validate_patch(payload=payload)

    assert result.is_valid is False
    assert any("identical repair patch" in v.lower() for v in result.violations)


def test_repair_patch_validator_enforces_attempt_budget_ceiling():
    """Docs/week3.md §6 F35: Hard ceiling of 3 task-level repair attempts."""
    diff = """
--- a/backend/app/service.py
+++ b/backend/app/service.py
@@ -1 +1 @@
-a = 1
+a = 3
"""
    # Attempt 4 when max is 3
    payload = RepairPatchPayload(
        task_id="task_123",
        attempt_number=4,
        diff=diff,
    )
    validator = RepairPatchValidator()
    result = validator.validate_patch(payload=payload, max_attempts=3)

    assert result.is_valid is False
    assert any("exceeds maximum allowed budget" in v.lower() for v in result.violations)


# ---------------------------------------------------------------------------
# 5. RepairLoopState Model Tests
# ---------------------------------------------------------------------------

def test_repair_loop_state_lifecycle():
    """Verify RepairLoopState tracks attempts and enforces exhaustion."""
    state = RepairLoopState(task_id="task_456", max_attempts=3)
    assert state.attempts_used == 0
    assert state.is_exhausted is False
    assert state.remaining_budget == 3
    assert state.status == "IDLE"

    # Attempt 1
    state.record_attempt(patch_hash="hash_1")
    assert state.attempts_used == 1
    assert state.remaining_budget == 2
    assert state.is_exhausted is False
    assert state.status == "REPAIRING"

    # Attempt 2
    state.record_attempt(patch_hash="hash_2")
    assert state.attempts_used == 2
    assert state.remaining_budget == 1

    # Attempt 3 (Ceiling reached)
    state.record_attempt(patch_hash="hash_3")
    assert state.attempts_used == 3
    assert state.remaining_budget == 0
    assert state.is_exhausted is True
    assert state.status == "EXHAUSTED"
    assert state.patch_hashes == ["hash_1", "hash_2", "hash_3"]

