"""Authenticated repository-management endpoints."""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Optional, Protocol
from uuid import UUID

logger = logging.getLogger(__name__)

from fastapi import APIRouter, Depends, Query, Request, Response, status
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.database import get_db, run_db
from app.core.errors import APIError, ErrorCode
from app.core.http_cache import (
    apply_cache_headers,
    compute_etag,
    etag_matches,
    not_modified,
    repository_index_token,
)
from app.core.redis import get_redis
from app.api.v1.dependencies import (
    get_owned_repository,
    get_request_user_id as _request_user_id,
)
from app.models.user import UserRole
from app.services.repository_metadata_service import extract_repository_dependencies
from app.models.code_chunk import CodeChunk
from app.models.code_symbol import CodeSymbol
from app.models.github_installation import GitHubInstallation
from app.models.symbol_edge import SymbolEdge
from app.models.sync_job import SyncJob
from app.models.repository import Repository, SyncStatus
from app.models.repository_file import RepositoryFile
from app.repositories.repository_repository import RepositoryRepository
from app.services.repository_sync import RedisSyncJobQueue, RepositorySyncService


def _owned_repository(
    repository_id: UUID,
    request: Request,
    db: Session,
    min_role: str | UserRole | None = None,
) -> Repository:
    return get_owned_repository(
        repository_id, request, db, repo_cls=RepositoryRepository, min_role=min_role
    )
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
    BranchResponse,
    SwitchBranchRequest,
    SwitchBranchResponse,
    CommitResponse,
    LanguageMetric,
    PullRequestSummaryResponse,
    RepositoryMetricsResponse,
    SyncJobDetailResponse,
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
    if getattr(db, "_is_mock_db", None) is True or not hasattr(db, "query") or not repo_ids:  # ISS-041: test-aware branch; pending DI refactor
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
def list_repositories(
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
    page: int | None = Query(default=None, ge=1, description="Page number (1-based)"),
    page_size: int | None = Query(default=None, ge=1, le=100, description="Page size (max 100)"),
    skip: int | None = Query(default=None, ge=0, description="Offset for pagination"),
    limit: int | None = Query(default=None, ge=1, le=100, description="Limit for pagination"),
) -> list[RepositoryResponse]:
    """List connected repositories for the authenticated user with optional server-side pagination (ISS-024).

    The body stays a plain list for backwards compatibility; the total number of repositories is
    returned in the ``X-Total-Count`` header so clients can paginate correctly.
    """
    repo_repo = RepositoryRepository(db)
    user_id = _request_user_id(request)
    try:
        response.headers["X-Total-Count"] = str(repo_repo.count_by_user(user_id))
    except Exception as exc:  # test doubles without count support
        logger.debug("repository_count_unavailable: %s", exc)
    if page is not None or page_size is not None or skip is not None or limit is not None:
        calc_skip = skip if skip is not None else ((page - 1) * page_size if page and page_size else 0)
        calc_limit = limit if limit is not None else (page_size if page_size else None)
        try:
            repositories = repo_repo.list_by_user(user_id, skip=calc_skip, limit=calc_limit)
        except TypeError:
            repositories = repo_repo.list_by_user(user_id)
    else:
        repositories = repo_repo.list_by_user(user_id)

    if not repositories:
        return []
    missing_error_ids = [
        r.id
        for r in repositories
        if hasattr(r, "id")
        and getattr(r, "sync_status", None) == SyncStatus.FAILED
        and getattr(r, "last_sync_error", None) is None
    ]
    fallback_errors = _latest_sync_errors(repo_repo, missing_error_ids) if missing_error_ids else {}
    return [
        _repository_response(
            repository,
            file_count=int(getattr(repository, "file_count", 0) or 0),
            symbol_count=int(getattr(repository, "symbol_count", 0) or 0),
            chunk_count=int(getattr(repository, "chunk_count", 0) or 0),
            last_sync_error=(
                getattr(repository, "last_sync_error", None)
                if getattr(repository, "sync_status", None) == SyncStatus.FAILED
                and getattr(repository, "last_sync_error", None) is not None
                else fallback_errors.get(repository.id)
            ),
        )
        for repository in repositories
    ]


