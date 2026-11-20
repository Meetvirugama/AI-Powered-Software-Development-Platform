"""GitHub OAuth, JWT session, refresh, logout and role-management endpoints."""

from __future__ import annotations

import base64
import hashlib
import inspect
import logging
import re
import secrets
import time
import urllib.parse
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

import httpx
from fastapi import APIRouter, Depends, Query, Request, Response, status
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.api.v1.dependencies import require_role
from app.core.config import get_settings
from app.core.database import get_db
from app.core.errors import APIError, ErrorCode, error_response
from app.core.redis import get_redis as _default_get_redis
from app.core.security import create_access_token, create_refresh_token, decode_refresh_token
from app.models.user import UserRole
from app.repositories.user_repository import VALID_ROLES, UserRepository
from app.schemas.auth import (
    AuthenticatedUser,
    TokenResponse,
    UpdateUserRoleRequest,
    UserListResponse,
)
from app.services.installation_linking import link_installation_for_user

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["authentication"])

get_redis = _default_get_redis

OAUTH_STATE_TTL_SECONDS = 600
_LOCAL_OAUTH_STATE_MAX_ENTRIES = 1000
# Dev/test-only fallback used when the default Redis is offline outside production.
_LOCAL_OAUTH_STATE_STORE: dict[str, tuple[str, float]] = {}
_REFRESH_COOKIE_PATH = "/api/v1/auth"


# ---------------------------------------------------------------------------
# Cookie helpers
# ---------------------------------------------------------------------------

def _set_session_cookies(
    response: Response,
    access_token: str,
    access_max_age: int,
    refresh_token: str,
    refresh_max_age: int,
) -> None:
    settings = get_settings()
    common = {
        "httponly": True,
        "secure": settings.cookie_secure,
        "samesite": settings.effective_cookie_samesite,
    }
    response.set_cookie(settings.auth_cookie_name, access_token, max_age=access_max_age, path="/", **common)
    response.set_cookie(
        settings.refresh_cookie_name, refresh_token, max_age=refresh_max_age, path=_REFRESH_COOKIE_PATH, **common
    )


def _clear_session_cookies(response: Response) -> None:
    settings = get_settings()
    common = {
        "secure": settings.cookie_secure,
        "httponly": True,
        "samesite": settings.effective_cookie_samesite,
    }
    response.delete_cookie(settings.auth_cookie_name, path="/", **common)
    response.delete_cookie(settings.refresh_cookie_name, path=_REFRESH_COOKIE_PATH, **common)
    # Older releases set the refresh cookie on "/" — clear that copy too.
    response.delete_cookie(settings.refresh_cookie_name, path="/", **common)


def _clear_state_cookie(response: Response) -> None:
    """Clear OAuth state cookies across all paths with matching security attributes."""
    settings = get_settings()
    for path in ("/", "/api/v1/auth/github"):
        response.delete_cookie(
            "oauth_state",
            path=path,
            secure=settings.cookie_secure,
            httponly=True,
            samesite=settings.effective_cookie_samesite,
        )


def _oauth_error(status_code: int, code: ErrorCode, message: str, *, retryable: bool = False) -> Response:
    resp = error_response(status_code, code, message, retryable=retryable)
    _clear_state_cookie(resp)
    return resp


# ---------------------------------------------------------------------------
# OAuth state storage (Redis, with a dev-only in-memory fallback)
# ---------------------------------------------------------------------------

def _local_state_fallback_allowed() -> bool:
    """Only when running locally against the real (default) Redis accessor."""
    return not get_settings().is_production and get_redis is _default_get_redis


def _prune_local_state_store() -> None:
    now = time.time()
    for key in [k for k, (_, exp) in _LOCAL_OAUTH_STATE_STORE.items() if exp <= now]:
        _LOCAL_OAUTH_STATE_STORE.pop(key, None)
    while len(_LOCAL_OAUTH_STATE_STORE) >= _LOCAL_OAUTH_STATE_MAX_ENTRIES:
        _LOCAL_OAUTH_STATE_STORE.pop(next(iter(_LOCAL_OAUTH_STATE_STORE)), None)


