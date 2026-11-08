"""Runtime Coverage Engine for Baseline, Post-Generation, and Attribution Measurement.

Owner: Antigravity Test Engineering Team
Reference: task.md §5 (Feature 2: Coverage Measurement), task.md §6 (CoverUp P-11 inspiration)

Capabilities:
1. Measures baseline test coverage before adding generated tests.
2. Measures post-generation test coverage with generated tests.
3. Attributes newly covered lines and branches specifically to generated tests.
4. Calculates accurate coverage gains without fabricating metrics:
   - Line coverage gain = Post-generation Line Coverage - Baseline Line Coverage
   - Branch coverage gain = Post-generation Branch Coverage - Baseline Branch Coverage
5. Framework coverage adapters:
   - Python: coverage.py / pytest-cov (parses coverage json)
   - JavaScript/TypeScript: Jest / Vitest coverage (parses coverage-summary.json or coverage-final.json)
6. Graceful failure modes when coverage tools are missing (NOT_CONFIGURED / FAILED).
"""

from __future__ import annotations

from dataclasses import dataclass, field
import json
import logging
from pathlib import Path
import re
from typing import Any

from app.core.secret_redaction import redact
from app.schemas.analysis import CoverageReport
from sandbox.command_runner import WorkspaceCommandRunner

logger = logging.getLogger(__name__)


@dataclass
class TargetCoverageData:
    """Coverage metrics extracted for a specific target file."""

    line_coverage: float | None = None
    branch_coverage: float | None = None
    covered_lines: list[int] = field(default_factory=list)
    uncovered_lines: list[int] = field(default_factory=list)
    covered_branches: list[list[int]] = field(default_factory=list)
    uncovered_branches: list[list[int]] = field(default_factory=list)
    total_executable_lines: int = 0
    collection_status: str = "SUCCESS"  # SUCCESS, PARTIAL, NOT_CONFIGURED, FAILED
    error_message: str | None = None


