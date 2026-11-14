"""Model Context Protocol (MCP) Tool Execution Adapter Boundary.

Part of F21 — Tool router and tool policy bridge (Issue #201) & Issue 3 MCP Server Contract.
Connects MCP tool definitions to the PlatformMCPServer JSON-RPC 2.0 dispatcher
for local/platform MCP servers while enforcing strict boundary controls on remote servers.
"""

from __future__ import annotations

import logging
import pathlib
from typing import Any

from agent.tools.adapters.base import BaseToolAdapter
from agent.tools.models import ToolDefinition

logger = logging.getLogger(__name__)


class MCPToolAdapter(BaseToolAdapter):
    """Adapter for Model Context Protocol (MCP) tool execution."""

    def __init__(
        self,
        server_id: str,
        server_url: str | None = None,
        auth_token: str | None = None,
        *,
        workspace_root: pathlib.Path | str | None = None,
        dispatcher: Any | None = None,
    ) -> None:
        self.server_id = server_id
        self.server_url = server_url
        self._auth_token = auth_token
        self._workspace_root = workspace_root
        self._dispatcher = dispatcher

    def _get_dispatcher(self) -> Any | None:
        if self._dispatcher is not None:
            return self._dispatcher
        if self.server_id in ("mcp-platform-core", "se-project-mcp", "platform") and not self.server_url:
            from app.mcp.server import get_platform_mcp_server
            srv = get_platform_mcp_server(self._workspace_root)
            if not srv.initialized:
                srv.handle_jsonrpc({"jsonrpc": "2.0", "id": 0, "method": "initialize"})
            return srv
        return None

    def execute(
        self,
        tool: ToolDefinition,
        arguments: dict[str, Any],
        context: Any,
    ) -> Any:
        """Execute tool against PlatformMCPServer or remote MCP server endpoint."""
        logger.info("mcp_tool_execution_boundary_invoked", extra={"tool": tool.name, "server": self.server_id})
        dispatcher = self._get_dispatcher()
        if dispatcher is not None:
            resp = dispatcher.handle_jsonrpc(
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "tools/call",
                    "params": {"name": tool.name, "arguments": arguments},
                }
            )
            if isinstance(resp, dict) and "error" in resp:
                raise RuntimeError(resp["error"].get("message", "MCP JSON-RPC error"))
            if isinstance(resp, dict) and "result" in resp:
                return resp["result"]
            return resp

        raise NotImplementedError(
            f"MCP server execution for '{tool.name}' on server '{self.server_id}' is scheduled for a future milestone."
        )

    async def aexecute(
        self,
        tool: ToolDefinition,
        arguments: dict[str, Any],
        context: Any,
    ) -> Any:
        """Asynchronously execute tool against MCP server endpoint."""
        return self.execute(tool, arguments, context)
