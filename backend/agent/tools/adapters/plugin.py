"""External Plugin Tool Execution Adapter Boundary.

Part of F21 — Tool router and tool policy bridge (Issue #201).
Establishes the architectural extension point for third-party plugin providers.
"""

from __future__ import annotations

import logging
from typing import Any
from agent.tools.adapters.base import BaseToolAdapter
from agent.tools.models import ToolDefinition

logger = logging.getLogger(__name__)


class PluginToolAdapter(BaseToolAdapter):
    """Architectural boundary adapter for external plugin tool execution.

    In this milestone, defines provider resolution and error normalization contracts.
    External plugin execution is scheduled for a future milestone.
    """

    def __init__(
        self,
        plugin_id: str,
        provider_name: str,
        config: dict[str, Any] | None = None,
    ) -> None:
        self.plugin_id = plugin_id
        self.provider_name = provider_name
        self.config = config or {}

    def execute(
        self,
        tool: ToolDefinition,
        arguments: dict[str, Any],
        context: Any,
    ) -> Any:
        """Execute tool against external plugin provider (boundary stub)."""
        logger.info("plugin_tool_execution_boundary_invoked", extra={"tool": tool.name, "plugin": self.plugin_id})
        raise NotImplementedError(
            f"Plugin tool execution for '{tool.name}' via plugin '{self.plugin_id}' is scheduled for a future milestone."
        )

    async def aexecute(
        self,
        tool: ToolDefinition,
        arguments: dict[str, Any],
        context: Any,
    ) -> Any:
        """Asynchronously execute tool against external plugin provider (boundary stub)."""
        return self.execute(tool, arguments, context)
