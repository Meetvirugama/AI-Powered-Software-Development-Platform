"""Comprehensive Integration Suite for Execution-Verified Test Generation (task.md §11.2).

Validates Scenarios A through V:
- Scenario A: Valid Python pytest repository
- Scenario B: Python unittest repository
- Scenario C: JavaScript Jest repository
- Scenario D: TypeScript Vitest repository
- Scenario E: Repository with both Jest and Vitest dependencies
- Scenario F: Repository with no existing test framework
- Scenario G: Invalid generated syntax
- Scenario H: Incorrect imports
- Scenario I: Test with failing assertion
- Scenario J: Flaky generated test
- Scenario K: Passing test with no coverage improvement
- Scenario L: Passing test with additional coverage
- Scenario M: Sandbox timeout
- Scenario N: Resource limit exceeded
- Scenario O: Unsafe file access attempt
- Scenario P: Path traversal attempt
- Scenario Q: Attempt to access environment secrets
- Scenario R: Existing baseline test failures
- Scenario S: Coverage collection failure
- Scenario T: Generation budget exhausted
- Scenario U: Maximum iteration limit reached
- Scenario V: Temporary workspace cleanup failure
"""

from __future__ import annotations

import json
from pathlib import Path
import tempfile
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from app.core.errors import APIError
from app.core.input_security import UnsafePathError
from app.schemas.analysis import (
    CoverageReport,
    StabilityReport,
    StabilityRunResult,
    TestGenerationResult,
    TestScenario,
)
from app.schemas.workspace import (
    TestOutcomeStatus,
    WorkspaceCleanupResult,
    WorkspaceMetadata,
    WorkspaceStatus,
    WorkspaceTestExecutionResult,
)
from app.services.test_coverage_service import TargetCoverageData, TestCoverageService
from app.services.test_execution_verifier import TestExecutionVerifier
from app.services.test_generation_orchestrator import (
    check_generated_test_path,
    detect_repository_test_framework,
    validate_and_sanitize_generated_tests,
    validate_generated_test_syntax,
)
from app.services.test_iteration_service import TestIterationOrchestrator
from app.services.test_stability_service import TestStabilityValidator
from scanner.framework_detector import FrameworkDetector


def _make_dummy_result(
    framework: str = "pytest",
    test_path: str = "tests/test_example.py",
    content: str = "def test_example(): assert True",
    syntax_valid: bool = True,
) -> TestGenerationResult:
    return TestGenerationResult(
        detected_framework=framework,
        proposed_test_path=test_path,
        test_content=content,
        covered_scenarios=[TestScenario(name="Normal test", category="normal", description="Tests normal flow")],
        syntax_valid=syntax_valid,
        validation_errors=[] if syntax_valid else ["Syntax error"],
    )


# --- Scenario A: Valid Python pytest repository ---
def test_scenario_a_valid_python_pytest_repo() -> None:
    detector = FrameworkDetector()
    files = ["src/app.py", "tests/test_app.py", "pytest.ini"]
    res = detector.detect(repo_root=None, target_file="src/app.py", file_list=files)
    assert res.framework == "pytest"
    assert res.is_supported is True
    assert "pytest" in (res.test_command or "")


# --- Scenario B: Python unittest repository ---
def test_scenario_b_python_unittest_repo() -> None:
    detector = FrameworkDetector()
    files = ["src/app.py", "tests/test_app.py"]
    res = detector.detect(repo_root=None, target_file="src/app.py", file_list=files, preferred_framework="unittest")
    assert res.framework == "unittest"
    assert res.is_supported is True


# --- Scenario C: JavaScript Jest repository ---
def test_scenario_c_javascript_jest_repo() -> None:
    detector = FrameworkDetector()
    files = ["src/index.js", "package.json", "jest.config.js"]

    def fake_read(root: Any, rel_path: str) -> str:
        return '{"scripts": {"test": "jest"}}'

    detector._read_file = fake_read  # type: ignore[method-assign]
    res = detector.detect(repo_root=None, target_file="src/index.js", file_list=files)
    assert res.framework == "jest"
    assert res.is_supported is True
    assert res.test_command == "npm test"


