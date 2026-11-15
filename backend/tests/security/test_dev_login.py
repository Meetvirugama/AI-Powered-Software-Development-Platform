"""Dev-login endpoint security tests (TST-02, ISS-002).

Validates:
- Endpoint is disabled (404) when enable_dev_login is False.
- Non-loopback client IPs receive 403 Forbidden.
- Missing login parameter returns 400 Bad Request.
- Non-existent user returns 404 (no fallback impersonation of first user).
- Valid loopback request for existing user returns 200, JWT token, and auth cookie.
"""

from uuid import uuid4
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.user import User


def test_dev_login_disabled_by_default(client: TestClient) -> None:
    """TST-02: Dev login must return 404 when enable_dev_login is False (default)."""
    settings = get_settings()
    original_flag = settings.enable_dev_login
    try:
        settings.enable_dev_login = False
        resp = client.post("/api/v1/auth/dev-login?login=anyuser")
        assert resp.status_code == 404
        assert resp.json()["error"]["code"] == "RESOURCE_NOT_FOUND"
    finally:
        settings.enable_dev_login = original_flag


def test_dev_login_rejects_non_loopback_client(client: TestClient, db_session: Session) -> None:
    """TST-02: Dev login must reject non-loopback IP addresses with 403 FORBIDDEN."""
    settings = get_settings()
    original_flag = settings.enable_dev_login
    original_env = settings.app_env
    try:
        settings.enable_dev_login = True
        settings.app_env = "development"

        # Construct TestClient with remote IP
        remote_client = TestClient(client.app, client=("198.51.100.25", 54321))
        resp = remote_client.post("/api/v1/auth/dev-login?login=testuser")
        assert resp.status_code == 403
        assert resp.json()["error"]["code"] == "FORBIDDEN"
        assert "loopback" in resp.json()["error"]["message"].lower()
    finally:
        settings.enable_dev_login = original_flag
        settings.app_env = original_env


def test_dev_login_requires_explicit_login_param(client: TestClient) -> None:
    """TST-02: Dev login must require explicit 'login' parameter (returns 400)."""
    settings = get_settings()
    original_flag = settings.enable_dev_login
    original_env = settings.app_env
    try:
        settings.enable_dev_login = True
        settings.app_env = "development"

        resp = client.post("/api/v1/auth/dev-login")
        assert resp.status_code == 400
        assert resp.json()["error"]["code"] == "BAD_REQUEST"
    finally:
        settings.enable_dev_login = original_flag
        settings.app_env = original_env


def test_dev_login_rejects_nonexistent_user_no_fallback(client: TestClient, db_session: Session) -> None:
    """TST-02: Dev login must NOT fall back to first user when given unknown login; returns 404."""
    # Seed an existing user in DB
    existing_user = User(
        id=uuid4(),
        github_id="9990001",
        login="legit-admin",
        email="admin@example.com",
        role="admin",
    )
    db_session.add(existing_user)
    db_session.commit()

    settings = get_settings()
    original_flag = settings.enable_dev_login
    original_env = settings.app_env
    try:
        settings.enable_dev_login = True
        settings.app_env = "development"

        # Request a non-existent login
        resp = client.post("/api/v1/auth/dev-login?login=ghost-user")
        assert resp.status_code == 404
        assert resp.json()["error"]["code"] == "RESOURCE_NOT_FOUND"
        assert "not found" in resp.json()["error"]["message"].lower()
    finally:
        settings.enable_dev_login = original_flag
        settings.app_env = original_env


def test_dev_login_happy_path_on_loopback(client: TestClient, db_session: Session) -> None:
    """TST-02: Dev login succeeds for valid user on loopback when enabled."""
    user = User(
        id=uuid4(),
        github_id="9990002",
        login="local-dev-user",
        email="dev@example.local",
        role="developer",
    )
    db_session.add(user)
    db_session.commit()

    settings = get_settings()
    original_flag = settings.enable_dev_login
    original_env = settings.app_env
    try:
        settings.enable_dev_login = True
        settings.app_env = "development"

        resp = client.post("/api/v1/auth/dev-login?login=local-dev-user")
        assert resp.status_code == 200
        data = resp.json()
        assert "access_token" in data
        assert data["user"]["login"] == "local-dev-user"
        assert settings.auth_cookie_name in resp.cookies
    finally:
        settings.enable_dev_login = original_flag
        settings.app_env = original_env
