"""Repository-scoped chat API backed by Meet's RAG pipeline."""

from __future__ import annotations

from typing import Protocol
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from ai.schemas.output import RepositoryAnswer
from app.core.database import get_db
from app.core.errors import APIError, ErrorCode
from app.models.repository import Repository
from app.repositories.repository_repository import RepositoryRepository
from app.schemas.repository import ChatHistoryMessage, RepositoryChatRequest

router = APIRouter(tags=["chat"])


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
    """Return a source-cited answer only for a repository owned by the caller."""
    _owned_repository(repository_id, request, db)
    pipeline = get_rag_chat_pipeline(request)
    answer = await pipeline.chat(payload.question, repository_id, payload.history)
    # Validate third-party pipeline implementations at the HTTP boundary too.
    return RepositoryAnswer.model_validate(answer)


def _request_user_id(request: Request) -> UUID:
    try:
        return UUID(request.state.user_id)
    except (AttributeError, ValueError) as exc:
        raise APIError(401, ErrorCode.UNAUTHORIZED, "Invalid authenticated user.") from exc


def _owned_repository(repository_id: UUID, request: Request, db: Session) -> Repository:
    repository = RepositoryRepository(db).get_for_user(repository_id, _request_user_id(request))
    if repository is None:
        raise APIError(
            404,
            ErrorCode.REPOSITORY_NOT_FOUND,
            "Repository does not exist or you do not have access.",
        )
    return repository
