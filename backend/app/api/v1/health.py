"""Health and readiness check endpoints used by local tooling, Docker, Kubernetes, and CI."""

import asyncio
import json
import logging
import os
import shutil
import time
from pathlib import Path

import httpx
from fastapi import APIRouter, Request, Response, status
from sqlalchemy import func, select, text

from app.core.config import Settings, get_settings
from app.core.database import SessionLocal
from app.core.redis import get_redis
from app.models.webhook_event import GitHubWebhookEvent, WebhookEventStatus
from app.schemas.health import ComponentHealth, HealthResponse, OperationalReadinessMetrics, ReadinessResponse
from sandbox.container_backend import container_runtime_available

logger = logging.getLogger(__name__)

router = APIRouter(tags=["health"])


async def _sandbox_backend_ready(settings: Settings) -> bool:
    backend = settings.sandbox_backend.strip().lower()
    if backend == "runner":
        if not settings.task_workspace_root or not settings.runner_base_url or not settings.runner_auth_secret:
            return False
        root = Path(settings.task_workspace_root)
        if not root.is_absolute() or not root.is_dir() or not os.access(root, os.R_OK | os.W_OK | os.X_OK):
            return False
        try:
            async with httpx.AsyncClient(timeout=2.0) as client:
                result = await client.get(f"{settings.runner_base_url.rstrip('/')}/health")
                result.raise_for_status()
                data = result.json()
            return (
                isinstance(data, dict)
                and data.get("status") == "healthy"
                and data.get("backend") == "container"
                and data.get("shared_workspace_ready") is True
            )
        except (httpx.HTTPError, httpx.InvalidURL, ValueError):
            logger.debug("readiness_check_runner_failed")
            return False
    if backend == "container":
        return await asyncio.to_thread(container_runtime_available)
    return backend == "local"


def _count_webhook_backlog() -> int:
    with SessionLocal() as db:
        return db.scalar(
            select(func.count()).select_from(GitHubWebhookEvent).where(
                GitHubWebhookEvent.status.in_((WebhookEventStatus.PENDING, WebhookEventStatus.RETRY))
            )
        ) or 0


@router.get(
    "/health",
    response_model=HealthResponse,
    summary="Check API liveness (legacy/default)",
)
@router.get(
    "/health/live",
    response_model=HealthResponse,
    summary="Check API liveness",
)
async def health_liveness() -> HealthResponse:
    """Return basic process liveness without requiring external dependencies."""
    return HealthResponse(status="ok", version=get_settings().app_version)


