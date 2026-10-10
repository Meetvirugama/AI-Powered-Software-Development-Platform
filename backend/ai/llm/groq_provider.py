"""
Groq LLM Provider — uses Groq's OpenAI-compatible API with free-tier keys.
This allows using the same LLMGateway interface with Groq instead of OpenAI.
"""

from __future__ import annotations

import json
import os
import time
from itertools import cycle
from typing import Any

import httpx

from .provider import LLMProvider
from .schemas import (
    LLMRequest,
    LLMResponse,
    LLMRateLimitError,
    LLMTimeoutError,
    LLMUnavailableError,
    LLMValidationError,
)

_DEFAULT_TIMEOUT_SECONDS: float = 30.0
_MAX_RETRIES: int = 3
_BACKOFF_BASE_SECONDS: float = 1.0
_GROQ_CHAT_URL = "https://api.groq.com/openai/v1/chat/completions"
_RETRYABLE_STATUS_CODES: frozenset[int] = frozenset({429, 500, 502, 503, 504})

# Default model — llama3-70b is the best free Groq model for code tasks
_DEFAULT_MODEL = "llama3-70b-8192"

# Map OpenAI model names → Groq equivalents
_MODEL_MAP = {
    "gpt-4o": "llama3-70b-8192",
    "gpt-4": "llama3-70b-8192",
    "gpt-3.5-turbo": "llama3-8b-8192",
    "llama3-70b-8192": "llama3-70b-8192",
    "llama3-8b-8192": "llama3-8b-8192",
    "mixtral-8x7b-32768": "mixtral-8x7b-32768",
}


class GroqProvider(LLMProvider):
    """
    Concrete LLMProvider for the Groq API (OpenAI-compatible).

    Supports multiple API keys with round-robin rotation to spread
    across rate limits on the free tier.

    Args:
        api_keys: List of Groq API keys. If not provided, reads from
                  GROQ_API_KEYS (comma-separated) or GROQ_API_KEY env vars.
        timeout:  Per-request timeout in seconds (default 30).
        model:    Default model override (default: llama3-70b-8192).
    """

    @property
    def provider_name(self) -> str:
        return "groq"

    def __init__(
        self,
        api_keys: list[str] | None = None,
        timeout: float = _DEFAULT_TIMEOUT_SECONDS,
        model: str = _DEFAULT_MODEL,
    ) -> None:
        if api_keys:
            self._api_keys = api_keys
        else:
            # Read from env: comma-separated list or single key
            keys_str = os.getenv("GROQ_API_KEYS", "") or os.getenv("GROQ_API_KEY", "")
            self._api_keys = [k.strip() for k in keys_str.split(",") if k.strip()]
        if not self._api_keys:
            raise ValueError("No Groq API keys configured. Set GROQ_API_KEYS env var.")
        self._key_cycle = cycle(self._api_keys)
        self._timeout = timeout
        self._default_model = model

    def _next_key(self) -> str:
        return next(self._key_cycle)

    def _resolve_model(self, requested: str) -> str:
        return _MODEL_MAP.get(requested, self._default_model)

    async def generate(self, request: LLMRequest) -> LLMResponse:
        model = self._resolve_model(request.model)
        messages = [{"role": m.role, "content": m.content} for m in request.messages]

        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": 0.1,
        }

        # Enable JSON mode if a response schema is requested
        if request.response_schema is not None:
            payload["response_format"] = {"type": "json_object"}

        last_exc: Exception | None = None

        for attempt in range(_MAX_RETRIES):
            api_key = self._next_key()
            try:
                async with httpx.AsyncClient(timeout=self._timeout) as client:
                    resp = await client.post(
                        _GROQ_CHAT_URL,
                        headers={
                            "Authorization": f"Bearer {api_key}",
                            "Content-Type": "application/json",
                        },
                        json=payload,
                    )
                    if resp.status_code in _RETRYABLE_STATUS_CODES:
                        if resp.status_code == 429:
                            raise LLMRateLimitError("Groq rate limit exceeded.")
                        wait = _BACKOFF_BASE_SECONDS * (2 ** attempt)
                        import asyncio
                        await asyncio.sleep(wait)
                        last_exc = LLMUnavailableError(f"Groq returned {resp.status_code}")
                        continue
                    resp.raise_for_status()
                    data = resp.json()
                    choice = data["choices"][0]
                    content = choice["message"]["content"]
                    usage = data.get("usage", {})
                    return LLMResponse(
                        content=content,
                        model=model,
                        input_tokens=usage.get("prompt_tokens", 0),
                        output_tokens=usage.get("completion_tokens", 0),
                        latency_ms=0.0,
                    )
            except LLMRateLimitError:
                # Try next key immediately on rate limit
                last_exc = LLMRateLimitError("Groq rate limit exceeded on all keys.")
                continue
            except httpx.TimeoutException as exc:
                last_exc = LLMTimeoutError(str(exc))
                continue
            except httpx.HTTPError as exc:
                last_exc = LLMUnavailableError(str(exc))
                continue

        if isinstance(last_exc, LLMTimeoutError):
            raise last_exc
        raise LLMUnavailableError(f"Groq unavailable after {_MAX_RETRIES} attempts.") from last_exc
