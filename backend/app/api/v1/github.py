"""GitHub App repository discovery and connect endpoints.

GET  /api/v1/github/repositories           — list repos accessible via GitHub App
POST /api/v1/github/repositories/:id/connect — connect a repo to the platform
"""

from __future__ import annotations

import asyncio
import inspect
import json
import logging
from uuid import UUID

import httpx
from fastapi import APIRouter, Depends, Query, Request, Response, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.v1.dependencies import ensure_min_role, require_min_role
from app.core.config import get_settings
from app.core.database import get_db, run_db
from app.core.errors import APIError, ErrorCode
from app.core.redis import get_redis, get_redis_async
from app.models.github_installation import GitHubInstallation
from app.models.repository import Repository
from app.models.user import UserRole
from app.models.webhook_event import GitHubWebhookEvent, WebhookEventStatus
from app.repositories.github_installation_repository import GitHubInstallationRepository
from app.repositories.repository_repository import RepositoryRepository
from app.repositories.user_repository import UserRepository
from app.repositories.webhook_event_repository import WebhookEventRepository
from app.schemas.repository import (
    AvailableRepository,
    ConnectRepositoryResponse,
    PaginatedAvailableRepositoryResponse,
    RepositoryAutomationSettingsResponse,
    UpdateRepositoryAutomationSettingsRequest,
)
from app.services.installation_linking import (
    link_installation_for_user,
    normalize_installation_id,
    sync_user_installations,
)
from app.services.repository_sync import RedisSyncJobQueue, RepositorySyncService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/github", tags=["github"])


def _request_user_id(request: Request) -> UUID:
    try:
        return UUID(request.state.user_id)
    except (AttributeError, ValueError) as exc:
        raise APIError(401, ErrorCode.UNAUTHORIZED, "Invalid authenticated user.") from exc


def _verify_event_access(event: GitHubWebhookEvent, user_id: UUID, db: Session) -> None:
    has_access = False
    if event.repository_id:
        r = RepositoryRepository(db).get_for_user(event.repository_id, user_id)
        if r:
            has_access = True
    if not has_access and event.installation_id:
        inst = GitHubInstallationRepository(db).get_by_installation_id(event.installation_id)
        if inst and inst.user_id == user_id:
            has_access = True
    if not has_access:
        raise APIError(403, ErrorCode.FORBIDDEN, "Access denied to this event.")


_DISCOVERY_CACHE_TTL_SECONDS = 240


def _discovery_cache_key(user_id: UUID, installation_id: str | int) -> str:
    return f"github:repos:{user_id}:{installation_id}"


