"""
LLM Gateway — Single Entry Point for All LLM Inference in the System.

Architecture & System Contracts (team_rules.md):
- Every LLM call in the platform MUST route through ``LLMGateway.generate()``.
- No application domain or controller may import vendor LLM SDKs directly.
- Emits structured telemetry logs on every invocation:
  request_id, model, input_tokens, output_tokens, latency_ms, provider, and success/failure.
- Encapsulates provider delegation, fallback execution, and lifecycle management.
- Hardened for production reliability (task2.md P0.1):
  * Explicit fallback policy (auth error fallback disabled by default).
  * Explicit cross-provider model translation mapping.
  * Preservation of request semantics during fallback.
  * Resource safety on aclose() (both providers cleaned up reliably).
"""

from collections.abc import AsyncIterator
import asyncio
import logging
import time
import uuid
from typing import Self

from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode

from .provider import LLMProvider
from .schemas import (
    LLMAuthenticationError,
    LLMError,
    LLMRateLimitError,
    LLMRequest,
    LLMResponse,
    LLMResponseChunk,
    LLMTimeoutError,
    LLMToolRequest,
    LLMToolResponse,
    LLMUnavailableError,
)

logger = logging.getLogger(__name__)

# Canonical cross-vendor model translations
CROSS_PROVIDER_DEFAULT_MODELS: dict[str, str] = {
    "groq": "openai/gpt-oss-120b",
    "gemini": "gemini-flash-lite-latest",
}

