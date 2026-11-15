"""Webhook payload size guard test (TST-10, ISS-031).

Validates:
- Webhook requests with Content-Length header > 5MB are rejected early with 413 without reading entire body.
- Webhook requests with actual body bytes > 5MB are rejected with 413.
"""

from fastapi.testclient import TestClient


def test_webhook_rejects_large_content_length_header(client: TestClient) -> None:
    """TST-10: Request with Content-Length > 5MB is rejected with 413 Payload Too Large."""
    resp = client.post(
        "/api/v1/github/webhook",
        headers={"Content-Length": str(6 * 1024 * 1024)},  # 6 MB
        content=b"small-dummy",
    )
    assert resp.status_code == 413
    assert "exceeds maximum allowed size" in resp.json()["error"]["message"].lower()


def test_webhook_rejects_large_body_bytes(client: TestClient) -> None:
    """TST-10: Request with actual body > 5MB is rejected with 413."""
    large_payload = b"X" * (5 * 1024 * 1024 + 1024)  # 5MB + 1KB
    resp = client.post(
        "/api/v1/github/webhook",
        content=large_payload,
    )
    assert resp.status_code == 413
    assert "exceeds maximum allowed size" in resp.json()["error"]["message"].lower()
