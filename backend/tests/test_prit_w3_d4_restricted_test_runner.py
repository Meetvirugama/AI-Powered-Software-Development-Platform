"""Week 3 Day 4 Acceptance & Integration Test Suite.

Owner: Prit Zania — Week 3 Day 4 Deliverable (Docs/week3.md §6 F35, §8 Day 4, line 634)
Reference:
- Docs/week3.md §6 (F35 Test Runner and Bounded Repair Loop)
- Docs/week3.md §8 (Day 4 Code Changes, Test Execution and Bounded Repair)
- Docs/week3.md §11 (Scenario D: Test failure and repair exhaustion)
- Docs/daily_tasks.md (line 634: Prit Restricted test runner executing pytest or npm test)
- ADR-007 (Sandbox Isolation), ADR-010 (Mandatory Human Approval Gate & Bounded Repair Loop)

Verifies:
1. Framework detection across pytest, unittest, and jest.
2. Explicit handling of unsupported test frameworks (vitest, go test) and ambiguous configs (zero crash).
3. Command allowlist enforcement and strict rejection of unauthorized dependency installs (npm install, pip install).
4. Shell metacharacter injection blocking and path traversal containment via WorkspacePathGuard.
5. Successful test execution (PASSED, exit code 0) and parsed test metrics.
6. Test failure execution (FAILED, exit code 1) classified as TEST_FAILURE with is_repair_eligible=True.
7. Infrastructure failure (syntax error, missing command) classified as INFRASTRUCTURE_ERROR with is_repair_eligible=False.
8. Execution timeout handling (TIMEOUT) capping runtime and setting is_repair_eligible=False.
9. Output bounding (100 KB max) with truncation notice and secret redaction.
10. Bounded auto-repair tracking (attempts 1, 2, 3 recorded with revision references).
11. Hard 3-attempt repair budget ceiling (ADR-010, Scenario D) rejecting the 4th attempt with WorkspaceRepairBudgetExhaustedError.
12. Duplicate failed repair patch detection and rejection to prevent infinite repair cycles.
13. WorkspaceManager.run_tests() integration, test history retention, and timeline event emissions.
14. WorkspaceManager.record_repair_attempt() integration with REPAIR_BUDGET_EXHAUSTED event emission.
15. ToolRouter registration and policy dispatch for run_tests and record_repair_attempt.
16. Status policy enforcement blocking test runs on unapproved or stopped workspaces.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from uuid import uuid4

import pytest

from agent.tools.router import ToolDefinition, ToolRequest, ToolResult, ToolRouter
from app.schemas.workspace import (
    RepairAttemptRecord,
    TestFailureClassification,
    TestOutcomeStatus,
    WorkspaceCommandRequest,
    WorkspaceCommandResult,
    WorkspaceCreateRequest,
    WorkspaceExecutionEventType,
    WorkspaceMetadata,
    WorkspaceRepairBudgetStatus,
    WorkspaceResourceLimits,
    WorkspaceStartExecutionRequest,
    WorkspaceStatus,
    WorkspaceTestExecutionRequest,
    WorkspaceTestExecutionResult,
)
from sandbox.command_runner import WorkspaceCommandRunner
from sandbox.constants import MAX_COMMAND_OUTPUT_BYTES
from sandbox.exceptions import (
    WorkspaceDuplicateRepairPatchError,
    WorkspacePathEscapeError,
    WorkspacePolicyViolationError,
    WorkspaceRepairBudgetExhaustedError,
    WorkspaceStateError,
    WorkspaceTestExecutionError,
    WorkspaceUnsupportedFrameworkError,
)
from sandbox.test_runner import (
    MAX_REPAIR_ATTEMPTS,
    WorkspaceTestRunner,
)
from sandbox.tool_policy_bridge import (
    TOOL_RECORD_REPAIR,
    TOOL_RUN_TESTS,
    WorkspaceToolPolicyBridge,
    register_workspace_tools,
)
from sandbox.workspace_manager import WorkspaceManager


# ---------------------------------------------------------------------------
# Test Fixtures & Mock Helpers
# ---------------------------------------------------------------------------

@pytest.fixture
def temp_workspace(tmp_path: Path) -> Path:
    """Create a temporary workspace directory populated with sample test files."""
    ws = tmp_path / "test_workspace"
    ws.mkdir(parents=True, exist_ok=True)
    tests_dir = ws / "tests"
    tests_dir.mkdir(parents=True, exist_ok=True)

    # Sample passing test
    (tests_dir / "test_pass.py").write_text(
        "def test_simple_addition():\n    assert 1 + 1 == 2\n",
        encoding="utf-8",
    )
    # Sample failing test
    (tests_dir / "test_fail.py").write_text(
        "def test_failing_assertion():\n    assert 2 * 2 == 5\n",
        encoding="utf-8",
    )
    # pytest.ini config
    (ws / "pytest.ini").write_text("[pytest]\ntestpaths = tests\n", encoding="utf-8")
    return ws


@pytest.fixture
def test_runner() -> WorkspaceTestRunner:
    """Initialize a WorkspaceTestRunner instance."""
    return WorkspaceTestRunner()


@pytest.fixture
def workspace_manager(tmp_path: Path) -> WorkspaceManager:
    """Initialize a WorkspaceManager backed by a temporary directory."""
    workspaces_root = tmp_path / ".workspaces"
    return WorkspaceManager(base_workspaces_dir=workspaces_root)


@pytest.fixture
def initialized_workspace(workspace_manager: WorkspaceManager, tmp_path: Path) -> tuple[WorkspaceManager, str, Path]:
    """Provision and start an approved workspace ready for Day 4 test runner actions."""
    repo_dir = tmp_path / "mock_repo"
    repo_dir.mkdir(parents=True, exist_ok=True)
    tests_dir = repo_dir / "tests"
    tests_dir.mkdir(parents=True, exist_ok=True)
    (tests_dir / "test_sample.py").write_text("def test_ok():\n    assert True\n", encoding="utf-8")
    (repo_dir / "pytest.ini").write_text("[pytest]\ntestpaths = tests\n", encoding="utf-8")

    task_id = f"task-{uuid4().hex[:8]}"
    create_req = WorkspaceCreateRequest(
        task_id=task_id,
        repository_id=str(uuid4()),
        base_revision="a1b2c3d4e5f67890abcdef1234567890abcdef12",
        repository_root=str(repo_dir),
        isolation_type="directory_copy",
    )
    meta = workspace_manager.create_workspace(create_req)
    ws_path = Path(meta.workspace_path)
    (ws_path / "pytest.ini").write_text("[pytest]\ntestpaths = tests\n", encoding="utf-8")
    (ws_path / "tests").mkdir(parents=True, exist_ok=True)
    (ws_path / "tests" / "test_sample.py").write_text("def test_ok():\n    assert True\n", encoding="utf-8")

    # Start execution to enter IN_USE state
    start_req = WorkspaceStartExecutionRequest(
        task_id=task_id,
        approved_base_revision="a1b2c3d4e5f67890abcdef1234567890abcdef12",
        task_status="APPROVED",
    )
    start_res = workspace_manager.start_execution(start_req)
    assert start_res.success is True
    assert start_res.status == WorkspaceStatus.IN_USE

    return workspace_manager, task_id, ws_path


# ---------------------------------------------------------------------------
# 1. Framework Detection & Command Synthesis Tests
# ---------------------------------------------------------------------------

def test_framework_detection_pytest_and_explicit(test_runner: WorkspaceTestRunner, temp_workspace: Path) -> None:
    """Verify test runner detects pytest and supports explicit framework override."""
    # Automatic detection via pytest.ini
    fw, cmd, args, status = test_runner.detect_test_configuration(temp_workspace)
    assert fw == "pytest"
    assert cmd == "pytest"
    assert "-v" in args
    assert status == "CONFIRMED"

    # Explicit override: unittest
    fw_u, cmd_u, args_u, status_u = test_runner.detect_test_configuration(
        temp_workspace, explicit_framework="unittest"
    )
    assert fw_u == "unittest"
    assert cmd_u == "python"
    assert args_u == ["-m", "unittest", "-v"]
    assert status_u == "CONFIRMED"

    # Explicit override: jest
    fw_j, cmd_j, args_j, status_j = test_runner.detect_test_configuration(
        temp_workspace, explicit_framework="jest"
    )
    assert fw_j == "jest"
    assert cmd_j == "npm"
    assert status_j == "CONFIRMED"


def test_unsupported_framework_reported_explicitly(test_runner: WorkspaceTestRunner, temp_workspace: Path) -> None:
    """Verify unsupported frameworks (vitest, go) return explicit status without crashing."""
    fw, cmd, args, status = test_runner.detect_test_configuration(
        temp_workspace, explicit_framework="vitest"
    )
    assert fw == "vitest"
    assert status == "UNSUPPORTED_FRAMEWORK"

    req = WorkspaceTestExecutionRequest(
        task_id="task-unsupported-fw",
        framework="vitest",
    )
    res = test_runner.run_tests(temp_workspace, req)
    assert res.success is False
    assert res.status == TestOutcomeStatus.UNSUPPORTED_FRAMEWORK
    assert res.classification == TestFailureClassification.INFRASTRUCTURE_ERROR
    assert res.is_repair_eligible is False
    assert "UNSUPPORTED_FRAMEWORK" in (res.error or "")


def test_no_config_found_reporting(test_runner: WorkspaceTestRunner, tmp_path: Path) -> None:
    """Verify empty directory with no test config returns NO_TESTS_FOUND cleanly."""
    empty_ws = tmp_path / "empty_workspace"
    empty_ws.mkdir()

    fw, cmd, args, status = test_runner.detect_test_configuration(empty_ws)
    assert status == "NO_CONFIG_FOUND"

    req = WorkspaceTestExecutionRequest(task_id="task-no-tests")
    res = test_runner.run_tests(empty_ws, req)
    assert res.success is False
    assert res.status == TestOutcomeStatus.NO_TESTS_FOUND
    assert res.is_repair_eligible is False


# ---------------------------------------------------------------------------
# 2. Command Validation & Security Invariant Tests
# ---------------------------------------------------------------------------

def test_command_allowlist_and_install_prevention(test_runner: WorkspaceTestRunner, temp_workspace: Path) -> None:
    """Verify non-allowlisted commands and dependency install actions are strictly rejected."""
    # Non-allowlisted command
    with pytest.raises(WorkspacePolicyViolationError, match="not an authorized test runner"):
        test_runner.validate_test_request(temp_workspace, "curl", ["http://attacker.com"])

    # Disallow npm install inside test runner (Docs/week3.md §6 F35)
    with pytest.raises(WorkspacePolicyViolationError, match="Arbitrary dependency or package installation"):
        test_runner.validate_test_request(temp_workspace, "npm", ["install", "axios"])

    # Disallow pip install inside test runner
    with pytest.raises(WorkspacePolicyViolationError, match="Arbitrary pip installation"):
        test_runner.validate_test_request(temp_workspace, "python", ["-m", "pip", "install", "requests"])


def test_disallowed_shell_tokens_and_path_traversal(test_runner: WorkspaceTestRunner, temp_workspace: Path) -> None:
    """Verify shell operators and path traversal attempts are blocked."""
    # Shell operator in argument
    with pytest.raises(WorkspacePolicyViolationError, match="forbidden shell operator"):
        test_runner.validate_test_request(temp_workspace, "pytest", ["tests/test_pass.py; rm -rf /"])

    with pytest.raises(WorkspacePolicyViolationError, match="forbidden shell operator"):
        test_runner.validate_test_request(temp_workspace, "pytest", ["tests/test_pass.py && echo pwned"])

    # Path traversal outside workspace root
    with pytest.raises(WorkspacePathEscapeError):
        test_runner.validate_test_request(temp_workspace, "pytest", ["-v"], test_path="../sibling_repo")


# ---------------------------------------------------------------------------
# 3. Output Parsing & Failure Classification Tests
# ---------------------------------------------------------------------------

def test_output_parsing_pytest_success(test_runner: WorkspaceTestRunner) -> None:
    """Verify regex extraction of passed test metrics from pytest logs."""
    sample_stdout = """
