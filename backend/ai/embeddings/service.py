"""
Embedding Service — batch embedding, dimension validation, retry logic.
Owner: Meet — W1-12

Day 1: class skeleton + interface contract.
Day 3: full implementation — OpenAI text-embedding-3-small, batch of 100,
        asyncio.gather parallelism, dimension validation, retry on 429/503.

team_rules.md rule:
    Never hard-code embedding dimensions — read from config so swapping
    providers doesn't break anything.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .client import EmbeddingProvider

logger = logging.getLogger(__name__)

# Maximum number of texts sent to the provider in a single API call.
# OpenAI's embeddings endpoint accepts up to 2048 items, but we cap at 100
# to keep individual request sizes manageable and error recovery cheap.
_BATCH_SIZE = 100


class EmbeddingService:
    """
    High-level embedding service used throughout the codebase.

    Wraps an EmbeddingProvider with:
    - **Dimension validation** — rejects wrong-dimension vectors immediately
      (non-retryable; signals a config or provider mismatch).
    - **Retry on 429 / 5xx** — delegates to the provider's built-in retry loop
      (OpenAIEmbeddingProvider handles exponential backoff).
    - **Batch size enforcement** — splits large lists into sub-batches of 100.
    - **Async parallelism** — sub-batches run concurrently via ``asyncio.gather``.

    Usage::

        from ai.embeddings.openai_provider import OpenAIEmbeddingProvider
        from ai.embeddings.service import EmbeddingService

        service = EmbeddingService(provider=OpenAIEmbeddingProvider())
        vector  = await service.embed("def authenticate(user, password):")
        batch   = await service.embed_batch(["func A ...", "func B ..."])
    """

    def __init__(self, provider: "EmbeddingProvider") -> None:
        self._provider = provider

    async def embed(self, text: str) -> list[float]:
        """
        Embed a single text string with dimension validation.

        Retry is handled by the underlying provider.

        Args:
            text: Source code or query text.

        Returns:
            Validated float vector of length ``provider.embedding_dimensions``.

        Raises:
            EmbeddingError: After provider exhausts retries, or on dimension mismatch.
        """
        vector = await self._provider.embed(text)
        self._validate_dimensions(vector)
        logger.debug(
            "embedding_produced",
            extra={"dims": len(vector), "provider": self._provider.provider_name},
        )
        return vector

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """
        Embed a list of texts.

        Automatically splits ``texts`` into sub-batches of ``_BATCH_SIZE`` (100),
        runs all sub-batches concurrently with ``asyncio.gather``, then
        flattens the results — preserving the original order.

        Args:
            texts: List of source code strings (max 2048 tokens each per OpenAI).

        Returns:
            List of float vectors in the same order as ``texts``.

        Raises:
            EmbeddingError: If any sub-batch fails after provider retries,
                            or if any vector has wrong dimensions.
        """
        if not texts:
            return []

        # Split into sub-batches
        sub_batches: list[list[str]] = [
            texts[i : i + _BATCH_SIZE] for i in range(0, len(texts), _BATCH_SIZE)
        ]

        # Run all sub-batches concurrently
        batch_results: list[list[list[float]]] = await asyncio.gather(
            *[self._provider.embed_batch(batch) for batch in sub_batches]
        )

        # Flatten and validate
        all_vectors: list[list[float]] = []
        for batch_vectors in batch_results:
            for vector in batch_vectors:
                self._validate_dimensions(vector)
                all_vectors.append(vector)

        logger.info(
            "batch_embedding_complete",
            extra={
                "total_texts": len(texts),
                "num_batches": len(sub_batches),
                "provider": self._provider.provider_name,
            },
        )
        return all_vectors

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _validate_dimensions(self, vector: list[float]) -> None:
        """
        Assert the returned vector matches the provider's declared dimension.

        This is a hard, non-retryable check — a dimension mismatch means either
        the provider config is wrong or the provider returned a different model
        than expected. Both require human intervention.

        Raises:
            EmbeddingError: (retryable=False) on dimension mismatch.
        """
        expected = self._provider.embedding_dimensions
        actual = len(vector)
        if actual != expected:
            from .client import EmbeddingError

            raise EmbeddingError(
                f"Embedding dimension mismatch: expected {expected}, got {actual}. "
                f"Check that the provider model matches the configured dimension.",
                retryable=False,
            )
