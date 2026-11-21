"""Regression tests for the Module 5 (RAG / retrieval) and Module 6 (repository chat) audit fixes.

Covers:
- Conversation history now reaches the LLM prompt (it was budgeted but never sent).
- Follow-up questions borrow the previous question for retrieval.
- Context fitting skips oversized items instead of stopping, and compresses the top chunk.
- History is capped so it cannot starve code context.
- RAGPipeline.chat_stream streams answer text and ends with a grounded answer.
- LLMGateway.generate_stream does not duplicate output via mid-stream fallback.
- Server-side conversations: create, persist exchanges, reload, tenant isolation, delete.
- POST /chat/stream (SSE) and its rate-limit rule.
"""

from __future__ import annotations

import json
import re
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from ai.context.builder import ChatMessage, ContextBuilder
from ai.context.chat_context import compress_chunk
from ai.context.renderers import format_chunk
from ai.context.token_budget import count_tokens, fit_items
from ai.llm.schemas import LLMResponse, LLMResponseChunk, LLMUnavailableError
from ai.pipeline import RAGPipeline
from ai.retrieval.base import CodeChunk
from ai.schemas.output import RepositoryAnswer
from ai.schemas.prompt_builder import PromptBuilder
from app.core.security import create_access_token
from app.models.chat_conversation import ChatConversation, ChatMessageRecord
from app.models.github_installation import GitHubInstallation
from app.models.repository import Repository
from app.models.user import User

ANSWER_JSON = json.dumps(
    {
        "answer": "Authentication is handled in the auth service.",
        "sources": [{"file": "src/auth/service.py", "start_line": 10, "end_line": 20, "symbol": None}],
        "confidence": "high",
    }
)


def _chunk(content: str = "def authenticate(user, pw):\n    return True", start: int = 10, end: int = 20) -> CodeChunk:
    return CodeChunk(
        id=uuid.uuid4(),
        repository_id=uuid.uuid4(),
        file_id=uuid.uuid4(),
        symbol_id=None,
        content=content,
        token_count=len(content.split()),
        start_line=start,
        end_line=end,
        content_hash="h",
        score=0.9,
        file_path="src/auth/service.py",
    )


def _pipeline(retriever=None, llm=None) -> RAGPipeline:
    retriever = retriever or SimpleNamespace(retrieve=AsyncMock(return_value=[_chunk()]))
    llm = llm or SimpleNamespace(generate=AsyncMock(return_value=LLMResponse(content=ANSWER_JSON, model="m")))
    return RAGPipeline(retriever=retriever, llm_gateway=llm, model="test-model")


# ---------------------------------------------------------------------------
# Module 5 — history, retrieval query, context fitting
# ---------------------------------------------------------------------------

def test_prompt_includes_fenced_history_when_given() -> None:
    messages = PromptBuilder().build_chat_prompt(
        context="def f(): ...", question="Who calls it?", history="USER: What does f do?"
    )
    user = messages[-1].content
    assert "CONVERSATION HISTORY" in user
    assert "What does f do?" in user
    assert user.index("CONVERSATION HISTORY") < user.index("USER QUESTION")
    assert "What does f do?" not in messages[0].content  # never in the system prompt


@pytest.mark.asyncio
async def test_pipeline_sends_history_to_llm() -> None:
    pipeline = _pipeline()
    await pipeline.chat(
        "And who calls it?",
        uuid.uuid4(),
        [
            {"role": "user", "content": "What does authenticate do?"},
            {"role": "assistant", "content": "It checks the password."},
        ],
    )
    request = pipeline.llm.generate.await_args.args[0]
    prompt_text = "\n".join(m.content for m in request.messages)
    assert "It checks the password." in prompt_text


@pytest.mark.asyncio
async def test_follow_up_question_borrows_previous_question_for_retrieval() -> None:
    pipeline = _pipeline()
    await pipeline.chat(
        "who calls it?",
        uuid.uuid4(),
        [{"role": "user", "content": "Explain authenticate_user"}, {"role": "assistant", "content": "..."}],
    )
    query = pipeline.retriever.retrieve.await_args.kwargs["query"]
    assert "authenticate_user" in query and "who calls it?" in query


def test_standalone_long_question_is_not_rewritten() -> None:
    q = "Where in the backend is the rate limiter configured for the repository chat endpoints today"
    history = [ChatMessage(role="user", content="Explain authenticate_user")]
    assert RAGPipeline._retrieval_query(q, history) == q


def test_fit_items_skips_oversized_item_and_keeps_smaller_ones() -> None:
    big, small = _chunk("word " * 3000), _chunk("x = 1")
    used, kept = fit_items([big, small], 200, format_chunk)
    assert kept == [small] and used > 0


def test_top_chunk_is_compressed_instead_of_dropped() -> None:
    long_body = "\n".join(f"line_{i} = compute_value({i})" for i in range(800))
    top = _chunk(long_body, start=100, end=899)
    ctx = ContextBuilder(max_context_tokens=2_000).build(chunks=[top], memory=[], history=[])
    assert ctx.code_chunks, "best-ranked chunk must not vanish from the prompt"
    kept = ctx.code_chunks[0]
    assert kept.start_line == 100 and kept.end_line < 899
    assert "more lines omitted" in kept.content
    assert compress_chunk(top, 50) is None  # too small a budget to be useful


