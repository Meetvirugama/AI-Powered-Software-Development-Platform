"""Repository-scoped chat API backed by the RAG pipeline.

Endpoints
---------
POST   /repositories/{id}/chat                         one complete grounded answer (JSON)
POST   /repositories/{id}/chat/stream                  same answer streamed as Server-Sent Events
GET    /repositories/{id}/chat/conversations           saved conversations (newest first)
POST   /repositories/{id}/chat/conversations           start a conversation
GET    /repositories/{id}/chat/conversations/{cid}     conversation with its messages
PATCH  /repositories/{id}/chat/conversations/{cid}     rename
DELETE /repositories/{id}/chat/conversations/{cid}     delete

When a request carries ``conversation_id`` the server loads the history itself and saves the
exchange after a successful answer, so the conversation survives reloads and devices.
Without it the legacy behaviour is kept: the client sends ``history`` and nothing is stored.
"""

from __future__ import annotations

import asyncio
import inspect
import json
import logging
import uuid
from collections.abc import AsyncIterator
from typing import Any, Protocol
from uuid import UUID

from ai.schemas.output import RepositoryAnswer
from fastapi import APIRouter, Depends, Query, Request, Response, status
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.api.v1.dependencies import get_owned_repository
from app.core.database import get_db
from app.core.errors import APIError, ErrorCode
from app.core.secret_redaction import redact_obj
from app.models.repository import Repository
from app.repositories.chat_repository import ChatRepository
from app.repositories.repository_repository import RepositoryRepository
from app.schemas.repository import (
    ChatConversationCreate,
    ChatConversationDetail,
    ChatConversationList,
    ChatConversationRename,
    ChatConversationSummary,
    ChatHistoryMessage,
    ChatMessageOut,
    RepositoryChatRequest,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["chat"])


def _owned_repository(repository_id: UUID, request: Request, db: Session) -> Repository:
    return get_owned_repository(repository_id, request, db, repo_cls=RepositoryRepository)


def _request_user_uuid(request: Request) -> UUID:
    try:
        return UUID(str(getattr(request.state, "user_id", "")))
    except (ValueError, TypeError) as exc:
        raise APIError(401, ErrorCode.UNAUTHORIZED, "Invalid authenticated user.") from exc


class RAGChatPipeline(Protocol):
    """Public boundary supplied by the repository-aware RAG implementation."""

    async def chat(
        self,
        question: str,
        repository_id: UUID,
        history: list[ChatHistoryMessage],
    ) -> RepositoryAnswer: ...


def get_rag_chat_pipeline(request: Request) -> RAGChatPipeline:
    """Get the startup-configured RAG pipeline, or return a useful API error."""
    pipeline = getattr(request.app.state, "rag_pipeline", None)
    if pipeline is None or not callable(getattr(pipeline, "chat", None)):
        raise APIError(
            503,
            ErrorCode.SERVICE_UNAVAILABLE,
            "Repository chat is not available because the RAG pipeline is not configured.",
            retryable=True,
        )
    return pipeline


# ---------------------------------------------------------------------------
# Shared chat execution
# ---------------------------------------------------------------------------

def _project_memories(db: Session, repository_id: UUID) -> list[Any]:
    try:
        from app.services.memory_service import ProjectMemoryService

        return ProjectMemoryService(db).get_context_memories(repository_id, limit=10)
    except Exception as exc:
        logger.debug("Failed querying project memories for chat: %s", exc)
        return []


def _accepts_kwarg(fn: Any, name: str) -> bool:
    try:
        params = inspect.signature(fn).parameters
    except (TypeError, ValueError):
        return False
    return name in params or any(p.kind == inspect.Parameter.VAR_KEYWORD for p in params.values())


def _resolve_orchestrator(request: Request, pipeline: Any) -> Any:
    from app.core.config import get_settings

    settings = get_settings()
    if not settings.agentic_chat_enabled:
        raise APIError(400, ErrorCode.INVALID_REQUEST, "Agentic chat mode is currently disabled in configuration.")

    orchestrator = getattr(request.app.state, "agent_orchestrator", None)
    if orchestrator is not None:
        return orchestrator

    llm_gateway = getattr(request.app.state, "llm_gateway", None)
    if llm_gateway is None and hasattr(pipeline, "llm_gateway"):
        llm_gateway = pipeline.llm_gateway
    elif llm_gateway is None and hasattr(pipeline, "llm"):
        llm_gateway = pipeline.llm
    if llm_gateway is None:
        raise APIError(
            503,
            ErrorCode.SERVICE_UNAVAILABLE,
            "Agentic chat is unavailable because LLM gateway is not configured.",
            retryable=True,
        )

    from ai.agent.orchestrator import AgentOrchestrator

    return AgentOrchestrator(
        llm_gateway=llm_gateway,
        rag_pipeline=pipeline,
        model=settings.agent_model,
        primary_provider=settings.agent_primary_provider,
        fallback_provider=settings.agent_fallback_provider,
    )


