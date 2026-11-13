"""
Langfuse LLM Observability Adapter.

Provides dedicated LLM and agent observation tracking (generations, spans, token usage,
model parameters, and latency) with fail-closed safety and privacy redaction.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

_LANGFUSE_ADAPTER: LangfuseAdapter | None = None


class LangfuseAdapter:
    """
    Fail-safe adapter bridging LLMGateway and agent workflows to Langfuse.
    """

    def __init__(
        self,
        *,
        enabled: bool = False,
        public_key: str | None = None,
        secret_key: str | None = None,
        base_url: str = "https://cloud.langfuse.com",
        capture_prompts: bool = False,
        capture_responses: bool = False,
        client: Any | None = None,
    ) -> None:
        self.enabled = bool(enabled and (client or (public_key and secret_key)))
        self.capture_prompts = capture_prompts
        self.capture_responses = capture_responses
        self._client = client

        if self.enabled and self._client is None:
            try:
                from langfuse import Langfuse
                self._client = Langfuse(
                    public_key=public_key,
                    secret_key=secret_key,
                    host=base_url,
                )
                logger.info("langfuse_adapter_initialized", extra={"host": base_url})
            except Exception as exc:
                logger.warning("langfuse_adapter_init_failed", extra={"error": str(exc)})
                self.enabled = False
                self._client = None

    @property
    def is_active(self) -> bool:
        return self.enabled and self._client is not None

    def record_generation(
        self,
        *,
        trace_id: str,
        name: str = "llm.generate",
        model: str,
        provider: str,
        input_tokens: int = 0,
        output_tokens: int = 0,
        latency_ms: float = 0.0,
        finish_reason: str | None = None,
        metadata: dict[str, Any] | None = None,
        prompt: Any | None = None,
        completion: str | None = None,
        error: str | None = None,
    ) -> None:
        """Record an LLM generation event in Langfuse."""
        if not self.is_active:
            return

        try:
            input_payload = prompt if self.capture_prompts else None
            output_payload = completion if self.capture_responses else None

            meta = dict(metadata or {})
            meta["provider"] = provider
            meta["latency_ms"] = round(latency_ms, 2)
            if finish_reason:
                meta["finish_reason"] = finish_reason

            usage_dict = {
                "input": input_tokens,
                "output": output_tokens,
                "total": input_tokens + output_tokens,
            }

            # Use modern or fallback generation API safely
            if hasattr(self._client, "generation"):
                self._client.generation(
                    trace_id=trace_id,
                    name=name,
                    model=model,
                    input=input_payload,
                    output=output_payload,
                    usage=usage_dict,
                    metadata=meta,
                    level="ERROR" if error else "DEFAULT",
                    status_message=error,
                )
            elif hasattr(self._client, "trace"):
                t = self._client.trace(id=trace_id)
                t.generation(
                    name=name,
                    model=model,
                    input=input_payload,
                    output=output_payload,
                    usage=usage_dict,
                    metadata=meta,
                    level="ERROR" if error else "DEFAULT",
                    status_message=error,
                )
        except Exception as exc:
            logger.debug("langfuse_record_generation_failed", extra={"error": str(exc)})

    def record_tool_call(
        self,
        *,
        trace_id: str,
        tool_name: str,
        duration_ms: float,
        is_error: bool = False,
        error_message: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Record a tool invocation span in Langfuse."""
        if not self.is_active:
            return

        try:
            meta = dict(metadata or {})
            meta["duration_ms"] = round(duration_ms, 2)

            if hasattr(self._client, "span"):
                self._client.span(
                    trace_id=trace_id,
                    name=f"tool:{tool_name}",
                    metadata=meta,
                    level="ERROR" if is_error else "DEFAULT",
                    status_message=error_message,
                )
            elif hasattr(self._client, "trace"):
                t = self._client.trace(id=trace_id)
                t.span(
                    name=f"tool:{tool_name}",
                    metadata=meta,
                    level="ERROR" if is_error else "DEFAULT",
                    status_message=error_message,
                )
        except Exception as exc:
            logger.debug("langfuse_record_tool_call_failed", extra={"error": str(exc)})

    def flush(self) -> None:
        """Flush pending observations."""
        if not self.is_active:
            return
        try:
            if hasattr(self._client, "flush"):
                self._client.flush()
        except Exception as exc:
            logger.debug("langfuse_flush_error", extra={"error": str(exc)})

    def shutdown(self) -> None:
        """Flush and terminate Langfuse client."""
        if not self.is_active:
            return
        try:
            if hasattr(self._client, "shutdown"):
                self._client.shutdown()
            elif hasattr(self._client, "flush"):
                self._client.flush()
        except Exception as exc:
            logger.debug("langfuse_shutdown_error", extra={"error": str(exc)})
        self._client = None
        self.enabled = False


def get_langfuse_adapter(settings: Any = None) -> LangfuseAdapter:
    """Retrieve or initialize singleton Langfuse adapter."""
    global _LANGFUSE_ADAPTER
    if _LANGFUSE_ADAPTER is None:
        if settings is None:
            from app.core.config import get_settings
            settings = get_settings()

        _LANGFUSE_ADAPTER = LangfuseAdapter(
            enabled=getattr(settings, "langfuse_enabled", False),
            public_key=getattr(settings, "langfuse_public_key", None),
            secret_key=getattr(settings, "langfuse_secret_key", None),
            base_url=getattr(settings, "langfuse_base_url", "https://cloud.langfuse.com"),
            capture_prompts=getattr(settings, "observability_capture_prompts", False),
            capture_responses=getattr(settings, "observability_capture_responses", False),
        )
    return _LANGFUSE_ADAPTER
