"""Base interface and protocol for Tool Execution Adapters.

Part of F21 — Tool router and tool policy bridge (Issue #201).
Decouples ToolRouter and UnifiedToolRegistry from concrete execution mechanisms.
"""

from __future__ import annotations

import asyncio
from typing import Any, Protocol, runtime_checkable

from agent.tools.models import ToolDefinition


@runtime_checkable
class ToolExecutionAdapter(Protocol):
    """Protocol for adapters executing tools from various sources (Builtin, MCP, Plugins)."""

    def execute(
        self,
        tool: ToolDefinition,
        arguments: dict[str, Any],
        context: Any,
    ) -> Any:
        """Execute tool synchronously with provided arguments and execution context."""
        ...

    async def aexecute(
        self,
        tool: ToolDefinition,
        arguments: dict[str, Any],
        context: Any,
    ) -> Any:
        """Execute tool asynchronously with provided arguments and execution context."""
        ...


class BaseToolAdapter:
    """Convenience base class providing default async/sync bridge for execution adapters."""

    def execute(
        self,
        tool: ToolDefinition,
        arguments: dict[str, Any],
        context: Any,
    ) -> Any:
        """Default synchronous implementation: raises NotImplementedError if not overridden."""
        raise NotImplementedError(f"Synchronous execution not implemented for {self.__class__.__name__}")

    async def aexecute(
        self,
        tool: ToolDefinition,
        arguments: dict[str, Any],
        context: Any,
    ) -> Any:
        """Default asynchronous implementation: delegates synchronous execute in thread pool."""
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self.execute, tool, arguments, context)