def test_history_cannot_starve_code_context() -> None:
    history = [ChatMessage(role="user", content="lorem ipsum " * 400) for _ in range(10)]
    ctx = ContextBuilder(max_context_tokens=4_000).build(chunks=[_chunk()], memory=[], history=history)
    assert ctx.code_chunks, "code must still fit when history is long"
    assert ctx.history_tokens <= int((4_000 - ctx.overhead_tokens) * 0.3)


# ---------------------------------------------------------------------------
# Module 5 — streaming
# ---------------------------------------------------------------------------

class _StreamingLLM:
    def __init__(self, text: str, step: int = 7) -> None:
        self._text, self._step = text, step
        self.generate = AsyncMock(return_value=LLMResponse(content=ANSWER_JSON, model="m"))

    async def generate_stream(self, request):
        for i in range(0, len(self._text), self._step):
            yield LLMResponseChunk(delta=self._text[i : i + self._step], index=i)


@pytest.mark.asyncio
async def test_chat_stream_emits_progress_and_grounded_final_answer() -> None:
    pipeline = _pipeline(llm=_StreamingLLM(ANSWER_JSON))
    events = [e async for e in pipeline.chat_stream("Where is auth?", uuid.uuid4(), [])]
    kinds = [e["event"] for e in events]
    assert kinds[0] == "status" and kinds[-1] == "done"
    texts = [e["text"] for e in events if e["event"] == "answer"]
    assert texts and texts[-1].startswith("Authentication is handled")
    assert all(b.startswith(a) for a, b in zip(texts, texts[1:]))  # snapshots grow monotonically
    final = events[-1]["answer"]
    assert isinstance(final, RepositoryAnswer) and final.answer == "Authentication is handled in the auth service."
    pipeline.llm.generate.assert_not_awaited()


@pytest.mark.asyncio
async def test_chat_stream_falls_back_when_streamed_json_is_invalid() -> None:
    pipeline = _pipeline(llm=_StreamingLLM('{"answer": "partial'))
    events = [e async for e in pipeline.chat_stream("Where is auth?", uuid.uuid4(), [])]
    assert events[-1]["event"] == "done"
    assert events[-1]["answer"].answer == "Authentication is handled in the auth service."
    pipeline.llm.generate.assert_awaited_once()


@pytest.mark.asyncio
async def test_gateway_stream_does_not_fall_back_after_output_started() -> None:
    from ai.llm.client import LLMGateway

    class Primary:
        provider_name = "primary"

        async def generate_stream(self, request):
            yield LLMResponseChunk(delta="Hello ", index=0)
            raise LLMUnavailableError("connection dropped", provider="primary")

    class Fallback:
        provider_name = "fallback"
        called = False

        async def generate_stream(self, request):
            Fallback.called = True
            yield LLMResponseChunk(delta="Hello again", index=0)

    from ai.llm.schemas import LLMRequest, Message

    gateway = LLMGateway(provider=Primary(), fallback_provider=Fallback())
    received = []
    with pytest.raises(LLMUnavailableError):
        async for chunk in gateway.generate_stream(LLMRequest(model="m", messages=[Message.user("hi")])):
            received.append(chunk.delta)
    assert received == ["Hello "]
    assert Fallback.called is False


# ---------------------------------------------------------------------------
# Module 6 — conversations and streaming API
# ---------------------------------------------------------------------------

def _seed(db_session):
    user = User(id=uuid.uuid4(), github_id=f"gh_{uuid.uuid4().hex[:8]}", login=f"c_{uuid.uuid4().hex[:6]}")
    db_session.add(user)
    db_session.flush()
    inst = GitHubInstallation(
        id=uuid.uuid4(), user_id=user.id, installation_id=str(uuid.uuid4().int % 10**9),
        account_login=user.login, permissions={},
    )
    db_session.add(inst)
    db_session.flush()
    repo = Repository(
        id=uuid.uuid4(), user_id=user.id, installation_id=inst.id,
        github_repo_id=f"r_{uuid.uuid4().hex[:8]}", owner=user.login, name="repo", default_branch="main",
    )
    db_session.add(repo)
    db_session.commit()
    token, _ = create_access_token(str(user.id))
    return user, repo, {"Authorization": f"Bearer {token}"}


class _RecordingPipeline:
    """Fake RAG pipeline recording the history it receives."""

    def __init__(self) -> None:
        self.histories: list[list] = []

    async def chat(self, question, repository_id, history, memory=None):
        self.histories.append([dict(role=getattr(h, "role", None) or h["role"],
                                    content=getattr(h, "content", None) or h["content"]) for h in history])
        return RepositoryAnswer(answer=f"Answer to: {question}", sources=[], confidence="medium")

    async def chat_stream(self, question, repository_id, history, memory=None):
        self.histories.append(list(history))
        yield {"event": "status", "stage": "retrieving"}
        yield {"event": "answer", "text": "Answer to:"}
        yield {"event": "done", "answer": RepositoryAnswer(answer=f"Answer to: {question}", sources=[], confidence="high")}


