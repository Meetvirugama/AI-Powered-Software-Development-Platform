"""Authenticated repository-management endpoints."""

from __future__ import annotations

import json
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.errors import APIError, ErrorCode
from app.core.redis import get_redis
from app.models.repository import Repository, SyncStatus
from app.repositories.repository_repository import RepositoryRepository
from app.schemas.repository import (
    CodeSymbolResponse,
    PaginatedResponse,
    RepositoryFileResponse,
    RepositoryResponse,
    SyncJobResponse,
)

router = APIRouter(prefix="/repositories", tags=["repositories"])


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
    repository = _owned_repository(repository_id, request, db)
    repository_repository = RepositoryRepository(db)
    job = repository_repository.create_sync_job(repository.id, user_id)
    try:
        get_redis().rpush(
            "sync_jobs",
            json.dumps({"job_id": str(job.id), "repository_id": str(repository.id), "user_id": str(user_id)}),
        )
        repository_repository.update_sync_status(repository.id, SyncStatus.SYNCING)
    except Exception as exc:
        db.rollback()
        raise APIError(503, ErrorCode.SERVICE_UNAVAILABLE, "Sync queue is unavailable.", retryable=True) from exc
    return SyncJobResponse(job_id=str(job.id))


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
