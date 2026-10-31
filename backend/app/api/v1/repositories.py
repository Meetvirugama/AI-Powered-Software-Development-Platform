"""Authenticated repository-management endpoints."""

from __future__ import annotations

import json
import logging
import re
from typing import TYPE_CHECKING, Optional, Protocol
from uuid import UUID

logger = logging.getLogger(__name__)

from fastapi import APIRouter, Depends, Query, Request, status
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.errors import APIError, ErrorCode
from app.core.redis import get_redis
from app.api.v1.dependencies import (
    get_owned_repository,
    get_request_user_id as _request_user_id,
)
from app.services.repository_metadata_service import extract_repository_dependencies
from app.models.code_chunk import CodeChunk
from app.models.code_symbol import CodeSymbol
from app.models.repository import Repository
from app.models.repository_file import RepositoryFile
from app.repositories.repository_repository import RepositoryRepository
from app.services.repository_sync import RedisSyncJobQueue, RepositorySyncService


def _owned_repository(repository_id: UUID, request: Request, db: Session) -> Repository:
    return get_owned_repository(repository_id, request, db, repo_cls=RepositoryRepository)
from app.schemas.repository import (
    CodeSymbolResponse,
    PaginatedResponse,
    RepositoryDependencyResponse,
    RepositoryFileContentResponse,
    RepositoryFileResponse,
    RepositoryResponse,
    RepositorySearchRequest,
    RepositorySearchResponse,
    RepositorySearchResult,
    SyncJobResponse,
)

if TYPE_CHECKING:
    from ai.retrieval.base import CodeChunk as RetrievedCodeChunk

router = APIRouter(prefix="/repositories", tags=["repositories"])


class RetrievalPipeline(Protocol):
    """The Day 5 interface published by Meet's RAG pipeline."""

    async def retrieve(self, query: str, repository_id: UUID, top_k: int) -> list["RetrievedCodeChunk"]: ...


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


def _get_counts_for_repos(
    repo_ids: list[UUID],
    db: Session,
    request: Request | None = None,
) -> tuple[dict[UUID, int], dict[UUID, int], dict[UUID, int]]:
    if getattr(db, "_is_mock_db", None) is True or not hasattr(db, "query") or not repo_ids:
        return {}, {}, {}
    try:
        file_counts = dict(
            db.query(RepositoryFile.repository_id, func.count(RepositoryFile.id))
            .filter(RepositoryFile.repository_id.in_(repo_ids))
            .group_by(RepositoryFile.repository_id)
            .all()
        )
        symbol_counts = dict(
            db.query(CodeSymbol.repository_id, func.count(CodeSymbol.id))
            .filter(CodeSymbol.repository_id.in_(repo_ids))
            .group_by(CodeSymbol.repository_id)
            .all()
        )
        chunk_counts = dict(
            db.query(CodeChunk.repository_id, func.count(CodeChunk.id))
            .filter(CodeChunk.repository_id.in_(repo_ids))
            .group_by(CodeChunk.repository_id)
            .all()
        )
        return file_counts, symbol_counts, chunk_counts
    except Exception as exc:
        req_id = getattr(getattr(request, "state", None), "request_id", None) if request else None
        logger.error(
            "repo_counts_query_failed",
            extra={"repo_ids": [str(rid) for rid in repo_ids], "request_id": req_id, "error": str(exc)},
        )
        raise APIError(
            503,
            ErrorCode.SERVICE_UNAVAILABLE,
            "Database service is temporarily unavailable while querying repository statistics.",
            retryable=True,
        ) from exc


@router.get("", response_model=list[RepositoryResponse], summary="List connected repositories")
def list_repositories(request: Request, db: Session = Depends(get_db)) -> list[RepositoryResponse]:
    repositories = RepositoryRepository(db).list_by_user(_request_user_id(request))
    if not repositories:
        return []
    repo_ids = [r.id for r in repositories if hasattr(r, "id")]
    file_counts, symbol_counts, chunk_counts = _get_counts_for_repos(repo_ids, db, request=request)
    return [
        _repository_response(
            repository,
            file_count=file_counts.get(repository.id),
            symbol_count=symbol_counts.get(repository.id),
            chunk_count=chunk_counts.get(repository.id),
        )
        for repository in repositories
    ]


