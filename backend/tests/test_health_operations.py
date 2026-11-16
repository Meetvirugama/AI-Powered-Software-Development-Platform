"""Test operational readiness metrics (OPT-24) in /health/ready."""

from fastapi.testclient import TestClient
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
