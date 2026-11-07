"""
Unit tests for query-intent classification and adaptive RRF weights (R05).
"""

from __future__ import annotations

import math
from uuid import uuid4

import pytest

from backend.ai.retrieval.base import CodeChunk
from backend.ai.retrieval.fusion import (
    CONCEPTUAL,
    CONFIGURATION_LOOKUP,
    DEBUGGING,
    EXACT_SYMBOL,
    IMPACT_ANALYSIS,
    PATH_LOOKUP,
    TEST_GENERATION,
    RRFFusion,
)


def _make_chunk(identifier: str | None = None, score: float = 0.5) -> CodeChunk:
    return CodeChunk(
        id=uuid4(),
        repository_id=uuid4(),
        file_id=uuid4(),
        symbol_id=uuid4(),
        content=f"def {identifier or 'func'}(): pass",
        token_count=10,
        start_line=1,
        end_line=2,
        content_hash="abc1234",
        score=score,
        file_path="src/service.py",
    )


def test_intent_classification_canonical_examples() -> None:
    fusion = RRFFusion()
    assert fusion.detect_query_intent("Where is getUserById defined?") == EXACT_SYMBOL
    assert fusion.detect_query_intent("Find UserAuthenticationService") == EXACT_SYMBOL
    assert fusion.detect_query_intent("Open src/auth/login.py") == PATH_LOOKUP
    assert fusion.detect_query_intent("Which file contains the login route?") == CONCEPTUAL
    assert fusion.detect_query_intent("Why does token refresh fail?") == DEBUGGING
    assert fusion.detect_query_intent("What functions call validate_user?") == IMPACT_ANALYSIS
    assert fusion.detect_query_intent("Find all callers of create_session") == IMPACT_ANALYSIS
    assert fusion.detect_query_intent("Generate tests for payment service") == TEST_GENERATION
    assert fusion.detect_query_intent("What happens when payment verification fails?") == DEBUGGING
    assert fusion.detect_query_intent("Where is the database URL configured?") == CONFIGURATION_LOOKUP


def test_intent_backward_compatibility() -> None:
    fusion = RRFFusion()
    intent = fusion.detect_query_intent("Where is `JWTMiddleware.dispatch` defined?")
    # Should evaluate equal to both "symbol" and "exact_symbol"
    assert intent == "symbol"
    assert intent == "exact_symbol"
    assert intent == EXACT_SYMBOL
    assert isinstance(intent, str)


def test_intent_empty_or_whitespace() -> None:
    fusion = RRFFusion()
    assert fusion.detect_query_intent("") == CONCEPTUAL
    assert fusion.detect_query_intent("   ") == CONCEPTUAL


def test_rrf_weight_validation() -> None:
    fusion = RRFFusion()
    c1 = _make_chunk("c1")

    # Mismatched weights length
    with pytest.raises(ValueError, match="weights length"):
        fusion.fuse([c1], [c1], weights=[1.0])

    # Negative weight
    with pytest.raises(ValueError, match="non-negative"):
        fusion.fuse([c1], [c1], weights=[-0.5, 1.0])

    # Infinite weight
    with pytest.raises(ValueError, match="finite"):
        fusion.fuse([c1], [c1], weights=[math.inf, 1.0])

    # NaN weight
    with pytest.raises(ValueError, match="finite"):
        fusion.fuse([c1], [c1], weights=[float("nan"), 1.0])

    # Invalid k
    with pytest.raises(ValueError, match="smoothing constant k must be positive"):
        fusion.fuse([c1], k=0)


def test_adaptive_rrf_two_sources() -> None:
    fusion = RRFFusion()
    c1 = _make_chunk("c1")
    c2 = _make_chunk("c2")

    # Exact symbol: lexical weight (1.6) > vector weight (0.7)
    res_symbol = fusion.fuse_adaptive(
        "Find UserAuthenticationService",
        vector_results=[c1],
        lexical_results=[c2],
    )
    # c2 from lexical list should have higher RRF score than c1 from vector list
    assert res_symbol[0].id == c2.id
    assert res_symbol[1].id == c1.id

    # Conceptual query: vector weight (1.4) > lexical weight (0.7)
    res_concept = fusion.fuse_adaptive(
        "Explain architecture of service",
        vector_results=[c1],
        lexical_results=[c2],
    )
    # c1 from vector list should have higher RRF score than c2 from lexical list
    assert res_concept[0].id == c1.id
    assert res_concept[1].id == c2.id


def test_adaptive_rrf_three_sources_with_graph() -> None:
    fusion = RRFFusion()
    c_vec = _make_chunk("vec")
    c_lex = _make_chunk("lex")
    c_graph = _make_chunk("graph")

    # Impact analysis: graph weight (1.5) > lexical (1.0) > vector (0.8)
    res = fusion.fuse_adaptive(
        "Find all callers of create_session",
        vector_results=[c_vec],
        lexical_results=[c_lex],
        graph_results=[c_graph],
    )
    assert len(res) == 3
    # c_graph should rank highest
    assert res[0].id == c_graph.id
    assert res[1].id == c_lex.id
    assert res[2].id == c_vec.id


def test_metadata_and_score_preservation() -> None:
    fusion = RRFFusion()
    c1 = _make_chunk("common")
    c1_vec = CodeChunk(
        id=c1.id,
        repository_id=c1.repository_id,
        file_id=c1.file_id,
        symbol_id=c1.symbol_id,
        content=c1.content,
        token_count=10,
        start_line=1,
        end_line=2,
        content_hash="h1",
        score=0.95,
        file_path="src/common.py",
        vector_similarity=0.95,
    )
    c1_lex = CodeChunk(
        id=c1.id,
        repository_id=c1.repository_id,
        file_id=c1.file_id,
        symbol_id=c1.symbol_id,
        content=c1.content,
        token_count=10,
        start_line=1,
        end_line=2,
        content_hash="h1",
        score=0.88,
        file_path="src/common.py",
        lexical_rank=0.88,
    )

    fused = fusion.fuse([c1_vec], [c1_lex])
    assert len(fused) == 1
    assert fused[0].vector_similarity == 0.95
    assert fused[0].lexical_rank == 0.88
    assert fused[0].rrf_score is not None
    assert fused[0].score == fused[0].rrf_score