@router.get("/{repository_id}", response_model=RepositoryResponse, summary="Get repository details")
def get_repository(repository_id: UUID, request: Request, db: Session = Depends(get_db)) -> RepositoryResponse:
    repo = _owned_repository(repository_id, request, db)
    file_counts, symbol_counts, chunk_counts = _get_counts_for_repos([repo.id], db, request=request)
    return _repository_response(
        repo,
        file_count=file_counts.get(repo.id, 0),
        symbol_count=symbol_counts.get(repo.id, 0),
        chunk_count=chunk_counts.get(repo.id, 0),
    )


@router.post("/{repository_id}/sync", response_model=SyncJobResponse, status_code=status.HTTP_202_ACCEPTED, summary="Queue repository synchronization")
def sync_repository(
    repository_id: UUID,
    request: Request,
    force: bool = Query(default=False),
    db: Session = Depends(get_db),
) -> SyncJobResponse:
    user_id = _request_user_id(request)
    service = RepositorySyncService(RepositoryRepository(db), RedisSyncJobQueue(get_redis()))
    job = service.request_sync(repository_id, user_id, force=force)
    try:
        get_redis().publish(
            "platform_events",
            json.dumps(
                {
                    "type": "repository.updated",
                    "user_id": str(user_id),
                    "data": {"repository_id": str(repository_id), "user_id": str(user_id)},
                }
            ),
        )
    except Exception as pub_exc:
        req_id = getattr(getattr(request, "state", None), "request_id", None)
        logger.warning(
            "event_publication_failed",
            extra={
                "event": "repository.updated",
                "repository_id": str(repository_id),
                "job_id": str(job.id),
                "request_id": req_id,
                "error": str(pub_exc),
            },
        )
    return SyncJobResponse(job_id=str(job.id))


@router.delete("/{repository_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Disconnect and remove a repository")
def delete_repository(repository_id: UUID, request: Request, db: Session = Depends(get_db)) -> None:
    user_id = _request_user_id(request)
    repo = _owned_repository(repository_id, request, db)
    RepositoryRepository(db).delete(repo.id)
    try:
        get_redis().publish(
            "platform_events",
            json.dumps(
                {
                    "type": "repository.updated",
                    "user_id": str(user_id),
                    "data": {"repository_id": str(repository_id), "user_id": str(user_id)},
                }
            ),
        )
    except Exception as pub_exc:
        req_id = getattr(getattr(request, "state", None), "request_id", None)
        logger.warning(
            "event_publication_failed",
            extra={
                "event": "repository.updated",
                "repository_id": str(repository_id),
                "request_id": req_id,
                "error": str(pub_exc),
            },
        )


