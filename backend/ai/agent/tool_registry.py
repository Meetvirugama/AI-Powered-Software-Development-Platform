"""
Central Tool Registry (task.md §9).

Registers approved repository investigation tools, maintains their schemas,
and ensures only read-only, validated tools are exposed to language models.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Coroutine
from typing import Any

from ai.agent.errors import AgentToolNotFound, AgentToolValidationError
from ai.agent.schemas import AgentToolContext, AgentToolResult
from ai.agent.tools import (
    FIND_CALLERS_DESC,
    FIND_CALLERS_NAME,
    FIND_CALLERS_PARAMS,
    GET_SYMBOL_DESC,
    GET_SYMBOL_NAME,
    GET_SYMBOL_PARAMS,
    READ_FILE_RANGE_DESC,
    READ_FILE_RANGE_NAME,
    READ_FILE_RANGE_PARAMS,
    SEARCH_CODE_DESC,
    SEARCH_CODE_NAME,
    SEARCH_CODE_PARAMS,
    run_find_callers,
    run_get_symbol,
    run_read_file_range,
    run_search_code,
)
from ai.llm.schemas import LLMToolDefinition

logger = logging.getLogger(__name__)

ToolHandler = Callable[[str, dict[str, Any], AgentToolContext], Coroutine[Any, Any, AgentToolResult]]


class ToolRegistry:
    """
    Central repository of permitted tools for agentic chat.
    """

    def __init__(self) -> None:
        self._handlers: dict[str, ToolHandler] = {}
        self._definitions: dict[str, LLMToolDefinition] = {}

    def register(
        self,
        name: str,
        description: str,
        parameters: dict[str, Any],
        handler: ToolHandler,
        *,
        strict: bool | None = None,
    ) -> None:
        """Register a read-only tool implementation."""
        if not name or not name.strip():
            raise AgentToolValidationError("Tool name cannot be empty.")
        if name in self._handlers:
            raise AgentToolValidationError(f"Tool '{name}' is already registered.")

        # Ensure no write capabilities are accidentally introduced
        forbidden_verbs = ("write", "delete", "create", "execute", "shell", "bash", "eval", "commit")
        if any(verb in name.lower() for verb in forbidden_verbs):
            raise AgentToolValidationError(f"Tool '{name}' violates read-only agent policy.")

        tool_def = LLMToolDefinition(
            name=name,
            description=description,
            parameters=parameters,
            strict=strict,
        )

        self._handlers[name] = handler
        self._definitions[name] = tool_def
        logger.debug("agent_tool_registered", extra={"tool_name": name})

    def get_handler(self, name: str) -> ToolHandler:
        """Retrieve handler for a registered tool."""
        if name not in self._handlers:
            raise AgentToolNotFound(name)
        return self._handlers[name]

    def get_definition(self, name: str) -> LLMToolDefinition:
        """Retrieve definition for a registered tool."""
        if name not in self._definitions:
            raise AgentToolNotFound(name)
        return self._definitions[name]

    def get_definitions(self) -> list[LLMToolDefinition]:
        """Return all registered tool definitions for LLM request building."""
        return list(self._definitions.values())

    def has_tool(self, name: str) -> bool:
        """Check whether a tool is registered."""
        return name in self._handlers


def create_default_registry() -> ToolRegistry:
    """Factory that instantiates and registers the 4 core read-only repository tools."""
    registry = ToolRegistry()

    registry.register(
        name=SEARCH_CODE_NAME,
        description=SEARCH_CODE_DESC,
        parameters=SEARCH_CODE_PARAMS,
        handler=run_search_code,
    )

    registry.register(
        name=READ_FILE_RANGE_NAME,
        description=READ_FILE_RANGE_DESC,
        parameters=READ_FILE_RANGE_PARAMS,
        handler=run_read_file_range,
    )

    registry.register(
        name=GET_SYMBOL_NAME,
        description=GET_SYMBOL_DESC,
        parameters=GET_SYMBOL_PARAMS,
        handler=run_get_symbol,
    )

    registry.register(
        name=FIND_CALLERS_NAME,
        description=FIND_CALLERS_DESC,
        parameters=FIND_CALLERS_PARAMS,
        handler=run_find_callers,
    )

    return registry
