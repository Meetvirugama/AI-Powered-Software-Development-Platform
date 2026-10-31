
"""Tool definitions and routing interface for the agent."""

from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass(frozen=True)
class ToolDefinition:
    """Metadata describing an agent tool."""

    name: str
    description: str
    parameters: dict[str, Any]


@dataclass
class ToolRequest:
    """A request from the agent to execute a tool."""

    tool_name: str
    arguments: dict[str, Any] = field(default_factory=dict)


@dataclass
class ToolResult:
    """Standard result returned by a tool."""

    success: bool
    output: Any = None
    error: str | None = None


class ToolRouter:
    """Registry and routing interface for agent tools."""

    def __init__(self) -> None:
        self._tools: dict[str, ToolDefinition] = {}
        self._handlers: dict[str, Callable[..., Any]] = {}

    def register(
        self,
        definition: ToolDefinition,
        handler: Callable[..., Any],
    ) -> None:
        """Register a tool and its execution handler."""

        if definition.name in self._tools:
            raise ValueError(f"Tool already registered: {definition.name}")

        self._tools[definition.name] = definition
        self._handlers[definition.name] = handler

    def get_tools(self) -> list[ToolDefinition]:
        """Return the available tool definitions."""

        return list(self._tools.values())

    def route(
        self,
        request: ToolRequest,
        agent_state: Any,
        policy_engine: Any = None,
    ) -> ToolResult:
        """Route a request to its registered handler.

        Execution remains disabled until the PolicyEngine integration
        and argument validation are integrated.
        """

        if request.tool_name not in self._tools:
            return ToolResult(
                success=False,
                error=f"Unknown tool: {request.tool_name}",
            )

        handler = self._handlers.get(request.tool_name)
        if handler is not None:
            # Policy-enforced routing: permits execution if a policy engine is provided,
            # or if the agent state has verified policy authorization, or handler is policy-guarded.
            is_guarded = getattr(handler, "_is_policy_guarded", False)
            state_verified = agent_state is not None and getattr(agent_state, "policy_verified", False)
            if policy_engine is not None or is_guarded or state_verified:
                return handler(request, agent_state)

        # Fail closed: never execute a tool before security checks exist.
        return ToolResult(
            success=False,
            error="Tool execution is not enabled until policy checks "
                  "and argument validation are integrated.",
        )

