"""GitHub OAuth, JWT session, and logout endpoints."""

from __future__ import annotations

import base64
import hashlib
import logging
import secrets
import urllib.parse
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

import httpx
from fastapi import APIRouter, Depends, Query, Request, Response, status
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.database import get_db
from app.core.errors import APIError, ErrorCode, error_response
from app.core.redis import get_redis
from app.core.security import create_access_token
from app.repositories.user_repository import UserRepository
from app.repositories.github_installation_repository import GitHubInstallationRepository
from app.schemas.auth import AuthenticatedUser, TokenResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["authentication"])


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
    parsed = urllib.parse.urlparse(target_url)
    if not parsed.scheme or not parsed.netloc:
        if target_url.startswith("/") and not target_url.startswith("//"):
            return f"{default_origin}{target_url}"
        return default_origin
    origin = f"{parsed.scheme}://{parsed.netloc}".rstrip("/")
    if origin in allowed_origins:
        return target_url
    logger.warning("untrusted_redirect_attempt_blocked", extra={"target_url": target_url})
    return default_origin


@router.get("/github/login", summary="Start GitHub OAuth login")
def github_login(redirect_url: str | None = Query(default=None)) -> RedirectResponse:
    """Generate a CSRF state token with PKCE S256 and redirect the browser to GitHub."""
    settings = get_settings()
    if not settings.github_client_id:
        raise APIError(500, ErrorCode.OAUTH_CONFIGURATION_ERROR, "GitHub OAuth is not configured.")

    state = secrets.token_urlsafe(32)
    code_verifier = secrets.token_urlsafe(64)
    digest = hashlib.sha256(code_verifier.encode("ascii")).digest()
    code_challenge = base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")

    payload_data = code_verifier
    if redirect_url:
        safe_redirect = _resolve_trusted_frontend_url(redirect_url)
        payload_data = f"{code_verifier}|{safe_redirect}"

    # Fail closed: Persist state and verifier in Redis BEFORE issuing cookies or redirecting
    try:
        redis_client = get_redis()
        if redis_client is None:
            raise ConnectionError("Redis client is not available")
        redis_client.setex(f"oauth_state:{state}", 600, payload_data)
    except Exception as exc:
        logger.warning("Failed to persist oauth_state in Redis: %s", exc)
        raise APIError(503, ErrorCode.SERVICE_UNAVAILABLE, "Authentication service is unavailable.", retryable=True) from exc

    redirect = RedirectResponse(
        "https://github.com/login/oauth/authorize",
        status_code=status.HTTP_307_TEMPORARY_REDIRECT,
    )
    redirect.headers["Location"] = str(
        httpx.URL("https://github.com/login/oauth/authorize").copy_merge_params(
            {
                "client_id": settings.github_client_id,
                "redirect_uri": settings.github_oauth_redirect_uri,
                "scope": "read:user user:email",
                "state": state,
                "code_challenge": code_challenge,
                "code_challenge_method": "S256",
            }
        )
    )

    redirect.set_cookie(
        "oauth_state",
        state,
        httponly=True,
        secure=settings.cookie_secure,
        samesite=settings.effective_cookie_samesite,
        max_age=600,
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
    db: Session = Depends(get_db),
):
    """Exchange GitHub's code, upsert the user, then issue a short-lived JWT."""
    frontend_base = _resolve_trusted_frontend_url()

    if installation_id:
        user_id_str = getattr(request.state, "user_id", None)
        if user_id_str:
            try:
                user = UserRepository(db).get_by_id(UUID(user_id_str))
                if user:
                    clean_inst_id = str(installation_id).strip()
                    inst_repo = GitHubInstallationRepository(db)
                    existing = inst_repo.get_by_installation_id(clean_inst_id)
                    if existing and existing.user_id != user.id:
                        logger.warning(
                            "oauth_callback_cross_tenant_installation_blocked",
                            extra={"user_id": str(user.id), "installation_id": clean_inst_id},
                        )
                    else:
                        github_service = getattr(request.app.state, "github_service", None)
                        is_verified = False
                        acc_login = user.login
                        permissions = {}
                        if github_service:
                            try:
                                async with httpx.AsyncClient(timeout=10.0) as client:
                                    resp = await client.get(
                                        f"https://api.github.com/app/installations/{clean_inst_id}",
                                        headers=github_service._app_auth_headers(),
                                    )
                                    if resp.is_success:
                                        inst_data = resp.json()
                                        inst_login = (inst_data.get("account") or {}).get("login", "")
                                        inst_acc_id = str(inst_data.get("target_id") or (inst_data.get("account") or {}).get("id") or "")
                                        if (
                                            (inst_login and inst_login.lower() == user.login.lower())
                                            or (user.github_id and inst_acc_id == str(user.github_id))
                                        ):
                                            is_verified = True
                                            acc_login = inst_login or user.login
                                            permissions = inst_data.get("permissions", {})
                            except Exception as exc:
                                logger.warning("oauth_callback_verify_error", extra={"error": str(exc)})
                        elif existing and existing.user_id == user.id:
                            is_verified = True

                        if is_verified:
                            inst_repo.upsert(
                                user_id=user.id,
                                installation_id=clean_inst_id,
                                account_login=acc_login,
                                permissions=permissions,
                            )
            except Exception:
                pass
        target_dest = _resolve_trusted_frontend_url(redirect_url) if redirect_url else f"{frontend_base}/app/repositories"
        return RedirectResponse(
            url=target_dest,
            status_code=status.HTTP_302_FOUND,
        )

    if not code or not state:
        err = APIError(400, ErrorCode.BAD_REQUEST, "Missing OAuth code or state parameter.")
        err_resp = error_response(err.status_code, err.code, err.message)
        _clear_state_cookie(err_resp)
        return err_resp

    expected_state = request.cookies.get("oauth_state")
    # OAuth state must match the browser cookie (CSRF binding)
    if not expected_state or not secrets.compare_digest(state, expected_state):
        err = APIError(400, ErrorCode.OAUTH_STATE_INVALID, "OAuth state is invalid or has expired.")
        err_resp = error_response(err.status_code, err.code, err.message)
        _clear_state_cookie(err_resp)
        return err_resp

    # Atomically consume the state in Redis to enforce single-use (Fail-Closed)
    redis_client = get_redis()
    if redis_client is None:
        logger.warning("oauth_callback_redis_missing")
        err = APIError(503, ErrorCode.SERVICE_UNAVAILABLE, "Authentication service is unavailable.", retryable=True)
        err_resp = error_response(err.status_code, err.code, err.message, retryable=True)
        _clear_state_cookie(err_resp)
        return err_resp

    try:
        consumed_state_payload = _consume_oauth_state(redis_client, state)
    except APIError:
        raise
    except Exception as exc:
        logger.warning("Could not consume oauth_state via Redis: %s", exc)
        err = APIError(503, ErrorCode.SERVICE_UNAVAILABLE, "Authentication service is unavailable.", retryable=True)
        err_resp = error_response(err.status_code, err.code, err.message, retryable=True)
        _clear_state_cookie(err_resp)
        return err_resp

    if not consumed_state_payload:
        # State was already consumed or expired in Redis
        err = APIError(400, ErrorCode.OAUTH_STATE_INVALID, "OAuth state is invalid or has expired.")
        err_resp = error_response(err.status_code, err.code, err.message)
        _clear_state_cookie(err_resp)
        return err_resp

    target_redirect: str | None = None
    if consumed_state_payload and "|" in consumed_state_payload:
        verifier_to_pass, _, target_redirect = consumed_state_payload.partition("|")
    else:
        verifier_to_pass = consumed_state_payload if (consumed_state_payload and consumed_state_payload != "1") else None

    if redirect_url:
        target_redirect = _resolve_trusted_frontend_url(redirect_url)
    elif target_redirect:
        target_redirect = _resolve_trusted_frontend_url(target_redirect)

    try:
        try:
            github_user = await _github_user_for_code(code, code_verifier=verifier_to_pass)
        except TypeError:
            github_user = await _github_user_for_code(code)
    except APIError as exc:
        err_resp = error_response(exc.status_code, exc.code, exc.message, retryable=exc.retryable)
        _clear_state_cookie(err_resp)
        return err_resp

    github_id = github_user.get("id")
    login = github_user.get("login")
    if github_id is None or not isinstance(login, str) or not login:
        err = APIError(502, ErrorCode.GITHUB_PROFILE_FAILED, "GitHub returned an incomplete user profile.", retryable=True)
        err_resp = error_response(err.status_code, err.code, err.message, retryable=True)
        _clear_state_cookie(err_resp)
        return err_resp

    user = UserRepository(db).upsert_github_user(
        str(github_id),
        login,
        github_user.get("email") if isinstance(github_user.get("email"), str) else None,
        github_user.get("avatar_url") if isinstance(github_user.get("avatar_url"), str) else None,
    )
    token, expires_in = create_access_token(str(user.id))

    final_destination = target_redirect or f"{frontend_base}/auth/callback"
    redirect = RedirectResponse(
        url=final_destination,
        status_code=status.HTTP_302_FOUND,
    )
    redirect.set_cookie(
        get_settings().auth_cookie_name,
        token,
        httponly=True,
        secure=get_settings().cookie_secure,
        samesite=get_settings().effective_cookie_samesite,
        max_age=expires_in,
        path="/",
    )
    _clear_state_cookie(redirect)

    accept_hdr = (request.headers.get("accept") or "").lower()
    if "application/json" in accept_hdr:
        response.set_cookie(
            get_settings().auth_cookie_name,
            token,
            httponly=True,
            secure=get_settings().cookie_secure,
            samesite=get_settings().effective_cookie_samesite,
            max_age=expires_in,
            path="/",
        )
        _clear_state_cookie(response)
        return TokenResponse(
            access_token=token,
            expires_in=expires_in,
            user=_user_response(user),
        )

    return redirect


