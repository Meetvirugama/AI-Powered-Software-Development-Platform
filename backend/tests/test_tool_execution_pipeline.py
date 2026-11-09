"""Integration tests for the unified tool execution pipeline.

Part of F21 — Tool router and tool policy bridge (Issue #201).
Tests:
- Common execution pipeline: request -> rate_limit -> authorize -> execute -> validate output -> redact -> bound
- Elimination of TypeError-based execution signature guessing (no double-execution)
- Rate limiting enforcement (rate-limited requests never reach handler)
- Execution timeouts (timeout_s threshold, timeout status, safe diagnostic)
- Output schema enforcement
- Secret redaction and output bounding
"""

import time
import pytest

from agent.tools.models import (
    ToolAnnotations,
    ToolDefinition,
    ToolRateLimit,
    ToolRequest,
    ToolResult,
)
from agent.tools.rate_limiter import ToolRateLimiter
from agent.tools.router import ToolRouter


class AlwaysAllowPolicyEngine:
    def check(self, tool, agent_state, context):
        return "ALLOW"


def make_test_router(max_output_chars: int = 1000) -> ToolRouter:
    engine = AlwaysAllowPolicyEngine()
    context_factory = lambda state, req: {"task_id": "test_task", "tool": req.tool_name}
    return ToolRouter(
        policy_engine=engine,
        policy_context_factory=context_factory,
        max_output_chars=max_output_chars,
        rate_limiter=ToolRateLimiter(fallback_to_memory=True),
    )


def test_signature_inspection_prevents_double_execution():
    """Verify that an internal TypeError inside a handler does NOT cause a second execution attempt."""
    router = make_test_router()
    call_count = 0

    def buggy_handler(item_name: str) -> dict:
        nonlocal call_count
        call_count += 1
        # Internal TypeError (e.g. bug in handler implementation)
        raise TypeError("Simulated internal TypeError in handler logic")

    tool = ToolDefinition(
        name="buggy_tool",
        description="Tool with internal bug",
        input_schema={
            "type": "object",
            "properties": {"item_name": {"type": "string"}},
            "required": ["item_name"],
        },
    )
    router.register(tool, buggy_handler)

    res = router.route(
        ToolRequest("buggy_tool", {"item_name": "widget"}),
        agent_state={"task_id": "t1"},
    )

    assert res.success is False
    assert res.error == "Tool execution failed"
    assert res.error_category == "EXECUTION_ERROR"
    # Exactly one invocation attempt — zero retry attempts!
    assert call_count == 1


def test_rate_limiting_blocks_execution_before_handler():
    """Verify that requests exceeding the sliding-window limit are blocked before reaching handler."""
    router = make_test_router()
    handler_invocations = 0

    def tracked_handler(query: str) -> str:
        nonlocal handler_invocations
        handler_invocations += 1
        return f"Result for {query}"

    tool = ToolDefinition(
        name="rate_limited_query",
        description="Query tool with strict rate limit",
        input_schema={"type": "object", "properties": {"query": {"type": "string"}}},
        rate_limit=ToolRateLimit(requests=2, window_seconds=10, scope="task"),
    )
    router.register(tool, tracked_handler)

    # Call 1: Allowed
    res1 = router.route(ToolRequest("rate_limited_query", {"query": "one"}), agent_state={"task_id": "task_A"})
    assert res1.success is True
    assert handler_invocations == 1

    # Call 2: Allowed
    res2 = router.route(ToolRequest("rate_limited_query", {"query": "two"}), agent_state={"task_id": "task_A"})
    assert res2.success is True
    assert handler_invocations == 2

    # Call 3: Rate limited!
    res3 = router.route(ToolRequest("rate_limited_query", {"query": "three"}), agent_state={"task_id": "task_A"})
    assert res3.success is False
    assert res3.rate_limited is True
    assert res3.error_category == "RATE_LIMIT_ERROR"
    assert "Rate limit exceeded" in (res3.error or "")
    # Handler must NOT have been called for request 3
    assert handler_invocations == 2

    # Different task ID should NOT be limited
    res_b = router.route(ToolRequest("rate_limited_query", {"query": "task_b_req"}), agent_state={"task_id": "task_B"})
    assert res_b.success is True
    assert handler_invocations == 3


def test_execution_timeout_enforcement():
    """Verify that a tool exceeding timeout_s is stopped and classified as TIMEOUT_ERROR."""
    router = make_test_router()

    def slow_tool(duration: float) -> str:
        time.sleep(duration)
        return "completed"

    tool = ToolDefinition(
        name="slow_runner",
        description="Simulates slow operation",
        input_schema={"type": "object", "properties": {"duration": {"type": "number"}}},
        timeout_s=0.2,  # 200ms ceiling
    )
    router.register(tool, slow_tool)

    res = router.route(
        ToolRequest("slow_runner", {"duration": 1.0}),
        agent_state={"task_id": "task_timeout"},
    )

    assert res.success is False
    assert res.timed_out is True
    assert res.error_category == "TIMEOUT_ERROR"
    assert "timed out after 0.2s" in (res.error or "")


def test_output_schema_validation_failure_blocks_result():
    """Verify that output violating the configured output schema is rejected."""
    router = make_test_router()

    def bad_output_generator() -> dict:
        return {"unexpected": "missing_required_keys"}

    tool = ToolDefinition(
        name="strict_output_tool",
        description="Tool with strict output schema contract",
        input_schema={"type": "object"},
        output_schema={
            "type": "object",
            "properties": {
                "result_id": {"type": "integer"},
                "status": {"type": "string"},
            },
            "required": ["result_id", "status"],
        },
    )
    router.register(tool, bad_output_generator)

    res = router.route(
        ToolRequest("strict_output_tool", {}),
        agent_state={"task_id": "task_out"},
    )

    assert res.success is False
    assert res.error_category == "OUTPUT_SCHEMA_ERROR"
    assert "Output validation failed" in (res.error or "")


def test_secret_redaction_and_bounding_in_execution_pipeline():
    """Verify that credentials and tokens are redacted and large outputs bounded."""
    router = make_test_router(max_output_chars=50)

    def credential_leaker() -> dict:
        return {
            "api_key": "sk-proj-supersecretkey1234567890abcdef",
            "info": "This is a very long text string meant to exceed the output bounding threshold of 50 characters",
        }

    tool = ToolDefinition(
        name="credential_leaker",
        description="Tool outputting secrets and long text",
        input_schema={"type": "object"},
    )
    router.register(tool, credential_leaker)

    res = router.route(
        ToolRequest("credential_leaker", {}),
        agent_state={"task_id": "task_secret"},
    )

    assert res.success is True
    out_str = str(res.output)
    # Secret must be redacted
    assert "sk-proj-supersecretkey1234567890abcdef" not in out_str
    assert "[REDACTED]" in out_str
    # Output must be truncated
    assert "OUTPUT TRUNCATED" in out_str
