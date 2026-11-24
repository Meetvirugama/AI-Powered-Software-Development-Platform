"""Test operational readiness metrics (OPT-24) in /health/ready."""

import httpx
import pytest
from fastapi.testclient import TestClient

from app.api.v1 import health
from app.core.config import Settings
from app.main import app


def test_health_ready_includes_operational_metrics():
    client = TestClient(app)
    response = client.get("/api/v1/health/ready")
    assert response.status_code in (200, 503)
    data = response.json()
    assert "operations" in data
    ops = data["operations"]
    assert "scanner_availability" in ops
    assert "sandbox_backend_ok" in ops
    assert "webhook_backlog" in ops
    assert "sync_worker_heartbeat_age_s" in ops
    assert isinstance(ops["scanner_availability"], dict)
    assert "ruff" in ops["scanner_availability"]
    assert isinstance(ops["webhook_backlog"], int)
    assert isinstance(ops["sandbox_backend_ok"], bool)


@pytest.mark.parametrize("workspace_ready", [True, False])
async def test_remote_runner_readiness_checks_both_workspace_roots(tmp_path, monkeypatch, workspace_ready):
    settings = Settings(
        app_env="testing",
        sandbox_backend="runner",
        task_workspace_root=str(tmp_path),
        runner_base_url="https://runner.example.com",
        runner_auth_secret="test-runner-secret",
    )
    client_type = httpx.AsyncClient

    def respond(request):
        assert request.url.path == "/health"
        assert "Authorization" not in request.headers
        return httpx.Response(200, json={
            "status": "healthy", "backend": "container", "shared_workspace_ready": workspace_ready,
        })

    monkeypatch.setattr(health.httpx, "AsyncClient", lambda **kwargs: client_type(
        **kwargs, transport=httpx.MockTransport(respond),
    ))
    assert await health._sandbox_backend_ready(settings) is workspace_ready
    settings.task_workspace_root = str(tmp_path / "missing")
    assert not await health._sandbox_backend_ready(settings)
