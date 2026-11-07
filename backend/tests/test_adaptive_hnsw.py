"""Unit tests for adaptive HNSW retrieval settings (R02, task.md §4)."""

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from ai.retrieval.vector import (
    HNSW_PROFILES,
    VectorRetriever,
    resolve_hnsw_profile,
)


class TestAdaptiveHNSW:
    def test_resolve_hnsw_profile_mappings(self):
        assert resolve_hnsw_profile("exact_symbol") == "exact"
        assert resolve_hnsw_profile("path_lookup") == "exact"
        assert resolve_hnsw_profile("symbol") == "exact"
        assert resolve_hnsw_profile("conceptual") == "normal"
        assert resolve_hnsw_profile(None) == "normal"
        assert resolve_hnsw_profile("debugging") == "complex"
        assert resolve_hnsw_profile("impact_analysis") == "complex"
        assert resolve_hnsw_profile("test_generation") == "complex"

    def test_hnsw_profile_values(self):
        assert HNSW_PROFILES["exact"]["ef_search"] == 40
        assert HNSW_PROFILES["normal"]["ef_search"] == 64
        assert HNSW_PROFILES["complex"]["ef_search"] == 120
        assert HNSW_PROFILES["normal"]["iterative_scan"] == "relaxed_order"

    @pytest.mark.asyncio
    async def test_adaptive_hnsw_executes_set_local(self):
        repo_id = uuid.uuid4()
        session = AsyncMock()

        mock_result = MagicMock()
        mock_result.fetchall.return_value = []
        session.execute = AsyncMock(return_value=mock_result)

        mock_embedding = AsyncMock()
        mock_embedding.embed = AsyncMock(return_value=[0.1] * 768)
        mock_embedding.dimensions = 768

        retriever = VectorRetriever(db=session, embedding_service=mock_embedding)
        await retriever.retrieve(
            query="find getUserById",
            repository_id=repo_id,
            top_k=10,
            query_intent="exact_symbol",
        )

        # Check calls on session.execute
        executed_sqls = [str(call[0][0]) for call in session.execute.call_args_list]
        assert any("hnsw.ef_search = 40" in s for s in executed_sqls)
        assert any("hnsw.iterative_scan" in s for s in executed_sqls)

    @pytest.mark.asyncio
    async def test_adaptive_hnsw_fallback_on_unsupported_engine(self):
        """When database engine fails on SET LOCAL (e.g. SQLite), it must gracefully proceed without error."""
        repo_id = uuid.uuid4()
        session = AsyncMock()

        mock_result = MagicMock()
        row = SimpleNamespace(
            id=uuid.uuid4(),
            repository_id=repo_id,
            file_id=uuid.uuid4(),
            symbol_id=None,
            content="def test(): pass",
            token_count=10,
            start_line=1,
            end_line=5,
            content_hash="h1",
            distance=0.1,
            file_path="test.py",
        )
        mock_result.fetchall.return_value = [row]

        # First two calls (SET LOCAL) raise exception, third call (vector search) succeeds
        session.execute = AsyncMock(side_effect=[
            RuntimeError("syntax error near LOCAL"),
            RuntimeError("syntax error near LOCAL"),
            mock_result,
        ])

        mock_embedding = AsyncMock()
        mock_embedding.embed = AsyncMock(return_value=[0.1] * 768)
        mock_embedding.dimensions = 768

        retriever = VectorRetriever(db=session, embedding_service=mock_embedding)
        chunks = await retriever.retrieve(
            query="test query",
            repository_id=repo_id,
            query_intent="complex",
        )
        assert len(chunks) == 1
        assert chunks[0].score == pytest.approx(0.9, rel=1e-3)

    @pytest.mark.asyncio
    async def test_adaptive_hnsw_with_nested_transaction(self):
        """When session.begin_nested() is available as an async context manager, wrap SET LOCAL."""
        repo_id = uuid.uuid4()
        session = MagicMock()
        mock_result = MagicMock()
        mock_result.fetchall.return_value = []
        session.execute = AsyncMock(return_value=mock_result)

        nested_ctx = AsyncMock()
        session.begin_nested = MagicMock(return_value=nested_ctx)

        mock_embedding = AsyncMock()
        mock_embedding.embed = AsyncMock(return_value=[0.1] * 768)
        mock_embedding.dimensions = 768

        retriever = VectorRetriever(db=session, embedding_service=mock_embedding)
        await retriever.retrieve(
            query="find getUserById",
            repository_id=repo_id,
            top_k=10,
            query_intent="exact_symbol",
        )

        assert session.begin_nested.call_count >= 1
        assert nested_ctx.__aenter__.call_count >= 1
