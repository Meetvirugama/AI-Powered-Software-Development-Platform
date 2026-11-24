"""Catalog and health probe for the built-in MCP dispatcher."""

from __future__ import annotations

import json
import time
from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.api.v1.dependencies import require_min_role, require_role
from app.core.errors import APIError, ErrorCode
from app.mcp.server import DEFAULT_MCP_TOOLS, get_platform_mcp_server
from app.models.user import UserRole

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
    transport: Literal["in_process"] = "in_process"
    endpointOrCommand: str
    enabled: bool = True
    status: Literal["connected", "degraded", "offline"] = "connected"
    protocolVersion: str = "2024-11-05"
    lastLatencyMs: int | None = None
    tools: list[MCPToolItemSchema] = Field(default_factory=list)


_CORE_SERVER = MCPServerSchema(
    id="mcp-platform-core",
    name="Platform Repository Intelligence MCP",
    endpointOrCommand="Built-in dispatcher",
    tools=[
        MCPToolItemSchema(
            name=tool["name"],
            description=tool["description"],
            riskTier=tool["riskTier"],
            requiresApproval=tool["requiresApproval"],
            inputSchemaJson=json.dumps(tool["inputSchema"], indent=2),
        )
        for tool in DEFAULT_MCP_TOOLS
    ],
)


@router.get("/servers", response_model=list[MCPServerSchema], summary="List built-in MCP tools")
async def list_mcp_servers(
    _user_role: str = Depends(require_min_role(UserRole.DEVELOPER)),
) -> list[MCPServerSchema]:
    return [_CORE_SERVER]


@router.post("/servers/{server_id}/ping", response_model=MCPServerSchema, summary="Ping the built-in MCP dispatcher")
async def ping_mcp_server(
    server_id: str,
    _user_role: str = Depends(require_role(UserRole.ADMIN)),
) -> MCPServerSchema:
    if server_id != _CORE_SERVER.id:
        raise APIError(404, ErrorCode.RESOURCE_NOT_FOUND, "MCP server not found")
    start_ns = time.perf_counter_ns()
    reply = get_platform_mcp_server().handle_jsonrpc({"jsonrpc": "2.0", "id": 1, "method": "ping"})
    if not isinstance(reply, dict) or "result" not in reply:
        raise APIError(503, ErrorCode.SERVICE_UNAVAILABLE, "The built-in MCP dispatcher did not respond to ping")
    elapsed_ms = (time.perf_counter_ns() - start_ns) // 1_000_000
    return _CORE_SERVER.model_copy(update={"lastLatencyMs": elapsed_ms})
