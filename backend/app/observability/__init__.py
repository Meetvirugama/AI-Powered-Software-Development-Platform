"""
Distributed Tracing, LLM Observability & Agent Execution Monitoring Package.
"""

from __future__ import annotations

from .agent import trace_agent_execution, trace_tool_invocation
from .genai import build_llm_span_attributes
from .instrumentation import (
    instrument_fastapi,
    instrument_httpx,
    instrument_redis,
    instrument_sqlalchemy,
)
from .langfuse_adapter import LangfuseAdapter, get_langfuse_adapter
from .metrics import ObservabilityMetrics, get_observability_metrics
from .telemetry import (
    TelemetryManager,
    get_meter,
    get_telemetry_manager,
    get_tracer,
    setup_telemetry,
    shutdown_telemetry,
)

__all__ = [
    "LangfuseAdapter",
    "ObservabilityMetrics",
    "TelemetryManager",
    "build_llm_span_attributes",
    "get_langfuse_adapter",
    "get_meter",
    "get_observability_metrics",
    "get_telemetry_manager",
    "get_tracer",
    "instrument_fastapi",
    "instrument_httpx",
    "instrument_redis",
    "instrument_sqlalchemy",
    "setup_telemetry",
    "shutdown_telemetry",
    "trace_agent_execution",
    "trace_tool_invocation",
]
