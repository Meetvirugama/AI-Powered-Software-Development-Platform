"""Comprehensive Unit & Regression Tests for Bounded Self-Repair Loop (F24 / Issue #205).

Owner: Prit Zania (Issue #205)
Covers:
1. LLMRepairSynthesizer reusing EditSynthesizer (F22) instead of dummy handler stubs.
2. Structured failure diagnosis ingestion (test name, traceback, file:line, Reflexion memory).
3. Reflexion verbal reinforcement history formatting and propagation across attempts.
4. Fault localization resolving root-cause application frames from tracebacks (AgentFL / Spectrum-based).
5. Anti-Reward Hacking Gate: strictly forbids modifying test files to force a pass unless in approved scope.
6. Failure classification into 'infra', 'test-bug', and 'code-bug'.
7. Immediate halt on infrastructure failures without consuming repair attempts.
8. Anti-cycling patch-hash deduplication and avoidance of identical repeat patches.
9. Strict 3-attempt repair budget ceiling enforcement (MAX_TASK_REPAIR_ATTEMPTS = 3).
10. Full end-to-end self-repair recovery with test execution and workspace updates.
"""

from __future__ import annotations

import tempfile
import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from ai.services.bounded_repair_loop import (
    MAX_TASK_REPAIR_ATTEMPTS,
    BoundedRepairLoop,
    BoundedRepairOutcome,
    LLMRepairSynthesizer,
)
from ai.services.edit_synthesizer import EditSynthesizer
from app.schemas.repair import (
    DiagnosedFailure,
    FailureCategory,
    FailureClassification,
    PatchValidationResult,
    RepairPatchPayload,
    TracebackDiagnosisResult,
)
from app.schemas.workspace import (
    RepairAttemptRecord,
    TestOutcomeStatus,
    WorkspaceCreateRequest,
    WorkspaceStatus,
    WorkspaceTestExecutionResult,
)
from app.services.repair_service import (
    FailureTracebackAnalyzer,
    RepairPatchValidator,
    classify_diagnosis,
    classify_failure,
    compute_normalized_patch_hash,
    extract_application_frames_from_traceback,
    is_test_file,
)
from sandbox.workspace_manager import WorkspaceManager


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def temp_dir():
    with tempfile.TemporaryDirectory() as td:
        yield td


@pytest.fixture
def workspace_mgr(temp_dir):
    return WorkspaceManager(base_workspaces_dir=temp_dir)


@pytest.fixture
def task_workspace(workspace_mgr):
    task_id = str(uuid.uuid4())
    req = WorkspaceCreateRequest(
        task_id=task_id,
        repository_id=str(uuid.uuid4()),
        base_revision="0123456789abcdef0123456789abcdef01234567",
    )
    workspace_mgr.create_workspace(req)
    workspace_mgr.transition_state(task_id, WorkspaceStatus.READY)
    return task_id


# ---------------------------------------------------------------------------
# 1. Failure Classification & Fault Localization Tests
# ---------------------------------------------------------------------------

