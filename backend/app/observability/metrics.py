"""
OpenTelemetry Metrics Instruments and Recorders.

Defines standardized counters and latency histograms for LLM generation,
autonomous agent execution, tool invocations, and HTTP requests with strict
cardinality governance.
"""

from __future__ import annotations

import logging
from typing import Any

from opentelemetry import metrics

logger = logging.getLogger(__name__)

_METER_NAME = "app.observability"


class ObservabilityMetrics:
    """Manages OpenTelemetry meters and instrument recordings."""

    def __init__(self) -> None:
        meter = metrics.get_meter(_METER_NAME)

        # LLM Generation Instruments
        self.llm_requests = meter.create_counter(
            name="llm.requests.total",
            description="Total count of LLM inference requests",
            unit="1",
        )
        self.llm_duration = meter.create_histogram(
            name="llm.request.duration.seconds",
            description="Latency of LLM inference requests in seconds",
            unit="s",
        )
        self.llm_tokens = meter.create_counter(
            name="llm.tokens.total",
            description="Total number of LLM tokens consumed",
            unit="1",
        )
        self.llm_fallbacks = meter.create_counter(
            name="llm.fallbacks.total",
            description="Total count of cross-provider LLM fallbacks triggered",
            unit="1",
        )

        # Agent & Tool Instruments
        self.agent_executions = meter.create_counter(
            name="agent.executions.total",
            description="Total count of autonomous agent workflow executions",
            unit="1",
        )
        self.agent_duration = meter.create_histogram(
            name="agent.execution.duration.seconds",
            description="End-to-end autonomous agent execution time in seconds",
            unit="s",
        )
        self.tool_invocations = meter.create_counter(
            name="agent.tools.invocations.total",
            description="Total count of agent tool invocations",
            unit="1",
        )
        self.tool_duration = meter.create_histogram(
            name="agent.tools.duration.seconds",
            description="Execution latency of agent tools in seconds",
            unit="s",
        )

    def record_llm_request(
        self,
        *,
        provider: str,
        model: str,
        duration_s: float,
        input_tokens: int = 0,
        output_tokens: int = 0,
        success: bool = True,
        fallback_occurred: bool = False,
        initial_provider: str | None = None,
    ) -> None:
        """Record standard LLM generation telemetry metrics."""
        try:
            status_label = "success" if success else "error"
            labels = {
                "gen_ai.system": provider,
                "gen_ai.response.model": model,
                "status": status_label,
            }
            self.llm_requests.add(1, labels)
            self.llm_duration.record(max(0.0, duration_s), labels)

            if input_tokens > 0:
                self.llm_tokens.add(input_tokens, {
                    "gen_ai.system": provider,
                    "gen_ai.response.model": model,
                    "token_type": "input",
                })
            if output_tokens > 0:
                self.llm_tokens.add(output_tokens, {
                    "gen_ai.system": provider,
                    "gen_ai.response.model": model,
                    "token_type": "output",
                })

            if fallback_occurred:
                self.llm_fallbacks.add(1, {
                    "initial_provider": initial_provider or "unknown",
                    "target_provider": provider,
                })
        except Exception as exc:
            logger.debug("record_llm_request_metric_failed", extra={"error": str(exc)})

    def record_agent_execution(self, *, status: str, duration_s: float) -> None:
        """Record autonomous agent workflow outcome and duration."""
        try:
            labels = {"status": status}
            self.agent_executions.add(1, labels)
            self.agent_duration.record(max(0.0, duration_s), labels)
        except Exception as exc:
            logger.debug("record_agent_execution_metric_failed", extra={"error": str(exc)})

    def record_tool_invocation(self, *, tool_name: str, duration_s: float, success: bool = True) -> None:
        """Record tool execution counter and latency."""
        try:
            labels = {
                "tool_name": tool_name,
                "status": "success" if success else "error",
            }
            self.tool_invocations.add(1, labels)
            self.tool_duration.record(max(0.0, duration_s), labels)
        except Exception as exc:
            logger.debug("record_tool_invocation_metric_failed", extra={"error": str(exc)})


_METRICS_INSTANCE: ObservabilityMetrics | None = None


def get_observability_metrics() -> ObservabilityMetrics:
    global _METRICS_INSTANCE
    if _METRICS_INSTANCE is None:
        _METRICS_INSTANCE = ObservabilityMetrics()
    return _METRICS_INSTANCE
