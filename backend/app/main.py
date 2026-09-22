"""FastAPI application factory and public OpenAPI contract."""

from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.v1.router import api_router
from app.core.config import get_settings
from app.core.logging import RequestIdMiddleware, configure_logging

settings = get_settings()


@asynccontextmanager
async def lifespan(_: FastAPI):
    """Initialize process-wide infrastructure before serving requests."""
    configure_logging(settings.log_level)
    yield


app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description=(
        "API contract for the AI-Powered Agentic Software Engineering Platform. "
        "All public endpoints are versioned under /api/v1."
    ),
    openapi_url="/openapi.json",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)
app.add_middleware(RequestIdMiddleware)
app.include_router(api_router, prefix=settings.api_v1_prefix)
