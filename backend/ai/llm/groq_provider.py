"""
Groq LLM Provider — OpenAI-Compatible Low-Latency Inference with Key Rotation.

Features:
    - Wraps Groq's high-speed inference endpoint using an OpenAI-compatible wire schema.
    - Automatic round-robin key rotation across free-tier keys to circumvent rate limits.
    - Model resolution mapping standard names (e.g. gpt-4o) to Groq equivalents.
    - Structured output JSON-mode enforcement and Pydantic schema validation.
    - Real latency measurement and connection pooling support.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from itertools import cycle
from typing import Any

import httpx
from pydantic import BaseModel

from .provider import LLMProvider
from .schemas import (
    LLMAuthenticationError,
    LLMError,
    LLMRateLimitError,
    LLMRequest,
    LLMResponse,
    LLMTimeoutError,
    LLMUnavailableError,
    LLMValidationError,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants & Model Mapping
# ---------------------------------------------------------------------------

_DEFAULT_TIMEOUT_SECONDS: float = 30.0
_MAX_RETRIES: int = 3
_BACKOFF_BASE_SECONDS: float = 1.0
_GROQ_CHAT_URL = "https://api.groq.com/openai/v1/chat/completions"
_RETRYABLE_STATUS_CODES: frozenset[int] = frozenset({429, 500, 502, 503, 504})

_DEFAULT_MODEL = "openai/gpt-oss-120b"

# Map standard/legacy model names to current Groq endpoints
_MODEL_MAP: dict[str, str] = {
    "openai/gpt-oss-120b": "openai/gpt-oss-120b",
    "openai/gpt-oss-20b": "openai/gpt-oss-20b",
    "qwen/qwen3.8-27b": "qwen/qwen3.8-27b",
    "allam-2-7b": "allam-2-7b",
    # Legacy and fallback mappings to active Groq models
    "llama-3.3-70b-versatile": "openai/gpt-oss-120b",
    "llama-3.1-8b-instant": "openai/gpt-oss-20b",
    "llama3-70b-8192": "openai/gpt-oss-120b",
    "llama3-8b-8192": "openai/gpt-oss-20b",
    "mixtral-8x7b-32768": "qwen/qwen3.8-27b",
    "gpt-4o": "openai/gpt-oss-120b",
    "gpt-4": "openai/gpt-oss-120b",
    "gpt-3.5-turbo": "openai/gpt-oss-20b",
}


class GroqProvider(LLMProvider):
    """
    Concrete LLMProvider for Groq Cloud.

    Args:
        api_keys: List of Groq API keys. Falls back to ``GROQ_API_KEYS`` or ``GROQ_API_KEY``.
        timeout: Per-request timeout in seconds (default: 30.0).
        model: Default model identifier (default: ``llama-3.3-70b-versatile``).
        client: Optional shared ``httpx.AsyncClient`` for connection pooling.
    """

    def __init__(
        self,
        api_keys: list[str] | None = None,
        timeout: float = _DEFAULT_TIMEOUT_SECONDS,
        model: str = _DEFAULT_MODEL,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        if api_keys:
            self._api_keys = [k.strip() for k in api_keys if k.strip()]
        else:
            keys_str = os.getenv("GROQ_API_KEYS", "") or os.getenv("GROQ_API_KEY", "")
            self._api_keys = [k.strip() for k in keys_str.split(",") if k.strip()]

        if not self._api_keys:
            raise ValueError("No Groq API keys configured. Set GROQ_API_KEYS env var.")

        self._key_cycle = cycle(self._api_keys)
        self._timeout = timeout
        self._default_model = model
        self._external_client = client

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def provider_name(self) -> str:
        return "groq"

    @property
    def default_model(self) -> str:
        return self._default_model

    @property
    def timeout(self) -> float:
        return self._timeout

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def generate(self, request: LLMRequest) -> LLMResponse:
        """Execute chat completion on Groq with key rotation and backoff."""
        resolved_model = self._resolve_model(request.model)
        payload = self._build_payload(request, resolved_model)

        last_error: LLMError | None = None

        for attempt in range(1, _MAX_RETRIES + 1):
            api_key = self._next_key()
            client_ctx = (
                self._external_client
                if self._external_client is not None
                else httpx.AsyncClient(timeout=self._timeout)
            )

            async with (client_ctx if self._external_client is None else _noop_context(client_ctx)) as client:
                try:
                    start_ns = time.monotonic_ns()
                    resp = await client.post(
                        _GROQ_CHAT_URL,
                        headers={
                            "Authorization": f"Bearer {api_key}",
                            "Content-Type": "application/json",
                        },
                        json=payload,
                    )
                    latency_ms = (time.monotonic_ns() - start_ns) / 1_000_000

                    if resp.status_code == 200:
                        return self._parse_response(
                            resp.json(),
                            latency_ms=latency_ms,
                            model=resolved_model,
                            schema=request.response_schema,
                        )

                    if resp.status_code == 429:
                        last_error = LLMRateLimitError(
                            "Groq rate limit exceeded.",
                            provider=self.provider_name,
                        )
                        logger.warning(
                            "groq_rate_limit_rotating_key",
                            extra={"attempt": attempt, "key_masked": f"{api_key[:4]}...{api_key[-4:]}"},
                        )
                        # Rotate key immediately with minimal wait
                        await asyncio.sleep(0.1)
                        continue

                    if resp.status_code == 400:
                        err_body = resp.text[:200]
                        try:
                            err_data = resp.json()
                            if isinstance(err_data, dict):
                                err_body = err_data.get("error", {}).get("message", err_body)
                        except (json.JSONDecodeError, ValueError, TypeError):
                            logger.debug("groq_400_raw_body_fallback")
                        raise LLMUnavailableError(
                            f"Groq 400 Bad Request: {err_body}",
                            status_code=400,
                            provider=self.provider_name,
                        )

                    if resp.status_code in (401, 403):
                        raise LLMAuthenticationError(
                            f"Groq authentication failure (HTTP {resp.status_code}).",
                            status_code=resp.status_code,
                            provider=self.provider_name,
                        )

                    if resp.status_code in _RETRYABLE_STATUS_CODES:
                        last_error = LLMUnavailableError(
                            f"Groq server error (HTTP {resp.status_code}).",
                            status_code=resp.status_code,
                            provider=self.provider_name,
                        )

                except httpx.TimeoutException as exc:
                    last_error = LLMTimeoutError(str(exc), provider=self.provider_name)
                except httpx.RequestError as exc:
                    last_error = LLMUnavailableError(str(exc), provider=self.provider_name)

            if attempt < _MAX_RETRIES:
                wait_time = _BACKOFF_BASE_SECONDS * (2 ** (attempt - 1))
                logger.info(
                    "groq_retry_backoff",
                    extra={"attempt": attempt, "wait_seconds": wait_time, "error": str(last_error)},
                )
                await asyncio.sleep(wait_time)

        if last_error is not None:
            raise last_error

        raise LLMUnavailableError(
            f"Groq unavailable after {_MAX_RETRIES} attempts.",
            provider=self.provider_name,
        )

    async def aclose(self) -> None:
        """Close external client if managed."""
        if self._external_client is not None and not self._external_client.is_closed:
            await self._external_client.aclose()

    # ------------------------------------------------------------------
    # Private Helpers
    # ------------------------------------------------------------------

    def _next_key(self) -> str:
        return next(self._key_cycle)

    def _resolve_model(self, requested: str) -> str:
        return _MODEL_MAP.get(requested, self._default_model)

    def _build_payload(self, request: LLMRequest, model: str) -> dict[str, Any]:
        messages = [m.to_dict() for m in request.messages]
        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": request.temperature,
            "max_tokens": request.max_tokens,
        }

        if request.response_schema is not None:
            payload["response_format"] = {"type": "json_object"}

        return payload

    def _parse_response(
        self,
        data: dict[str, Any],
        latency_ms: float,
        model: str,
        schema: type[BaseModel] | None,
    ) -> LLMResponse:
        choices = data.get("choices")
        if not choices:
            raise LLMUnavailableError("Groq response contained no choices.", provider=self.provider_name)

        content = choices[0].get("message", {}).get("content", "")
        usage = data.get("usage", {})

        if schema is not None:
            self._validate_structured_output(content, schema)

        return LLMResponse(
            content=content,
            model=model,
            input_tokens=usage.get("prompt_tokens", 0),
            output_tokens=usage.get("completion_tokens", 0),
            latency_ms=round(latency_ms, 2),
        )

    @staticmethod
    def _validate_structured_output(content: str, schema: type[BaseModel]) -> None:
        raw = content.strip()
        if raw.startswith("```"):
            lines = raw.splitlines()
            if len(lines) >= 2 and lines[0].startswith("```"):
                raw = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])

        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise LLMValidationError(f"Response is not valid JSON: {exc}", provider="groq") from exc

        try:
            schema.model_validate(parsed)
        except Exception as exc:
            raise LLMValidationError(f"Schema validation failed: {exc}", provider="groq") from exc


class _noop_context:
    """Async context manager wrapper for reusing persistent client."""

    def __init__(self, client: httpx.AsyncClient) -> None:
        self.client = client

    async def __aenter__(self) -> httpx.AsyncClient:
        return self.client

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: object,
    ) -> None:
        pass
