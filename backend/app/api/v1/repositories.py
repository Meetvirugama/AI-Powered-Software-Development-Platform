"""Authenticated repository-management endpoints."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.errors import APIError, ErrorCode
from app.core.redis import get_redis
from app.models.repository import Repository
from app.repositories.repository_repository import RepositoryRepository
from app.services.repository_sync import RedisSyncJobQueue, RepositorySyncService
from app.schemas.repository import (
    CodeSymbolResponse,
    PaginatedResponse,
    RepositoryFileResponse,
    RepositoryResponse,
    RepositorySearchRequest,
    RepositorySearchResponse,
    RepositorySearchResult,
    SyncJobResponse,
)

if TYPE_CHECKING:
    from ai.retrieval.base import CodeChunk

router = APIRouter(prefix="/repositories", tags=["repositories"])


class RetrievalPipeline(Protocol):
    """The Day 5 interface published by Meet's RAG pipeline."""

    async def retrieve(self, query: str, repository_id: UUID, top_k: int) -> list["CodeChunk"]: ...


def get_rag_pipeline(request: Request) -> RetrievalPipeline:
    """Return the application-configured RAG pipeline without coupling routes to it.

    Application startup (or an integration test) supplies the implementation on
    ``app.state.rag_pipeline``. Keeping this boundary explicit lets the API own
    authentication and response shaping while Meet's module owns retrieval.
    """
    pipeline = getattr(request.app.state, "rag_pipeline", None)
    if pipeline is None:
        raise APIError(
            503,
            ErrorCode.SERVICE_UNAVAILABLE,
            "Repository search is not available because the retrieval pipeline is not configured.",
            retryable=True,
        )
    return pipeline


@router.get("", response_model=list[RepositoryResponse], summary="List connected repositories")
def list_repositories(request: Request, db: Session = Depends(get_db)) -> list[RepositoryResponse]:
    repositories = RepositoryRepository(db).list_by_user(_request_user_id(request))
    return [_repository_response(repository) for repository in repositories]


@router.get("/{repository_id}", response_model=RepositoryResponse, summary="Get repository details")
def get_repository(repository_id: UUID, request: Request, db: Session = Depends(get_db)) -> RepositoryResponse:
    return _repository_response(_owned_repository(repository_id, request, db))


@router.post("/{repository_id}/sync", response_model=SyncJobResponse, status_code=status.HTTP_202_ACCEPTED, summary="Queue repository synchronization")
def sync_repository(repository_id: UUID, request: Request, db: Session = Depends(get_db)) -> SyncJobResponse:
    user_id = _request_user_id(request)
    service = RepositorySyncService(RepositoryRepository(db), RedisSyncJobQueue(get_redis()))
    job = service.request_sync(repository_id, user_id)
    return SyncJobResponse(job_id=str(job.id))


@router.post("/{repository_id}/search", response_model=RepositorySearchResponse, summary="Hybrid code search")
async def search_repository(
    repository_id: UUID,
    payload: RepositorySearchRequest,
    request: Request,
    db: Session = Depends(get_db),
    pipeline: RetrievalPipeline = Depends(get_rag_pipeline),
) -> RepositorySearchResponse:
    """Search only code indexed for a repository the authenticated user owns."""
    _owned_repository(repository_id, request, db)
    chunks = await pipeline.retrieve(payload.query, repository_id, payload.top_k)
    return RepositorySearchResponse(
        query=payload.query,
        results=[
            RepositorySearchResult(
                id=str(chunk.id),
                file_path=chunk.file_path,
                start_line=chunk.start_line,
                end_line=chunk.end_line,
                content=chunk.content,
                score=chunk.score,
            )
            for chunk in chunks
        ],
    )


@router.get("/{repository_id}/files", response_model=PaginatedResponse, summary="List indexed repository files")
def list_files(
    repository_id: UUID,
    request: Request,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=100),
    db: Session = Depends(get_db),
) -> PaginatedResponse:
    _owned_repository(repository_id, request, db)
    files, total = RepositoryRepository(db).list_files(repository_id, (page - 1) * page_size, page_size)
    return PaginatedResponse(page=page, page_size=page_size, total=total, items=[_file_response(item) for item in files])


@router.get("/{repository_id}/symbols", response_model=PaginatedResponse, summary="List extracted repository symbols")
def list_symbols(
    repository_id: UUID,
    request: Request,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=100),
    db: Session = Depends(get_db),
) -> PaginatedResponse:
    _owned_repository(repository_id, request, db)
    symbols, total = RepositoryRepository(db).list_symbols(repository_id, (page - 1) * page_size, page_size)
    return PaginatedResponse(page=page, page_size=page_size, total=total, items=[_symbol_response(item) for item in symbols])


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


def _repository_response(repository: Repository) -> RepositoryResponse:
    return RepositoryResponse(
        id=str(repository.id),
        github_repo_id=repository.github_repo_id,
        owner=repository.owner,
        name=repository.name,
        full_name=f"{repository.owner}/{repository.name}",
        default_branch=repository.default_branch,
        language=repository.language,
        sync_status=repository.sync_status.value,
        last_synced_at=repository.last_synced_at,
    )


def _file_response(file: object) -> RepositoryFileResponse:
    return RepositoryFileResponse(
        id=str(file.id), path=file.path, language=file.language, size_bytes=file.size_bytes,
        line_count=file.line_count, content_hash=file.content_hash, last_indexed_at=file.last_indexed_at,
    )


def _symbol_response(symbol: object) -> CodeSymbolResponse:
    return CodeSymbolResponse(
        id=str(symbol.id), file_id=str(symbol.file_id), name=symbol.name, kind=symbol.kind,
        start_line=symbol.start_line, end_line=symbol.end_line, signature=symbol.signature,
        parent_id=str(symbol.parent_id) if symbol.parent_id else None,
    )
