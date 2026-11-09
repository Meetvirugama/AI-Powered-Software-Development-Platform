"""Built-in Workspace Tool Execution Adapter.

Part of F21 — Tool router and tool policy bridge (Issue #201).
Connects UnifiedToolRegistry with WorkspaceToolPolicyBridge while maintaining
all workspace isolation, path guard checks, and lifecycle requirements.
"""

from __future__ import annotations

import inspect
import logging
from typing import TYPE_CHECKING, Any, Callable

from agent.tools.adapters.base import BaseToolAdapter
from agent.tools.models import ToolDefinition, ToolRequest, ToolResult

if TYPE_CHECKING:
    from sandbox.tool_policy_bridge import WorkspaceToolPolicyBridge

logger = logging.getLogger(__name__)


class BuiltinWorkspaceAdapter(BaseToolAdapter):
    """Executes trusted built-in workspace tools via WorkspaceToolPolicyBridge."""

    def __init__(
        self,
        policy_bridge: WorkspaceToolPolicyBridge | None = None,
        custom_handlers: dict[str, Callable[..., Any]] | None = None,
    ) -> None:
        self.policy_bridge = policy_bridge
        self._handlers: dict[str, Callable[..., Any]] = custom_handlers or {}

    def register_handler(self, tool_name: str, handler: Callable[..., Any]) -> None:
        """Register a direct callable handler for a built-in tool."""
        if not callable(handler):
            raise ValueError(f"Handler for tool '{tool_name}' must be callable")
        self._handlers[tool_name] = handler

    def execute(
        self,
        tool: ToolDefinition,
        arguments: dict[str, Any],
        context: Any,
    ) -> Any:
        """Execute built-in tool via policy bridge or registered callable handler."""
        tool_name = tool.name

        # If policy bridge is present and owns this workspace tool
        if self.policy_bridge is not None and hasattr(self.policy_bridge, "execute_tool"):
            from sandbox.tool_policy_bridge import CANONICAL_WORKSPACE_TOOLS
            if tool_name in CANONICAL_WORKSPACE_TOOLS:
                req = ToolRequest(tool_name=tool_name, arguments=arguments)
                return self.policy_bridge.execute_tool(req, context)

        # Direct registered handler execution
        handler = self._handlers.get(tool_name)
        if handler is None:
            raise RuntimeError(f"No execution handler registered for built-in tool '{tool_name}'")

        # Explicit signature inspection — eliminates TypeError-based execution retry
        sig = inspect.signature(handler)
        params = list(sig.parameters.values())

        # If handler takes (request, context) or (request, agent_state)
        if len(params) == 2 and not any(p.kind == inspect.Parameter.VAR_KEYWORD for p in params):
            req = ToolRequest(tool_name=tool_name, arguments=arguments)
            return handler(req, context)

        # Otherwise pass keyword arguments directly
        return handler(**arguments)
