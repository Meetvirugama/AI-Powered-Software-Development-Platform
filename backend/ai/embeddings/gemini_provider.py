"""
Gemini Embedding Provider — Google Gemini REST API Client.

Responsibilities:
- Embeds text and code chunks using Google's `gemini-embedding-001` model.
- Supports specified output dimensionality (default: 768 to match pgvector schema).
- Supports official Gemini taskType values (`RETRIEVAL_DOCUMENT` for corpus indexing,
  `CODE_RETRIEVAL_QUERY` for code search queries) and EmbeddingProfile v2.
- Automatic round-robin key rotation across free-tier API keys on rate-limits (HTTP 429).
- Translates Google API errors into structured `EmbeddingError` hierarchy.
- Connection pooling via shared or managed `httpx.AsyncClient`.
- Security (W2-S8): Sends API key via `x-goog-api-key` request header instead of URL query string.
"""

from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import Sequence
from itertools import cycle
from typing import Any

import httpx

from .client import (
    AuthenticationError,
    EmbeddingError,
    EmbeddingProfile,
    EmbeddingProvider,
    GeminiTaskType,
    InvalidRequestError,
    ProviderUnavailableError,
    RateLimitError,
)

logger = logging.getLogger(__name__)

_DEFAULT_MODEL = "models/gemini-embedding-001"
_DEFAULT_DIMENSIONS = 768
_DEFAULT_TIMEOUT_SECONDS = 30.0
_MAX_RETRIES = 3
_BACKOFF_BASE_SECONDS = 1.0
_RETRYABLE_STATUS_CODES: frozenset[int] = frozenset({429, 500, 502, 503, 504})
_GEMINI_API_BASE = "https://generativelanguage.googleapis.com/v1beta"


def _redact_key(text: str, key: str) -> str:
    if not text or not key:
        return text
    return text.replace(key, "[REDACTED]")


def _normalize_task_type(task_type: GeminiTaskType | str | None) -> str | None:
    if task_type is None:
        return None
    if isinstance(task_type, GeminiTaskType):
        return task_type.value
    val = str(task_type).strip().upper()
    if not val:
        return None
    # Validate against official GeminiTaskType enum values
    valid_values = {item.value for item in GeminiTaskType}
    if val not in valid_values:
        raise ValueError(
            f"Unsupported Gemini embedding taskType {task_type!r}. "
            f"Must be one of: {sorted(valid_values)}"
        )
    return val


