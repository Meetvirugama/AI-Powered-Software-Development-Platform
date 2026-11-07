"""
Unit tests for bounded symbol-graph expansion (R06).
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from backend.ai.retrieval.base import CodeChunk
from backend.ai.retrieval.graph_expansion import SymbolGraphExpander


def _make_candidate(symbol_id=None, content="def sample(): pass") -> CodeChunk:
    return CodeChunk(
        id=uuid4(),
        repository_id=uuid4(),
        file_id=uuid4(),
        symbol_id=symbol_id or uuid4(),
        content=content,
        token_count=10,
        start_line=1,
        end_line=2,
        content_hash="h123",
        score=0.9,
        file_path="src/service.py",
    )


@pytest.mark.asyncio
async def test_graph_expansion_incoming_and_outgoing_edges() -> None:
    repo_id = uuid4()
    seed_sym_id = uuid4()
    neighbor_sym_id = uuid4()
    candidate = _make_candidate(symbol_id=seed_sym_id)

    # Mock DB session returns edges and then code chunk rows
    session = AsyncMock()
    # 1. edge result: (source, target, edge_type)
    edge_res = MagicMock()
    edge_res.fetchall.return_value = [
        (seed_sym_id, neighbor_sym_id, "calls")
    ]
    # 2. chunk result: (id, repo_id, file_id, sym_id, content, token_count, start, end, hash, path)
    chunk_res = MagicMock()
    new_chunk_id = uuid4()
    chunk_res.fetchall.return_value = [
        (new_chunk_id, repo_id, uuid4(), neighbor_sym_id, "def neighbor(): pass", 15, 10, 15, "h456", "src/neighbor.py")
    ]
    session.execute.side_effect = [edge_res, chunk_res]

    expander = SymbolGraphExpander(db=session, enabled=True)
    expanded = await expander.expand(
        candidates=[candidate],
        repository_id=repo_id,
        intent="debugging",
    )

    assert len(expanded) == 1
    assert expanded[0].id == new_chunk_id
    assert expanded[0].graph_score == 0.5
    assert expanded[0].file_path == "src/neighbor.py"


@pytest.mark.asyncio
async def test_graph_expansion_repository_isolation() -> None:
    repo_a = uuid4()
    seed_sym = uuid4()
    candidate = _make_candidate(symbol_id=seed_sym)

    session = AsyncMock()
    edge_res = MagicMock()
    edge_res.fetchall.return_value = []
    session.execute.return_value = edge_res

    expander = SymbolGraphExpander(db=session, enabled=True)
    await expander.expand(candidates=[candidate], repository_id=repo_a, intent="impact_analysis")

    # Verify repository_id was passed in query params
    call_args = session.execute.call_args[0]
    params = call_args[1]
    assert params["repo_id"] == str(repo_a)


@pytest.mark.asyncio
async def test_graph_expansion_skips_path_lookup() -> None:
    session = AsyncMock()
    expander = SymbolGraphExpander(db=session, enabled=True)
    candidate = _make_candidate()

    res = await expander.expand([candidate], repository_id=uuid4(), intent="path_lookup")
    assert res == []
    assert not session.execute.called


@pytest.mark.asyncio
async def test_graph_expansion_handles_no_symbol_ids() -> None:
    session = AsyncMock()
    expander = SymbolGraphExpander(db=session, enabled=True)
    c_no_sym = CodeChunk(
        id=uuid4(),
        repository_id=uuid4(),
        file_id=uuid4(),
        symbol_id=None,
        content="raw content",
        token_count=5,
        start_line=1,
        end_line=2,
        content_hash="h00",
        score=0.7,
        file_path="src/file.py",
    )

    res = await expander.expand([c_no_sym], repository_id=uuid4(), intent="debugging")
    assert res == []
    assert not session.execute.called


@pytest.mark.asyncio
async def test_graph_expansion_graceful_failure_on_exception() -> None:
    session = AsyncMock()
    session.execute.side_effect = RuntimeError("Database connection lost")

    expander = SymbolGraphExpander(db=session, enabled=True)
    candidate = _make_candidate()

    # Must not raise RuntimeError, returns empty list gracefully
    res = await expander.expand([candidate], repository_id=uuid4(), intent="impact_analysis")
    assert res == []


@pytest.mark.asyncio
async def test_graph_expansion_max_seed_limit() -> None:
    repo_id = uuid4()
    candidates = [_make_candidate() for _ in range(10)]  # 10 candidates with unique symbol IDs

    session = AsyncMock()
    edge_res = MagicMock()
    edge_res.fetchall.return_value = []
    session.execute.return_value = edge_res

    expander = SymbolGraphExpander(db=session, max_seeds=5, enabled=True)
    await expander.expand(candidates, repository_id=repo_id, intent="conceptual")

    params = session.execute.call_args[0][1]
    # Should only have seed_0 through seed_4 (max 5 seeds)
    seed_keys = [k for k in params if k.startswith("seed_")]
    assert len(seed_keys) == 5


@pytest.mark.asyncio
async def test_graph_expansion_deduplicates_against_candidates() -> None:
    repo_id = uuid4()
    seed_sym = uuid4()
    neighbor_sym = uuid4()
    candidate = _make_candidate(symbol_id=seed_sym)

    session = AsyncMock()
    edge_res = MagicMock()
    edge_res.fetchall.return_value = [(seed_sym, neighbor_sym, "calls")]

    chunk_res = MagicMock()
    # The chunk returned has the same ID as the candidate
    chunk_res.fetchall.return_value = [
        (candidate.id, repo_id, candidate.file_id, neighbor_sym, candidate.content, 10, 1, 2, "h", "src/service.py")
    ]
    session.execute.side_effect = [edge_res, chunk_res]

    expander = SymbolGraphExpander(db=session, enabled=True)
    res = await expander.expand([candidate], repository_id=repo_id, intent="debugging")

    # Candidate should be deduplicated out
    assert res == []