@router.get(
    "/health/ready",
    response_model=ReadinessResponse,
    summary="Check complete system readiness",
    responses={
        200: {"description": "All core systems ready or operating in degraded mode"},
        503: {"description": "Primary dependencies (database) unhealthy"},
    },
)
async def health_readiness(request: Request, response: Response) -> ReadinessResponse:
    """Deep readiness check validating database, Redis, and configured service availability."""
    settings = get_settings()

    # 1. Database check (non-blocking thread with resilient timeout for cloud pools)
    db_health = ComponentHealth(status="unhealthy")
    def _sync_db_check() -> None:
        with SessionLocal() as db:
            db.execute(text("SELECT 1"))

    try:
        await asyncio.wait_for(asyncio.to_thread(_sync_db_check), timeout=5.0)
        db_health = ComponentHealth(status="healthy", message="Connected to PostgreSQL")
    except asyncio.TimeoutError:
        logger.warning("readiness_check_db_timeout")
        db_health = ComponentHealth(status="unhealthy", message="Database connection timed out")
    except Exception as exc:
        logger.warning("readiness_check_db_failed", extra={"error": str(exc)})
        db_health = ComponentHealth(status="unhealthy", message="Database connection failed")

    # 2. Redis check (non-blocking thread with resilient timeout)
    redis_health = ComponentHealth(status="unhealthy")
    def _sync_redis_check() -> bool:
        redis_client = get_redis()
        return bool(redis_client.ping())

    try:
        ping_ok = await asyncio.wait_for(asyncio.to_thread(_sync_redis_check), timeout=5.0)
        if ping_ok:
            redis_health = ComponentHealth(status="healthy", message="Connected to Redis")
        else:
            redis_health = ComponentHealth(status="degraded", message="Redis ping returned False")
    except asyncio.TimeoutError:
        logger.warning("readiness_check_redis_timeout")
        redis_health = ComponentHealth(status="degraded", message="Redis ping timed out")
    except Exception as exc:
        logger.warning("readiness_check_redis_failed", extra={"error": str(exc)})
        redis_health = ComponentHealth(status="degraded", message="Redis unavailable (caching/rate-limiting degraded)")

    # 3. AI / LLM Gateway check
    readiness_map = getattr(request.app.state, "service_readiness", {})
    llm_gateway = getattr(request.app.state, "llm_gateway", None)
    if llm_gateway is not None:
        llm_health = ComponentHealth(status="healthy", message="LLM Gateway initialized")
    else:
        llm_health = ComponentHealth(status="degraded", message="No AI provider configured")

    rag_pipeline = getattr(request.app.state, "rag_pipeline", None)
    if rag_pipeline is None:
        rag_health = ComponentHealth(status="unhealthy", message="RAG pipeline not initialized")
    elif not hasattr(rag_pipeline, "retriever"):
        rag_health = ComponentHealth(status="healthy", message="RAG pipeline initialized")
    else:
        has_retriever = getattr(rag_pipeline, "retriever", None) is not None
        has_llm = (
            getattr(rag_pipeline, "llm", None) is not None
            or llm_gateway is not None
        )
        if has_retriever and has_llm:
            rag_health = ComponentHealth(
                status="healthy", message="RAG pipeline ready (retriever and LLM configured)"
            )
        elif not has_retriever and not has_llm:
            rag_health = ComponentHealth(
                status="unhealthy",
                message="RAG pipeline unavailable (retriever and LLM gateway missing)",
            )
        elif not has_retriever:
            rag_health = ComponentHealth(
                status="degraded",
                message="RAG pipeline degraded (retriever unavailable: missing Gemini API key)",
            )
        else:
            rag_health = ComponentHealth(
                status="degraded",
                message="RAG pipeline degraded (LLM gateway unavailable)",
            )

    # 4. Service mapping summary
    services_summary = {
        k: ("healthy" if v else "unavailable")
        for k, v in readiness_map.items()
    }

    # 5. Operational metrics (OPT-24)
    sync_worker_heartbeat_age_s: float | None = None
    webhook_backlog: int | None = None
    if db_health.status == "healthy":
        try:
            webhook_backlog = await asyncio.wait_for(asyncio.to_thread(_count_webhook_backlog), timeout=2.0)
        except Exception:
            logger.debug("readiness_check_webhook_backlog_failed")
    if redis_health.status == "healthy":
        try:
            r = get_redis()
            keys = r.keys("worker:heartbeat:*")
            if keys:
                latest_hb = 0.0
                for k in keys:
                    raw_val = r.get(k)
                    if raw_val:
                        try:
                            hb_data = json.loads(raw_val)
                            hb_time = float(hb_data.get("last_heartbeat", 0))
                            if hb_time > latest_hb:
                                latest_hb = hb_time
                        except Exception as exc:
                            logger.debug("Failed parsing worker heartbeat JSON: %s", exc)
                if latest_hb > 0:
                    sync_worker_heartbeat_age_s = max(0.0, time.time() - latest_hb)

        except Exception as exc:
            logger.debug("operational_metrics_redis_error", extra={"error": str(exc)})

    scanner_availability = {
        "ruff": shutil.which("ruff") is not None,
        "bandit": shutil.which("bandit") is not None,
        "semgrep": shutil.which("semgrep") is not None,
        "gitleaks": shutil.which("gitleaks") is not None,
    }
    sandbox_backend_ok = await _sandbox_backend_ready(settings)

    operations = OperationalReadinessMetrics(
        sync_worker_heartbeat_age_s=sync_worker_heartbeat_age_s,
        webhook_backlog=webhook_backlog,
        scanner_availability=scanner_availability,
        sandbox_backend_ok=sandbox_backend_ok,
    )

    # Determine overall status
    if db_health.status == "unhealthy":
        overall_status = "not_ready"
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    elif (
        not sandbox_backend_ok
        or redis_health.status == "degraded"
        or llm_health.status == "degraded"
        or rag_health.status in ("degraded", "unhealthy")
    ):
        overall_status = "degraded"
    else:
        overall_status = "ready"

    return ReadinessResponse(
        status=overall_status,
        version=settings.app_version,
        database=db_health,
        redis=redis_health,
        llm_gateway=llm_health,
        rag_pipeline=rag_health,
        services=services_summary,
        operations=operations,
    )
