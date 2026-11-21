"""Module 9 (Automated Test Generation) audit fixes."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

from app.schemas.analysis import (
    CoverageReport,
    StabilityReport,
    StabilityRunResult,
    TestGenerationResult,
    TestQualityReport,
    TestScenario,
)
from app.schemas.workspace import TestOutcomeStatus, WorkspaceMetadata, WorkspaceStatus
from app.services.test_execution_verifier import TestExecutionVerifier
from scanner.framework_detector import FrameworkDetector
from scanner.test_quality_analyzer import TestQualityAnalyzer


# ---------------------------------------------------------------------------
# Framework detection in monorepos
# ---------------------------------------------------------------------------

def _detect(files: dict[str, str], file_list: list[str], target: str):
    detector = FrameworkDetector(repo_root=None)
    detector._read_file = lambda _root, p: files.get(p.replace("\\", "/").lstrip("/"), "")  # type: ignore[method-assign]
    return detector.detect(repo_root=None, target_file=target, file_list=file_list, preferred_framework=None)


def test_python_config_in_subproject_is_found() -> None:
    result = _detect(
        {"services/api/pyproject.toml": "[tool.pytest.ini_options]\n"},
        ["services/api/pyproject.toml", "services/api/app/x.py"],
        "services/api/app/x.py",
    )
    assert result.framework == "pytest"
    assert result.config_file == "services/api/pyproject.toml"


def test_nearest_package_json_wins_over_root() -> None:
    result = _detect(
        {
            "package.json": '{"devDependencies":{"jest":"29"}}',
            "packages/web/package.json": '{"devDependencies":{"vitest":"1"},"scripts":{"test":"vitest"}}',
        },
        ["package.json", "packages/web/package.json", "packages/web/src/a.ts"],
        "packages/web/src/a.ts",
    )
    assert result.framework == "vitest"


def test_root_level_detection_still_works() -> None:
    result = _detect(
        {"package.json": '{"devDependencies":{"jest":"29"},"scripts":{"test":"jest"}}'},
        ["package.json", "src/a.ts"],
        "src/a.ts",
    )
    assert result.framework == "jest"


# ---------------------------------------------------------------------------
# Quality analysis
# ---------------------------------------------------------------------------

def test_tests_of_same_function_with_different_inputs_are_not_duplicates() -> None:
    code = (
        "from m import add\n"
        "def test_pos():\n    assert add(1, 2) == 3\n"
        "def test_neg():\n    assert add(-1, -2) == -3\n"
        "def test_copy():\n    '''doc'''\n    assert add(1, 2) == 3\n"
    )
    dups = TestQualityAnalyzer().inspect_test_code(code, "test_m.py").duplicate_tests
    assert dups == ["Test 'test_copy' duplicates call logic of 'test_pos'"]


# ---------------------------------------------------------------------------
# Safety policy
# ---------------------------------------------------------------------------

def test_method_named_eval_is_not_a_safety_violation() -> None:
    assert TestExecutionVerifier._check_safety_policy("def test_m(model):\n    model.eval()\n") == []
    assert TestExecutionVerifier._check_safety_policy("def test_x():\n    eval('1')\n")


# ---------------------------------------------------------------------------
# Mutation scoring
# ---------------------------------------------------------------------------

_TARGET = "def f(a, b):\n    if a > b:\n        return a + b\n    return 0\n"


def _stable() -> StabilityReport:
    runs = [
        StabilityRunResult(run_number=i, passed=True, duration_seconds=0.1, passed_count=1, failed_count=0)
        for i in (1, 2, 3)
    ]
    return StabilityReport(total_runs=3, passed_runs=3, classification="STABLE", is_stable=True, runs=runs)


def _verifier(tmp_path: Path, stability: StabilityReport) -> tuple[TestExecutionVerifier, MagicMock]:
    ws = MagicMock()
    ws.create_workspace.return_value = WorkspaceMetadata(
        workspace_id="ws",
        task_id="t",
        repository_id=str(uuid4()),
        base_revision="0123456789abcdef0123456789abcdef01234567",
        branch_name="agent/t",
        workspace_path=str(tmp_path),
        status=WorkspaceStatus.READY,
    )

    def run_tests(*, workspace_root, request):
        # The fake suite only asserts on the addition, so it kills the
        # arithmetic mutant and lets the comparison mutant survive.
        source = (Path(workspace_root) / "calc.py").read_text()
        passed = "a + b" in source
        return SimpleNamespace(
            status=TestOutcomeStatus.PASSED if passed else TestOutcomeStatus.FAILED,
            failed_count=0 if passed else 1,
        )

    ws.test_runner.run_tests.side_effect = run_tests
    stab = MagicMock()
    stab.validate_with_sandbox_test_runner.return_value = stability
    cov = MagicMock()
    cov.calculate_coverage_gain.return_value = CoverageReport(
        baseline_line_coverage=0.0,
        final_line_coverage=100.0,
        line_coverage_gain=100.0,
        coverage_attributable_to_generated_tests=True,
        collection_status="SUCCESS",
    )
    return TestExecutionVerifier(workspace_manager=ws, stability_validator=stab, coverage_service=cov), ws


def _result() -> TestGenerationResult:
    return TestGenerationResult(
        detected_framework="pytest",
        proposed_test_path="tests/test_calc.py",
        test_content="from calc import f\ndef test_f():\n    assert f(2, 1) == 3\n",
        covered_scenarios=[TestScenario(name="add", category="normal", description="d")],
        syntax_valid=True,
        validation_errors=[],
        quality_report=TestQualityReport(
            mutation_score_percent=40.0,
            summary_notes=["Mutation score is an estimate from requirement coverage and assertion quality; x"],
        ),
    )


def test_stable_suite_gets_measured_mutation_score_and_target_is_restored(tmp_path: Path) -> None:
    verifier, _ = _verifier(tmp_path, _stable())
    verified = verifier.verify_generated_test(
        result=_result(), target_path="calc.py", target_source_code=_TARGET, repository_id=str(uuid4())
    )
    report = verified.quality_report
    assert report is not None
    assert report.mutation_score_percent == 50.0
    assert any(n.startswith("Mutation score 50%") for n in report.summary_notes)
    assert not any(n.startswith("Mutation score is an estimate") for n in report.summary_notes)
    assert (tmp_path / "calc.py").read_text() == _TARGET


def test_failing_suite_is_not_mutation_scored(tmp_path: Path) -> None:
    failing = StabilityReport(
        total_runs=3,
        passed_runs=0,
        classification="FAILED",
        is_stable=False,
        runs=[StabilityRunResult(run_number=1, passed=False, duration_seconds=0.1, passed_count=0, failed_count=1)],
    )
    verifier, ws = _verifier(tmp_path, failing)
    verified = verifier.verify_generated_test(
        result=_result(), target_path="calc.py", target_source_code=_TARGET, repository_id=str(uuid4())
    )
    ws.test_runner.run_tests.assert_not_called()
    assert verified.quality_report.mutation_score_percent == 40.0
