"""
Embeddings Module — Providers, Error Types, L2 Normalization, and Batching Services.

Provides high-level embedding generation with dimension validation,
L2 vector normalization, task-type separation, bounded concurrency,
and provider abstractions (Gemini, optional CodeRankEmbed, etc.).
"""

from .client import (
    AuthenticationError,
    DimensionMismatchError,
    EmbeddingError,
    EmbeddingProfile,
    EmbeddingProvider,
    GeminiTaskType,
    InvalidRequestError,
    InvalidVectorError,
    ProviderUnavailableError,
    RateLimitError,
    evaluate_vector_storage_modes,
    l2_normalize_vector,
)
from .gemini_provider import GeminiEmbeddingProvider
from .local_provider import (
    CODERANK_MODEL_SPEC,
    CodeRankEmbedProvider,
    LocalEmbeddingModelSpec,
    evaluate_local_embedding_candidate,
)
from .rate_limiter import DistributedEmbeddingRateLimiter, EmbeddingRateLimitExceededError
from .service import CachedEmbeddingService, EmbeddingService

__all__ = [
    "AuthenticationError",
    "CODERANK_MODEL_SPEC",
    "CachedEmbeddingService",
    "CodeRankEmbedProvider",
    "DimensionMismatchError",
    "DistributedEmbeddingRateLimiter",
    "EmbeddingError",
    "EmbeddingProfile",
    "EmbeddingProvider",
    "EmbeddingRateLimitExceededError",
    "EmbeddingService",
    "GeminiEmbeddingProvider",
    "GeminiTaskType",
    "InvalidRequestError",
    "InvalidVectorError",
    "LocalEmbeddingModelSpec",
    "ProviderUnavailableError",
    "RateLimitError",
    "evaluate_local_embedding_candidate",
    "evaluate_vector_storage_modes",
    "l2_normalize_vector",
]
