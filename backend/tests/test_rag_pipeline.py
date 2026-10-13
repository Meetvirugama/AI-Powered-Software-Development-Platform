"""
Integration tests for Day 7 — RAGPipeline (full end-to-end flow).
Owner: Meet — W1-12

Tests cover the complete pipeline:
    retrieval → context builder → prompt builder → LLM → grounding validation

Test plan:
    RAGPipeline.chat — happy path:
        1.  test_chat_returns_repository_answer              — returns RepositoryAnswer
        2.  test_chat_uses_context_builder                   — ContextBuilder.build() called
        3.  test_chat_uses_prompt_builder                    — PromptBuilder.build_chat_prompt() called
        4.  test_chat_uses_grounding_validator               — GroundingValidator.validate_sources() called
        5.  test_chat_passes_question_to_retriever           — retriever called with question
        6.  test_chat_passes_repository_id_to_retriever      — retriever scoped to repo_id
        7.  test_chat_history_normalised_from_dicts          — plain dict history accepted
        8.  test_chat_with_memory_entries                    — memory forwarded to context builder

    RAGPipeline.chat — zero retrieval:
        9.  test_zero_results_returns_low_confidence         — confidence=low
        10. test_zero_results_answer_mentions_no_code        — answer contains "no relevant code"
        11. test_zero_results_sources_empty                  — sources=[]
        12. test_zero_results_does_not_call_llm              — LLM not called when no chunks

    RAGPipeline.chat — error handling:
        13. test_llm_timeout_raises_api_error_503            — LLMTimeoutError → APIError 503
        14. test_llm_unavailable_raises_api_error_503        — LLMUnavailableError → APIError 503
        15. test_timeout_error_is_retryable                  — retryable=True on timeout
        16. test_unavailable_error_is_retryable              — retryable=True on unavailable

    RAGPipeline.chat — JSON repair loop:
        17. test_repair_loop_succeeds_on_second_attempt      — bad JSON → retry → valid JSON
        18. test_repair_loop_calls_llm_twice                 — exactly 2 LLM calls on repair
        19. test_repair_loop_exhausted_raises_api_error      — both attempts fail → APIError 500
        20. test_markdown_fences_stripped_from_response      — ```json … ``` code fence removed

    RAGPipeline._normalise_history:
        21. test_normalise_dict_history                      — dicts → ChatMessage
        22. test_normalise_chat_message_history              — ChatMessage objects pass through
        23. test_normalise_mixed_history                     — mixed list accepted

    RAGPipeline._retrieve:
        24. test_retrieve_no_retriever_returns_empty         — None retriever → []
        25. test_retrieve_exception_returns_empty            — retriever exception → [] (no crash)

    Acceptance test (Week 1 spec):
        26. test_acceptance_authentication_question          — "Where is authentication?" → grounded answer

Run with:
    pytest backend/tests/test_rag_pipeline.py -v
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from typing import Any
from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest

from ai.context.builder import AgentContext, ChatMessage, ContextBuilder, MemoryEntry
from ai.llm.schemas import LLMResponse, LLMTimeoutError, LLMUnavailableError, Message
from ai.pipeline import RAGPipeline
from ai.retrieval.base import CodeChunk
from ai.schemas.grounding import GroundingValidator
from ai.schemas.output import RepositoryAnswer, SourceReference
from ai.schemas.prompt_builder import PromptBuilder
from app.core.errors import APIError, ErrorCode


# ===========================================================================
# Fixtures / factories
# ===========================================================================


def _make_chunk(
    file_path: str = "src/auth/service.py",
    content: str = "def authenticate(user, pw):\n    ...",
    start_line: int = 10,
    end_line: int = 20,
    score: float = 0.95,
) -> CodeChunk:
    return CodeChunk(
        id=uuid.uuid4(),
        repository_id=uuid.uuid4(),
        file_id=uuid.uuid4(),
        symbol_id=None,
        content=content,
        token_count=len(content.split()),
        start_line=start_line,
        end_line=end_line,
        content_hash="deadbeef",
        score=score,
        file_path=file_path,
    )


def _make_llm_response(
    answer: str = "Authentication is handled in AuthService.",
    sources: list[dict] | None = None,
    confidence: str = "high",
    model: str = "gpt-4o",
) -> MagicMock:
    """Build a mock LLMResponse whose `.content` is valid RepositoryAnswer JSON."""
    if sources is None:
        sources = [
            {
                "file": "src/auth/service.py",
                "start_line": 10,
                "end_line": 20,
                "symbol": "AuthService",
            }
        ]
    payload = json.dumps(
        {"answer": answer, "sources": sources, "confidence": confidence}
    )
    mock = MagicMock(spec=LLMResponse)
    mock.content = payload
    mock.model = model
    mock.input_tokens = 512
    mock.output_tokens = 128
    mock.latency_ms = 350.0
    return mock


def _make_memory(
    id: str = "mem-1",
    content: str = "Use JWT for all authentication tokens.",
    type: str = "architecture",
    created_at: str = "2024-06-01T00:00:00Z",
) -> MemoryEntry:
    return MemoryEntry(id=id, content=content, type=type, created_at=created_at)


def _make_pipeline(
    *,
    chunks: list[CodeChunk] | None = None,
    llm_response: Any = None,
    no_retriever: bool = False,
    no_llm: bool = False,
) -> tuple[RAGPipeline, AsyncMock, AsyncMock]:
    """
    Build a fully-mocked RAGPipeline for testing.

    Returns (pipeline, mock_retriever, mock_llm).
    """
    # Mock retriever
    mock_retriever = AsyncMock()
    mock_retriever.retrieve.return_value = chunks if chunks is not None else [_make_chunk()]

    # Mock LLM gateway
    mock_llm = AsyncMock()
    if llm_response is not None:
        mock_llm.generate.return_value = llm_response
    else:
        mock_llm.generate.return_value = _make_llm_response()

    pipeline = RAGPipeline(
        retriever=None if no_retriever else mock_retriever,
        llm_gateway=None if no_llm else mock_llm,
    )
    return pipeline, mock_retriever, mock_llm


# ===========================================================================
# 1–8: Happy path
# ===========================================================================


class TestChatHappyPath:
    @pytest.mark.asyncio
    async def test_chat_returns_repository_answer(self):
        pipeline, _, _ = _make_pipeline()
        result = await pipeline.chat("Where is auth?", uuid.uuid4(), [])
        assert isinstance(result, RepositoryAnswer)

    @pytest.mark.asyncio
    async def test_chat_uses_context_builder(self):
        chunks = [_make_chunk()]
        pipeline, mock_retriever, _ = _make_pipeline(chunks=chunks)

        mock_cb = MagicMock(spec=ContextBuilder)
        mock_cb.build.return_value = AgentContext(
            code_chunks=chunks, total_tokens=500
        )
        mock_cb.render_repository_data.return_value = "REPOSITORY DATA:\n..."
        pipeline.context_builder = mock_cb

        await pipeline.chat("test question", uuid.uuid4(), [])
        mock_cb.build.assert_called_once()

    @pytest.mark.asyncio
    async def test_chat_uses_prompt_builder(self):
        pipeline, _, _ = _make_pipeline()

        mock_pb = MagicMock(spec=PromptBuilder)
        mock_pb.build_chat_prompt.return_value = [
            Message(role="system", content="sys"),
            Message(role="user", content="user"),
        ]
        pipeline.prompt_builder = mock_pb

        await pipeline.chat("test question", uuid.uuid4(), [])
        mock_pb.build_chat_prompt.assert_called_once()

    @pytest.mark.asyncio
    async def test_chat_uses_grounding_validator(self):
        pipeline, _, _ = _make_pipeline()

        mock_gv = AsyncMock(spec=GroundingValidator)
        raw_answer = RepositoryAnswer(
            answer="Auth is in service.py", sources=[], confidence="high"
        )
        mock_gv.validate_sources.return_value = raw_answer
        pipeline.grounding_validator = mock_gv

        await pipeline.chat("Where is auth?", uuid.uuid4(), [])
        mock_gv.validate_sources.assert_called_once()

    @pytest.mark.asyncio
    async def test_chat_passes_question_to_retriever(self):
        pipeline, mock_retriever, _ = _make_pipeline()
        question = "Where is JWT validation?"
        await pipeline.chat(question, uuid.uuid4(), [])
        call_kwargs = mock_retriever.retrieve.call_args
        assert call_kwargs.kwargs.get("query") == question or (
            call_kwargs.args and call_kwargs.args[0] == question
        )

    @pytest.mark.asyncio
    async def test_chat_passes_repository_id_to_retriever(self):
        pipeline, mock_retriever, _ = _make_pipeline()
        repo_id = uuid.uuid4()
        await pipeline.chat("question", repo_id, [])
        call_kwargs = mock_retriever.retrieve.call_args
        assert call_kwargs.kwargs.get("repository_id") == repo_id or (
            len(call_kwargs.args) > 1 and call_kwargs.args[1] == repo_id
        )

    @pytest.mark.asyncio
    async def test_chat_history_normalised_from_dicts(self):
        pipeline, _, _ = _make_pipeline()

        mock_cb = MagicMock(spec=ContextBuilder)
        mock_cb.build.return_value = AgentContext(
            code_chunks=[_make_chunk()], total_tokens=100
        )
        mock_cb.render_repository_data.return_value = "data"
        pipeline.context_builder = mock_cb

        dict_history = [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi there"},
        ]
        await pipeline.chat("follow-up", uuid.uuid4(), dict_history)

        build_call = mock_cb.build.call_args
        history_arg = build_call.kwargs.get("history") or (
            build_call.args[2] if len(build_call.args) > 2 else []
        )
        assert all(isinstance(m, ChatMessage) for m in history_arg)
        assert len(history_arg) == 2

    @pytest.mark.asyncio
    async def test_chat_with_memory_entries(self):
        pipeline, _, _ = _make_pipeline()
        memory = [_make_memory()]

        mock_cb = MagicMock(spec=ContextBuilder)
        mock_cb.build.return_value = AgentContext(
            code_chunks=[_make_chunk()], total_tokens=100
        )
        mock_cb.render_repository_data.return_value = "data"
        pipeline.context_builder = mock_cb

        await pipeline.chat("question", uuid.uuid4(), [], memory=memory)

        build_call = mock_cb.build.call_args
        memory_arg = build_call.kwargs.get("memory") or (
            build_call.args[1] if len(build_call.args) > 1 else []
        )
        assert memory_arg == memory


# ===========================================================================
# 9–12: Zero retrieval
# ===========================================================================


class TestZeroRetrieval:
    @pytest.mark.asyncio
    async def test_zero_results_returns_low_confidence(self):
        pipeline, _, _ = _make_pipeline(chunks=[])
        result = await pipeline.chat("question", uuid.uuid4(), [])
        assert result.confidence == "low"

    @pytest.mark.asyncio
    async def test_zero_results_answer_mentions_no_code(self):
        pipeline, _, _ = _make_pipeline(chunks=[])
        result = await pipeline.chat("question", uuid.uuid4(), [])
        assert "no relevant code" in result.answer.lower()

    @pytest.mark.asyncio
    async def test_zero_results_sources_empty(self):
        pipeline, _, _ = _make_pipeline(chunks=[])
        result = await pipeline.chat("question", uuid.uuid4(), [])
        assert result.sources == []

    @pytest.mark.asyncio
    async def test_zero_results_does_not_call_llm(self):
        pipeline, _, mock_llm = _make_pipeline(chunks=[])
        await pipeline.chat("question", uuid.uuid4(), [])
        mock_llm.generate.assert_not_called()


# ===========================================================================
# 13–16: Error handling
# ===========================================================================


class TestErrorHandling:
    @pytest.mark.asyncio
    async def test_llm_timeout_raises_api_error_503(self):
        pipeline, _, mock_llm = _make_pipeline()
        mock_llm.generate.side_effect = LLMTimeoutError()
        with pytest.raises(APIError) as exc_info:
            await pipeline.chat("question", uuid.uuid4(), [])
        assert exc_info.value.code == ErrorCode.SERVICE_UNAVAILABLE

    @pytest.mark.asyncio
    async def test_llm_unavailable_raises_api_error_503(self):
        pipeline, _, mock_llm = _make_pipeline()
        mock_llm.generate.side_effect = LLMUnavailableError("Server down")
        with pytest.raises(APIError) as exc_info:
            await pipeline.chat("question", uuid.uuid4(), [])
        assert exc_info.value.code == ErrorCode.SERVICE_UNAVAILABLE

    @pytest.mark.asyncio
    async def test_timeout_error_is_retryable(self):
        pipeline, _, mock_llm = _make_pipeline()
        mock_llm.generate.side_effect = LLMTimeoutError()
        with pytest.raises(APIError) as exc_info:
            await pipeline.chat("question", uuid.uuid4(), [])
        assert exc_info.value.retryable is True

    @pytest.mark.asyncio
    async def test_unavailable_error_is_retryable(self):
        pipeline, _, mock_llm = _make_pipeline()
        mock_llm.generate.side_effect = LLMUnavailableError()
        with pytest.raises(APIError) as exc_info:
            await pipeline.chat("question", uuid.uuid4(), [])
        assert exc_info.value.retryable is True


# ===========================================================================
# 17–20: JSON repair loop
# ===========================================================================


class TestJsonRepairLoop:
    @pytest.mark.asyncio
    async def test_repair_loop_succeeds_on_second_attempt(self):
        pipeline, _, mock_llm = _make_pipeline(no_llm=True)
        pipeline.llm = mock_llm

        # First call returns broken JSON, second returns valid JSON
        bad_response = MagicMock()
        bad_response.content = "{ invalid json !!!"
        good_response = _make_llm_response(answer="Auth is in service.py", sources=[])
        good_response.content = json.dumps(
            {"answer": "Auth is in service.py", "sources": [], "confidence": "high"}
        )
        mock_llm.generate.side_effect = [bad_response, good_response]

        result = await pipeline.chat("question", uuid.uuid4(), [])
        assert isinstance(result, RepositoryAnswer)
        assert result.answer == "Auth is in service.py"

    @pytest.mark.asyncio
    async def test_repair_loop_calls_llm_twice(self):
        pipeline, _, mock_llm = _make_pipeline(no_llm=True)
        pipeline.llm = mock_llm

        bad_response = MagicMock()
        bad_response.content = "not json at all"
        good_response = MagicMock()
        good_response.content = json.dumps(
            {"answer": "answer", "sources": [], "confidence": "medium"}
        )
        mock_llm.generate.side_effect = [bad_response, good_response]

        await pipeline.chat("question", uuid.uuid4(), [])
        assert mock_llm.generate.call_count == 2

    @pytest.mark.asyncio
    async def test_repair_loop_exhausted_raises_api_error(self):
        pipeline, _, mock_llm = _make_pipeline(no_llm=True)
        pipeline.llm = mock_llm

        # Both attempts return broken JSON
        bad = MagicMock()
        bad.content = "still broken JSON!!!"
        mock_llm.generate.return_value = bad

        with pytest.raises(APIError) as exc_info:
            await pipeline.chat("question", uuid.uuid4(), [])
        assert exc_info.value.code == ErrorCode.INTERNAL_SERVER_ERROR

    @pytest.mark.asyncio
    async def test_markdown_fences_stripped_from_response(self):
        pipeline, _, mock_llm = _make_pipeline(no_llm=True)
        pipeline.llm = mock_llm

        inner_json = json.dumps(
            {"answer": "Auth is here", "sources": [], "confidence": "high"}
        )
        fenced_response = MagicMock()
        fenced_response.content = f"```json\n{inner_json}\n```"
        mock_llm.generate.return_value = fenced_response

        result = await pipeline.chat("question", uuid.uuid4(), [])
        assert result.answer == "Auth is here"


# ===========================================================================
# 21–23: _normalise_history
# ===========================================================================


class TestNormaliseHistory:
    def test_normalise_dict_history(self):
        raw = [{"role": "user", "content": "Hello"}, {"role": "assistant", "content": "Hi"}]
        result = RAGPipeline._normalise_history(raw)
        assert len(result) == 2
        assert all(isinstance(m, ChatMessage) for m in result)
        assert result[0].role == "user"
        assert result[1].role == "assistant"

    def test_normalise_chat_message_history(self):
        messages = [ChatMessage(role="user", content="Q"), ChatMessage(role="assistant", content="A")]
        result = RAGPipeline._normalise_history(messages)
        assert result == messages

    def test_normalise_mixed_history(self):
        mixed = [
            ChatMessage(role="user", content="First"),
            {"role": "assistant", "content": "Second"},
        ]
        result = RAGPipeline._normalise_history(mixed)
        assert len(result) == 2
        assert all(isinstance(m, ChatMessage) for m in result)


# ===========================================================================
# 24–25: _retrieve
# ===========================================================================


class TestRetrieve:
    @pytest.mark.asyncio
    async def test_retrieve_no_retriever_returns_empty(self):
        pipeline = RAGPipeline(retriever=None)
        result = await pipeline._retrieve("query", uuid.uuid4())
        assert result == []

    @pytest.mark.asyncio
    async def test_retrieve_exception_returns_empty(self):
        """Retriever errors are caught — the pipeline degrades gracefully."""
        mock_retriever = AsyncMock()
        mock_retriever.retrieve.side_effect = ConnectionError("DB down")
        pipeline = RAGPipeline(retriever=mock_retriever)

        result = await pipeline._retrieve("query", uuid.uuid4())
        assert result == []


# ===========================================================================
# 26: Acceptance test (Week 1 spec)
# ===========================================================================


class TestAcceptance:
    """
    Acceptance test from week1.md Day 7:

        Ask: "Where is authentication implemented?"
        Expected: RepositoryAnswer with file + line sources.
    """

    @pytest.mark.asyncio
    async def test_acceptance_authentication_question(self):
        """
        End-to-end pipeline smoke test using mocked dependencies.

        Verifies that:
        1. The pipeline accepts the canonical question from the spec.
        2. The response is a RepositoryAnswer with a non-empty answer.
        3. At least one source is returned.
        4. The source points to an auth-related file.
        """
        # Simulate a repository with an auth file indexed
        auth_chunk = _make_chunk(
            file_path="src/auth/service.py",
            content=(
                "class AuthService:\n"
                "    def authenticate(self, user, password):\n"
                "        token = generate_jwt(user)\n"
                "        return token\n"
            ),
            start_line=20,
            end_line=48,
        )

        expected_answer = (
            "Authentication is handled in the AuthService class (src/auth/service.py, "
            "lines 20–48). The class manages JWT token generation and validation."
        )
        llm_response = _make_llm_response(
            answer=expected_answer,
            sources=[
                {
                    "file": "src/auth/service.py",
                    "start_line": 20,
                    "end_line": 48,
                    "symbol": "AuthService",
                }
            ],
            confidence="high",
        )

        mock_retriever = AsyncMock()
        mock_retriever.retrieve.return_value = [auth_chunk]

        mock_llm = AsyncMock()
        mock_llm.generate.return_value = llm_response

        pipeline = RAGPipeline(retriever=mock_retriever, llm_gateway=mock_llm)

        answer = await pipeline.chat(
            question="Where is authentication implemented?",
            repository_id=uuid.uuid4(),
            history=[],
        )

        # Verify structure
        assert isinstance(answer, RepositoryAnswer)
        assert len(answer.answer) > 0
        assert len(answer.sources) > 0

        # Verify source points to auth file
        source_files = [s.file for s in answer.sources]
        assert any("auth" in f for f in source_files), (
            f"Expected an auth-related source, got: {source_files}"
        )

        # Verify confidence is not low for a well-retrieved answer
        assert answer.confidence in ("high", "medium"), (
            f"Expected high or medium confidence, got: {answer.confidence}"
        )
