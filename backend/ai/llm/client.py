"""
LLM Gateway — single entry point for every LLM call in the system.
Owner: Meet — W1-12

Responsibilities:
    Day 1 (skeleton): interface + structured logging stub
    Day 2 (this):     full implementation — retry, structured output, token tracking

Usage::

    from ai.llm.openai_provider import OpenAIProvider
    from ai.llm.client import LLMGateway

    gateway  = LLMGateway(provider=OpenAIProvider())
    response = await gateway.generate(request)
    # response is always a typed LLMResponse — never a raw dict

team_rules.md rule:
    Every LLM call must log: model, input_tokens, output_tokens, latency_ms, success/failure.
    The LLM Gateway is the ONLY place in the codebase that calls an LLM API.
"""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING

from .schemas import LLMError, LLMRequest, LLMResponse

if TYPE_CHECKING:
    from .provider import LLMProvider

logger = logging.getLogger(__name__)


class LLMGateway:
    """
    Wraps an LLMProvider with:
    - Structured logging on every call (model, tokens, latency, success)
    - Delegates retry + backoff to the provider (OpenAIProvider handles it)
    - Structured-output / JSON-mode enforcement (delegated to provider)
    - Token usage tracking (extracted from LLMResponse)

    This is the *only* object that the rest of the codebase should call.
    Providers are injected at construction time, making the gateway testable.

    Args:
        provider: A concrete LLMProvider implementation (e.g. OpenAIProvider).

    Example::

        gateway = LLMGateway(provider=OpenAIProvider())
        response = await gateway.generate(request)
        print(response.content)        # always a str
        print(response.input_tokens)   # always populated
    """

    def __init__(self, provider: "LLMProvider") -> None:
        self._provider = provider

    async def generate(self, request: LLMRequest) -> LLMResponse:
        """
        Route a generation request through the provider with full logging.

        This method guarantees:
        - Returns a typed ``LLMResponse`` — never a raw ``dict``.
        - Logs every call with model, input_tokens, output_tokens, latency_ms, success.
        - On failure, logs the error class name before re-raising.

        Args:
            request: Fully constructed LLMRequest.

        Returns:
            LLMResponse with content, model, token counts, latency.

        Raises:
            LLMTimeoutError:     Provider timed out after all retries.
            LLMRateLimitError:   Rate-limited after all retries.
            LLMUnavailableError: Provider unreachable after all retries.
            LLMValidationError:  Structured output failed schema validation.
        """
        start = time.monotonic()
        success = False
        response: LLMResponse | None = None
        error_type: str | None = None

        try:
            response = await self._provider.generate(request)
            # Defensive: provider contract says LLMResponse, but guard anyway
            if not isinstance(response, LLMResponse):
                raise TypeError(
                    f"Provider {self._provider.provider_name!r} returned "
                    f"{type(response).__name__!r} instead of LLMResponse."
                )
            success = True
            return response

        except LLMError as exc:
            error_type = type(exc).__name__
            raise

        finally:
            latency_ms = (time.monotonic() - start) * 1000
            logger.info(
                "llm_call",
                extra={
                    "provider": self._provider.provider_name,
                    "model": request.model,
                    "input_tokens": response.input_tokens if response else None,
                    "output_tokens": response.output_tokens if response else None,
                    "latency_ms": round(latency_ms, 2),
                    "success": success,
                    "error_type": error_type,
                },
            )