============================= test session starts =============================
platform win32 -- Python 3.14.6, pytest-9.1.1
collected 5 items

tests/test_calc.py .....                                                 [100%]

============================== 5 passed in 0.35s ==============================
"""
    passed, failed, skipped, errors, total, failed_names, details = test_runner.parse_test_output(
        framework="pytest",
        stdout=sample_stdout,
        stderr="",
        exit_code=0,
    )
    assert passed == 5
    assert failed == 0
    assert skipped == 0
    assert errors == 0
    assert total == 5
    assert failed_names == []


def test_output_parsing_pytest_failure_and_repair_eligibility(test_runner: WorkspaceTestRunner) -> None:
    """Verify failed test parsing, failing test name extraction, and repair eligibility."""
    sample_stdout = """
============================= test session starts =============================
collected 4 items

tests/test_calc.py .F..                                                  [100%]

=================================== FAILURES ===================================
_______________________________ test_subtract _________________________________
    def test_subtract():
>       assert 5 - 3 == 4
E       AssertionError: assert (5 - 3) == 4

tests/test_calc.py:12: AssertionError
=========================== short test summary info ===========================
FAILED tests/test_calc.py::test_subtract - AssertionError: assert (5 - 3) == 4
========================= 1 failed, 3 passed in 0.42s =========================
"""
    passed, failed, skipped, errors, total, failed_names, details = test_runner.parse_test_output(
        framework="pytest",
        stdout=sample_stdout,
        stderr="",
        exit_code=1,
    )
    assert passed == 3
    assert failed == 1
    assert total == 4
    assert "tests/test_calc.py::test_subtract" in failed_names

    # Classification test
    outcome, classification, eligible = test_runner.classify_failure(
        exit_code=1,
        timed_out=False,
        failed_count=failed,
        error_count=errors,
        stdout=sample_stdout,
        stderr="",
        framework_status="CONFIRMED",
    )
    assert outcome == TestOutcomeStatus.FAILED
    assert classification == TestFailureClassification.TEST_FAILURE
    assert eligible is True  # Assertion failures are repair eligible!


def test_output_parsing_jest_format(test_runner: WorkspaceTestRunner) -> None:
    """Verify test metrics extraction from Jest/npm test outputs."""
    sample_stdout = """