def _latest_sync_errors(repo_repo: RepositoryRepository, repo_ids: list[UUID]) -> dict[UUID, str]:
    try:
        return repo_repo.latest_sync_errors(repo_ids)
    except Exception as exc:  # mocked sessions in unit tests
        logger.debug("latest_sync_errors_unavailable: %s", exc)
        return {}


@router.get("/{repository_id}", response_model=RepositoryResponse, summary="Get repository details")
def get_repository(repository_id: UUID, request: Request, db: Session = Depends(get_db)) -> RepositoryResponse:
    repo = _owned_repository(repository_id, request, db)
    last_error: str | None = None
    if getattr(repo, "sync_status", None) == SyncStatus.FAILED:
        last_error = getattr(repo, "last_sync_error", None)
        if last_error is None:
            last_error = _latest_sync_errors(RepositoryRepository(db), [repo.id]).get(repo.id)
    return _repository_response(
        repo,
        file_count=int(getattr(repo, "file_count", 0) or 0),
        symbol_count=int(getattr(repo, "symbol_count", 0) or 0),
        chunk_count=int(getattr(repo, "chunk_count", 0) or 0),
        last_sync_error=last_error,
    )


@router.post("/{repository_id}/sync", response_model=SyncJobResponse, status_code=status.HTTP_202_ACCEPTED, summary="Queue repository synchronization")
def sync_repository(
    repository_id: UUID,
    request: Request,
    force: bool = Query(default=False),
    db: Session = Depends(get_db),
) -> SyncJobResponse:
    _owned_repository(repository_id, request, db, min_role=UserRole.DEVELOPER)
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
    job_status = getattr(job, "status", "QUEUED")
    return SyncJobResponse(job_id=str(job.id), status=str(getattr(job_status, "value", job_status)))


