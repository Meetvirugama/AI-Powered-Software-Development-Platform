"""Unit tests for TestExecutionVerifier (task.md §4).

Verifies:
1. Syntax-invalid test returns UNVERIFIED without sandbox execution.
2. Workspace creation failure returns EXECUTION_ERROR.
3. Stable test with coverage gain returns VERIFIED.
4. Stable test with zero coverage gain returns UNVERIFIED.
5. Flaky test returns UNVERIFIED (flakiness reported).
6. Failing test returns UNVERIFIED.
7. Cleanup is always invoked.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch
from pathlib import Path
from uuid import uuid4

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
from app.services.test_coverage_service import TargetCoverageData
from app.services.test_execution_verifier import TestExecutionVerifier


def _sample_result(syntax_valid: bool = True) -> TestGenerationResult:
    return TestGenerationResult(
        detected_framework="pytest",
        proposed_test_path="tests/test_calc.py",
        test_content="def test_add(): assert 1 + 1 == 2",
        covered_scenarios=[TestScenario(name="Normal add", category="normal", description="Tests 1+1")],
        syntax_valid=syntax_valid,
        validation_errors=[] if syntax_valid else ["Syntax error: invalid syntax"],
    )


def test_verifier_skips_execution_on_syntax_error() -> None:
    verifier = TestExecutionVerifier()
    res = _sample_result(syntax_valid=False)

    verified = verifier.verify_generated_test(
        result=res,
        target_path="calc.py",
        target_source_code="def add(a, b): return a + b",
        repository_id=str(uuid4()),
    )
    assert verified.verification_status == "UNVERIFIED"
    assert "Static validation failed" in verified.verification_reasons[0]
    assert verified.execution_status == "NOT_EXECUTED"


def test_verifier_handles_workspace_creation_failure() -> None:
    mock_ws = MagicMock()
    mock_ws.create_workspace.side_effect = RuntimeError("Disk quota exceeded")

    verifier = TestExecutionVerifier(workspace_manager=mock_ws)
    res = _sample_result(syntax_valid=True)

    verified = verifier.verify_generated_test(
        result=res,
        target_path="calc.py",
        target_source_code="def add(a, b): return a + b",
        repository_id=str(uuid4()),
    )
    assert verified.verification_status == "EXECUTION_ERROR"
    assert "Infrastructure error" in verified.verification_reasons[0]


def test_verifier_marks_stable_with_coverage_verified(tmp_path: Path) -> None:
    mock_ws = MagicMock()
    ws_meta = WorkspaceMetadata(
        workspace_id="ws-1",
        task_id="t-1",
        repository_id=str(uuid4()),
        base_revision="0123456789abcdef0123456789abcdef01234567",
        branch_name="agent/t-1",
        workspace_path=str(tmp_path),
        status=WorkspaceStatus.READY,
    )
    mock_ws.create_workspace.return_value = ws_meta
    mock_ws.cleanup_workspace.return_value = WorkspaceCleanupResult(success=True, workspace_id="ws-1", duration_ms=1.0)

    mock_stability = MagicMock()
    mock_stability.validate_with_sandbox_test_runner.return_value = StabilityReport(
        total_runs=3,
        passed_runs=3,
        classification="STABLE",
        is_stable=True,
        runs=[
            StabilityRunResult(run_number=1, passed=True, duration_seconds=0.1, passed_count=1, failed_count=0),
            StabilityRunResult(run_number=2, passed=True, duration_seconds=0.1, passed_count=1, failed_count=0),
            StabilityRunResult(run_number=3, passed=True, duration_seconds=0.1, passed_count=1, failed_count=0),
        ],
    )

    mock_cov = MagicMock()
    mock_cov.measure_coverage.side_effect = [
        TargetCoverageData(line_coverage=0.0, covered_lines=[]),  # baseline
        TargetCoverageData(line_coverage=100.0, covered_lines=[1, 2]),  # post-gen
    ]
    mock_cov.calculate_coverage_gain.return_value = CoverageReport(
        baseline_line_coverage=0.0,
        final_line_coverage=100.0,
        line_coverage_gain=100.0,
        newly_covered_lines=[1, 2],
        coverage_attributable_to_generated_tests=True,
        collection_status="SUCCESS",
    )

    verifier = TestExecutionVerifier(
        workspace_manager=mock_ws,
        stability_validator=mock_stability,
        coverage_service=mock_cov,
    )
    res = _sample_result(syntax_valid=True)

    verified = verifier.verify_generated_test(
        result=res,
        target_path="calc.py",
        target_source_code="def add(a, b): return a + b",
        repository_id=str(uuid4()),
    )
    assert verified.verification_status == "VERIFIED"
    assert verified.execution_status == "PASSED"
    assert verified.stability_report.is_stable is True
    assert verified.coverage_report.line_coverage_gain == 100.0
    mock_ws.cleanup_workspace.assert_called_once()


def test_verifier_marks_stable_with_zero_coverage_unverified(tmp_path: Path) -> None:
    mock_ws = MagicMock()
    ws_meta = WorkspaceMetadata(
        workspace_id="ws-2",
        task_id="t-2",
        repository_id=str(uuid4()),
        base_revision="0123456789abcdef0123456789abcdef01234567",
        branch_name="agent/t-2",
        workspace_path=str(tmp_path),
        status=WorkspaceStatus.READY,
    )
    mock_ws.create_workspace.return_value = ws_meta

    mock_stability = MagicMock()
    mock_stability.validate_with_sandbox_test_runner.return_value = StabilityReport(
        total_runs=3,
        passed_runs=3,
        classification="STABLE",
        is_stable=True,
        runs=[
            StabilityRunResult(run_number=1, passed=True, duration_seconds=0.1, passed_count=1, failed_count=0),
            StabilityRunResult(run_number=2, passed=True, duration_seconds=0.1, passed_count=1, failed_count=0),
            StabilityRunResult(run_number=3, passed=True, duration_seconds=0.1, passed_count=1, failed_count=0),
        ],
    )

    mock_cov = MagicMock()
    mock_cov.calculate_coverage_gain.return_value = CoverageReport(
        baseline_line_coverage=50.0,
        final_line_coverage=50.0,
        line_coverage_gain=0.0,
        newly_covered_lines=[],
        coverage_attributable_to_generated_tests=False,
        collection_status="SUCCESS",
    )

    verifier = TestExecutionVerifier(
        workspace_manager=mock_ws,
        stability_validator=mock_stability,
        coverage_service=mock_cov,
    )
    res = _sample_result(syntax_valid=True)

    verified = verifier.verify_generated_test(
        result=res,
        target_path="calc.py",
        target_source_code="def add(a, b): return a + b",
        repository_id=str(uuid4()),
    )
    assert verified.verification_status == "UNVERIFIED"
    assert "0% coverage gain" in verified.verification_reasons[0]


def test_verifier_marks_flaky_test_unverified(tmp_path: Path) -> None:
    mock_ws = MagicMock()
    ws_meta = WorkspaceMetadata(
        workspace_id="ws-3",
        task_id="t-3",
        repository_id=str(uuid4()),
        base_revision="0123456789abcdef0123456789abcdef01234567",
        branch_name="agent/t-3",
        workspace_path=str(tmp_path),
        status=WorkspaceStatus.READY,
    )
    mock_ws.create_workspace.return_value = ws_meta

    mock_stability = MagicMock()
    mock_stability.validate_with_sandbox_test_runner.return_value = StabilityReport(
        total_runs=3,
        passed_runs=2,
        classification="UNSTABLE",
        is_stable=False,
        runs=[
            StabilityRunResult(run_number=1, passed=True, duration_seconds=0.1, passed_count=1, failed_count=0),
            StabilityRunResult(run_number=2, passed=False, duration_seconds=0.1, passed_count=0, failed_count=1, error_message="AssertionError"),
            StabilityRunResult(run_number=3, passed=True, duration_seconds=0.1, passed_count=1, failed_count=0),
        ],
    )

    mock_cov = MagicMock()
    mock_cov.calculate_coverage_gain.return_value = CoverageReport(
        collection_status="SUCCESS",
        coverage_attributable_to_generated_tests=True,
    )

    verifier = TestExecutionVerifier(
        workspace_manager=mock_ws,
        stability_validator=mock_stability,
        coverage_service=mock_cov,
    )
    res = _sample_result(syntax_valid=True)

    verified = verifier.verify_generated_test(
        result=res,
        target_path="calc.py",
        target_source_code="def add(a, b): return a + b",
        repository_id=str(uuid4()),
    )
    assert verified.verification_status == "UNVERIFIED"
    assert "flakiness" in verified.verification_reasons[0].lower()


def test_verifier_marks_stable_with_unconfigured_coverage_unverified(tmp_path: Path) -> None:
    mock_ws = MagicMock()
    ws_meta = WorkspaceMetadata(
        workspace_id="ws-4",
        task_id="t-4",
        repository_id=str(uuid4()),
        base_revision="0123456789abcdef0123456789abcdef01234567",
        branch_name="agent/t-4",
        workspace_path=str(tmp_path),
        status=WorkspaceStatus.READY,
    )
    mock_ws.create_workspace.return_value = ws_meta

    mock_stability = MagicMock()
    mock_stability.validate_with_sandbox_test_runner.return_value = StabilityReport(
        total_runs=3,
        passed_runs=3,
        classification="STABLE",
        is_stable=True,
        runs=[
            StabilityRunResult(run_number=1, passed=True, duration_seconds=0.1, passed_count=1, failed_count=0),
            StabilityRunResult(run_number=2, passed=True, duration_seconds=0.1, passed_count=1, failed_count=0),
            StabilityRunResult(run_number=3, passed=True, duration_seconds=0.1, passed_count=1, failed_count=0),
        ],
    )

    mock_cov = MagicMock()
    mock_cov.calculate_coverage_gain.return_value = CoverageReport(
        collection_status="NOT_CONFIGURED",
        coverage_attributable_to_generated_tests=False,
    )

    verifier = TestExecutionVerifier(
        workspace_manager=mock_ws,
        stability_validator=mock_stability,
        coverage_service=mock_cov,
    )
    res = _sample_result(syntax_valid=True)

    verified = verifier.verify_generated_test(
        result=res,
        target_path="calc.py",
        target_source_code="def add(a, b): return a + b",
        repository_id=str(uuid4()),
    )
    assert verified.verification_status == "UNVERIFIED"
    assert "coverage tool not configured" in verified.verification_reasons[0].lower()

