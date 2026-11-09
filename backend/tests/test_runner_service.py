"""Integration Tests for the Internal Runner Service.

Owner: AI Platform Security Architecture — Issue #200 / F20
Reference: Docs/security/sandbox/04-runner-service-design.md
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from runner.main import create_runner_app
from sandbox.backend import SandboxBackend
from app.schemas.workspace import WorkspaceCommandResult


@pytest.fixture
def mock_backend():
    backend = MagicMock(spec=SandboxBackend)
    backend.backend_type = "container"
    backend.gvisor_available = True
    backend.create_workspace.return_value = Path("/sandbox/workspaces/test-task-1")
    backend.read_file.return_value = "print('hello from runner')\n"
    backend.get_diff.return_value = "diff --git a/test.py b/test.py\n"
    backend.get_status.return_value = {
        "status": "READY",
        "gvisor_verified": True,
        "backend": "container",
    }
    backend.execute.return_value = WorkspaceCommandResult(
        success=True,
        command="pytest",
        exit_code=0,
        stdout="1 passed",
        stderr="",
        duration_ms=45.0,
        timed_out=False,
    )
    return backend


@pytest.fixture
def runner_client(mock_backend, monkeypatch):
    monkeypatch.setattr("runner.main.get_runner_secret", lambda: "test-runner-token-12345")
    app = create_runner_app(backend=mock_backend)
    return TestClient(app)


def test_health_check(runner_client):
    """Health check endpoint requires no auth and reports runner status."""
    resp = runner_client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "healthy"
    assert data["backend"] == "container"
    assert data["gvisor_verified"] is True


def test_runner_auth_enforcement(runner_client):
    """Endpoints require valid X-Runner-Token or Authorization Bearer header."""
    # 1. No token -> 401
    resp = runner_client.post(
        "/internal/v1/workspaces",
        json={"task_id": "task-unauth"},
    )
    assert resp.status_code == 401

    # 2. Invalid token -> 401
    resp = runner_client.post(
        "/internal/v1/workspaces",
        json={"task_id": "task-unauth"},
        headers={"X-Runner-Token": "wrong-secret-token"},
    )
    assert resp.status_code == 401

    # 3. Valid Bearer Token -> 200
    resp = runner_client.post(
        "/internal/v1/workspaces",
        json={"task_id": "task-auth-ok"},
        headers={"Authorization": "Bearer test-runner-token-12345"},
    )
    assert resp.status_code == 200
    assert resp.json()["success"] is True


def test_runner_execute_command(runner_client, mock_backend):
    """Verify execution request is passed to backend and formatted."""
    resp = runner_client.post(
        "/internal/v1/workspaces/test-task-1/exec",
        json={
            "command": "pytest",
            "arguments": ["-q"],
            "timeout_seconds": 30,
            "network_enabled": False,
        },
        headers={"X-Runner-Token": "test-runner-token-12345"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert data["command"] == "pytest"
    assert data["stdout"] == "1 passed"
    mock_backend.execute.assert_called_once()


def test_runner_file_operations(runner_client, mock_backend):
    """Verify read, write, diff, and destroy endpoints."""
    headers = {"X-Runner-Token": "test-runner-token-12345"}

    # Read
    resp = runner_client.get(
        "/internal/v1/workspaces/test-task-1/files?path=main.py",
        headers=headers,
    )
    assert resp.status_code == 200
    assert resp.json()["content"] == "print('hello from runner')\n"

    # Write
    resp = runner_client.put(
        "/internal/v1/workspaces/test-task-1/files",
        json={"path": "main.py", "content": "updated code"},
        headers=headers,
    )
    assert resp.status_code == 200
    assert resp.json()["bytes_written"] == len("updated code".encode("utf-8"))

    # Diff
    resp = runner_client.get(
        "/internal/v1/workspaces/test-task-1/diff",
        headers=headers,
    )
    assert resp.status_code == 200
    assert "diff --git" in resp.json()["diff"]

    # Status
    resp = runner_client.get(
        "/internal/v1/workspaces/test-task-1/status",
        headers=headers,
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "READY"

    # Destroy
    resp = runner_client.delete(
        "/internal/v1/workspaces/test-task-1",
        headers=headers,
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "DESTROYED"
    mock_backend.destroy_workspace.assert_called_once_with("test-task-1")


def test_runner_auth_missing_secret_fails_closed(mock_backend, monkeypatch):
    """Missing secret fails closed (500) by default even in development."""
    monkeypatch.setattr("runner.main.get_runner_secret", lambda: "")
    monkeypatch.setattr("app.core.config.settings.app_env", "development")
    monkeypatch.setattr("app.core.config.settings.runner_allow_unauthenticated_dev", False)

    app = create_runner_app(backend=mock_backend)
    client = TestClient(app)

    resp = client.post("/internal/v1/workspaces", json={"task_id": "test-task"})
    assert resp.status_code == 500
    assert "RUNNER_AUTH_SECRET" in resp.json()["detail"]


def test_runner_auth_missing_secret_opt_in_loopback(mock_backend, monkeypatch):
    """Missing secret allows access only when explicit dev opt-in is enabled on loopback."""
    monkeypatch.setattr("runner.main.get_runner_secret", lambda: "")
    monkeypatch.setattr("app.core.config.settings.app_env", "development")
    monkeypatch.setattr("app.core.config.settings.runner_allow_unauthenticated_dev", True)

    app = create_runner_app(backend=mock_backend)
    client = TestClient(app)

    resp = client.post("/internal/v1/workspaces", json={"task_id": "test-task"})
    assert resp.status_code == 200
    assert resp.json()["success"] is True


def test_runner_create_workspace_path_traversal_rejection(runner_client):
    """base_repo_path traversal attempts are rejected."""
    headers = {"X-Runner-Token": "test-runner-token-12345"}
    resp = runner_client.post(
        "/internal/v1/workspaces",
        json={"task_id": "test-task", "base_repo_path": "/etc/shadow"},
        headers=headers,
    )
    assert resp.status_code in (400, 422)
