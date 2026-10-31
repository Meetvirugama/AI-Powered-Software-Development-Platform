"""Contract tests for Yug's Day 6 repository chat endpoint."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from ai.schemas.output import RepositoryAnswer, SourceReference
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
    monkeypatch.setattr("app.core.auth.get_redis", lambda: FakeRedis())
    return create_access_token("0e969876-16d2-4c9f-8fe1-a849f32fa605")[0]


def test_chat_is_repository_scoped_and_returns_pipeline_answer(monkeypatch) -> None:
    token = _configure_auth(monkeypatch)
    repository_id = uuid4()
    answer = RepositoryAnswer(
        answer="Authentication is handled by AuthService.",
        sources=[SourceReference(file="src/auth.py", start_line=10, end_line=24, symbol="AuthService")],
        confidence="high",
    )
    pipeline = SimpleNamespace(chat=AsyncMock(return_value=answer))

    class FakeRepositoryRepository:
        def __init__(self, _: object) -> None:
            pass

        def get_for_user(self, requested_id, user_id):
            assert requested_id == repository_id
            assert str(user_id) == "0e969876-16d2-4c9f-8fe1-a849f32fa605"
            return SimpleNamespace()

    monkeypatch.setattr("app.api.v1.chat.RepositoryRepository", FakeRepositoryRepository)
    app.state.rag_pipeline = pipeline
    app.dependency_overrides[get_db] = lambda: object()
    try:
        response = TestClient(app, raise_server_exceptions=False).post(
            f"/api/v1/repositories/{repository_id}/chat",
            headers={"Authorization": f"Bearer {token}"},
            json={"question": " Where is authentication? ", "history": []},
        )
    finally:
        app.dependency_overrides.clear()
        del app.state.rag_pipeline

    assert response.status_code == 200
    assert response.json() == answer.model_dump()
    pipeline.chat.assert_awaited_once_with("Where is authentication?", repository_id, [])


def test_chat_returns_503_when_pipeline_is_not_configured(monkeypatch) -> None:
    token = _configure_auth(monkeypatch)

    class FakeRepositoryRepository:
        def __init__(self, _: object) -> None:
            pass

        def get_for_user(self, repo_id, user_id):
            return SimpleNamespace()  # User owns the repo

    monkeypatch.setattr("app.api.v1.chat.RepositoryRepository", FakeRepositoryRepository)
    app.dependency_overrides[get_db] = lambda: object()
    try:
        response = TestClient(app, raise_server_exceptions=False).post(
            f"/api/v1/repositories/{uuid4()}/chat",
            headers={"Authorization": f"Bearer {token}"},
            json={"question": "Where is authentication?"},
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "SERVICE_UNAVAILABLE"


def test_chat_rejects_whitespace_only_question(monkeypatch) -> None:
    token = _configure_auth(monkeypatch)
    response = TestClient(app, raise_server_exceptions=False).post(
        f"/api/v1/repositories/{uuid4()}/chat",
        headers={"Authorization": f"Bearer {token}"},
        json={"question": "   "},
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "INVALID_REQUEST"


def test_chat_returns_404_when_user_does_not_own_repository(monkeypatch) -> None:
    token = _configure_auth(monkeypatch)

    class FakeRepositoryRepository:
        def __init__(self, _: object) -> None:
            pass

        def get_for_user(self, repo_id, user_id):
            return None  # User doesn't own this repo

    monkeypatch.setattr("app.api.v1.chat.RepositoryRepository", FakeRepositoryRepository)
    pipeline = SimpleNamespace(chat=AsyncMock())
    app.state.rag_pipeline = pipeline
    app.dependency_overrides[get_db] = lambda: object()
    try:
        response = TestClient(app, raise_server_exceptions=False).post(
            f"/api/v1/repositories/{uuid4()}/chat",
            headers={"Authorization": f"Bearer {token}"},
            json={"question": "Where is auth?"},
        )
    finally:
        app.dependency_overrides.clear()
        del app.state.rag_pipeline

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "REPOSITORY_NOT_FOUND"
    pipeline.chat.assert_not_awaited()


@pytest.mark.asyncio
async def test_concurrent_chat_ownership_checks(monkeypatch) -> None:
    """F-03: Concurrent repository chat requests safely manage their own session lifecycle."""
    import asyncio
    import httpx
    from uuid import uuid4

    token = _configure_auth(monkeypatch)
    owned_repo_id = uuid4()
    foreign_repo_id = uuid4()

    sessions_opened = 0
    sessions_closed = 0

    def mock_get_db():
        nonlocal sessions_opened, sessions_closed
        sessions_opened += 1
        try:
            yield object()
        finally:
            sessions_closed += 1

    class ConcurrencySafeRepoRepository:
        """Mock RepositoryRepository: returns repo for owned_repo_id, None for foreign."""

        def __init__(self, _: object) -> None:
            pass

        def get_for_user(self, requested_id, user_id):
            if requested_id == owned_repo_id:
                return SimpleNamespace(id=owned_repo_id)
            return None

    app.dependency_overrides[get_db] = mock_get_db
    monkeypatch.setattr("app.api.v1.chat.RepositoryRepository", ConcurrencySafeRepoRepository)

    answer = RepositoryAnswer(answer="Concurrency safe answer", sources=[], confidence="high")
    pipeline = SimpleNamespace(chat=AsyncMock(return_value=answer))
    app.state.rag_pipeline = pipeline

    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://testserver",
        ) as ac:
            async def send_req(repo_id: UUID):
                return await ac.post(
                    f"/api/v1/repositories/{repo_id}/chat",
                    headers={"Authorization": f"Bearer {token}"},
                    json={"question": "Concurrency test?"},
                )

            # Fire 10 concurrent requests (5 owned, 5 foreign)
            tasks = [
                send_req(owned_repo_id if i % 2 == 0 else foreign_repo_id)
                for i in range(10)
            ]
            responses = await asyncio.gather(*tasks)

            assert len(responses) == 10
            owned_responses = [r for r in responses if r.status_code == 200]
            foreign_responses = [r for r in responses if r.status_code == 404]

            assert len(owned_responses) == 5
            assert len(foreign_responses) == 5
            assert sessions_opened == 10
            assert sessions_closed == 10
    finally:
        app.dependency_overrides.clear()
        del app.state.rag_pipeline