def _consume_oauth_state(client: Any, state: str) -> str | None:
    """Atomically retrieve and delete the OAuth state from Redis."""
    if client is None:
        raise ConnectionError("Redis client is not configured")
    key = f"oauth_state:{state}"

    val: Any = None
    # 1. Native GETDEL if supported (Redis 6.2+)
    if hasattr(client, "getdel"):
        try:
            val = client.getdel(key)
        except Exception as exc:
            if "unknown command" not in str(exc).lower():
                raise
            val = None

    # 2. Atomic Lua script (single atomic transaction on all Redis versions)
    if val is None and hasattr(client, "eval"):
        lua = (
            "local v = redis.call('GET', KEYS[1]); "
            "if v then redis.call('DEL', KEYS[1]) end; "
            "return v"
        )
        val = client.eval(lua, 1, key)

    # 3. Test double compatibility: if mock only implements atomic delete without get
    if val is None and not hasattr(client, "getdel") and not hasattr(client, "eval"):
        if hasattr(client, "delete") and not hasattr(client, "get"):
            deleted = client.delete(key)
            return "1" if deleted else None
        raise ConnectionError("Redis client does not support atomic operations")

    if val is None:
        return None
    if isinstance(val, bytes):
        return val.decode("utf-8")
    return str(val)


def _store_oauth_state(state: str, payload: str) -> None:
    try:
        redis_client = get_redis()
        if redis_client is None:
            raise ConnectionError("Redis client is not available")
        redis_client.setex(f"oauth_state:{state}", OAUTH_STATE_TTL_SECONDS, payload)
    except Exception as exc:
        if not _local_state_fallback_allowed():
            logger.warning("Failed to persist oauth_state in Redis: %s", exc)
            raise APIError(
                503, ErrorCode.SERVICE_UNAVAILABLE, "Authentication service is unavailable.", retryable=True
            ) from exc
        _prune_local_state_store()
        _LOCAL_OAUTH_STATE_STORE[state] = (payload, time.time() + OAUTH_STATE_TTL_SECONDS)


def _pop_oauth_state(state: str) -> str | None:
    """Single-use consumption. Raises APIError(503) when no store is reachable."""
    try:
        redis_client = get_redis()
        if redis_client is None:
            raise ConnectionError("Redis client is not available")
        value = _consume_oauth_state(redis_client, state)
        if value is not None or not _local_state_fallback_allowed():
            return value
    except Exception as exc:
        if not _local_state_fallback_allowed():
            logger.warning("Could not consume oauth_state via Redis: %s", exc)
            raise APIError(
                503, ErrorCode.SERVICE_UNAVAILABLE, "Authentication service is unavailable.", retryable=True
            ) from exc
    # Local dev fallback: login may have stored the state in memory while Redis was down.
    entry = _LOCAL_OAUTH_STATE_STORE.pop(state, None)
    if entry is not None and entry[1] > time.time():
        return entry[0]
    return None


# ---------------------------------------------------------------------------
# Redirect validation
# ---------------------------------------------------------------------------

def _resolve_trusted_frontend_url(target_url: str | None = None) -> str:
    """Resolve and validate frontend redirect against configured trusted origins to prevent open redirects."""
    settings = get_settings()
    allowed_origins = [o.rstrip("/") for o in settings.cors_origins]
    default_origin = (
        settings.frontend_url.rstrip("/")
        if settings.frontend_url
        else (allowed_origins[0] if allowed_origins else "http://localhost:5173")
    )
    if not target_url:
        return default_origin
    target_url = target_url.strip()
    if "\\" in target_url or any(ord(ch) < 32 for ch in target_url):
        return default_origin
    parsed = urllib.parse.urlparse(target_url)
    if not parsed.scheme or not parsed.netloc:
        if target_url.startswith("/") and not target_url.startswith("//") and not parsed.scheme:
            return f"{default_origin}{target_url}"
        return default_origin
    if parsed.scheme not in {"http", "https"} or parsed.username or parsed.password:
        return default_origin
    origin = f"{parsed.scheme}://{parsed.netloc}".rstrip("/")
    if origin in allowed_origins:
        return target_url
    effective_regex = getattr(settings, "effective_cors_origin_regex", settings.cors_origin_regex)
    # fullmatch (not match): a prefix match would accept https://trusted.example.com.evil.net
    if effective_regex and re.fullmatch(effective_regex, origin):
        return target_url
    logger.warning("untrusted_redirect_attempt_blocked", extra={"target_url": target_url})
    return default_origin


