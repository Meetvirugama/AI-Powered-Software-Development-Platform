"""
Abstract Embedding Provider Interface and Structured Error Hierarchy.

Defines the contract for embedding providers (Gemini, local, etc.)
and domain exceptions used throughout retrieval and vector storage pipelines.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence
from typing import Self


class EmbeddingError(Exception):
    """
    Base structured exception for all embedding-related errors.

    Attributes:
        message: Descriptive error message.
        retryable: Whether the caller should attempt to retry this operation.
        status_code: Optional HTTP status code from upstream provider.
        provider: Name of the provider that produced the error.
    """

    def __init__(
        self,
        message: str,
        *,
        retryable: bool = False,
        status_code: int | None = None,
        provider: str | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.retryable = retryable
        self.status_code = status_code
        self.provider = provider

    def __repr__(self) -> str:
        return (
            f"{self.__class__.__name__}(message={self.message!r}, "
            f"retryable={self.retryable}, status_code={self.status_code}, provider={self.provider!r})"
        )


class RateLimitError(EmbeddingError):
    """Raised when an embedding provider returns a rate limit (HTTP 429)."""

    def __init__(
        self,
        message: str = "Embedding rate limit reached (HTTP 429).",
        *,
        retry_after: float | None = None,
        provider: str | None = None,
    ) -> None:
        super().__init__(message, retryable=True, status_code=429, provider=provider)
        self.retry_after = retry_after


class ProviderUnavailableError(EmbeddingError):
    """Raised on upstream 5xx errors or connection/timeout failures."""

    def __init__(
        self,
        message: str = "Embedding provider unavailable or request timed out.",
        *,
        status_code: int | None = 503,
        provider: str | None = None,
    ) -> None:
        super().__init__(message, retryable=True, status_code=status_code, provider=provider)


class AuthenticationError(EmbeddingError):
    """Raised when provider authentication fails (e.g. invalid API key)."""

    def __init__(
        self,
        message: str = "Embedding provider authentication failed (HTTP 401/403).",
        *,
        status_code: int = 401,
        provider: str | None = None,
    ) -> None:
        super().__init__(message, retryable=False, status_code=status_code, provider=provider)


class InvalidRequestError(EmbeddingError):
    """Raised on non-retryable 4xx client errors (e.g. malformed inputs)."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int = 400,
        provider: str | None = None,
    ) -> None:
        super().__init__(message, retryable=False, status_code=status_code, provider=provider)


class DimensionMismatchError(EmbeddingError):
    """
    Raised when an embedding vector does not match the provider's declared dimension.

    Indicates a critical configuration mismatch between DB schema and provider model.
    """

    def __init__(
        self,
        expected: int,
        actual: int,
        *,
        provider: str | None = None,
    ) -> None:
        message = (
            f"Embedding dimension mismatch: expected {expected}, got {actual}. "
            f"Check that the provider model matches the configured dimension."
        )
        super().__init__(message, retryable=False, status_code=None, provider=provider)
        self.expected = expected
        self.actual = actual


class EmbeddingProvider(ABC):
    """
    Abstract base class for all embedding provider implementations.

    Implementations manage transport communication with the provider API / model.
    Batch splitting, concurrency limits, and dimension validation are handled
    by the high-level `EmbeddingService`.
    """

    async def embed(self, text: str) -> list[float]:
        """
        Embed a single text string.

        Default implementation delegates to `embed_batch([text])` to centralize
        batching and retry handling. Providers may override with specialized calls.

        Args:
            text: Raw text string (code snippet, query, document).

        Returns:
            Float vector of length `embedding_dimensions`.

        Raises:
            EmbeddingError: On provider failure or retry exhaustion.
        """
        results = await self.embed_batch([text])
        if not results:
            raise EmbeddingError("Provider returned empty result for single text.", retryable=False)
        return results[0]

    @abstractmethod
    async def embed_batch(self, texts: Sequence[str]) -> list[list[float]]:
        """
        Embed multiple texts in a single batch API call.

        Args:
            texts: Sequence of strings to embed.

        Returns:
            List of float vectors, ordered identically to `texts`.

        Raises:
            EmbeddingError: On provider failure or retry exhaustion.
        """
        ...

    @property
    @abstractmethod
    def embedding_dimensions(self) -> int:
        """Declared number of dimensions in each output vector (from config)."""
        ...

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Canonical human-readable provider identifier (e.g. 'gemini')."""
        ...

    @property
    def model_name(self) -> str:
        """Name of the model used by the provider."""
        return "unknown"

    async def aclose(self) -> None:
        """Optional hook to release network connections and resources."""

    async def __aenter__(self: Self) -> Self:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: object,
    ) -> None:
        await self.aclose()
