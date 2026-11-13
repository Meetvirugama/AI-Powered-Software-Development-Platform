"""Authentication middleware for JWT-protected API routes."""

from __future__ import annotations

import asyncio
import inspect
import logging
import time

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

from app.core.config import get_settings
from app.core.errors import APIError, ErrorCode, error_response
from app.core.redis import get_redis, get_redis_async
from app.core.security import decode_access_token

logger = logging.getLogger(__name__)

# Short-lived in-memory cache and in-flight deduplicator for token revocation checks
# Prevents connection pool starvation and timeout errors when browsers fire parallel requests
_BLOCKLIST_CACHE: dict[str, tuple[bool, float]] = {}  # jti -> (is_revoked, expires_at)
_IN_FLIGHT_CHECKS: dict[str, asyncio.Future] = {}


def revoke_token_in_cache(jti: str) -> None:
    """Mark a token as revoked in the local memory cache."""
    _BLOCKLIST_CACHE[jti] = (True, time.monotonic() + 300.0)


def clear_blocklist_cache() -> None:
    """Clear memory blocklist cache (primarily for tests)."""
    _BLOCKLIST_CACHE.clear()
    _IN_FLIGHT_CHECKS.clear()


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
    "/api/v1/auth/dev-login",
    "/api/v1/github/webhook",
    "/api/v1/github/installation/callback",
}


async def _is_token_blocklisted_async(jti: str) -> bool:
    """Check if token jti is revoked without blocking the async event loop."""
    from app.core.redis import get_redis as default_get_redis
    is_live_environment = (get_redis is default_get_redis)

    now = time.monotonic()
    if is_live_environment:
        cached = _BLOCKLIST_CACHE.get(jti)
        if cached is not None:
            is_revoked, expires_at = cached
            if now < expires_at:
                return is_revoked

        # In-flight deduplication: if an identical check is already in-progress, join it
        existing_fut = _IN_FLIGHT_CHECKS.get(jti)
        if existing_fut is not None and not existing_fut.done():
            try:
                return await asyncio.shield(existing_fut)
            except Exception:
                pass

    loop = asyncio.get_running_loop()
    fut = loop.create_future() if is_live_environment else None
    if fut is not None:
        _IN_FLIGHT_CHECKS[jti] = fut

    try:
        res = await _check_redis_blocklist(jti, is_live_environment)
        if fut is not None and not fut.done():
            fut.set_result(res)
        if is_live_environment:
            # Revoked tokens stay revoked (300s); valid tokens are cached 5s to absorb parallel bursts
            ttl = 300.0 if res else 5.0
            _BLOCKLIST_CACHE[jti] = (res, time.monotonic() + ttl)
        return res
    except Exception as exc:
        if fut is not None and not fut.done():
            fut.set_exception(exc)
        raise
    finally:
        if is_live_environment:
            _IN_FLIGHT_CHECKS.pop(jti, None)


async def _check_redis_blocklist(jti: str, is_live_environment: bool) -> bool:
    key = f"auth:blocklist:{jti}"
    try:
        from app.core.redis import get_redis as default_get_redis
        if get_redis is not default_get_redis:
            client = get_redis()
        else:
            client = await get_redis_async()
    except Exception:
        client = get_redis()

    if client is None:
        logger.warning("auth_blocklist_missing_client", extra={"jti": jti})
        raise APIError(503, ErrorCode.SERVICE_UNAVAILABLE, "Authentication service is unavailable.", retryable=True)

    try:
        exists_fn = getattr(client, "exists", None)
        if exists_fn is None:
            logger.warning("auth_blocklist_missing_exists", extra={"jti": jti})
            raise APIError(503, ErrorCode.SERVICE_UNAVAILABLE, "Authentication service is unavailable.", retryable=True)

        timeout_sec = 2.5
        if inspect.iscoroutinefunction(exists_fn):
            res = await asyncio.wait_for(exists_fn(key), timeout=timeout_sec)
        else:
            res = await asyncio.wait_for(asyncio.to_thread(exists_fn, key), timeout=timeout_sec)
            if inspect.isawaitable(res):
                res = await asyncio.wait_for(res, timeout=timeout_sec)
        return bool(res)
    except (TimeoutError, asyncio.TimeoutError) as exc:
        if is_live_environment:
            try:
                from app.core.redis import get_redis as sync_get_redis
                sync_client = sync_get_redis()
                if sync_client is not None:
                    return bool(await asyncio.wait_for(asyncio.to_thread(sync_client.exists, key), timeout=2.0))
            except Exception:
                pass
        logger.warning("auth_blocklist_timeout", extra={"jti": jti, "error": str(exc)})
        raise APIError(503, ErrorCode.SERVICE_UNAVAILABLE, "Authentication service is unavailable.", retryable=True) from exc
    except APIError:
        raise
    except Exception as exc:
        # If async client failed due to closed or mismatched event loop, fall back to synchronous client
        err_msg = str(exc).lower()
        if "loop" in err_msg or "closed" in err_msg:
            import app.core.redis as r_mod
            r_mod._async_redis_client = None
            try:
                from app.core.redis import get_redis as sync_get_redis
                sync_client = sync_get_redis()
                if sync_client is not None:
                    return bool(await asyncio.to_thread(sync_client.exists, key))
            except Exception:
                pass

        if "timeout" in err_msg or "timed out" in err_msg:
            logger.warning("auth_blocklist_timeout", extra={"jti": jti, "error": str(exc)})
        else:
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
            app_settings = get_settings()
            trusted_origins = {o.rstrip("/") for o in app_settings.cors_origins}
            effective_regex = getattr(app_settings, "effective_cors_origin_regex", app_settings.cors_origin_regex)
            if origin:
                origin_clean = origin.rstrip("/")
                is_trusted = origin_clean in trusted_origins
                if not is_trusted and effective_regex:
                    import re
                    is_trusted = bool(re.match(effective_regex, origin_clean))
                if not is_trusted:
                    logger.warning("untrusted_origin_rejected", extra={"origin": origin, "path": request.url.path})
                    return error_response(403, ErrorCode.FORBIDDEN, "Cross-origin request rejected.")
            elif app_settings.is_production:
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
