"""
Embeddings Module — Providers, Error Types, and Batching Services.

Provides high-level embedding generation with dimension validation,
bounded concurrency, and provider abstractions (Gemini, etc.).
"""

from .client import (
    AuthenticationError,
    DimensionMismatchError,
    EmbeddingError,
    EmbeddingProfile,
    EmbeddingProvider,
    InvalidRequestError,
    ProviderUnavailableError,
    RateLimitError,
)
from .gemini_provider import GeminiEmbeddingProvider
from .rate_limiter import DistributedEmbeddingRateLimiter, EmbeddingRateLimitExceededError
from .service import CachedEmbeddingService, EmbeddingService

__all__ = [
    "AuthenticationError",
    "CachedEmbeddingService",
    "DimensionMismatchError",
    "DistributedEmbeddingRateLimiter",
    "EmbeddingError",
    "EmbeddingProfile",
    "EmbeddingProvider",
    "EmbeddingRateLimitExceededError",
    "EmbeddingService",
    "GeminiEmbeddingProvider",
    "InvalidRequestError",
    "ProviderUnavailableError",
    "RateLimitError",
]