class GeminiEmbeddingProvider(EmbeddingProvider):
    """
    Concrete EmbeddingProvider for Google Gemini Embeddings API.

    Args:
        api_keys: List of Gemini API keys. Falls back to `GEMINI_API_KEYS` or `GEMINI_API_KEY`.
        model: Model identifier (default: `models/gemini-embedding-001`).
        dimensions: Expected output dimensionality (default: 768).
        timeout: Per-request timeout in seconds (default: 30.0).
        client: Optional shared `httpx.AsyncClient` for connection pooling.
        max_retries: Maximum retry attempts per sub-batch (default: 3).
        profile_version: Profile version ('v1' or 'v2'; default 'v1' for legacy callers, 'v2' when configured).
        task_type: Optional explicit default `taskType` for generic `embed`/`embed_batch` calls.
        document_task_type: Verified Gemini taskType for indexing documents (`RETRIEVAL_DOCUMENT`).
        query_task_type: Verified Gemini taskType for code search queries (`CODE_RETRIEVAL_QUERY`).
    """

    def __init__(
        self,
        api_keys: Sequence[str] | None = None,
        model: str = _DEFAULT_MODEL,
        dimensions: int = _DEFAULT_DIMENSIONS,
        timeout: float = _DEFAULT_TIMEOUT_SECONDS,
        client: httpx.AsyncClient | None = None,
        max_retries: int = _MAX_RETRIES,
        profile_version: str = "v1",
        task_type: GeminiTaskType | str | None = None,
        document_task_type: GeminiTaskType | str = GeminiTaskType.RETRIEVAL_DOCUMENT,
        query_task_type: GeminiTaskType | str = GeminiTaskType.CODE_RETRIEVAL_QUERY,
    ) -> None:
        if api_keys:
            valid_keys = [k.strip() for k in api_keys if k and k.strip()]
        else:
            keys_str = os.getenv("GEMINI_API_KEYS", "") or os.getenv("GEMINI_API_KEY", "")
            valid_keys = [k.strip() for k in keys_str.split(",") if k.strip()]

        if not valid_keys:
            raise ValueError("GeminiEmbeddingProvider requires at least one non-empty API key.")

        self._api_keys = valid_keys
        self._key_cycle = cycle(self._api_keys)
        self._model = model if model.startswith("models/") else f"models/{model}"
        self._dimensions = dimensions
        self._timeout = timeout
        self._external_client = client
        self._client: httpx.AsyncClient | None = None
        self._max_retries = max_retries
        self._profile_version = profile_version
        self._task_type = _normalize_task_type(task_type)
        self._document_task_type = (
            _normalize_task_type(document_task_type) or GeminiTaskType.RETRIEVAL_DOCUMENT.value
        )
        self._query_task_type = (
            _normalize_task_type(query_task_type) or GeminiTaskType.CODE_RETRIEVAL_QUERY.value
        )

    @classmethod
    def v2(
        cls,
        api_keys: Sequence[str] | None = None,
        model: str = _DEFAULT_MODEL,
        dimensions: int = _DEFAULT_DIMENSIONS,
        timeout: float = _DEFAULT_TIMEOUT_SECONDS,
        client: httpx.AsyncClient | None = None,
        max_retries: int = _MAX_RETRIES,
    ) -> GeminiEmbeddingProvider:
        """Factory constructing a v2 GeminiEmbeddingProvider with verified task types."""
        return cls(
            api_keys=api_keys,
            model=model,
            dimensions=dimensions,
            timeout=timeout,
            client=client,
            max_retries=max_retries,
            profile_version="v2",
            document_task_type=GeminiTaskType.RETRIEVAL_DOCUMENT,
            query_task_type=GeminiTaskType.CODE_RETRIEVAL_QUERY,
        )

    @property
    def embedding_dimensions(self) -> int:
        return self._dimensions

    @property
    def provider_name(self) -> str:
        return "gemini"

    @property
    def model_name(self) -> str:
        return self._model

    @property
    def document_task_type(self) -> str:
        return self._document_task_type

    @property
    def query_task_type(self) -> str:
        return self._query_task_type

    @property
    def profile(self) -> EmbeddingProfile:
        if self._profile_version == "v2":
            return EmbeddingProfile.v2_gemini(
                model=self._model,
                dimensions=self._dimensions,
                document_task_type=self._document_task_type,
                query_task_type=self._query_task_type,
                active_task_type=self._task_type or self._document_task_type,
            )
        return EmbeddingProfile(
            provider=self.provider_name,
            model=self._model,
            dimensions=self._dimensions,
            normalization=True,
            distance_metric="cosine",
            profile_version=self._profile_version,
            document_task_type=self._task_type,
            query_task_type=self._task_type,
            active_task_type=self._task_type,
        )

    def _get_client(self) -> httpx.AsyncClient:
        if self._external_client is not None:
            return self._external_client
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(self._timeout, connect=10.0),
                limits=httpx.Limits(max_keepalive_connections=20, max_connections=50),
            )
        return self._client

    def _next_key(self) -> str:
        return next(self._key_cycle)

    async def embed(self, text: str, *, task_type: GeminiTaskType | str | None = None) -> list[float]:
        """Embed a single text snippet."""
        results = await self.embed_batch([text], task_type=task_type)
        if not results:
            raise EmbeddingError("Gemini returned empty embeddings for text.", provider=self.provider_name)
        return results[0]

    async def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        """Embed repository document/code chunks with taskType=RETRIEVAL_DOCUMENT."""
        return await self.embed_batch(texts, task_type=self._document_task_type)

    async def embed_query(self, text: str) -> list[float]:
        """Embed a search query with taskType=CODE_RETRIEVAL_QUERY."""
        results = await self.embed_batch([text], task_type=self._query_task_type)
        if not results:
            raise EmbeddingError("Gemini returned empty embeddings for query.", provider=self.provider_name)
        return results[0]

    async def embed_batch(
        self,
        texts: Sequence[str],
        *,
        task_type: GeminiTaskType | str | None = None,
    ) -> list[list[float]]:
        """
        Embed a sequence of texts using Gemini's batchEmbedContents endpoint.

        Args:
            texts: List of strings to embed.
            task_type: Optional taskType override for this batch.

        Returns:
            List of float vectors, length matching `texts`, each with length `embedding_dimensions`.
        """
        if not texts:
            return []

        resolved_task_type = _normalize_task_type(task_type) or self._task_type
        if resolved_task_type is None and self._profile_version == "v2":
            resolved_task_type = self._document_task_type

        # Gemini batchEmbedContents endpoint handles up to 100 per call
        text_list = list(texts)
        if len(text_list) > 100:
            results: list[list[float]] = []
            for i in range(0, len(text_list), 100):
                chunk = text_list[i : i + 100]
                chunk_embeddings = await self._embed_batch_direct(chunk, task_type=resolved_task_type)
                results.extend(chunk_embeddings)
            return results

        return await self._embed_batch_direct(text_list, task_type=resolved_task_type)

    async def _embed_batch_direct(
        self,
        texts: list[str],
        *,
        task_type: str | None = None,
    ) -> list[list[float]]:
        """Embed up to 100 texts in a single batchEmbedContents call with retry & key rotation."""
        requests_payload: list[dict[str, Any]] = []
        for t in texts:
            req_item: dict[str, Any] = {
                "model": self._model,
                "content": {"parts": [{"text": t}]},
                "outputDimensionality": self._dimensions,
            }
            if task_type:
                req_item["taskType"] = task_type
            requests_payload.append(req_item)

        payload = {"requests": requests_payload}

        client = self._get_client()
        last_error: EmbeddingError | None = None
        max_attempts = self._max_retries

        for attempt in range(1, max_attempts + 1):
            api_key = self._next_key()
            url = f"{_GEMINI_API_BASE}/{self._model}:batchEmbedContents"
            headers = {"x-goog-api-key": api_key}

            try:
                response = await client.post(url, json=payload, headers=headers)

                if response.status_code == 200:
                    data = response.json()
                    embeddings_raw = data.get("embeddings", [])
                    if len(embeddings_raw) != len(texts):
                        raise EmbeddingError(
                            f"Gemini returned {len(embeddings_raw)} embeddings for {len(texts)} texts.",
                            provider=self.provider_name,
                        )
                    return [item["values"] for item in embeddings_raw]

                if response.status_code == 429:
                    retry_after: float | None = None
                    ra_hdr = response.headers.get("Retry-After") if hasattr(response, "headers") else None
                    if ra_hdr:
                        try:
                            retry_after = float(ra_hdr)
                        except (ValueError, TypeError):
                            retry_after = None
                    last_error = RateLimitError(
                        "Gemini embedding rate limit exceeded.",
                        retry_after=retry_after,
                        provider=self.provider_name,
                    )
                    logger.warning(
                        "gemini_embedding_rate_limit_rotating_key",
                        extra={"attempt": attempt, "key_masked": f"{api_key[:4]}...{api_key[-4:]}"},
                    )
                    if retry_after and retry_after > 0:
                        await asyncio.sleep(retry_after)
                    elif attempt >= len(self._api_keys):
                        await asyncio.sleep(min(1.5 * (attempt // len(self._api_keys) + 1), 8.0))
                    else:
                        await asyncio.sleep(0.3)
                    continue

                if response.status_code in {401, 403}:
                    raise AuthenticationError(
                        f"Gemini authentication failed (HTTP {response.status_code}): {_redact_key(response.text[:200], api_key)}",
                        status_code=response.status_code,
                        provider=self.provider_name,
                    )

                if response.status_code == 400:
                    raise InvalidRequestError(
                        f"Gemini 400 Bad Request: {_redact_key(response.text[:200], api_key)}",
                        status_code=400,
                        provider=self.provider_name,
                    )

                if response.status_code in _RETRYABLE_STATUS_CODES:
                    last_error = ProviderUnavailableError(
                        f"Gemini embedding temporary failure (HTTP {response.status_code}): {_redact_key(response.text[:200], api_key)}",
                        status_code=response.status_code,
                        provider=self.provider_name,
                    )

            except (StopIteration, StopAsyncIteration):
                break
            except (httpx.TimeoutException, httpx.NetworkError) as exc:
                safe_err = _redact_key(str(exc), api_key)
                last_error = ProviderUnavailableError(
                    f"Gemini network or timeout error: {safe_err}",
                    provider=self.provider_name,
                )

            if attempt < max_attempts:
                wait_time = min(_BACKOFF_BASE_SECONDS * (1.5 ** (attempt - 1)), 8.0)
                logger.info(
                    "gemini_embedding_retry_backoff",
                    extra={"attempt": attempt, "wait_seconds": wait_time, "error": str(last_error)},
                )
                await asyncio.sleep(wait_time)

        if last_error is not None:
            raise last_error

        raise ProviderUnavailableError(
            f"Gemini embedding unavailable after {max_attempts} attempts.",
            provider=self.provider_name,
        )

    async def aclose(self) -> None:
        """Release underlying HTTP client if locally owned."""
        if self._client is not None and not self._client.is_closed:
            await self._client.aclose()