async def _run_agentic(
    request: Request,
    pipeline: Any,
    question: str,
    repository_id: UUID,
    history: list[Any],
    db: Session,
    orchestrator: Any = None,
) -> RepositoryAnswer:
    orchestrator = orchestrator or _resolve_orchestrator(request, pipeline)
    kwargs: dict[str, Any] = {
        "question": question,
        "repository_id": repository_id,
        "history": history,
        "db_session": db,
        "user_id": getattr(getattr(request, "state", None), "user_id", None),
    }
    # Agentic answers now get the same project memory as normal chat.
    if _accepts_kwarg(orchestrator.run, "memory"):
        memories = _project_memories(db, repository_id)
        if memories:
            kwargs["memory"] = memories
    return await orchestrator.run(**kwargs)


async def _run_normal(
    pipeline: Any,
    question: str,
    repository_id: UUID,
    history: list[Any],
    db: Session,
) -> RepositoryAnswer:
    # Fetch active project memories for the repository (ISS-036 / TST-40)
    project_memories = _project_memories(db, repository_id)
    if project_memories and _accepts_kwarg(pipeline.chat, "memory"):
        return await pipeline.chat(question, repository_id, history, memory=project_memories)
    try:
        has_memory_param = "memory" in inspect.signature(pipeline.chat).parameters
    except (TypeError, ValueError):
        has_memory_param = False
    if has_memory_param:
        return await pipeline.chat(question, repository_id, history, memory=project_memories)
    return await pipeline.chat(question, repository_id, history)


def _sanitize(answer: Any) -> RepositoryAnswer:
    """Validate third-party pipeline output and redact secrets at the HTTP boundary."""
    validated = RepositoryAnswer.model_validate(answer)
    return RepositoryAnswer.model_validate(redact_obj(validated.model_dump(mode="json")))


def _resolve_history(
    payload: RepositoryChatRequest, request: Request, repository_id: UUID, db: Session
) -> tuple[list[Any], Any]:
    """Return (history, conversation). Server-side history wins when a conversation is given."""
    if payload.conversation_id is None:
        return payload.history, None
    chats = ChatRepository(db)
    conv = chats.get_owned_conversation(payload.conversation_id, _request_user_uuid(request), repository_id)
    if conv is None:
        raise APIError(404, ErrorCode.RESOURCE_NOT_FOUND, "Conversation not found.")
    return chats.history_for_pipeline(conv.id), conv


async def _publish_completion(request: Request, repository_id: UUID, answer: RepositoryAnswer) -> None:
    """Notify other tabs/devices of the user over the platform SSE channel."""
    caller_uid = str(getattr(getattr(request, "state", None), "user_id", "") or "")
    if not caller_uid:
        return
    try:
        from app.services.sse_redis_streams import publish_chat_token

        await publish_chat_token(
            user_id=caller_uid,
            channel="platform_events",
            session_id=str(repository_id),
            # Unique per answer: a fixed "msg-{repo}" id made clients de-duplicate every later answer.
            message_id=f"msg-{uuid.uuid4().hex}",
            token=answer.answer,
            index=0,
            done=True,
        )
    except Exception as exc:
        logger.debug("Failed publishing chat token over SSE: %s", exc)


def _persist_exchange(db: Session, conv: Any, question: str, answer: RepositoryAnswer, mode: str) -> None:
    try:
        ChatRepository(db).append_exchange(conv, question, answer.model_dump(mode="json"), mode)
    except Exception as exc:  # the answer itself succeeded; never fail the request over history
        logger.warning("chat_history_persist_failed", extra={"conversation_id": str(conv.id), "error": str(exc)})
        try:
            db.rollback()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Chat (complete response)
# ---------------------------------------------------------------------------

