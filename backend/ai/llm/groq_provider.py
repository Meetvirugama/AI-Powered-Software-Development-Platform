"""
Groq LLM Provider — OpenAI-Compatible Low-Latency Inference with Key Rotation & Strict JSON Schemas.

Features:
    - Wraps Groq's high-speed inference endpoint using an OpenAI-compatible wire schema.
    - Automatic round-robin key rotation across free-tier keys to circumvent rate limits.
    - Model resolution mapping standard names (e.g. gpt-4o) to Groq equivalents.
    - Strict Structured Output (`json_schema` with `strict: True` and recursive `additionalProperties: False`)
      at the provider level (Issue 3), with automatic graceful fallback to `json_object` when needed.
    - Real latency measurement and connection pooling support.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
import copy
from itertools import cycle
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
    LLMResponseChunk,
    LLMTimeoutError,
    LLMToolCall,
    LLMToolRequest,
    LLMToolResponse,
    LLMUnavailableError,
    validate_structured_payload,
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
    "gemini-flash-lite-latest": "openai/gpt-oss-120b",
    "gemini-flash-latest": "openai/gpt-oss-120b",
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


def _enforce_strict_json_schema_node(node: Any) -> Any:
    """Recursively enforce `additionalProperties: False` and complete `required` lists for OpenAI/Groq strict json_schema."""
    if isinstance(node, dict):
        if "$ref" in node:
            return {"$ref": node["$ref"]}
        out = {k: _enforce_strict_json_schema_node(v) for k, v in node.items()}
        if out.get("type") == "object" or "properties" in out:
            out["type"] = "object"
            props = out.get("properties")
            if isinstance(props, dict):
                out["additionalProperties"] = False
                out["required"] = list(props.keys())
            else:
                out.setdefault("additionalProperties", False)
        return out
    if isinstance(node, list):
        return [_enforce_strict_json_schema_node(item) for item in node]
    return node


def build_strict_groq_json_schema(schema_cls: type[BaseModel]) -> dict[str, Any]:
    """Build an OpenAI/Groq provider-level `response_format` payload with `type: 'json_schema'` and `strict: True`."""
    raw_schema = copy.deepcopy(schema_cls.model_json_schema())
    strict_schema = _enforce_strict_json_schema_node(raw_schema)
    return {
        "type": "json_schema",
        "json_schema": {
            "name": schema_cls.__name__,
            "strict": True,
            "schema": strict_schema,
        },
    }


class GroqProvider(LLMProvider):
    """
    Concrete LLMProvider for Groq Cloud.
    """

    def __init__(
        self,
        api_keys: list[str] | None = None,
        timeout: float = _DEFAULT_TIMEOUT_SECONDS,
        model: str = _DEFAULT_MODEL,
        client: httpx.AsyncClient | None = None,
        concurrency_limit: int = 50,
        *,
        api_key: str | None = None,
    ) -> None:
        if api_key and not api_keys:
            api_keys = [api_key]
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
        self._client: httpx.AsyncClient | None = None
        self._semaphore = asyncio.Semaphore(concurrency_limit)

    @property
    def provider_name(self) -> str:
        return "groq"

    @property
    def default_model(self) -> str:
        return self._default_model

    @property
    def timeout(self) -> float:
        return self._timeout

    def _get_client(self) -> httpx.AsyncClient:
        if self._external_client is not None:
            return self._external_client
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(self._timeout, connect=10.0),
                limits=httpx.Limits(max_keepalive_connections=20, max_connections=50),
            )
        return self._client

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def generate(self, request: LLMRequest) -> LLMResponse:
        """Execute chat completion on Groq with key rotation, strict json_schema, and backoff."""
        resolved_model = self._resolve_model(request.model)
        payload = self._build_payload(request, resolved_model)

        last_error: LLMError | None = None

        async with self._semaphore:
            for attempt in range(1, _MAX_RETRIES + 1):
                api_key = self._next_key()
                client = self._get_client()

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

                        # If Groq constrained JSON schema / JSON decoding fails, fallback to json_object or unconstrained
                        if (
                            ("json" in str(err_body).lower() or "schema" in str(err_body).lower() or "response_format" in str(err_body).lower())
                            and "response_format" in payload
                        ):
                            logger.info("groq_retrying_without_response_format_constraint")
                            payload_copy = dict(payload)
                            payload_copy.pop("response_format", None)
                            retry_resp = await client.post(
                                _GROQ_CHAT_URL,
                                headers={
                                    "Authorization": f"Bearer {api_key}",
                                    "Content-Type": "application/json",
                                },
                                json=payload_copy,
                            )
                            if retry_resp.status_code == 200:
                                latency_ms = (time.monotonic_ns() - start_ns) / 1_000_000
                                return self._parse_response(
                                    retry_resp.json(),
                                    latency_ms=latency_ms,
                                    model=resolved_model,
                                    schema=request.response_schema,
                                )

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
        """Close persistent or external client if managed."""
        if self._client is not None and not self._client.is_closed:
            await self._client.aclose()
            self._client = None
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
        """Convert LLMRequest into OpenAI/Groq wire format with tools and strict json_schema support."""
        messages: list[dict[str, Any]] = []
        for m in request.messages:
            if m.role == "tool":
                messages.append({
                    "role": "tool",
                    "tool_call_id": m.tool_call_id or "",
                    "name": m.name or "tool",
                    "content": m.content,
                })
            elif m.role == "assistant":
                msg_dict: dict[str, Any] = {"role": "assistant"}
                if m.content:
                    msg_dict["content"] = m.content
                else:
                    msg_dict["content"] = None
                if m.tool_calls:
                    msg_dict["tool_calls"] = [
                        {
                            "id": tc.id,
                            "type": "function",
                            "function": {
                                "name": tc.name,
                                "arguments": json.dumps(tc.arguments) if isinstance(tc.arguments, dict) else str(tc.arguments),
                            },
                        }
                        for tc in m.tool_calls
                    ]
                messages.append(msg_dict)
            else:
                messages.append({"role": m.role, "content": m.content})

        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": request.temperature,
            "max_tokens": request.max_tokens,
        }

        if request.tools:
            payload["tools"] = [t.to_openai_dict() for t in request.tools]

        if request.tool_choice:
            payload["tool_choice"] = request.tool_choice

        # Strict JSON Schema vs JSON Object vs None
        # Caveat: Groq does not allow response_format combined with tools or streaming
        explicit_format = getattr(request, "response_format", None)
        schema_mode = getattr(request, "response_schema_mode", "json")

        if explicit_format is not None:
            payload["response_format"] = explicit_format
        elif not request.tools and schema_mode != "none" and request.response_schema is not None:
            if schema_mode in ("strict", "json"):
                try:
                    payload["response_format"] = build_strict_groq_json_schema(request.response_schema)
                except Exception:
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

        choice = choices[0]
        msg = choice.get("message", {})
        content = msg.get("content") or ""
        if not content and msg.get("reasoning"):
            content = msg.get("reasoning") or ""

        raw_tool_calls = msg.get("tool_calls", [])
        tool_calls: list[LLMToolCall] = []
        for rtc in raw_tool_calls:
            fn = rtc.get("function", {})
            fn_name = fn.get("name", "")
            raw_args = fn.get("arguments", "{}")
            if isinstance(raw_args, dict):
                parsed_args = raw_args
            else:
                try:
                    parsed_args = json.loads(raw_args)
                except (json.JSONDecodeError, TypeError):
                    parsed_args = {}
            tool_calls.append(
                LLMToolCall(
                    id=rtc.get("id", ""),
                    name=fn_name,
                    arguments=parsed_args,
                )
            )

        if not content and not tool_calls:
            raise LLMUnavailableError("Groq response message contained no content or tool calls.", provider=self.provider_name)

        usage = data.get("usage", {})
        finish_reason = choice.get("finish_reason")

        if schema is not None and not tool_calls:
            self._validate_structured_output(content, schema)

        return LLMResponse(
            content=content,
            model=model,
            input_tokens=usage.get("prompt_tokens", 0),
            output_tokens=usage.get("completion_tokens", 0),
            latency_ms=round(latency_ms, 2),
            tool_calls=tool_calls if tool_calls else None,
            finish_reason=finish_reason,
            provider=self.provider_name,
        )

    async def generate_stream(
        self, request: LLMRequest
    ) -> AsyncIterator[LLMResponseChunk]:
        """Stream tokens from Groq API via SSE."""
        resolved_model = self._resolve_model(request.model)
        payload = self._build_payload(request, resolved_model)
        payload["stream"] = True

        async with self._semaphore:
            for attempt in range(1, _MAX_RETRIES + 1):
                api_key = self._next_key()
                client = self._get_client()

                try:
                    async with client.stream(
                        "POST",
                        _GROQ_CHAT_URL,
                        headers={
                            "Authorization": f"Bearer {api_key}",
                            "Content-Type": "application/json",
                            "Accept": "text/event-stream",
                        },
                        json=payload,
                    ) as resp:
                        if resp.status_code != 200:
                            if resp.status_code == 429 and attempt < _MAX_RETRIES:
                                await asyncio.sleep(0.1)
                                continue
                            body = await resp.aread()
                            raise LLMUnavailableError(
                                f"Groq stream error (HTTP {resp.status_code}): {body.decode('utf-8', errors='replace')[:200]}",
                                status_code=resp.status_code,
                                provider=self.provider_name,
                            )

                        chunk_idx = 0
                        async for line in resp.aiter_lines():
                            line_str = line.strip()
                            if not line_str.startswith("data:"):
                                continue
                            raw_data = line_str.removeprefix("data:").strip()
                            if not raw_data or raw_data == "[DONE]":
                                break
                            try:
                                chunk_json = json.loads(raw_data)
                            except (json.JSONDecodeError, TypeError):
                                continue

                            choices = chunk_json.get("choices", [])
                            if not choices:
                                continue
                            ch = choices[0]
                            delta_obj = ch.get("delta", {})
                            delta_text = delta_obj.get("content") or ""
                            finish_reason = ch.get("finish_reason")
                            usage = chunk_json.get("usage", {})

                            yield LLMResponseChunk(
                                delta=delta_text,
                                index=chunk_idx,
                                finish_reason=finish_reason,
                                model=resolved_model,
                                provider=self.provider_name,
                                input_tokens=usage.get("prompt_tokens", 0),
                                output_tokens=usage.get("completion_tokens", 0),
                            )
                            chunk_idx += 1
                        return
                except (httpx.TimeoutException, httpx.RequestError) as exc:
                    if attempt >= _MAX_RETRIES:
                        raise LLMUnavailableError(f"Groq stream failed: {exc}", provider=self.provider_name) from exc
                    await asyncio.sleep(0.5)

    async def generate_with_tools(self, request: LLMToolRequest) -> LLMToolResponse:
        """Execute chat completion with tool-calling capabilities against Groq API."""
        llm_req = LLMRequest.create(
            model=request.model,
            messages=request.messages,
            tools=request.tools,
            tool_choice=request.tool_choice,
            temperature=request.temperature,
            max_tokens=request.max_tokens,
            allow_fallback=request.allow_fallback,
            request_id=request.request_id,
            estimated_tokens=request.estimated_tokens,
            feature=request.feature,
        )
        resp = await self.generate(llm_req)
        return LLMToolResponse(
            content=resp.content,
            tool_calls=resp.tool_calls or [],
            model=resp.model,
            input_tokens=resp.input_tokens,
            output_tokens=resp.output_tokens,
            latency_ms=resp.latency_ms,
            finish_reason=resp.finish_reason,
            provider=self.provider_name,
        )

    @staticmethod
    def _validate_structured_output(content: str, schema: type[BaseModel]) -> None:
        validate_structured_payload(content, schema, provider="groq")


__all__ = ["GroqProvider", "build_strict_groq_json_schema"]
