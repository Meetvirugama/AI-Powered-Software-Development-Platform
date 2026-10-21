"""Tests for authentication and standardized API error formatting."""

from __future__ import annotations

import uuid
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.core.security import create_access_token


def test_unauthenticated_returns_401(client: TestClient) -> None:
    """Verify that calling any protected endpoint without an auth token returns 401 UNAUTHORIZED."""
    response = client.get("/api/v1/repositories")

    assert response.status_code == 401
    data = response.json()
    assert "error" in data
    assert data["error"]["code"] == "UNAUTHORIZED"
    assert "Authentication is required." in data["error"]["message"]


def test_health_returns_200(client: TestClient) -> None:
    """Verify that the health check endpoint returns 200 and expected service status."""
    response = client.get("/health")

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert "version" in data
    assert data["version"] == "1.0.0"

    # Also verify versioned health route
    v1_response = client.get("/api/v1/health")
    assert v1_response.status_code == 200
    assert v1_response.json()["status"] == "ok"


def test_error_format_is_standard(client: TestClient, auth_headers: dict[str, str]) -> None:
    """Trigger a 404 and verify the error envelope matches the standard contract: error.code and error.message."""
    response = client.get("/api/v1/nonexistent-route-for-testing-404", headers=auth_headers)

    assert response.status_code == 404
    data = response.json()
    assert "error" in data
    assert "code" in data["error"]
    assert "message" in data["error"]
    assert "retryable" in data["error"]
    assert data["error"]["code"] == "NOT_FOUND"
    assert isinstance(data["error"]["message"], str)


def test_invalid_token_returns_401(client: TestClient, monkeypatch) -> None:
    """Verify that malformed or invalid JWT tokens are rejected with 401."""
    monkeypatch.setenv("JWT_SECRET", "test-secret")
    get_settings.cache_clear()

    response = client.get(
        "/api/v1/repositories",
        headers={"Authorization": "Bearer invalid.jwt.token"},
    )

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "UNAUTHORIZED"


def test_revoked_token_returns_401(client: TestClient, fake_redis, monkeypatch) -> None:
    """Verify that revoked tokens blocklisted in Redis return 401."""
    monkeypatch.setenv("JWT_SECRET", "test-secret")
    get_settings.cache_clear()

    token, _ = create_access_token(user_id=str(uuid.uuid4()))
    from app.core.security import decode_access_token

    claims = decode_access_token(token)
    jti = str(claims["jti"])
    fake_redis.blocklisted.add(f"auth:blocklist:{jti}")

    response = client.get(
        "/api/v1/repositories",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "UNAUTHORIZED"
    assert "revoked" in response.json()["error"]["message"]