@router.post(
    "/repositories/{repository_id}/chat",
    response_model=RepositoryAnswer,
    summary="Ask a grounded question about a repository",
)
async def chat_with_repository(
    repository_id: UUID,
    payload: RepositoryChatRequest,
    request: Request,
    db: Session = Depends(get_db),
) -> RepositoryAnswer:
    """Return a source-cited answer only for a repository owned by the caller (F-03)."""
    await asyncio.to_thread(_owned_repository, repository_id, request, db)
    pipeline = get_rag_chat_pipeline(request)
    history, conv = _resolve_history(payload, request, repository_id, db)

    if payload.mode == "agentic":
        answer = await _run_agentic(request, pipeline, payload.question, repository_id, history, db)
    else:
        answer = await _run_normal(pipeline, payload.question, repository_id, history, db)

    sanitized = _sanitize(answer)
    if conv is not None:
        _persist_exchange(db, conv, payload.question, sanitized, payload.mode)
    await _publish_completion(request, repository_id, sanitized)
    return sanitized


# ---------------------------------------------------------------------------
# Chat (Server-Sent Events stream)
# ---------------------------------------------------------------------------

def _sse(event: str, data: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(data, default=str)}\n\n"


def _fresh_session(request: Request) -> tuple[Session, Any]:
    """Open a DB session for use inside the streaming body.

    Request-scoped dependencies may already be closed while a StreamingResponse is still
    sending, so the stream opens its own session (honouring test dependency overrides).
    """
    factory = request.app.dependency_overrides.get(get_db, get_db)
    gen = factory()
    if inspect.isgenerator(gen):
        return next(gen), gen
    return gen, None


@router.post(
    "/repositories/{repository_id}/chat/stream",
    summary="Ask a grounded question and receive the answer as Server-Sent Events",
    responses={200: {"content": {"text/event-stream": {}}}},
)
async def chat_with_repository_stream(
    repository_id: UUID,
    payload: RepositoryChatRequest,
    request: Request,
    db: Session = Depends(get_db),
) -> StreamingResponse:
    """Stream the answer while it is generated.

    Events (``event:`` line, JSON ``data:`` line):
      - ``meta``    ``{"conversation_id": str | null, "mode": str}``
      - ``status``  ``{"stage": "retrieving" | "generating" | "grounding" | "investigating"}``
      - ``answer``  ``{"text": str}`` — answer text generated so far (replace, don't append)
      - ``done``    the final, grounded RepositoryAnswer (authoritative; citations live here)
      - ``error``   ``{"code": str, "message": str, "retryable": bool}``

    Agentic mode streams status events and then the final answer.
    """
    # Everything that can fail with a normal HTTP error happens before the stream starts.
    await asyncio.to_thread(_owned_repository, repository_id, request, db)
    pipeline = get_rag_chat_pipeline(request)
    history, conv = _resolve_history(payload, request, repository_id, db)
    agent_orchestrator = _resolve_orchestrator(request, pipeline) if payload.mode == "agentic" else None
    memories = _project_memories(db, repository_id) if payload.mode != "agentic" else []
    conv_id = conv.id if conv is not None else None

    async def event_stream() -> AsyncIterator[str]:
        yield _sse("meta", {"conversation_id": str(conv_id) if conv_id else None, "mode": payload.mode})
        stream_db, stream_db_gen = _fresh_session(request)
        try:
            final: RepositoryAnswer | None = None
            if payload.mode == "agentic":
                yield _sse("status", {"stage": "investigating"})
                final = await _run_agentic(
                    request, pipeline, payload.question, repository_id, history, stream_db, agent_orchestrator
                )
            elif callable(getattr(pipeline, "chat_stream", None)):
                kwargs: dict[str, Any] = {}
                if memories and _accepts_kwarg(pipeline.chat_stream, "memory"):
                    kwargs["memory"] = memories
                async for item in pipeline.chat_stream(payload.question, repository_id, history, **kwargs):
                    if await request.is_disconnected():
                        logger.info("chat_stream_client_disconnected", extra={"repo_id": str(repository_id)})
                        return
                    kind = item.get("event")
                    if kind == "status":
                        yield _sse("status", {"stage": item.get("stage")})
                    elif kind == "answer":
                        yield _sse("answer", {"text": item.get("text", "")})
                    elif kind == "done":
                        final = item.get("answer")
            else:
                yield _sse("status", {"stage": "generating"})
                final = await _run_normal(pipeline, payload.question, repository_id, history, stream_db)

            if final is None:
                raise APIError(500, ErrorCode.INTERNAL_SERVER_ERROR, "Chat pipeline produced no answer.")
            sanitized = _sanitize(final)
            if conv_id is not None:
                stream_conv = ChatRepository(stream_db).get_owned_conversation(
                    conv_id, _request_user_uuid(request), repository_id
                )
                if stream_conv is not None:
                    _persist_exchange(stream_db, stream_conv, payload.question, sanitized, payload.mode)
            yield _sse("done", sanitized.model_dump(mode="json"))
            await _publish_completion(request, repository_id, sanitized)
        except APIError as exc:
            yield _sse(
                "error",
                {"code": str(getattr(exc.code, "value", exc.code)), "message": exc.message, "retryable": exc.retryable},
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception("chat_stream_failed", extra={"repo_id": str(repository_id)})
            yield _sse(
                "error",
                {"code": "INTERNAL_SERVER_ERROR", "message": "The answer could not be generated.", "retryable": True},
            )
        finally:
            if stream_db_gen is not None:
                stream_db_gen.close()

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"},
    )