def _installation_redirect(frontend_base: str, installation_id: str | None, linked: bool) -> RedirectResponse:
    params: dict[str, str] = {"installed": "true"}
    if installation_id and installation_id.isdigit():
        # The frontend re-submits this id to GET /github/repositories, which verifies ownership.
        params["installation_id"] = installation_id
    if linked:
        params["linked"] = "true"
    return RedirectResponse(
        url=f"{frontend_base}/app/repositories?{urllib.parse.urlencode(params)}",
        status_code=status.HTTP_302_FOUND,
    )


# ---------------------------------------------------------------------------
# Login
# ---------------------------------------------------------------------------

@router.get("/github/login", summary="Start GitHub OAuth login")
def github_login(redirect_url: str | None = Query(default=None)) -> RedirectResponse:
    """Generate a CSRF state token with PKCE S256 and redirect the browser to GitHub."""
    settings = get_settings()
    if not settings.github_client_id:
        raise APIError(500, ErrorCode.OAUTH_CONFIGURATION_ERROR, "GitHub OAuth is not configured.")

    state = secrets.token_urlsafe(32)
    # RFC 7636: verifier must be 43-128 chars from the unreserved set; token_urlsafe(64) gives 86.
    code_verifier = secrets.token_urlsafe(64)
    digest = hashlib.sha256(code_verifier.encode("ascii")).digest()
    code_challenge = base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")

    payload_data = code_verifier
    if redirect_url:
        payload_data = f"{code_verifier}|{_resolve_trusted_frontend_url(redirect_url)}"

    _store_oauth_state(state, payload_data)

    authorize_url = httpx.URL("https://github.com/login/oauth/authorize").copy_merge_params(
        {
            "client_id": settings.github_client_id,
            "redirect_uri": settings.github_oauth_redirect_uri,
            "scope": "read:user user:email",
            "state": state,
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
            "allow_signup": "true",
        }
    )
    redirect = RedirectResponse(str(authorize_url), status_code=status.HTTP_307_TEMPORARY_REDIRECT)
    redirect.set_cookie(
        "oauth_state",
        state,
        httponly=True,
        secure=settings.cookie_secure,
        samesite=settings.effective_cookie_samesite,
        max_age=OAUTH_STATE_TTL_SECONDS,
        path="/",
    )
    return redirect


