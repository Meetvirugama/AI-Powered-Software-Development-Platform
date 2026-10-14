"""Authenticated repository-management endpoints."""

from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING, Protocol
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, status
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.errors import APIError, ErrorCode
from app.core.redis import get_redis
from app.models.code_chunk import CodeChunk
from app.models.code_symbol import CodeSymbol
from app.models.repository import Repository
from app.models.repository_file import RepositoryFile
from app.repositories.repository_repository import RepositoryRepository
from app.services.repository_sync import RedisSyncJobQueue, RepositorySyncService
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
) -> tuple[dict[UUID, int], dict[UUID, int], dict[UUID, int]]:
    if not hasattr(db, "query") or not repo_ids:
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
    except Exception:
        return {}, {}, {}


@router.get("", response_model=list[RepositoryResponse], summary="List connected repositories")
def list_repositories(request: Request, db: Session = Depends(get_db)) -> list[RepositoryResponse]:
    repositories = RepositoryRepository(db).list_by_user(_request_user_id(request))
    if not repositories:
        return []
    repo_ids = [r.id for r in repositories if hasattr(r, "id")]
    file_counts, symbol_counts, chunk_counts = _get_counts_for_repos(repo_ids, db)
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
    file_counts, symbol_counts, chunk_counts = _get_counts_for_repos([repo.id], db)
    return _repository_response(
        repo,
        file_count=file_counts.get(repo.id, 0),
        symbol_count=symbol_counts.get(repo.id, 0),
        chunk_count=chunk_counts.get(repo.id, 0),
    )


@router.post("/{repository_id}/sync", response_model=SyncJobResponse, status_code=status.HTTP_202_ACCEPTED, summary="Queue repository synchronization")
def sync_repository(repository_id: UUID, request: Request, db: Session = Depends(get_db)) -> SyncJobResponse:
    user_id = _request_user_id(request)
    service = RepositorySyncService(RepositoryRepository(db), RedisSyncJobQueue(get_redis()))
    job = service.request_sync(repository_id, user_id)
    return SyncJobResponse(job_id=str(job.id))


@router.delete("/{repository_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Disconnect and remove a repository")
def delete_repository(repository_id: UUID, request: Request, db: Session = Depends(get_db)) -> None:
    repo = _owned_repository(repository_id, request, db)
    RepositoryRepository(db).delete(repo.id)


@router.post("/{repository_id}/search", response_model=RepositorySearchResponse, summary="Hybrid code search")
async def search_repository(
    repository_id: UUID,
    payload: RepositorySearchRequest,
    request: Request,
    db: Session = Depends(get_db),
) -> RepositorySearchResponse:
    """Search only code indexed for a repository the authenticated user owns."""
    _owned_repository(repository_id, request, db)
    pipeline = get_rag_pipeline(request)
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
    content = "\n".join(chunk.content for chunk in chunks)

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
    page_size: int = Query(default=50, ge=1, le=100),
    db: Session = Depends(get_db),
) -> PaginatedResponse:
    _owned_repository(repository_id, request, db)
    symbols, total = RepositoryRepository(db).list_symbols(repository_id, (page - 1) * page_size, page_size)
    return PaginatedResponse(page=page, page_size=page_size, total=total, items=[_symbol_response(item) for item in symbols])


def _extract_dependencies(repository_id: UUID, db: Session) -> list[RepositoryDependencyResponse]:
    """Parse top-level dependency manifests indexed for this repository."""
    if not hasattr(db, "query"):
        return []

    try:
        manifest_files = (
            db.query(RepositoryFile)
            .filter(
                RepositoryFile.repository_id == repository_id,
                or_(
                    RepositoryFile.path.endswith("package.json"),
                    RepositoryFile.path.endswith("requirements.txt"),
                    RepositoryFile.path.endswith("Pipfile"),
                    RepositoryFile.path.endswith("pyproject.toml"),
                    RepositoryFile.path.endswith("go.mod"),
                    RepositoryFile.path.endswith("Cargo.toml"),
                ),
            )
            .all()
        )

        dependencies: list[RepositoryDependencyResponse] = []
        for file in manifest_files:
            chunks = (
                db.query(CodeChunk.content)
                .filter(
                    CodeChunk.repository_id == repository_id,
                    CodeChunk.file_id == file.id,
                )
                .order_by(CodeChunk.start_line)
                .all()
            )
            content = "\n".join(c[0] for c in chunks)
            if file.path.endswith("package.json"):
                try:
                    data = json.loads(content)
                    deps = data.get("dependencies", {})
                    dev_deps = data.get("devDependencies", {})
                    for name, ver in deps.items():
                        dependencies.append(RepositoryDependencyResponse(name=name, version=str(ver), ecosystem="npm"))
                    for name, ver in dev_deps.items():
                        dependencies.append(RepositoryDependencyResponse(name=name, version=str(ver), ecosystem="npm"))
                except Exception:
                    pass
            elif file.path.endswith("requirements.txt"):
                for line in content.splitlines():
                    line = line.strip()
                    if not line or line.startswith(("#", "-", "http://", "https://")):
                        continue
                    match = re.match(r"^([A-Za-z0-9_\-\.]+)(?:([<>=!~]+.*))?$", line)
                    if match:
                        name, ver = match.groups()
                        dependencies.append(
                            RepositoryDependencyResponse(
                                name=name,
                                version=ver.strip() if ver else "*",
                                ecosystem="pip",
                            )
                        )
            elif file.path.endswith("go.mod"):
                for line in content.splitlines():
                    line = line.strip()
                    if line.startswith("require "):
                        parts = line.split()
                        if len(parts) >= 3:
                            dependencies.append(RepositoryDependencyResponse(name=parts[1], version=parts[2], ecosystem="gomod"))
                    elif not line.startswith("//") and len(line.split()) == 2:
                        parts = line.split()
                        if "." in parts[0] or "/" in parts[0]:
                            dependencies.append(RepositoryDependencyResponse(name=parts[0], version=parts[1], ecosystem="gomod"))
            elif file.path.endswith("Cargo.toml"):
                in_deps = False
                for line in content.splitlines():
                    line = line.strip()
                    if line.startswith("[dependencies"):
                        in_deps = True
                        continue
                    elif line.startswith("["):
                        in_deps = False
                    if in_deps and "=" in line and not line.startswith("#"):
                        parts = line.split("=", 1)
                        name = parts[0].strip()
                        ver = parts[1].strip().strip('"').strip("'")
                        dependencies.append(RepositoryDependencyResponse(name=name, version=ver, ecosystem="cargo"))
        return dependencies
    except Exception:
        return []


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
    return _extract_dependencies(repository_id, db)


def _request_user_id(request: Request) -> UUID:
    try:
        return UUID(request.state.user_id)
    except (AttributeError, ValueError) as exc:
        raise APIError(401, ErrorCode.UNAUTHORIZED, "Invalid authenticated user.") from exc


def _owned_repository(repository_id: UUID, request: Request, db: Session) -> Repository:
    user_id = _request_user_id(request)
    repository = RepositoryRepository(db).get_for_user(repository_id, user_id)
    if repository is None:
        raise APIError(404, ErrorCode.REPOSITORY_NOT_FOUND, "Repository does not exist or you do not have access.")
    return repository


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
