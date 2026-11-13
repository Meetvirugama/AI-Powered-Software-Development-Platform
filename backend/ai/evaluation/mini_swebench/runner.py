"""Runner and Aggregator for Mini SWE-bench (Phase 4 & 5, task3.md §9.8 & §9.9)."""

from __future__ import annotations

import logging
import time
from typing import Callable, List, Optional
from pathlib import Path

from ai.evaluation.mini_swebench.models import (
    MiniSWEBenchReport,
    TaskExecutionResult,
)
from ai.evaluation.mini_swebench.task_loader import BenchmarkTask, MiniSWEBenchTaskLoader
from ai.evaluation.mini_swebench.test_executor import BenchmarkTestExecutor
from ai.evaluation.quality_gate import QualityGate

logger = logging.getLogger(__name__)


class MiniSWEBenchRunner:
    """Orchestrates running tasks across the Mini SWE-bench dataset."""

    def __init__(
        self,
        loader: Optional[MiniSWEBenchTaskLoader] = None,
        test_executor: Optional[BenchmarkTestExecutor] = None,
        quality_gate: Optional[QualityGate] = None,
    ) -> None:
        self.loader = loader or MiniSWEBenchTaskLoader()
        self.executor = test_executor or BenchmarkTestExecutor()
        self.quality_gate = quality_gate or QualityGate()

    def run_benchmark(
        self,
        task_solver: Optional[Callable[[BenchmarkTask], TaskExecutionResult]] = None,
        target_task_ids: Optional[List[str]] = None,
    ) -> MiniSWEBenchReport:
        """Run benchmark evaluation over selected tasks."""
        all_tasks = self.loader.tasks
        if target_task_ids:
            tasks = [t for t in all_tasks if t.task_id in target_task_ids]
        else:
            tasks = all_tasks

        results: List[TaskExecutionResult] = []
        total_time = 0.0

        for task in tasks:
            start = time.perf_counter()
            if task_solver is not None:
                res = task_solver(task)
            else:
                # Default baseline simulation: checks if tests run directly in task_dir
                repro_ok, reg_ok, log = self.executor.evaluate_task_tests(task, task.task_dir)
                res = TaskExecutionResult(
                    task_id=task.task_id,
                    reproduction_test_passed=repro_ok,
                    regression_test_passed=reg_ok,
                    solved=repro_ok and reg_ok,
                    execution_time_seconds=round(time.perf_counter() - start, 3),
                    error_message=None if (repro_ok and reg_ok) else log[:200],
                )
            duration = time.perf_counter() - start
            res.execution_time_seconds = round(duration, 3)
            total_time += duration
            results.append(res)

        total_tasks = len(results)
        solved_count = sum(1 for r in results if r.solved)
        repro_count = sum(1 for r in results if r.reproduction_test_passed)
        reg_count = sum(1 for r in results if r.regression_test_passed)

        pass_at_1 = (solved_count / total_tasks) if total_tasks > 0 else 0.0
        repro_rate = (repro_count / total_tasks) if total_tasks > 0 else 0.0
        reg_rate = (reg_count / total_tasks) if total_tasks > 0 else 0.0
        avg_time = (total_time / total_tasks) if total_tasks > 0 else 0.0

        # Evaluate against quality gate
        gate_eval = self.quality_gate.evaluate(
            metric_name="swebench_pass_at_1",
            actual=pass_at_1,
            threshold=0.50,
            comparison=">=",
            mandatory=True,
        )

        all_passed = gate_eval.passed and total_tasks > 0
        summary = (
            f"Mini SWE-bench Pass@1={pass_at_1:.1%} ({solved_count}/{total_tasks} solved). "
            f"Reproduction={repro_rate:.1%}, Regression={reg_rate:.1%}, Avg Time={avg_time:.2f}s. "
            f"Gate status: {'PASS' if all_passed else 'FAIL'}."
        )

        return MiniSWEBenchReport(
            benchmark_version="1.0.0",
            total_tasks=total_tasks,
            solved_tasks=solved_count,
            failed_tasks=total_tasks - solved_count,
            pass_at_1=round(pass_at_1, 4),
            reproduction_pass_rate=round(repro_rate, 4),
            regression_pass_rate=round(reg_rate, 4),
            avg_execution_time_seconds=round(avg_time, 2),
            results=results,
            all_quality_gates_passed=all_passed,
            summary=summary,
        )


__all__ = ["MiniSWEBenchRunner"]
