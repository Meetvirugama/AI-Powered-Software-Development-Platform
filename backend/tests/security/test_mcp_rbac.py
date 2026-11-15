"""Role-Based Access Control (RBAC) tests for MCP Registry endpoints (TST-04, ISS-003).

Validates RBAC permissions:
- Viewer cannot view or mutate MCP servers (403).
- Developer can list MCP servers (200), but cannot mutate them (403).
- Admin can list and mutate (register, ping, toggle, update policy) MCP servers.
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


def test_mcp_register_server_rbac(client: TestClient) -> None:
    """TST-04: POST /mcp/servers requires ADMIN role; VIEWER and DEVELOPER receive 403."""
    viewer_headers = _get_headers("viewer")
    dev_headers = _get_headers("developer")
    admin_headers = _get_headers("admin")

    payload = {
        "name": "Audit Test Server",
        "transport": "stdio",
        "endpointOrCommand": "npx -y @modelcontextprotocol/server-everything",
    }

    # Viewer receives 403
    v_resp = client.post("/api/v1/mcp/servers", headers=viewer_headers, json=payload)
    assert v_resp.status_code == 403

    # Developer receives 403
    d_resp = client.post("/api/v1/mcp/servers", headers=dev_headers, json=payload)
    assert d_resp.status_code == 403

    # Admin receives 201
    a_resp = client.post("/api/v1/mcp/servers", headers=admin_headers, json=payload)
    assert a_resp.status_code == 201
    assert a_resp.json()["name"] == "Audit Test Server"


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


def test_mcp_toggle_server_rbac(client: TestClient) -> None:
    """TST-04: PATCH /mcp/servers/{server_id}/toggle requires ADMIN role."""
    viewer_headers = _get_headers("viewer")
    dev_headers = _get_headers("developer")
    admin_headers = _get_headers("admin")

    server_id = "mcp-platform-core"

    # Viewer receives 403
    v_resp = client.patch(f"/api/v1/mcp/servers/{server_id}/toggle", headers=viewer_headers)
    assert v_resp.status_code == 403

    # Developer receives 403
    d_resp = client.patch(f"/api/v1/mcp/servers/{server_id}/toggle", headers=dev_headers)
    assert d_resp.status_code == 403

    # Admin receives 200
    a_resp = client.patch(f"/api/v1/mcp/servers/{server_id}/toggle", headers=admin_headers)
    assert a_resp.status_code == 200


def test_mcp_tool_policy_rbac(client: TestClient) -> None:
    """TST-04: PATCH /mcp/servers/{server_id}/tools/{tool_name}/policy requires ADMIN role."""
    viewer_headers = _get_headers("viewer")
    dev_headers = _get_headers("developer")
    admin_headers = _get_headers("admin")

    server_id = "mcp-platform-core"
    tool_name = "read_file"
    payload = {"requiresApproval": True, "riskTier": "high"}

    # Viewer receives 403
    v_resp = client.patch(
        f"/api/v1/mcp/servers/{server_id}/tools/{tool_name}/policy",
        headers=viewer_headers,
        json=payload,
    )
    assert v_resp.status_code == 403

    # Developer receives 403
    d_resp = client.patch(
        f"/api/v1/mcp/servers/{server_id}/tools/{tool_name}/policy",
        headers=dev_headers,
        json=payload,
    )
    assert d_resp.status_code == 403

    # Admin receives 200
    a_resp = client.patch(
        f"/api/v1/mcp/servers/{server_id}/tools/{tool_name}/policy",
        headers=admin_headers,
        json=payload,
    )
    assert a_resp.status_code == 200
