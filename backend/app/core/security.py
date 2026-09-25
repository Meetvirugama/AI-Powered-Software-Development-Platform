"""JWT creation and validation for browser and API clients."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

from jose import JWTError, jwt

from app.core.config import get_settings
from app.core.errors import APIError, ErrorCode


def create_access_token(user_id: str) -> tuple[str, int]:
    """Create a short-lived JWT and return it with its remaining lifetime in seconds."""
    settings = get_settings()
    if not settings.jwt_secret:
        raise APIError(500, ErrorCode.OAUTH_CONFIGURATION_ERROR, "JWT signing is not configured.")

    expires_at = datetime.now(timezone.utc) + timedelta(minutes=settings.jwt_expire_minutes)
    token = jwt.encode(
        {"sub": user_id, "jti": str(uuid4()), "exp": expires_at, "iat": datetime.now(timezone.utc)},
        settings.jwt_secret,
        algorithm=settings.jwt_algorithm,
    )
    return token, int(timedelta(minutes=settings.jwt_expire_minutes).total_seconds())


def decode_access_token(token: str) -> dict[str, object]:
    """Verify the expected algorithm, signature, and required subject claims."""
    settings = get_settings()
    if not settings.jwt_secret:
        raise APIError(500, ErrorCode.OAUTH_CONFIGURATION_ERROR, "JWT signing is not configured.")
    try:
        claims = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    except JWTError as exc:
        raise APIError(401, ErrorCode.UNAUTHORIZED, "Invalid or expired access token.") from exc
    if not claims.get("sub") or not claims.get("jti"):
        raise APIError(401, ErrorCode.UNAUTHORIZED, "Invalid access token.")
    return claims
