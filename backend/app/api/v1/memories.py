"""Project Memory Management & Automated Writers API (Issue #217).

Endpoints:
- POST   /api/v1/repositories/{repository_id}/memories
- GET    /api/v1/repositories/{repository_id}/memories
- GET    /api/v1/repositories/{repository_id}/memories/{entry_id}
- PATCH  /api/v1/repositories/{repository_id}/memories/{entry_id}
- DELETE /api/v1/repositories/{repository_id}/memories/{entry_id}
- POST   /api/v1/repositories/{repository_id}/memories/automated/task-completion
- POST   /api/v1/repositories/{repository_id}/memories/automated/task-failure
- POST   /api/v1/repositories/{repository_id}/memories/rules
"""

from __future__ import annotations

import logging
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.errors import APIError, ErrorCode
from app.models.memory_entry import MemoryStatus, MemoryType
from app.repositories.repository_repository import RepositoryRepository
from app.schemas.memory import (
    MemoryEntryCreate,
    MemoryEntryResponse,
    MemoryEntryUpdate,
    PaginatedMemoryEntriesResponse,
    ProjectRuleCreateRequest,
    TaskCompletionMemoryRequest,
    TaskFailureMemoryRequest,
)
from app.services.memory_service import ProjectMemoryService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/repositories/{repository_id}/memories", tags=["project-memory"])


def _verify_owned_repository(repository_id: UUID, request: Request, db: Session) -> UUID:
    """Enforce multi-tenant repository access boundaries."""
    try:
        user_id = UUID(str(request.state.user_id))
    except (AttributeError, ValueError) as exc:
        raise APIError(401, ErrorCode.UNAUTHORIZED, "Authentication is required.") from exc

    repo = RepositoryRepository(db).get_for_user(repository_id, user_id)
    if repo is None:
        raise APIError(
            404,
            ErrorCode.REPOSITORY_NOT_FOUND,
            "Repository does not exist or you do not have access.",
        )
    return user_id


# ---------------------------------------------------------------------------
# CRUD & Search Endpoints
# ---------------------------------------------------------------------------

@router.post(
    "",
    response_model=MemoryEntryResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new project memory entry",
    description="Manually record a convention, decision, rule, or summary in repository memory.",
)
def create_memory_entry(
    repository_id: UUID,
    payload: MemoryEntryCreate,
    request: Request,
    db: Session = Depends(get_db),
) -> MemoryEntryResponse:
    _verify_owned_repository(repository_id, request, db)
    service = ProjectMemoryService(db)
    entry = service.create_memory(
        repository_id=repository_id,
        type_=payload.type,
        content=payload.content,
        source=payload.source,
        status=payload.status,
    )
    return MemoryEntryResponse.from_orm_model(entry)


