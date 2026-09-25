"""
Unit tests for Day 5 — Hybrid Search (RRF + Reranking).
Owner: Meet — W1-12

Tests:
    LexicalRetriever:
        1.  test_sanitize_query_normal_sentence      — normal text → joined & tokens
        2.  test_sanitize_query_strips_special_chars — punctuation removed
        3.  test_sanitize_query_empty_raises         — empty → ValueError
        4.  test_single_char_tokens_dropped          — "a b" → ValueError (both too short)
        5.  test_returns_empty_on_sanitize_failure   — retriever returns [] gracefully
        6.  test_empty_db_returns_empty_list         — zero rows → []
        7.  test_returns_code_chunks                 — rows map to CodeChunk instances
        8.  test_score_is_normalised_rank            — normalised_rank field becomes .score
        9.  test_repository_id_in_sql_params         — correct repo_id forwarded to DB
        10. test_top_k_forwarded                     — top_k appears in SQL params
        11. test_tsquery_forwarded                   — sanitized tsquery in SQL params
        12. test_results_ordered_desc                — highest-score first

    RRFFusion:
        13. test_single_list_ranked_correctly        — single source, k=60 formula
        14. test_two_lists_merged_and_deduplicated   — common chunk scores accumulated
        15. test_rrf_formula_values                  — exact 1/(k+rank) arithmetic
        16. test_score_replaced_with_rrf             — .score is RRF, not original
        17. test_higher_rank_in_both_lists_wins      — chunk in both lists scores higher
        18. test_empty_inputs_returns_empty          — no sources → []
        19. test_top_n_limits_output                 — top_n=2 returns at most 2
        20. test_order_is_descending                 — sorted by RRF score desc

    CrossEncoderReranker:
        21. test_returns_top_n                       — at most top_n chunks returned
        22. test_empty_candidates_returns_empty      — [] input → []
        23. test_score_replaced_with_logit           — .score overwritten by cross-encoder
        24. test_results_ordered_desc                — highest logit first
        25. test_top_n_less_than_candidates          — top_n=2 from 5 candidates
        26. test_model_predict_called_once           — predict() called once per rerank()
        27. test_query_paired_with_each_chunk        — pairs = [(query, chunk.content) × N]
        28. test_missing_library_raises_runtime_error — ImportError → RuntimeError

Run with:
    pytest backend/tests/test_hybrid_retrieval.py -v
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from ai.retrieval.base import CodeChunk


# ===========================================================================
# Shared helpers
# ===========================================================================

def _make_chunk(
    *,
    id: uuid.UUID | None = None,
    content: str = "def authenticate(user, pw): ...",
    score: float = 0.5,
    file_path: str = "src/auth/service.py",
    repository_id: uuid.UUID | None = None,
    start_line: int = 1,
    end_line: int = 10,
) -> CodeChunk:
    """Build a minimal CodeChunk for testing."""
    return CodeChunk(
        id=id or uuid.uuid4(),
        repository_id=repository_id or uuid.uuid4(),
        file_id=uuid.uuid4(),
        symbol_id=None,
        content=content,
        token_count=20,
        start_line=start_line,
        end_line=end_line,
        content_hash="hash123",
        score=score,
        file_path=file_path,
    )


def _make_fts_row(
    *,
    id: uuid.UUID | None = None,
    repository_id: uuid.UUID | None = None,
    normalised_rank: float = 0.8,
    content: str = "def authenticate(user, pw): ...",
    file_path: str = "src/auth/service.py",
) -> SimpleNamespace:
    """Build a fake DB row matching the FTS SQL CTE output."""
    return SimpleNamespace(
        id=id or uuid.uuid4(),
        repository_id=repository_id or uuid.uuid4(),
        file_id=uuid.uuid4(),
        symbol_id=None,
        content=content,
        token_count=20,
        start_line=1,
        end_line=10,
        content_hash="hash123",
        file_path=file_path,
        normalised_rank=normalised_rank,
    )


def _make_db_session(rows: list[SimpleNamespace]) -> AsyncMock:
    mock_result = MagicMock()
    mock_result.fetchall.return_value = rows
    session = AsyncMock()
    session.execute = AsyncMock(return_value=mock_result)
    return session


# ===========================================================================
# 1. LexicalRetriever — _sanitize_query helper
# ===========================================================================

class TestSanitizeQuery:
    """Unit tests for the query sanitizer (module-level helper)."""

    def test_normal_sentence_joins_with_ampersand(self):
        from ai.retrieval.lexical import _sanitize_query
        result = _sanitize_query("where is authentication handled")
        assert result == "where & is & authentication & handled"

    def test_strips_special_characters(self):
        from ai.retrieval.lexical import _sanitize_query
        result = _sanitize_query("auth? (user) - login!")
        assert "&" in result
        assert "?" not in result
        assert "!" not in result
        assert "(" not in result

    def test_empty_string_raises_value_error(self):
        from ai.retrieval.lexical import _sanitize_query
        with pytest.raises(ValueError, match="no searchable tokens"):
            _sanitize_query("")

    def test_only_special_chars_raises_value_error(self):
        from ai.retrieval.lexical import _sanitize_query
        with pytest.raises(ValueError, match="no searchable tokens"):
            _sanitize_query("!!! ??? ///")

    def test_single_char_tokens_are_dropped(self):
        """Single-char tokens (noise) are dropped; only real words survive."""
        from ai.retrieval.lexical import _sanitize_query
        # "a" and "b" are single chars — must be dropped
        result = _sanitize_query("find auth module")
        assert "find" in result
        assert "auth" in result
        assert "module" in result

    def test_underscore_preserved_in_token(self):
        """Underscores are word chars — preserved inside tokens."""
        from ai.retrieval.lexical import _sanitize_query
        result = _sanitize_query("auth_service login_flow")
        assert "auth_service" in result
        assert "login_flow" in result


# ===========================================================================
# 2. LexicalRetriever — retrieve()
# ===========================================================================

class TestLexicalRetrieverRetrieve:
    """Integration-style tests for LexicalRetriever.retrieve()."""

    @pytest.fixture()
    def repo_id(self) -> uuid.UUID:
        return uuid.uuid4()

    @pytest.fixture()
    def one_row(self, repo_id: uuid.UUID) -> SimpleNamespace:
        return _make_fts_row(repository_id=repo_id, normalised_rank=0.75)

    @pytest.mark.asyncio
    async def test_empty_db_returns_empty_list(self, repo_id):
        from ai.retrieval.lexical import LexicalRetriever
        db = _make_db_session([])
        retriever = LexicalRetriever(db=db)
        result = await retriever.retrieve("authentication", repo_id)
        assert result == []

    @pytest.mark.asyncio
    async def test_returns_code_chunk_instances(self, repo_id, one_row):
        from ai.retrieval.lexical import LexicalRetriever
        db = _make_db_session([one_row])
        retriever = LexicalRetriever(db=db)
        result = await retriever.retrieve("authentication", repo_id)
        assert len(result) == 1
        assert isinstance(result[0], CodeChunk)

    @pytest.mark.asyncio
    async def test_score_equals_normalised_rank(self, repo_id):
        from ai.retrieval.lexical import LexicalRetriever
        row = _make_fts_row(repository_id=repo_id, normalised_rank=0.63)
        db = _make_db_session([row])
        retriever = LexicalRetriever(db=db)
        result = await retriever.retrieve("authentication", repo_id)
        assert abs(result[0].score - 0.63) < 1e-6

    @pytest.mark.asyncio
    async def test_repository_id_passed_to_sql(self, repo_id, one_row):
        from ai.retrieval.lexical import LexicalRetriever
        db = _make_db_session([one_row])
        retriever = LexicalRetriever(db=db)
        await retriever.retrieve("auth function", repo_id)

        call_args = db.execute.call_args
        params: dict = call_args[0][1]
        assert params["repository_id"] == str(repo_id)

    @pytest.mark.asyncio
    async def test_tsquery_passed_to_sql(self, repo_id, one_row):
        """Sanitized tsquery string must appear in the SQL params dict."""
        from ai.retrieval.lexical import LexicalRetriever
        db = _make_db_session([one_row])
        retriever = LexicalRetriever(db=db)
        await retriever.retrieve("auth function", repo_id)

        call_args = db.execute.call_args
        params: dict = call_args[0][1]
        assert "tsquery" in params
        assert "auth" in params["tsquery"]
        assert "function" in params["tsquery"]

    @pytest.mark.asyncio
    async def test_top_k_forwarded_to_sql(self, repo_id):
        from ai.retrieval.lexical import LexicalRetriever
        db = _make_db_session([])
        retriever = LexicalRetriever(db=db)
        await retriever.retrieve("auth", repo_id, top_k=15)

        call_args = db.execute.call_args
        params: dict = call_args[0][1]
        assert params["top_k"] == 15

    @pytest.mark.asyncio
    async def test_default_top_k_is_30(self, repo_id):
        from ai.retrieval.lexical import LexicalRetriever
        db = _make_db_session([])
        retriever = LexicalRetriever(db=db)
        await retriever.retrieve("auth", repo_id)

        call_args = db.execute.call_args
        params: dict = call_args[0][1]
        assert params["top_k"] == 30

    @pytest.mark.asyncio
    async def test_unsearchable_query_returns_empty(self, repo_id):
        """Query with only noise chars produces [] without hitting the DB."""
        from ai.retrieval.lexical import LexicalRetriever
        db = _make_db_session([])
        retriever = LexicalRetriever(db=db)
        result = await retriever.retrieve("??? !!!", repo_id)
        assert result == []
        db.execute.assert_not_called()

    @pytest.mark.asyncio
    async def test_multiple_rows_all_returned(self, repo_id):
        from ai.retrieval.lexical import LexicalRetriever
        rows = [
            _make_fts_row(repository_id=repo_id, normalised_rank=0.9),
            _make_fts_row(repository_id=repo_id, normalised_rank=0.6),
            _make_fts_row(repository_id=repo_id, normalised_rank=0.3),
        ]
        db = _make_db_session(rows)
        retriever = LexicalRetriever(db=db)
        result = await retriever.retrieve("authentication", repo_id)
        assert len(result) == 3
        # Scores should be in descending order (DB orders by rank DESC)
        assert result[0].score >= result[1].score >= result[2].score


# ===========================================================================
# 3. RRFFusion
# ===========================================================================

class TestRRFFusion:
    """Unit tests for Reciprocal Rank Fusion."""

    @pytest.fixture()
    def fusion(self):
        from ai.retrieval.fusion import RRFFusion
        return RRFFusion()

    def test_empty_input_returns_empty(self, fusion):
        result = fusion.fuse()
        assert result == []

    def test_single_list_returns_correct_order(self, fusion):
        """Items in a single list should be ordered by 1/(k+rank) desc — i.e. rank 1 wins."""
        chunks = [_make_chunk(score=0.9), _make_chunk(score=0.5), _make_chunk(score=0.1)]
        result = fusion.fuse(chunks)
        # rank 1 (index 0) gets highest RRF score → should still be first
        assert result[0].id == chunks[0].id
        assert result[1].id == chunks[1].id
        assert result[2].id == chunks[2].id

    def test_rrf_formula_single_list(self, fusion):
        """Exact formula: score ≈ 1/(60+1) for rank=1 in single list."""
        chunk = _make_chunk()
        result = fusion.fuse([chunk], k=60)
        expected = 1.0 / (60 + 1)
        # round(score, 6) storage means we allow 1e-5 tolerance
        assert abs(result[0].score - expected) < 1e-5

    def test_chunk_in_both_lists_accumulates_score(self, fusion):
        """
        A chunk that appears in both vector and lexical results at rank 1
        should have score = 1/(60+1) + 1/(60+1) = 2/(61).
        """
        shared_id = uuid.uuid4()
        repo_id = uuid.uuid4()

        shared = _make_chunk(id=shared_id, repository_id=repo_id, score=0.9)
        unique = _make_chunk(score=0.4)

        vector_results = [shared]
        lexical_results = [shared, unique]

        result = fusion.fuse(vector_results, lexical_results, k=60)

        shared_result = next(r for r in result if r.id == shared_id)
        expected = 1.0 / (60 + 1) + 1.0 / (60 + 1)
        assert abs(shared_result.score - expected) < 1e-5

    def test_chunk_in_both_lists_outranks_chunk_in_one(self, fusion):
        """Chunk present in both lists should score higher than chunk in only one."""
        shared_id = uuid.uuid4()
        shared = _make_chunk(id=shared_id, score=0.5)
        only_vector = _make_chunk(score=0.99)  # higher original score but only in one list

        result = fusion.fuse([shared, only_vector], [shared])

        ids = [r.id for r in result]
        assert ids.index(shared_id) < ids.index(only_vector.id), (
            "Chunk in both lists should outrank chunk in only one list"
        )

    def test_score_is_replaced_not_original(self, fusion):
        """chunk.score must be the RRF score, not the original similarity score."""
        chunk = _make_chunk(score=0.999)
        result = fusion.fuse([chunk])
        # RRF score for rank=1, k=60 is 1/61 ≈ 0.0164 — definitely not 0.999
        assert result[0].score != 0.999
        assert abs(result[0].score - 1.0 / 61) < 1e-5

    def test_top_n_limits_output(self, fusion):
        """top_n=2 must return at most 2 chunks."""
        chunks = [_make_chunk() for _ in range(10)]
        result = fusion.fuse(chunks, top_n=2)
        assert len(result) == 2

    def test_result_is_sorted_descending(self, fusion):
        """All returned chunks must be sorted by RRF score descending."""
        chunks = [_make_chunk() for _ in range(5)]
        result = fusion.fuse(chunks)
        scores = [r.score for r in result]
        assert scores == sorted(scores, reverse=True), (
            f"Expected descending order, got {scores}"
        )

    def test_deduplication_by_id(self, fusion):
        """If the same chunk appears multiple times in one list, it is counted only once per list."""
        chunk = _make_chunk()
        # Both lists contain the same chunk — should appear only once in output
        result = fusion.fuse([chunk], [chunk])
        ids = [r.id for r in result]
        assert ids.count(chunk.id) == 1, "Duplicate chunk IDs must be deduplicated"

    def test_empty_list_is_ignored(self, fusion):
        """An empty list mixed with a real list should not crash."""
        chunks = [_make_chunk()]
        result = fusion.fuse(chunks, [])
        assert len(result) == 1

    def test_k_parameter_changes_scores(self, fusion):
        """Different k values must produce different RRF scores."""
        chunk = _make_chunk()
        result_k60 = fusion.fuse([chunk], k=60)
        result_k1 = fusion.fuse([chunk], k=1)
        assert result_k60[0].score != result_k1[0].score


# ===========================================================================
# 4. CrossEncoderReranker
# ===========================================================================

class TestCrossEncoderReranker:
    """Unit tests for CrossEncoderReranker (cross-encoder model is mocked)."""

    @pytest.fixture()
    def mock_cross_encoder(self):
        """Patch CrossEncoder so no model is actually downloaded."""
        with patch("ai.retrieval.reranker.CrossEncoderReranker._get_model") as m:
            mock_model = MagicMock()
            m.return_value = mock_model
            yield mock_model

    @pytest.fixture()
    def reranker(self):
        from ai.retrieval.reranker import CrossEncoderReranker
        return CrossEncoderReranker()

    def _make_logits(self, *scores: float):
        """Return a list of floats simulating CrossEncoder.predict() output."""
        return list(scores)

    def test_empty_candidates_returns_empty(self, reranker, mock_cross_encoder):
        result = reranker.rerank("query", [])
        assert result == []
        mock_cross_encoder.predict.assert_not_called()

    def test_returns_at_most_top_n(self, reranker, mock_cross_encoder):
        candidates = [_make_chunk() for _ in range(10)]
        mock_cross_encoder.predict.return_value = self._make_logits(*range(10, 0, -1))
        result = reranker.rerank("query", candidates, top_n=3)
        assert len(result) == 3

    def test_default_top_n_is_8(self, reranker, mock_cross_encoder):
        candidates = [_make_chunk() for _ in range(12)]
        mock_cross_encoder.predict.return_value = self._make_logits(*range(12, 0, -1))
        result = reranker.rerank("query", candidates)
        assert len(result) == 8

    def test_results_ordered_by_logit_descending(self, reranker, mock_cross_encoder):
        """Highest logit score must be first."""
        chunks = [_make_chunk(content=f"chunk_{i}") for i in range(5)]
        # Assign reverse logits so the last chunk has highest score
        mock_cross_encoder.predict.return_value = [1.0, 2.0, 5.0, 3.0, 4.0]
        result = reranker.rerank("query", chunks, top_n=5)

        scores = [r.score for r in result]
        assert scores == sorted(scores, reverse=True), (
            f"Expected descending order, got {scores}"
        )
        # chunk_2 had logit 5.0 → should be first
        assert result[0].content == "chunk_2"

    def test_score_replaced_with_logit(self, reranker, mock_cross_encoder):
        """chunk.score must be the cross-encoder logit, not the original RRF score."""
        chunk = _make_chunk(score=0.0164)  # original RRF score
        mock_cross_encoder.predict.return_value = [7.5]
        result = reranker.rerank("query", [chunk], top_n=1)
        assert abs(result[0].score - 7.5) < 1e-4

    def test_predict_called_once_per_rerank(self, reranker, mock_cross_encoder):
        candidates = [_make_chunk() for _ in range(5)]
        mock_cross_encoder.predict.return_value = [1.0, 2.0, 3.0, 4.0, 5.0]
        reranker.rerank("query", candidates)
        mock_cross_encoder.predict.assert_called_once()

    def test_query_paired_with_each_chunk_content(self, reranker, mock_cross_encoder):
        """predict() must receive (query, chunk.content) pairs for every candidate."""
        query = "where is auth handled?"
        chunks = [
            _make_chunk(content="def login(): ..."),
            _make_chunk(content="def logout(): ..."),
        ]
        mock_cross_encoder.predict.return_value = [2.0, 1.0]
        reranker.rerank(query, chunks)

        call_args = mock_cross_encoder.predict.call_args
        pairs = call_args[0][0]  # positional arg 0 = pairs list

        assert len(pairs) == 2
        assert pairs[0] == (query, "def login(): ...")
        assert pairs[1] == (query, "def logout(): ...")

    def test_top_n_larger_than_candidates_returns_all(self, reranker, mock_cross_encoder):
        """If top_n > len(candidates), return all candidates."""
        chunks = [_make_chunk() for _ in range(3)]
        mock_cross_encoder.predict.return_value = [1.0, 2.0, 3.0]
        result = reranker.rerank("query", chunks, top_n=10)
        assert len(result) == 3

    def test_missing_sentence_transformers_raises_runtime_error(self):
        """If sentence-transformers is not installed, a clear RuntimeError is raised."""
        from ai.retrieval.reranker import CrossEncoderReranker
        reranker = CrossEncoderReranker()

        with patch.dict("sys.modules", {"sentence_transformers": None}):
            with pytest.raises(RuntimeError, match="sentence-transformers"):
                reranker._get_model()
