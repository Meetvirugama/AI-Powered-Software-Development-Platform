"""JWT creation and validation for browser and API clients."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID, uuid4

import jwt
from jwt.exceptions import ExpiredSignatureError, InvalidTokenError, PyJWTError

from app.core.config import get_settings
from app.core.errors import APIError, ErrorCode

logger = logging.getLogger(__name__)

# Explicit algorithm allowlist for platform symmetric tokens
ALLOWED_PLATFORM_ALGORITHMS = frozenset({"HS256", "HS384", "HS512"})
TOKEN_TYPE_ACCESS = "access"


def create_access_token(
    user_id: str | UUID,
    role: str = "developer",
    permissions: list[str] | None = None,
) -> tuple[str, int]:
    """Create a short-lived JWT and return it with its remaining lifetime in seconds."""
    settings = get_settings()
    if not settings.jwt_secret or not settings.jwt_issuer or not settings.jwt_audience:
        raise APIError(500, ErrorCode.OAUTH_CONFIGURATION_ERROR, "JWT signing is not properly configured.")

    if settings.jwt_expire_minutes <= 0:
        raise APIError(500, ErrorCode.OAUTH_CONFIGURATION_ERROR, "Invalid token expiration configuration.")

    sub_str = str(user_id).strip()
    if not sub_str:
        raise APIError(400, ErrorCode.BAD_REQUEST, "Invalid user identifier for token generation.")

    algorithm = settings.jwt_algorithm
    if algorithm not in ALLOWED_PLATFORM_ALGORITHMS:
        raise APIError(500, ErrorCode.OAUTH_CONFIGURATION_ERROR, f"Unsupported JWT algorithm: {algorithm}")

    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(minutes=settings.jwt_expire_minutes)

    payload: dict[str, Any] = {
        "sub": sub_str,
        "jti": str(uuid4()),
        "iss": settings.jwt_issuer,
        "aud": settings.jwt_audience,
        "token_type": TOKEN_TYPE_ACCESS,
        "type": TOKEN_TYPE_ACCESS,
        "role": str(role or "developer").lower(),
        "permissions": list(permissions or []),
        "iat": int(now.timestamp()),
        "exp": int(expires_at.timestamp()),
    }

    token = jwt.encode(
        payload,
        settings.jwt_secret,
        algorithm=algorithm,
    )
    token_str = token.decode("utf-8") if isinstance(token, bytes) else str(token)
    return token_str, int(timedelta(minutes=settings.jwt_expire_minutes).total_seconds())


def decode_access_token(token: str) -> dict[str, object]:
    """Verify algorithm allowlist, signature, issuer, audience, and mandatory claims using PyJWT."""
    settings = get_settings()
    if not settings.jwt_secret or not settings.jwt_issuer or not settings.jwt_audience:
        raise APIError(500, ErrorCode.OAUTH_CONFIGURATION_ERROR, "JWT signing is not properly configured.")

    if not token or not isinstance(token, str) or not token.strip():
        raise APIError(401, ErrorCode.UNAUTHORIZED, "Invalid access token.")

    algorithm = settings.jwt_algorithm
    if algorithm not in ALLOWED_PLATFORM_ALGORITHMS:
        raise APIError(500, ErrorCode.OAUTH_CONFIGURATION_ERROR, f"Unsupported JWT algorithm: {algorithm}")

    try:
        claims = jwt.decode(
            token.strip(),
            settings.jwt_secret,
            algorithms=[algorithm],
            issuer=settings.jwt_issuer,
            audience=settings.jwt_audience,
            options={
                "require": ["sub", "jti", "exp", "iat", "iss", "aud"],
                "verify_exp": True,
                "verify_iat": True,
                "verify_iss": True,
                "verify_aud": True,
                "verify_signature": True,
            },
        )
    except ExpiredSignatureError as exc:
        logger.info("access_token_expired", extra={"error": str(exc)})
        raise APIError(401, ErrorCode.UNAUTHORIZED, "Invalid or expired access token.") from exc
    except InvalidTokenError as exc:
        logger.info("access_token_invalid", extra={"error": str(exc)})
        raise APIError(401, ErrorCode.UNAUTHORIZED, "Invalid access token.") from exc
    except PyJWTError as exc:
        logger.info("jwt_error", extra={"error": str(exc)})
        raise APIError(401, ErrorCode.UNAUTHORIZED, "Invalid access token.") from exc
    except Exception as exc:
        logger.warning("unexpected_jwt_decode_error", extra={"error": str(exc)})
        raise APIError(401, ErrorCode.UNAUTHORIZED, "Invalid access token.") from exc

    # Additional strict claim validation
    token_type = claims.get("token_type") or claims.get("type")
    if token_type != TOKEN_TYPE_ACCESS:
        logger.info("token_type_mismatch", extra={"token_type": str(token_type)})
        raise APIError(401, ErrorCode.UNAUTHORIZED, "Invalid access token.")

    sub = claims.get("sub")
    if isinstance(sub, bool) or not isinstance(sub, str) or not sub.strip():
        raise APIError(401, ErrorCode.UNAUTHORIZED, "Invalid access token.")

    jti = claims.get("jti")
    if isinstance(jti, bool) or not isinstance(jti, str) or not jti.strip():
        raise APIError(401, ErrorCode.UNAUTHORIZED, "Invalid access token.")

    exp = claims.get("exp")
    iat = claims.get("iat")
    if (
        isinstance(exp, bool)
        or isinstance(iat, bool)
        or not isinstance(exp, (int, float))
        or not isinstance(iat, (int, float))
    ):
        raise APIError(401, ErrorCode.UNAUTHORIZED, "Invalid access token.")
    if exp <= iat:
        raise APIError(401, ErrorCode.UNAUTHORIZED, "Invalid access token.")

    return claims
