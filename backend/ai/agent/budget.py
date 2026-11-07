"""
Agent Execution and Token Budget Manager (task.md §8, §13).

Centrally enforces:
- Maximum agent investigation rounds (default 3).
- Maximum tool calls per request (default 6).
- Maximum model calls per request (default 4).
- Maximum parallel tool calls per turn (default 2).
- Maximum accumulated input tokens (default 12,000).
- Maximum accumulated output tokens (default 2,000).
- Maximum overall request duration (default 35.0s).
- Repeated identical tool call detection (1 retry, then stop).
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any

logger = logging.getLogger(__name__)


class AgentBudget:
    """
    Central request-level budget tracker for agentic chat.
    """

    def __init__(
        self,
        max_rounds: int = 3,
        max_tool_calls: int = 6,
        max_model_calls: int = 4,
        max_parallel_tool_calls: int = 2,
        max_input_tokens: int = 12_000,
        max_output_tokens: int = 2_000,
        max_request_seconds: float = 35.0,
    ) -> None:
        self.max_rounds = max_rounds
        self.max_tool_calls = max_tool_calls
        self.max_model_calls = max_model_calls
        self.max_parallel_tool_calls = max_parallel_tool_calls
        self.max_input_tokens = max_input_tokens
        self.max_output_tokens = max_output_tokens
        self.max_request_seconds = max_request_seconds

        # Active counters
        self.current_round: int = 0
        self.tool_call_count: int = 0
        self.model_call_count: int = 0
        self.accumulated_input_tokens: int = 0
        self.accumulated_output_tokens: int = 0
        self.started_at: float = time.monotonic()

        # Tool signature tracking: signature -> count
        self._tool_call_signatures: dict[str, int] = {}

    def can_continue(self) -> bool:
        """Evaluate whether another agent round / model call is permitted."""
        if self.current_round >= self.max_rounds:
            logger.info("agent_budget_stopped_max_rounds", extra={"rounds": self.current_round})
            return False

        if self.tool_call_count >= self.max_tool_calls:
            logger.info("agent_budget_stopped_max_tool_calls", extra={"tool_calls": self.tool_call_count})
            return False

        if self.model_call_count >= self.max_model_calls:
            logger.info("agent_budget_stopped_max_model_calls", extra={"model_calls": self.model_call_count})
            return False

        if self.accumulated_input_tokens >= self.max_input_tokens:
            logger.info("agent_budget_stopped_input_tokens", extra={"tokens": self.accumulated_input_tokens})
            return False

        if self.accumulated_output_tokens >= self.max_output_tokens:
            logger.info("agent_budget_stopped_output_tokens", extra={"tokens": self.accumulated_output_tokens})
            return False

        if self.elapsed_seconds() >= self.max_request_seconds:
            logger.info("agent_budget_stopped_timeout", extra={"elapsed": self.elapsed_seconds()})
            return False

        return True

    def start_round(self) -> None:
        """Increment active round counter."""
        self.current_round += 1

    def record_model_call(self, input_tokens: int, output_tokens: int) -> None:
        """Record model inference invocation and token consumption."""
        self.model_call_count += 1
        self.accumulated_input_tokens += max(0, input_tokens)
        self.accumulated_output_tokens += max(0, output_tokens)

    def record_tool_call(self, tool_name: str, arguments: dict[str, Any]) -> bool:
        """
        Record tool invocation and check for duplicate execution.

        Returns:
            True if call was recorded and allowed; False if call is an identical repeated retry.
        """
        self.tool_call_count += 1
        sig = self._signature(tool_name, arguments)
        count = self._tool_call_signatures.get(sig, 0) + 1
        self._tool_call_signatures[sig] = count

        if count > 2:
            # 1 initial call + 1 retry = 2. More than 2 is rejected.
            logger.warning("agent_budget_repeated_call_rejected", extra={"signature": sig, "count": count})
            return False

        return True

    def is_repeated_call(self, tool_name: str, arguments: dict[str, Any]) -> bool:
        """Check if an identical tool call signature has already occurred."""
        sig = self._signature(tool_name, arguments)
        return self._tool_call_signatures.get(sig, 0) >= 2

    def elapsed_seconds(self) -> float:
        """Seconds elapsed since budget initialization."""
        return time.monotonic() - self.started_at

    def remaining_seconds(self) -> float:
        """Seconds remaining within max_request_seconds budget."""
        return max(0.0, self.max_request_seconds - self.elapsed_seconds())

    def summary(self) -> dict[str, Any]:
        """Summary metrics of consumed budget."""
        return {
            "rounds": self.current_round,
            "tool_calls": self.tool_call_count,
            "model_calls": self.model_call_count,
            "input_tokens": self.accumulated_input_tokens,
            "output_tokens": self.accumulated_output_tokens,
            "elapsed_seconds": round(self.elapsed_seconds(), 2),
        }

    @staticmethod
    def _signature(tool_name: str, arguments: dict[str, Any]) -> str:
        """Compute canonical string signature for tool call deduplication."""
        try:
            sorted_args = json.dumps(arguments, sort_keys=True, default=str)
        except (TypeError, ValueError):
            sorted_args = str(sorted(arguments.items()))
        return f"{tool_name}:{sorted_args}"