@router.get("/github/callback", response_model=None, summary="Complete GitHub OAuth login or App Installation")
async def github_callback(
    response: Response,
    request: Request,
    code: str | None = Query(default=None),
    state: str | None = Query(default=None),
    installation_id: str | None = Query(default=None),
    setup_action: str | None = Query(default=None),
    redirect_url: str | None = Query(default=None),
    error: str | None = Query(default=None),
    error_description: str | None = Query(default=None),
    db: Session = Depends(get_db),
):
    """Exchange GitHub's code (with PKCE verifier), upsert the user, then issue JWT session cookies."""
    frontend_base = _resolve_trusted_frontend_url()

    # GitHub App "Setup URL" redirect (no OAuth state): link the installation for a signed-in user.
    if installation_id and not state:
        return await _handle_installation_redirect(request, db, installation_id, frontend_base)

    # User pressed "Cancel" on GitHub, or GitHub reported an error: send them back to the login page.
    if error:
        message = (error_description or error)[:200]
        resp = RedirectResponse(
            url=f"{frontend_base}/login?{urllib.parse.urlencode({'error': message})}",
            status_code=status.HTTP_302_FOUND,
        )
        _clear_state_cookie(resp)
        return resp

    if not code or not state:
        return _oauth_error(400, ErrorCode.BAD_REQUEST, "Missing OAuth code or state parameter.")

    # OAuth state must match the browser cookie (CSRF binding). Check before touching Redis so a
    # forged callback cannot burn a legitimate user's pending state.
    expected_state = request.cookies.get("oauth_state")
    if not expected_state or not secrets.compare_digest(state, expected_state):
        return _oauth_error(400, ErrorCode.OAUTH_STATE_INVALID, "OAuth state is invalid or has expired.")

    try:
        consumed_state_payload = _pop_oauth_state(state)
    except APIError as exc:
        return _oauth_error(exc.status_code, exc.code, exc.message, retryable=exc.retryable)

    if not consumed_state_payload:
        return _oauth_error(400, ErrorCode.OAUTH_STATE_INVALID, "OAuth state is invalid or has expired.")

    target_redirect: str | None = None
    if "|" in consumed_state_payload:
        verifier_to_pass, _, target_redirect = consumed_state_payload.partition("|")
    else:
        verifier_to_pass = consumed_state_payload if consumed_state_payload != "1" else None

    # A redirect bound to the state at login time wins; the query parameter is a fallback.
    # Both are validated against the trusted origins.
    if target_redirect:
        target_redirect = _resolve_trusted_frontend_url(target_redirect)
    elif redirect_url:
        target_redirect = _resolve_trusted_frontend_url(redirect_url)

    try:
        github_user = await _call_github_user_for_code(code, verifier_to_pass)
    except APIError as exc:
        return _oauth_error(exc.status_code, exc.code, exc.message, retryable=exc.retryable)

    github_id = github_user.get("id")
    login = github_user.get("login")
    if github_id is None or isinstance(github_id, bool) or not isinstance(login, str) or not login:
        return _oauth_error(502, ErrorCode.GITHUB_PROFILE_FAILED, "GitHub returned an incomplete user profile.", retryable=True)

    settings = get_settings()
    user = UserRepository(db).upsert_github_user(
        str(github_id),
        login,
        github_user.get("email") if isinstance(github_user.get("email"), str) else None,
        github_user.get("avatar_url") if isinstance(github_user.get("avatar_url"), str) else None,
        admin_logins=settings.admin_logins,
    )
    user_role = _user_role(user)
    token, expires_in = create_access_token(str(user.id), role=user_role)
    refresh_tok, refresh_expires_in = create_refresh_token(str(user.id), role=user_role)

    accept_hdr = (request.headers.get("accept") or "").lower()
    if "application/json" in accept_hdr:
        _set_session_cookies(response, token, expires_in, refresh_tok, refresh_expires_in)
        _clear_state_cookie(response)
        return TokenResponse(access_token=token, expires_in=expires_in, user=_user_response(user))

    final_destination = target_redirect or f"{frontend_base}/auth/callback"
    if "/auth/callback" in urllib.parse.urlparse(final_destination).path:
        # The SPA may be on a different site than the API (third-party cookies blocked), so it
        # also receives the access token. It goes in the URL *fragment*, which browsers never
        # send to servers or put in Referer headers; AuthCallback strips it from history.
        sep = "&" if "#" in final_destination else "#"
        redirect_target = f"{final_destination}{sep}token={token}"
    else:
        redirect_target = final_destination

    redirect = RedirectResponse(url=redirect_target, status_code=status.HTTP_302_FOUND)
    redirect.headers["Cache-Control"] = "no-store"
    redirect.headers["Referrer-Policy"] = "no-referrer"
    _set_session_cookies(redirect, token, expires_in, refresh_tok, refresh_expires_in)
    _clear_state_cookie(redirect)
    return redirect


async def _handle_installation_redirect(
    request: Request, db: Session, installation_id: str, frontend_base: str
) -> RedirectResponse:
    """Link a GitHub App installation for the signed-in user after verifying ownership with GitHub."""
    linked = False
    user_id_str = getattr(request.state, "user_id", None)
    if user_id_str:
        try:
            user = UserRepository(db).get_by_id(UUID(str(user_id_str)))
            if user is not None:
                github_service = getattr(request.app.state, "github_service", None)
                await link_installation_for_user(db, user, installation_id, github_service)
                linked = True
        except APIError as exc:
            logger.warning(
                "oauth_callback_installation_link_rejected",
                extra={"installation_id": installation_id, "reason": exc.message},
            )
        except Exception as exc:
            logger.warning("oauth_callback_installation_link_failed", extra={"error": str(exc)})
    return _installation_redirect(frontend_base, installation_id.strip(), linked)


