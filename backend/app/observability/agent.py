"""
Autonomous Agent Execution and Tool Invocation Tracing.

Provides context managers and decorators for tracing agent execution loops,
tool routing, and multi-turn workflow stages.
"""

from __future__ import annotations

import contextlib
import logging
import time
from typing import Any, Generator

from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode

from app.core.logging import agent_execution_id_context, analysis_run_id_context
from app.observability.langfuse_adapter import get_langfuse_adapter
from app.observability.metrics import get_observability_metrics

logger = logging.getLogger(__name__)


@contextlib.contextmanager
def trace_agent_execution(
    execution_id: str,
    *,
    task_id: str | None = None,
    analysis_run_id: str | None = None,
    agent_version: str = "1.0.0",
) -> Generator[trace.Span, None, None]:
    """
    Context manager creating a root or parent span for autonomous agent execution.
    """
    tracer = trace.get_tracer("app.agent")
    token = agent_execution_id_context.set(execution_id)
    run_token = None
    if analysis_run_id:
        run_token = analysis_run_id_context.set(analysis_run_id)

    start_time = time.perf_counter()
    status = "completed"

    with tracer.start_as_current_span(
        "agent.execution",
        attributes={
            "agent.execution.id": execution_id,
            "agent.version": agent_version,
            "task.id": task_id or "",
            "analysis.run.id": analysis_run_id or "",
        },
    ) as span:
        try:
            yield span
            span.set_attribute("agent.status", "completed")
            span.set_status(Status(StatusCode.OK))
        except Exception as exc:
            status = "failed"
            span.set_attribute("agent.status", "failed")
            span.record_exception(exc)
            span.set_status(Status(StatusCode.ERROR, description=str(exc)))
            raise
        finally:
            elapsed = time.perf_counter() - start_time
            get_observability_metrics().record_agent_execution(status=status, duration_s=elapsed)
            agent_execution_id_context.reset(token)
            if run_token is not None:
                analysis_run_id_context.reset(run_token)


@contextlib.contextmanager
def trace_tool_invocation(
    tool_name: str,
    *,
    execution_id: str | None = None,
    task_id: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> Generator[trace.Span, None, None]:
    """
    Context manager creating child span for an agent tool invocation.
    """
    start_time = time.perf_counter()
    success = True
    err_msg = None

    attrs = {
        "tool.name": tool_name,
        "tool.execution_id": execution_id or "",
        "task.id": task_id or "",
    }
    if metadata:
        for k, v in metadata.items():
            if not any(secret in k.lower() for secret in ("token", "key", "secret", "password", "auth")):
                attrs[f"tool.metadata.{k}"] = str(v)[:200]

    tracer = trace.get_tracer("app.agent")
    with tracer.start_as_current_span(f"tool:{tool_name}", attributes=attrs) as span:
        try:
            yield span
            span.set_attribute("tool.status", "success")
            span.set_status(Status(StatusCode.OK))
        except Exception as exc:
            success = False
            err_msg = str(exc)
            span.set_attribute("tool.status", "error")
            span.record_exception(exc)
            span.set_status(Status(StatusCode.ERROR, description=err_msg))
            raise
        finally:
            duration_s = time.perf_counter() - start_time
            duration_ms = duration_s * 1000.0

            get_observability_metrics().record_tool_invocation(
                tool_name=tool_name,
                duration_s=duration_s,
                success=success,
            )

            # Record in Langfuse if active
            ctx = span.get_span_context()
            trace_id_str = format(ctx.trace_id, "032x") if ctx and ctx.is_valid else ""
            if trace_id_str:
                get_langfuse_adapter().record_tool_call(
                    trace_id=trace_id_str,
                    tool_name=tool_name,
                    duration_ms=duration_ms,
                    is_error=not success,
                    error_message=err_msg,
                    metadata=metadata,
                )