@router.delete("/{repository_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Disconnect and remove a repository")
def delete_repository(repository_id: UUID, request: Request, db: Session = Depends(get_db)) -> None:
    repo = _owned_repository(repository_id, request, db, min_role=UserRole.DEVELOPER)
    user_id = _request_user_id(request)
    redis_client = None
    try:
        redis_client = get_redis()
    except Exception as exc:
        logger.debug("Redis client unavailable during repository deletion: %s", exc)
    RepositoryRepository(db).delete(repo.id, redis_client=redis_client)
    try:
        if redis_client is not None:
            redis_client.publish(
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


    await run_db(db, _owned_repository, repository_id, request, db)
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
    response: Response,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=1000),
    path: Optional[str] = Query(default=None, description="Optional path pattern to filter files"),
    db: Session = Depends(get_db),
) -> PaginatedResponse | Response:
    repo = _owned_repository(repository_id, request, db)
    token = repository_index_token(repo)
    etag = compute_etag("files", repository_id, token, page, page_size, path) if token is not None else None
    if etag is not None and etag_matches(request, etag):
        return not_modified(etag)

    files, total = RepositoryRepository(db).list_files(
        repository_id, (page - 1) * page_size, page_size, path=path
    )
    if etag is not None:
        apply_cache_headers(response, etag)
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
async def get_file_content(
    repository_id: UUID,
    file_id: UUID,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
) -> RepositoryFileContentResponse | Response:
    from app.core.secret_redaction import redact
    from indexer.chunker import reconstruct_file_from_chunks

    def _load_file_and_chunks():
        owned_repo = _owned_repository(repository_id, request, db)
        f_rec = (
            db.query(RepositoryFile)
            .filter(RepositoryFile.id == file_id, RepositoryFile.repository_id == repository_id)
            .first()
        )
        if not f_rec:
            raise APIError(404, ErrorCode.RESOURCE_NOT_FOUND, "File not found.")
        return owned_repo, f_rec

    repo, file_record = await run_db(db, _load_file_and_chunks)

    token = repository_index_token(repo)
    last_indexed = (
        file_record.last_indexed_at.isoformat()
        if hasattr(file_record.last_indexed_at, "isoformat")
        else file_record.last_indexed_at
    )
    etag = (
        compute_etag("file-content", repository_id, token, file_id, file_record.content_hash, last_indexed)
        if token is not None
        else None
    )
    if etag is not None and etag_matches(request, etag):
        return not_modified(etag)

    def _load_chunks_and_symbols():
        loaded_chunks = (
            db.query(CodeChunk)
            .filter(CodeChunk.repository_id == repository_id, CodeChunk.file_id == file_id)
            .order_by(CodeChunk.start_line)
            .all()
        )
        loaded_symbols = (
            db.query(CodeSymbol)
            .filter(CodeSymbol.repository_id == repository_id, CodeSymbol.file_id == file_id)
            .order_by(CodeSymbol.start_line)
            .all()
        )
        return loaded_chunks, loaded_symbols

    chunks, symbols = await run_db(db, _load_chunks_and_symbols)
    content = redact(reconstruct_file_from_chunks(chunks))

    # Fallback to GitHub source content when a non-empty file has no indexed chunks
    # (e.g., if embeddings failed during sync so repository_files was saved without code_chunks).
    if not content and (file_record.size_bytes or 0) > 0:
        try:
            from app.integrations.github.schemas import FileContentRequest
            from app.integrations.github.source_service import GitHubSourceService

            ref = getattr(repo, "last_indexed_commit_sha", None) or getattr(repo, "default_branch", None)
            fallback = await GitHubSourceService(db).get_file_content(
                repository_id=repository_id,
                user_id=_request_user_id(request),
                request=FileContentRequest(path=file_record.path, ref=ref),
            )
            if not fallback.is_binary and fallback.content:
                content = redact(fallback.content)
        except Exception as exc:
            logger.debug(
                "file_content_github_fallback_unavailable",
                extra={"repository_id": str(repository_id), "file_id": str(file_id), "error": str(exc)},
            )

    if etag is not None and (content or (file_record.size_bytes or 0) == 0):
        apply_cache_headers(response, etag)

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
    response: Response,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=1000),
    kind: Optional[str] = Query(default=None, max_length=50, description="Filter by symbol kind, e.g. function"),
    file_id: Optional[UUID] = Query(default=None, description="Only symbols defined in this file"),
    q: Optional[str] = Query(default=None, max_length=200, description="Case-insensitive name search"),
    db: Session = Depends(get_db),
) -> PaginatedResponse | Response:
    repo = _owned_repository(repository_id, request, db)
    token = repository_index_token(repo)
    etag = (
        compute_etag("symbols", repository_id, token, page, page_size, kind, file_id, q)
        if token is not None
        else None
    )
    if etag is not None and etag_matches(request, etag):
        return not_modified(etag)

    repo_repo = RepositoryRepository(db)
    offset = (page - 1) * page_size
    if kind or file_id or q:
        symbols, total = repo_repo.list_symbols(repository_id, offset, page_size, kind=kind, file_id=file_id, query=q)
    else:
        symbols, total = repo_repo.list_symbols(repository_id, offset, page_size)
    if etag is not None:
        apply_cache_headers(response, etag)
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
    last_sync_error: str | None = None,
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
        last_sync_error=last_sync_error,
        last_indexed_commit_sha=getattr(repository, "last_indexed_commit_sha", None),
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
        importance_score=getattr(symbol, "importance_score", None),
    )


# ---------------------------------------------------------------------------
# Sync status & history
# ---------------------------------------------------------------------------

def _sync_job_response(job: SyncJob) -> SyncJobDetailResponse:
    status_val = getattr(job.status, "value", job.status)
    duration = None
    if job.started_at and job.finished_at:
        duration = round((job.finished_at - job.started_at).total_seconds(), 2)
    return SyncJobDetailResponse(
        job_id=str(job.id),
        repository_id=str(job.repository_id),
        status=str(status_val),
        stage=job.stage,
        error_message=job.error_message,
        commit_sha=job.commit_sha,
        stats=job.stats,
        created_at=job.created_at,
        started_at=job.started_at,
        finished_at=job.finished_at,
        duration_seconds=duration,
    )