# --- Scenario D: TypeScript Vitest repository ---
def test_scenario_d_typescript_vitest_repo() -> None:
    detector = FrameworkDetector()
    files = ["src/index.ts", "package.json", "vitest.config.ts"]

    def fake_read(root: Any, rel_path: str) -> str:
        return '{"scripts": {"test": "vitest"}, "devDependencies": {"vitest": "^1.0.0"}}'

    detector._read_file = fake_read  # type: ignore[method-assign]
    res = detector.detect(repo_root=None, target_file="src/index.ts", file_list=files)
    assert res.framework == "vitest"
    assert res.is_supported is True
    assert res.test_command == "npm test -- --run"


# --- Scenario E: Repository with both Jest and Vitest dependencies ---
def test_scenario_e_jest_and_vitest_both_present() -> None:
    detector = FrameworkDetector()
    files = ["src/index.ts", "package.json", "jest.config.js", "vitest.config.ts"]

    def fake_read(root: Any, rel_path: str) -> str:
        return '{"devDependencies": {"jest": "^29.0.0", "vitest": "^1.0.0"}}'

    detector._read_file = fake_read  # type: ignore[method-assign]
    # Requesting explicit vitest preferred framework
    res = detector.detect(repo_root=None, target_file="src/index.ts", file_list=files, preferred_framework="vitest")
    assert res.framework == "vitest"


# --- Scenario F: Repository with no existing test framework ---
def test_scenario_f_no_test_framework_found() -> None:
    detector = FrameworkDetector()
    files = ["src/app.py", "src/utils.py"]
    res = detector.detect(repo_root=None, target_file="src/app.py", file_list=files)
    assert res.status in ("NO_CONFIG_FOUND", "CONFIRMED")


# --- Scenario G: Invalid generated syntax ---
def test_scenario_g_invalid_generated_syntax() -> None:
    invalid_code = "def test_broken(:\n    assert True"
    valid, errors = validate_generated_test_syntax(invalid_code, "pytest", "tests/test_b.py")
    assert valid is False
    assert len(errors) > 0

    res = _make_dummy_result(content=invalid_code, syntax_valid=False)
    verifier = TestExecutionVerifier()
    verified = verifier.verify_generated_test(
        result=res,
        target_path="app.py",
        target_source_code="def f(): pass",
        repository_id=str(uuid4()),
    )
    assert verified.verification_status == "UNVERIFIED"
    assert verified.execution_status == "NOT_EXECUTED"


# --- Scenario H: Incorrect imports ---
def test_scenario_h_incorrect_imports_fails_execution() -> None:
    validator = TestStabilityValidator(max_runs=3)

    def import_error_runner(idx: int) -> tuple[bool, int, float, int, int, str | None]:
        return False, 1, 0.05, 0, 1, "ModuleNotFoundError: No module named 'non_existent_module'"

    rep = validator.run_stability_validation(runner_fn=import_error_runner)
    assert rep.is_stable is False
    assert rep.classification == "FAILED"
    assert "ModuleNotFoundError" in (rep.runs[0].error_message or "")


# --- Scenario I: Test with failing assertion ---
def test_scenario_i_failing_assertion() -> None:
    validator = TestStabilityValidator(max_runs=3)

    def assert_fail_runner(idx: int) -> tuple[bool, int, float, int, int, str | None]:
        return False, 1, 0.04, 0, 1, "AssertionError: 1 != 2"

    rep = validator.run_stability_validation(runner_fn=assert_fail_runner)
    assert rep.is_stable is False
    assert rep.classification == "FAILED"


# --- Scenario J: Flaky generated test ---
def test_scenario_j_flaky_generated_test() -> None:
    validator = TestStabilityValidator(max_runs=3)

    runs = [
        StabilityRunResult(run_number=1, passed=True, duration_seconds=0.1, passed_count=1, failed_count=0),
        StabilityRunResult(run_number=2, passed=False, duration_seconds=0.1, passed_count=0, failed_count=1, error_message="AssertionError: Timeout"),
        StabilityRunResult(run_number=3, passed=True, duration_seconds=0.1, passed_count=1, failed_count=0),
    ]
    rep = validator.evaluate_runs(runs)
    assert rep.classification == "UNSTABLE"
    assert rep.is_stable is False


