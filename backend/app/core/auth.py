"""Authentication middleware for JWT-protected API routes."""

from __future__ import annotations

import asyncio
import inspect
import logging
import re
import time
from urllib.parse import urlparse

from fastapi import Request
from starlette.types import ASGIApp, Receive, Scope, Send

from app.core.config import get_settings
from app.core.errors import APIError, ErrorCode, error_response
from app.core.redis import get_redis, get_redis_async
from app.core.security import decode_access_token

logger = logging.getLogger(__name__)

# Short-lived in-memory cache and in-flight deduplicator for token revocation checks
# Prevents connection pool starvation and timeout errors when browsers fire parallel requests
_BLOCKLIST_CACHE: dict[str, tuple[bool, float]] = {}  # jti -> (is_revoked, expires_at)
_IN_FLIGHT_CHECKS: dict[str, asyncio.Future] = {}


_REVOCATION_CHANNEL = "auth:revocations"


def revoke_token_in_cache(jti: str) -> None:
    """Mark a token as revoked in the local memory cache."""
    _BLOCKLIST_CACHE[jti] = (True, time.monotonic() + 300.0)


def publish_token_revocation(jti: str, redis_client: Any = None) -> None:
    """Best-effort cross-worker revocation broadcast on Redis pub/sub."""
    if not jti:
        return
    try:
        client = redis_client or get_redis()
        if client is not None and hasattr(client, "publish"):
            client.publish(_REVOCATION_CHANNEL, jti)
    except Exception as exc:
        logger.debug("auth_revocation_publish_failed", extra={"error": str(exc)})


async def revocation_subscriber_loop(stop_event: asyncio.Event | None = None) -> None:
    """Listen for cross-worker token revocations and update the local blocklist cache."""
    while stop_event is None or not stop_event.is_set():
        pubsub = None
        try:
            redis = await get_redis_async()
            pubsub = redis.pubsub()
            await pubsub.subscribe(_REVOCATION_CHANNEL)
            while stop_event is None or not stop_event.is_set():
                msg = await pubsub.get_message(ignore_subscribe_messages=True, timeout=5.0)
                if msg and msg.get("type") == "message":
                    raw = msg.get("data")
                    jti = raw.decode("utf-8") if isinstance(raw, bytes) else str(raw or "")
                    if jti:
                        revoke_token_in_cache(jti)
        except asyncio.CancelledError:
            break
        except Exception as exc:
            logger.debug("auth_revocation_subscriber_backoff", extra={"error": str(exc)})
            await asyncio.sleep(5.0)
        finally:
            if pubsub is not None:
                try:
                    await pubsub.unsubscribe(_REVOCATION_CHANNEL)
                    await pubsub.close()
                except Exception as exc:
                    logger.debug("auth_revocation_pubsub_cleanup_failed", extra={"error": str(exc)})


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
    "/api/v1/github/webhook",
    "/api/v1/github/installation/callback",
    "/api/v1/auth/refresh",
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
            except Exception as exc:
                logger.debug("in_flight_blocklist_check_failed", extra={"error": str(exc)})

    loop = asyncio.get_running_loop()
    fut = loop.create_future() if is_live_environment else None
    if fut is not None:
        _IN_FLIGHT_CHECKS[jti] = fut

    try:
        res = await _check_redis_blocklist(jti, is_live_environment)
        if fut is not None and not fut.done():
            fut.set_result(res)
        if is_live_environment:
            # Revoked tokens stay revoked (300s); valid tokens are cached 30s (invalidated via pub/sub on logout)
            ttl = 300.0 if res else 30.0
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

        timeout_sec = 1.0
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
                    return bool(await asyncio.wait_for(asyncio.to_thread(sync_client.exists, key), timeout=0.8))
            except Exception as sync_exc:
                logger.debug("auth_blocklist_sync_check_failed", extra={"error": str(sync_exc)})
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
                    return bool(await asyncio.wait_for(asyncio.to_thread(sync_client.exists, key), timeout=0.8))
            except Exception as sync_err:
                logger.debug("auth_blocklist_sync_fallback_failed", extra={"error": str(sync_err)})

        if "timeout" in err_msg or "timed out" in err_msg:
            logger.warning("auth_blocklist_timeout", extra={"jti": jti, "error": str(exc)})
        else:
            logger.warning("auth_blocklist_check_failed", extra={"jti": jti, "error": str(exc)})
        raise APIError(503, ErrorCode.SERVICE_UNAVAILABLE, "Authentication service is unavailable.", retryable=True) from exc