async def _invalidate_discovery_cache(user_id: UUID, installation_id: str | int) -> None:
    try:
        redis = await get_redis_async()
        if redis is not None and hasattr(redis, "delete"):
            await redis.delete(_discovery_cache_key(user_id, installation_id))
    except Exception as exc:
        logger.debug("github_discovery_cache_invalidate_skipped: %s", exc)


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
    installation_id: str | None = Query(default=None),
    refresh: bool = Query(default=False, description="Bypass Redis discovery cache and fetch fresh repositories from GitHub"),
    db: Session = Depends(get_db),
) -> PaginatedAvailableRepositoryResponse:
    """Return repositories accessible via the user's GitHub App installation."""
    user_id = _request_user_id(request)

    # Get user's GitHub installations
    installation_repo = GitHubInstallationRepository(db)
    user = await run_db(db, UserRepository(db).get_by_id, user_id)

    github_service = getattr(request.app.state, "github_service", None)

    # installation_id arrives from the post-install redirect; link it only after GitHub
    # confirms the installation belongs to this user's own account.
    if installation_id and user:
        try:
            linked_inst = await link_installation_for_user(db, user, installation_id, github_service)
            await _invalidate_discovery_cache(user_id, linked_inst.installation_id)
        except APIError as exc:
            if exc.status_code < 500:
                raise
            # GitHub/App unavailable: still list what is already linked instead of failing the page.
            logger.warning("query_installation_link_unverified", extra={"reason": exc.message})

    installations = await run_db(db, installation_repo.list_by_user, user_id)

    # Auto-discover installations on the user's own account if none are linked yet
    if not installations and github_service and user:
        installations = await sync_user_installations(db, user, github_service)

    if not installations:
        return PaginatedAvailableRepositoryResponse(
            items=[], total=0, page=page, page_size=page_size, total_pages=1
        )

    # Get already-connected repo IDs for this user
    repo_repo = RepositoryRepository(db)
    connected_repos = await run_db(db, repo_repo.list_by_user, user_id)
    connected_github_ids = {r.github_repo_id for r in connected_repos}

    # Fetch repos from GitHub API (or Redis cache) in parallel across installations
    github_service = getattr(request.app.state, "github_service", None)
    all_repos: list[AvailableRepository] = []

    if github_service:
        async def _load_for_installation(inst: GitHubInstallation) -> list[dict[str, object]]:
            cache_key = _discovery_cache_key(user_id, inst.installation_id)
            redis_client = None
            try:
                redis_client = await get_redis_async()
            except Exception:
                redis_client = None

            if not refresh and redis_client is not None and hasattr(redis_client, "get"):
                try:
                    cached_raw = await redis_client.get(cache_key)
                    if cached_raw:
                        if isinstance(cached_raw, bytes):
                            cached_raw = cached_raw.decode("utf-8")
                        parsed = json.loads(cached_raw)
                        if isinstance(parsed, list):
                            return parsed
                except Exception as cache_exc:
                    logger.debug("github_discovery_cache_read_failed: %s", cache_exc)

            gh_repos = await github_service.list_repositories(int(inst.installation_id))
            serialized = [
                {
                    "github_repo_id": str(r.id),
                    "owner": r.owner,
                    "name": r.name,
                    "full_name": r.full_name,
                    "default_branch": r.default_branch,
                    "language": r.language,
                }
                for r in gh_repos
            ]
            if redis_client is not None and hasattr(redis_client, "set"):
                try:
                    await redis_client.set(
                        cache_key,
                        json.dumps(serialized),
                        ex=_DISCOVERY_CACHE_TTL_SECONDS,
                    )
                except Exception as cache_exc:
                    logger.debug("github_discovery_cache_write_failed: %s", cache_exc)
            return serialized

        per_installation = await asyncio.gather(
            *[_load_for_installation(inst) for inst in installations],
            return_exceptions=True,
        )
        for batch_or_exc in per_installation:
            if isinstance(batch_or_exc, Exception):
                logger.error("github_list_repos_error: %s", batch_or_exc, exc_info=True)
                continue
            for item in batch_or_exc:
                gh_id = str(item.get("github_repo_id", ""))
                all_repos.append(
                    AvailableRepository(
                        github_repo_id=gh_id,
                        owner=str(item.get("owner", "")),
                        name=str(item.get("name", "")),
                        full_name=str(item.get("full_name", "")),
                        default_branch=str(item.get("default_branch", "main")),
                        language=item.get("language") if isinstance(item.get("language"), str) else None,
                        is_connected=gh_id in connected_github_ids,
                    )
                )
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
    ensure_min_role(request, UserRole.DEVELOPER)

    repo_repo = RepositoryRepository(db)

    # Check if already connected
    existing = await run_db(db, repo_repo.get_by_github_id_and_user, github_repo_id, user_id)
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
    installations = await run_db(db, installation_repo.list_by_user, user_id)
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

    def _create_and_queue() -> tuple[Repository, Any]:
        created_repo = repo_repo.create(
            user_id=user_id,
            installation_id=installation.id,
            github_repo_id=github_repo_id,
            owner=owner,
            name=name,
            default_branch=default_branch,
            language=language,
        )
        sync_svc = RepositorySyncService(repo_repo, RedisSyncJobQueue(get_redis()))
        queued_job = sync_svc.request_sync(created_repo.id, user_id)
        return created_repo, queued_job

    repository, job = await run_db(db, _create_and_queue)

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


class LinkInstallationRequest(BaseModel):
    installation_id: str


def _installation_payload(inst: GitHubInstallation) -> dict:
    return {
        "id": str(inst.id),
        "installation_id": inst.installation_id,
        "account_login": inst.account_login,
        "permissions": inst.permissions or {},
        "installed_at": inst.installed_at.isoformat() if getattr(inst, "installed_at", None) else None,
    }