class TestFailureClassificationAndLocalization:
    """Tests for classifying failures into infra / test-bug / code-bug and locating faults."""

    def test_classify_infrastructure_failures(self):
        """Verify infrastructure errors, timeouts, and permission errors classify as 'infra'."""
        fail_timeout = DiagnosedFailure(
            failure_id="f1",
            category="TIMEOUT",
            error_type="TimeoutExpired",
            error_message="Test timed out after 30s",
            is_repairable=False,
        )
        assert classify_failure(fail_timeout) == "infra"

        fail_env = DiagnosedFailure(
            failure_id="f2",
            category="ENVIRONMENT_ERROR",
            error_type="FileNotFoundError",
            error_message="pytest: command not found",
            is_repairable=False,
        )
        assert classify_failure(fail_env) == "infra"

        diag = TracebackDiagnosisResult(
            framework="pytest",
            total_failed=1,
            failures=[fail_timeout],
            has_infrastructure_failure=True,
            can_attempt_repair=False,
        )
        assert classify_diagnosis(diag) == "infra"

    def test_classify_test_bug_when_isolated_to_test_file(self):
        """Verify test failure without application frames is classified as 'test-bug'."""
        fail_test = DiagnosedFailure(
            failure_id="f1",
            category="TEST_FAILURE",
            test_name="test_bad_assertion",
            file_path="tests/test_math.py",
            line_number=12,
            error_type="AssertionError",
            error_message="assert 1 == 2",
            stack_trace_snippet="tests/test_math.py:12: AssertionError: assert 1 == 2",
        )
        assert is_test_file(fail_test.file_path) is True
        # No application frames in snippet
        assert classify_failure(fail_test) == "test-bug"

    def test_classify_code_bug_when_test_invokes_application_code(self):
        """Verify test failure whose traceback traverses application code is classified as 'code-bug'."""
        traceback_snippet = """
Traceback (most recent call last):
  File "tests/test_calculator.py", line 18, in test_add
    res = add(2, 3)
  File "src/calculator.py", line 9, in add
    return a - b
AssertionError: assert -1 == 5
"""
        fail_code = DiagnosedFailure(
            failure_id="f1",
            category="TEST_FAILURE",
            test_name="test_add",
            file_path="tests/test_calculator.py",
            line_number=18,
            error_type="AssertionError",
            error_message="assert -1 == 5",
            stack_trace_snippet=traceback_snippet,
        )
        frames = extract_application_frames_from_traceback(traceback_snippet)
        assert len(frames) == 1
        assert frames[0] == ("src/calculator.py", 9)
        assert classify_failure(fail_code) == "code-bug"

    def test_identify_target_file_and_line_extracts_application_source(self):
        """Verify spectrum-based fault localization selects the application file over the test file."""
        traceback_snippet = """
  File "tests/test_service.py", line 40, in test_process
    output = process_data("invalid")
  File "backend/app/processor.py", line 85, in process_data
    raise ValueError("unexpected payload")
"""
        failure = DiagnosedFailure(
            failure_id="f1",
            category="TEST_FAILURE",
            test_name="test_process",
            file_path="tests/test_service.py",
            line_number=40,
            stack_trace_snippet=traceback_snippet,
        )
        diagnosis = TracebackDiagnosisResult(
            framework="pytest",
            total_failed=1,
            failures=[failure],
            can_attempt_repair=True,
        )
        target_file, target_line = LLMRepairSynthesizer.identify_target_file_and_line(
            diagnosis=diagnosis,
            allow_test_edits=False,
        )
        assert target_file == "backend/app/processor.py"
        assert target_line == 85


# ---------------------------------------------------------------------------
# 2. Anti-Reward Hacking Gate Tests
# ---------------------------------------------------------------------------

class TestAntiRewardHackingGate:
    """Tests ensuring agents cannot alter test files to force a pass unless in approved scope."""

    def test_patch_modifying_test_file_is_strictly_rejected(self):
        """Verify modifying test files during repair is blocked as reward hacking."""
        diff = """--- a/tests/test_auth.py
+++ b/tests/test_auth.py
@@ -10,2 +10,2 @@
-    assert token.is_valid is True
+    assert True
"""
        payload = RepairPatchPayload(
            task_id="task-100",
            attempt_number=1,
            diff=diff,
            target_files=["tests/test_auth.py"],
            explanation="Cheating by making assertion always pass",
        )

        validator = RepairPatchValidator()
        result = validator.validate_patch(
            payload=payload,
            allowed_files=["src/auth.py"],
            allow_test_edits=False,
        )

        assert result.is_valid is False
        assert any("Anti-reward hacking violation" in v for v in result.violations)
        assert "tests/test_auth.py" in str(result.violations)

    def test_patch_modifying_test_file_permitted_when_explicitly_in_scope(self):
        """Verify modifying test files is permitted if the plan explicitly included the test file."""
        diff = """--- a/tests/test_auth.py
+++ b/tests/test_auth.py
@@ -10,2 +10,2 @@
-    assert token.status == 200
+    assert token.status == 201
"""
        payload = RepairPatchPayload(
            task_id="task-101",
            attempt_number=1,
            diff=diff,
            target_files=["tests/test_auth.py"],
            explanation="Authorized test fixture update",
        )

        validator = RepairPatchValidator()
        result = validator.validate_patch(
            payload=payload,
            allowed_files=["tests/test_auth.py"],
            allow_test_edits=False,
        )

        assert result.is_valid is True
        assert result.violations == []

    def test_patch_modifying_application_file_is_allowed(self):
        """Verify normal application file repairs are permitted."""
        diff = """--- a/src/auth.py
+++ b/src/auth.py
@@ -15,2 +15,2 @@
-    return False
+    return True
"""
        payload = RepairPatchPayload(
            task_id="task-102",
            attempt_number=1,
            diff=diff,
            target_files=["src/auth.py"],
            explanation="Fix authentication logic in app code",
        )

        validator = RepairPatchValidator()
        result = validator.validate_patch(
            payload=payload,
            allowed_files=["src/auth.py"],
            allow_test_edits=False,
        )

        assert result.is_valid is True
        assert result.violations == []