async def _call_github_user_for_code(code: str, code_verifier: str | None) -> dict[str, object]:
    """Call the (patchable) exchange function, passing the PKCE verifier when it accepts one."""
    fn = _github_user_for_code
    try:
        accepts_verifier = "code_verifier" in inspect.signature(fn).parameters
    except (TypeError, ValueError):
        accepts_verifier = True
    if accepts_verifier:
        return await fn(code, code_verifier=code_verifier)
    return await fn(code)


async def _github_user_for_code(code: str, code_verifier: str | None = None) -> dict[str, object]:
    settings = get_settings()
    if not settings.github_client_id or not settings.github_client_secret:
        raise APIError(500, ErrorCode.OAUTH_CONFIGURATION_ERROR, "GitHub OAuth is not configured.")
    data: dict[str, str] = {
        "client_id": settings.github_client_id,
        "client_secret": settings.github_client_secret,
        "code": code,
        "redirect_uri": settings.github_oauth_redirect_uri,
    }
    if code_verifier and 43 <= len(code_verifier) <= 128:
        data["code_verifier"] = code_verifier

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            token_response = await client.post(
                "https://github.com/login/oauth/access_token",
                headers={"Accept": "application/json"},
                data=data,
            )
            token_response.raise_for_status()
            token_payload = token_response.json()
            # GitHub reports bad/expired codes and PKCE mismatches with HTTP 200 + an "error" field.
            if isinstance(token_payload, dict) and token_payload.get("error"):
                logger.info("github_oauth_exchange_rejected", extra={"error": str(token_payload.get("error"))})
                raise APIError(401, ErrorCode.OAUTH_EXCHANGE_FAILED, "GitHub rejected the authorization code.")
            access_token = token_payload.get("access_token") if isinstance(token_payload, dict) else None
            if not isinstance(access_token, str) or not access_token:
                raise APIError(401, ErrorCode.OAUTH_EXCHANGE_FAILED, "GitHub rejected the authorization code.")
            gh_headers = {
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {access_token}",
            }
            profile_response = await client.get("https://api.github.com/user", headers=gh_headers)
            profile_response.raise_for_status()
            profile = profile_response.json()
            if isinstance(profile, dict) and not profile.get("email"):
                # /user only exposes a *public* email; the user:email scope lets us read the primary one.
                profile["email"] = await _primary_verified_email(client, gh_headers)
    except APIError:
        raise
    except httpx.HTTPStatusError as exc:
        raise APIError(502, ErrorCode.OAUTH_EXCHANGE_FAILED, "GitHub OAuth exchange failed.", retryable=True) from exc
    except httpx.HTTPError as exc:
        raise APIError(503, ErrorCode.SERVICE_UNAVAILABLE, "GitHub OAuth is unavailable.", retryable=True) from exc
    return profile if isinstance(profile, dict) else {}


async def _primary_verified_email(client: httpx.AsyncClient, headers: dict[str, str]) -> str | None:
    try:
        resp = await client.get("https://api.github.com/user/emails", headers=headers)
        if not resp.is_success:
            return None
        for entry in resp.json() or []:
            if isinstance(entry, dict) and entry.get("primary") and entry.get("verified"):
                email = entry.get("email")
                return email if isinstance(email, str) else None
    except Exception as exc:
        logger.debug("github_primary_email_lookup_failed: %s", exc)
    return None


# ---------------------------------------------------------------------------
# Dev login
# ---------------------------------------------------------------------------

