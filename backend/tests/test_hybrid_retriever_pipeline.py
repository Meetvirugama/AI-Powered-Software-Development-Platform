"""
Integration tests for HybridRetriever with Caching, Intent, Adaptive HNSW, and Graph Expansion.
"""

from __future__ import annotations

from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from backend.ai.retrieval.base import CodeChunk
from backend.ai.retrieval.cache import RetrievalResultCache
from backend.ai.retrieval.graph_expansion import SymbolGraphExpander
from backend.ai.retrieval.hybrid import HybridRetriever


def _make_chunk(name: str = "chunk", score: float = 0.8) -> CodeChunk:
    return CodeChunk(
        id=uuid4(),
        repository_id=uuid4(),
        file_id=uuid4(),
        symbol_id=uuid4(),
        content=f"def {name}(): pass",
        token_count=10,
        start_line=1,
        end_line=2,
        content_hash="hash1",
        score=score,
        file_path=f"src/{name}.py",
    )


@pytest.mark.asyncio
async def test_hybrid_retriever_cache_hit_bypasses_backends() -> None:
    repo_id = uuid4()
    cached_chunk = _make_chunk("cached")

    mock_cache = AsyncMock(spec=RetrievalResultCache)
    mock_cache.get.return_value = [cached_chunk]

    mock_vec = AsyncMock()
    mock_lex = AsyncMock()

    hybrid = HybridRetriever(
        vector_retriever=mock_vec,
        lexical_retriever=mock_lex,
        cache=mock_cache,
    )

    results = await hybrid.retrieve("getUserById", repo_id)
    assert len(results) == 1
    assert results[0].id == cached_chunk.id

    # Vector and lexical should NOT have been called due to cache hit
    assert not mock_vec.retrieve.called
    assert not mock_lex.retrieve.called


@pytest.mark.asyncio
async def test_hybrid_retriever_miss_calls_backends_and_sets_cache() -> None:
    repo_id = uuid4()
    vec_chunk = _make_chunk("vec", 0.9)
    lex_chunk = _make_chunk("lex", 0.8)

    mock_cache = AsyncMock(spec=RetrievalResultCache)
    mock_cache.get.return_value = None  # Cache miss

    mock_vec = AsyncMock()
    mock_vec.retrieve.return_value = [vec_chunk]
    mock_lex = AsyncMock()
    mock_lex.retrieve.return_value = [lex_chunk]

    hybrid = HybridRetriever(
        vector_retriever=mock_vec,
        lexical_retriever=mock_lex,
        cache=mock_cache,
    )

    results = await hybrid.retrieve("Find UserAuthenticationService", repo_id)
    assert len(results) == 2
    mock_cache.set.assert_called_once()


@pytest.mark.asyncio
async def test_hybrid_retriever_graph_expansion_participates() -> None:
    repo_id = uuid4()
    vec_chunk = _make_chunk("vec", 0.8)
    graph_chunk = _make_chunk("graph_caller", 0.7)

    mock_vec = AsyncMock()
    mock_vec.retrieve.return_value = [vec_chunk]
    mock_lex = AsyncMock()
    mock_lex.retrieve.return_value = []

    mock_graph = AsyncMock(spec=SymbolGraphExpander)
    mock_graph.expand.return_value = [graph_chunk]

    hybrid = HybridRetriever(
        vector_retriever=mock_vec,
        lexical_retriever=mock_lex,
        graph_expander=mock_graph,
    )

    # Impact analysis: graph source weight (1.5) > vector weight (0.8)
    results = await hybrid.retrieve("Find all callers of create_session", repo_id)
    assert len(results) == 2
    mock_graph.expand.assert_called_once()
    # Graph expanded candidate should rank highest in impact_analysis
    assert results[0].id == graph_chunk.id