# ---------------------------------------------------------------------------
# 3. Reflexion Memory & Synthesis Tests
# ---------------------------------------------------------------------------

class TestReflexionMemoryAndSynthesizer:
    """Tests verifying Reflexion memory accumulation and LLMRepairSynthesizer execution."""

    def test_reflexion_memory_formatting_includes_prior_attempts(self):
        """Verify format_reflexion_memory serializes attempt history and outcomes."""
        history = [
            RepairAttemptRecord(
                task_id="t1",
                attempt_number=1,
                timestamp="2026-11-11T12:00:00Z",
                patch_summary="Added null check to auth.py",
                patch_hash="abc1234567890abcdef1234567890abcdef",
                test_status_before=TestOutcomeStatus.FAILED,
                test_status_after=TestOutcomeStatus.FAILED,
                success=False,
            ),
            RepairAttemptRecord(
                task_id="t1",
                attempt_number=2,
                timestamp="2026-11-11T12:01:00Z",
                patch_summary="Refactored token extraction in auth.py",
                patch_hash="def9876543210fedcba9876543210fedcba",
                test_status_before=TestOutcomeStatus.FAILED,
                test_status_after=TestOutcomeStatus.FAILED,
                success=False,
            ),
        ]

        synthesizer = LLMRepairSynthesizer()
        formatted = synthesizer.format_reflexion_memory(history)

        assert "REFLEXION MEMORY" in formatted
        assert "Attempt 1" in formatted
        assert "Added null check to auth.py" in formatted
        assert "Attempt 2" in formatted
        assert "Refactored token extraction in auth.py" in formatted
        assert "FAILED" in formatted

    def test_deterministic_repair_generates_targeted_patch_without_placeholder_stub(self, workspace_mgr, task_workspace):
        """Verify synthesis replaces the dummy 'handler(): pass -> return True' placeholder with targeted edits."""
        task_id = task_workspace
        # Write initial code file to workspace
        initial_code = (
            "def calculate_tax(amount):\n"
            "    if amount < 0:\n"
            "        return False\n"
            "    return amount * 0.1\n"
        )
        workspace_mgr.write_file(task_id, "src/billing.py", initial_code, create_parents=True)

        failure = DiagnosedFailure(
            failure_id="f1",
            category="TEST_FAILURE",
            test_name="test_calculate_tax_negative",
            file_path="src/billing.py",
            line_number=3,
            error_type="AssertionError",
            error_message="assert False is True",
            stack_trace_snippet="src/billing.py:3: AssertionError: assert False is True",
        )
        diagnosis = TracebackDiagnosisResult(
            framework="pytest",
            total_failed=1,
            failures=[failure],
            can_attempt_repair=True,
        )

        synthesizer = LLMRepairSynthesizer(workspace_manager=workspace_mgr)
        patch = synthesizer.synthesize_repair(
            task_id=task_id,
            attempt_number=1,
            diagnosis=diagnosis,
            allowed_files=["src/billing.py"],
        )

        assert patch.task_id == task_id
        assert patch.attempt_number == 1
        assert "src/billing.py" in patch.target_files
        assert "billing.py" in patch.diff
        # Verify it did NOT output the old placeholder stub
        assert "def handler():" not in patch.diff

    def test_synthesizer_ensures_anti_cycling_distinct_hashes_across_attempts(self, workspace_mgr, task_workspace):
        """Verify successive repair attempts generate distinct patch hashes to avoid repeat loops."""
        task_id = task_workspace
        code = "def check_access(user):\n    return False\n"
        workspace_mgr.write_file(task_id, "src/access.py", code, create_parents=True)

        failure = DiagnosedFailure(
            failure_id="f1",
            category="TEST_FAILURE",
            test_name="test_access",
            file_path="src/access.py",
            line_number=2,
        )
        diagnosis = TracebackDiagnosisResult(framework="pytest", total_failed=1, failures=[failure], can_attempt_repair=True)

        synthesizer = LLMRepairSynthesizer(workspace_manager=workspace_mgr)

        # Attempt 1
        patch1 = synthesizer.synthesize_repair(task_id=task_id, attempt_number=1, diagnosis=diagnosis, allowed_files=["src/access.py"])
        hash1 = compute_normalized_patch_hash(patch1.diff)

        # Attempt 2 (knowing hash1 from previous attempts)
        patch2 = synthesizer.synthesize_repair(
            task_id=task_id,
            attempt_number=2,
            diagnosis=diagnosis,
            previous_hashes=[hash1],
            allowed_files=["src/access.py"],
        )
        hash2 = compute_normalized_patch_hash(patch2.diff)

        assert hash1 != hash2
        assert hash2 not in patch2.previous_patch_hashes
        assert hash1 in patch2.previous_patch_hashes

    @pytest.mark.asyncio
    async def test_llm_gateway_async_synthesis_integration(self, workspace_mgr, task_workspace):
        """Verify LLMRepairSynthesizer calls LLMGateway and produces unified diff from EditBlock responses."""
        task_id = task_workspace
        initial_code = "def greet(name):\n    return 'Hello'\n"
        workspace_mgr.write_file(task_id, "src/greeter.py", initial_code, create_parents=True)

        mock_llm_resp = MagicMock()
        mock_llm_resp.content = (
            '{\n'
            '  "explanation": "Fix greeting to include name",\n'
            '  "edits": [\n'
            '    {\n'
            '      "file": "src/greeter.py",\n'
            '      "search": "    return \'Hello\'\\n",\n'
            '      "replace": "    return f\'Hello {name}\'\\n"\n'
            '    }\n'
            '  ]\n'
            '}'
        )
        mock_gateway = MagicMock()
        mock_gateway.generate = AsyncMock(return_value=mock_llm_resp)

        failure = DiagnosedFailure(
            failure_id="f1",
            category="TEST_FAILURE",
            test_name="test_greet_with_name",
            file_path="src/greeter.py",
            line_number=2,
        )
        diagnosis = TracebackDiagnosisResult(framework="pytest", total_failed=1, failures=[failure], can_attempt_repair=True)

        synthesizer = LLMRepairSynthesizer(llm_gateway=mock_gateway, workspace_manager=workspace_mgr)
        patch = await synthesizer.synthesize_repair_async(
            task_id=task_id,
            attempt_number=1,
            diagnosis=diagnosis,
            allowed_files=["src/greeter.py"],
        )

        assert "src/greeter.py" in patch.target_files
        assert "Hello {name}" in patch.diff
        assert mock_gateway.generate.called


