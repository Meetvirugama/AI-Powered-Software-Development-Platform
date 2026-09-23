"""GitHub OAuth, JWT session, and logout endpoints."""

from __future__ import annotations

import secrets
from datetime import datetime, timezone
from uuid import UUID

import httpx
from fastapi import APIRouter, Depends, Query, Request, Response, status
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.database import get_db
from app.core.errors import APIError, ErrorCode
from app.core.redis import get_redis
from app.core.security import create_access_token
from app.repositories.user_repository import UserRepository
from app.schemas.auth import AuthenticatedUser, TokenResponse

router = APIRouter(prefix="/auth", tags=["authentication"])


@router.get("/github/login", summary="Start GitHub OAuth login")
def github_login() -> RedirectResponse:
    """Generate a CSRF state token and redirect the browser to GitHub."""
    settings = get_settings()
    if not settings.github_client_id:
        raise APIError(500, ErrorCode.OAUTH_CONFIGURATION_ERROR, "GitHub OAuth is not configured.")
    state = secrets.token_urlsafe(32)
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
            }
        )
    )
    redirect.set_cookie(
        "oauth_state",
        state,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        max_age=600,
        path="/api/v1/auth/github",
    )
    return redirect


@router.get("/github/callback", response_model=TokenResponse, summary="Complete GitHub OAuth login")
async def github_callback(
    response: Response,
    request: Request,
    code: str = Query(min_length=1),
    state: str = Query(min_length=1),
    db: Session = Depends(get_db),
) -> TokenResponse:
    """Exchange GitHub's code, upsert the user, then issue a short-lived JWT."""
    expected_state = request.cookies.get("oauth_state")
    if not expected_state or not secrets.compare_digest(state, expected_state):
        raise APIError(400, ErrorCode.OAUTH_STATE_INVALID, "OAuth state is invalid or has expired.")

    github_user = await _github_user_for_code(code)
    github_id = github_user.get("id")
    login = github_user.get("login")
    if github_id is None or not isinstance(login, str) or not login:
        raise APIError(502, ErrorCode.GITHUB_PROFILE_FAILED, "GitHub returned an incomplete user profile.", retryable=True)

    user = UserRepository(db).upsert_github_user(
        str(github_id),
        login,
        github_user.get("email") if isinstance(github_user.get("email"), str) else None,
        github_user.get("avatar_url") if isinstance(github_user.get("avatar_url"), str) else None,
    )
    token, expires_in = create_access_token(str(user.id))
    response.set_cookie(
        get_settings().auth_cookie_name,
        token,
        httponly=True,
        secure=get_settings().cookie_secure,
        samesite="lax",
        max_age=expires_in,
        path="/",
    )
    response.delete_cookie("oauth_state", path="/api/v1/auth/github")
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
        get_redis().setex(f"auth:blocklist:{request.state.token_jti}", ttl, "1")
    except Exception as exc:
        raise APIError(503, ErrorCode.SERVICE_UNAVAILABLE, "Logout service is unavailable.", retryable=True) from exc
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    response.delete_cookie(get_settings().auth_cookie_name, path="/")
    return response


async def _github_user_for_code(code: str) -> dict[str, object]:
    settings = get_settings()
    if not settings.github_client_id or not settings.github_client_secret:
        raise APIError(500, ErrorCode.OAUTH_CONFIGURATION_ERROR, "GitHub OAuth is not configured.")
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            token_response = await client.post(
                "https://github.com/login/oauth/access_token",
                headers={"Accept": "application/json"},
                data={
                    "client_id": settings.github_client_id,
                    "client_secret": settings.github_client_secret,
                    "code": code,
                    "redirect_uri": settings.github_oauth_redirect_uri,
                },
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
