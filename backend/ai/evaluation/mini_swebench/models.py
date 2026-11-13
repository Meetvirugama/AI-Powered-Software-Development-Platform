"""Data models for Mini SWE-bench Agent Evaluation Framework (Phase 4 & 5, task3.md §9)."""

from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, Field


class BenchmarkTaskMetadata(BaseModel):
    """Metadata describing a single Mini SWE-bench coding task."""

    task_id: str
    repository: str
    base_commit: str = "main@pinned"
    issue_title: str
    issue_description: str
    category: Literal[
        "bug_fix",
        "api_behavior",
        "validation",
        "error_handling",
        "data_processing",
        "performance",
        "refactoring",
    ] = "bug_fix"
    difficulty: Literal["easy", "medium", "hard"] = "easy"
    language: str = "python"
    reproduction_test: str
    regression_test: str
    expected_files: List[str] = Field(default_factory=list)
    license: str = "MIT"


class TaskExecutionResult(BaseModel):
    """Result of running the autonomous agent against a single benchmark task."""

    task_id: str
    reproduction_test_passed: bool = False
    regression_test_passed: bool = False
    solved: bool = False
    execution_time_seconds: float = 0.0
    tokens_used: int = 0
    tool_calls_count: int = 0
    modified_files: List[str] = Field(default_factory=list)
    patch_diff: Optional[str] = None
    error_message: Optional[str] = None


class MiniSWEBenchReport(BaseModel):
    """Aggregated benchmark report across all evaluated tasks."""

    benchmark_version: str = "1.0.0"
    total_tasks: int
    solved_tasks: int
    failed_tasks: int
    pass_at_1: float
    reproduction_pass_rate: float
    regression_pass_rate: float
    avg_execution_time_seconds: float
    results: List[TaskExecutionResult]
    all_quality_gates_passed: bool
    summary: str


__all__ = [
    "BenchmarkTaskMetadata",
    "TaskExecutionResult",
    "MiniSWEBenchReport",
]