@router.get("/installations", summary="List GitHub App installations linked to the authenticated user")
def list_linked_installations(request: Request, db: Session = Depends(get_db)) -> dict:
    user_id = _request_user_id(request)
    items = [_installation_payload(i) for i in GitHubInstallationRepository(db).list_by_user(user_id)]
    return {"items": items, "total": len(items)}


@router.post(
    "/installations/link",
    summary="Link a GitHub App installation to the authenticated user",
    dependencies=[Depends(require_min_role(UserRole.DEVELOPER))],
)
async def link_github_installation(
    body: LinkInstallationRequest,
    request: Request,
    db: Session = Depends(get_db),
):
    """Link an installation after verifying with GitHub that it belongs to the caller's account."""
    user_id = _request_user_id(request)
    user = await run_db(db, UserRepository(db).get_by_id, user_id)
    if not user:
        raise APIError(401, ErrorCode.UNAUTHORIZED, "User account not found.")

    github_service = getattr(request.app.state, "github_service", None)
    inst = await link_installation_for_user(db, user, body.installation_id, github_service)
    await _invalidate_discovery_cache(user_id, inst.installation_id)
    return {
        "status": "linked",
        "installation_id": inst.installation_id,
        "user_id": str(user.id),
        "account_login": inst.account_login,
    }


