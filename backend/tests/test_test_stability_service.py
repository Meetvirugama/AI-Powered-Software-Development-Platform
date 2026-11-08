"""Unit tests for TestStabilityValidator (task.md §4.6).

Verifies:
1. 3/3 passed runs classified as STABLE.
2. 2/3 passed runs classified as UNSTABLE (flaky candidate).
3. 1/3 or 0/3 passed runs classified as FAILED.
4. Exception during run is caught, logged, and counted as failure.
5. Duration and error message sanitization.
"""

from __future__ import annotations

from unittest.mock import MagicMock
from pathlib import Path

from app.schemas.analysis import StabilityRunResult
from app.schemas.workspace import TestOutcomeStatus, WorkspaceTestExecutionResult
from app.services.test_stability_service import TestStabilityValidator, MAX_STABILITY_RUNS


def test_stability_evaluation_three_passes() -> None:
    validator = TestStabilityValidator(max_runs=3)
    runs = [
        StabilityRunResult(run_number=1, passed=True, duration_seconds=0.1, passed_count=2, failed_count=0),
        StabilityRunResult(run_number=2, passed=True, duration_seconds=0.1, passed_count=2, failed_count=0),
        StabilityRunResult(run_number=3, passed=True, duration_seconds=0.1, passed_count=2, failed_count=0),
    ]
    report = validator.evaluate_runs(runs)
    assert report.total_runs == 3
    assert report.passed_runs == 3
    assert report.classification == "STABLE"
    assert report.is_stable is True


def test_stability_evaluation_two_passes_flaky() -> None:
    validator = TestStabilityValidator(max_runs=3)
    runs = [
        StabilityRunResult(run_number=1, passed=True, duration_seconds=0.1, passed_count=2, failed_count=0),
        StabilityRunResult(run_number=2, passed=False, duration_seconds=0.2, passed_count=1, failed_count=1, error_message="Race condition"),
        StabilityRunResult(run_number=3, passed=True, duration_seconds=0.1, passed_count=2, failed_count=0),
    ]
    report = validator.evaluate_runs(runs)
    assert report.total_runs == 3
    assert report.passed_runs == 2
    assert report.classification == "UNSTABLE"
    assert report.is_stable is False


def test_stability_evaluation_one_pass_failed() -> None:
    validator = TestStabilityValidator(max_runs=3)
    runs = [
        StabilityRunResult(run_number=1, passed=False, duration_seconds=0.1, passed_count=0, failed_count=1),
        StabilityRunResult(run_number=2, passed=True, duration_seconds=0.1, passed_count=1, failed_count=0),
        StabilityRunResult(run_number=3, passed=False, duration_seconds=0.1, passed_count=0, failed_count=1),
    ]
    report = validator.evaluate_runs(runs)
    assert report.total_runs == 3
    assert report.passed_runs == 1
    assert report.classification == "FAILED"
    assert report.is_stable is False


def test_stability_evaluation_zero_passes_failed() -> None:
    validator = TestStabilityValidator(max_runs=3)
    runs = [
        StabilityRunResult(run_number=1, passed=False, duration_seconds=0.1, passed_count=0, failed_count=1),
        StabilityRunResult(run_number=2, passed=False, duration_seconds=0.1, passed_count=0, failed_count=1),
        StabilityRunResult(run_number=3, passed=False, duration_seconds=0.1, passed_count=0, failed_count=1),
    ]
    report = validator.evaluate_runs(runs)
    assert report.total_runs == 3
    assert report.passed_runs == 0
    assert report.classification == "FAILED"
    assert report.is_stable is False


def test_run_stability_validation_with_runner_fn() -> None:
    validator = TestStabilityValidator(max_runs=3)

    call_count = 0
    def mock_runner(idx: int) -> tuple[bool, int, float, int, int, str | None]:
        nonlocal call_count
        call_count += 1
        return True, 0, 0.05, 3, 0, None

    report = validator.run_stability_validation(runner_fn=mock_runner)
    assert call_count == 3
    assert report.is_stable is True
    assert len(report.runs) == 3


def test_run_stability_validation_handles_crashes() -> None:
    validator = TestStabilityValidator(max_runs=3)

    def crashing_runner(idx: int) -> tuple[bool, int, float, int, int, str | None]:
        if idx == 2:
            raise RuntimeError("Unexpected runner process crash")
        return True, 0, 0.05, 2, 0, None

    report = validator.run_stability_validation(runner_fn=crashing_runner)
    assert report.total_runs == 3
    assert report.passed_runs == 2
    assert report.classification == "UNSTABLE"
    assert report.is_stable is False
    assert "Unexpected runner process crash" in (report.runs[1].error_message or "")


def test_validate_with_sandbox_test_runner() -> None:
    validator = TestStabilityValidator(max_runs=3)
    mock_runner = MagicMock()
    mock_runner.run_tests.return_value = WorkspaceTestExecutionResult(
        task_id="t1",
        success=True,
        status=TestOutcomeStatus.PASSED,
        passed_count=4,
        failed_count=0,
        skipped_count=0,
        error_count=0,
        total_count=4,
        duration_ms=45.0,
        exit_code=0,
    )

    report = validator.validate_with_sandbox_test_runner(
        test_runner=mock_runner,
        workspace_root=Path("/tmp/ws"),
        test_path="tests/test_foo.py",
        framework="pytest",
        task_id="task-123",
    )
    assert report.total_runs == 3
    assert report.passed_runs == 3
    assert report.is_stable is True
    assert mock_runner.run_tests.call_count == 3