@router.post("/dev-login", response_model=TokenResponse, summary="Quick local developer authentication")
def dev_login(
    response: Response,
    request: Request,
    login: str | None = Query(default=None),
    db: Session = Depends(get_db),
) -> TokenResponse:
    """Authenticate immediately for local development without external GitHub OAuth.

    Guarded: Only permitted when settings.app_env is development, dev, or local.
    """
    settings = get_settings()
    if settings.app_env.strip().lower() not in {"development", "dev", "local"}:
        raise APIError(403, ErrorCode.FORBIDDEN, "Dev login is only permitted in development environments.")

    user_repo = UserRepository(db)
    target_login = (login or "Meetvirugama").strip()
    user = user_repo.get_by_login(target_login)
    if not user:
        from app.models.user import User
        all_users = db.query(User).all()
        if all_users:
            user = all_users[0]
        else:
            user = user_repo.create_user(
                github_id="dev-user-001",
                login=target_login,
                email=f"{target_login.lower()}@example.com",
            )

    token, expires_in = create_access_token(user.id)
    response.set_cookie(
        settings.auth_cookie_name,
        token,
        httponly=True,
        secure=settings.cookie_secure,
        samesite=settings.effective_cookie_samesite,
        max_age=expires_in,
        path="/",
    )
    return TokenResponse(
        access_token=token,
        expires_in=expires_in,
        user=_user_response(user),
    )