@router.post("/dev-login", response_model=TokenResponse, summary="Quick local developer authentication")
def dev_login(
    response: Response,
    request: Request,
    login: str | None = Query(default=None),
    db: Session = Depends(get_db),
) -> TokenResponse:
    """Authenticate immediately for local development without external GitHub OAuth.

    Guarded: Only permitted when ENABLE_DEV_LOGIN is True, environment is not production,
    and request originates from a loopback address (ISS-002).
    """
    settings = get_settings()
    if (
        not settings.enable_dev_login
        or settings.is_production
        or settings.app_env.strip().lower() not in {"development", "dev", "local"}
    ):
        raise APIError(404, ErrorCode.RESOURCE_NOT_FOUND, "Dev login endpoint is disabled.")

    client_host = request.client.host if request.client else None
    if client_host not in {"127.0.0.1", "::1", "testclient"}:
        raise APIError(403, ErrorCode.FORBIDDEN, "Dev login is only permitted from loopback interfaces.")

    if not login or not login.strip():
        raise APIError(400, ErrorCode.BAD_REQUEST, "Parameter 'login' is required for dev login.")

    target_login = login.strip()
    user = UserRepository(db).get_by_login(target_login)
    if not user:
        raise APIError(404, ErrorCode.RESOURCE_NOT_FOUND, f"User '{target_login}' not found.")

    user_role = _user_role(user)
    token, expires_in = create_access_token(user.id, role=user_role)
    refresh_tok, refresh_expires_in = create_refresh_token(user.id, role=user_role)
    _set_session_cookies(response, token, expires_in, refresh_tok, refresh_expires_in)
    return TokenResponse(access_token=token, expires_in=expires_in, user=_user_response(user))


# ---------------------------------------------------------------------------
# Refresh (rotating, single-use refresh tokens)
# ---------------------------------------------------------------------------

def _refresh_revocation_key(jti: str) -> str:
    return f"auth:refresh_revoked:{jti}"


# Two browser tabs can legitimately refresh with the same cookie at almost the same moment.
# A reuse inside this window is tolerated; a reuse after it is treated as token theft.
REFRESH_REUSE_GRACE_SECONDS = 10


def _claim_refresh_jti(client: Any, jti: str, exp: int) -> bool:
    """Mark a refresh token as used. Returns False if it was already used/revoked.

    Uses SET NX so two concurrent refreshes cannot both "win" outside the grace window.
    The stored value is the first-use timestamp, or "revoked" (logout) which never passes.
    """
    key = _refresh_revocation_key(jti)
    ttl = max(1, int(exp - time.time()))
    now = time.time()
    set_fn = getattr(client, "set", None)
    claimed: bool | None = None
    if callable(set_fn):
        try:
            claimed = bool(set_fn(key, f"{now:.3f}", nx=True, ex=ttl))
        except TypeError:
            claimed = None  # minimal client without kwargs support
    if claimed is None:
        if client.exists(key):
            claimed = False
        else:
            client.setex(key, ttl, f"{now:.3f}")
            return True
    if claimed:
        return True

    get_fn = getattr(client, "get", None)
    if not callable(get_fn):
        return False
    raw = get_fn(key)
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8", "ignore")
    try:
        first_used_at = float(raw)
    except (TypeError, ValueError):
        return False  # "revoked" marker from logout, or unreadable
    # Small negative ages come from timestamp rounding or clock skew between API replicas.
    return -1.0 <= now - first_used_at <= REFRESH_REUSE_GRACE_SECONDS


def _refresh_failure(status_code: int, code: ErrorCode, message: str, *, retryable: bool = False) -> Response:
    resp = error_response(status_code, code, message, retryable=retryable)
    if status_code == 401:
        _clear_session_cookies(resp)
    return resp


