"""
Gemini Embedding Provider — Google Gemini REST API Client.

Responsibilities:
- Embeds text and code chunks using Google's `gemini-embedding-001` model.
- Supports specified output dimensionality (default: 768 to match pgvector schema).
- Automatic round-robin key rotation across free-tier API keys on rate-limits (HTTP 429).
- Translates Google API errors into structured `EmbeddingError` hierarchy.
- Connection pooling via shared or managed `httpx.AsyncClient`.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from collections.abc import Sequence
from itertools import cycle
from typing import Any

import httpx

from .client import (
    AuthenticationError,
    EmbeddingError,
    EmbeddingProvider,
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


class GeminiEmbeddingProvider(EmbeddingProvider):
    """
    Concrete EmbeddingProvider for Google Gemini Embeddings API.

    Args:
        api_keys: List of Gemini API keys. Falls back to `GEMINI_API_KEYS` or `GEMINI_API_KEY`.
        model: Model identifier (default: `models/gemini-embedding-001`).
        dimensions: Expected output dimensionality (default: 768).
        timeout: Per-request timeout in seconds (default: 30.0).
        client: Optional shared `httpx.AsyncClient` for connection pooling.
    """

    def __init__(
        self,
        api_keys: Sequence[str] | None = None,
        model: str = _DEFAULT_MODEL,
        dimensions: int = _DEFAULT_DIMENSIONS,
        timeout: float = _DEFAULT_TIMEOUT_SECONDS,
        client: httpx.AsyncClient | None = None,
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

    @property
    def embedding_dimensions(self) -> int:
        return self._dimensions

    @property
    def provider_name(self) -> str:
        return "gemini"

    @property
    def model_name(self) -> str:
        return self._model

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

    async def embed(self, text: str) -> list[float]:
        """Embed a single text snippet."""
        results = await self.embed_batch([text])
        if not results:
            raise EmbeddingError("Gemini returned empty embeddings for text.", provider=self.provider_name)
        return results[0]

    async def embed_batch(self, texts: Sequence[str]) -> list[list[float]]:
        """
        Embed a sequence of texts using Gemini's batchEmbedContents endpoint.

        Args:
            texts: List of strings to embed.

        Returns:
            List of float vectors, length matching `texts`, each with length `embedding_dimensions`.
        """
        if not texts:
            return []

        # Gemini batchEmbedContents endpoint handles up to 100 per call
        # Chunk if texts > 100
        text_list = list(texts)
        if len(text_list) > 100:
            results: list[list[float]] = []
            for i in range(0, len(text_list), 100):
                chunk = text_list[i : i + 100]
                chunk_embeddings = await self._embed_batch_direct(chunk)
                results.extend(chunk_embeddings)
            return results

        return await self._embed_batch_direct(text_list)

    async def _embed_batch_direct(self, texts: list[str]) -> list[list[float]]:
        """Embed up to 100 texts in a single batchEmbedContents call with retry & key rotation."""
        payload = {
            "requests": [
                {
                    "model": self._model,
                    "content": {"parts": [{"text": t}]},
                    "outputDimensionality": self._dimensions,
                }
                for t in texts
            ]
        }

        client = self._get_client()
        last_error: EmbeddingError | None = None

        for attempt in range(1, _MAX_RETRIES + 1):
            api_key = self._next_key()
            url = f"{_GEMINI_API_BASE}/{self._model}:batchEmbedContents?key={api_key}"

            try:
                response = await client.post(url, json=payload)

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
                    else:
                        await asyncio.sleep(0.1)
                    continue

                if response.status_code in {401, 403}:
                    raise AuthenticationError(
                        f"Gemini authentication failed (HTTP {response.status_code}): {response.text[:200]}",
                        status_code=response.status_code,
                        provider=self.provider_name,
                    )

                if response.status_code == 400:
                    raise InvalidRequestError(
                        f"Gemini 400 Bad Request: {response.text[:200]}",
                        status_code=400,
                        provider=self.provider_name,
                    )

                if response.status_code in _RETRYABLE_STATUS_CODES:
                    last_error = ProviderUnavailableError(
                        f"Gemini embedding temporary failure (HTTP {response.status_code}): {response.text[:200]}",
                        status_code=response.status_code,
                        provider=self.provider_name,
                    )

            except (httpx.TimeoutException, httpx.NetworkError) as exc:
                last_error = ProviderUnavailableError(
                    f"Gemini network or timeout error: {exc}",
                    provider=self.provider_name,
                )

            # Backoff before next attempt
            if attempt < _MAX_RETRIES:
                wait_time = _BACKOFF_BASE_SECONDS * (2 ** (attempt - 1))
                logger.info(
                    "gemini_embedding_retry_backoff",
                    extra={"attempt": attempt, "wait_seconds": wait_time, "error": str(last_error)},
                )
                await asyncio.sleep(wait_time)

        if last_error is not None:
            raise last_error

        raise ProviderUnavailableError(
            f"Gemini embedding unavailable after {_MAX_RETRIES} attempts.",
            provider=self.provider_name,
        )

    async def aclose(self) -> None:
        """Release underlying HTTP client if locally owned."""
        if self._client is not None and not self._client.is_closed:
            await self._client.aclose()