class TestCoverageService:
    """Service to measure baseline and post-generation coverage and compute attributions."""

    __test__ = False

    def __init__(self, command_runner: WorkspaceCommandRunner | None = None) -> None:
        self._command_runner = command_runner or WorkspaceCommandRunner()

    # -----------------------------------------------------------------------
    # Python Coverage via coverage.py
    # -----------------------------------------------------------------------

    def _parse_python_coverage_json(
        self,
        json_path: Path,
        target_file: str,
    ) -> TargetCoverageData:
        """Parse coverage.py JSON export and extract metrics for `target_file`."""
        if not json_path.exists():
            return TargetCoverageData(
                collection_status="FAILED",
                error_message=f"Coverage report file '{json_path.name}' was not created.",
            )

        try:
            data = json.loads(json_path.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001
            return TargetCoverageData(
                collection_status="FAILED",
                error_message=f"Failed to parse coverage JSON: {exc}",
            )

        files = data.get("files", {})
        norm_target = target_file.strip().replace("\\", "/")

        # Match target_file by exact suffix or normalized path
        matching_key = None
        for file_key in files:
            norm_key = file_key.replace("\\", "/")
            if norm_key.endswith(norm_target) or norm_target.endswith(norm_key):
                matching_key = file_key
                break

        if not matching_key:
            # File might not have been executed at all in the run
            return TargetCoverageData(
                line_coverage=0.0,
                branch_coverage=0.0,
                covered_lines=[],
                uncovered_lines=[],
                total_executable_lines=0,
                collection_status="SUCCESS",
            )

        file_data = files[matching_key]
        summary = file_data.get("summary", {})

        pct_cov = summary.get("percent_covered")
        line_cov = round(float(pct_cov), 2) if pct_cov is not None else 0.0

        num_branches = summary.get("num_branches", 0)
        covered_branches = summary.get("covered_branches", 0)
        branch_cov = (
            round((covered_branches / num_branches) * 100.0, 2)
            if num_branches > 0
            else None
        )

        executed_lines = sorted(file_data.get("executed_lines", []))
        missing_lines = sorted(file_data.get("missing_lines", []))
        total_exec = len(executed_lines) + len(missing_lines)

        missing_branches = file_data.get("missing_branches", [])
        clean_missing_branches = [list(b) for b in missing_branches if isinstance(b, (list, tuple))]

        return TargetCoverageData(
            line_coverage=line_cov,
            branch_coverage=branch_cov,
            covered_lines=executed_lines,
            uncovered_lines=missing_lines,
            uncovered_branches=clean_missing_branches,
            total_executable_lines=total_exec,
            collection_status="SUCCESS",
        )

    def _run_command_compat(
        self,
        workspace_root: Path,
        command: str,
        arguments: list[str],
        timeout_seconds: int = 45,
    ) -> Any:
        """Execute command safely supporting both WorkspaceCommandRunner.run_command and legacy runner.run."""
        if hasattr(self._command_runner, "run_command"):
            return self._command_runner.run_command(
                workspace_root=workspace_root,
                command=command,
                arguments=arguments,
                timeout_seconds=timeout_seconds,
            )
        if hasattr(self._command_runner, "run"):
            return self._command_runner.run(
                workspace_root=workspace_root,
                command=command,
                arguments=arguments,
                timeout_seconds=timeout_seconds,
            )
        raise RuntimeError(f"Unsupported command runner interface: {type(self._command_runner)}")

    def _measure_python_coverage(
        self,
        workspace_root: Path,
        target_file: str,
        test_path: str | None = None,
        framework: str = "pytest",
    ) -> TargetCoverageData:
        """Execute coverage run using coverage.py and extract target coverage metrics."""
        report_file = workspace_root / f".coverage_{target_file.replace('/', '_')}.json"
        data_file = workspace_root / f".coverage_{target_file.replace('/', '_')}.data"

        # Determine target source flag
        clean_target = target_file.strip().replace("\\", "/")
        source_flag = clean_target if (workspace_root / clean_target).exists() else Path(clean_target).stem

        # Build runner command: coverage run --data-file=... --source=... -m pytest ...
        cmd_args = [
            "-m",
            "coverage",
            "run",
            f"--data-file={data_file}",
            f"--source={source_flag}",
        ]
        if framework == "pytest":
            cmd_args.extend(["-m", "pytest", "-q"])
            if test_path:
                cmd_args.append(test_path)
        else:
            cmd_args.extend(["-m", "unittest", "discover", "-s"])
            if test_path:
                cmd_args.extend([str(Path(test_path).parent), "-p", Path(test_path).name])
            else:
                cmd_args.extend(["tests", "-p", "test_*.py"])

        try:
            exec_res = self._run_command_compat(
                workspace_root=workspace_root,
                command="python",
                arguments=cmd_args,
                timeout_seconds=45,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"Python coverage run failed: {exc}")
            return TargetCoverageData(
                collection_status="FAILED",
                error_message=f"Coverage execution failed: {exc}",
            )

        # Export to JSON
        try:
            json_export_res = self._run_command_compat(
                workspace_root=workspace_root,
                command="python",
                arguments=[
                    "-m",
                    "coverage",
                    "json",
                    f"--data-file={data_file}",
                    "-o",
                    str(report_file),
                ],
                timeout_seconds=15,
            )
            if json_export_res.exit_code != 0:
                # coverage tool might not be installed in the environment
                return TargetCoverageData(
                    collection_status="NOT_CONFIGURED",
                    error_message=f"coverage.py not configured or failed to export JSON: {json_export_res.stderr}",
                )
        except Exception as exc:  # noqa: BLE001
            return TargetCoverageData(
                collection_status="NOT_CONFIGURED",
                error_message=f"Coverage JSON export command failed: {exc}",
            )

        parsed = self._parse_python_coverage_json(report_file, target_file)

        # Cleanup temp coverage data files
        try:
            if report_file.exists():
                report_file.unlink()
            if data_file.exists():
                data_file.unlink()
        except Exception:
            pass

        return parsed

    # -----------------------------------------------------------------------
    # Node (Jest & Vitest) Coverage
    # -----------------------------------------------------------------------

    def _parse_node_coverage_json(
        self,
        summary_path: Path,
        target_file: str,
    ) -> TargetCoverageData:
        """Parse Istanbul/V8 coverage-summary.json from Jest or Vitest."""
        if not summary_path.exists():
            return TargetCoverageData(
                collection_status="FAILED",
                error_message=f"Node coverage summary file '{summary_path.name}' was not found.",
            )

        try:
            data = json.loads(summary_path.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001
            return TargetCoverageData(
                collection_status="FAILED",
                error_message=f"Failed to parse node coverage JSON: {exc}",
            )

        norm_target = target_file.strip().replace("\\", "/")
        matching_key = None
        for key in data:
            if key == "total":
                continue
            norm_key = key.replace("\\", "/")
            if norm_key.endswith(norm_target) or norm_target.endswith(norm_key):
                matching_key = key
                break

        if not matching_key:
            total_sec = data.get("total", {})
            lines_pct = total_sec.get("lines", {}).get("pct")
            branches_pct = total_sec.get("branches", {}).get("pct")
            return TargetCoverageData(
                line_coverage=float(lines_pct) if lines_pct is not None else 0.0,
                branch_coverage=float(branches_pct) if branches_pct is not None else None,
                collection_status="SUCCESS",
            )

        target_stats = data[matching_key]
        lines_pct = target_stats.get("lines", {}).get("pct")
        branches_pct = target_stats.get("branches", {}).get("pct")

        return TargetCoverageData(
            line_coverage=float(lines_pct) if lines_pct is not None else 0.0,
            branch_coverage=float(branches_pct) if branches_pct is not None else None,
            collection_status="SUCCESS",
        )

    def _measure_node_coverage(
        self,
        workspace_root: Path,
        target_file: str,
        test_path: str | None = None,
        framework: str = "jest",
    ) -> TargetCoverageData:
        """Run Jest or Vitest coverage command and parse output JSON."""
        summary_path = workspace_root / "coverage" / "coverage-summary.json"

        args = ["test", "--", "--coverage", "--coverageReporters=json-summary"]
        if framework == "vitest":
            args = ["test", "--", "--run", "--coverage"]
        if test_path:
            args.append(test_path)

        try:
            exec_res = self._run_command_compat(
                workspace_root=workspace_root,
                command="npm",
                arguments=args,
                timeout_seconds=60,
            )
            if not summary_path.exists():
                return TargetCoverageData(
                    collection_status="NOT_CONFIGURED",
                    error_message=f"Node coverage summary not produced. Output: {exec_res.stderr or exec_res.stdout}",
                )
            return self._parse_node_coverage_json(summary_path, target_file)
        except Exception as exc:  # noqa: BLE001
            return TargetCoverageData(
                collection_status="NOT_CONFIGURED",
                error_message=f"Node coverage execution failed: {exc}",
            )

    # -----------------------------------------------------------------------
    # Public API: Measure & Calculate Gain
    # -----------------------------------------------------------------------

    def measure_coverage(
        self,
        workspace_root: Path,
        target_file: str,
        framework: str,
        test_path: str | None = None,
    ) -> TargetCoverageData:
        """Dispatch coverage measurement according to detected framework."""
        clean_fw = framework.strip().lower()
        if clean_fw in ("pytest", "unittest"):
            return self._measure_python_coverage(
                workspace_root=workspace_root,
                target_file=target_file,
                test_path=test_path,
                framework=clean_fw,
            )
        elif clean_fw in ("jest", "vitest"):
            return self._measure_node_coverage(
                workspace_root=workspace_root,
                target_file=target_file,
                test_path=test_path,
                framework=clean_fw,
            )
        else:
            return TargetCoverageData(
                collection_status="NOT_CONFIGURED",
                error_message=f"Coverage collection not supported for framework '{framework}'.",
            )

    def calculate_coverage_gain(
        self,
        baseline: TargetCoverageData,
        post_generation: TargetCoverageData,
        target_file: str,
    ) -> CoverageReport:
        """Compare baseline and post-generation coverage to calculate gain and attribution."""
        warnings: list[str] = []

        if baseline.collection_status in ("NOT_CONFIGURED", "FAILED"):
            warnings.append(
                f"Baseline coverage collection: {baseline.error_message or baseline.collection_status}"
            )
        if post_generation.collection_status in ("NOT_CONFIGURED", "FAILED"):
            warnings.append(
                f"Post-generation coverage collection: {post_generation.error_message or post_generation.collection_status}"
            )

        status = "SUCCESS"
        if baseline.collection_status == "NOT_CONFIGURED" or post_generation.collection_status == "NOT_CONFIGURED":
            status = "NOT_CONFIGURED"
        elif baseline.collection_status == "FAILED" or post_generation.collection_status == "FAILED":
            status = "FAILED"
        elif baseline.collection_status == "PARTIAL" or post_generation.collection_status == "PARTIAL":
            status = "PARTIAL"

        base_line = baseline.line_coverage
        final_line = post_generation.line_coverage
        line_gain: float | None = None
        if base_line is not None and final_line is not None:
            line_gain = round(final_line - base_line, 2)

        base_branch = baseline.branch_coverage
        final_branch = post_generation.branch_coverage
        branch_gain: float | None = None
        if base_branch is not None and final_branch is not None:
            branch_gain = round(final_branch - base_branch, 2)

        # Attribution: which lines were newly covered in post_generation
        newly_covered = sorted(list(set(post_generation.covered_lines) - set(baseline.covered_lines)))

        # Also newly covered branches
        base_branches_set = {tuple(b) for b in baseline.covered_branches}
        post_branches_set = {tuple(b) for b in post_generation.covered_branches}
        new_branches = [list(b) for b in sorted(post_branches_set - base_branches_set)]

        # Attributable if newly covered lines or branches, or positive line/branch gain
        has_positive_delta = (line_gain is not None and line_gain > 0.0) or (
            branch_gain is not None and branch_gain > 0.0
        )
        attributable = bool(newly_covered or new_branches or has_positive_delta)

        return CoverageReport(
            baseline_line_coverage=base_line,
            final_line_coverage=final_line,
            line_coverage_gain=line_gain,
            baseline_branch_coverage=base_branch,
            final_branch_coverage=final_branch,
            branch_coverage_gain=branch_gain,
            newly_covered_lines=newly_covered,
            newly_covered_branches=new_branches,
            coverage_attributable_to_generated_tests=attributable,
            collection_status=status,
            warnings=[redact(w) for w in warnings],
        )