class JWTMiddleware:
    """Pure ASGI middleware populating request state from Bearer tokens or auth cookies."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        scope.setdefault("state", {})
        request = Request(scope)
        path = request.url.path
        is_public = (
            path in PUBLIC_PATHS
            or path.startswith("/api/v1/auth/github/")
            or path == "/api/v1/auth/dev-login"
            or path == "/api/v1/auth/refresh"
        )
        if is_public:
            await _try_populate_user_state(request)
            await self.app(scope, receive, send)
            return

        token, auth_source = _get_token_and_source(request)
        if not token:
            resp = error_response(401, ErrorCode.UNAUTHORIZED, "Authentication is required.")
            await resp(scope, receive, send)
            return

        # CSRF Protection: For state-changing requests authenticated by cookies, validate Origin
        if auth_source == "cookie" and request.method in {"POST", "PUT", "PATCH", "DELETE"}:
            csrf_error = csrf_origin_error(request)
            if csrf_error is not None:
                logger.warning(
                    "untrusted_origin_rejected",
                    extra={"origin": request.headers.get("origin"), "path": path},
                )
                resp = error_response(403, ErrorCode.FORBIDDEN, csrf_error)
                await resp(scope, receive, send)
                return

        try:
            claims = decode_access_token(token)
            jti = str(claims["jti"])
            if await _is_token_blocklisted_async(jti):
                resp = error_response(401, ErrorCode.UNAUTHORIZED, "Access token has been revoked.")
                await resp(scope, receive, send)
                return
            request.state.user_id = str(claims["sub"])
            request.state.token_jti = jti
            request.state.token_exp = int(claims["exp"])
            request.state.role = _claim_role(claims)
            request.state.permissions = list(claims.get("permissions", []))
        except APIError as exc:
            resp = error_response(exc.status_code, exc.code, exc.message, retryable=exc.retryable)
            await resp(scope, receive, send)
            return
        except Exception:
            resp = error_response(503, ErrorCode.SERVICE_UNAVAILABLE, "Authentication service is unavailable.", retryable=True)
            await resp(scope, receive, send)
            return

        await self.app(scope, receive, send)


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
            request.state.role = _claim_role(claims)
            request.state.permissions = list(claims.get("permissions", []))
    except Exception as exc:
        logger.debug("Failed validating token in auth middleware: %s", exc)


def _claim_role(claims: dict) -> str:
    """Normalize the role claim; unknown values degrade to the least-privileged role."""
    role = claims.get("role")
    if role is None or (isinstance(role, str) and not role.strip()):
        return "developer"
    role_str = str(role).strip().lower()
    return role_str if role_str in {"viewer", "developer", "admin"} else "viewer"


def _is_trusted_origin(origin: str) -> bool:
    settings = get_settings()
    origin_clean = origin.strip().rstrip("/")
    if origin_clean in {o.rstrip("/") for o in settings.cors_origins}:
        return True
    effective_regex = getattr(settings, "effective_cors_origin_regex", settings.cors_origin_regex)
    # fullmatch: a prefix-only match would accept https://trusted.example.com.evil.net
    return bool(effective_regex) and re.fullmatch(effective_regex, origin_clean) is not None


def csrf_origin_error(request: Request) -> str | None:
    """Return an error message when a cookie-authenticated mutation comes from an untrusted origin.

    Browsers always send Origin on cross-site POST/PUT/PATCH/DELETE, so a missing Origin is
    tolerated only outside production (curl, TestClient). In production the Referer must then
    match a trusted origin.
    """
    origin = request.headers.get("origin")
    if origin:
        return None if _is_trusted_origin(origin) else "Cross-origin request rejected."
    if not get_settings().is_production:
        return None
    referer = request.headers.get("referer")
    if not referer:
        return "Origin header is required for cookie-authenticated requests."
    parsed = urlparse(referer)
    if not parsed.scheme or not parsed.netloc:
        return "Cross-origin request rejected."
    return None if _is_trusted_origin(f"{parsed.scheme}://{parsed.netloc}") else "Cross-origin request rejected."


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
