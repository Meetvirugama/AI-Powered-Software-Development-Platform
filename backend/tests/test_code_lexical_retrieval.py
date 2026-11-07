"""Unit tests for code-aware lexical retrieval (R01)."""

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from ai.retrieval.base import CodeChunk
from ai.retrieval.lexical import LexicalRetriever, _build_code_tsquery


def _make_row(
    *,
    id: uuid.UUID | None = None,
    repository_id: uuid.UUID | None = None,
    content: str = "def getUserById(user_id): return db.get(user_id)",
    file_path: str = "src/auth/service.py",
    normalised_rank: float = 0.95,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=id or uuid.uuid4(),
        repository_id=repository_id or uuid.uuid4(),
        file_id=uuid.uuid4(),
        symbol_id=None,
        content=content,
        token_count=15,
        start_line=1,
        end_line=5,
        content_hash="hash_abc",
        file_path=file_path,
        normalised_rank=normalised_rank,
    )


class TestCodeAwareLexicalRetriever:
    def test_build_code_tsquery_camel_case(self):
        query = "getUserById"
        tsquery = _build_code_tsquery(query)
        assert "get" in tsquery
        assert "user" in tsquery
        assert "id" in tsquery

    def test_build_code_tsquery_snake_case(self):
        query = "validate_user_token"
        tsquery = _build_code_tsquery(query)
        assert "validate" in tsquery
        assert "user" in tsquery
        assert "token" in tsquery

    @pytest.mark.asyncio
    async def test_code_lexical_retrieval_passes_both_queries(self):
        repo_id = uuid.uuid4()
        row = _make_row(repository_id=repo_id)

        mock_result = MagicMock()
        mock_result.fetchall.return_value = [row]
        session = AsyncMock()
        session.execute = AsyncMock(return_value=mock_result)

        retriever = LexicalRetriever(db=session)
        chunks = await retriever.retrieve("getUserById", repository_id=repo_id, top_k=10)

        assert len(chunks) == 1
        assert isinstance(chunks[0], CodeChunk)
        assert chunks[0].score == 0.95
        assert chunks[0].file_path == "src/auth/service.py"

        # Verify SQL execution parameters
        call_args = session.execute.call_args
        params = call_args[0][1]
        assert "tsquery" in params
        assert "code_tsquery" in params
        assert "repository_id" in params
        assert params["repository_id"] == str(repo_id)
        assert params["top_k"] == 10

    @pytest.mark.asyncio
    async def test_empty_or_whitespace_query_returns_empty(self):
        repo_id = uuid.uuid4()
        session = AsyncMock()
        retriever = LexicalRetriever(db=session)

        res1 = await retriever.retrieve("", repository_id=repo_id)
        res2 = await retriever.retrieve("   ", repository_id=repo_id)
        assert res1 == []
        assert res2 == []
        assert not session.execute.called
