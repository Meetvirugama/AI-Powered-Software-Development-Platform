"""Comprehensive Test Suite for F23 Restricted Test Runner (Issue #204).

Owner: Om Vaghela — Issue #204 Deliverable
Reference:
- Issue #204 (F23 Restricted Test Runner)
- Recommendations:
  1. Isolated container backend (F20) with network disabled and bounded limits.
  2. Structured JUnit XML parsing for reliable test failure diagnosis.
  3. Automated line and branch coverage collection (F13 dependency).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from app.schemas.workspace import (
    CoverageMetric,
    FileCoverageDetail,
    TestCaseResult,
    TestCoverageSummary,
    TestOutcomeStatus,
    TestSuiteResult,
    WorkspaceCommandResult,
    WorkspaceTestExecutionRequest,
    WorkspaceTestExecutionResult,
)
from sandbox.backend import SandboxBackend
from sandbox.command_runner import WorkspaceCommandRunner
from sandbox.test_reports import CoverageReportParser, JUnitReportParser
from sandbox.test_runner import WorkspaceTestRunner
from sandbox.tool_policy_bridge import (
    TOOL_RUN_TESTS,
    WorkspaceToolPolicyBridge,
)
from sandbox.workspace_manager import WorkspaceManager


# ---------------------------------------------------------------------------
# 1. JUnit XML Parser Unit Tests
# ---------------------------------------------------------------------------

SAMPLE_PYTEST_JUNIT_XML = """<?xml version="1.0" encoding="utf-8"?>
<testsuites>
  <testsuite name="pytest" errors="1" failures="1" skipped="1" tests="4" time="0.852">
    <testcase classname="tests.test_auth" file="tests/test_auth.py" name="test_login_success" time="0.120" />
    <testcase classname="tests.test_auth" file="tests/test_auth.py" name="test_login_invalid_password" time="0.085">
      <failure message="AssertionError: 401 != 200" type="AssertionError">
def test_login_invalid_password():
&gt;       assert response.status_code == 200
E       AssertionError: 401 != 200
tests/test_auth.py:42: AssertionError
      </failure>
    </testcase>
    <testcase classname="tests.test_auth" file="tests/test_auth.py" name="test_login_rate_limited" time="0.045">
      <skipped message="Redis rate limiter unavailable" type="pytest.skip" />
    </testcase>
    <testcase classname="tests.test_auth" file="tests/test_auth.py" name="test_database_down" time="0.602">
      <error message="ConnectionRefusedError: [Errno 111] Connection refused" type="ConnectionRefusedError">
Traceback (most recent call last):
  File "tests/test_auth.py", line 88, in test_database_down
    connect_db()
ConnectionRefusedError: [Errno 111] Connection refused
      </error>
    </testcase>
  </testsuite>
</testsuites>
"""

SAMPLE_JEST_JUNIT_XML = """<?xml version="1.0" encoding="UTF-8"?>
<testsuites name="jest tests" tests="2" failures="1" time="1.45">
  <testsuite name="AuthService" errors="0" failures="1" skipped="0" tests="2" time="1.2">
    <testcase classname="AuthService should validate token" name="AuthService should validate token" time="0.05" />
    <testcase classname="AuthService should reject expired token" name="AuthService should reject expired token" time="0.08">
      <failure message="Error: expect(received).toBe(expected)">
Error: expect(received).toBe(expected)
Expected: 403
Received: 200
      </failure>
    </testcase>
  </testsuite>
