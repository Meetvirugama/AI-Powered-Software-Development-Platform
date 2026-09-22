"""Health-check endpoint used by local tooling, Docker, and CI."""

from fastapi import APIRouter

from app.core.config import get_settings
from app.schemas.health import HealthResponse

router = APIRouter(tags=["health"])


@router.get(
    "/health",
    response_model=HealthResponse,
    summary="Check API availability",
)
async def health_check() -> HealthResponse:
    """Return service metadata without requiring database connectivity."""
    return HealthResponse(version=get_settings().app_version)
