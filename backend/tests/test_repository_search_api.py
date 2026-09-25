"""Contract tests for Yug's Day 5 repository hybrid-search endpoint."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.core.database import get_db
from app.core.security import create_access_token
from app.main import app


class FakeRedis:
    def exists(self, _: str) -> int:
        return 0


def _configure_auth(monkeypatch) -> str:
    monkeypatch.setenv("JWT_SECRET", "test-secret")
    get_settings.cache_clear()
    fake_redis = FakeRedis()
    monkeypatch.setattr("app.core.auth.get_redis", lambda: fake_redis)
    return create_access_token("0e969876-16d2-4c9f-8fe1-a849f32fa605")[0]


def test_search_is_repository_scoped_and_shapes_pipeline_chunks(monkeypatch) -> None:
    token = _configure_auth(monkeypatch)
    repository_id = uuid4()
    chunk = SimpleNamespace(
        id=uuid4(), file_path="src/auth/service.py", start_line=20, end_line=42,
        content="def authenticate(): ...", score=0.91,
    )
    pipeline = SimpleNamespace(retrieve=AsyncMock(return_value=[chunk]))

    class FakeRepositoryRepository:
        def __init__(self, _: object) -> None:
            pass

        def get_for_user(self, requested_id, user_id):
            assert requested_id == repository_id
            assert str(user_id) == "0e969876-16d2-4c9f-8fe1-a849f32fa605"
            return SimpleNamespace()

    monkeypatch.setattr("app.api.v1.repositories.RepositoryRepository", FakeRepositoryRepository)
    app.state.rag_pipeline = pipeline
    app.dependency_overrides[get_db] = lambda: object()
    try:
        response = TestClient(app, raise_server_exceptions=False).post(
            f"/api/v1/repositories/{repository_id}/search",
            headers={"Authorization": f"Bearer {token}"},
            json={"query": "where is authentication?", "top_k": 8},
        )
    finally:
        app.dependency_overrides.clear()
        del app.state.rag_pipeline

    assert response.status_code == 200
    assert response.json() == {
        "query": "where is authentication?",
        "results": [{
            "id": str(chunk.id), "file_path": "src/auth/service.py",
            "start_line": 20, "end_line": 42, "content": "def authenticate(): ...", "score": 0.91,
        }],
    }
    pipeline.retrieve.assert_awaited_once_with("where is authentication?", repository_id, 8)


def test_search_returns_503_when_retrieval_pipeline_is_not_configured(monkeypatch) -> None:
    token = _configure_auth(monkeypatch)
    repository_id = uuid4()

    class FakeRepositoryRepository:
        def __init__(self, _: object) -> None:
            pass

        def get_for_user(self, *_: object):
            return SimpleNamespace()

    monkeypatch.setattr("app.api.v1.repositories.RepositoryRepository", FakeRepositoryRepository)
    app.dependency_overrides[get_db] = lambda: object()
    try:
        response = TestClient(app, raise_server_exceptions=False).post(
            f"/api/v1/repositories/{repository_id}/search",
            headers={"Authorization": f"Bearer {token}"},
            json={"query": "authentication"},
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "SERVICE_UNAVAILABLE"


def test_search_returns_404_when_repository_is_not_owned(monkeypatch) -> None:
    token = _configure_auth(monkeypatch)

    class FakeRepositoryRepository:
        def __init__(self, _: object) -> None:
            pass

        def get_for_user(self, *_: object):
            return None

    monkeypatch.setattr("app.api.v1.repositories.RepositoryRepository", FakeRepositoryRepository)
    app.state.rag_pipeline = SimpleNamespace(retrieve=AsyncMock())
    app.dependency_overrides[get_db] = lambda: object()
    try:
        response = TestClient(app, raise_server_exceptions=False).post(
            f"/api/v1/repositories/{uuid4()}/search",
            headers={"Authorization": f"Bearer {token}"},
            json={"query": "authentication"},
        )
    finally:
        app.dependency_overrides.clear()
        del app.state.rag_pipeline

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "REPOSITORY_NOT_FOUND"


def test_search_rejects_a_whitespace_only_query(monkeypatch) -> None:
    token = _configure_auth(monkeypatch)

    response = TestClient(app, raise_server_exceptions=False).post(
        f"/api/v1/repositories/{uuid4()}/search",
        headers={"Authorization": f"Bearer {token}"},
        json={"query": "   "},
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "INVALID_REQUEST"
