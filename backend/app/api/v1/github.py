"""GitHub App repository discovery and connect endpoints.

GET  /api/v1/github/repositories           — list repos accessible via GitHub App
POST /api/v1/github/repositories/:id/connect — connect a repo to the platform
"""

from __future__ import annotations

import logging
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, status
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.database import get_db
from app.core.errors import APIError, ErrorCode
from app.core.redis import get_redis
import httpx
from app.repositories.user_repository import UserRepository
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

    # Auto-sync installations from GitHub App if not found in database
    github_service = getattr(request.app.state, "github_service", None)
    if not installations and github_service:
        user = UserRepository(db).get_by_id(user_id)
        if user:
            try:
                async with httpx.AsyncClient(timeout=10.0) as client:
                    resp = await client.get(
                        "https://api.github.com/app/installations",
                        headers=github_service._app_auth_headers(),
                    )
                    if resp.is_success:
                        app_installs = resp.json()
                        for inst in app_installs:
                            acc_login = inst.get("account", {}).get("login", "")
                            acc_id = str(inst.get("target_id") or inst.get("account", {}).get("id") or "")
                            if (
                                (acc_login and acc_login.lower() == user.login.lower())
                                or (user.github_id and acc_id == str(user.github_id))
                            ):
                                installation_repo.upsert(
                                    user_id=user.id,
                                    installation_id=str(inst["id"]),
                                    account_login=acc_login or user.login,
                                    permissions=inst.get("permissions", {}),
                                )
                        installations = installation_repo.list_by_user(user_id)
            except Exception as exc:
                logger.warning("auto_sync_installations_error", extra={"error": str(exc)})

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
                logger.error("github_list_repos_error: %s", exc, exc_info=True)
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

    if not github_repo_id or not github_repo_id.strip().isdigit():
        raise APIError(
            400,
            ErrorCode.INVALID_REQUEST,
            f"Invalid GitHub repository ID '{github_repo_id}'. Must be a numeric identifier.",
        )
    numeric_repo_id = int(github_repo_id.strip())

    # Get user's installations
    installation_repo = GitHubInstallationRepository(db)
    installations = installation_repo.list_by_user(user_id)
    if not installations:
        raise APIError(
            400,
            ErrorCode.BAD_REQUEST,
            "No GitHub App installation found. Please install the GitHub App first.",
        )

    # Fetch repo details from GitHub across all user installations
    github_service = getattr(request.app.state, "github_service", None)
    owner, name, default_branch, language = "", "", "main", None
    installation = installations[0]

    if github_service:
        last_exc: Exception | None = None
        gh_repo = None
        for candidate_inst in installations:
            try:
                gh_repo = await github_service.get_repository(
                    int(candidate_inst.installation_id), numeric_repo_id
                )
                installation = candidate_inst
                break
            except Exception as exc:
                last_exc = exc
                continue
        if gh_repo is None:
            logger.warning("github_get_repo_error", extra={"error": str(last_exc)})
            raise APIError(
                502,
                ErrorCode.GITHUB_API_ERROR,
                "Failed to fetch repository details from GitHub.",
                retryable=True,
            ) from last_exc
        owner = gh_repo.owner
        name = gh_repo.name
        default_branch = gh_repo.default_branch
        language = gh_repo.language
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


@router.get("/installation/callback", summary="GitHub App installation redirect callback")
async def github_installation_callback(
    request: Request,
    installation_id: str = Query(...),
    setup_action: str = Query(default="install"),
    db: Session = Depends(get_db),
):
    """Handle redirect from GitHub after user installs the GitHub App."""
    settings = get_settings()
    frontend_base = settings.cors_origins[0] if settings.cors_origins else "http://localhost:5173"

    try:
        user_id = _request_user_id(request)
        user = UserRepository(db).get_by_id(user_id)
        if user:
            GitHubInstallationRepository(db).upsert(
                user_id=user.id,
                installation_id=installation_id,
                account_login=user.login,
                permissions={},
            )
    except Exception as exc:
        logger.info("installation_callback_without_user", extra={"error": str(exc)})

    return RedirectResponse(
        url=f"{frontend_base}/app/repositories?installed=true&installation_id={installation_id}",
        status_code=status.HTTP_302_FOUND,
    )


@router.post("/webhook", summary="GitHub App webhook handler")
async def github_webhook(
    request: Request,
    db: Session = Depends(get_db),
):
    """Process incoming GitHub App webhook events with HMAC signature verification."""
    import hashlib
    import hmac
    import json

    settings = get_settings()
    body_bytes = await request.body()

    # Security Fix: Fail closed if webhook secret is not configured
    if not settings.github_webhook_secret:
        raise APIError(
            503,
            ErrorCode.SERVICE_UNAVAILABLE,
            "GitHub webhook secret is not configured.",
            retryable=False,
        )

    signature_header = request.headers.get("X-Hub-Signature-256")
    if not signature_header:
        raise APIError(401, ErrorCode.UNAUTHORIZED, "Missing GitHub webhook signature.")
    expected_sig = "sha256=" + hmac.new(
        settings.github_webhook_secret.encode("utf-8"),
        body_bytes,
        hashlib.sha256,
    ).hexdigest()
    if not hmac.compare_digest(signature_header, expected_sig):
        raise APIError(401, ErrorCode.UNAUTHORIZED, "Invalid GitHub webhook signature.")

    event = request.headers.get("X-GitHub-Event", "ping")
    if event == "ping":
        return {"status": "pong"}

    try:
        payload = json.loads(body_bytes.decode("utf-8"))
    except Exception:
        return {"status": "ignored_bad_payload"}

    action = payload.get("action")
    installation = payload.get("installation", {})
    inst_id = str(installation.get("id", ""))
    acc_login = installation.get("account", {}).get("login", "")

    inst_repo = GitHubInstallationRepository(db)

    if event == "installation":
        if action in ("created", "added"):
            user = UserRepository(db).get_by_login(acc_login)
            if user and inst_id:
                inst_repo.upsert(
                    user_id=user.id,
                    installation_id=inst_id,
                    account_login=acc_login,
                    permissions=installation.get("permissions", {}),
                )
        elif action in ("deleted", "removed"):
            if inst_id:
                inst_repo.delete_by_installation_id(inst_id)

    return {"status": "ok", "event": event, "action": action}
