"""
Retrieval Subsystem — Vector, Lexical, Hybrid Search with Adaptive HNSW, RRF, Graph Expansion, Redis Cache, and Cross-Encoder Reranking.
Owner: Meet — W1-12
"""

from __future__ import annotations

from .base import CodeChunk, RetrievalUnavailableError, Retriever
from .cache import RetrievalResultCache
from .cache_keys import build_retrieval_cache_key
from .evaluation import evaluate_retriever
from .fusion import RRFFusion
from .graph_expansion import SymbolGraphExpander
from .hybrid import HybridRetriever
from .lexical import LexicalRetriever
from .pipeline import RAGPipeline
from .reranker import CrossEncoderReranker
from .reranker_factory import create_reranker
from .reranker_onnx import ONNXCrossEncoderReranker
from .vector import VectorRetriever

__all__ = [
    "CodeChunk",
    "CrossEncoderReranker",
    "HybridRetriever",
    "LexicalRetriever",
    "ONNXCrossEncoderReranker",
    "RAGPipeline",
    "RRFFusion",
    "RetrievalResultCache",
    "RetrievalUnavailableError",
    "Retriever",
    "SymbolGraphExpander",
    "VectorRetriever",
    "build_retrieval_cache_key",
    "create_reranker",
    "evaluate_retriever",
]