@router.delete(
    "/installations/{installation_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Unlink a GitHub App installation from the authenticated user",
    dependencies=[Depends(require_min_role(UserRole.DEVELOPER))],
)
def unlink_github_installation(installation_id: str, request: Request, db: Session = Depends(get_db)) -> Response:
    user_id = _request_user_id(request)
    clean_id = normalize_installation_id(installation_id)
    repo = GitHubInstallationRepository(db)
    inst = repo.get_by_installation_id(clean_id)
    if inst is None or inst.user_id != user_id:
        raise APIError(404, ErrorCode.RESOURCE_NOT_FOUND, "Installation not found.")
    in_use = db.query(Repository.id).filter(Repository.installation_id == inst.id).first()
    if in_use is not None:
        raise APIError(
            409,
            ErrorCode.CONFLICT,
            "Disconnect the repositories that use this installation before unlinking it.",
        )
    repo.delete_by_installation_id(clean_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/installation/callback", summary="GitHub App installation redirect callback")
async def github_installation_callback(
    request: Request,
    installation_id: str | None = Query(default=None),
    setup_action: str = Query(default="install"),
    db: Session = Depends(get_db),
):
    """Handle the redirect from GitHub after the user installs (or updates) the GitHub App.

    The installation_id query parameter is attacker-controllable, so it is only linked after
    GitHub confirms the installation belongs to the signed-in user's own account.
    """
    from app.api.v1.auth import _installation_redirect, _resolve_trusted_frontend_url

    frontend_base = _resolve_trusted_frontend_url()
    linked = False
    clean_id = (installation_id or "").strip()
    user_id_str = getattr(request.state, "user_id", None)
    if clean_id and user_id_str and setup_action != "request":
        try:
            user = await run_db(db, UserRepository(db).get_by_id, UUID(str(user_id_str)))
            if user:
                github_service = getattr(request.app.state, "github_service", None)
                linked_inst = await link_installation_for_user(db, user, clean_id, github_service)
                await _invalidate_discovery_cache(user.id, linked_inst.installation_id)
                linked = True
        except APIError as exc:
            logger.warning(
                "installation_callback_link_rejected",
                extra={"installation_id": clean_id, "reason": exc.message},
            )
        except Exception as exc:
            logger.info("installation_callback_without_user", extra={"error": str(exc)})

    return _installation_redirect(frontend_base, clean_id or None, linked)


SUPPORTED_WEBHOOK_EVENTS = {
    "push",
    "pull_request",
    "installation",
    "installation_repositories",
    "issues",
}


@router.post("/webhook", summary="GitHub App webhook handler")
async def github_webhook(
    request: Request,
    db: Session = Depends(get_db),
):
    """Process incoming GitHub App webhook events with HMAC signature verification, size checks, delivery deduplication, and durable event persistence."""
    import hashlib
    import hmac
    import json
    import re
    import uuid

    from app.core.redis import get_redis
    from app.models.repository import Repository
    from app.repositories.webhook_event_repository import WebhookEventRepository

    MAX_WEBHOOK_BODY_BYTES = 5 * 1024 * 1024  # 5 MB

    settings = get_settings()

    # Precheck Content-Length header before reading body into memory (ISS-031 / TST-10)
    content_length_header = request.headers.get("content-length")
    if content_length_header:
        try:
            if int(content_length_header) > MAX_WEBHOOK_BODY_BYTES:
                raise APIError(413, ErrorCode.BAD_REQUEST, "Webhook payload exceeds maximum allowed size.")
        except ValueError:
            pass

    body_bytes = await request.body()

    if len(body_bytes) > MAX_WEBHOOK_BODY_BYTES:
        raise APIError(413, ErrorCode.BAD_REQUEST, "Webhook payload exceeds maximum allowed size.")

    # Security Fix: Fail closed if webhook secret is not configured
    if not settings.github_webhook_secret or not settings.github_webhook_secret.strip():
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
    delivery_id = request.headers.get("X-GitHub-Delivery")

    # Validate delivery ID format if present and perform deduplication
    if delivery_id:
        if not re.match(r"^[a-zA-Z0-9_-]{1,64}$", delivery_id):
            raise APIError(400, ErrorCode.BAD_REQUEST, "Invalid X-GitHub-Delivery header.")
        try:
            try:
                r = await get_redis_async()
                was_set = r.set(f"webhook_delivery:{delivery_id}", "1", ex=86400, nx=True)
                if inspect.isawaitable(was_set):
                    was_set = await was_set
            except Exception:
                was_set = await asyncio.to_thread(
                    get_redis().set, f"webhook_delivery:{delivery_id}", "1", ex=86400, nx=True
                )
            if not was_set:
                logger.info("github_webhook_duplicate_delivery", extra={"delivery_id": delivery_id, "event": event})
                return {"status": "duplicate_delivery_ignored", "delivery_id": delivery_id}
        except Exception as redis_exc:
            logger.warning("webhook_dedup_redis_failed", extra={"error": str(redis_exc)})

    logger.info("github_webhook_received", extra={"event": event, "delivery_id": delivery_id})

    if event == "ping":
        return {"status": "pong"}

    try:
        payload = json.loads(body_bytes.decode("utf-8"))
    except Exception:
        return {"status": "ignored_bad_payload"}

    if not isinstance(payload, dict):
        return {"status": "ignored_bad_payload"}

    if event not in SUPPORTED_WEBHOOK_EVENTS:
        logger.info("github_webhook_unsupported_event_ignored", extra={"event": event})
        return {"status": "ignored_unsupported_event", "event": event}

    action = payload.get("action")
    installation = payload.get("installation") or {}
    inst_id = str(installation.get("id", "")) if installation.get("id") else None
    repo_data = payload.get("repository") or {}
    github_repo_id = str(repo_data.get("id", "")) if repo_data.get("id") else None

    # Resolve linked repository & persist webhook event durably off the event loop
    def _lookup_repo_and_create_event():
        linked_id = None
        if github_repo_id:
            found_repo = db.query(Repository).filter(Repository.github_repo_id == github_repo_id).first()
            if found_repo:
                linked_id = found_repo.id
        effective_id = delivery_id or f"auto-{uuid.uuid4().hex}"
        ev_repo = WebhookEventRepository(db)
        ev_record, is_created = ev_repo.create_event(
            delivery_id=effective_id,
            event_type=event,
            action=action,
            installation_id=inst_id,
            repository_id=linked_id,
            github_repo_id=github_repo_id,
            payload=payload,
        )
        return effective_id, ev_record, is_created

    try:
        effective_delivery_id, event_record, created = await run_db(db, _lookup_repo_and_create_event)
        if not created:
            logger.info("github_webhook_db_duplicate_delivery", extra={"delivery_id": effective_delivery_id, "event": event})
            return {"status": "duplicate_delivery_ignored", "delivery_id": effective_delivery_id}
    except Exception as db_exc:
        await run_db(db, db.rollback)
        logger.error("github_webhook_persistence_failed", extra={"error": str(db_exc)})
        if delivery_id:
            try:
                r_clean = await get_redis_async()
                if r_clean is not None:
                    await r_clean.delete(f"webhook_delivery:{delivery_id}")
                else:
                    get_redis().delete(f"webhook_delivery:{delivery_id}")
            except Exception:
                logger.warning("webhook_dedup_key_release_failed", extra={"delivery_id": delivery_id})
        raise APIError(
            500,
            ErrorCode.INTERNAL_SERVER_ERROR,
            "Failed to persist webhook event durably.",
            retryable=True,
        ) from db_exc

    from fastapi.responses import JSONResponse

    return JSONResponse(
        status_code=status.HTTP_202_ACCEPTED,
        content={
            "status": "accepted",
            "delivery_id": effective_delivery_id,
            "event_id": str(event_record.id),
            "event": event,
            "action": action,
        },
    )


@router.get("/events", summary="List durably persisted GitHub webhook events")
def list_webhook_events(
    request: Request,
    status: str | None = Query(default=None),
    event_type: str | None = Query(default=None),
    repository_id: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    """Inspect durably persisted webhook events with status and event_type filters."""
    user_id = _request_user_id(request)

    user_repo_ids = None
    user_install_ids = None
    repo_uuid = None
    if repository_id:
        try:
            repo_uuid = UUID(repository_id)
        except ValueError:
            raise APIError(400, ErrorCode.INVALID_REQUEST, "Invalid repository UUID.")
        repo_item = RepositoryRepository(db).get_for_user(repo_uuid, user_id)
        if not repo_item:
            raise APIError(404, ErrorCode.REPOSITORY_NOT_FOUND, "Repository not found or access denied.")
    else:
        user_repo_ids = [r.id for r in db.query(Repository.id).filter(Repository.user_id == user_id).all()]
        user_install_ids = [
            str(i.installation_id)
            for i in db.query(GitHubInstallation.installation_id).filter(GitHubInstallation.user_id == user_id).all()
        ]

    status_filter = None
    if status:
        try:
            status_filter = WebhookEventStatus(status.upper())
        except ValueError:
            raise APIError(400, ErrorCode.INVALID_REQUEST, f"Invalid event status '{status}'.")

    offset = (page - 1) * page_size
    repo = WebhookEventRepository(db)
    events, total = repo.list_events(
        status=status_filter,
        event_type=event_type,
        repository_id=repo_uuid,
        repository_ids=user_repo_ids,
        installation_ids=user_install_ids,
        limit=page_size,
        offset=offset,
    )

    items = [
        {
            "id": str(e.id),
            "delivery_id": e.delivery_id,
            "event_type": e.event_type,
            "action": e.action,
            "installation_id": e.installation_id,
            "repository_id": str(e.repository_id) if e.repository_id else None,
            "status": e.status.value if hasattr(e.status, "value") else str(e.status),
            "attempts": e.attempts,
            "max_attempts": e.max_attempts,
            "available_at": e.available_at.isoformat() if e.available_at else None,
            "processed_at": e.processed_at.isoformat() if e.processed_at else None,
            "last_error": e.last_error,
            "replay_count": getattr(e, "replay_count", 0),
            "created_at": e.created_at.isoformat() if e.created_at else None,
        }
        for e in events
    ]

    return {
        "items": items,
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": max(1, (total + page_size - 1) // page_size),
    }


@router.get("/events/{event_id}", summary="Get detailed status of a webhook event")
def get_webhook_event(
    event_id: str,
    request: Request,
    db: Session = Depends(get_db),
):
    """Retrieve details and sanitized metadata for a specific webhook event."""
    user_id = _request_user_id(request)
    try:
        event_uuid = UUID(event_id)
    except ValueError:
        raise APIError(400, ErrorCode.INVALID_REQUEST, "Invalid event UUID.")

    repo = WebhookEventRepository(db)
    event = repo.get_by_id(event_uuid)
    if not event:
        raise APIError(404, ErrorCode.RESOURCE_NOT_FOUND, "Webhook event not found.")

    _verify_event_access(event, user_id, db)

    return {
        "id": str(event.id),
        "delivery_id": event.delivery_id,
        "event_type": event.event_type,
        "action": event.action,
        "installation_id": event.installation_id,
        "repository_id": str(event.repository_id) if event.repository_id else None,
        "status": event.status.value if hasattr(event.status, "value") else str(event.status),
        "attempts": event.attempts,
        "max_attempts": event.max_attempts,
        "available_at": event.available_at.isoformat() if event.available_at else None,
        "processed_at": event.processed_at.isoformat() if event.processed_at else None,
        "last_error": event.last_error,
        "replay_count": getattr(event, "replay_count", 0),
        "created_at": event.created_at.isoformat() if event.created_at else None,
    }


@router.post("/events/{event_id}/replay", summary="Safely replay a failed or dead-letter webhook event")
def replay_webhook_event(
    event_id: str,
    request: Request,
    db: Session = Depends(get_db),
):
    """Replay a failed or dead-letter webhook event. Actively processing events cannot be replayed."""
    user_id = _request_user_id(request)
    ensure_min_role(request, UserRole.DEVELOPER)
    try:
        event_uuid = UUID(event_id)
    except ValueError:
        raise APIError(400, ErrorCode.INVALID_REQUEST, "Invalid event UUID.")

    repo = WebhookEventRepository(db)
    event = repo.get_by_id(event_uuid)
    if not event:
        raise APIError(404, ErrorCode.RESOURCE_NOT_FOUND, "Webhook event not found.")

    _verify_event_access(event, user_id, db)

    try:
        replayed = repo.replay_event(event_uuid)
    except ValueError as val_err:
        raise APIError(409, ErrorCode.CONFLICT, str(val_err))

    return {
        "status": "replayed",
        "event_id": str(replayed.id),
        "replay_count": getattr(replayed, "replay_count", 1),
    }


@router.get(
    "/repositories/{github_repo_id}/automation",
    response_model=RepositoryAutomationSettingsResponse,
    summary="Get repository automation settings",
)
def get_repository_automation(
    github_repo_id: str,
    request: Request,
    db: Session = Depends(get_db),
) -> RepositoryAutomationSettingsResponse:
    """Retrieve opt-in automation configuration for a connected repository."""
    user_id = _request_user_id(request)
    repo = RepositoryRepository(db).get_by_github_id_and_user(github_repo_id, user_id)
    if not repo:
        raise APIError(404, ErrorCode.REPOSITORY_NOT_FOUND, "Repository not found or access denied.")

    return RepositoryAutomationSettingsResponse(
        github_repo_id=github_repo_id,
        auto_sync_enabled=getattr(repo, "auto_sync_enabled", True),
        pr_review_enabled=getattr(repo, "pr_review_enabled", False),
        pr_review_drafts=getattr(repo, "pr_review_drafts", False),
        last_indexed_commit_sha=getattr(repo, "last_indexed_commit_sha", None),
    )


@router.patch(
    "/repositories/{github_repo_id}/automation",
    response_model=RepositoryAutomationSettingsResponse,
    summary="Update repository automation settings",
)
def update_repository_automation(
    github_repo_id: str,
    body: UpdateRepositoryAutomationSettingsRequest,
    request: Request,
    db: Session = Depends(get_db),
) -> RepositoryAutomationSettingsResponse:
    """Update opt-in automation settings (push-sync, PR review, draft review) for a repository."""
    user_id = _request_user_id(request)
    ensure_min_role(request, UserRole.DEVELOPER)
    repo = RepositoryRepository(db).get_by_github_id_and_user(github_repo_id, user_id)
    if not repo:
        raise APIError(404, ErrorCode.REPOSITORY_NOT_FOUND, "Repository not found or access denied.")

    if body.auto_sync_enabled is not None:
        repo.auto_sync_enabled = body.auto_sync_enabled
    if body.pr_review_enabled is not None:
        repo.pr_review_enabled = body.pr_review_enabled
    if body.pr_review_drafts is not None:
        repo.pr_review_drafts = body.pr_review_drafts

    db.commit()
    db.refresh(repo)

    return RepositoryAutomationSettingsResponse(
        github_repo_id=github_repo_id,
        auto_sync_enabled=getattr(repo, "auto_sync_enabled", True),
        pr_review_enabled=getattr(repo, "pr_review_enabled", False),
        pr_review_drafts=getattr(repo, "pr_review_drafts", False),
        last_indexed_commit_sha=getattr(repo, "last_indexed_commit_sha", None),
    )
