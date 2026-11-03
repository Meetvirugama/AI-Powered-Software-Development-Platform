"""Authentication middleware for JWT-protected API routes."""

from __future__ import annotations

import asyncio
import inspect
import logging

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

from app.core.config import get_settings
from app.core.errors import APIError, ErrorCode, error_response
from app.core.redis import get_redis
from app.core.security import decode_access_token

logger = logging.getLogger(__name__)


PUBLIC_PATHS = {
    "/docs",
    "/openapi.json",
    "/redoc",
    "/health",
    "/health/live",
    "/health/ready",
    "/api/v1/health",
    "/api/v1/health/live",
    "/api/v1/health/ready",
    "/api/v1/events",
    "/api/v1/github/webhook",
    "/api/v1/github/installation/callback",
}


async def _is_token_blocklisted_async(jti: str) -> bool:
    """Check if token jti is revoked without blocking the async event loop."""
    key = f"auth:blocklist:{jti}"
    client = get_redis()
    try:
        exists_fn = getattr(client, "exists", None)
        if exists_fn is None:
            return False
        if inspect.iscoroutinefunction(exists_fn):
            res = await asyncio.wait_for(exists_fn(key), timeout=1.5)
        else:
            res = await asyncio.wait_for(asyncio.to_thread(exists_fn, key), timeout=1.5)
            if inspect.isawaitable(res):
                res = await asyncio.wait_for(res, timeout=1.5)
        return bool(res)
    except TimeoutError as exc:
        logger.warning("auth_blocklist_timeout", extra={"jti": jti, "error": str(exc)})
        raise APIError(503, ErrorCode.SERVICE_UNAVAILABLE, "Authentication service is unavailable.", retryable=True) from exc
    except APIError:
        raise
    except Exception as exc:
        logger.warning("auth_blocklist_check_failed", extra={"jti": jti, "error": str(exc)})
        raise APIError(503, ErrorCode.SERVICE_UNAVAILABLE, "Authentication service is unavailable.", retryable=True) from exc


class JWTMiddleware(BaseHTTPMiddleware):
    """Populate request state from a Bearer token or the HTTP-only auth cookie."""

    async def dispatch(self, request: Request, call_next) -> Response:
        if request.url.path in PUBLIC_PATHS or request.url.path.startswith("/api/v1/auth/github/"):
            await _try_populate_user_state(request)
            return await call_next(request)

        token, auth_source = _get_token_and_source(request)
        if not token:
            return error_response(401, ErrorCode.UNAUTHORIZED, "Authentication is required.")

        # CSRF Protection: For state-changing requests authenticated by cookies, validate Origin
        if auth_source == "cookie" and request.method in {"POST", "PUT", "PATCH", "DELETE"}:
            origin = request.headers.get("origin")
            trusted_origins = {o.rstrip("/") for o in get_settings().cors_origins}
            if origin:
                if origin.rstrip("/") not in trusted_origins:
                    logger.warning("untrusted_origin_rejected", extra={"origin": origin, "path": request.url.path})
                    return error_response(403, ErrorCode.FORBIDDEN, "Cross-origin request rejected.")
            elif get_settings().is_production:
                referer = request.headers.get("referer")
                if referer:
                    from urllib.parse import urlparse
                    ref_parsed = urlparse(referer)
                    ref_origin = f"{ref_parsed.scheme}://{ref_parsed.netloc}".rstrip("/")
                    if ref_origin not in trusted_origins:
                        return error_response(403, ErrorCode.FORBIDDEN, "Cross-origin request rejected.")
                else:
                    return error_response(403, ErrorCode.FORBIDDEN, "Origin header is required for cookie-authenticated requests.")

        try:
            claims = decode_access_token(token)
            jti = str(claims["jti"])
            if await _is_token_blocklisted_async(jti):
                return error_response(401, ErrorCode.UNAUTHORIZED, "Access token has been revoked.")
            request.state.user_id = str(claims["sub"])
            request.state.token_jti = jti
            request.state.token_exp = int(claims["exp"])
        except APIError as exc:
            return error_response(exc.status_code, exc.code, exc.message, retryable=exc.retryable)
        except Exception:
            return error_response(503, ErrorCode.SERVICE_UNAVAILABLE, "Authentication service is unavailable.", retryable=True)
        return await call_next(request)


async def _try_populate_user_state(request: Request) -> None:
    """Opportunistically populate request.state.user_id on public/callback routes when a valid token is present."""
    token, _ = _get_token_and_source(request)
    if not token:
        return
    try:
        claims = decode_access_token(token)
        jti = str(claims["jti"])
        is_revoked = await _is_token_blocklisted_async(jti)
        if not is_revoked:
            request.state.user_id = str(claims["sub"])
            request.state.token_jti = jti
            request.state.token_exp = int(claims["exp"])
    except Exception:
        pass


def _get_token_and_source(request: Request) -> tuple[str | None, str]:
    authorization = request.headers.get("Authorization", "")
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() == "bearer" and token:
        return token, "bearer"
    cookie_token = request.cookies.get(get_settings().auth_cookie_name)
    if cookie_token:
        return cookie_token, "cookie"
    return None, "none"


def _get_token(request: Request) -> str | None:
    token, _ = _get_token_and_source(request)
    return token
