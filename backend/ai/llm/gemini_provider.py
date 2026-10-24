"""
Gemini LLM Provider — Google Gemini REST API Client.

Features:
- Direct, resilient HTTP client over Google's Generative Language REST API.
- Converts standardized ``LLMRequest`` to Gemini's ``system_instruction`` and ``contents`` format.
- Round-robin key rotation across free-tier keys on rate-limits (HTTP 429).
- Normalizes output to ``LLMResponse`` with latency, token usage, and finish reasons.
- Translates API errors into structured ``LLMError`` hierarchy with API key redaction.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from itertools import cycle
from typing import Any, Sequence

import httpx

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
    Message,
)

logger = logging.getLogger(__name__)

_GEMINI_API_BASE = "https://generativelanguage.googleapis.com/v1beta/models"
_RETRYABLE_STATUS_CODES: frozenset[int] = frozenset({429, 500, 502, 503, 504})


def _redact_key(text: str, key: str) -> str:
    if not text or not key:
        return text
    return text.replace(key, "[REDACTED]")


class GeminiProvider(LLMProvider):
    """
    Inference adapter for Google Gemini models via official REST API.
    """

    def __init__(
        self,
        api_keys: Sequence[str],
        default_model: str = "gemini-flash-latest",
        timeout_seconds: float = 30.0,
        max_retries: int = 3,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        valid_keys = [k.strip() for k in api_keys if k and k.strip()]
        if not valid_keys:
            raise ValueError("GeminiProvider requires at least one non-empty API key.")

        self._api_keys = valid_keys
        self._key_cycle = cycle(self._api_keys)
        self._default_model = default_model
        self._timeout_seconds = timeout_seconds
        self._max_retries = max_retries
        self._external_client = client
        self._client: httpx.AsyncClient | None = None

    @property
    def provider_name(self) -> str:
        return "gemini"

    @property
    def default_model(self) -> str:
        return self._default_model

    def _get_client(self) -> httpx.AsyncClient:
        if self._external_client is not None:
            return self._external_client
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(self._timeout_seconds, connect=10.0),
                limits=httpx.Limits(max_keepalive_connections=20, max_connections=50),
            )
        return self._client

    def _next_key(self) -> str:
        return next(self._key_cycle)

    def _build_payload(self, request: LLMRequest) -> tuple[dict[str, Any], str]:
        """Convert LLMRequest into Gemini JSON payload."""
        system_instructions: list[str] = []
        contents: list[dict[str, Any]] = []

        for msg in request.messages:
            if msg.role == "system":
                system_instructions.append(msg.content)
            elif msg.role == "user":
                contents.append({"role": "user", "parts": [{"text": msg.content}]})
            elif msg.role == "assistant":
                contents.append({"role": "model", "parts": [{"text": msg.content}]})

        # Default model resolution (including legacy gpt-* fallback safety)
        requested_model = (request.model or "").strip()
        if (
            not requested_model
            or requested_model == "default"
            or requested_model.startswith("gpt-")
            or requested_model.startswith("openai/")
        ):
            model_name = self._default_model
        else:
            model_name = requested_model
        # Strip models/ prefix if present
        if model_name.startswith("models/"):
            model_name = model_name[len("models/"):]
        if model_name in ("gemini-flash-lite-latest", "gemini-1.5-flash", "gemini-2.0-flash"):
            model_name = "gemini-flash-latest"

        payload: dict[str, Any] = {"contents": contents}

        if system_instructions:
            payload["system_instruction"] = {
                "parts": [{"text": "\n\n".join(system_instructions)}]
            }

        generation_config: dict[str, Any] = {}
        if request.temperature is not None:
            generation_config["temperature"] = request.temperature
        if request.max_tokens is not None:
            generation_config["maxOutputTokens"] = request.max_tokens
        if getattr(request, "response_schema", None) is not None or getattr(request, "response_format", None):
            generation_config["responseMimeType"] = "application/json"

        if generation_config:
            payload["generationConfig"] = generation_config

        return payload, model_name

    async def generate(self, request: LLMRequest) -> LLMResponse:
        """Execute chat completion against Gemini API with retry & rotation."""
        payload, model = self._build_payload(request)
        client = self._get_client()

        last_error: Exception | None = None
        start_time = time.monotonic()

        for attempt in range(self._max_retries):
            current_key = self._next_key()
            url = f"{_GEMINI_API_BASE}/{model}:generateContent?key={current_key}"

            try:
                response = await client.post(url, json=payload)

                if response.status_code == 200:
                    data = response.json()
                    latency_ms = (time.monotonic() - start_time) * 1000.0

                    candidates = data.get("candidates", [])
                    if not candidates:
                        raise LLMValidationError(
                            f"Gemini returned 0 candidates: {data}",
                            provider=self.provider_name,
                        )

                    candidate = candidates[0]
                    content_parts = candidate.get("content", {}).get("parts", [])
                    content_text = "".join(p.get("text", "") for p in content_parts)

                    usage = data.get("usageMetadata", {})
                    input_tokens = usage.get("promptTokenCount", 0)
                    output_tokens = usage.get("candidatesTokenCount", 0)

                    # Validate JSON schema if required
                    if request.response_schema is not None:
                        raw = content_text.strip()
                        if raw.startswith("```"):
                            lines = raw.splitlines()
                            if len(lines) >= 2 and lines[0].startswith("```"):
                                raw = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
                        if "{" in raw and "}" in raw:
                            start = raw.find("{")
                            end = raw.rfind("}") + 1
                            raw = raw[start:end]

                        try:
                            parsed_json = json.loads(raw)
                            if hasattr(request.response_schema, "model_validate"):
                                request.response_schema.model_validate(parsed_json)
                        except Exception as val_exc:
                            raise LLMValidationError(
                                f"Structured output schema validation failed: {val_exc}",
                                provider=self.provider_name,
                                raw_response=content_text,
                            ) from val_exc

                    return LLMResponse(
                        content=content_text,
                        model=model,
                        input_tokens=input_tokens,
                        output_tokens=output_tokens,
                        latency_ms=round(latency_ms, 2),
                    )

                if response.status_code in (401, 403):
                    error_msg = _redact_key(response.text, current_key)
                    logger.error("gemini_auth_failed", extra={"status": response.status_code, "body": error_msg[:200]})
                    raise LLMAuthenticationError(
                        f"Gemini authentication failed (HTTP {response.status_code})",
                        status_code=response.status_code,
                        provider=self.provider_name,
                    )

                if response.status_code == 429:
                    logger.warning("gemini_rate_limited", extra={"attempt": attempt + 1})
                    last_error = LLMRateLimitError(
                        "Gemini rate limit exceeded (HTTP 429)",
                        provider=self.provider_name,
                    )
                    await asyncio.sleep(0.1)
                    continue

                if response.status_code in _RETRYABLE_STATUS_CODES:
                    safe_body = _redact_key(response.text[:200], current_key)
                    logger.warning("gemini_transient_error", extra={"status": response.status_code, "attempt": attempt + 1})
                    last_error = LLMUnavailableError(
                        f"Gemini service error (HTTP {response.status_code}): {safe_body}",
                        status_code=response.status_code,
                        provider=self.provider_name,
                    )
                    await asyncio.sleep(1.0 * (attempt + 1))
                    continue

                # Non-retryable error
                safe_body = _redact_key(response.text[:300], current_key)
                raise LLMError(
                    f"Gemini API error (HTTP {response.status_code}): {safe_body}",
                    status_code=response.status_code,
                    provider=self.provider_name,
                )

            except (httpx.TimeoutException, httpx.ConnectTimeout) as exc:
                safe_err = _redact_key(str(exc), current_key)
                last_error = LLMTimeoutError(f"Gemini request timed out: {safe_err}", provider=self.provider_name)
                logger.warning("gemini_timeout", extra={"attempt": attempt + 1, "error": safe_err})
                await asyncio.sleep(0.5)
            except (httpx.NetworkError, httpx.TransportError) as exc:
                safe_err = _redact_key(str(exc), current_key)
                last_error = LLMUnavailableError(f"Gemini network error: {safe_err}", provider=self.provider_name)
                logger.warning("gemini_network_error", extra={"attempt": attempt + 1, "error": safe_err})
                await asyncio.sleep(0.5)

        if isinstance(last_error, LLMError):
            raise last_error
        raise LLMUnavailableError(f"Gemini failed after {self._max_retries} attempts.", provider=self.provider_name)

    async def aclose(self) -> None:
        if self._client is not None and not self._client.is_closed:
            await self._client.aclose()
            self._client = None
