"""
OpenAI LLM Provider — concrete implementation of LLMProvider.
Owner: Meet — W1-12, Day 2

Responsibilities:
    - Wraps the OpenAI Chat Completions API (async)
    - Configurable per-request timeout (default 30 s)
    - Retry: 3 attempts with exponential backoff on 429 / 503
    - Structured output: when request.response_schema is set, enables JSON mode
      and validates the returned JSON against the schema
    - Token tracking: extracts input_tokens and output_tokens from usage field

DO NOT add retry / logging here — those live in LLMGateway (client.py).
Only provider-level concerns belong here.
"""

from __future__ import annotations

import json
import time
from typing import Any

import httpx
from pydantic import BaseModel

from .provider import LLMProvider
from .schemas import LLMRequest, LLMResponse, LLMRateLimitError, LLMTimeoutError, LLMUnavailableError, LLMValidationError

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_DEFAULT_TIMEOUT_SECONDS: float = 30.0
_MAX_RETRIES: int = 3
_BACKOFF_BASE_SECONDS: float = 1.0  # 1 s, 2 s, 4 s

# Status codes that warrant a retry
_RETRYABLE_STATUS_CODES: frozenset[int] = frozenset({429, 500, 502, 503, 504})


class OpenAIProvider(LLMProvider):
    """
    Concrete LLMProvider for the OpenAI Chat Completions API.

    Args:
        api_key:   OpenAI API key. Reads from OPENAI_API_KEY env var if not supplied.
        timeout:   Per-request timeout in seconds (default 30).
        base_url:  Override the OpenAI base URL (useful for testing with a mock server).

    Example::

        provider = OpenAIProvider(api_key="sk-...")
        gateway  = LLMGateway(provider=provider)
        response = await gateway.generate(request)
    """

    _OPENAI_CHAT_URL = "https://api.openai.com/v1/chat/completions"

    def __init__(
        self,
        api_key: str | None = None,
        timeout: float = _DEFAULT_TIMEOUT_SECONDS,
        base_url: str | None = None,
    ) -> None:
        import os

        self._api_key = api_key or os.environ.get("OPENAI_API_KEY", "")
        self._timeout = timeout
        self._chat_url = (base_url.rstrip("/") + "/chat/completions") if base_url else self._OPENAI_CHAT_URL

    # ------------------------------------------------------------------
    # LLMProvider interface
    # ------------------------------------------------------------------

    @property
    def provider_name(self) -> str:
        return "openai"

    async def generate(self, request: LLMRequest) -> LLMResponse:
        """
        Send a chat completion request to OpenAI with timeout and retry.

        Retry policy:
            - Up to _MAX_RETRIES attempts total (including the first)
            - Retried on: 429 (rate limit) and 5xx (server errors)
            - Backoff: exponential — 1 s, 2 s, 4 s

        Structured output:
            - If request.response_schema is set, adds ``"response_format": {"type": "json_object"}``
              to the payload and parses + validates the returned JSON.

        Raises:
            LLMTimeoutError:    httpx.TimeoutException raised.
            LLMRateLimitError:  HTTP 429 after all retries exhausted.
            LLMUnavailableError: HTTP 5xx after all retries exhausted.
            LLMValidationError:  Response JSON failed Pydantic schema validation.
        """
        payload = self._build_payload(request)
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }

        last_error: Exception | None = None

        async with httpx.AsyncClient(timeout=self._timeout) as client:
            for attempt in range(1, _MAX_RETRIES + 1):
                try:
                    start_ns = time.monotonic_ns()
                    resp = await client.post(self._chat_url, json=payload, headers=headers)
                    latency_ms = (time.monotonic_ns() - start_ns) / 1_000_000

                    if resp.status_code == 200:
                        return self._parse_response(resp.json(), latency_ms, request)

                    if resp.status_code == 429:
                        last_error = LLMRateLimitError()
                    elif resp.status_code in _RETRYABLE_STATUS_CODES:
                        last_error = LLMUnavailableError(f"HTTP {resp.status_code}")
                    else:
                        # Non-retryable HTTP error (4xx except 429)
                        raise LLMUnavailableError(
                            f"HTTP {resp.status_code}: {resp.text[:200]}"
                        )

                except httpx.TimeoutException as exc:
                    last_error = LLMTimeoutError()

                # Backoff before next attempt (skip sleep on last attempt)
                if attempt < _MAX_RETRIES:
                    import asyncio
                    backoff = _BACKOFF_BASE_SECONDS * (2 ** (attempt - 1))
                    await asyncio.sleep(backoff)

        # All retries exhausted — raise the last recorded error
        raise last_error  # type: ignore[misc]

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _build_payload(self, request: LLMRequest) -> dict[str, Any]:
        """Convert an LLMRequest to the OpenAI API payload dict."""
        payload: dict[str, Any] = {
            "model": request.model,
            "messages": [{"role": m.role, "content": m.content} for m in request.messages],
            "temperature": request.temperature,
            "max_tokens": request.max_tokens,
        }

        if request.response_schema is not None:
            # Enable JSON mode — OpenAI guarantees a parseable JSON object
            payload["response_format"] = {"type": "json_object"}

        return payload

    def _parse_response(
        self,
        data: dict[str, Any],
        latency_ms: float,
        request: LLMRequest,
    ) -> LLMResponse:
        """
        Parse a raw OpenAI response dict into a typed LLMResponse.

        If request.response_schema is set, the content string is parsed as JSON
        and validated against the schema (raises LLMValidationError on failure).
        """
        choice = data["choices"][0]
        raw_content: str = choice["message"]["content"]
        usage: dict[str, int] = data.get("usage", {})

        # Validate structured output if a schema was requested
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
        Parse content as JSON and validate against schema.

        Raises:
            LLMValidationError: If JSON parse fails or Pydantic validation fails.
        """
        try:
            parsed = json.loads(content)
        except json.JSONDecodeError as exc:
            raise LLMValidationError(f"Response is not valid JSON: {exc}") from exc

        try:
            schema.model_validate(parsed)
        except Exception as exc:  # pydantic.ValidationError
            raise LLMValidationError(f"Schema validation failed: {exc}") from exc
