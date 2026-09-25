# Embeddings module — Meet, W1-12
# Day 1: abstract interface (EmbeddingProvider, EmbeddingError)
# Day 3: concrete provider (OpenAIEmbeddingProvider) + full EmbeddingService

from .client import EmbeddingError, EmbeddingProvider
from .openai_provider import OpenAIEmbeddingProvider
from .service import EmbeddingService

__all__ = [
    "EmbeddingError",
    "EmbeddingProvider",
    "EmbeddingService",
    "OpenAIEmbeddingProvider",
]