@router.get(
    "",
    response_model=PaginatedMemoryEntriesResponse,
    summary="List and search project memory entries",
    description="Retrieve paginated memory entries with optional text query, type, and status filtering.",
)
def list_memory_entries(
    repository_id: UUID,
    request: Request,
    query: str | None = Query(default=None, description="Search query in content or source"),
    type: MemoryType | None = Query(default=None, description="Filter by memory type"),
    status: MemoryStatus | None = Query(default=None, description="Filter by status"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
) -> PaginatedMemoryEntriesResponse:
    _verify_owned_repository(repository_id, request, db)
    service = ProjectMemoryService(db)
    offset = (page - 1) * page_size
    items, total = service.search_project_memory(
        repository_id=repository_id,
        query=query,
        type_=type,
        status=status,
        offset=offset,
        limit=page_size,
    )
    return PaginatedMemoryEntriesResponse(
        page=page,
        page_size=page_size,
        total=total,
        items=[MemoryEntryResponse.from_orm_model(item) for item in items],
    )


@router.get(
    "/{entry_id}",
    response_model=MemoryEntryResponse,
    summary="Get a specific memory entry",
)
def get_memory_entry(
    repository_id: UUID,
    entry_id: UUID,
    request: Request,
    db: Session = Depends(get_db),
) -> MemoryEntryResponse:
    _verify_owned_repository(repository_id, request, db)
    service = ProjectMemoryService(db)
    entry = service.get_memory(entry_id, repository_id=repository_id)
    if entry is None:
        raise APIError(404, ErrorCode.NOT_FOUND, "Memory entry not found.")
    return MemoryEntryResponse.from_orm_model(entry)


@router.patch(
    "/{entry_id}",
    response_model=MemoryEntryResponse,
    summary="Update a project memory entry",
)
def update_memory_entry(
    repository_id: UUID,
    entry_id: UUID,
    payload: MemoryEntryUpdate,
    request: Request,
    db: Session = Depends(get_db),
) -> MemoryEntryResponse:
    _verify_owned_repository(repository_id, request, db)
    service = ProjectMemoryService(db)
    entry = service.update_memory(
        entry_id=entry_id,
        repository_id=repository_id,
        content=payload.content,
        status=payload.status,
        type_=payload.type,
        source=payload.source,
    )
    if entry is None:
        raise APIError(404, ErrorCode.NOT_FOUND, "Memory entry not found.")
    return MemoryEntryResponse.from_orm_model(entry)


@router.delete(
    "/{entry_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a project memory entry",
)
def delete_memory_entry(
    repository_id: UUID,
    entry_id: UUID,
    request: Request,
    db: Session = Depends(get_db),
) -> None:
    _verify_owned_repository(repository_id, request, db)
    service = ProjectMemoryService(db)
    deleted = service.delete_memory(entry_id, repository_id=repository_id)
    if not deleted:
        raise APIError(404, ErrorCode.NOT_FOUND, "Memory entry not found.")


# ---------------------------------------------------------------------------
# Automated Memory Writers (Issue #217)
# ---------------------------------------------------------------------------

@router.post(
    "/automated/task-completion",
    response_model=MemoryEntryResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Record task completion memory",
    description="Reflexion-style automated memory recorder for successful task executions.",
)
def record_task_completion_endpoint(
    repository_id: UUID,
    payload: TaskCompletionMemoryRequest,
    request: Request,
    db: Session = Depends(get_db),
) -> MemoryEntryResponse:
    _verify_owned_repository(repository_id, request, db)
    service = ProjectMemoryService(db)
    entry = service.record_task_completion_memory(
        repository_id=repository_id,
        task_id=payload.task_id,
        title=payload.title,
        verification_summary=payload.verification_summary,
        repair_attempts_used=payload.repair_attempts_used,
        files_changed=payload.files_changed,
    )
    return MemoryEntryResponse.from_orm_model(entry)


@router.post(
    "/automated/task-failure",
    response_model=MemoryEntryResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Record task failure memory",
    description="Automated memory recorder for failed task executions to preserve negative feedback.",
)
def record_task_failure_endpoint(
    repository_id: UUID,
    payload: TaskFailureMemoryRequest,
    request: Request,
    db: Session = Depends(get_db),
) -> MemoryEntryResponse:
    _verify_owned_repository(repository_id, request, db)
    service = ProjectMemoryService(db)
    entry = service.record_task_failure_memory(
        repository_id=repository_id,
        task_id=payload.task_id,
        title=payload.title,
        failure_reason=payload.failure_reason,
        repair_attempts_used=payload.repair_attempts_used,
    )
    return MemoryEntryResponse.from_orm_model(entry)


@router.post(
    "/rules",
    response_model=MemoryEntryResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Pin an architectural convention or rule",
)
def pin_architectural_rule_endpoint(
    repository_id: UUID,
    payload: ProjectRuleCreateRequest,
    request: Request,
    db: Session = Depends(get_db),
) -> MemoryEntryResponse:
    _verify_owned_repository(repository_id, request, db)
    service = ProjectMemoryService(db)
    entry = service.record_architectural_rule(
        repository_id=repository_id,
        rule_content=payload.rule,
        source=payload.source,
    )
    return MemoryEntryResponse.from_orm_model(entry)
