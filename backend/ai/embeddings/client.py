"""
Abstract Embedding provider interface.
Owner: Meet — W1-12

Day 1: interface definitions only.
Day 3: OpenAI text-embedding-3-small implementation, batch support, dimension validation.
"""

from __future__ import annotations

from abc import ABC, abstractmethod


class EmbeddingProvider(ABC):
    """
    Abstract base for an embedding provider.

    Implementations must handle a single provider SDK.
    Retry, batching, and dimension validation live in EmbeddingService.
    """

    @abstractmethod
    async def embed(self, text: str) -> list[float]:
        """
        Embed a single text string.

        Args:
            text: Raw text (code, query, or doc).

        Returns:
            Float vector of length `embedding_dimensions`.

        Raises:
            EmbeddingError: Any provider-level failure.
        """
        ...

    @abstractmethod
    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """
        Embed multiple texts in a single API call.

        Args:
            texts: List of strings. Max batch size is provider-dependent.

        Returns:
            List of float vectors, same length as `texts`, in the same order.
        """
        ...

    @property
    @abstractmethod
    def embedding_dimensions(self) -> int:
        """Number of dimensions in each output vector. Read from config."""
        ...

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Human-readable provider name, e.g. 'openai'."""
        ...


class EmbeddingError(Exception):
    """Structured error for embedding failures."""

    def __init__(self, message: str, *, retryable: bool = False) -> None:
        super().__init__(message)
        self.retryable = retryable
