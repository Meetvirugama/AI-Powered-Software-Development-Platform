"""
Tests for Repository Chat API Mode Dispatch and Agentic Mode (task.md §15, §22.8).

Verifies:
- Default request without 'mode' defaults to 'normal' chat.
- Explicit 'normal' mode executes standard RAG pipeline.
- Explicit 'agentic' mode executes AgentOrchestrator and includes agent_metadata.
- Invalid mode value returns 422 validation error.
- Disabled agentic feature flag returns 400.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

from ai.schemas.output import RepositoryAnswer, SourceReference
from app.core.config import get_settings
from app.core.database import get_db
from app.core.security import create_access_token
from app.main import app
from fastapi.testclient import TestClient


class FakeRedis:
    def exists(self, _: str) -> int:
        return 0


def _configure_auth(monkeypatch) -> str:
    monkeypatch.setenv("JWT_SECRET", "test-secret")
    get_settings.cache_clear()
    monkeypatch.setattr("app.core.auth.get_redis", lambda: FakeRedis())
    return create_access_token("0e969876-16d2-4c9f-8fe1-a849f32fa605")[0]


def test_api_omitted_mode_defaults_to_normal(monkeypatch) -> None:
    token = _configure_auth(monkeypatch)
    repo_id = uuid4()

    class FakeRepoRepo:
        def __init__(self, _: object) -> None:
            pass

        def get_for_user(self, r_id, u_id):
            return SimpleNamespace()

    monkeypatch.setattr("app.api.v1.chat.RepositoryRepository", FakeRepoRepo)
    mock_pipeline = SimpleNamespace(
        chat=AsyncMock(
            return_value=RepositoryAnswer(
                answer="Normal chat answer",
                sources=[],
                confidence="high",
                status="completed",
            )
        )
    )
    app.state.rag_pipeline = mock_pipeline
    app.dependency_overrides[get_db] = lambda: object()

    try:
        resp = TestClient(app, raise_server_exceptions=False).post(
            f"/api/v1/repositories/{repo_id}/chat",
            headers={"Authorization": f"Bearer {token}"},
            json={"question": "What is this repo?"},
        )
    finally:
        app.dependency_overrides.clear()
        if hasattr(app.state, "rag_pipeline"):
            del app.state.rag_pipeline

    assert resp.status_code == 200
    data = resp.json()
    assert data["answer"] == "Normal chat answer"
    assert data.get("agent_metadata") is None
    mock_pipeline.chat.assert_awaited_once_with("What is this repo?", repo_id, [])


def test_api_explicit_normal_mode(monkeypatch) -> None:
    token = _configure_auth(monkeypatch)
    repo_id = uuid4()

    class FakeRepoRepo:
        def __init__(self, _: object) -> None:
            pass

        def get_for_user(self, r_id, u_id):
            return SimpleNamespace()

    monkeypatch.setattr("app.api.v1.chat.RepositoryRepository", FakeRepoRepo)
    mock_pipeline = SimpleNamespace(
        chat=AsyncMock(
            return_value=RepositoryAnswer(
                answer="Explicit normal answer",
                sources=[],
                confidence="high",
                status="completed",
            )
        )
    )
    app.state.rag_pipeline = mock_pipeline
    app.dependency_overrides[get_db] = lambda: object()

    try:
        resp = TestClient(app, raise_server_exceptions=False).post(
            f"/api/v1/repositories/{repo_id}/chat",
            headers={"Authorization": f"Bearer {token}"},
            json={"question": "What is this repo?", "mode": "normal"},
        )
    finally:
        app.dependency_overrides.clear()
        if hasattr(app.state, "rag_pipeline"):
            del app.state.rag_pipeline

    assert resp.status_code == 200
    data = resp.json()
    assert data["answer"] == "Explicit normal answer"
    mock_pipeline.chat.assert_awaited_once_with("What is this repo?", repo_id, [])


def test_api_agentic_mode_dispatches_to_orchestrator(monkeypatch) -> None:
    token = _configure_auth(monkeypatch)
    repo_id = uuid4()

    class FakeRepoRepo:
        def __init__(self, _: object) -> None:
            pass

        def get_for_user(self, r_id, u_id):
            return SimpleNamespace()

    monkeypatch.setattr("app.api.v1.chat.RepositoryRepository", FakeRepoRepo)
    mock_pipeline = SimpleNamespace(chat=AsyncMock())
    mock_orchestrator = SimpleNamespace(
        run=AsyncMock(
            return_value=RepositoryAnswer(
                answer="Agentic investigation answer",
                sources=[SourceReference(file="src/auth.py", start_line=1, end_line=20)],
                confidence="high",
                status="completed",
                agent_metadata={
                    "mode": "agentic",
                    "provider": "gemini",
                    "model": "gemini-flash-lite-latest",
                    "tool_calls": 2,
                    "model_calls": 3,
                    "stop_reason": "final_answer",
                },
            )
        )
    )
    app.state.rag_pipeline = mock_pipeline
    app.state.agent_orchestrator = mock_orchestrator
    app.dependency_overrides[get_db] = lambda: object()

    try:
        resp = TestClient(app, raise_server_exceptions=False).post(
            f"/api/v1/repositories/{repo_id}/chat",
            headers={"Authorization": f"Bearer {token}"},
            json={"question": "Where does token refresh fail?", "mode": "agentic"},
        )
    finally:
        app.dependency_overrides.clear()
        if hasattr(app.state, "rag_pipeline"):
            del app.state.rag_pipeline
        if hasattr(app.state, "agent_orchestrator"):
            del app.state.agent_orchestrator

    assert resp.status_code == 200
    data = resp.json()
    assert data["answer"] == "Agentic investigation answer"
    assert data["agent_metadata"]["mode"] == "agentic"
    assert data["agent_metadata"]["tool_calls"] == 2
    mock_orchestrator.run.assert_awaited_once()


def test_api_invalid_mode_rejected(monkeypatch) -> None:
    token = _configure_auth(monkeypatch)
    repo_id = uuid4()

    class FakeRepoRepo:
        def __init__(self, _: object) -> None:
            pass

        def get_for_user(self, r_id, u_id):
            return SimpleNamespace()

    monkeypatch.setattr("app.api.v1.chat.RepositoryRepository", FakeRepoRepo)
    app.dependency_overrides[get_db] = lambda: object()

    try:
        resp = TestClient(app, raise_server_exceptions=False).post(
            f"/api/v1/repositories/{repo_id}/chat",
            headers={"Authorization": f"Bearer {token}"},
            json={"question": "Question", "mode": "unsupported_mode"},
        )
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 422


def test_api_agentic_mode_disabled_by_flag(monkeypatch) -> None:
    token = _configure_auth(monkeypatch)
    repo_id = uuid4()

    class FakeRepoRepo:
        def __init__(self, _: object) -> None:
            pass

        def get_for_user(self, r_id, u_id):
            return SimpleNamespace()

    monkeypatch.setattr("app.api.v1.chat.RepositoryRepository", FakeRepoRepo)
    monkeypatch.setenv("AGENTIC_CHAT_ENABLED", "false")
    get_settings.cache_clear()

    mock_pipeline = SimpleNamespace(chat=AsyncMock())
    app.state.rag_pipeline = mock_pipeline
    app.dependency_overrides[get_db] = lambda: object()

    try:
        resp = TestClient(app, raise_server_exceptions=False).post(
            f"/api/v1/repositories/{repo_id}/chat",
            headers={"Authorization": f"Bearer {token}"},
            json={"question": "Question", "mode": "agentic"},
        )
    finally:
        app.dependency_overrides.clear()
        if hasattr(app.state, "rag_pipeline"):
            del app.state.rag_pipeline
        get_settings.cache_clear()

    assert resp.status_code == 400
    assert "disabled" in resp.json()["error"]["message"]