def _parse_sse(body: str) -> list[tuple[str, dict]]:
    events = []
    for block in body.strip().split("\n\n"):
        name = re.search(r"^event: (.+)$", block, re.M).group(1)
        data = json.loads(re.search(r"^data: (.+)$", block, re.M).group(1))
        events.append((name, data))
    return events


def test_conversation_history_is_stored_and_replayed_by_server(client: TestClient, db_session, monkeypatch) -> None:
    _, repo, headers = _seed(db_session)
    pipeline = _RecordingPipeline()
    monkeypatch.setattr(client.app.state, "rag_pipeline", pipeline, raising=False)
    base = f"/api/v1/repositories/{repo.id}/chat"

    conv = client.post(f"{base}/conversations", json={}, headers=headers)
    assert conv.status_code == 201
    conv_id = conv.json()["id"]

    first = client.post(base, json={"question": "What does auth do?", "conversation_id": conv_id}, headers=headers)
    assert first.status_code == 200
    # Client-supplied history is ignored when the server owns the conversation.
    second = client.post(
        base,
        json={"question": "Who calls it?", "conversation_id": conv_id,
              "history": [{"role": "user", "content": "forged"}]},
        headers=headers,
    )
    assert second.status_code == 200
    assert pipeline.histories[1] == [
        {"role": "user", "content": "What does auth do?"},
        {"role": "assistant", "content": "Answer to: What does auth do?"},
    ]

    detail = client.get(f"{base}/conversations/{conv_id}", headers=headers).json()
    assert detail["title"] == "What does auth do?"
    assert [m["role"] for m in detail["messages"]] == ["user", "assistant", "user", "assistant"]
    assert detail["message_count"] == 4

    listing = client.get(f"{base}/conversations", headers=headers).json()
    assert listing["total"] == 1 and listing["items"][0]["id"] == conv_id


def test_conversations_are_tenant_isolated(client: TestClient, db_session, monkeypatch) -> None:
    _, repo, headers = _seed(db_session)
    _, other_repo, other_headers = _seed(db_session)
    monkeypatch.setattr(client.app.state, "rag_pipeline", _RecordingPipeline(), raising=False)
    conv_id = client.post(f"/api/v1/repositories/{repo.id}/chat/conversations", json={}, headers=headers).json()["id"]

    # Another user cannot read it, nor use it from their own repository.
    assert client.get(f"/api/v1/repositories/{repo.id}/chat/conversations/{conv_id}", headers=other_headers).status_code == 404
    resp = client.post(
        f"/api/v1/repositories/{other_repo.id}/chat",
        json={"question": "hi", "conversation_id": conv_id},
        headers=other_headers,
    )
    assert resp.status_code == 404


def test_delete_conversation_removes_messages(client: TestClient, db_session, monkeypatch) -> None:
    _, repo, headers = _seed(db_session)
    monkeypatch.setattr(client.app.state, "rag_pipeline", _RecordingPipeline(), raising=False)
    base = f"/api/v1/repositories/{repo.id}/chat"
    conv_id = client.post(f"{base}/conversations", json={}, headers=headers).json()["id"]
    client.post(base, json={"question": "q", "conversation_id": conv_id}, headers=headers)

    assert client.delete(f"{base}/conversations/{conv_id}", headers=headers).status_code == 204
    assert db_session.get(ChatConversation, uuid.UUID(conv_id)) is None
    assert db_session.query(ChatMessageRecord).filter_by(conversation_id=uuid.UUID(conv_id)).count() == 0


def test_stream_endpoint_emits_sse_and_saves_exchange(client: TestClient, db_session, monkeypatch) -> None:
    _, repo, headers = _seed(db_session)
    monkeypatch.setattr(client.app.state, "rag_pipeline", _RecordingPipeline(), raising=False)
    base = f"/api/v1/repositories/{repo.id}/chat"
    conv_id = client.post(f"{base}/conversations", json={}, headers=headers).json()["id"]

    resp = client.post(f"{base}/stream", json={"question": "Where is auth?", "conversation_id": conv_id}, headers=headers)
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/event-stream")
    events = _parse_sse(resp.text)
    names = [n for n, _ in events]
    assert names[0] == "meta" and names[-1] == "done"
    assert events[0][1]["conversation_id"] == conv_id
    assert ("answer", {"text": "Answer to:"}) in events
    assert events[-1][1]["answer"] == "Answer to: Where is auth?"

    detail = client.get(f"{base}/conversations/{conv_id}", headers=headers).json()
    assert detail["message_count"] == 2


def test_chat_stream_route_shares_the_chat_rate_limit() -> None:
    from app.core.rate_limit import _rules

    rule = next(r for r in _rules("/api/v1") if r.name == "repo_chat")
    assert rule.path_pattern.match("/api/v1/repositories/abc/chat/stream")
    assert rule.path_pattern.match("/api/v1/repositories/abc/chat")
    assert not rule.path_pattern.match("/api/v1/repositories/abc/chat/conversations")
