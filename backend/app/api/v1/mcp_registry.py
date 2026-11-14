"""Tools & MCP Server Registry Admin API (Issue 2 — §12 Tools & Integrations Admin UI)."""

from __future__ import annotations

import json
import time
from typing import Any, Dict, List, Literal

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.core.errors import APIError, ErrorCode
from app.mcp.server import DEFAULT_MCP_TOOLS, get_platform_mcp_server
from app.services.mcp_elicitation_service import validate_mcp_url

router = APIRouter(prefix="/mcp", tags=["mcp-registry"])


class MCPToolItemSchema(BaseModel):
    name: str
    description: str
    riskTier: Literal["low", "medium", "high", "critical"] = "low"
    requiresApproval: bool = False
    inputSchemaJson: str


class MCPServerSchema(BaseModel):
    id: str
    name: str
    transport: Literal["stdio", "sse", "streamable_http"] = "stdio"
    endpointOrCommand: str
    enabled: bool = True
    status: Literal["connected", "degraded", "offline"] = "connected"
    protocolVersion: str = "2024-11-05"
    lastLatencyMs: int | None = 4
    tools: List[MCPToolItemSchema] = Field(default_factory=list)


class RegisterMCPServerRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=120)
    transport: Literal["stdio", "sse", "streamable_http"] = "stdio"
    endpointOrCommand: str = Field(..., min_length=1, max_length=512)


class UpdateToolApprovalPolicyRequest(BaseModel):
    requiresApproval: bool


_REGISTRY_SERVERS: Dict[str, MCPServerSchema] = {
    "mcp-platform-core": MCPServerSchema(
        id="mcp-platform-core",
        name="Platform Repository Intelligence MCP",
        transport="stdio",
        endpointOrCommand="python -m backend.mcp.server",
        enabled=True,
        status="connected",
        protocolVersion="2024-11-05",
        lastLatencyMs=4,
        tools=[
            MCPToolItemSchema(
                name=t["name"],
                description=t["description"],
                riskTier=t["riskTier"],
                requiresApproval=t["requiresApproval"],
                inputSchemaJson=json.dumps(t["inputSchema"], indent=2),
            )
            for t in DEFAULT_MCP_TOOLS
        ],
    )
}


@router.get("/servers", response_model=List[MCPServerSchema], summary="List registered MCP servers and tool schemas")
async def list_mcp_servers() -> List[MCPServerSchema]:
    return list(_REGISTRY_SERVERS.values())


@router.post("/servers", response_model=MCPServerSchema, status_code=201, summary="Register an MCP server")
async def register_mcp_server(payload: RegisterMCPServerRequest) -> MCPServerSchema:
    endpoint = payload.endpointOrCommand.strip()
    if payload.transport in ("sse", "streamable_http"):
        endpoint = validate_mcp_url(endpoint)
    elif any(ch in endpoint for ch in (";", "&&", "||", "|", "`", "$", "\n", "\r", "\x00")):
        raise APIError(400, ErrorCode.MCP_SECURITY_VIOLATION, "Unsafe shell metacharacters in stdio command")

    srv_id = f"mcp-{int(time.time() * 1000)}"
    server = MCPServerSchema(
        id=srv_id,
        name=payload.name.strip(),
        transport=payload.transport,
        endpointOrCommand=endpoint,
        enabled=True,
        status="connected",
        protocolVersion="2024-11-05",
        lastLatencyMs=3,
        tools=[],
    )
    _REGISTRY_SERVERS[srv_id] = server
    return server


@router.post("/servers/{server_id}/ping", response_model=MCPServerSchema, summary="Ping an MCP server")
async def ping_mcp_server(server_id: str) -> MCPServerSchema:
    srv = _REGISTRY_SERVERS.get(server_id)
    if srv is None:
        raise APIError(404, ErrorCode.RESOURCE_NOT_FOUND, f"MCP server '{server_id}' not found")
    if not srv.enabled:
        return srv
    start_ns = time.perf_counter_ns()
    mcp_srv = get_platform_mcp_server()
    mcp_srv.handle_jsonrpc({"jsonrpc": "2.0", "id": 1, "method": "ping"})
    elapsed_ms = max(1, int((time.perf_counter_ns() - start_ns) / 1_000_000))
    updated = srv.model_copy(update={"status": "connected", "lastLatencyMs": elapsed_ms})
    _REGISTRY_SERVERS[server_id] = updated
    return updated


@router.patch("/servers/{server_id}/toggle", response_model=MCPServerSchema, summary="Enable or disable an MCP server")
async def toggle_mcp_server(server_id: str) -> MCPServerSchema:
    srv = _REGISTRY_SERVERS.get(server_id)
    if srv is None:
        raise APIError(404, ErrorCode.RESOURCE_NOT_FOUND, f"MCP server '{server_id}' not found")
    next_enabled = not srv.enabled
    updated = srv.model_copy(
        update={
            "enabled": next_enabled,
            "status": "connected" if next_enabled else "offline",
            "lastLatencyMs": 4 if next_enabled else None,
        }
    )
    _REGISTRY_SERVERS[server_id] = updated
    return updated


@router.patch(
    "/servers/{server_id}/tools/{tool_name}/policy",
    response_model=MCPServerSchema,
    summary="Update approval gate policy for an MCP tool",
)
async def update_mcp_tool_policy(
    server_id: str,
    tool_name: str,
    payload: UpdateToolApprovalPolicyRequest,
) -> MCPServerSchema:
    srv = _REGISTRY_SERVERS.get(server_id)
    if srv is None:
        raise APIError(404, ErrorCode.RESOURCE_NOT_FOUND, f"MCP server '{server_id}' not found")
    new_tools = [
        t.model_copy(update={"requiresApproval": payload.requiresApproval}) if t.name == tool_name else t
        for t in srv.tools
    ]
    updated = srv.model_copy(update={"tools": new_tools})
    _REGISTRY_SERVERS[server_id] = updated
    return updated
