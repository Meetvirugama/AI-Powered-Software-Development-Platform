"""FastAPI application factory and public OpenAPI contract."""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.v1.health import router as health_router
from app.api.v1.router import api_router
from app.core.auth import JWTMiddleware
from app.core.config import get_settings
from app.core.errors import (
    APIError,
    api_error_handler,
    http_exception_handler,
    unhandled_exception_handler,
    validation_exception_handler,
)
from app.core.logging import RequestIdMiddleware, configure_logging
from app.core.rate_limit import RateLimitMiddleware
from app.core.security_headers import SecurityHeadersMiddleware
from fastapi.exceptions import RequestValidationError

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
# Middleware order: the LAST one added runs FIRST (outermost). Resulting order
# for an incoming request:
#   SecurityHeaders → CORS → JWT → RequestId → RateLimit → route
# - SecurityHeaders is outermost so every response (401, 429, 500, preflight) gets the headers.
# - CORS sits outside JWT so browser OPTIONS preflights are answered without a token.
# - RateLimit sits inside JWT so request.state.user_id is available for per-user limits.
app.add_middleware(RateLimitMiddleware, api_prefix=settings.api_v1_prefix)
app.add_middleware(RequestIdMiddleware)
app.add_middleware(JWTMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,  # the auth JWT travels in an httpOnly cookie
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization", "X-Request-ID"],
    expose_headers=["X-Request-ID", "Retry-After", "X-RateLimit-Limit", "X-RateLimit-Remaining", "X-RateLimit-Reset"],
    max_age=600,
)
app.add_middleware(SecurityHeadersMiddleware, trust_proxy_headers=settings.trust_proxy_headers)
app.add_exception_handler(APIError, api_error_handler)
app.add_exception_handler(StarletteHTTPException, http_exception_handler)
app.add_exception_handler(RequestValidationError, validation_exception_handler)
app.add_exception_handler(Exception, unhandled_exception_handler)
app.include_router(health_router)
app.include_router(api_router, prefix=settings.api_v1_prefix)