</testsuites>
"""


def test_junit_parser_standard_pytest_xml() -> None:
    """Verify standard pytest JUnit XML parsing with passed, failed, skipped, and error cases."""
    suite = JUnitReportParser.parse_xml(SAMPLE_PYTEST_JUNIT_XML)

    assert suite.name == "pytest"
    assert suite.tests_total == 4
    assert suite.passed == 1
    assert suite.failed == 1
    assert suite.skipped == 1
    assert suite.errors == 1
    assert suite.time_s == 0.852
    assert len(suite.test_cases) == 4

    # Check passed test case
    tc_pass = suite.test_cases[0]
    assert tc_pass.name == "test_login_success"
    assert tc_pass.classname == "tests.test_auth"
    assert tc_pass.file == "tests/test_auth.py"
    assert tc_pass.status == "passed"
    assert tc_pass.failure_message is None

    # Check failed test case
    tc_fail = suite.test_cases[1]
    assert tc_fail.name == "test_login_invalid_password"
    assert tc_fail.status == "failed"
    assert "AssertionError: 401 != 200" in (tc_fail.failure_message or "")
    assert tc_fail.failure_type == "AssertionError"
    assert "AssertionError: 401 != 200" in (tc_fail.traceback or "")

    # Check skipped test case
    tc_skip = suite.test_cases[2]
    assert tc_skip.name == "test_login_rate_limited"
    assert tc_skip.status == "skipped"
    assert "Redis rate limiter unavailable" in (tc_skip.failure_message or "")

    # Check error test case
    tc_err = suite.test_cases[3]
    assert tc_err.name == "test_database_down"
    assert tc_err.status == "error"
    assert "ConnectionRefusedError" in (tc_err.failure_type or "")


def test_junit_parser_jest_xml() -> None:
    """Verify Jest JUnit XML parsing."""
    suite = JUnitReportParser.parse_xml(SAMPLE_JEST_JUNIT_XML)

    assert suite.tests_total == 2
    assert suite.passed == 1
    assert suite.failed == 1
    assert suite.errors == 0
    assert suite.skipped == 0
    assert len(suite.test_cases) == 2


def test_junit_parser_malformed_xml() -> None:
    """Verify malformed XML falls back safely without raising exceptions."""
    suite = JUnitReportParser.parse_xml("<not_valid_xml><unclosed>")
    assert suite.name == "malformed"
    assert suite.tests_total == 0
    assert suite.test_cases == []


def test_junit_parser_empty_content() -> None:
    """Verify empty string returns empty suite result."""
    suite = JUnitReportParser.parse_xml("")
    assert suite.name == "empty"
    assert suite.tests_total == 0


def test_junit_parser_nonexistent_file(tmp_path: Path) -> None:
    """Verify nonexistent file returns empty suite without throwing."""
    missing = tmp_path / "does_not_exist.xml"
    suite = JUnitReportParser.parse_file(missing)
    assert suite.name == "empty"
    assert suite.tests_total == 0


# ---------------------------------------------------------------------------
# 2. Coverage Report Parser Unit Tests
# ---------------------------------------------------------------------------

SAMPLE_PYTEST_COV_JSON = json.dumps({
    "meta": {"version": "7.1.0"},
    "totals": {
        "covered_lines": 85,
        "num_statements": 100,
        "percent_covered": 85.0,
        "missing_lines": 15,
        "excluded_lines": 2,
        "num_branches": 20,
        "covered_branches": 16,
        "missing_branches": 4,
    },
    "files": {
        "app/services/auth.py": {
            "executed_lines": [1, 2, 3, 5, 8],
            "missing_lines": [10, 11],
            "summary": {
                "covered_lines": 40,
                "num_statements": 50,
                "percent_covered": 80.0,
                "missing_lines": 10,
                "num_branches": 10,
                "covered_branches": 8,
            },
        },
        "app/core/config.py": {
            "executed_lines": [1, 2, 3, 4],
            "missing_lines": [],
            "summary": {
                "covered_lines": 45,
                "num_statements": 50,
                "percent_covered": 90.0,
                "missing_lines": 5,
                "num_branches": 10,
                "covered_branches": 8,
            },
        },
    },
})

SAMPLE_JEST_SUMMARY_JSON = json.dumps({
    "total": {
        "lines": {"total": 200, "covered": 180, "skipped": 0, "pct": 90.0},
        "statements": {"total": 200, "covered": 180, "skipped": 0, "pct": 90.0},
        "functions": {"total": 40, "covered": 36, "skipped": 0, "pct": 90.0},
        "branches": {"total": 50, "covered": 40, "skipped": 0, "pct": 80.0},
    },
    "src/index.ts": {
        "lines": {"total": 100, "covered": 90, "skipped": 0, "pct": 90.0},
        "statements": {"total": 100, "covered": 90, "skipped": 0, "pct": 90.0},
        "functions": {"total": 20, "covered": 18, "skipped": 0, "pct": 90.0},
        "branches": {"total": 25, "covered": 20, "skipped": 0, "pct": 80.0},
    },
})


def test_coverage_parser_pytest_cov_json() -> None:
    """Verify pytest-cov / coverage.py JSON parser with lines and branch metrics."""
    cov = CoverageReportParser.parse_json(SAMPLE_PYTEST_COV_JSON, framework="pytest")

    assert cov.total_percent == 85.0
    assert cov.lines.total == 100
    assert cov.lines.covered == 85
    assert cov.lines.percent == 85.0
    assert cov.branches.total == 20
    assert cov.branches.covered == 16
    assert cov.branches.percent == 80.0

    # Per-file coverage
    assert "app/services/auth.py" in cov.files
    auth_detail = cov.files["app/services/auth.py"]
    assert auth_detail.lines.covered == 40
    assert auth_detail.lines.total == 50
    assert auth_detail.branches.covered == 8
    assert auth_detail.branches.total == 10
    assert auth_detail.missing_lines == [10, 11]
    assert auth_detail.executed_lines == [1, 2, 3, 5, 8]


def test_coverage_parser_jest_summary_json() -> None:
    """Verify Jest / Istanbul summary JSON parsing."""
    cov = CoverageReportParser.parse_json(SAMPLE_JEST_SUMMARY_JSON, framework="jest")

    assert cov.total_percent == 90.0
    assert cov.lines.total == 200
    assert cov.lines.covered == 180
    assert cov.branches.total == 50
    assert cov.branches.covered == 40
    assert cov.branches.percent == 80.0
    assert cov.functions.total == 40
    assert cov.functions.covered == 36

    assert "src/index.ts" in cov.files
    idx_detail = cov.files["src/index.ts"]
    assert idx_detail.lines.covered == 90
    assert idx_detail.branches.covered == 20


def test_coverage_parser_malformed_json() -> None:
    """Verify malformed coverage JSON returns empty summary without error."""
    cov = CoverageReportParser.parse_json("{invalid json}")
    assert cov.total_percent == 0.0
    assert cov.lines.total == 0


def test_coverage_parser_missing_file(tmp_path: Path) -> None:
    """Verify missing coverage report file returns empty summary."""
    missing = tmp_path / "coverage_missing.json"
    cov = CoverageReportParser.parse_file(missing)
    assert cov.total_percent == 0.0
    assert cov.lines.total == 0


# ---------------------------------------------------------------------------
# 3. WorkspaceTestRunner with Container Backend (F20 Isolation)
# ---------------------------------------------------------------------------

class MockIsolatedContainerBackend(SandboxBackend):
    """Mock container sandbox backend for testing isolated execution."""

    def __init__(self) -> None:
        self.executed_commands: list[dict[str, Any]] = []

    @property
    def backend_type(self) -> str:
        return "container"

    def create_workspace(self, task_id: str, base_repo_path: Path | None = None) -> Path:
        return Path(f"/tmp/workspaces/{task_id}")

    def read_file(self, task_id: str, relative_path: str) -> str:
        return ""

    def write_file(self, task_id: str, relative_path: str, content: str) -> None:
        pass

    def get_diff(self, task_id: str) -> str:
        return ""

    def destroy_workspace(self, task_id: str) -> None:
        pass

    def get_status(self, task_id: str) -> dict[str, Any]:
        return {"status": "running"}

    def get_resource_usage(self, task_id: str) -> dict[str, Any]:
        return {"cpu_percent": 0.0, "memory_mb": 0.0}

    def execute(
        self,
        task_id: str,
        command: str,
        arguments: list[str],
        cwd: Path,
        timeout_seconds: int = 60,
        custom_env: dict[str, str] | None = None,
        network_enabled: bool = False,
    ) -> WorkspaceCommandResult:
        self.executed_commands.append({
            "task_id": task_id,
            "command": command,
            "arguments": arguments,
            "cwd": cwd,
            "timeout_seconds": timeout_seconds,
            "network_enabled": network_enabled,
        })
        return WorkspaceCommandResult(
            success=True,
            command=command,
            exit_code=0,
            stdout="==== 2 passed in 0.12s ====",
            duration_ms=120.0,
        )


def test_test_runner_backend_binding_and_isolation(tmp_path: Path) -> None:
    """Verify WorkspaceTestRunner configures container backend and executes with network_enabled=False."""
    mock_backend = MockIsolatedContainerBackend()
    runner = WorkspaceTestRunner(backend=mock_backend)

    assert runner.backend is mock_backend
    assert runner.backend.backend_type == "container"

    # Setup dummy workspace
    workspace = tmp_path / "workspaces" / "task-100"
    workspace.mkdir(parents=True, exist_ok=True)
    (workspace / "tests").mkdir()
    (workspace / "tests" / "test_sample.py").write_text("def test_ok(): pass\n")

    req = WorkspaceTestExecutionRequest(
        task_id="task-100",
        framework="pytest",
        test_path="tests/test_sample.py",
        arguments=[],
        collect_coverage=False,
        junit_xml=False,
    )
    result = runner.run_tests(workspace, req)

    assert result.success is True
    assert len(mock_backend.executed_commands) == 1
    call = mock_backend.executed_commands[0]
    assert call["command"] == "pytest"
    assert call["network_enabled"] is False  # Mandatory container network isolation (F20)
    assert call["task_id"] == "task-100"


def test_test_runner_backend_setter(tmp_path: Path) -> None:
    """Verify backend getter and setter properties."""
    runner = WorkspaceTestRunner()
    assert runner.backend is None

    mock_backend = MockIsolatedContainerBackend()
    runner.backend = mock_backend
    assert runner.backend is mock_backend


# ---------------------------------------------------------------------------
# 4. Structured JUnit XML & Coverage Parsing Integration in TestRunner
# ---------------------------------------------------------------------------

def test_test_runner_parses_emitted_junit_and_coverage(tmp_path: Path) -> None:
    """Verify WorkspaceTestRunner parses JUnit XML and coverage files emitted by the test run."""
    workspace = tmp_path / "workspaces" / "task-200"
    reports_dir = workspace / ".test_reports"
    reports_dir.mkdir(parents=True, exist_ok=True)

    # Write simulated JUnit XML and Coverage JSON into .test_reports
    (reports_dir / "junit.xml").write_text(SAMPLE_PYTEST_JUNIT_XML, encoding="utf-8")
    (reports_dir / "coverage.json").write_text(SAMPLE_PYTEST_COV_JSON, encoding="utf-8")

    class MockTestCommandRunner(WorkspaceCommandRunner):
        def run_command(self, *args, **kwargs) -> WorkspaceCommandResult:
            return WorkspaceCommandResult(
                success=False,
                command="pytest",
                exit_code=1,
                stdout="= 1 failed, 1 passed, 1 skipped, 1 error in 0.85s =",
                duration_ms=850.0,
            )

    runner = WorkspaceTestRunner(command_runner=MockTestCommandRunner())

    req = WorkspaceTestExecutionRequest(
        task_id="task-200",
        framework="pytest",
        collect_coverage=True,
        junit_xml=True,
    )
    result = runner.run_tests(workspace, req)

    # Structured JUnit XML verified
    assert result.junit_report is not None
    assert result.junit_report.name == "pytest"
    assert result.junit_report.tests_total == 4
    assert result.junit_report.passed == 1
    assert result.junit_report.failed == 1
    assert result.junit_report.skipped == 1
    assert result.junit_report.errors == 1

    # Exact failing test names from XML
    assert any("test_login_invalid_password" in name for name in result.failed_test_names)
    assert any("test_database_down" in name for name in result.failed_test_names)

    # Structured Coverage verified
    assert result.coverage is not None
    assert result.coverage.total_percent == 85.0
    assert result.coverage.lines.total == 100
    assert result.coverage.lines.covered == 85
    assert result.coverage.branches.total == 20
    assert result.coverage.branches.covered == 16


def test_test_runner_argument_injection(tmp_path: Path) -> None:
    """Verify --junitxml and --cov arguments are injected when enabled."""
    captured_args: list[str] = []

    class MockArgCaptureRunner(WorkspaceCommandRunner):
        def run_command(self, *args, **kwargs) -> WorkspaceCommandResult:
            captured_args.extend(kwargs.get("arguments", []))
            return WorkspaceCommandResult(
                success=True,
                command="pytest",
                exit_code=0,
                stdout="==== 1 passed in 0.05s ====",
                duration_ms=50.0,
            )

    runner = WorkspaceTestRunner(command_runner=MockArgCaptureRunner())
    workspace = tmp_path / "workspaces" / "task-300"
    workspace.mkdir(parents=True, exist_ok=True)

    req = WorkspaceTestExecutionRequest(
        task_id="task-300",
        framework="pytest",
        collect_coverage=True,
        junit_xml=True,
    )
    runner.run_tests(workspace, req)

    assert any(a.startswith("--junitxml=") for a in captured_args)
    assert "-o" in captured_args
    assert "junit_family=xunit2" in captured_args


# ---------------------------------------------------------------------------
# 5. ToolPolicyBridge Integration with JUnit & Coverage
# ---------------------------------------------------------------------------

def test_tool_policy_bridge_run_tests_with_reports(tmp_path: Path) -> None:
    """Verify ToolPolicyBridge returns junit_report and coverage in ToolResult output."""
    from app.schemas.workspace import WorkspaceCreateRequest, WorkspaceStartExecutionRequest

    repo_dir = tmp_path / "mock_repo"
    repo_dir.mkdir(parents=True, exist_ok=True)
    (repo_dir / "pytest.ini").write_text("[pytest]\n", encoding="utf-8")

    wm = WorkspaceManager(base_workspaces_dir=tmp_path / "wm_workspaces")
    create_req = WorkspaceCreateRequest(
        task_id="task-400",
        repository_id="repo-400",
        base_revision="a1b2c3d4e5f67890abcdef1234567890abcdef12",
        repository_root=str(repo_dir),
        isolation_type="directory_copy",
    )
    meta = wm.create_workspace(create_req)
    ws_path = Path(meta.workspace_path)

    start_req = WorkspaceStartExecutionRequest(
        task_id="task-400",
        approved_base_revision="a1b2c3d4e5f67890abcdef1234567890abcdef12",
        task_status="APPROVED",
    )
    wm.start_execution(start_req)

    # Setup simulated reports
    reports_dir = ws_path / ".test_reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    (reports_dir / "junit.xml").write_text(SAMPLE_PYTEST_JUNIT_XML, encoding="utf-8")
    (reports_dir / "coverage.json").write_text(SAMPLE_PYTEST_COV_JSON, encoding="utf-8")

    class MockPassingRunner(WorkspaceCommandRunner):
        def run_command(self, *args, **kwargs) -> WorkspaceCommandResult:
            return WorkspaceCommandResult(
                success=True,
                command="pytest",
                exit_code=0,
                stdout="==== 4 passed ====",
                duration_ms=100.0,
            )

    wm.test_runner._command_runner = MockPassingRunner()

    bridge = WorkspaceToolPolicyBridge(wm)
    from agent.tools.router import ToolRequest

    req = ToolRequest(
        tool_name=TOOL_RUN_TESTS,
        arguments={
            "collect_coverage": True,
            "junit_xml": True,
        },
    )
    result = bridge.execute_tool(req, agent_state={"task_id": "task-400"})

    assert result.success is True
    assert isinstance(result.output, dict)
    assert "junit_report" in result.output
    assert result.output["junit_report"]["tests_total"] == 4
    assert "coverage" in result.output
    assert result.output["coverage"]["total_percent"] == 85.0