EXPLICIT_MODEL_TRANSLATION_MAP: dict[tuple[str, str], str] = {
    # (exact_requested_model, target_provider_name) -> target_model_name
    ("gemini-flash-lite-latest", "groq"): "openai/gpt-oss-120b",
    ("gemini-flash-latest", "groq"): "openai/gpt-oss-120b",
    ("gemini-1.5-flash", "groq"): "openai/gpt-oss-120b",
    ("gemini-2.0-flash", "groq"): "openai/gpt-oss-120b",
    ("gemini-1.5-pro", "groq"): "openai/gpt-oss-120b",
    ("openai/gpt-oss-120b", "gemini"): "gemini-flash-lite-latest",
    ("openai/gpt-oss-20b", "gemini"): "gemini-flash-lite-latest",
    ("llama-3.3-70b-versatile", "gemini"): "gemini-flash-lite-latest",
    ("qwen/qwen3.8-27b", "gemini"): "gemini-flash-lite-latest",
}


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
        provider: LLMProvider | None = None,
        fallback_provider: LLMProvider | None = None,
        *,
        primary: LLMProvider | None = None,
        secondary: LLMProvider | None = None,
        fallback_on_auth_error: bool = False,
        model_map: dict[tuple[str, str], str] | None = None,
    ) -> None:
        effective_provider = provider or primary
        if effective_provider is None:
            raise ValueError("LLMGateway requires a valid LLMProvider.")
        self._provider = effective_provider
        self._fallback_provider = fallback_provider or secondary
        self._fallback_on_auth_error = fallback_on_auth_error
        self._model_map = model_map or {}

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

    @property
    def fallback_on_auth_error(self) -> bool:
        """Whether authentication errors trigger fallback."""
        return self._fallback_on_auth_error

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
        - Preserves request semantics (response schema, temperature, max tokens).
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
            LLMAuthenticationError: If credentials fail and fallback_on_auth_error is False.
            LLMError: For any other unrecoverable provider failure.
        """
        if not isinstance(request, LLMRequest):
            raise TypeError(f"Expected LLMRequest instance, got {type(request).__name__}")
        if not request.messages:
            raise ValueError("LLMRequest must contain at least one Message turn.")

        request_id = getattr(request, "request_id", None) or uuid.uuid4().hex[:12]
        start_time = time.monotonic()
        success = False
        response: LLMResponse | None = None
        error_type: str | None = None
        effective_provider = self._provider
        effective_model = request.model
        fallback_occurred = False
        initial_provider_name = self._provider.provider_name

        # Determine estimated input token count for calibration (Issue #189)
        estimated_tokens = getattr(request, "estimated_tokens", None)
        if estimated_tokens is None:
            try:
                from ai.context.token_budget import estimate_messages_tokens
                estimated_tokens = await asyncio.to_thread(
                    estimate_messages_tokens,
                    request.messages,
                    provider=self._provider.provider_name,
                    model=request.model,
                )
            except Exception:
                estimated_tokens = None

        tracer = trace.get_tracer("ai.llm")

        with tracer.start_as_current_span(
            "gen_ai.generate",
            attributes={
                "gen_ai.system": self._provider.provider_name,
                "gen_ai.operation.name": "generate",
                "gen_ai.request.model": request.model,
                "gen_ai.request.temperature": request.temperature,
                "gen_ai.request.max_tokens": request.max_tokens,
                "gen_ai.fallback.attempted": False,
                "request_id": request_id,
            },
        ) as span:
            try:
                try:
                    response = await self._provider.generate(request)
                except (
                    LLMUnavailableError,
                    LLMTimeoutError,
                    LLMRateLimitError,
                    LLMAuthenticationError,
                ) as exc:
                    # Do not fallback on auth errors by default (P0.1)
                    if isinstance(exc, LLMAuthenticationError) and not self._fallback_on_auth_error:
                        raise

                    if getattr(request, "allow_fallback", True) and self._fallback_provider is not None:
                        fallback_occurred = True
                        span.set_attribute("gen_ai.fallback.attempted", True)
                        span.set_attribute("gen_ai.fallback.initial_provider", initial_provider_name)
                        span.set_attribute("gen_ai.fallback.target_provider", self._fallback_provider.provider_name)
                        span.set_attribute("gen_ai.fallback.reason", type(exc).__name__)
                        logger.warning(
                            "llm_gateway_primary_failed_trying_fallback",
                            extra={
                                "request_id": request_id,
                                "primary": self._provider.provider_name,
                                "fallback": self._fallback_provider.provider_name,
                                "error_type": type(exc).__name__,
                            },
                        )
                        effective_provider = self._fallback_provider
                        fallback_request = self._build_fallback_request(request)
                        effective_model = fallback_request.model
                        # Recompute estimated_tokens for the effective fallback provider and model;
                        # do not reuse the primary-provider estimate or request.estimated_tokens
                        try:
                            from ai.context.token_budget import estimate_messages_tokens
                            estimated_tokens = await asyncio.to_thread(
                                estimate_messages_tokens,
                                fallback_request.messages,
                                provider=self._fallback_provider.provider_name,
                                model=fallback_request.model,
                            )
                        except Exception:
                            estimated_tokens = None
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
                span.record_exception(exc)
                span.set_status(Status(StatusCode.ERROR, description=str(exc)))
                raise

            finally:
                latency_ms = (time.monotonic() - start_time) * 1000.0

                # OpenTelemetry GenAI Span completion
                if success and response:
                    span.set_attribute("gen_ai.response.model", effective_model)
                    span.set_attribute("gen_ai.usage.input_tokens", response.input_tokens)
                    span.set_attribute("gen_ai.usage.output_tokens", response.output_tokens)
                    if response.finish_reason:
                        span.set_attribute("gen_ai.response.finish_reasons", [response.finish_reason])
                    if response.tool_calls:
                        span.set_attribute("gen_ai.tool.call_count", len(response.tool_calls))
                    span.set_status(Status(StatusCode.OK))
                elif error_type:
                    span.set_status(Status(StatusCode.ERROR, description=error_type))

                # Record OpenTelemetry Metrics
                try:
                    from app.observability.metrics import get_observability_metrics
                    get_observability_metrics().record_llm_request(
                        provider=effective_provider.provider_name,
                        model=effective_model,
                        duration_s=latency_ms / 1000.0,
                        input_tokens=response.input_tokens if response else 0,
                        output_tokens=response.output_tokens if response else 0,
                        success=success,
                        fallback_occurred=fallback_occurred,
                        initial_provider=initial_provider_name if fallback_occurred else None,
                    )
                except Exception:
                    pass

                # Record Langfuse Generation
                try:
                    from app.observability.langfuse_adapter import get_langfuse_adapter
                    lf = get_langfuse_adapter()
                    if lf.is_active:
                        ctx = span.get_span_context()
                        trace_id_str = format(ctx.trace_id, "032x") if ctx and ctx.is_valid else request_id
                        lf.record_generation(
                            trace_id=trace_id_str,
                            name="llm.generate",
                            model=effective_model,
                            provider=effective_provider.provider_name,
                            input_tokens=response.input_tokens if response else 0,
                            output_tokens=response.output_tokens if response else 0,
                            latency_ms=latency_ms,
                            finish_reason=response.finish_reason if response else None,
                            metadata={
                                "request_id": request_id,
                                "fallback": fallback_occurred,
                                "tool_calls_count": len(response.tool_calls) if response and response.tool_calls else 0,
                            },
                            prompt=request.messages if getattr(request, "messages", None) else None,
                            completion=response.content if response else None,
                            error=error_type,
                        )
                except Exception:
                    pass

                from datetime import datetime, timezone
                from ai.context.token_budget import (
                    calculate_calibration_ratio,
                    get_calibration_tracker,
                )

                iso_ts = datetime.now(timezone.utc).isoformat()
                actual_input_tokens = response.input_tokens if response else None
                ratio = calculate_calibration_ratio(estimated_tokens, actual_input_tokens)
                feature_cat = getattr(request, "feature", None)

                try:
                    tracker = get_calibration_tracker()
                    tracker.record_sample(
                        provider=effective_provider.provider_name,
                        model=effective_model,
                        estimated_tokens=estimated_tokens,
                        actual_input_tokens=actual_input_tokens,
                        feature=feature_cat,
                        timestamp=iso_ts,
                    )
                except Exception as calib_exc:
                    logger.warning("token_calibration_recording_failed", extra={"error": str(calib_exc)})

                logger.info(
                    "llm_call",
                    extra={
                        "request_id": request_id,
                        "provider": effective_provider.provider_name,
                        "effective_provider": effective_provider.provider_name,
                        "requested_provider": self._provider.provider_name,
                        "model": effective_model,
                        "effective_model": effective_model,
                        "requested_model": request.model,
                        "fallback_used": effective_provider != self._provider,
                        "input_tokens": response.input_tokens if response else None,
                        "output_tokens": response.output_tokens if response else None,
                        "total_tokens": response.total_tokens if response else None,
                        "estimated_input_tokens": estimated_tokens,
                        "actual_input_tokens": actual_input_tokens,
                        "estimated_to_actual_ratio": ratio,
                        "timestamp": iso_ts,
                        "latency_ms": round(latency_ms, 2),
                        "success": success,
                        "error_type": error_type,
                        "tool_calls_count": len(response.tool_calls) if response and response.tool_calls else 0,
                        "finish_reason": response.finish_reason if response else None,
                    },
                )

    async def generate_stream(
        self, request: LLMRequest
    ) -> AsyncIterator[LLMResponseChunk]:
        """
        Execute streaming inference through the provider with chunk yield and fallback.
        """
        if not isinstance(request, LLMRequest):
            raise TypeError(f"Expected LLMRequest instance, got {type(request).__name__}")
        if not request.messages:
            raise ValueError("LLMRequest must contain at least one Message turn.")

        request_id = request.request_id or uuid.uuid4().hex[:12]
        req_with_id = request if request.request_id else request.model_copy(update={"request_id": request_id})

        tracer = trace.get_tracer("ai.llm")
        with tracer.start_as_current_span(
            "gen_ai.stream",
            attributes={
                "gen_ai.system": self._provider.provider_name,
                "gen_ai.operation.name": "stream",
                "gen_ai.request.model": request.model,
                "request_id": request_id,
            },
        ) as span:
            try:
                async for chunk in self._provider.generate_stream(req_with_id):
                    yield chunk
                span.set_status(Status(StatusCode.OK))
            except Exception as exc:
                if not self._should_attempt_fallback(exc) or not self._fallback_provider:
                    span.record_exception(exc)
                    span.set_status(Status(StatusCode.ERROR, description=str(exc)))
                    raise
                fallback_request = self._build_fallback_request(req_with_id)
                span.set_attribute("gen_ai.fallback.attempted", True)
                span.set_attribute("gen_ai.fallback.initial_provider", self._provider.provider_name)
                span.set_attribute("gen_ai.fallback.target_provider", self._fallback_provider.provider_name)
                span.set_attribute("gen_ai.fallback.reason", str(exc))
                logger.warning(
                    "llm_stream_primary_failed_attempting_fallback",
                    extra={
                        "error": str(exc),
                        "fallback_provider": self._fallback_provider.provider_name,
                        "fallback_model": fallback_request.model,
                        "request_id": request_id,
                    },
                )
                async for chunk in self._fallback_provider.generate_stream(fallback_request):
                    yield chunk
                span.set_status(Status(StatusCode.OK))

    def _should_attempt_fallback(self, exc: Exception) -> bool:
        """Determine whether an exception qualifies for fallback execution."""
        if isinstance(exc, LLMAuthenticationError) and not self._fallback_on_auth_error:
            return False
        return isinstance(
            exc,
            (
                LLMUnavailableError,
                LLMTimeoutError,
                LLMRateLimitError,
                LLMAuthenticationError,
            ),
        )

    async def generate_with_tools(self, request: LLMToolRequest) -> LLMToolResponse:
        """
        Execute a tool-capable inference request through the provider with comprehensive telemetry.

        Guarantees:
        - Returns a validated, typed ``LLMToolResponse`` containing generated text or tool calls.
        - Emits structured logging metrics on both success and failure.
        - Translates transient outages to optional fallback provider if configured.
        - Preserves tool definitions and conversation turns during fallback.
        - Enforces provider timeouts and key rotations.
        """
        if not isinstance(request, LLMToolRequest):
            raise TypeError(f"Expected LLMToolRequest instance, got {type(request).__name__}")
        if not request.messages:
            raise ValueError("LLMToolRequest must contain at least one Message turn.")

        request_id = getattr(request, "request_id", None) or uuid.uuid4().hex[:12]
        start_time = time.monotonic()
        success = False
        response: LLMToolResponse | None = None
        error_type: str | None = None
        effective_provider = self._provider
        effective_model = request.model

        # Determine estimated input token count for calibration (Issue #189)
        estimated_tokens = getattr(request, "estimated_tokens", None)
        if estimated_tokens is None:
            try:
                from ai.context.token_budget import estimate_messages_tokens
                estimated_tokens = await asyncio.to_thread(
                    estimate_messages_tokens,
                    request.messages,
                    provider=self._provider.provider_name,
                    model=request.model,
                )
            except Exception:
                estimated_tokens = None

        try:
            try:
                response = await self._provider.generate_with_tools(request)
            except (
                LLMUnavailableError,
                LLMTimeoutError,
                LLMRateLimitError,
                LLMAuthenticationError,
            ) as exc:
                if isinstance(exc, LLMAuthenticationError) and not self._fallback_on_auth_error:
                    raise

                if getattr(request, "allow_fallback", True) and self._fallback_provider is not None:
                    logger.warning(
                        "llm_gateway_primary_tool_failed_trying_fallback",
                        extra={
                            "request_id": request_id,
                            "primary": self._provider.provider_name,
                            "fallback": self._fallback_provider.provider_name,
                            "error_type": type(exc).__name__,
                        },
                    )
                    effective_provider = self._fallback_provider
                    fallback_request = self._build_fallback_tool_request(request)
                    effective_model = fallback_request.model
                    # Recompute estimated_tokens for the effective fallback provider and model;
                    # do not reuse the primary-provider estimate or request.estimated_tokens
                    try:
                        from ai.context.token_budget import estimate_messages_tokens
                        estimated_tokens = await asyncio.to_thread(
                            estimate_messages_tokens,
                            fallback_request.messages,
                            provider=self._fallback_provider.provider_name,
                            model=fallback_request.model,
                        )
                    except Exception:
                        estimated_tokens = None
                    response = await self._fallback_provider.generate_with_tools(fallback_request)
                else:
                    raise

            if not isinstance(response, LLMToolResponse):
                raise TypeError(
                    f"Provider {effective_provider.provider_name!r} returned "
                    f"{type(response).__name__!r} instead of LLMToolResponse."
                )

            success = True
            return response

        except LLMError as exc:
            error_type = type(exc).__name__
            raise

        finally:
            latency_ms = (time.monotonic() - start_time) * 1000.0
            from datetime import datetime, timezone
            from ai.context.token_budget import (
                calculate_calibration_ratio,
                get_calibration_tracker,
            )

            iso_ts = datetime.now(timezone.utc).isoformat()
            actual_input_tokens = response.input_tokens if response else None
            ratio = calculate_calibration_ratio(estimated_tokens, actual_input_tokens)
            feature_cat = getattr(request, "feature", None)

            try:
                tracker = get_calibration_tracker()
                tracker.record_sample(
                    provider=effective_provider.provider_name,
                    model=effective_model,
                    estimated_tokens=estimated_tokens,
                    actual_input_tokens=actual_input_tokens,
                    feature=feature_cat,
                    timestamp=iso_ts,
                )
            except Exception as calib_exc:
                logger.warning("token_calibration_recording_failed", extra={"error": str(calib_exc)})

            logger.info(
                "llm_tool_call",
                extra={
                    "request_id": request_id,
                    "provider": effective_provider.provider_name,
                    "effective_provider": effective_provider.provider_name,
                    "requested_provider": self._provider.provider_name,
                    "model": effective_model,
                    "effective_model": effective_model,
                    "requested_model": request.model,
                    "fallback_used": effective_provider != self._provider,
                    "tool_calls_count": len(response.tool_calls) if response else 0,
                    "is_final": response.is_final if response else False,
                    "input_tokens": response.input_tokens if response else None,
                    "output_tokens": response.output_tokens if response else None,
                    "total_tokens": response.total_tokens if response else None,
                    "estimated_input_tokens": estimated_tokens,
                    "actual_input_tokens": actual_input_tokens,
                    "estimated_to_actual_ratio": ratio,
                    "timestamp": iso_ts,
                    "latency_ms": round(latency_ms, 2),
                    "success": success,
                    "error_type": error_type,
                },
            )

    def _build_fallback_tool_request(self, request: LLMToolRequest) -> LLMToolRequest:
        """
        Translate request model for the fallback provider while strictly preserving
        tools, messages, temperature, and tokens.
        """
        assert self._fallback_provider is not None
        fb_name = (self._fallback_provider.provider_name or "").lower()
        req_model = (request.model or "").strip()
        primary_default = getattr(self._provider, "default_model", None)

        target_model: str | None = None

        if (req_model, fb_name) in self._model_map:
            target_model = self._model_map[(req_model, fb_name)]
        elif (req_model, fb_name) in EXPLICIT_MODEL_TRANSLATION_MAP:
            target_model = EXPLICIT_MODEL_TRANSLATION_MAP[(req_model, fb_name)]
        elif not req_model or req_model == "default" or req_model == primary_default:
            target_model = self._fallback_provider.default_model
        else:
            is_cross_vendor = (
                (fb_name == "groq" and req_model.lower().startswith("gemini"))
                or (
                    fb_name == "gemini"
                    and (
                        req_model.lower().startswith("openai/")
                        or req_model.lower().startswith("llama")
                        or req_model.lower().startswith("qwen")
                    )
                )
            )
            if is_cross_vendor:
                target_model = CROSS_PROVIDER_DEFAULT_MODELS.get(
                    fb_name, self._fallback_provider.default_model
                )
            else:
                target_model = req_model

        return LLMToolRequest(
            messages=request.messages,
            tools=request.tools,
            tool_choice=request.tool_choice,
            model=target_model or self._fallback_provider.default_model,
            temperature=request.temperature,
            max_tokens=request.max_tokens,
            request_id=getattr(request, "request_id", None),
        )

    def _build_fallback_request(self, request: LLMRequest) -> LLMRequest:
        """
        Translate request model for the fallback provider while strictly preserving
        all request semantics (messages, temperature, max_tokens, response_schema).
        """
        assert self._fallback_provider is not None
        fb_name = (self._fallback_provider.provider_name or "").lower()
        req_model = (request.model or "").strip()
        primary_default = getattr(self._provider, "default_model", None)

        target_model: str | None = None

        # 1. Custom model translation map
        if (req_model, fb_name) in self._model_map:
            target_model = self._model_map[(req_model, fb_name)]
        # 2. Explicit model mapping table
        elif (req_model, fb_name) in EXPLICIT_MODEL_TRANSLATION_MAP:
            target_model = EXPLICIT_MODEL_TRANSLATION_MAP[(req_model, fb_name)]
        # 3. Provider default / cross-vendor check
        elif not req_model or req_model == "default" or req_model == primary_default:
            target_model = self._fallback_provider.default_model
        else:
            # Check if requested model is cross-vendor
            is_cross_vendor = (
                (fb_name == "groq" and req_model.lower().startswith("gemini"))
                or (
                    fb_name == "gemini"
                    and (
                        req_model.lower().startswith("openai/")
                        or req_model.lower().startswith("llama")
                        or req_model.lower().startswith("qwen")
                    )
                )
            )
            if is_cross_vendor:
                target_model = CROSS_PROVIDER_DEFAULT_MODELS.get(
                    fb_name, self._fallback_provider.default_model
                )
            else:
                target_model = req_model

        return LLMRequest(
            messages=request.messages,
            model=target_model or self._fallback_provider.default_model,
            temperature=request.temperature,
            max_tokens=request.max_tokens,
            response_schema=request.response_schema,
            response_format=getattr(request, "response_format", None),
            tools=getattr(request, "tools", None),
            tool_choice=getattr(request, "tool_choice", None),
            stream=getattr(request, "stream", False),
            response_schema_mode=getattr(request, "response_schema_mode", "json"),
            allow_fallback=getattr(request, "allow_fallback", True),
            request_id=getattr(request, "request_id", None),
            estimated_tokens=getattr(request, "estimated_tokens", None),
            feature=getattr(request, "feature", None),
        )

    async def aclose(self) -> None:
        """
        Close provider resources safely (P0.1 requirement 8).
        Both primary and fallback providers are closed even if closing primary raises.
        """
        err: Exception | None = None
        try:
            await self._provider.aclose()
        except Exception as exc:  # noqa: BLE001
            err = exc
            logger.error("llm_gateway_primary_close_error: %s", exc)

        if self._fallback_provider is not None:
            try:
                await self._fallback_provider.aclose()
            except Exception as exc:  # noqa: BLE001
                logger.error("llm_gateway_fallback_close_error: %s", exc)
                if err is None:
                    err = exc

        if err is not None:
            raise err

    async def __aenter__(self: Self) -> Self:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: object,
    ) -> None:
        await self.aclose()


__all__ = [
    "CROSS_PROVIDER_DEFAULT_MODELS",
    "EXPLICIT_MODEL_TRANSLATION_MAP",
    "LLMGateway",
]
