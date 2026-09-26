"""Tests for the application health check endpoint and test infrastructure.

Validates that:
- GET /health returns 200 OK and expected JSON schema.
- Asynchronous client (httpx) works as expected against the endpoint.
- Health checks do not require JWT authentication or database connectivity.
- Request ID middleware generates and propagates X-Request-ID headers.
"""

from __future__ import annotations

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