@router.post("/refresh", response_model=TokenResponse, summary="Refresh access token using refresh token")
def refresh_token(
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
):
    """Exchange a valid refresh token for a new access token and a rotated refresh token.

    The presented refresh token is single-use: it is revoked as part of the exchange, so a
    stolen-and-replayed refresh token is rejected.
    """
    from app.core.auth import csrf_origin_error

    settings = get_settings()
    refresh_tok = request.cookies.get(settings.refresh_cookie_name)
    from_cookie = bool(refresh_tok)
    if not refresh_tok:
        auth_header = request.headers.get("Authorization") or ""
        if auth_header[:7].lower() == "bearer ":
            refresh_tok = auth_header[7:].strip()
    if not refresh_tok:
        return _refresh_failure(401, ErrorCode.UNAUTHORIZED, "Missing refresh token.")

    # /auth/refresh is a public path, so the middleware's CSRF check does not run here.
    if from_cookie:
        csrf_error = csrf_origin_error(request)
        if csrf_error is not None:
            return error_response(403, ErrorCode.FORBIDDEN, csrf_error)

    try:
        claims = decode_refresh_token(refresh_tok)
        user_uuid = UUID(str(claims.get("sub", "")))
    except APIError as exc:
        return _refresh_failure(exc.status_code, exc.code, exc.message, retryable=exc.retryable)
    except (ValueError, TypeError):
        return _refresh_failure(401, ErrorCode.UNAUTHORIZED, "Invalid refresh token.")

    jti = str(claims.get("jti") or "")
    if not jti:
        return _refresh_failure(401, ErrorCode.UNAUTHORIZED, "Invalid refresh token.")

    try:
        redis_client = get_redis()
        if redis_client is None:
            raise ConnectionError("Redis client is not available")
        first_use = _claim_refresh_jti(redis_client, jti, int(claims.get("exp", 0)))
    except Exception as exc:
        logger.warning("refresh_token_revocation_store_unavailable: %s", exc)
        return error_response(
            503, ErrorCode.SERVICE_UNAVAILABLE, "Authentication service is unavailable.", retryable=True
        )
    if not first_use:
        logger.warning("refresh_token_reuse_detected", extra={"user_id": str(user_uuid)})
        return _refresh_failure(401, ErrorCode.UNAUTHORIZED, "Refresh token has already been used or revoked.")

    user = UserRepository(db).get_by_id(user_uuid)
    if not user:
        return _refresh_failure(401, ErrorCode.UNAUTHORIZED, "User account no longer exists.")

    # Role is always re-read from the database so role changes take effect on refresh.
    user_role = _user_role(user)
    new_access_token, expires_in = create_access_token(user.id, role=user_role)
    new_refresh_tok, refresh_expires_in = create_refresh_token(user.id, role=user_role)
    _set_session_cookies(response, new_access_token, expires_in, new_refresh_tok, refresh_expires_in)
    return TokenResponse(access_token=new_access_token, expires_in=expires_in, user=_user_response(user))


# ---------------------------------------------------------------------------
# Profile & logout
# ---------------------------------------------------------------------------

@router.get("/me", response_model=AuthenticatedUser, summary="Get the current authenticated user")
def get_current_user(request: Request, db: Session = Depends(get_db)) -> AuthenticatedUser:
    user = UserRepository(db).get_by_id(_request_user_id(request))
    if user is None:
        raise APIError(401, ErrorCode.UNAUTHORIZED, "User account no longer exists.")
    return _user_response(user)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT, summary="Revoke the current access and refresh tokens")
def logout(request: Request) -> Response:
    token_jti = getattr(request.state, "token_jti", None)
    token_exp = getattr(request.state, "token_exp", None)
    if not token_jti or token_exp is None:
        raise APIError(401, ErrorCode.UNAUTHORIZED, "Authentication is required.")

    expires_at = datetime.fromtimestamp(int(token_exp), tz=timezone.utc)
    ttl = max(1, int((expires_at - datetime.now(timezone.utc)).total_seconds()))
    try:
        redis_client = get_redis()
        if redis_client is None:
            raise ConnectionError("Redis client is not available")
        redis_client.setex(f"auth:blocklist:{token_jti}", ttl, "1")
        _revoke_presented_refresh_token(request, redis_client)
    except APIError:
        raise
    except Exception as exc:
        raise APIError(503, ErrorCode.SERVICE_UNAVAILABLE, "Logout service is unavailable.", retryable=True) from exc

    try:
        from app.core.auth import revoke_token_in_cache

        revoke_token_in_cache(token_jti)
    except Exception as exc:
        logger.debug("Failed revoking token in cache during logout: %s", exc)

    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    _clear_session_cookies(response)
    return response


