"""
Embedding Service — batch embedding, dimension validation, retry logic.
Owner: Meet — W1-12

Day 1: class skeleton + interface contract.
Day 3: full implementation — OpenAI text-embedding-3-small, batch of 100,
        asyncio.gather parallelism, dimension validation.

team_rules.md rule:
    Never hard-code embedding dimensions — read from config so swapping
    providers doesn't break anything.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .client import EmbeddingProvider

logger = logging.getLogger(__name__)


class EmbeddingService:
    """
    High-level embedding service used throughout the codebase.

    Wraps an EmbeddingProvider with:
    - Dimension validation (rejects wrong-dimension vectors immediately)
    - Retry on 429 / 503 (max 3 attempts, exponential backoff)
    - Batch size enforcement (Day 3)
    - Async parallelism via asyncio.gather (Day 3)
    """

    def __init__(self, provider: "EmbeddingProvider") -> None:
        self._provider = provider

    async def embed(self, text: str) -> list[float]:
        """
        Embed a single text string with retry and dimension validation.

        Args:
            text: Source code or query text.

        Returns:
            Validated float vector.

        Raises:
            EmbeddingError: After exhausting retries or on dimension mismatch.
        """
        # Day 3: add retry + backoff
        vector = await self._provider.embed(text)
        self._validate_dimensions(vector)
        return vector

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """
        Embed a list of texts. Batches into groups of 100, runs in parallel.

        Args:
            texts: List of source code strings (max 2048 tokens each).

        Returns:
            List of float vectors, same order as input.
        """
        # Day 3: chunk into batches of 100 + asyncio.gather
        vectors = await self._provider.embed_batch(texts)
        for v in vectors:
            self._validate_dimensions(v)
        return vectors

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _validate_dimensions(self, vector: list[float]) -> None:
        expected = self._provider.embedding_dimensions
        actual = len(vector)
        if actual != expected:
            from .client import EmbeddingError
            raise EmbeddingError(
                f"Dimension mismatch: expected {expected}, got {actual}.",
                retryable=False,
            )
