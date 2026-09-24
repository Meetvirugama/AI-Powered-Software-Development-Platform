"""Focused contract tests for Yug's Day 2 and Day 3 API endpoints."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.core.database import get_db
from app.core.security import create_access_token
from app.main import app


class FakeRedis:
    def __init__(self) -> None:
        self.blocklisted: set[str] = set()

    def exists(self, key: str) -> int:
        return int(key in self.blocklisted)

    def setex(self, key: str, _: int, __: str) -> None:
        self.blocklisted.add(key)

    def rpush(self, *_: object) -> int:
        return 1


def _configure_auth(monkeypatch) -> FakeRedis:
    monkeypatch.setenv("JWT_SECRET", "test-secret")
    get_settings.cache_clear()
    fake_redis = FakeRedis()
    monkeypatch.setattr("app.core.auth.get_redis", lambda: fake_redis)
    monkeypatch.setattr("app.api.v1.auth.get_redis", lambda: fake_redis)
    monkeypatch.setattr("app.api.v1.repositories.get_redis", lambda: fake_redis)
    return fake_redis


def test_non_auth_routes_require_a_jwt(monkeypatch) -> None:
    _configure_auth(monkeypatch)
    client = TestClient(app, raise_server_exceptions=False)

    response = client.get("/api/v1/repositories")

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "UNAUTHORIZED"


def test_github_login_redirects_with_a_csrf_state(monkeypatch) -> None:
    monkeypatch.setenv("GITHUB_CLIENT_ID", "github-client")
    get_settings.cache_clear()
    client = TestClient(app, raise_server_exceptions=False)

    response = client.get("/api/v1/auth/github/login", follow_redirects=False)

    assert response.status_code == 307
    assert "state=" in response.headers["location"]
    assert "oauth_state=" in response.headers["set-cookie"]


def test_logout_blocklists_current_token(monkeypatch) -> None:
    _configure_auth(monkeypatch)
    token, _ = create_access_token("0e969876-16d2-4c9f-8fe1-a849f32fa605")
    client = TestClient(app, raise_server_exceptions=False)

    response = client.post("/api/v1/auth/logout", headers={"Authorization": f"Bearer {token}"})
    retry = client.post("/api/v1/auth/logout", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 204
    assert retry.status_code == 401
    assert retry.json()["error"]["code"] == "UNAUTHORIZED"


def test_list_repositories_is_scoped_to_authenticated_user(monkeypatch) -> None:
    _configure_auth(monkeypatch)
    token, _ = create_access_token("0e969876-16d2-4c9f-8fe1-a849f32fa605")

    class FakeRepositoryRepository:
        def __init__(self, session: object) -> None:
            self.session = session

        def list_by_user(self, user_id: object) -> list[object]:
            assert str(user_id) == "0e969876-16d2-4c9f-8fe1-a849f32fa605"
            return []

    monkeypatch.setattr("app.api.v1.repositories.RepositoryRepository", FakeRepositoryRepository)
    app.dependency_overrides[get_db] = lambda: object()
    try:
        client = TestClient(app, raise_server_exceptions=False)
        response = client.get("/api/v1/repositories", headers={"Authorization": f"Bearer {token}"})
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json() == []