# ---------------------------------------------------------------------------
# Conversations (server-side history)
# ---------------------------------------------------------------------------

def _summary(conv: Any) -> ChatConversationSummary:
    return ChatConversationSummary(
        id=str(conv.id),
        repository_id=str(conv.repository_id),
        title=conv.title,
        message_count=int(conv.message_count or 0),
        created_at=conv.created_at,
        updated_at=conv.updated_at,
    )


def _owned_conversation(request: Request, repository_id: UUID, conversation_id: UUID, db: Session) -> Any:
    _owned_repository(repository_id, request, db)
    conv = ChatRepository(db).get_owned_conversation(conversation_id, _request_user_uuid(request), repository_id)
    if conv is None:
        raise APIError(404, ErrorCode.RESOURCE_NOT_FOUND, "Conversation not found.")
    return conv


@router.get(
    "/repositories/{repository_id}/chat/conversations",
    response_model=ChatConversationList,
    summary="List saved chat conversations for a repository (newest first)",
)
def list_conversations(
    repository_id: UUID,
    request: Request,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=30, ge=1, le=100),
    db: Session = Depends(get_db),
) -> ChatConversationList:
    _owned_repository(repository_id, request, db)
    items, total = ChatRepository(db).list_conversations(
        _request_user_uuid(request), repository_id, offset=(page - 1) * page_size, limit=page_size
    )
    return ChatConversationList(items=[_summary(c) for c in items], total=total)


@router.post(
    "/repositories/{repository_id}/chat/conversations",
    response_model=ChatConversationSummary,
    status_code=status.HTTP_201_CREATED,
    summary="Start a new chat conversation",
)
def create_conversation(
    repository_id: UUID,
    request: Request,
    body: ChatConversationCreate | None = None,
    db: Session = Depends(get_db),
) -> ChatConversationSummary:
    _owned_repository(repository_id, request, db)
    conv = ChatRepository(db).create_conversation(
        _request_user_uuid(request), repository_id, title=body.title if body else None
    )
    return _summary(conv)


@router.get(
    "/repositories/{repository_id}/chat/conversations/{conversation_id}",
    response_model=ChatConversationDetail,
    summary="Get a conversation with its messages",
)
def get_conversation(
    repository_id: UUID,
    conversation_id: UUID,
    request: Request,
    db: Session = Depends(get_db),
) -> ChatConversationDetail:
    conv = _owned_conversation(request, repository_id, conversation_id, db)
    messages = [
        ChatMessageOut(
            id=str(m.id),
            role=m.role,
            content=m.content,
            sources=m.sources or [],
            confidence=m.confidence,
            status=m.status,
            mode=m.mode,
            agent_metadata=m.agent_metadata,
            created_at=m.created_at,
        )
        for m in ChatRepository(db).list_messages(conv.id)
        if m.role in ("user", "assistant")
    ]
    return ChatConversationDetail(**_summary(conv).model_dump(), messages=messages)


@router.patch(
    "/repositories/{repository_id}/chat/conversations/{conversation_id}",
    response_model=ChatConversationSummary,
    summary="Rename a conversation",
)
def rename_conversation(
    repository_id: UUID,
    conversation_id: UUID,
    body: ChatConversationRename,
    request: Request,
    db: Session = Depends(get_db),
) -> ChatConversationSummary:
    conv = _owned_conversation(request, repository_id, conversation_id, db)
    return _summary(ChatRepository(db).rename_conversation(conv, body.title))


@router.delete(
    "/repositories/{repository_id}/chat/conversations/{conversation_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a conversation and its messages",
)
def delete_conversation(
    repository_id: UUID,
    conversation_id: UUID,
    request: Request,
    db: Session = Depends(get_db),
) -> Response:
    conv = _owned_conversation(request, repository_id, conversation_id, db)
    ChatRepository(db).delete_conversation(conv)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