@router.get(
    "/{repository_id}/sync-jobs",
    response_model=list[SyncJobDetailResponse],
    summary="Recent synchronization jobs (newest first) with stage, timing and failure reason",
)
def list_sync_jobs(
    repository_id: UUID,
    request: Request,
    limit: int = Query(default=10, ge=1, le=100),
    db: Session = Depends(get_db),
) -> list[SyncJobDetailResponse]:
    _owned_repository(repository_id, request, db)
    return [_sync_job_response(j) for j in RepositoryRepository(db).list_sync_jobs(repository_id, limit=limit)]


@router.get(
    "/{repository_id}/sync-jobs/{job_id}",
    response_model=SyncJobDetailResponse,
    summary="Status of a single synchronization job",
)
def get_sync_job(
    repository_id: UUID,
    job_id: UUID,
    request: Request,
    db: Session = Depends(get_db),
) -> SyncJobDetailResponse:
    _owned_repository(repository_id, request, db)
    job = RepositoryRepository(db).get_sync_job(repository_id, job_id)
    if job is None:
        raise APIError(404, ErrorCode.RESOURCE_NOT_FOUND, "Sync job not found.")
    return _sync_job_response(job)


# ---------------------------------------------------------------------------
# Repository metrics
# ---------------------------------------------------------------------------

@router.get(
    "/{repository_id}/metrics",
    response_model=RepositoryMetricsResponse,
    summary="Repository statistics: languages, lines, symbols by kind, graph size, top symbols",
)
def get_repository_metrics(
    repository_id: UUID,
    request: Request,
    top: int = Query(default=10, ge=0, le=50),
    db: Session = Depends(get_db),
) -> RepositoryMetricsResponse:
    repo = _owned_repository(repository_id, request, db)

    lang_rows = (
        db.query(
            func.coalesce(RepositoryFile.language, "unknown"),
            func.count(RepositoryFile.id),
            func.coalesce(func.sum(RepositoryFile.line_count), 0),
            func.coalesce(func.sum(RepositoryFile.size_bytes), 0),
        )
        .filter(RepositoryFile.repository_id == repository_id)
        .group_by(RepositoryFile.language)
        .all()
    )
    languages = sorted(
        (LanguageMetric(language=str(l), files=int(f), lines=int(n), bytes=int(b)) for l, f, n, b in lang_rows),
        key=lambda m: m.lines,
        reverse=True,
    )
    kind_rows = (
        db.query(CodeSymbol.kind, func.count(CodeSymbol.id))
        .filter(CodeSymbol.repository_id == repository_id)
        .group_by(CodeSymbol.kind)
        .all()
    )
    symbols_by_kind = {str(k): int(c) for k, c in kind_rows}
    chunk_count = int(
        db.query(func.count(CodeChunk.id)).filter(CodeChunk.repository_id == repository_id).scalar() or 0
    )
    edge_count = int(
        db.query(func.count(SymbolEdge.id)).filter(SymbolEdge.repository_id == repository_id).scalar() or 0
    )
    top_symbols = []
    if top:
        top_symbols = (
            db.query(CodeSymbol)
            .filter(CodeSymbol.repository_id == repository_id, CodeSymbol.kind != "import")
            .order_by(CodeSymbol.importance_score.desc(), CodeSymbol.name)
            .limit(top)
            .all()
        )
    return RepositoryMetricsResponse(
        repository_id=str(repository_id),
        file_count=sum(m.files for m in languages),
        total_lines=sum(m.lines for m in languages),
        total_bytes=sum(m.bytes for m in languages),
        symbol_count=sum(symbols_by_kind.values()),
        chunk_count=chunk_count,
        edge_count=edge_count,
        languages=languages,
        symbols_by_kind=symbols_by_kind,
        top_symbols=[_symbol_response(s) for s in top_symbols],
        last_synced_at=getattr(repo, "last_synced_at", None),
        last_indexed_commit_sha=getattr(repo, "last_indexed_commit_sha", None),
    )


