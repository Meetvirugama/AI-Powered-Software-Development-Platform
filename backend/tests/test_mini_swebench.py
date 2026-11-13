"""Unit tests for Mini SWE-bench Evaluation Harness & Dataset (Phase 5, task3.md §11.4).

Verifies:
1. Manifest and dataset discovery: Loads 25 tasks.
2. Metadata completeness: Unique IDs, categories, difficulty, pinned commits, MIT licenses.
3. Test executor functionality: Runs reproduction and regression tests.
4. Pass@1 calculation and benchmark aggregation.
5. QualityGate integration: Rejection on below-threshold Pass@1.
"""

from __future__ import annotations

import pytest

from ai.evaluation.mini_swebench.models import (
    BenchmarkTaskMetadata,
    MiniSWEBenchReport,
    TaskExecutionResult,
)
from ai.evaluation.mini_swebench.runner import MiniSWEBenchRunner
from ai.evaluation.mini_swebench.task_loader import MiniSWEBenchTaskLoader
from ai.evaluation.mini_swebench.test_executor import BenchmarkTestExecutor
from ai.evaluation.quality_gate import QualityGate


@pytest.fixture
def loader() -> MiniSWEBenchTaskLoader:
    return MiniSWEBenchTaskLoader()


@pytest.fixture
def executor() -> BenchmarkTestExecutor:
    return BenchmarkTestExecutor(timeout_seconds=10)


@pytest.fixture
def runner(loader: MiniSWEBenchTaskLoader, executor: BenchmarkTestExecutor) -> MiniSWEBenchRunner:
    return MiniSWEBenchRunner(loader=loader, test_executor=executor)


def test_mini_swebench_task_loader_discovers_tasks(loader: MiniSWEBenchTaskLoader) -> None:
    """Verify task loader loads all 25 benchmark tasks."""
    tasks = loader.tasks
    assert len(tasks) == 25, f"Expected 25 tasks, found {len(tasks)}"

    task_ids = [t.task_id for t in tasks]
    assert len(task_ids) == len(set(task_ids)), "Task IDs must be globally unique"
    assert "TASK-001" in task_ids
    assert "TASK-025" in task_ids


def test_task_metadata_completeness(loader: MiniSWEBenchTaskLoader) -> None:
    """Verify metadata requirements across all tasks."""
    for task in loader.tasks:
        meta = task.metadata
        assert meta.task_id.startswith("TASK-")
        assert len(meta.issue_title) > 5
        assert len(meta.issue_description) > 10
        assert meta.base_commit == "main@pinned"
        assert meta.license == "MIT"
        assert len(meta.expected_files) > 0
        assert meta.category in [
            "bug_fix",
            "api_behavior",
            "validation",
            "error_handling",
            "data_processing",
            "performance",
            "refactoring",
        ]


def test_test_executor_runs_task_tests(loader: MiniSWEBenchTaskLoader, executor: BenchmarkTestExecutor) -> None:
    """Verify test executor executes tests on a task workspace."""
    task = loader.get_task("TASK-001")
    assert task is not None

    repro_ok, reg_ok, log = executor.evaluate_task_tests(task, task.task_dir)
    assert repro_ok is True
    assert reg_ok is True
    assert "PASS" in log


def test_runner_evaluates_pass_at_1(runner: MiniSWEBenchRunner) -> None:
    """Verify MiniSWEBenchRunner runs tasks and computes Pass@1 metrics."""
    # Run on a sample of 3 tasks for fast unit test execution
    report = runner.run_benchmark(target_task_ids=["TASK-001", "TASK-002", "TASK-003"])

    assert report.total_tasks == 3
    assert report.solved_tasks == 3
    assert report.pass_at_1 == 1.0
    assert report.reproduction_pass_rate == 1.0
    assert report.regression_pass_rate == 1.0
    assert report.all_quality_gates_passed is True
    assert "Pass@1=100.0%" in report.summary


def test_runner_fails_gate_when_pass_at_1_below_threshold(runner: MiniSWEBenchRunner) -> None:
    """Verify runner marks gate as failed when simulated solver fails tasks."""
    def failing_solver(task):
        return TaskExecutionResult(
            task_id=task.task_id,
            reproduction_test_passed=False,
            regression_test_passed=True,
            solved=False,
            error_message="Reproduction test failed",
        )

    report = runner.run_benchmark(
        task_solver=failing_solver,
        target_task_ids=["TASK-001", "TASK-002"],
    )

    assert report.total_tasks == 2
    assert report.solved_tasks == 0
    assert report.pass_at_1 == 0.0
    assert report.all_quality_gates_passed is False
    assert "FAIL" in report.summary
