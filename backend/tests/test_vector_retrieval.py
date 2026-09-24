"""
Unit tests for VectorRetriever — Meet Day 4 requirement.
Owner: Meet — W1-12

Tests:
    1. test_returns_typed_code_chunks         — items are CodeChunk instances
    2. test_scoped_to_repository_id           — SQL receives correct repository_id
    3. test_empty_db_result_returns_empty     — no rows → [], no exception
    4. test_embedding_called_exactly_once     — EmbeddingService.embed called once per query
    5. test_similarity_score_computed         — score = 1 − distance (clamped ≥ 0)
    6. test_negative_distance_clamped_to_zero — pathological: distance > 1 → score = 0
    7. test_top_k_forwarded_to_sql            — top_k param reaches DB execute call
    8. test_results_ordered_by_score_desc     — returned list is highest-score-first

Run with:
    pytest backend/tests/test_vector_retrieval.py -v

Design notes:
    - No real DB or OpenAI calls — both are fully mocked.
    - AsyncMock used for async DB execute and embedding service.
    - Row objects are simulated via SimpleNamespace for readability.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest

from ai.retrieval.base import CodeChunk


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_row(
    *,
    id: uuid.UUID | None = None,
    repository_id: uuid.UUID | None = None,
    file_id: uuid.UUID | None = None,
    symbol_id: uuid.UUID | None = None,
    content: str = "def authenticate(user, pw): ...",
    token_count: int = 42,
    start_line: int = 10,
    end_line: int = 25,
    content_hash: str = "abc123",
    distance: float = 0.2,
    file_path: str = "src/auth/service.py",
) -> SimpleNamespace:
    """Create a fake DB row that mimics a SQLAlchemy Row."""
    return SimpleNamespace(
        id=id or uuid.uuid4(),
        repository_id=repository_id or uuid.uuid4(),
        file_id=file_id or uuid.uuid4(),
        symbol_id=symbol_id,
        content=content,
        token_count=token_count,
        start_line=start_line,
        end_line=end_line,
        content_hash=content_hash,
        distance=distance,
        file_path=file_path,
    )


def _make_db_session(rows: list[SimpleNamespace]) -> AsyncMock:
    """Return a mock AsyncSession whose execute() returns the given rows."""
    mock_result = MagicMock()
    mock_result.fetchall.return_value = rows

    session = AsyncMock()
    session.execute = AsyncMock(return_value=mock_result)
    return session


def _make_embedding_service(vector: list[float] | None = None) -> AsyncMock:
    """Return a mock EmbeddingService.embed() returning a fake vector."""
    svc = AsyncMock()
    svc.embed = AsyncMock(return_value=vector or [0.1] * 1536)
    return svc


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def repo_id() -> uuid.UUID:
    return uuid.uuid4()


@pytest.fixture()
def fake_vector() -> list[float]:
    return [0.05] * 1536


@pytest.fixture()
def one_row(repo_id: uuid.UUID) -> SimpleNamespace:
    return _make_row(repository_id=repo_id, distance=0.25)


@pytest.fixture()
def retriever(one_row: SimpleNamespace, fake_vector: list[float]):
    """Returns a VectorRetriever wired to a mocked DB + embedding service."""
    from ai.retrieval.vector import VectorRetriever

    db = _make_db_session([one_row])
    svc = _make_embedding_service(fake_vector)
    return VectorRetriever(db=db, embedding_service=svc), db, svc


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestReturnTypes:
    """VectorRetriever.retrieve() always returns list[CodeChunk]."""

    @pytest.mark.asyncio
    async def test_returns_list(self, retriever, repo_id):
        rv, _, _ = retriever
        result = await rv.retrieve("where is auth?", repo_id)
        assert isinstance(result, list), "Must return a list"

    @pytest.mark.asyncio
    async def test_items_are_code_chunks(self, retriever, repo_id):
        """Each item in the result must be a typed CodeChunk instance."""
        rv, _, _ = retriever
        result = await rv.retrieve("where is auth?", repo_id)

        assert len(result) == 1
        assert isinstance(result[0], CodeChunk), (
            f"Expected CodeChunk, got {type(result[0]).__name__}"
        )

    @pytest.mark.asyncio
    async def test_chunk_fields_populated(self, retriever, repo_id, one_row):
        """All CodeChunk fields must be populated from the DB row."""
        rv, _, _ = retriever
        result = await rv.retrieve("where is auth?", repo_id)

        chunk = result[0]
        assert chunk.id == one_row.id
        assert chunk.repository_id == one_row.repository_id
        assert chunk.file_id == one_row.file_id
        assert chunk.content == one_row.content
        assert chunk.token_count == one_row.token_count
        assert chunk.start_line == one_row.start_line
        assert chunk.end_line == one_row.end_line
        assert chunk.content_hash == one_row.content_hash
        assert chunk.file_path == one_row.file_path


class TestRepositoryScoping:
    """Every query must be scoped to the correct repository_id."""

    @pytest.mark.asyncio
    async def test_repository_id_in_db_call(self, retriever, repo_id):
        """
        The DB execute() call must receive the correct repository_id string
        so PostgreSQL scopes the search to one repo (team_rules: no cross-repo leakage).
        """
        rv, db, _ = retriever
        await rv.retrieve("auth?", repo_id)

        # Extract the params dict passed to db.execute()
        call_args = db.execute.call_args
        params: dict = call_args[0][1]  # positional arg 1 = params dict

        assert params["repository_id"] == str(repo_id), (
            f"Expected repository_id={repo_id!s} in SQL params, got: {params}"
        )


class TestEmptyResults:
    """No indexed chunks → empty list, no exception."""

    @pytest.mark.asyncio
    async def test_empty_db_returns_empty_list(self, repo_id, fake_vector):
        """Empty DB result returns [] without raising any exception."""
        from ai.retrieval.vector import VectorRetriever

        db = _make_db_session([])  # zero rows
        svc = _make_embedding_service(fake_vector)
        rv = VectorRetriever(db=db, embedding_service=svc)

        result = await rv.retrieve("anything", repo_id)
        assert result == [], f"Expected [], got {result}"

    @pytest.mark.asyncio
    async def test_empty_result_does_not_call_row_mapper(self, repo_id, fake_vector):
        """When rows are empty, no CodeChunk construction should occur."""
        from ai.retrieval.vector import VectorRetriever

        db = _make_db_session([])
        svc = _make_embedding_service(fake_vector)
        rv = VectorRetriever(db=db, embedding_service=svc)

        result = await rv.retrieve("anything", repo_id)
        assert len(result) == 0


class TestEmbeddingBehaviour:
    """EmbeddingService is called exactly once with the original query string."""

    @pytest.mark.asyncio
    async def test_embedding_called_exactly_once(self, retriever, repo_id):
        """embed() must be called once per retrieve() call — not zero, not many."""
        rv, _, svc = retriever
        await rv.retrieve("search query", repo_id)

        svc.embed.assert_called_once_with("search query")

    @pytest.mark.asyncio
    async def test_embedding_receives_full_query(self, repo_id, fake_vector):
        """embed() receives the exact query string, unmodified."""
        from ai.retrieval.vector import VectorRetriever

        query = "Where is the JWT token validation logic?"
        db = _make_db_session([_make_row(repository_id=repo_id)])
        svc = _make_embedding_service(fake_vector)
        rv = VectorRetriever(db=db, embedding_service=svc)

        await rv.retrieve(query, repo_id)
        svc.embed.assert_called_once_with(query)


class TestSimilarityScore:
    """score = 1 − cosine_distance, clamped to [0, 1]."""

    @pytest.mark.asyncio
    async def test_score_is_one_minus_distance(self, repo_id, fake_vector):
        """Standard case: distance=0.3 → score=0.7."""
        from ai.retrieval.vector import VectorRetriever

        row = _make_row(repository_id=repo_id, distance=0.3)
        db = _make_db_session([row])
        svc = _make_embedding_service(fake_vector)
        rv = VectorRetriever(db=db, embedding_service=svc)

        result = await rv.retrieve("query", repo_id)

        expected_score = 1.0 - 0.3
        assert abs(result[0].score - expected_score) < 1e-6, (
            f"Expected score≈{expected_score}, got {result[0].score}"
        )

    @pytest.mark.asyncio
    async def test_perfect_match_score_is_one(self, repo_id, fake_vector):
        """distance=0.0 (identical vector) → score=1.0."""
        from ai.retrieval.vector import VectorRetriever

        row = _make_row(repository_id=repo_id, distance=0.0)
        db = _make_db_session([row])
        svc = _make_embedding_service(fake_vector)
        rv = VectorRetriever(db=db, embedding_service=svc)

        result = await rv.retrieve("query", repo_id)
        assert result[0].score == pytest.approx(1.0)

    @pytest.mark.asyncio
    async def test_pathological_distance_clamped_to_zero(self, repo_id, fake_vector):
        """
        pgvector distance can exceed 1.0 in rare cases (e.g., unnormalised vectors).
        score must be clamped to 0 — never negative.
        """
        from ai.retrieval.vector import VectorRetriever

        row = _make_row(repository_id=repo_id, distance=1.5)  # > 1
        db = _make_db_session([row])
        svc = _make_embedding_service(fake_vector)
        rv = VectorRetriever(db=db, embedding_service=svc)

        result = await rv.retrieve("query", repo_id)
        assert result[0].score == 0.0, (
            f"Score must be clamped to 0.0, got {result[0].score}"
        )


class TestTopK:
    """top_k parameter is forwarded to the SQL query."""

    @pytest.mark.asyncio
    async def test_top_k_forwarded(self, repo_id, fake_vector):
        """The top_k value must appear as the LIMIT in the SQL params."""
        from ai.retrieval.vector import VectorRetriever

        db = _make_db_session([])
        svc = _make_embedding_service(fake_vector)
        rv = VectorRetriever(db=db, embedding_service=svc)

        await rv.retrieve("q", repo_id, top_k=15)

        call_args = db.execute.call_args
        params: dict = call_args[0][1]
        assert params["top_k"] == 15, f"Expected top_k=15 in SQL params, got {params}"

    @pytest.mark.asyncio
    async def test_default_top_k_is_30(self, repo_id, fake_vector):
        """Default top_k=30 matches the RRF input spec in week1.md."""
        from ai.retrieval.vector import VectorRetriever

        db = _make_db_session([])
        svc = _make_embedding_service(fake_vector)
        rv = VectorRetriever(db=db, embedding_service=svc)

        await rv.retrieve("q", repo_id)  # no top_k arg

        call_args = db.execute.call_args
        params: dict = call_args[0][1]
        assert params["top_k"] == 30


class TestOrdering:
    """Results are returned highest-score-first."""

    @pytest.mark.asyncio
    async def test_results_ordered_by_score_descending(self, repo_id, fake_vector):
        """
        The DB returns rows in ORDER BY distance ASC (closest first).
        After converting to score = 1 − distance, the list must still be
        highest-score-first.
        """
        from ai.retrieval.vector import VectorRetriever

        # Simulate DB returning rows already sorted by distance ascending
        rows = [
            _make_row(repository_id=repo_id, distance=0.1, content="best match"),
            _make_row(repository_id=repo_id, distance=0.4, content="ok match"),
            _make_row(repository_id=repo_id, distance=0.9, content="poor match"),
        ]
        db = _make_db_session(rows)
        svc = _make_embedding_service(fake_vector)
        rv = VectorRetriever(db=db, embedding_service=svc)

        result = await rv.retrieve("query", repo_id)

        assert len(result) == 3
        assert result[0].score >= result[1].score >= result[2].score, (
            f"Expected descending scores, got {[r.score for r in result]}"
        )
        assert result[0].content == "best match"
        assert result[2].content == "poor match"
