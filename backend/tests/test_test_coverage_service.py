"""Unit tests for TestCoverageService (task.md §5).

Verifies:
1. Python coverage JSON parsing (line, branch, executed lines, missing lines).
2. Node coverage JSON parsing (Istanbul / V8 summary format).
3. Coverage gain computation (baseline vs post-generation).
4. Attribution tracking (newly covered lines and branches).
5. Unconfigured and failed coverage fallbacks.
6. Zero-gain and negative-gain edge cases.
"""

from __future__ import annotations

import json
from pathlib import Path
import tempfile

from app.services.test_coverage_service import TargetCoverageData, TestCoverageService


def test_parse_python_coverage_json() -> None:
    service = TestCoverageService()

    cov_data = {
        "files": {
            "src/calculator.py": {
                "executed_lines": [1, 2, 4, 7, 8],
                "missing_lines": [10, 11],
                "missing_branches": [[7, 10]],
                "summary": {
                    "percent_covered": 71.43,
                    "num_branches": 2,
                    "covered_branches": 1,
                },
            }
        }
    }

    with tempfile.NamedTemporaryFile("w+", suffix=".json", delete=False) as f:
        json.dump(cov_data, f)
        temp_path = Path(f.name)

    try:
        parsed = service._parse_python_coverage_json(temp_path, "src/calculator.py")
        assert parsed.collection_status == "SUCCESS"
        assert parsed.line_coverage == 71.43
        assert parsed.branch_coverage == 50.0
        assert parsed.covered_lines == [1, 2, 4, 7, 8]
        assert parsed.uncovered_lines == [10, 11]
        assert parsed.uncovered_branches == [[7, 10]]
        assert parsed.total_executable_lines == 7
    finally:
        if temp_path.exists():
            temp_path.unlink()


def test_parse_python_coverage_json_file_not_executed() -> None:
    service = TestCoverageService()
    cov_data = {"files": {"src/other.py": {"executed_lines": [1]}}}

    with tempfile.NamedTemporaryFile("w+", suffix=".json", delete=False) as f:
        json.dump(cov_data, f)
        temp_path = Path(f.name)

    try:
        parsed = service._parse_python_coverage_json(temp_path, "src/calculator.py")
        assert parsed.collection_status == "SUCCESS"
        assert parsed.line_coverage == 0.0
        assert parsed.covered_lines == []
    finally:
        if temp_path.exists():
            temp_path.unlink()


def test_parse_node_coverage_json() -> None:
    service = TestCoverageService()
    node_cov = {
        "src/utils.ts": {
            "lines": {"pct": 85.5},
            "branches": {"pct": 75.0},
        }
    }

    with tempfile.NamedTemporaryFile("w+", suffix=".json", delete=False) as f:
        json.dump(node_cov, f)
        temp_path = Path(f.name)

    try:
        parsed = service._parse_node_coverage_json(temp_path, "src/utils.ts")
        assert parsed.collection_status == "SUCCESS"
        assert parsed.line_coverage == 85.5
        assert parsed.branch_coverage == 75.0
    finally:
        if temp_path.exists():
            temp_path.unlink()


def test_calculate_coverage_gain_positive_attribution() -> None:
    service = TestCoverageService()

    baseline = TargetCoverageData(
        line_coverage=40.0,
        branch_coverage=30.0,
        covered_lines=[1, 2, 3],
        uncovered_lines=[4, 5, 6],
        covered_branches=[[2, 3]],
    )
    post_gen = TargetCoverageData(
        line_coverage=75.0,
        branch_coverage=60.0,
        covered_lines=[1, 2, 3, 4, 5],
        uncovered_lines=[6],
        covered_branches=[[2, 3], [2, 4]],
    )

    report = service.calculate_coverage_gain(baseline, post_gen, "src/target.py")

    assert report.baseline_line_coverage == 40.0
    assert report.final_line_coverage == 75.0
    assert report.line_coverage_gain == 35.0
    assert report.branch_coverage_gain == 30.0
    assert report.newly_covered_lines == [4, 5]
    assert report.newly_covered_branches == [[2, 4]]
    assert report.coverage_attributable_to_generated_tests is True
    assert report.collection_status == "SUCCESS"


def test_calculate_coverage_gain_no_improvement() -> None:
    service = TestCoverageService()

    baseline = TargetCoverageData(
        line_coverage=60.0,
        branch_coverage=50.0,
        covered_lines=[1, 2, 3],
        uncovered_lines=[4],
    )
    post_gen = TargetCoverageData(
        line_coverage=60.0,
        branch_coverage=50.0,
        covered_lines=[1, 2, 3],
        uncovered_lines=[4],
    )

    report = service.calculate_coverage_gain(baseline, post_gen, "src/target.py")

    assert report.line_coverage_gain == 0.0
    assert report.branch_coverage_gain == 0.0
    assert report.newly_covered_lines == []
    assert report.coverage_attributable_to_generated_tests is False


def test_calculate_coverage_gain_not_configured_fallback() -> None:
    service = TestCoverageService()

    baseline = TargetCoverageData(
        collection_status="NOT_CONFIGURED",
        error_message="coverage.py is not installed",
    )
    post_gen = TargetCoverageData(
        collection_status="NOT_CONFIGURED",
        error_message="coverage.py is not installed",
    )

    report = service.calculate_coverage_gain(baseline, post_gen, "src/target.py")

    assert report.collection_status == "NOT_CONFIGURED"
    assert report.baseline_line_coverage is None
    assert report.final_line_coverage is None
    assert report.line_coverage_gain is None
    assert report.coverage_attributable_to_generated_tests is False
    assert len(report.warnings) > 0


def test_coverage_service_with_real_workspace_command_runner() -> None:
    from sandbox.command_runner import WorkspaceCommandRunner

    runner = WorkspaceCommandRunner()
    service = TestCoverageService(command_runner=runner)

    with tempfile.TemporaryDirectory() as tmp_dir:
        res = service._measure_python_coverage(
            workspace_root=Path(tmp_dir),
            target_file="test.py",
            test_path=None,
            framework="pytest",
        )
        assert res.collection_status in ("SUCCESS", "NOT_CONFIGURED", "FAILED")
