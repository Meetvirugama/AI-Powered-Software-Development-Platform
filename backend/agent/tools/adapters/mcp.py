"""Model Context Protocol (MCP) Tool Execution Adapter Boundary.

Part of F21 — Tool router and tool policy bridge (Issue #201).
Establishes the architectural extension point for connecting external MCP servers
without executing untrusted code or bypassing platform security controls.
"""

from __future__ import annotations

import logging
from typing import Any
from agent.tools.adapters.base import BaseToolAdapter
from agent.tools.models import ToolDefinition

logger = logging.getLogger(__name__)


class MCPToolAdapter(BaseToolAdapter):
    """Architectural boundary adapter for Model Context Protocol (MCP) tool execution.

    In this milestone, defines the schema import, provider identity, and invocation contract.
    External MCP connections are scheduled for a future milestone.
    """

    def __init__(
        self,
        server_id: str,
        server_url: str | None = None,
        auth_token: str | None = None,
    ) -> None:
        self.server_id = server_id
        self.server_url = server_url
        self._auth_token = auth_token

    def execute(
        self,
        tool: ToolDefinition,
        arguments: dict[str, Any],
        context: Any,
    ) -> Any:
        """Execute tool against remote MCP server endpoint (boundary stub)."""
        logger.info("mcp_tool_execution_boundary_invoked", extra={"tool": tool.name, "server": self.server_id})
        raise NotImplementedError(
            f"MCP server execution for '{tool.name}' on server '{self.server_id}' is scheduled for a future milestone."
        )

    async def aexecute(
        self,
        tool: ToolDefinition,
        arguments: dict[str, Any],
        context: Any,
    ) -> Any:
        """Asynchronously execute tool against remote MCP server endpoint (boundary stub)."""
        return self.execute(tool, arguments, context)
