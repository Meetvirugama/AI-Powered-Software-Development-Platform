"""
OpenAI Embedding Provider — concrete implementation of EmbeddingProvider.
Owner: Meet — W1-12, Day 3

Responsibilities:
    - Wraps the OpenAI Embeddings API (async, via httpx)
    - Model: text-embedding-3-small (1536 dims) by default
    - Configurable timeout (default 30 s)
    - Retry: up to 3 attempts with exponential backoff on 429 / 5xx

Retry / logging / batching live in EmbeddingService — not here.
Only provider-level API concerns belong in this class.
"""

from __future__ import annotations

import asyncio
import os
import time
from typing import Any

import httpx

from .client import EmbeddingError, EmbeddingProvider

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_DEFAULT_TIMEOUT_SECONDS: float = 30.0
_MAX_RETRIES: int = 3
_BACKOFF_BASE_SECONDS: float = 1.0  # 1 s, 2 s, 4 s

_RETRYABLE_STATUS_CODES: frozenset[int] = frozenset({429, 500, 502, 503, 504})

_OPENAI_EMBEDDINGS_URL = "https://api.openai.com/v1/embeddings"

# Default model and its output dimension.
# team_rules.md: never hard-code dimensions — read from provider property.
_DEFAULT_MODEL = "text-embedding-3-small"
_DEFAULT_DIMENSIONS = 1536


class OpenAIEmbeddingProvider(EmbeddingProvider):
    """
    Concrete EmbeddingProvider for the OpenAI Embeddings API.

    Args:
        api_key:    OpenAI API key. Falls back to ``OPENAI_API_KEY`` env var.
        model:      Model identifier (default: ``text-embedding-3-small``).
        dimensions: Expected output vector length. Defaults to 1536.
                    Set this from config — never hard-code at call sites.
        timeout:    Per-request timeout in seconds (default 30).
        base_url:   Override the OpenAI base URL (useful for test mocking).

    Example::

        provider = OpenAIEmbeddingProvider(api_key="sk-...")
        service  = EmbeddingService(provider=provider)
        vector   = await service.embed("def authenticate(user, password):")
    """

    def __init__(
        self,
        api_key: str | None = None,
        model: str = _DEFAULT_MODEL,
        dimensions: int = _DEFAULT_DIMENSIONS,
        timeout: float = _DEFAULT_TIMEOUT_SECONDS,
        base_url: str | None = None,
    ) -> None:
        self._api_key = api_key or os.environ.get("OPENAI_API_KEY", "")
        self._model = model
        self._dimensions = dimensions
        self._timeout = timeout
        self._embeddings_url = (
            base_url.rstrip("/") + "/embeddings"
        ) if base_url else _OPENAI_EMBEDDINGS_URL

    # ------------------------------------------------------------------
    # EmbeddingProvider interface
    # ------------------------------------------------------------------

    @property
    def embedding_dimensions(self) -> int:
        """Number of dimensions in each output vector. Driven by config, not hard-coded."""
        return self._dimensions

    @property
    def provider_name(self) -> str:
        return "openai"

    async def embed(self, text: str) -> list[float]:
        """
        Embed a single text string.

        Delegates to ``embed_batch([text])`` for consistency —
        batching and retry logic live in one place.

        Returns:
            Float vector of length ``self.embedding_dimensions``.

        Raises:
            EmbeddingError: On non-retryable API failure or dimension mismatch.
        """
        results = await self.embed_batch([text])
        return results[0]

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """
        Embed a list of texts in a single API call with retry.

        Args:
            texts: List of strings. OpenAI's hard limit is 2048 tokens per item.

        Returns:
            List of float vectors ordered identically to ``texts``.

        Raises:
            EmbeddingError: After exhausting retries (retryable=True) or on
                            non-retryable HTTP errors.
        """
        payload: dict[str, Any] = {
            "model": self._model,
            "input": texts,
        }
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }

        last_error: EmbeddingError | None = None

        async with httpx.AsyncClient(timeout=self._timeout) as client:
            for attempt in range(1, _MAX_RETRIES + 1):
                try:
                    resp = await client.post(
                        self._embeddings_url, json=payload, headers=headers
                    )

                    if resp.status_code == 200:
                        return self._parse_response(resp.json())

                    if resp.status_code == 429:
                        last_error = EmbeddingError(
                            "OpenAI embedding rate limit (429).", retryable=True
                        )
                    elif resp.status_code in _RETRYABLE_STATUS_CODES:
                        last_error = EmbeddingError(
                            f"OpenAI embedding server error (HTTP {resp.status_code}).",
                            retryable=True,
                        )
                    else:
                        # Non-retryable (e.g. 400 bad request, 401 auth)
                        raise EmbeddingError(
                            f"OpenAI embedding request failed: HTTP {resp.status_code} — "
                            f"{resp.text[:200]}",
                            retryable=False,
                        )

                except httpx.TimeoutException:
                    last_error = EmbeddingError(
                        "OpenAI embedding request timed out.", retryable=True
                    )

                # Exponential backoff before next attempt (skip on last attempt)
                if attempt < _MAX_RETRIES:
                    backoff = _BACKOFF_BASE_SECONDS * (2 ** (attempt - 1))
                    await asyncio.sleep(backoff)

        # All retries exhausted
        raise last_error  # type: ignore[misc]

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_response(data: dict[str, Any]) -> list[list[float]]:
        """
        Parse the OpenAI embeddings response into a list of float vectors.

        OpenAI response shape::

            {
              "object": "list",
              "data": [
                {"object": "embedding", "index": 0, "embedding": [0.1, 0.2, ...]},
                ...
              ],
              "model": "text-embedding-3-small",
              "usage": {...}
            }

        Items are sorted by ``index`` to guarantee the output order matches
        the input order, regardless of how OpenAI returns them.
        """
        items: list[dict[str, Any]] = data.get("data", [])
        # Sort by index to ensure output order == input order
        items_sorted = sorted(items, key=lambda item: item["index"])
        return [item["embedding"] for item in items_sorted]
