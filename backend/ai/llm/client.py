"""
LLM Gateway — Single Entry Point for All LLM Inference in the System.

Architecture & System Contracts (team_rules.md):
- Every LLM call in the platform MUST route through ``LLMGateway.generate()``.
- No application domain or controller may import vendor LLM SDKs directly.
- Emits structured telemetry logs on every invocation:
  model, input_tokens, output_tokens, latency_ms, provider, and success/failure.
- Encapsulates provider delegation, fallback execution, and lifecycle management.
"""

from __future__ import annotations

import logging
import time
from typing import Self

from .provider import LLMProvider
from .schemas import (
    LLMAuthenticationError,
    LLMError,
    LLMRateLimitError,
    LLMRequest,
    LLMResponse,
    LLMTimeoutError,
    LLMUnavailableError,
)

logger = logging.getLogger(__name__)


class LLMGateway:
    """
    Central orchestrator and gateway for all LLM interactions across the system.

    Wraps an ``LLMProvider`` with:
    - Standardized telemetry and structured logging on every request.
    - Type verification enforcing ``LLMResponse`` invariants.
    - Optional fallback provider support during transient provider outages.
    - Resource lifecycle management.

    Usage::

        from ai.llm.gemini_provider import GeminiProvider
        from ai.llm.client import LLMGateway

        gateway  = LLMGateway(provider=GeminiProvider(api_keys=["key"]))
        response = await gateway.generate(request)
    """

    def __init__(
        self,
        provider: LLMProvider,
        fallback_provider: LLMProvider | None = None,
    ) -> None:
        if provider is None:
            raise ValueError("LLMGateway requires a valid LLMProvider.")
        self._provider = provider
        self._fallback_provider = fallback_provider

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def provider(self) -> LLMProvider:
        """Configured primary inference provider."""
        return self._provider

    @property
    def provider_name(self) -> str:
        """Name of the active primary provider."""
        return self._provider.provider_name

    @property
    def fallback_provider(self) -> LLMProvider | None:
        """Optional secondary provider for disaster recovery."""
        return self._fallback_provider

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def generate(self, request: LLMRequest) -> LLMResponse:
        """
        Execute an inference request through the provider with comprehensive telemetry.

        Guarantees:
        - Returns a validated, typed ``LLMResponse``.
        - Emits structured logging metrics on both success and failure.
        - Translates transient outages to optional fallback provider if configured.
        - Resource lifecycle management.

        Args:
            request: Fully constructed LLMRequest.

        Returns:
            LLMResponse with output content, token usage, and latency.

        Raises:
            LLMTimeoutError: If the call times out.
            LLMRateLimitError: If rate limits are exhausted.
            LLMUnavailableError: If provider is down or unreachable.
            LLMValidationError: If structured output fails schema validation.
            LLMError: For any other unrecoverable provider failure.
        """
        if not isinstance(request, LLMRequest):
            raise TypeError(f"Expected LLMRequest instance, got {type(request).__name__}")
        if not request.messages:
            raise ValueError("LLMRequest must contain at least one Message turn.")

        start_time = time.monotonic()
        success = False
        response: LLMResponse | None = None
        error_type: str | None = None
        effective_provider = self._provider

        try:
            try:
                response = await self._provider.generate(request)
            except (
                LLMUnavailableError,
                LLMTimeoutError,
                LLMRateLimitError,
                LLMAuthenticationError,
            ) as exc:
                if self._fallback_provider is not None:
                    logger.warning(
                        "llm_gateway_primary_failed_trying_fallback",
                        extra={
                            "primary": self._provider.provider_name,
                            "fallback": self._fallback_provider.provider_name,
                            "error": str(exc),
                        },
                    )
                    effective_provider = self._fallback_provider
                    fallback_request = request
                    # If request model was provider-specific or default, adjust for fallback
                    primary_default = getattr(self._provider, "default_model", None)
                    req_model = (request.model or "").strip().lower()
                    fb_name = (self._fallback_provider.provider_name or "").lower()
                    is_cross_vendor_model = (
                        (fb_name == "groq" and req_model.startswith("gemini"))
                        or (fb_name == "gemini" and (req_model.startswith("openai/") or req_model.startswith("llama") or req_model.startswith("qwen")))
                    )
                    if (
                        not request.model
                        or request.model == "default"
                        or request.model == primary_default
                        or is_cross_vendor_model
                    ):
                        fallback_request = LLMRequest(
                            messages=request.messages,
                            model=self._fallback_provider.default_model,
                            temperature=request.temperature,
                            max_tokens=request.max_tokens,
                            response_schema=request.response_schema,
                        )
                    response = await self._fallback_provider.generate(fallback_request)
                else:
                    raise

            if not isinstance(response, LLMResponse):
                raise TypeError(
                    f"Provider {effective_provider.provider_name!r} returned "
                    f"{type(response).__name__!r} instead of LLMResponse."
                )

            success = True
            return response

        except LLMError as exc:
            error_type = type(exc).__name__
            raise

        finally:
            latency_ms = (time.monotonic() - start_time) * 1000.0
            logger.info(
                "llm_call",
                extra={
                    "provider": effective_provider.provider_name,
                    "model": request.model,
                    "input_tokens": response.input_tokens if response else None,
                    "output_tokens": response.output_tokens if response else None,
                    "total_tokens": response.total_tokens if response else None,
                    "latency_ms": round(latency_ms, 2),
                    "success": success,
                    "error_type": error_type,
                },
            )

    async def aclose(self) -> None:
        """Close provider resources."""
        await self._provider.aclose()
        if self._fallback_provider is not None:
            await self._fallback_provider.aclose()

    async def __aenter__(self: Self) -> Self:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: object,
    ) -> None:
        await self.aclose()
