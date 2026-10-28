"""Tests for the application health check endpoint and test infrastructure.

Validates that:
- GET /health returns 200 OK and expected JSON schema.
- Asynchronous client (httpx) works as expected against the endpoint.
- Health checks do not require JWT authentication or database connectivity.
- Request ID middleware generates and propagates X-Request-ID headers.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient
import httpx

from app.schemas.health import HealthResponse


def test_health_check_returns_200_and_correct_json(client: TestClient) -> None:
    """Synchronous test verifying GET /health returns 200 and expected metadata."""
    response = client.get("/health")

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert "version" in data
    assert data["version"] == "1.0.0"


@pytest.mark.asyncio
async def test_health_check_async_client(async_client: httpx.AsyncClient) -> None:
    """Asynchronous test verifying GET /health via httpx.AsyncClient."""
    response = await async_client.get("/health")

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["version"] == "1.0.0"


def test_api_v1_health_check_returns_200(client: TestClient) -> None:
    """Verify versioned endpoint /api/v1/health also succeeds without auth."""
    response = client.get("/api/v1/health")

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["version"] == "1.0.0"


def test_health_check_does_not_require_jwt(client: TestClient) -> None:
    """Verify health check is public and accessible without Authorization headers."""
    response = client.get("/health", headers={})
    assert response.status_code == 200


def test_health_check_propagates_request_id(client: TestClient) -> None:
    """Verify RequestIdMiddleware adds an X-Request-ID response header."""
    custom_id = "test-request-id-12345"
    response = client.get("/health", headers={"x-request-id": custom_id})

    assert response.status_code == 200
    assert response.headers.get("x-request-id") == custom_id


def test_health_response_model() -> None:
    """Unit test for the HealthResponse Pydantic model serialization."""
    model = HealthResponse(status="ok", version="1.0.0")
    assert model.status == "ok"
    assert model.version == "1.0.0"
    serialized = model.model_dump()
    assert serialized == {"status": "ok", "version": "1.0.0"}


def test_health_live_endpoint(client: TestClient) -> None:
    """Verify GET /health/live returns 200 without requiring DB or auth."""
    res = client.get("/health/live")
    assert res.status_code == 200
    assert res.json()["status"] == "ok"


def test_health_ready_success_or_degraded(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify GET /health/ready returns 200 when database connectivity succeeds."""
    from unittest.mock import MagicMock
    from app.main import app

    app.state.service_readiness = {
        "database": True,
        "redis": True,
        "llm_gateway": True,
        "rag_pipeline": True,
        "explanation_service": True,
        "bug_detection_service": True,
        "test_generation_service": True,
        "code_review_service": True,
        "context_service": True,
        "history_services": True,
        "github_service": True,
    }
    app.state.llm_gateway = object()
    app.state.rag_pipeline = object()

    # Mock DB execution
    mock_session = MagicMock()
    mock_session.__enter__.return_value = mock_session
    monkeypatch.setattr("app.api.v1.health.SessionLocal", lambda: mock_session)

    # Mock Redis ping
    mock_redis = MagicMock()
    mock_redis.ping.return_value = True
    monkeypatch.setattr("app.api.v1.health.get_redis", lambda: mock_redis)

    res = client.get("/health/ready")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] in ("ready", "degraded")
    assert data["database"]["status"] == "healthy"
    assert data["redis"]["status"] == "healthy"
    assert data["llm_gateway"]["status"] == "healthy"
    assert data["rag_pipeline"]["status"] == "healthy"


def test_health_ready_returns_503_on_db_outage(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify GET /health/ready returns 503 and does not leak credentials when DB is down."""
    mock_session = MagicMock()
    mock_session.__enter__.side_effect = Exception("password=super_secret_db_password connection refused")
    monkeypatch.setattr("app.api.v1.health.SessionLocal", lambda: mock_session)

    res = client.get("/health/ready")
    assert res.status_code == 503
    data = res.json()
    assert data["status"] == "not_ready"
    assert data["database"]["status"] == "unhealthy"
    # Ensure sensitive credentials are never leaked
    assert "super_secret_db_password" not in str(data)


def test_modular_initialization_isolation(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify failure in one initializer does not prevent others or leave half-valid state."""
    from fastapi import FastAPI
    from app.main import (
        init_llm_gateway,
        init_rag_pipeline,
        init_intelligence_services,
        init_context_service,
        init_history_services,
    )

    test_app = FastAPI()
    test_app.state.service_readiness = {}

    # Force keys to empty
    monkeypatch.setattr("app.core.config.Settings.all_gemini_keys", property(lambda self: []))
    monkeypatch.setattr("app.core.config.Settings.all_groq_keys", property(lambda self: []))

    # LLM Gateway skips gracefully
    ok_llm = init_llm_gateway(test_app)
    assert ok_llm is False
    assert test_app.state.llm_gateway is None
    assert test_app.state.service_readiness["llm_gateway"] is False

    # Context service still succeeds independently
    ok_ctx = init_context_service(test_app)
    assert ok_ctx is True
    assert test_app.state.context_service is not None
    assert test_app.state.service_readiness["context_service"] is True

    # History services still succeed independently
    ok_hist = init_history_services(test_app)
    assert ok_hist is True
    assert test_app.state.service_readiness["history_services"] is True
    assert test_app.state.explanation_history_service is not None
