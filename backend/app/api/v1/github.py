"""GitHub App repository discovery and connect endpoints.

GET  /api/v1/github/repositories           — list repos accessible via GitHub App
POST /api/v1/github/repositories/:id/connect — connect a repo to the platform
"""

from __future__ import annotations

import logging
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.errors import APIError, ErrorCode
from app.core.redis import get_redis
from app.repositories.repository_repository import RepositoryRepository
from app.repositories.github_installation_repository import GitHubInstallationRepository
from app.schemas.repository import (
    AvailableRepository,
    ConnectRepositoryResponse,
    PaginatedAvailableRepositoryResponse,
    SyncJobResponse,
)
from app.services.repository_sync import RedisSyncJobQueue, RepositorySyncService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/github", tags=["github"])


def _request_user_id(request: Request) -> UUID:
    try:
        return UUID(request.state.user_id)
    except (AttributeError, ValueError) as exc:
        raise APIError(401, ErrorCode.UNAUTHORIZED, "Invalid authenticated user.") from exc


@router.get(
    "/repositories",
    response_model=PaginatedAvailableRepositoryResponse,
    summary="List repositories accessible via GitHub App",
)
async def list_github_repositories(
    request: Request,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    search: str = Query(default=""),
    db: Session = Depends(get_db),
) -> PaginatedAvailableRepositoryResponse:
    """Return repositories accessible via the user's GitHub App installation."""
    user_id = _request_user_id(request)

    # Get user's GitHub installations
    installation_repo = GitHubInstallationRepository(db)
    installations = installation_repo.list_by_user(user_id)

    if not installations:
        return PaginatedAvailableRepositoryResponse(
            items=[], total=0, page=page, page_size=page_size, total_pages=1
        )

    # Get already-connected repo IDs for this user
    repo_repo = RepositoryRepository(db)
    connected_repos = repo_repo.list_by_user(user_id)
    connected_github_ids = {r.github_repo_id for r in connected_repos}

    # Fetch repos from GitHub API for each installation
    github_service = getattr(request.app.state, "github_service", None)
    all_repos: list[AvailableRepository] = []

    if github_service:
        for installation in installations:
            try:
                gh_repos = await github_service.list_repositories(
                    int(installation.installation_id)
                )
                for r in gh_repos:
                    all_repos.append(
                        AvailableRepository(
                            github_repo_id=str(r.id),
                            owner=r.owner,
                            name=r.name,
                            full_name=r.full_name,
                            default_branch=r.default_branch,
                            language=r.language,
                            is_connected=str(r.id) in connected_github_ids,
                        )
                    )
            except Exception as exc:
                logger.warning("github_list_repos_error", extra={"error": str(exc)})
    else:
        # Fallback: return connected repos as available (no GitHub App configured)
        for r in connected_repos:
            all_repos.append(
                AvailableRepository(
                    github_repo_id=r.github_repo_id,
                    owner=r.owner,
                    name=r.name,
                    full_name=f"{r.owner}/{r.name}",
                    default_branch=r.default_branch,
                    language=r.language,
                    is_connected=True,
                )
            )

    # Server-side search filter
    if search:
        search_lower = search.lower()
        all_repos = [
            r for r in all_repos
            if search_lower in r.name.lower() or search_lower in r.full_name.lower()
        ]

    # Pagination
    total = len(all_repos)
    total_pages = max(1, (total + page_size - 1) // page_size)
    start = (page - 1) * page_size
    items = all_repos[start: start + page_size]

    return PaginatedAvailableRepositoryResponse(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
        total_pages=total_pages,
    )


@router.post(
    "/repositories/{github_repo_id}/connect",
    response_model=ConnectRepositoryResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Connect a GitHub repository to the platform",
)
async def connect_repository(
    github_repo_id: str,
    request: Request,
    db: Session = Depends(get_db),
) -> ConnectRepositoryResponse:
    """Register a GitHub repository and queue an initial sync job."""
    user_id = _request_user_id(request)

    repo_repo = RepositoryRepository(db)

    # Check if already connected
    existing = repo_repo.get_by_github_id_and_user(github_repo_id, user_id)
    if existing:
        raise APIError(
            409,
            ErrorCode.CONFLICT,
            "This repository is already connected to the platform.",
        )

    # Get user's installation
    installation_repo = GitHubInstallationRepository(db)
    installations = installation_repo.list_by_user(user_id)
    if not installations:
        raise APIError(
            400,
            ErrorCode.BAD_REQUEST,
            "No GitHub App installation found. Please install the GitHub App first.",
        )
    installation = installations[0]

    # Fetch repo details from GitHub
    github_service = getattr(request.app.state, "github_service", None)
    owner, name, default_branch, language = "", "", "main", None

    if github_service:
        try:
            gh_repo = await github_service.get_repository(
                int(installation.installation_id), int(github_repo_id)
            )
            owner = gh_repo.owner
            name = gh_repo.name
            default_branch = gh_repo.default_branch
            language = gh_repo.language
        except Exception as exc:
            logger.warning("github_get_repo_error", extra={"error": str(exc)})
            raise APIError(
                502,
                ErrorCode.GITHUB_API_ERROR,
                "Failed to fetch repository details from GitHub.",
                retryable=True,
            ) from exc
    else:
        raise APIError(
            503,
            ErrorCode.SERVICE_UNAVAILABLE,
            "GitHub App is not configured.",
        )

    # Create repository record
    repository = repo_repo.create(
        user_id=user_id,
        installation_id=installation.id,
        github_repo_id=github_repo_id,
        owner=owner,
        name=name,
        default_branch=default_branch,
        language=language,
    )

    # Queue initial sync job
    service = RepositorySyncService(repo_repo, RedisSyncJobQueue(get_redis()))
    job = service.request_sync(repository.id, user_id)

    logger.info(
        "repository_connected",
        extra={
            "user_id": str(user_id),
            "repo_id": str(repository.id),
            "github_repo_id": github_repo_id,
            "job_id": str(job.id),
        },
    )

    return ConnectRepositoryResponse(
        repository_id=str(repository.id),
        job_id=str(job.id),
    )
