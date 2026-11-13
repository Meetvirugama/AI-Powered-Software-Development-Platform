"""
Tool Executor with Sandbox Bounds, Timeouts, and Redaction (task.md §4.1, §9.2).

Guarantees:
- Enforces strict execution timeouts (default 5.0s per tool call).
- Truncates oversized results to a maximum of 8 KB.
- Applies secret redaction on tool results before return to the LLM.
- Normalizes all runtime exceptions into safe structured error results.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time

from ai.agent.errors import AgentToolValidationError
from ai.agent.policy import MAX_TOOL_RESULT_BYTES, sanitize_and_redact, truncate_tool_output
from ai.agent.schemas import AgentToolContext, AgentToolResult
from ai.agent.tool_registry import ToolRegistry
from ai.llm.schemas import LLMToolCall

logger = logging.getLogger(__name__)


class ToolExecutor:
    """
    Executes model-requested tools with timeout, isolation, and sanitization boundaries.
    """

    def __init__(
        self,
        registry: ToolRegistry,
        default_timeout_seconds: float = 5.0,
        max_result_bytes: int = MAX_TOOL_RESULT_BYTES,
    ) -> None:
        self._registry = registry
        self._default_timeout_seconds = default_timeout_seconds
        self._max_result_bytes = max_result_bytes

    async def execute(
        self,
        tool_call: LLMToolCall,
        context: AgentToolContext,
        timeout_seconds: float | None = None,
    ) -> AgentToolResult:
        """Execute a tool call with safety bounds."""
        effective_timeout = timeout_seconds or self._default_timeout_seconds
        start_time = time.monotonic()
        tool_name = tool_call.name
        call_id = tool_call.id or "call_unknown"

        # Check tool availability
        if not self._registry.has_tool(tool_name):
            logger.warning("agent_tool_unknown", extra={"tool_name": tool_name, "call_id": call_id})
            return AgentToolResult(
                call_id=call_id,
                tool_name=tool_name,
                is_error=True,
                error_message=f"Tool '{tool_name}' is not recognized or permitted.",
                execution_time_ms=(time.monotonic() - start_time) * 1000.0,
            )

        handler = self._registry.get_handler(tool_name)

        try:
            # Execute with strict timeout
            result: AgentToolResult = await asyncio.wait_for(
                handler(call_id, tool_call.arguments, context),
                timeout=effective_timeout,
            )
            result.execution_time_ms = round((time.monotonic() - start_time) * 1000.0, 2)

        except TimeoutError:
            latency_ms = round((time.monotonic() - start_time) * 1000.0, 2)
            logger.warning(
                "agent_tool_timeout",
                extra={"tool_name": tool_name, "call_id": call_id, "timeout": effective_timeout},
            )
            return AgentToolResult(
                call_id=call_id,
                tool_name=tool_name,
                is_error=True,
                error_message=f"Tool execution exceeded {effective_timeout}s deadline.",
                execution_time_ms=latency_ms,
            )

        except AgentToolValidationError as exc:
            latency_ms = round((time.monotonic() - start_time) * 1000.0, 2)
            safe_err = sanitize_and_redact(str(exc))
            logger.info(
                "agent_tool_validation_failed",
                extra={"tool_name": tool_name, "call_id": call_id, "error": safe_err},
            )
            return AgentToolResult(
                call_id=call_id,
                tool_name=tool_name,
                is_error=True,
                error_message=safe_err,
                execution_time_ms=latency_ms,
            )

        except Exception as exc:  # noqa: BLE001
            latency_ms = round((time.monotonic() - start_time) * 1000.0, 2)
            safe_err = sanitize_and_redact(f"Tool error: {exc}")
            logger.error(
                "agent_tool_unexpected_failure",
                extra={"tool_name": tool_name, "call_id": call_id, "error": safe_err},
            )
            return AgentToolResult(
                call_id=call_id,
                tool_name=tool_name,
                is_error=True,
                error_message=safe_err,
                execution_time_ms=latency_ms,
            )

        # Sanitize result payload and evidence
        return self._sanitize_result(result)

    def _sanitize_result(self, result: AgentToolResult) -> AgentToolResult:
        """Redact secrets and clamp output size."""
        if result.error_message:
            result.error_message = sanitize_and_redact(result.error_message)
            err_trunc, _ = truncate_tool_output(result.error_message, self._max_result_bytes)
            result.error_message = err_trunc

        # 1. Redact secrets from result representation
        if isinstance(result.result, str):
            result.result = sanitize_and_redact(result.result)
            truncated_str, is_trunc = truncate_tool_output(result.result, self._max_result_bytes)
            result.result = truncated_str
            result.is_truncated = is_trunc
        elif isinstance(result.result, dict):
            try:
                dumped = json.dumps(result.result, default=str)
                redacted_json = sanitize_and_redact(dumped)
                truncated_json, is_trunc = truncate_tool_output(redacted_json, self._max_result_bytes)
                if is_trunc:
                    result.result = {"raw_output": truncated_json}
                    result.is_truncated = True
                else:
                    result.result = json.loads(truncated_json)
            except (json.JSONDecodeError, TypeError, ValueError) as exc:
                logger.debug("tool_result_sanitization_parse_error", extra={"error": str(exc)})

        # 2. Redact and clamp evidence contents
        for ev in result.evidence:
            ev.content = sanitize_and_redact(ev.content)
            ev.redaction_applied = True
            ev_truncated, ev_is_trunc = truncate_tool_output(ev.content, self._max_result_bytes)
            ev.content = ev_truncated
            ev.is_truncated = ev_is_trunc

        return result