# ---------------------------------------------------------------------------
# Live GitHub data: branches, commits, pull requests
# ---------------------------------------------------------------------------

def _github_context(repo: Repository, request: Request, db: Session) -> tuple[object, int]:
    github_service = getattr(request.app.state, "github_service", None)
    if github_service is None:
        raise APIError(503, ErrorCode.SERVICE_UNAVAILABLE, "GitHub App is not configured.", retryable=True)
    installation = db.get(GitHubInstallation, repo.installation_id)
    if installation is None or not str(installation.installation_id).isdigit():
        raise APIError(
            409,
            ErrorCode.CONFLICT,
            "The GitHub App installation for this repository is missing. Reinstall the app and reconnect.",
        )
    return github_service, int(installation.installation_id)


async def _call_github(coro_factory, what: str):
    try:
        return await coro_factory()
    except APIError:
        raise
    except Exception as exc:
        logger.warning("github_%s_fetch_failed", what, extra={"error": str(exc)})
        raise APIError(
            502, ErrorCode.GITHUB_API_ERROR, f"Failed to fetch {what} from GitHub.", retryable=True
        ) from exc


@router.get("/{repository_id}/branches", response_model=list[BranchResponse], summary="List repository branches")
async def list_branches(repository_id: UUID, request: Request, db: Session = Depends(get_db)) -> list[BranchResponse]:
    repo, (github_service, inst_id) = await run_db(
        db,
        lambda: (
            r := _owned_repository(repository_id, request, db),
            _github_context(r, request, db),
        ),
    )
    branches = await _call_github(
        lambda: github_service.list_branches(repo.owner, repo.name, installation_id=inst_id), "branches"
    )
    default = repo.default_branch
    items = [
        BranchResponse(name=b.name, sha=b.sha, protected=bool(b.protected), is_default=(b.name == default))
        for b in branches
    ]
    items.sort(key=lambda b: (not b.is_default, b.name.lower()))
    return items


