"""Three-Run Test Stability Validator for Execution-Verified Test Generation.

Owner: Antigravity Test Engineering Team
Reference: task.md §4.6 (Stage 3: Stability Validation)

Capabilities:
1. Executes generated test suites across exactly MAX_STABILITY_RUNS (default 3) consecutive runs.
2. Classifies stability deterministically:
   - 3/3 PASS -> STABLE (is_stable=True)
   - 2/3 PASS -> UNSTABLE (is_stable=False, flakiness detected)
   - <= 1/3 PASS -> FAILED (is_stable=False, persistent failure)
3. Captures run-level telemetry (exit code, duration, pass/fail counts, error snippet).
4. Strictly distinguishes stability execution retries from LLM generation rounds (task.md §4.6).
5. Does not silently retry and mark flaky tests as verified.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from app.core.secret_redaction import redact
from app.schemas.analysis import (
    StabilityClassification,
    StabilityReport,
    StabilityRunResult,
)
from app.schemas.workspace import (
    TestOutcomeStatus,
    WorkspaceTestExecutionRequest,
    WorkspaceTestExecutionResult,
)

logger = logging.getLogger(__name__)

MAX_STABILITY_RUNS: int = 3


class TestStabilityValidator:
    """Validator executing generated test suites multiple times to detect flakiness."""

    __test__ = False

    def __init__(self, max_runs: int = MAX_STABILITY_RUNS) -> None:
        self.max_runs = max(1, max_runs)

    def evaluate_runs(self, runs: list[StabilityRunResult]) -> StabilityReport:
        """Compute the final stability classification from a set of executed runs."""
        total = len(runs)
        passed_runs = sum(1 for r in runs if r.passed)

        if total >= 3 and passed_runs == total:
            classification: StabilityClassification = "STABLE"
            is_stable = True
        elif passed_runs == 0 or (total >= 3 and passed_runs <= 1):
            classification = "FAILED"
            is_stable = False
        elif passed_runs < total:
            classification = "UNSTABLE"
            is_stable = False
        else:
            # If total < 3 but all passed
            classification = "STABLE" if passed_runs == total else "FAILED"
            is_stable = passed_runs == total

        return StabilityReport(
            total_runs=total,
            passed_runs=passed_runs,
            classification=classification,
            is_stable=is_stable,
            runs=runs,
        )

    def run_stability_validation(
        self,
        *,
        runner_fn: Callable[[int], tuple[bool, int, float, int, int, str | None]],
    ) -> StabilityReport:
        """Execute the suite `self.max_runs` times using a custom execution callable.

        The `runner_fn(run_index)` must return:
            (passed, exit_code, duration_seconds, passed_count, failed_count, error_message)
        """
        results: list[StabilityRunResult] = []

        for run_idx in range(1, self.max_runs + 1):
            try:
                passed, code, duration, p_count, f_count, err = runner_fn(run_idx)
                results.append(
                    StabilityRunResult(
                        run_number=run_idx,
                        passed=passed,
                        exit_code=code,
                        duration_seconds=round(max(0.0, duration), 3),
                        passed_count=p_count,
                        failed_count=f_count,
                        error_message=redact(err) if err else None,
                    )
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning(f"Stability run {run_idx} crashed with unexpected exception: {exc}")
                results.append(
                    StabilityRunResult(
                        run_number=run_idx,
                        passed=False,
                        exit_code=1,
                        duration_seconds=0.0,
                        passed_count=0,
                        failed_count=1,
                        error_message=redact(str(exc)),
                    )
                )

        return self.evaluate_runs(results)

    def validate_with_sandbox_test_runner(
        self,
        *,
        test_runner: Any,
        workspace_root: Path,
        test_path: str,
        framework: str,
        task_id: str,
        timeout_seconds: int = 60,
    ) -> StabilityReport:
        """Execute stability runs via an instance of WorkspaceTestRunner in the sandbox."""
        results: list[StabilityRunResult] = []

        for run_idx in range(1, self.max_runs + 1):
            start = time.perf_counter()
            try:
                req = WorkspaceTestExecutionRequest(
                    task_id=f"{task_id}-stab-{run_idx}",
                    test_path=test_path,
                    framework=framework,
                    timeout_seconds=timeout_seconds,
                )
                exec_res: WorkspaceTestExecutionResult = test_runner.run_tests(
                    workspace_root=workspace_root,
                    request=req,
                )
                duration = time.perf_counter() - start
                is_pass = exec_res.status == TestOutcomeStatus.PASSED and exec_res.failed_count == 0
                err_msg = exec_res.error or (
                    "; ".join(exec_res.failure_details[:2]) if exec_res.failure_details else None
                )

                results.append(
                    StabilityRunResult(
                        run_number=run_idx,
                        passed=is_pass,
                        exit_code=exec_res.exit_code,
                        duration_seconds=round(duration, 3),
                        passed_count=exec_res.passed_count,
                        failed_count=exec_res.failed_count,
                        error_message=redact(err_msg) if err_msg else None,
                    )
                )
            except Exception as exc:  # noqa: BLE001
                duration = time.perf_counter() - start
                results.append(
                    StabilityRunResult(
                        run_number=run_idx,
                        passed=False,
                        exit_code=1,
                        duration_seconds=round(duration, 3),
                        passed_count=0,
                        failed_count=1,
                        error_message=redact(str(exc)),
                    )
                )

        return self.evaluate_runs(results)
