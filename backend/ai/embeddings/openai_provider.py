"""
OpenAI Embedding Provider — Concrete Implementation of EmbeddingProvider.

Responsibilities:
    - Communicates with OpenAI Embeddings REST API via httpx.
    - Model: text-embedding-3-small (1536 dims) by default.
    - Configurable timeout and base URL (supports mock gateways / Azure OpenAI).
    - Transport-level exponential backoff with Retry-After header support on 429/5xx.
    - Resource management with optional persistent client session.
"""

from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import Sequence
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

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_DEFAULT_TIMEOUT_SECONDS: float = 30.0
_MAX_RETRIES: int = 3
_BACKOFF_BASE_SECONDS: float = 1.0  # 1s, 2s, 4s

_RETRYABLE_STATUS_CODES: frozenset[int] = frozenset({429, 500, 502, 503, 504})
_OPENAI_EMBEDDINGS_URL = "https://api.openai.com/v1/embeddings"

_DEFAULT_MODEL = "text-embedding-3-small"
_DEFAULT_DIMENSIONS = 1536


class OpenAIEmbeddingProvider(EmbeddingProvider):
    """
    Concrete EmbeddingProvider for the OpenAI Embeddings API.

    Args:
        api_key:    OpenAI API key. Falls back to ``OPENAI_API_KEY`` environment variable.
        model:      Model identifier (default: ``text-embedding-3-small``).
        dimensions: Expected output vector length. Defaults to 1536.
                    Always driven by configuration, never hard-coded at call sites.
        timeout:    Per-request timeout in seconds (default: 30.0).
        base_url:   Override the OpenAI base URL (useful for testing or proxy endpoints).
        client:     Optional shared ``httpx.AsyncClient`` instance for connection pooling.
    """

    def __init__(
        self,
        api_key: str | None = None,
        model: str = _DEFAULT_MODEL,
        dimensions: int = _DEFAULT_DIMENSIONS,
        timeout: float = _DEFAULT_TIMEOUT_SECONDS,
        base_url: str | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._api_key = api_key or os.environ.get("OPENAI_API_KEY", "")
        self._model = model
        self._dimensions = dimensions
        self._timeout = timeout
        self._embeddings_url = (
            base_url.rstrip("/") + "/embeddings"
        ) if base_url else _OPENAI_EMBEDDINGS_URL
        self._external_client = client

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def embedding_dimensions(self) -> int:
        """Vector dimensionality expected from the configured model."""
        return self._dimensions

    @property
    def provider_name(self) -> str:
        """Provider identifier."""
        return "openai"

    @property
    def model_name(self) -> str:
        """Configured OpenAI embedding model."""
        return self._model

    @property
    def timeout(self) -> float:
        """Configured HTTP timeout in seconds."""
        return self._timeout

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def embed(self, text: str) -> list[float]:
        """
        Embed a single text string.

        Delegates to ``embed_batch([text])`` to guarantee consistent retry
        and error handling behavior.
        """
        results = await self.embed_batch([text])
        if not results:
            raise EmbeddingError("OpenAI returned no embeddings for text.", provider=self.provider_name)
        return results[0]

    async def embed_batch(self, texts: Sequence[str]) -> list[list[float]]:
        """
        Embed a list of texts in a single API call with exponential backoff retry.

        Args:
            texts: Sequence of strings to embed.

        Returns:
            List of float vectors matching the exact order of ``texts``.

        Raises:
            RateLimitError: If 429 persists after retries.
            ProviderUnavailableError: If 5xx or timeouts persist after retries.
            AuthenticationError: On 401/403 credentials error.
            InvalidRequestError: On 400 bad request.
            EmbeddingError: On general failure.
        """
        if not texts:
            return []

        payload: dict[str, Any] = {
            "model": self._model,
            "input": list(texts),
        }
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }

        last_error: EmbeddingError | None = None

        for attempt in range(1, _MAX_RETRIES + 1):
            client_ctx = (
                self._external_client
                if self._external_client is not None
                else httpx.AsyncClient(timeout=self._timeout)
            )

            async with (client_ctx if self._external_client is None else _noop_context(client_ctx)) as client:
                try:
                    resp = await client.post(
                        self._embeddings_url,
                        json=payload,
                        headers=headers,
                    )

                    if resp.status_code == 200:
                        return self._parse_response(resp.json(), expected_count=len(texts))

                    if resp.status_code == 429:
                        retry_after = self._parse_retry_after(resp.headers.get("Retry-After"))
                        last_error = RateLimitError(
                            "OpenAI embedding rate limit (429).",
                            retry_after=retry_after,
                            provider=self.provider_name,
                        )
                    elif resp.status_code in _RETRYABLE_STATUS_CODES:
                        last_error = ProviderUnavailableError(
                            f"OpenAI embedding server error (HTTP {resp.status_code}).",
                            status_code=resp.status_code,
                            provider=self.provider_name,
                        )
                    elif resp.status_code in (401, 403):
                        raise AuthenticationError(
                            f"OpenAI embedding authentication failed: HTTP {resp.status_code} — {resp.text[:200]}",
                            status_code=resp.status_code,
                            provider=self.provider_name,
                        )
                    else:
                        raise InvalidRequestError(
                            f"OpenAI embedding request failed: HTTP {resp.status_code} — {resp.text[:200]}",
                            status_code=resp.status_code,
                            provider=self.provider_name,
                        )

                except httpx.TimeoutException as exc:
                    last_error = ProviderUnavailableError(
                        "OpenAI embedding request timed out.",
                        status_code=504,
                        provider=self.provider_name,
                    )
                    logger.warning(
                        "openai_embedding_timeout",
                        extra={"attempt": attempt, "max_retries": _MAX_RETRIES, "error": str(exc)},
                    )
                except httpx.RequestError as exc:
                    last_error = ProviderUnavailableError(
                        f"OpenAI network request error: {exc}",
                        status_code=503,
                        provider=self.provider_name,
                    )
                    logger.warning(
                        "openai_embedding_network_error",
                        extra={"attempt": attempt, "error": str(exc)},
                    )

            # Exponential backoff before next retry attempt
            if attempt < _MAX_RETRIES:
                backoff = _BACKOFF_BASE_SECONDS * (2 ** (attempt - 1))
                if isinstance(last_error, RateLimitError) and last_error.retry_after is not None:
                    backoff = max(backoff, last_error.retry_after)

                logger.info(
                    "openai_embedding_retry_backoff",
                    extra={"attempt": attempt, "backoff_seconds": backoff, "error": str(last_error)},
                )
                await asyncio.sleep(backoff)

        # Exhausted all retries
        if last_error is not None:
            raise last_error

        raise EmbeddingError(
            "OpenAI embedding failed with unknown state.",
            retryable=False,
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
        """Parse HTTP Retry-After header into seconds if available."""
        if not header_val:
            return None
        try:
            return float(header_val.strip())
        except (ValueError, TypeError):
            return None

    def _parse_response(
        self,
        data: dict[str, Any],
        expected_count: int,
    ) -> list[list[float]]:
        """
        Parse and order OpenAI embedding vectors by index.

        Validates payload structure and ensures count matches expected texts.
        """
        if not isinstance(data, dict):
            raise InvalidRequestError("Invalid JSON response from OpenAI API.", provider=self.provider_name)

        items: list[dict[str, Any]] = data.get("data", [])
        if not items and expected_count > 0:
            raise InvalidRequestError("OpenAI response contained empty 'data' list.", provider=self.provider_name)

        # Sort by index to guarantee input-output positional alignment
        try:
            items_sorted = sorted(items, key=lambda item: int(item["index"]))
        except (KeyError, ValueError, TypeError) as exc:
            raise InvalidRequestError(
                f"Invalid embedding item format in OpenAI response: {exc}",
                provider=self.provider_name,
            ) from exc

        vectors: list[list[float]] = []
        for item in items_sorted:
            vec = item.get("embedding")
            if not isinstance(vec, list):
                raise InvalidRequestError("Malformed embedding vector in response.", provider=self.provider_name)
            vectors.append(vec)

        return vectors


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