@router.post("/{repository_id}/search", response_model=RepositorySearchResponse, summary="Hybrid code search")
async def search_repository(
    repository_id: UUID,
    payload: RepositorySearchRequest,
    request: Request,
    db: Session = Depends(get_db),
) -> RepositorySearchResponse:
    """Search only code indexed for a repository the authenticated user owns."""
    from app.core.secret_redaction import redact

    import asyncio

    _owned_repository(repository_id, request, db)
    pipeline = get_rag_pipeline(request)
    try:
        chunks = await pipeline.retrieve(payload.query, repository_id, payload.top_k)
    except Exception as exc:
        from ai.retrieval.base import RetrievalUnavailableError
        if isinstance(exc, RetrievalUnavailableError):
            raise APIError(
                503,
                ErrorCode.SERVICE_UNAVAILABLE,
                "Code search is temporarily unavailable. Please retry shortly.",
                retryable=True,
            ) from exc
        raise
    return RepositorySearchResponse(
        query=payload.query,
        results=[
            RepositorySearchResult(
                id=str(chunk.id),
                file_path=chunk.file_path,
                start_line=chunk.start_line,
                end_line=chunk.end_line,
                content=redact(chunk.content),
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
    page_size: int = Query(default=50, ge=1, le=1000),
    path: Optional[str] = Query(default=None, description="Optional path pattern to filter files"),
    db: Session = Depends(get_db),
) -> PaginatedResponse:
    _owned_repository(repository_id, request, db)
    files, total = RepositoryRepository(db).list_files(
        repository_id, (page - 1) * page_size, page_size, path=path
    )
    return PaginatedResponse(page=page, page_size=page_size, total=total, items=[_file_response(item) for item in files])


@router.get(
    "/{repository_id}/files/by-path",
    response_model=RepositoryFileResponse,
    summary="Look up an indexed repository file by exact path",
)
def get_file_by_path(
    repository_id: UUID,
    path: str = Query(..., description="Repository-relative file path"),
    request: Request = None,
    db: Session = Depends(get_db),
) -> RepositoryFileResponse:
    _owned_repository(repository_id, request, db)
    file_record = RepositoryRepository(db).get_file_by_path(repository_id, path)
    if not file_record:
        raise APIError(404, ErrorCode.RESOURCE_NOT_FOUND, f"File '{path}' not found in repository.")
    return _file_response(file_record)


@router.get(
    "/{repository_id}/files/{file_id}/content",
    response_model=RepositoryFileContentResponse,
    summary="Get indexed file content and symbols",
)
def get_file_content(
    repository_id: UUID,
    file_id: UUID,
    request: Request,
    db: Session = Depends(get_db),
) -> RepositoryFileContentResponse:
    from app.core.secret_redaction import redact
    from indexer.chunker import reconstruct_file_from_chunks

    _owned_repository(repository_id, request, db)
    file_record = (
        db.query(RepositoryFile)
        .filter(RepositoryFile.id == file_id, RepositoryFile.repository_id == repository_id)
        .first()
    )
    if not file_record:
        raise APIError(404, ErrorCode.RESOURCE_NOT_FOUND, "File not found.")

    chunks = (
        db.query(CodeChunk)
        .filter(CodeChunk.repository_id == repository_id, CodeChunk.file_id == file_id)
        .order_by(CodeChunk.start_line)
        .all()
    )
    content = redact(reconstruct_file_from_chunks(chunks))

    symbols = (
        db.query(CodeSymbol)
        .filter(CodeSymbol.repository_id == repository_id, CodeSymbol.file_id == file_id)
        .order_by(CodeSymbol.start_line)
        .all()
    )

    return RepositoryFileContentResponse(
        id=str(file_record.id),
        path=file_record.path,
        language=file_record.language,
        size_bytes=file_record.size_bytes,
        line_count=file_record.line_count,
        content=content,
        symbols=[_symbol_response(s) for s in symbols],
    )


@router.get("/{repository_id}/symbols", response_model=PaginatedResponse, summary="List extracted repository symbols")
def list_symbols(
    repository_id: UUID,
    request: Request,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=1000),
    db: Session = Depends(get_db),
) -> PaginatedResponse:
    _owned_repository(repository_id, request, db)
    symbols, total = RepositoryRepository(db).list_symbols(repository_id, (page - 1) * page_size, page_size)
    return PaginatedResponse(page=page, page_size=page_size, total=total, items=[_symbol_response(item) for item in symbols])


_extract_dependencies = extract_repository_dependencies


@router.get(
    "/{repository_id}/dependencies",
    response_model=list[RepositoryDependencyResponse],
    summary="List top-level repository dependencies",
)
def list_dependencies(
    repository_id: UUID,
    request: Request,
    db: Session = Depends(get_db),
) -> list[RepositoryDependencyResponse]:
    """Return top-level dependencies discovered in repository manifest files."""
    _owned_repository(repository_id, request, db)
    return extract_repository_dependencies(repository_id, db)


def _repository_response(
    repository: Repository,
    file_count: int | None = None,
    symbol_count: int | None = None,
    chunk_count: int | None = None,
) -> RepositoryResponse:
    owner = getattr(repository, "owner", "")
    name = getattr(repository, "name", "")
    full_name = f"{owner}/{name}" if owner and name else getattr(repository, "full_name", "")
    sync_status = repository.sync_status
    if hasattr(sync_status, "value"):
        sync_status = sync_status.value

    return RepositoryResponse(
        id=str(repository.id),
        github_repo_id=str(repository.github_repo_id),
        owner=owner,
        name=name,
        full_name=full_name,
        default_branch=getattr(repository, "default_branch", "main"),
        language=getattr(repository, "language", None),
        sync_status=str(sync_status),
        last_synced_at=getattr(repository, "last_synced_at", None),
        description=getattr(repository, "description", None),
        framework=getattr(repository, "framework", None),
        file_count=file_count,
        symbol_count=symbol_count,
        chunk_count=chunk_count,
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
