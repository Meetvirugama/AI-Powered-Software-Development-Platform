"""
Embeddings Module — Providers, Error Types, and Batching Services.

Provides high-level embedding generation with dimension validation,
bounded concurrency, and provider abstractions (OpenAI, etc.).
"""

from .client import (
    AuthenticationError,
    DimensionMismatchError,
    EmbeddingError,
    EmbeddingProvider,
    InvalidRequestError,
    ProviderUnavailableError,
    RateLimitError,
)
from .gemini_provider import GeminiEmbeddingProvider
from .openai_provider import OpenAIEmbeddingProvider
from .service import EmbeddingService

__all__ = [
    "AuthenticationError",
    "DimensionMismatchError",
    "EmbeddingError",
    "EmbeddingProvider",
    "EmbeddingService",
    "GeminiEmbeddingProvider",
    "InvalidRequestError",
    "OpenAIEmbeddingProvider",
    "ProviderUnavailableError",
    "RateLimitError",
]
