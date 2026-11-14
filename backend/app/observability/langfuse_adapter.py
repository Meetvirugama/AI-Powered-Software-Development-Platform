"""
Langfuse LLM Observability Adapter.

Provides dedicated LLM and agent observation tracking (generations, spans, token usage,
model parameters, and latency) with fail-closed safety, SSRF host validation, and privacy redaction.
"""

from __future__ import annotations

import logging
from typing import Any

from app.core.secret_redaction import redact, redact_obj
from app.services.mcp_elicitation_service import validate_mcp_url

logger = logging.getLogger(__name__)

_LANGFUSE_ADAPTER: LangfuseAdapter | None = None


def _sanitize_langfuse_input(payload: Any) -> Any:
    """Recursively convert message models or dicts into secret-redacted structures."""
    if payload is None:
        return None
    if isinstance(payload, str):
        return redact(payload)
    if isinstance(payload, list):
        sanitized_list = []
        for item in payload:
            if hasattr(item, "to_dict") and callable(item.to_dict):
                sanitized_list.append(redact_obj(item.to_dict()))
            elif hasattr(item, "model_dump") and callable(item.model_dump):
                sanitized_list.append(redact_obj(item.model_dump()))
            else:
                sanitized_list.append(redact_obj(item))
        return sanitized_list
    return redact_obj(payload)


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
                safe_host = validate_mcp_url(base_url)
                from langfuse import Langfuse
                self._client = Langfuse(
                    public_key=public_key,
                    secret_key=secret_key,
                    host=safe_host,
                )
                logger.info("langfuse_adapter_initialized", extra={"host": safe_host})
            except Exception as exc:
                logger.warning("langfuse_adapter_init_failed", extra={"error": redact(str(exc))})
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
        """Record an LLM generation event in Langfuse with mandatory secret redaction."""
        if not self.is_active:
            return

        try:
            input_payload = _sanitize_langfuse_input(prompt) if self.capture_prompts else None
            output_payload = redact(completion) if (self.capture_responses and completion is not None) else None
            safe_error = redact(str(error)) if error else None

            meta = redact_obj(dict(metadata or {}))
            meta["provider"] = provider
            meta["latency_ms"] = round(latency_ms, 2)
            if finish_reason:
                meta["finish_reason"] = finish_reason

            usage_dict = {
                "input": input_tokens,
                "output": output_tokens,
                "total": input_tokens + output_tokens,
            }

            if hasattr(self._client, "generation"):
                self._client.generation(
                    trace_id=trace_id,
                    name=name,
                    model=model,
                    input=input_payload,
                    output=output_payload,
                    usage=usage_dict,
                    metadata=meta,
                    level="ERROR" if safe_error else "DEFAULT",
                    status_message=safe_error,
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
                    level="ERROR" if safe_error else "DEFAULT",
                    status_message=safe_error,
                )
        except Exception as exc:
            logger.debug("langfuse_record_generation_failed", extra={"error": redact(str(exc))})

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
        """Record a tool invocation span in Langfuse with mandatory secret redaction."""
        if not self.is_active:
            return

        try:
            meta = redact_obj(dict(metadata or {}))
            meta["duration_ms"] = round(duration_ms, 2)
            safe_err_msg = redact(str(error_message)) if error_message else None

            if hasattr(self._client, "span"):
                self._client.span(
                    trace_id=trace_id,
                    name=f"tool:{tool_name}",
                    metadata=meta,
                    level="ERROR" if is_error else "DEFAULT",
                    status_message=safe_err_msg,
                )
            elif hasattr(self._client, "trace"):
                t = self._client.trace(id=trace_id)
                t.span(
                    name=f"tool:{tool_name}",
                    metadata=meta,
                    level="ERROR" if is_error else "DEFAULT",
                    status_message=safe_err_msg,
                )
        except Exception as exc:
            logger.debug("langfuse_record_tool_call_failed", extra={"error": redact(str(exc))})

    def flush(self) -> None:
        """Flush pending observations."""
        if not self.is_active:
            return
        try:
            if hasattr(self._client, "flush"):
                self._client.flush()
        except Exception as exc:
            logger.debug("langfuse_flush_error", extra={"error": redact(str(exc))})

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
            logger.debug("langfuse_shutdown_error", extra={"error": redact(str(exc))})
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