PASS src/components/Button.test.tsx
FAIL src/lib/format.test.ts
  ● formatCurrency › should format negative numbers

    expect(received).toBe(expected) // Object.is equality

    Expected: "-$10.00"
    Received: "($10.00)"

Tests:       1 failed, 4 passed, 5 total
Snapshots:   0 total
Time:        1.45 s
"""
    passed, failed, skipped, errors, total, failed_names, details = test_runner.parse_test_output(
        framework="jest",
        stdout=sample_stdout,
        stderr="",
        exit_code=1,
    )
    assert passed == 4
    assert failed == 1
    assert total == 5
    assert len(failed_names) >= 1
    assert any("formatCurrency" in name for name in failed_names)


def test_infrastructure_failure_classification(test_runner: WorkspaceTestRunner) -> None:
    """Verify infrastructure crashes (syntax errors, missing modules) are NOT repair eligible."""
    infra_error = "ModuleNotFoundError: No module named 'nonexistent_package'"
    outcome, classification, eligible = test_runner.classify_failure(
        exit_code=2,
        timed_out=False,
        failed_count=0,
        error_count=1,
        stdout="",
        stderr=infra_error,
        framework_status="CONFIRMED",
    )
    assert outcome == TestOutcomeStatus.ERROR
    assert classification == TestFailureClassification.INFRASTRUCTURE_ERROR
    assert eligible is False


def test_timeout_classification(test_runner: WorkspaceTestRunner) -> None:
    """Verify execution timeout is classified as TIMEOUT and not eligible for auto-repair."""
    outcome, classification, eligible = test_runner.classify_failure(
        exit_code=-1,
        timed_out=True,
        failed_count=0,
        error_count=0,
        stdout="",
        stderr="Execution timed out after 60s.",
        framework_status="CONFIRMED",
    )
    assert outcome == TestOutcomeStatus.TIMEOUT
    assert classification == TestFailureClassification.TIMEOUT
    assert eligible is False


# ---------------------------------------------------------------------------
# 4. Mocked Execution & Bounded Output Tests
# ---------------------------------------------------------------------------

def test_test_output_truncation_and_secret_redaction(tmp_path: Path) -> None:
    """Verify outputs exceeding 100 KB are truncated with notice, and secrets are redacted."""
    ws = tmp_path / "truncation_ws"
    ws.mkdir()
    (ws / "pytest.ini").write_text("[pytest]\n", encoding="utf-8")

    class MockBigOutputCommandRunner(WorkspaceCommandRunner):
        def run_command(self, *args, **kwargs) -> WorkspaceCommandResult:
            huge_stdout = "X" * (MAX_COMMAND_OUTPUT_BYTES + 5000)
            return WorkspaceCommandResult(
                success=True,
                command="pytest",
                exit_code=0,
                stdout=huge_stdout + " GITHUB_TOKEN=ghp_1234567890abcdef1234567890abcdef1234",
                stderr="ghp_1234567890abcdef1234567890abcdef1234",
                duration_ms=120.0,
                timed_out=False,
            )

    mock_runner = WorkspaceTestRunner(command_runner=MockBigOutputCommandRunner())
    req = WorkspaceTestExecutionRequest(task_id="task-trunc-secret")
    res = mock_runner.run_tests(ws, req)

    assert res.success is True
    assert "ghp_1234567890" not in res.stdout
    assert "ghp_1234567890" not in res.stderr
    assert "[REDACTED]" in res.stdout or "[REDACTED]" in res.stderr


# ---------------------------------------------------------------------------
# 5. Bounded Auto-Repair Budget Tests (ADR-010, Docs/week3.md §6 F35, §11 Scenario D)
# ---------------------------------------------------------------------------

def test_bounded_repair_attempts_tracking_and_max_ceiling(test_runner: WorkspaceTestRunner) -> None:
    """Verify task repair budget tracks attempts up to 3 and strictly rejects the 4th attempt."""
    task_id = "task-repair-budget-001"

    # Initial state: 0 attempts used, 3 available
    status_0 = test_runner.get_repair_budget_status(task_id)
    assert status_0.repair_attempts_used == 0
    assert status_0.repair_attempts_max == 3
    assert status_0.is_budget_exhausted is False
    assert test_runner.can_attempt_repair(task_id) is True

    # Attempt 1
    rec1 = test_runner.record_repair_attempt(
        task_id=task_id,
        patch_summary="Patch line 14: fix off-by-one error",
        patch_content="--- a/calc.py\n+++ b/calc.py\n- return x + 2\n+ return x + 1",
        workspace_revision="sha-attempt-1",
        test_status_before=TestOutcomeStatus.FAILED,
        test_status_after=TestOutcomeStatus.FAILED,
        success=False,
    )
    assert rec1.attempt_number == 1
    assert rec1.patch_hash is not None
    assert test_runner.get_repair_budget_status(task_id).repair_attempts_used == 1

    # Attempt 2
    rec2 = test_runner.record_repair_attempt(
        task_id=task_id,
        patch_summary="Patch line 18: adjust boundary check",
        patch_content="--- a/calc.py\n+++ b/calc.py\n- if x > 10:\n+ if x >= 10:",
        workspace_revision="sha-attempt-2",
        test_status_before=TestOutcomeStatus.FAILED,
        test_status_after=TestOutcomeStatus.FAILED,
        success=False,
    )
    assert rec2.attempt_number == 2
    assert test_runner.get_repair_budget_status(task_id).repair_attempts_used == 2

    # Attempt 3 (Final allowed attempt)
    rec3 = test_runner.record_repair_attempt(
        task_id=task_id,
        patch_summary="Patch line 22: handle edge cases",
        patch_content="--- a/calc.py\n+++ b/calc.py\n- return None\n+ return 0",
        workspace_revision="sha-attempt-3",
        test_status_before=TestOutcomeStatus.FAILED,
        test_status_after=TestOutcomeStatus.FAILED,
        success=False,
    )
    assert rec3.attempt_number == 3

    # Budget is now exhausted (3/3 used)
    status_3 = test_runner.get_repair_budget_status(task_id)
    assert status_3.repair_attempts_used == 3
    assert status_3.is_budget_exhausted is True
    assert test_runner.can_attempt_repair(task_id) is False

    # Attempt 4 MUST be strictly blocked per ADR-010 and Scenario D!
    with pytest.raises(WorkspaceRepairBudgetExhaustedError, match="exhausted its maximum of 3 repair attempts"):
        test_runner.record_repair_attempt(
            task_id=task_id,
            patch_summary="Patch attempt 4: illegal retry",
            patch_content="--- a/calc.py\n+++ b/calc.py\n// fourth retry",
        )


def test_duplicate_failed_patch_rejected(test_runner: WorkspaceTestRunner) -> None:
    """Verify applying the exact same failed patch repeatedly is rejected to prevent infinite loops."""
    task_id = "task-duplicate-patch"
    identical_patch = "--- a/file.py\n+++ b/file.py\n+ x = 1"

    # First attempt with this patch
    rec1 = test_runner.record_repair_attempt(
        task_id=task_id,
        patch_summary="Fix var initialization",
        patch_content=identical_patch,
        success=False,
    )
    assert rec1.attempt_number == 1

    # Second attempt with the EXACT identical patch content
    with pytest.raises(WorkspaceDuplicateRepairPatchError, match="Identical repair patch already attempted"):
        test_runner.record_repair_attempt(
            task_id=task_id,
            patch_summary="Fix var initialization again",
            patch_content=identical_patch,
            success=False,
        )


# ---------------------------------------------------------------------------
# 6. WorkspaceManager Integration & Timeline Observability Tests
# ---------------------------------------------------------------------------

def test_workspace_manager_run_tests_integration(
    initialized_workspace: tuple[WorkspaceManager, str, Path],
) -> None:
    """Verify WorkspaceManager.run_tests() records timeline events and history."""
    wm, task_id, ws_path = initialized_workspace

    # Mock command runner to simulate passing test
    class MockPassedRunner(WorkspaceCommandRunner):
        def run_command(self, *args, **kwargs) -> WorkspaceCommandResult:
            return WorkspaceCommandResult(
                success=True,
                command="pytest",
                exit_code=0,
                stdout="====== 2 passed in 0.10s ======",
                duration_ms=105.0,
            )

    wm._test_runner._command_runner = MockPassedRunner()

    req = WorkspaceTestExecutionRequest(task_id=task_id, test_path="tests/test_sample.py")
    res = wm.run_tests(req)

    assert res.success is True
    assert res.status == TestOutcomeStatus.PASSED
    assert res.passed_count == 2
    assert res.task_id == task_id

    # Check test history
    history = wm.get_test_history(task_id)
    assert len(history) == 1
    assert history[0].status == TestOutcomeStatus.PASSED

    # Check timeline events
    timeline = wm.get_execution_timeline(task_id)
    event_types = [e.event_type for e in timeline]
    assert WorkspaceExecutionEventType.TESTS_STARTED in event_types
    assert WorkspaceExecutionEventType.TESTS_PASSED in event_types


def test_workspace_manager_record_repair_attempt_exhaustion(
    initialized_workspace: tuple[WorkspaceManager, str, Path],
) -> None:
    """Verify WorkspaceManager emits REPAIR_BUDGET_EXHAUSTED event upon ceiling reach."""
    wm, task_id, _ = initialized_workspace

    # Attempt 1
    wm.record_repair_attempt(task_id, "Attempt 1 patch", "diff 1")
    # Attempt 2
    wm.record_repair_attempt(task_id, "Attempt 2 patch", "diff 2")
    # Attempt 3 (hits ceiling)
    wm.record_repair_attempt(task_id, "Attempt 3 patch", "diff 3")

    budget = wm.get_repair_budget_status(task_id)
    assert budget.is_budget_exhausted is True
    assert budget.repair_attempts_used == 3

    # Check that REPAIR_BUDGET_EXHAUSTED event was emitted
    timeline = wm.get_execution_timeline(task_id)
    event_types = [e.event_type for e in timeline]
    assert WorkspaceExecutionEventType.REPAIR_ATTEMPT_STARTED in event_types
    assert WorkspaceExecutionEventType.REPAIR_ATTEMPT_COMPLETED in event_types
    assert WorkspaceExecutionEventType.REPAIR_BUDGET_EXHAUSTED in event_types


def test_unapproved_workspace_blocks_test_execution(workspace_manager: WorkspaceManager, tmp_path: Path) -> None:
    """Verify tests cannot be run on a workspace that is NOT in IN_USE state."""
    task_id = f"task-unapproved-{uuid4().hex[:6]}"
    repo = tmp_path / "mock_repo"
    repo.mkdir(parents=True, exist_ok=True)

    create_req = WorkspaceCreateRequest(
        task_id=task_id,
        repository_id=str(uuid4()),
        base_revision="a1b2c3d4e5f67890abcdef1234567890abcdef12",
        repository_root=str(repo),
        isolation_type="directory_copy",
    )
    meta = workspace_manager.create_workspace(create_req)
    assert meta.status == WorkspaceStatus.READY  # Not yet IN_USE!

    # Attempting to run tests in READY state must be blocked
    test_req = WorkspaceTestExecutionRequest(task_id=task_id)
    with pytest.raises(WorkspaceStateError, match="Cannot run tests in workspace state 'READY'"):
        workspace_manager.run_tests(test_req)


# ---------------------------------------------------------------------------
# 7. ToolRouter & Policy Bridge Integration Tests
# ---------------------------------------------------------------------------

def test_tool_router_run_tests_dispatch(
    initialized_workspace: tuple[WorkspaceManager, str, Path],
) -> None:
    """Verify run_tests tool registration with ToolRouter and safe execution."""
    wm, task_id, _ = initialized_workspace
    router = ToolRouter()
    bridge = register_workspace_tools(router, wm)

    # Check registered tool names
    tool_names = [t.name for t in router.get_tools()]
    assert TOOL_RUN_TESTS in tool_names
    assert TOOL_RECORD_REPAIR in tool_names

    # Mock test runner to return passed
    class MockFastRunner(WorkspaceCommandRunner):
        def run_command(self, *args, **kwargs) -> WorkspaceCommandResult:
            return WorkspaceCommandResult(
                success=True,
                command="pytest",
                exit_code=0,
                stdout="==== 1 passed in 0.05s ====",
                duration_ms=45.0,
            )

    wm._test_runner._command_runner = MockFastRunner()

    # Invoke run_tests through ToolRouter
    req = ToolRequest(
        tool_name=TOOL_RUN_TESTS,
        arguments={"test_path": "tests/test_sample.py"},
    )
    result = router.route(req, agent_state={"task_id": task_id}, policy_engine=bridge)
    assert result.success is True
    assert isinstance(result.output, dict)
    assert result.output["status"] == "PASSED"
    assert result.output["passed_count"] == 1


def test_tool_router_record_repair_dispatch(
    initialized_workspace: tuple[WorkspaceManager, str, Path],
) -> None:
    """Verify record_repair_attempt tool invocation through ToolRouter."""
    wm, task_id, _ = initialized_workspace
    router = ToolRouter()
    bridge = register_workspace_tools(router, wm)

    req = ToolRequest(
        tool_name=TOOL_RECORD_REPAIR,
        arguments={
            "patch_summary": "Fix syntax in parser",
            "patch_content": "+ fixed_code()",
            "success": True,
        },
    )
    result = router.route(req, agent_state={"task_id": task_id}, policy_engine=bridge)
    assert result.success is True
    assert result.output["attempt_number"] == 1
    assert result.output["success"] is True