# --- Scenario K: Passing test with no coverage improvement ---
def test_scenario_k_passing_test_no_coverage_improvement() -> None:
    cov_svc = TestCoverageService()
    baseline = TargetCoverageData(line_coverage=50.0, covered_lines=[1, 2])
    post_gen = TargetCoverageData(line_coverage=50.0, covered_lines=[1, 2])

    rep = cov_svc.calculate_coverage_gain(baseline, post_gen, "src/math.py")
    assert rep.line_coverage_gain == 0.0
    assert rep.coverage_attributable_to_generated_tests is False


# --- Scenario L: Passing test with additional coverage ---
def test_scenario_l_passing_test_with_additional_coverage() -> None:
    cov_svc = TestCoverageService()
    baseline = TargetCoverageData(line_coverage=50.0, covered_lines=[1, 2])
    post_gen = TargetCoverageData(line_coverage=80.0, covered_lines=[1, 2, 3, 4])

    rep = cov_svc.calculate_coverage_gain(baseline, post_gen, "src/math.py")
    assert rep.line_coverage_gain == 30.0
    assert rep.newly_covered_lines == [3, 4]
    assert rep.coverage_attributable_to_generated_tests is True


# --- Scenario M: Sandbox timeout ---
def test_scenario_m_sandbox_timeout() -> None:
    validator = TestStabilityValidator(max_runs=3)

    def timeout_runner(idx: int) -> tuple[bool, int, float, int, int, str | None]:
        return False, 124, 60.0, 0, 1, "Execution timed out after 60 seconds."

    rep = validator.run_stability_validation(runner_fn=timeout_runner)
    assert rep.is_stable is False
    assert rep.classification == "FAILED"
    assert "timed out" in (rep.runs[0].error_message or "")


# --- Scenario N: Resource limit / Memory limit exceeded ---
def test_scenario_n_resource_limit_exceeded() -> None:
    validator = TestStabilityValidator(max_runs=3)

    def oom_runner(idx: int) -> tuple[bool, int, float, int, int, str | None]:
        return False, 137, 2.0, 0, 1, "MemoryError: Out of memory limit"

    rep = validator.run_stability_validation(runner_fn=oom_runner)
    assert rep.is_stable is False
    assert rep.classification == "FAILED"


# --- Scenario O: Unsafe file access attempt (protected configuration files) ---
def test_scenario_o_unsafe_file_access_attempt() -> None:
    rejection = check_generated_test_path("tests/conftest.py", "pytest")
    assert rejection is not None
    assert "reserved" in rejection.lower() or "automatically executed" in rejection.lower()

    rejection2 = check_generated_test_path("pytest.ini", "pytest")
    assert rejection2 is not None


# --- Scenario P: Path traversal attempt ---
def test_scenario_p_path_traversal_attempt() -> None:
    from app.core.input_security import validate_repo_relative_path, UnsafePathError
    with pytest.raises(UnsafePathError):
        validate_repo_relative_path("../../etc/passwd")

    rejection = check_generated_test_path("../../etc/passwd", "pytest")
    assert rejection is not None


# --- Scenario Q: Attempt to access environment secrets ---
def test_scenario_q_secret_redaction() -> None:
    res = TestGenerationResult(
        detected_framework="pytest",
        proposed_test_path="tests/test_sec.py",
        test_content="API_KEY = 'sk-proj-123456789012345678901234567890123456789012345678'",
        covered_scenarios=[
            TestScenario(
                name="Key test",
                category="normal",
                description="Token: ghp_123456789012345678901234567890123456",
            )
        ],
        syntax_valid=True,
    )

    resolved = MagicMock()
    resolved.target.path = "sec.py"
    resolved.indexed_paths = []
    resolved.revision = "HEAD"
    resolved.file_record = None

    detection = MagicMock()
    detection.warnings = ["Found key sk-proj-123456789012345678901234567890123456789012345678"]
    detection.is_ambiguous = False

    sanitized = validate_and_sanitize_generated_tests(
        res,
        repository_id=uuid4(),
        resolved=resolved,
        detection=detection,
        default_proposed_path="tests/test_sec.py",
    )
    assert "sk-proj-" not in sanitized.test_content
    assert "[REDACTED]" in sanitized.test_content
    assert "ghp_" not in sanitized.covered_scenarios[0].description


