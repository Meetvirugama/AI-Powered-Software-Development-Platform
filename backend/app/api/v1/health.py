"""Health and readiness check endpoints used by local tooling, Docker, Kubernetes, and CI."""

import logging
from fastapi import APIRouter, Request, Response, status
from sqlalchemy import text

from app.core.config import get_settings
from app.core.database import SessionLocal
from app.core.redis import get_redis
from app.schemas.health import ComponentHealth, HealthResponse, ReadinessResponse

logger = logging.getLogger(__name__)

router = APIRouter(tags=["health"])


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

    # 1. Database check
    db_health = ComponentHealth(status="unhealthy")
    try:
        with SessionLocal() as db:
            db.execute(text("SELECT 1"))
        db_health = ComponentHealth(status="healthy", message="Connected to PostgreSQL")
    except Exception as exc:
        logger.warning("readiness_check_db_failed", extra={"error": str(exc)})
        db_health = ComponentHealth(status="unhealthy", message="Database connection failed")

    # 2. Redis check
    redis_health = ComponentHealth(status="unhealthy")
    try:
        redis_client = get_redis()
        if redis_client.ping():
            redis_health = ComponentHealth(status="healthy", message="Connected to Redis")
        else:
            redis_health = ComponentHealth(status="degraded", message="Redis ping returned False")
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

    # Determine overall status
    if db_health.status == "unhealthy":
        overall_status = "not_ready"
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    elif (
        redis_health.status == "degraded"
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
    )
