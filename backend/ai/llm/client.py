"""
LLM Gateway — single entry point for every LLM call in the system.
Owner: Meet — W1-12

Responsibilities (implemented across Day 1–2):
    Day 1 (this file): interface skeleton + structured logging stub
    Day 2: OpenAI provider, retry/backoff, structured-output enforcement, token tracking

Usage:
    gateway = LLMGateway(provider=OpenAIProvider())
    response = await gateway.generate(request)

team_rules.md rule:
    Every LLM call must log: model, input_tokens, output_tokens, latency, success/failure.
"""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING

from .schemas import LLMRequest, LLMResponse

if TYPE_CHECKING:
    from .provider import LLMProvider

logger = logging.getLogger(__name__)


class LLMGateway:
    """
    Wraps an LLMProvider with:
    - Structured logging on every call
    - Retry + exponential backoff (Day 2)
    - Structured-output / JSON-mode enforcement (Day 2)
    - Token usage tracking (Day 2)
    """

    def __init__(self, provider: "LLMProvider") -> None:
        self._provider = provider

    async def generate(self, request: LLMRequest) -> LLMResponse:
        """
        Route a generation request through the provider with logging.

        Args:
            request: LLMRequest instance.

        Returns:
            Typed LLMResponse — never a raw dict.
        """
        start = time.monotonic()
        success = False
        try:
            response = await self._provider.generate(request)
            success = True
            return response
        finally:
            latency_ms = (time.monotonic() - start) * 1000
            logger.info(
                "llm_call",
                extra={
                    "provider": self._provider.provider_name,
                    "model": request.model,
                    # token counts available only on success; filled in by Day-2 impl
                    "latency_ms": round(latency_ms, 2),
                    "success": success,
                },
            )