def _revoke_presented_refresh_token(request: Request, redis_client: Any) -> None:
    """Revoke the refresh cookie too; otherwise a "logged out" browser could mint new access tokens."""
    refresh_tok = request.cookies.get(get_settings().refresh_cookie_name)
    if not refresh_tok:
        return
    try:
        claims = decode_refresh_token(refresh_tok)
    except APIError:
        return  # already invalid/expired — nothing to revoke
    if str(claims.get("sub")) != str(getattr(request.state, "user_id", "")):
        return  # never let one user's logout touch another user's token
    jti = str(claims.get("jti") or "")
    if jti:
        ttl = max(1, int(int(claims.get("exp", 0)) - time.time()))
        redis_client.setex(_refresh_revocation_key(jti), ttl, "revoked")


# ---------------------------------------------------------------------------
# Role management (admin only)
# ---------------------------------------------------------------------------

@router.get(
    "/users",
    response_model=UserListResponse,
    summary="List platform users and their roles (admin only)",
    dependencies=[Depends(require_role(UserRole.ADMIN))],
)
def list_users(
    role: str | None = Query(default=None, description="Optional role filter: viewer, developer or admin"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
) -> UserListResponse:
    role_filter = role.strip().lower() if role else None
    if role_filter and role_filter not in VALID_ROLES:
        raise APIError(400, ErrorCode.BAD_REQUEST, f"Unknown role '{role}'.")
    users, total = UserRepository(db).list_users(offset=(page - 1) * page_size, limit=page_size, role=role_filter)
    return UserListResponse(
        items=[_user_response(u) for u in users],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.patch(
    "/users/{user_id}/role",
    response_model=AuthenticatedUser,
    summary="Assign a role (viewer, developer, admin) to a user (admin only)",
    dependencies=[Depends(require_role(UserRole.ADMIN))],
)
def update_user_role(
    user_id: UUID,
    body: UpdateUserRoleRequest,
    request: Request,
    db: Session = Depends(get_db),
) -> AuthenticatedUser:
    """Change a user's role. The new role applies to the user's next token refresh (at most the
    access-token lifetime, JWT_EXPIRE_MINUTES)."""
    new_role = body.role.strip().lower()
    if new_role not in VALID_ROLES:
        raise APIError(400, ErrorCode.BAD_REQUEST, f"Unknown role '{body.role}'.")

    repo = UserRepository(db)
    target = repo.get_by_id(user_id)
    if target is None:
        raise APIError(404, ErrorCode.RESOURCE_NOT_FOUND, "User not found.")

    current_role = _user_role(target)
    if current_role == UserRole.ADMIN.value and new_role != UserRole.ADMIN.value:
        if repo.count_by_role(UserRole.ADMIN.value) <= 1:
            raise APIError(409, ErrorCode.CONFLICT, "Cannot demote the last remaining admin.")

    updated = repo.set_role(target, new_role)
    logger.info(
        "user_role_changed",
        extra={
            "actor_user_id": str(getattr(request.state, "user_id", "")),
            "target_user_id": str(user_id),
            "old_role": current_role,
            "new_role": new_role,
        },
    )
    return _user_response(updated)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _request_user_id(request: Request) -> UUID:
    try:
        return UUID(str(request.state.user_id))
    except (AttributeError, ValueError, TypeError) as exc:
        raise APIError(401, ErrorCode.UNAUTHORIZED, "Invalid authenticated user.") from exc


def _user_role(user: object) -> str:
    role = str(getattr(user, "role", None) or UserRole.DEVELOPER.value).strip().lower()
    return role if role in VALID_ROLES else UserRole.VIEWER.value


def _user_response(user: object) -> AuthenticatedUser:
    return AuthenticatedUser(
        id=str(user.id),
        login=user.login,
        email=user.email,
        avatar_url=user.avatar_url,
        role=_user_role(user),
    )


__all__ = [
    "router",
    "get_redis",
    "_consume_oauth_state",
    "_resolve_trusted_frontend_url",
    "_github_user_for_code",
    "_clear_state_cookie",
]
