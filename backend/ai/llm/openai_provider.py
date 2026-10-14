"""
OpenAI LLM Provider — Concrete Implementation of LLMProvider.

Responsibilities:
    - Wraps OpenAI Chat Completions REST API via httpx.
    - Configurable timeout and base URL (supports mock test gateways / Azure OpenAI).
    - Transport-level retry with exponential backoff on 429 and 5xx errors.
    - Respects upstream Retry-After headers when rate-limited.
    - JSON-mode structured output formatting and schema validation.
    - Reusable connection pooling via optional persistent AsyncClient.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
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
# Constants
# ---------------------------------------------------------------------------

_DEFAULT_TIMEOUT_SECONDS: float = 30.0
_MAX_RETRIES: int = 3
_BACKOFF_BASE_SECONDS: float = 1.0

_RETRYABLE_STATUS_CODES: frozenset[int] = frozenset({429, 500, 502, 503, 504})
_OPENAI_CHAT_URL = "https://api.openai.com/v1/chat/completions"


class OpenAIProvider(LLMProvider):
    """
    Concrete LLMProvider for the OpenAI Chat Completions API.

    Args:
        api_key:   OpenAI API key. Reads from ``OPENAI_API_KEY`` env var if omitted.
        timeout:   Per-request timeout in seconds (default: 30.0).
        base_url:  Override OpenAI base URL (useful for test mocking or proxies).
        client:    Optional shared ``httpx.AsyncClient`` for connection reuse.
    """

    def __init__(
        self,
        api_key: str | None = None,
        timeout: float = _DEFAULT_TIMEOUT_SECONDS,
        base_url: str | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._api_key = api_key or os.environ.get("OPENAI_API_KEY", "")
        self._timeout = timeout
        self._chat_url = (
            base_url.rstrip("/") + "/chat/completions"
        ) if base_url else _OPENAI_CHAT_URL
        self._external_client = client

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def provider_name(self) -> str:
        return "openai"

    @property
    def default_model(self) -> str:
        return "gpt-4o"

    @property
    def timeout(self) -> float:
        return self._timeout

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def generate(self, request: LLMRequest) -> LLMResponse:
        """
        Send a chat completion request to OpenAI with exponential backoff retry.

        Args:
            request: Fully constructed LLMRequest.

        Returns:
            LLMResponse with content, token counts, model name, and latency.

        Raises:
            LLMTimeoutError: On request timeout after retries.
            LLMRateLimitError: On HTTP 429 after retries.
            LLMUnavailableError: On HTTP 5xx or connection drops after retries.
            LLMAuthenticationError: On HTTP 401/403 credentials failure.
            LLMValidationError: If structured output fails schema validation.
        """
        payload = self._build_payload(request)
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }

        last_error: LLMError | None = None

        for attempt in range(1, _MAX_RETRIES + 1):
            client_ctx = (
                self._external_client
                if self._external_client is not None
                else httpx.AsyncClient(timeout=self._timeout)
            )

            async with (client_ctx if self._external_client is None else _noop_context(client_ctx)) as client:
                try:
                    start_ns = time.monotonic_ns()
                    resp = await client.post(self._chat_url, json=payload, headers=headers)
                    latency_ms = (time.monotonic_ns() - start_ns) / 1_000_000

                    if resp.status_code == 200:
                        return self._parse_response(resp.json(), latency_ms, request)

                    if resp.status_code == 429:
                        retry_after = self._parse_retry_after(resp.headers.get("Retry-After"))
                        last_error = LLMRateLimitError(
                            "OpenAI rate limit reached (HTTP 429).",
                            retry_after=retry_after,
                            provider=self.provider_name,
                        )
                    elif resp.status_code in _RETRYABLE_STATUS_CODES:
                        last_error = LLMUnavailableError(
                            f"HTTP {resp.status_code}",
                            status_code=resp.status_code,
                            provider=self.provider_name,
                        )
                    elif resp.status_code in (401, 403):
                        raise LLMAuthenticationError(
                            f"HTTP {resp.status_code}: {resp.text[:200]}",
                            status_code=resp.status_code,
                            provider=self.provider_name,
                        )
                    else:
                        raise LLMUnavailableError(
                            f"HTTP {resp.status_code}: {resp.text[:200]}",
                            status_code=resp.status_code,
                            provider=self.provider_name,
                        )

                except httpx.TimeoutException:
                    last_error = LLMTimeoutError(provider=self.provider_name)
                except httpx.RequestError as exc:
                    last_error = LLMUnavailableError(
                        f"Network error: {exc}",
                        provider=self.provider_name,
                    )

            if attempt < _MAX_RETRIES:
                backoff = _BACKOFF_BASE_SECONDS * (2 ** (attempt - 1))
                if isinstance(last_error, LLMRateLimitError) and last_error.retry_after is not None:
                    backoff = max(backoff, last_error.retry_after)

                logger.info(
                    "openai_llm_retry_backoff",
                    extra={"attempt": attempt, "backoff_seconds": backoff, "error": str(last_error)},
                )
                await asyncio.sleep(backoff)

        if last_error is not None:
            raise last_error

        raise LLMUnavailableError(
            f"OpenAI unavailable after {_MAX_RETRIES} attempts.",
            provider=self.provider_name,
        )

    async def aclose(self) -> None:
        """Close external client if managed."""
        if self._external_client is not None and not self._external_client.is_closed:
            await self._external_client.aclose()

    # ------------------------------------------------------------------
    # Private Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_retry_after(header_val: str | None) -> float | None:
        if not header_val:
            return None
        try:
            return float(header_val.strip())
        except (ValueError, TypeError):
            return None

    def _build_payload(self, request: LLMRequest) -> dict[str, Any]:
        """Convert LLMRequest into OpenAI Chat Completions payload."""
        payload: dict[str, Any] = {
            "model": request.model,
            "messages": [m.to_dict() for m in request.messages],
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
        request: LLMRequest,
    ) -> LLMResponse:
        """Parse raw response dict into typed LLMResponse with optional schema validation."""
        choices = data.get("choices")
        if not choices:
            raise LLMUnavailableError("OpenAI response contained no completion choices.")

        choice = choices[0]
        raw_content: str = choice.get("message", {}).get("content", "")
        usage: dict[str, int] = data.get("usage", {})

        if request.response_schema is not None:
            self._validate_structured_output(raw_content, request.response_schema)

        return LLMResponse(
            content=raw_content,
            model=data.get("model", request.model),
            input_tokens=usage.get("prompt_tokens", 0),
            output_tokens=usage.get("completion_tokens", 0),
            latency_ms=round(latency_ms, 2),
        )

    @staticmethod
    def _validate_structured_output(content: str, schema: type[BaseModel]) -> None:
        """
        Parse and validate structured JSON content against the given Pydantic schema.

        Strips markdown code blocks if the model wrapped the JSON in fences.
        """
        raw = content.strip()
        if raw.startswith("```"):
            lines = raw.splitlines()
            if len(lines) >= 2 and lines[0].startswith("```"):
                raw = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])

        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise LLMValidationError(f"Response is not valid JSON: {exc}") from exc

        try:
            schema.model_validate(parsed)
        except Exception as exc:
            raise LLMValidationError(f"Schema validation failed: {exc}") from exc


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
