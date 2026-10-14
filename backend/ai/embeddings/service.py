"""
Embedding Service — Batching, Dimension Validation, and Concurrency Control.

Coordinates embedding operations across the application:
- Enforces strict vector dimensionality contracts before ingestion or search.
- Splits large item collections into provider-optimal sub-batches (default: 100).
- Governs concurrent sub-batch execution via asyncio.Semaphore to prevent socket exhaustion.
- Preserves 1:1 positional ordering between input text sequences and output vectors.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Sequence
from typing import Self

from .client import DimensionMismatchError, EmbeddingProvider

logger = logging.getLogger(__name__)

# Maximum number of texts sent to the provider in a single API call.
# Capped at 100 to balance network throughput and blast radius of individual retries.
_BATCH_SIZE: int = 100
_DEFAULT_MAX_CONCURRENCY: int = 10


class EmbeddingService:
    """
    High-level embedding orchestrator used across indexing, retrieval, and Q&A.

    Wraps an ``EmbeddingProvider`` with:
    - **Dimension Validation**: Rejects malformed vectors immediately (non-retryable).
    - **Batching & Concurrency Limits**: Partitions large text sets into sub-batches
      and executes them concurrently under a Semaphore ceiling.
    - **Observability**: Tracks processing time, batch count, and vector sizes.

    Usage::

        provider = OpenAIEmbeddingProvider()
        service  = EmbeddingService(provider=provider)

        # Single text
        vector = await service.embed("def authenticate(user, password):")

        # Large batch
        vectors = await service.embed_batch(code_chunks)
    """

    def __init__(
        self,
        provider: EmbeddingProvider,
        batch_size: int = _BATCH_SIZE,
        max_concurrency: int = _DEFAULT_MAX_CONCURRENCY,
    ) -> None:
        if batch_size <= 0:
            raise ValueError(f"batch_size must be positive, got {batch_size}")
        if max_concurrency <= 0:
            raise ValueError(f"max_concurrency must be positive, got {max_concurrency}")

        self._provider = provider
        self._batch_size = batch_size
        self._max_concurrency = max_concurrency

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def provider(self) -> EmbeddingProvider:
        """Underlying embedding provider."""
        return self._provider

    @property
    def dimensions(self) -> int:
        """Expected output vector length (from provider)."""
        return self._provider.embedding_dimensions

    @property
    def batch_size(self) -> int:
        """Configured sub-batch partition size."""
        return self._batch_size

    @property
    def max_concurrency(self) -> int:
        """Maximum concurrent API requests permitted."""
        return self._max_concurrency

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def embed(self, text: str) -> list[float]:
        """
        Embed a single text string with strict dimension validation.

        Args:
            text: Source code, query, or text snippet.

        Returns:
            Validated float vector of length ``provider.embedding_dimensions``.

        Raises:
            ValueError: If text is None.
            DimensionMismatchError: If the output vector size deviates from provider config.
            EmbeddingError: On provider failure or retry exhaustion.
        """
        if text is None:
            raise ValueError("text to embed cannot be None.")

        start_time = time.perf_counter()
        vector = await self._provider.embed(text)
        self._validate_dimensions(vector)

        duration_ms = (time.perf_counter() - start_time) * 1000.0
        logger.debug(
            "embedding_produced",
            extra={
                "dims": len(vector),
                "provider": self._provider.provider_name,
                "duration_ms": round(duration_ms, 2),
            },
        )
        return vector

    async def embed_batch(self, texts: Sequence[str]) -> list[list[float]]:
        """
        Embed a sequence of texts with automatic batching and bounded concurrency.

        Splits ``texts`` into sub-batches of ``self.batch_size``, runs them concurrently
        up to ``self.max_concurrency``, validates dimensions, and returns vectors
        preserving original input sequence order.

        Args:
            texts: Sequence of strings to embed.

        Returns:
            List of float vectors matching the exact order of ``texts``.

        Raises:
            DimensionMismatchError: On vector dimension mismatch.
            EmbeddingError: If any sub-batch exhausts retries.
        """
        if not texts:
            return []

        text_list = list(texts)
        total_count = len(text_list)
        start_time = time.perf_counter()

        # Partition texts into sub-batches
        sub_batches: list[list[str]] = [
            text_list[i : i + self._batch_size]
            for i in range(0, total_count, self._batch_size)
        ]

        # Bounded concurrency runner
        semaphore = asyncio.Semaphore(self._max_concurrency)

        async def _run_sub_batch(batch: list[str]) -> list[list[float]]:
            async with semaphore:
                return await self._provider.embed_batch(batch)

        batch_results: list[list[list[float]]] = await asyncio.gather(
            *[_run_sub_batch(batch) for batch in sub_batches]
        )

        # Flatten while validating dimensionality
        all_vectors: list[list[float]] = []
        for batch_vectors in batch_results:
            for vector in batch_vectors:
                self._validate_dimensions(vector)
                all_vectors.append(vector)

        duration_ms = (time.perf_counter() - start_time) * 1000.0
        logger.info(
            "batch_embedding_complete",
            extra={
                "total_texts": total_count,
                "num_batches": len(sub_batches),
                "provider": self._provider.provider_name,
                "duration_ms": round(duration_ms, 2),
            },
        )
        return all_vectors

    async def aclose(self) -> None:
        """Release underlying provider resources."""
        await self._provider.aclose()

    async def __aenter__(self: Self) -> Self:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: object,
    ) -> None:
        await self.aclose()

    # ------------------------------------------------------------------
    # Internal Helpers
    # ------------------------------------------------------------------

    def _validate_dimensions(self, vector: list[float]) -> None:
        """
        Assert the returned vector matches the provider's declared dimension.

        Raises:
            DimensionMismatchError: (retryable=False) on vector length mismatch.
        """
        expected = self._provider.embedding_dimensions
        actual = len(vector)
        if actual != expected:
            raise DimensionMismatchError(
                expected=expected,
                actual=actual,
                provider=self._provider.provider_name,
            )
