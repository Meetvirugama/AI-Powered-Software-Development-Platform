"""Security test for LLM concurrency cap (ISS-025 / TST-16).

Verifies that LLMGateway bounds simultaneous provider calls to
settings.ai_max_concurrent_calls (or explicitly provided max_concurrent_calls),
preventing upstream provider rate limit exhaustion, resource starvation,
and cost spikes.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from ai.llm.client import LLMGateway
from ai.llm.provider import LLMProvider
from ai.llm.schemas import (
    LLMRequest,
    LLMResponse,
    Message,
)


class ConcurrencyTrackingProvider(LLMProvider):
    """Mock LLM provider that measures simultaneous concurrent invocations."""

    def __init__(self, delay: float = 0.05) -> None:
        self.delay = delay
        self.current_concurrency = 0
        self.peak_concurrency = 0
        self.total_invocations = 0
        self._lock = asyncio.Lock()

    @property
    def provider_name(self) -> str:
        return "concurrency-mock"

    async def generate(self, request: LLMRequest) -> LLMResponse:
        async with self._lock:
            self.current_concurrency += 1
            self.total_invocations += 1
            self.peak_concurrency = max(self.peak_concurrency, self.current_concurrency)

        try:
            await asyncio.sleep(self.delay)
            return LLMResponse(
                content=f"Echo for {request.model}",
                model=request.model,
                input_tokens=10,
                output_tokens=5,
                latency_ms=self.delay * 1000.0,
                finish_reason="stop",
                provider=self.provider_name,
            )
        finally:
            async with self._lock:
                self.current_concurrency -= 1

    async def generate_stream(self, request: LLMRequest) -> Any:  # pragma: no cover
        raise NotImplementedError

    async def generate_with_tools(self, request: Any) -> Any:  # pragma: no cover
        raise NotImplementedError


@pytest.mark.asyncio
async def test_llm_gateway_enforces_explicit_concurrency_cap() -> None:
    """Verify LLMGateway never allows concurrent calls to exceed max_concurrent_calls."""
    provider = ConcurrencyTrackingProvider(delay=0.04)
    gateway = LLMGateway(provider=provider, max_concurrent_calls=3)

    requests = [
        LLMRequest(
            messages=[Message(role="user", content=f"Task {i}")],
            model="gemini-2.5-flash",
        )
        for i in range(12)
    ]

    responses = await asyncio.gather(*(gateway.generate(req) for req in requests))

    assert len(responses) == 12
    assert all(r.content.startswith("Echo") for r in responses)
    assert provider.total_invocations == 12
    assert provider.peak_concurrency <= 3
    assert provider.current_concurrency == 0


@pytest.mark.asyncio
async def test_llm_gateway_defaults_to_settings_concurrency_cap() -> None:
    """Verify LLMGateway defaults to settings.ai_max_concurrent_calls when none passed."""
    from app.core.config import get_settings
    settings = get_settings()

    provider = ConcurrencyTrackingProvider(delay=0.02)
    gateway = LLMGateway(provider=provider)

    assert gateway.semaphore._value == settings.ai_max_concurrent_calls
