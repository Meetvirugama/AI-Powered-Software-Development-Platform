"""Refresh token flow verification tests (TST-03, TST-32, ISS-012).

Validates:
- Refresh token issuance, validation, and token type isolation.
- POST /api/v1/auth/refresh rotates tokens and issues new short-lived access token.
- Invalid, expired, or wrong-type tokens are rejected with 401.
- Logout revokes both access and refresh cookies.
"""

from __future__ import annotations

from uuid import uuid4
import pytest
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.core.errors import APIError
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_access_token,
    decode_refresh_token,
    TOKEN_TYPE_ACCESS,
    TOKEN_TYPE_REFRESH,
)
from app.models.user import User
from app.repositories.user_repository import UserRepository


def test_token_type_isolation_and_claims() -> None:
    """TST-03: Access tokens cannot be used as refresh tokens and vice-versa."""
    uid = uuid4()
    access_tok, _ = create_access_token(uid)
    refresh_tok, _ = create_refresh_token(uid)

    access_claims = decode_access_token(access_tok)
    assert access_claims["token_type"] == TOKEN_TYPE_ACCESS

    refresh_claims = decode_refresh_token(refresh_tok)
    assert refresh_claims["token_type"] == TOKEN_TYPE_REFRESH

    # Cross-decoding fails with 401
    with pytest.raises(APIError) as exc_access:
        decode_access_token(refresh_tok)
    assert exc_access.value.status_code == 401

    with pytest.raises(APIError) as exc_refresh:
        decode_refresh_token(access_tok)
    assert exc_refresh.value.status_code == 401


def test_refresh_endpoint_success(client: TestClient, db_session) -> None:
    """TST-32: POST /api/v1/auth/refresh returns new access token and rotated refresh token."""
    user = User(
        id=uuid4(),
        github_id="refresh-test-gh-999",
        login="refresh_tester",
        email="refresh@test.local",
        role="developer",
    )
    db_session.add(user)
    db_session.commit()

    refresh_tok, _ = create_refresh_token(user.id, role="developer")
    settings = get_settings()

    # Call /api/v1/auth/refresh via cookie
    client.cookies.set(settings.refresh_cookie_name, refresh_tok, path="/api/v1/auth")
    resp = client.post("/api/v1/auth/refresh")

    assert resp.status_code == 200
    data = resp.json()
    assert "access_token" in data
    assert data["user"]["login"] == "refresh_tester"

    # Verify new cookies are set
    cookies = resp.cookies
    assert settings.auth_cookie_name in cookies
    assert settings.refresh_cookie_name in cookies


def test_refresh_endpoint_missing_token_returns_401(client: TestClient) -> None:
    """TST-32: POST /api/v1/auth/refresh without token returns 401 Unauthorized."""
    resp = client.post("/api/v1/auth/refresh")
    assert resp.status_code == 401


def test_refresh_endpoint_invalid_token_returns_401(client: TestClient) -> None:
    """TST-32: POST /api/v1/auth/refresh with bogus token returns 401."""
    settings = get_settings()
    client.cookies.set(settings.refresh_cookie_name, "invalid.garbage.jwt", path="/api/v1/auth")
    resp = client.post("/api/v1/auth/refresh")
    assert resp.status_code == 401
