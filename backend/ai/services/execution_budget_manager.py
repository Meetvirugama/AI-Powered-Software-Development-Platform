"""Execution Budget Manager.

Implements Phase 9 & 10: Budget Enforcement & LLM Cost Controls.
References: task.md §10, test plan OPS-06, OPS-07, OPS-08, EXE-15, EXE-17.
Enforces:
- Step iteration caps (max steps).
- Per-step retry limits (prevents infinite repair loops).
- Modified file count limit (blast radius bounds).
- Execution wall-clock time limit.
- LLM token usage budget.
- Context omission disclosure.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


class BudgetExceededError(RuntimeError):
    """Raised when an execution or resource budget is exhausted."""


@dataclass
class ExecutionBudget:
    """Configured and consumed resource budget for a task execution."""

    max_steps: int = 50
    max_time_seconds: float = 600.0
    max_modified_files: int = 25
    max_retries_per_step: int = 3
    token_budget: int = 100_000
    step_timeout_seconds: float = 120.0

    used_steps: int = 0
    elapsed_time: float = 0.0
    used_tokens: int = 0
    omitted_context_count: int = 0
    modified_files: set[str] = field(default_factory=set)
    step_retries: dict[str, int] = field(default_factory=dict)


class ExecutionBudgetManager:
    """Enforces execution limits to prevent runaways and control costs."""

    def __init__(self, budget: ExecutionBudget | None = None) -> None:
        self.budget = budget or ExecutionBudget()

    def check_can_execute_step(self, step_id: str) -> None:
        """Verify whether executing another step or retrying step_id is allowed."""
        if self.budget.used_steps >= self.budget.max_steps:
            msg = f"Step limit reached: {self.budget.used_steps}/{self.budget.max_steps} steps."
            logger.warning(msg)
            raise BudgetExceededError(msg)

        retries = self.budget.step_retries.get(step_id, 0)
        if retries >= self.budget.max_retries_per_step:
            msg = f"Step '{step_id}' exceeded max retries ({retries}/{self.budget.max_retries_per_step})."
            logger.warning(msg)
            raise BudgetExceededError(msg)

    def record_step_attempt(self, step_id: str) -> None:
        """Register a step execution attempt and increment counters."""
        self.check_can_execute_step(step_id)
        self.budget.used_steps += 1
        self.budget.step_retries[step_id] = self.budget.step_retries.get(step_id, 0) + 1

    def record_file_modification(self, file_path: str) -> None:
        """Track modified file and enforce max_modified_files boundary."""
        if file_path not in self.budget.modified_files:
            if len(self.budget.modified_files) >= self.budget.max_modified_files:
                msg = (
                    f"Modified file limit reached: {len(self.budget.modified_files)}/"
                    f"{self.budget.max_modified_files} files (attempted '{file_path}')."
                )
                logger.warning(msg)
                raise BudgetExceededError(msg)
            self.budget.modified_files.add(file_path)

    def record_token_usage(self, tokens: int) -> None:
        """Register LLM tokens consumed and enforce token budget."""
        self.budget.used_tokens += max(0, tokens)
        if self.budget.used_tokens > self.budget.token_budget:
            msg = (
                f"Token budget exceeded: {self.budget.used_tokens}/"
                f"{self.budget.token_budget} tokens."
            )
            logger.warning(msg)
            raise BudgetExceededError(msg)

    def record_elapsed_time(self, seconds: float) -> None:
        """Track elapsed execution time and enforce max wall-clock duration."""
        self.budget.elapsed_time += max(0.0, seconds)
        if self.budget.elapsed_time > self.budget.max_time_seconds:
            msg = (
                f"Time budget exceeded: {self.budget.elapsed_time:.1f}/"
                f"{self.budget.max_time_seconds:.1f}s."
            )
            logger.warning(msg)
            raise BudgetExceededError(msg)

    def record_omitted_context(self, count: int = 1) -> None:
        """Disclose omitted context items due to token or size limits."""
        self.budget.omitted_context_count += max(0, count)

    def is_budget_exhausted(self) -> tuple[bool, str]:
        """Check if any budget dimension has been exceeded."""
        if self.budget.used_steps >= self.budget.max_steps:
            return True, f"Max steps exceeded ({self.budget.used_steps}/{self.budget.max_steps})"
        if self.budget.elapsed_time > self.budget.max_time_seconds:
            return True, f"Time limit exceeded ({self.budget.elapsed_time:.1f}s/{self.budget.max_time_seconds:.1f}s)"
        if self.budget.used_tokens > self.budget.token_budget:
            return True, f"Token budget exceeded ({self.budget.used_tokens}/{self.budget.token_budget})"
        if len(self.budget.modified_files) > self.budget.max_modified_files:
            return True, f"File modification limit exceeded ({len(self.budget.modified_files)}/{self.budget.max_modified_files})"
        return False, ""

    def get_remaining_budget(self) -> dict[str, Any]:
        """Return snapshot of remaining execution allowances."""
        return {
            "remaining_steps": max(0, self.budget.max_steps - self.budget.used_steps),
            "remaining_time_seconds": max(0.0, self.budget.max_time_seconds - self.budget.elapsed_time),
            "remaining_tokens": max(0, self.budget.token_budget - self.budget.used_tokens),
            "remaining_file_slots": max(0, self.budget.max_modified_files - len(self.budget.modified_files)),
            "omitted_context_count": self.budget.omitted_context_count,
        }