# --- Scenario R: Pre-existing baseline test failures ---
def test_scenario_r_baseline_failures_tracked_separately() -> None:
    cov_svc = TestCoverageService()
    baseline = TargetCoverageData(
        line_coverage=20.0,
        covered_lines=[1],
        uncovered_lines=[2, 3],
        error_message="Baseline test suite had 1 failing test",
    )
    post_gen = TargetCoverageData(
        line_coverage=60.0,
        covered_lines=[1, 2],
        uncovered_lines=[3],
    )
    rep = cov_svc.calculate_coverage_gain(baseline, post_gen, "src/code.py")
    assert rep.line_coverage_gain == 40.0
    assert rep.newly_covered_lines == [2]


# --- Scenario S: Coverage collection failure ---
def test_scenario_s_coverage_collection_failure() -> None:
    cov_svc = TestCoverageService()
    baseline = TargetCoverageData(
        collection_status="FAILED",
        error_message="Coverage tool segmentation fault",
    )
    post_gen = TargetCoverageData(
        collection_status="FAILED",
        error_message="Coverage tool segmentation fault",
    )
    rep = cov_svc.calculate_coverage_gain(baseline, post_gen, "src/code.py")
    assert rep.collection_status == "FAILED"
    assert rep.coverage_attributable_to_generated_tests is False
    assert len(rep.warnings) > 0


# --- Scenario T: Generation budget exhausted ---
def test_scenario_t_generation_budget_exhausted() -> None:
    orchestrator = TestIterationOrchestrator(max_rounds=3)
    cont, reason = orchestrator.should_continue_iteration(
        current_round=3,
        prev_coverage=40.0,
        new_coverage=50.0,
        uncovered_lines=[5, 6],
    )
    assert cont is False
    assert "Maximum generation rounds" in reason


# --- Scenario U: Maximum iteration limit reached ---
def test_scenario_u_max_iteration_limit_reached() -> None:
    orchestrator = TestIterationOrchestrator(max_rounds=3)
    cont, reason = orchestrator.should_continue_iteration(
        current_round=3,
        prev_coverage=75.0,
        new_coverage=80.0,
        uncovered_lines=[10],
    )
    assert cont is False
    assert "3" in reason


# --- Scenario V: Temporary workspace cleanup failure ---
def test_scenario_v_workspace_cleanup_failure_resilience(tmp_path: Path) -> None:
    mock_ws = MagicMock()
    ws_meta = WorkspaceMetadata(
        workspace_id="ws-v",
        task_id="t-v",
        repository_id=str(uuid4()),
        base_revision="0123456789abcdef0123456789abcdef01234567",
        branch_name="agent/t-v",
        workspace_path=str(tmp_path),
        status=WorkspaceStatus.READY,
    )
    mock_ws.create_workspace.return_value = ws_meta
    mock_ws.cleanup_workspace.side_effect = RuntimeError("Permission denied during rmdir")

    mock_stability = MagicMock()
    mock_stability.validate_with_sandbox_test_runner.return_value = StabilityReport(
        total_runs=3,
        passed_runs=3,
        classification="STABLE",
        is_stable=True,
        runs=[StabilityRunResult(run_number=1, passed=True, duration_seconds=0.1, passed_count=1, failed_count=0)],
    )

    mock_cov = MagicMock()
    mock_cov.calculate_coverage_gain.return_value = CoverageReport(
        line_coverage_gain=20.0,
        coverage_attributable_to_generated_tests=True,
        collection_status="SUCCESS",
    )

    verifier = TestExecutionVerifier(
        workspace_manager=mock_ws,
        stability_validator=mock_stability,
        coverage_service=mock_cov,
    )
    res = _make_dummy_result(syntax_valid=True)

    # Must complete and return VERIFIED without crashing despite cleanup failure
    verified = verifier.verify_generated_test(
        result=res,
        target_path="calc.py",
        target_source_code="def add(a, b): return a + b",
        repository_id=str(uuid4()),
    )
    assert verified.verification_status == "VERIFIED"
    mock_ws.cleanup_workspace.assert_called_once()
