"""Authentication middleware for JWT-protected API routes."""

from __future__ import annotations

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

from app.core.config import get_settings
from app.core.errors import APIError, ErrorCode, error_response
from app.core.redis import get_redis
from app.core.security import decode_access_token


PUBLIC_PATHS = {"/docs", "/openapi.json", "/redoc", "/api/v1/health"}


class JWTMiddleware(BaseHTTPMiddleware):
    """Populate request state from a Bearer token or the HTTP-only auth cookie."""

    async def dispatch(self, request: Request, call_next) -> Response:
        if request.url.path in PUBLIC_PATHS or request.url.path.startswith("/api/v1/auth/github/"):
            return await call_next(request)

        token = _get_token(request)
        if not token:
            return error_response(401, ErrorCode.UNAUTHORIZED, "Authentication is required.")
        try:
            claims = decode_access_token(token)
            jti = str(claims["jti"])
            if get_redis().exists(f"auth:blocklist:{jti}"):
                return error_response(401, ErrorCode.UNAUTHORIZED, "Access token has been revoked.")
            request.state.user_id = str(claims["sub"])
            request.state.token_jti = jti
            request.state.token_exp = int(claims["exp"])
        except APIError as exc:
            return error_response(exc.status_code, exc.code, exc.message, retryable=exc.retryable)
        except Exception:
            return error_response(503, ErrorCode.SERVICE_UNAVAILABLE, "Authentication service is unavailable.", retryable=True)
        return await call_next(request)


def _get_token(request: Request) -> str | None:
    authorization = request.headers.get("Authorization", "")
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() == "bearer" and token:
        return token
    return request.cookies.get(get_settings().auth_cookie_name)
