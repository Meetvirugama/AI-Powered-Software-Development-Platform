"""Role-Based Access Control (RBAC) tests for MCP Registry endpoints (TST-04, ISS-003).

Validates RBAC permissions:
- Viewer cannot view or mutate MCP servers (403).
- Developer can list built-in MCP tools (200).
- Admin can ping the built-in dispatcher.
"""

from uuid import uuid4
from fastapi.testclient import TestClient

from app.core.security import create_access_token


def _get_headers(role: str) -> dict[str, str]:
    token, _ = create_access_token(uuid4(), role=role)
    return {"Authorization": f"Bearer {token}"}


def test_mcp_list_servers_rbac(client: TestClient) -> None:
    """TST-04: GET /mcp/servers requires minimum DEVELOPER role; VIEWER is rejected."""
    viewer_headers = _get_headers("viewer")
    dev_headers = _get_headers("developer")
    admin_headers = _get_headers("admin")

    # Viewer receives 403
    v_resp = client.get("/api/v1/mcp/servers", headers=viewer_headers)
    assert v_resp.status_code == 403
    assert v_resp.json()["error"]["code"] == "FORBIDDEN"

    # Developer receives 200
    d_resp = client.get("/api/v1/mcp/servers", headers=dev_headers)
    assert d_resp.status_code == 200
    assert isinstance(d_resp.json(), list)

    # Admin receives 200
    a_resp = client.get("/api/v1/mcp/servers", headers=admin_headers)
    assert a_resp.status_code == 200
    assert isinstance(a_resp.json(), list)


def test_mcp_ping_server_rbac(client: TestClient) -> None:
    """TST-04: POST /mcp/servers/{server_id}/ping requires ADMIN role."""
    viewer_headers = _get_headers("viewer")
    dev_headers = _get_headers("developer")
    admin_headers = _get_headers("admin")

    server_id = "mcp-platform-core"

    # Viewer receives 403
    v_resp = client.post(f"/api/v1/mcp/servers/{server_id}/ping", headers=viewer_headers)
    assert v_resp.status_code == 403

    # Developer receives 403
    d_resp = client.post(f"/api/v1/mcp/servers/{server_id}/ping", headers=dev_headers)
    assert d_resp.status_code == 403

    # Admin receives 200
    a_resp = client.post(f"/api/v1/mcp/servers/{server_id}/ping", headers=admin_headers)
    assert a_resp.status_code == 200
    assert a_resp.json()["transport"] == "in_process"
    assert a_resp.json()["lastLatencyMs"] >= 0


def test_mcp_catalog_exposes_only_real_controls(client: TestClient) -> None:
    headers = _get_headers("admin")
    server = client.get("/api/v1/mcp/servers", headers=headers).json()[0]
    assert server["lastLatencyMs"] is None
    assert server["tools"]
    assert client.post("/api/v1/mcp/servers/external/ping", headers=headers).status_code == 404
    assert client.post("/api/v1/mcp/servers", headers=headers, json={}).status_code == 405
    assert client.patch("/api/v1/mcp/servers/mcp-platform-core/toggle", headers=headers).status_code == 404