# ---------------------------------------------------------------------------
# 4. BoundedRepairLoop Orchestration Tests
# ---------------------------------------------------------------------------

class TestBoundedRepairLoopOrchestration:
    """Tests for complete bounded self-repair cycle behavior."""

    def test_infrastructure_failure_halts_immediately_without_budget_use(self, workspace_mgr, task_workspace):
        """Verify environment/infrastructure faults abort without consuming repair attempts."""
        task_id = task_workspace
        test_runner = MagicMock()
        test_runner.run_tests.return_value = WorkspaceTestExecutionResult(
            task_id=task_id,
            success=False,
            command="pytest",
            exit_code=127,
            stdout="/bin/sh: pytest: command not found",
            stderr="",
            duration_ms=10.0,
            status=TestOutcomeStatus.FAILED,
            passed_count=0,
            failed_count=1,
        )

        repair = BoundedRepairLoop(workspace_manager=workspace_mgr, test_runner=test_runner)
        outcome = repair.run_repair_cycle(task_id=task_id)

        assert outcome.success is False
        assert outcome.attempts_used == 0
        assert outcome.budget_exhausted is False
        assert "Non-repairable infrastructure failure" in (outcome.error_message or "")

    def test_full_repair_cycle_recovers_code_defect(self, workspace_mgr, task_workspace):
        """Verify full loop: initial fail -> synthesize repair -> apply patch -> retest passes."""
        task_id = task_workspace
        initial_file = "def add(x, y):\n    return x - y\n"
        workspace_mgr.write_file(task_id, "src/calc.py", initial_file, create_parents=True)

        fail_res = WorkspaceTestExecutionResult(
            task_id=task_id,
            success=False,
            command="pytest",
            exit_code=1,
            stdout="""
FAILED tests/test_calc.py::test_add - AssertionError: assert -1 == 5
Traceback (most recent call last):
  File "src/calc.py", line 2, in add
    return x - y
AssertionError: assert -1 == 5
""",
            stderr="",
            duration_ms=50.0,
            status=TestOutcomeStatus.FAILED,
            passed_count=0,
            failed_count=1,
        )
        pass_res = WorkspaceTestExecutionResult(
            task_id=task_id,
            success=True,
            command="pytest",
            exit_code=0,
            stdout="1 passed in 0.05s",
            stderr="",
            duration_ms=40.0,
            status=TestOutcomeStatus.PASSED,
            passed_count=1,
            failed_count=0,
        )
        test_runner = MagicMock()
        test_runner.run_tests.side_effect = [fail_res, pass_res]

        repair = BoundedRepairLoop(
            workspace_manager=workspace_mgr,
            test_runner=test_runner,
        )
        outcome = repair.run_repair_cycle(
            task_id=task_id,
            allowed_files=["src/calc.py"],
        )

        assert outcome.success is True
        assert outcome.attempts_used == 1
        assert outcome.budget_exhausted is False
        assert outcome.final_test_status == TestOutcomeStatus.PASSED
        assert len(outcome.repair_records) == 1
        assert outcome.repair_records[0].success is True

    def test_repair_budget_exhausts_at_three_attempts_when_unfixed(self, workspace_mgr, task_workspace):
        """Verify strict 3-attempt ceiling halts the loop and sets budget_exhausted=True."""
        task_id = task_workspace
        workspace_mgr.write_file(task_id, "src/calc.py", "def broken(): return False\n", create_parents=True)

        fail_res = WorkspaceTestExecutionResult(
            task_id=task_id,
            success=False,
            command="pytest",
            exit_code=1,
            stdout="FAILED tests/test_calc.py::test_calc - AssertionError: assert False",
            stderr="",
            duration_ms=30.0,
            status=TestOutcomeStatus.FAILED,
            passed_count=0,
            failed_count=1,
        )
        test_runner = MagicMock()
        test_runner.run_tests.return_value = fail_res

        repair = BoundedRepairLoop(workspace_manager=workspace_mgr, test_runner=test_runner)
        outcome = repair.run_repair_cycle(
            task_id=task_id,
            allowed_files=["src/calc.py"],
        )

        assert outcome.success is False
        assert outcome.attempts_used == MAX_TASK_REPAIR_ATTEMPTS
        assert outcome.budget_exhausted is True
        assert outcome.final_test_status == TestOutcomeStatus.FAILED
        assert len(outcome.repair_records) == 3
        assert "exhausted maximum budget of 3 attempts" in (outcome.error_message or "")
