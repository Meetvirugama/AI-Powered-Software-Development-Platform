"""Repository-scoped chat API backed by Meet's RAG pipeline."""

from __future__ import annotations

import asyncio
from typing import Protocol
from uuid import UUID

from ai.schemas.output import RepositoryAnswer
from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.api.v1.dependencies import (
    get_owned_repository,
)
from app.core.database import get_db
from app.core.errors import APIError, ErrorCode
from app.core.secret_redaction import redact_obj
from app.models.repository import Repository
from app.repositories.repository_repository import RepositoryRepository
from app.schemas.repository import ChatHistoryMessage, RepositoryChatRequest

router = APIRouter(tags=["chat"])


def _owned_repository(repository_id: UUID, request: Request, db: Session) -> Repository:
    return get_owned_repository(repository_id, request, db, repo_cls=RepositoryRepository)


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

    if payload.mode == "agentic":
        from app.core.config import get_settings
        settings = get_settings()
        from ai.agent.orchestrator import AgentOrchestrator

        if not settings.agentic_chat_enabled:
            raise APIError(
                400,
                ErrorCode.INVALID_REQUEST,
                "Agentic chat mode is currently disabled in configuration.",
            )

        orchestrator = getattr(request.app.state, "agent_orchestrator", None)
        if orchestrator is None:
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

            orchestrator = AgentOrchestrator(
                llm_gateway=llm_gateway,
                rag_pipeline=pipeline,
                model=settings.agent_model,
                primary_provider=settings.agent_primary_provider,
                fallback_provider=settings.agent_fallback_provider,
            )

        user_id = getattr(getattr(request, "state", None), "user_id", None)
        answer = await orchestrator.run(
            question=payload.question,
            repository_id=repository_id,
            history=payload.history,
            db_session=db,
            user_id=user_id,
        )
    else:
        answer = await pipeline.chat(payload.question, repository_id, payload.history)

    # Validate third-party pipeline implementations and redact any secrets at the HTTP boundary.
    validated = RepositoryAnswer.model_validate(answer)
    return RepositoryAnswer.model_validate(redact_obj(validated.model_dump(mode="json")))
