
"""Tool definitions and safe routing for agent tools."""

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
    """Standard result returned by the router."""

    success: bool
    output: Any = None
    error: str | None = None


class ToolRouter:
    """Registers tools and validates requests before execution."""

    def __init__(self) -> None:
        self._tools: dict[str, ToolDefinition] = {}
        self._handlers: dict[str, Callable[..., Any]] = {}

    def register(
        self,
        definition: ToolDefinition,
        handler: Callable[..., Any],
    ) -> None:
        """Register a tool and its handler."""

        if not definition.name or not isinstance(definition.name, str):
            raise ValueError("Tool name must be a non-empty string")

        if definition.name in self._tools:
            raise ValueError(f"Tool already registered: {definition.name}")

        if not isinstance(definition.parameters, dict):
            raise ValueError("Tool parameters must be a JSON Schema object")

        if definition.parameters.get("type") != "object":
            raise ValueError("Tool parameter schema must have type 'object'")

        if not callable(handler):
            raise ValueError("Tool handler must be callable")

        self._tools[definition.name] = definition
        self._handlers[definition.name] = handler

    def get_tools(self) -> list[ToolDefinition]:
        """Return registered tool definitions."""

        return list(self._tools.values())

    @staticmethod
    def _matches_type(value: Any, expected: str) -> bool:
        checks = {
            "object": lambda v: isinstance(v, dict),
            "array": lambda v: isinstance(v, list),
            "string": lambda v: isinstance(v, str),
            "integer": lambda v: isinstance(v, int)
            and not isinstance(v, bool),
            "number": lambda v: isinstance(v, (int, float))
            and not isinstance(v, bool),
            "boolean": lambda v: isinstance(v, bool),
            "null": lambda v: v is None,
        }
        check = checks.get(expected)
        return check(value) if check else False

    @classmethod
    def _validate_value(
        cls,
        value: Any,
        schema: dict[str, Any],
        path: str,
    ) -> str | None:
        """Validate a value against supported JSON Schema keywords."""

        if not isinstance(schema, dict):
            return f"Invalid schema at {path}"

        expected = schema.get("type")
        if expected is not None:
            if isinstance(expected, list):
                if not any(cls._matches_type(value, item) for item in expected):
                    return f"{path} has an invalid type"
            elif not isinstance(expected, str) or not cls._matches_type(
                value, expected
            ):
                return f"{path} must be of type {expected}"

        if "enum" in schema and value not in schema["enum"]:
            return f"{path} must be one of {schema['enum']}"

        if isinstance(value, dict):
            properties = schema.get("properties", {})
            required = schema.get("required", [])

            if not isinstance(properties, dict) or not isinstance(required, list):
                return f"Invalid object schema at {path}"

            for key in required:
                if key not in value:
                    return f"Missing required argument: {path}.{key}"

            if schema.get("additionalProperties") is False:
                unexpected = set(value) - set(properties)
                if unexpected:
                    key = sorted(unexpected)[0]
                    return f"Unexpected argument: {path}.{key}"

            for key, item in value.items():
                if key in properties:
                    error = cls._validate_value(
                        item, properties[key], f"{path}.{key}"
                    )
                    if error:
                        return error

        if isinstance(value, list):
            item_schema = schema.get("items")
            if isinstance(item_schema, dict):
                for index, item in enumerate(value):
                    error = cls._validate_value(
                        item, item_schema, f"{path}[{index}]"
                    )
                    if error:
                        return error

            if len(value) < schema.get("minItems", 0):
                return f"{path} has too few items"

            if len(value) > schema.get("maxItems", float("inf")):
                return f"{path} has too many items"

        if isinstance(value, str):
            if len(value) < schema.get("minLength", 0):
                return f"{path} is too short"

            if len(value) > schema.get("maxLength", float("inf")):
                return f"{path} is too long"

        if isinstance(value, (int, float)) and not isinstance(value, bool):
            if "minimum" in schema and value < schema["minimum"]:
                return f"{path} must be at least {schema['minimum']}"

            if "maximum" in schema and value > schema["maximum"]:
                return f"{path} must be at most {schema['maximum']}"

        return None

    @classmethod
    def _validate_arguments(
        cls,
        arguments: dict[str, Any],
        schema: dict[str, Any],
    ) -> str | None:
        """Validate request arguments against the tool's schema."""

        if not isinstance(arguments, dict):
            return "Tool arguments must be an object"

        if schema.get("type") != "object":
            return "Tool parameter schema must declare type 'object'"

        return cls._validate_value(arguments, schema, "arguments")

    def route(
        self,
        request: ToolRequest,
        agent_state: Any,
        policy_engine: Any = None,
    ) -> ToolResult:
        """Route a request to its registered handler after validating arguments."""

        definition = self._tools.get(request.tool_name)
        if definition is None:
            return ToolResult(
                success=False,
                error=f"Unknown tool: {request.tool_name}",
            )

        error = self._validate_arguments(
            request.arguments, definition.parameters
        )
        if error:
            return ToolResult(success=False, error=error)

        handler = self._handlers.get(request.tool_name)
        if handler is not None:
            # Policy-enforced routing: permits execution only when the handler is explicitly policy-guarded
            if getattr(handler, "_is_policy_guarded", False) is True:
                return handler(request, agent_state)

        # Fail closed: never execute a tool before security checks exist.
        return ToolResult(
            success=False,
            error=(
                "Tool execution is not enabled until policy checks "
                "and argument validation are integrated."
            ),
        )

