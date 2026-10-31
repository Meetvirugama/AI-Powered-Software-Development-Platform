"""Stage-level latency and token usage telemetry (Week 2 Section 12 Item 14, B-14).

Tracks:
1. Stage-level latencies:
   - target_resolution_ms
   - context_assembly_ms
   - static_analysis_ms
   - llm_inference_ms
   - post_processing_ms
   - total_latency_ms
2. Token consumption:
   - prompt_tokens
   - completion_tokens
   - total_tokens
   - context_budget_tokens
   - context_utilized_tokens
3. Cost estimation (USD) based on standard provider pricing:
   - Gemini Flash: ~$0.075 / 1M input, ~$0.30 / 1M output
4. Structured logging and persistence into AnalysisRun.result_payload["stage_metrics"].
"""

from __future__ import annotations

import contextlib
import logging
import time
from dataclasses import asdict, dataclass, field
from typing import Any, Generator

from app.core.logging import request_id_context

logger = logging.getLogger(__name__)

# Standard pricing estimates (USD per 1M tokens)
_PRICE_PER_MILLION_INPUT: dict[str, float] = {
    "gemini": 0.075,
    "groq": 0.05,
    "default": 0.075,
}

_PRICE_PER_MILLION_OUTPUT: dict[str, float] = {
    "gemini": 0.30,
    "groq": 0.10,
    "default": 0.30,
}


@dataclass
class StageMetrics:
    """Encapsulates execution latency and token metrics across analysis pipeline stages."""

    stages_ms: dict[str, float] = field(default_factory=dict)
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    context_budget_tokens: int = 0
    context_utilized_tokens: int = 0
    provider: str | None = None
    model: str | None = None
    estimated_cost_usd: float = 0.0
    total_latency_ms: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        """Convert metrics to a JSON-serializable dictionary."""
        return {
            "stages_ms": {k: round(v, 2) for k, v in self.stages_ms.items()},
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
            "context_budget_tokens": self.context_budget_tokens,
            "context_utilized_tokens": self.context_utilized_tokens,
            "provider": self.provider,
            "model": self.model,
            "estimated_cost_usd": round(self.estimated_cost_usd, 6),
            "total_latency_ms": round(self.total_latency_ms, 2),
        }


class StageExecutionTimer:
    """Measures latency across pipeline stages and tracks token usage."""

    def __init__(self, feature_name: str, *, context_budget: int = 10_000) -> None:
        self.feature_name = feature_name
        self.start_time = time.perf_counter()
        self.stages_ms: dict[str, float] = {}
        self.prompt_tokens: int = 0
        self.completion_tokens: int = 0
        self.total_tokens: int = 0
        self.context_budget_tokens: int = context_budget
        self.context_utilized_tokens: int = 0
        self.provider: str | None = None
        self.model: str | None = None

    @contextlib.contextmanager
    def measure(self, stage_name: str) -> Generator[None, None, None]:
        """Context manager to measure the execution time of a specific pipeline stage."""
        t0 = time.perf_counter()
        try:
            yield
        finally:
            elapsed_ms = (time.perf_counter() - t0) * 1000.0
            self.stages_ms[stage_name] = self.stages_ms.get(stage_name, 0.0) + elapsed_ms

    def record_stage(self, stage_name: str, duration_ms: float) -> None:
        """Directly record execution duration for a stage."""
        self.stages_ms[stage_name] = round(duration_ms, 2)

    def record_tokens(
        self,
        *,
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
        total_tokens: int | None = None,
        context_utilized: int | None = None,
    ) -> None:
        """Record token usage metrics."""
        self.prompt_tokens += prompt_tokens
        self.completion_tokens += completion_tokens
        if total_tokens is not None:
            self.total_tokens = total_tokens
        else:
            self.total_tokens = self.prompt_tokens + self.completion_tokens
        if context_utilized is not None:
            self.context_utilized_tokens = context_utilized

    def set_model_info(self, *, provider: str | None, model: str | None) -> None:
        """Record provider and model metadata."""
        self.provider = provider
        self.model = model

    def finish(self) -> StageMetrics:
        """Calculate total execution time and estimated cost, log structured metrics, and return StageMetrics."""
        total_latency_ms = (time.perf_counter() - self.start_time) * 1000.0
        self.stages_ms["total_latency"] = total_latency_ms

        prov_key = (self.provider or "default").lower()
        cost_in = (self.prompt_tokens / 1_000_000.0) * _PRICE_PER_MILLION_INPUT.get(prov_key, 0.075)
        cost_out = (self.completion_tokens / 1_000_000.0) * _PRICE_PER_MILLION_OUTPUT.get(prov_key, 0.30)
        est_cost = cost_in + cost_out

        metrics = StageMetrics(
            stages_ms=self.stages_ms,
            prompt_tokens=self.prompt_tokens,
            completion_tokens=self.completion_tokens,
            total_tokens=self.total_tokens,
            context_budget_tokens=self.context_budget_tokens,
            context_utilized_tokens=self.context_utilized_tokens,
            provider=self.provider,
            model=self.model,
            estimated_cost_usd=est_cost,
            total_latency_ms=total_latency_ms,
        )

        logger.info(
            "stage_execution_metrics",
            extra={
                "request_id": request_id_context.get(),
                "feature": self.feature_name,
                "stages_ms": metrics.stages_ms,
                "tokens": {
                    "prompt": metrics.prompt_tokens,
                    "completion": metrics.completion_tokens,
                    "total": metrics.total_tokens,
                    "context_budget": metrics.context_budget_tokens,
                    "context_utilized": metrics.context_utilized_tokens,
                },
                "provider": metrics.provider,
                "model": metrics.model,
                "estimated_cost_usd": round(est_cost, 6),
                "total_latency_ms": round(total_latency_ms, 2),
            },
        )

        return metrics