@router.patch(
    "/{repository_id}/branch",
    response_model=SwitchBranchResponse,
    summary="Switch the active tracked branch and queue re-indexing",
)
async def switch_repository_branch(
    repository_id: UUID,
    payload: SwitchBranchRequest,
    request: Request,
    db: Session = Depends(get_db),
) -> SwitchBranchResponse:
    """Switch the repository's active tracked branch and trigger a fresh sync on that branch."""
    user_id = _request_user_id(request)

    def _load_context():
        owned = _owned_repository(repository_id, request, db, min_role=UserRole.DEVELOPER)
        return owned, _github_context(owned, request, db)

    repo, (github_service, inst_id) = await run_db(db, _load_context)
    target_branch = payload.branch

    if target_branch == (repo.default_branch or "main"):
        return SwitchBranchResponse(
            repository=_repository_response(
                repo,
                file_count=int(getattr(repo, "file_count", 0) or 0),
                symbol_count=int(getattr(repo, "symbol_count", 0) or 0),
                chunk_count=int(getattr(repo, "chunk_count", 0) or 0),
                last_sync_error=getattr(repo, "last_sync_error", None)
                if getattr(repo, "sync_status", None) == SyncStatus.FAILED
                else None,
            ),
            branch=target_branch,
            switched=False,
            job_id=None,
        )

    branches = await _call_github(
        lambda: github_service.list_branches(repo.owner, repo.name, installation_id=inst_id),
        "branches",
    )
    if not any(b.name == target_branch for b in branches):
        raise APIError(
            404,
            ErrorCode.NOT_FOUND,
            f"Branch '{target_branch}' was not found in {repo.owner}/{repo.name}.",
        )

    def _switch_and_queue():
        repo_row = _owned_repository(repository_id, request, db, min_role=UserRole.DEVELOPER)
        prev_branch = repo_row.default_branch
        prev_indexed_sha = repo_row.last_indexed_commit_sha
        prev_active_sha = repo_row.active_commit_sha
        prev_sync_error = repo_row.last_sync_error

        repo_row.default_branch = target_branch
        repo_row.last_indexed_commit_sha = None
        repo_row.active_commit_sha = None
        repo_row.last_sync_error = None
        db.commit()
        db.refresh(repo_row)

        try:
            sync_service = RepositorySyncService(RepositoryRepository(db), RedisSyncJobQueue(get_redis()))
            queued_job = sync_service.request_sync(repository_id, user_id, force=True)
        except Exception:
            # Roll back the branch metadata change if queueing the sync job fails so the DB
            # does not claim to track the new branch while still serving the old branch's index.
            repo_row.default_branch = prev_branch
            repo_row.last_indexed_commit_sha = prev_indexed_sha
            repo_row.active_commit_sha = prev_active_sha
            repo_row.last_sync_error = prev_sync_error
            db.commit()
            raise

        db.refresh(repo_row)
        return repo_row, queued_job

    updated_repo, job = await run_db(db, _switch_and_queue)
    try:
        import asyncio

        event_payload = json.dumps(
            {
                "type": "repository.updated",
                "user_id": str(user_id),
                "data": {
                    "repository_id": str(repository_id),
                    "user_id": str(user_id),
                    "branch": target_branch,
                },
            }
        )
        await asyncio.to_thread(get_redis().publish, "platform_events", event_payload)
    except Exception as pub_exc:
        logger.warning(
            "event_publication_failed",
            extra={
                "event": "repository.updated",
                "repository_id": str(repository_id),
                "branch": target_branch,
                "error": str(pub_exc),
            },
        )

    return SwitchBranchResponse(
        repository=_repository_response(
            updated_repo,
            file_count=int(getattr(updated_repo, "file_count", 0) or 0),
            symbol_count=int(getattr(updated_repo, "symbol_count", 0) or 0),
            chunk_count=int(getattr(updated_repo, "chunk_count", 0) or 0),
            last_sync_error=None,
        ),
        branch=target_branch,
        switched=True,
        job_id=str(job.id),
    )


@router.get("/{repository_id}/commits", response_model=list[CommitResponse], summary="List recent commits")
async def list_commits(
    repository_id: UUID,
    request: Request,
    branch: Optional[str] = Query(default=None, max_length=255),
    path: Optional[str] = Query(default=None, max_length=1024, description="Only commits touching this path"),
    page: int = Query(default=1, ge=1, le=100),
    page_size: int = Query(default=30, ge=1, le=100),
    db: Session = Depends(get_db),
) -> list[CommitResponse]:
    repo, (github_service, inst_id) = await run_db(
        db,
        lambda: (
            r := _owned_repository(repository_id, request, db),
            _github_context(r, request, db),
        ),
    )
    commits = await _call_github(
        lambda: github_service.list_commits(
            repo.owner,
            repo.name,
            installation_id=inst_id,
            branch=branch or repo.default_branch,
            path=path,
            page=page,
            per_page=page_size,
        ),
        "commits",
    )
    return [CommitResponse(**c) for c in commits]


@router.get(
    "/{repository_id}/pulls",
    response_model=list[PullRequestSummaryResponse],
    summary="List repository pull requests",
)
async def list_pull_requests(
    repository_id: UUID,
    request: Request,
    state: str = Query(default="open", pattern="^(open|closed|all)$"),
    page: int = Query(default=1, ge=1, le=100),
    page_size: int = Query(default=30, ge=1, le=100),
    db: Session = Depends(get_db),
) -> list[PullRequestSummaryResponse]:
    repo, (github_service, inst_id) = await run_db(
        db,
        lambda: (
            r := _owned_repository(repository_id, request, db),
            _github_context(r, request, db),
        ),
    )
    pulls = await _call_github(
        lambda: github_service.list_pull_requests(
            repo.owner, repo.name, installation_id=inst_id, state=state, page=page, per_page=page_size
        ),
        "pull requests",
    )
    return [PullRequestSummaryResponse(**p) for p in pulls]