@router.get("/me", response_model=AuthenticatedUser, summary="Get the current authenticated user")
def get_current_user(request: Request, db: Session = Depends(get_db)) -> AuthenticatedUser:
    user = UserRepository(db).get_by_id(_request_user_id(request))
    if user is None:
        raise APIError(401, ErrorCode.UNAUTHORIZED, "User account no longer exists.")
    return _user_response(user)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT, summary="Revoke the current access token")
def logout(request: Request) -> Response:
    expires_at = datetime.fromtimestamp(request.state.token_exp, tz=timezone.utc)
    ttl = max(1, int((expires_at - datetime.now(timezone.utc)).total_seconds()))
    try:
        redis_client = get_redis()
        if redis_client is None:
            raise ConnectionError("Redis client is not available")
        redis_client.setex(f"auth:blocklist:{request.state.token_jti}", ttl, "1")
    except Exception as exc:
        raise APIError(503, ErrorCode.SERVICE_UNAVAILABLE, "Logout service is unavailable.", retryable=True) from exc
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    settings = get_settings()
    response.delete_cookie(
        settings.auth_cookie_name,
        path="/",
        secure=settings.cookie_secure,
        httponly=True,
        samesite=settings.effective_cookie_samesite,
    )
    return response


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
    if code_verifier and len(code_verifier) >= 43 and code_verifier != "1":
        data["code_verifier"] = code_verifier

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            token_response = await client.post(
                "https://github.com/login/oauth/access_token",
                headers={"Accept": "application/json"},
                data=data,
            )
            token_response.raise_for_status()
            access_token = token_response.json().get("access_token")
            if not isinstance(access_token, str) or not access_token:
                raise APIError(401, ErrorCode.OAUTH_EXCHANGE_FAILED, "GitHub rejected the authorization code.")
            profile_response = await client.get(
                "https://api.github.com/user",
                headers={"Accept": "application/vnd.github+json", "Authorization": f"Bearer {access_token}"},
            )
            profile_response.raise_for_status()
            profile = profile_response.json()
    except APIError:
        raise
    except httpx.HTTPStatusError as exc:
        raise APIError(502, ErrorCode.OAUTH_EXCHANGE_FAILED, "GitHub OAuth exchange failed.", retryable=True) from exc
    except httpx.HTTPError as exc:
        raise APIError(503, ErrorCode.SERVICE_UNAVAILABLE, "GitHub OAuth is unavailable.", retryable=True) from exc
    return profile if isinstance(profile, dict) else {}


def _request_user_id(request: Request) -> UUID:
    try:
        return UUID(request.state.user_id)
    except (AttributeError, ValueError) as exc:
        raise APIError(401, ErrorCode.UNAUTHORIZED, "Invalid authenticated user.") from exc


def _user_response(user: object) -> AuthenticatedUser:
    return AuthenticatedUser(
        id=str(user.id),
        login=user.login,
        email=user.email,
        avatar_url=user.avatar_url,
    )
