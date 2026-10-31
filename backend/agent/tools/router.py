
"""Tool definitions and policy-enforced routing for agent tools."""

from dataclasses import dataclass, field
import json
import math
import re
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
    """Registers tools and authorizes requests before execution."""

    SECRET_PATTERNS = (
        re.compile(
            r"""(?i)(["']?(?:api[_-]?key|access[_-]?token|secret|password)["']?\s*[:=]\s*["']?)([^\s,"';}]+)"""
        ),
        re.compile(r"gh[pousr]_[A-Za-z0-9_]{20,}"),
        re.compile(r"sk-[A-Za-z0-9_-]{20,}"),
    )

    def __init__(
        self,
        policy_engine: Any = None,
        policy_context_factory: Callable[[Any, ToolRequest], Any] | None = None,
        command_allowlist: dict[str, list[list[str]]] | None = None,
        max_output_chars: int = 10000,
    ) -> None:
        self._tools: dict[str, ToolDefinition] = {}
        self._handlers: dict[str, Callable[..., Any]] = {}
        self._policy_engine = policy_engine
        self._policy_context_factory = policy_context_factory
        self._command_allowlist = command_allowlist or {}
        self._max_output_chars = max_output_chars

        if max_output_chars < 1:
            raise ValueError("max_output_chars must be positive")

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
            and not isinstance(v, bool)
            and math.isfinite(v),
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
                if not all(isinstance(item, str) for item in expected):
                    return f"Invalid type declaration at {path}"
                if not any(cls._matches_type(value, item) for item in expected):
                    return f"{path} has an invalid type"
            elif not isinstance(expected, str) or not cls._matches_type(
                value, expected
            ):
                return f"{path} must be of type {expected}"

        if "enum" in schema:
            if not isinstance(schema["enum"], list):
                return f"Invalid enum at {path}"
            if value not in schema["enum"]:
                return f"{path} must be one of {schema['enum']}"

        if isinstance(value, dict):
            properties = schema.get("properties", {})
            required = schema.get("required", [])

            if not isinstance(properties, dict) or not isinstance(required, list):
                return f"Invalid object schema at {path}"

            for key in required:
                if not isinstance(key, str):
                    return f"Invalid required property at {path}"
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
            if item_schema is not None:
                if not isinstance(item_schema, dict):
                    return f"Invalid items schema at {path}"
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
            if not math.isfinite(value):
                return f"{path} must be finite"

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

    def _validate_command(
        self,
        tool_name: str,
        arguments: dict,
    ) -> str | None:
        """Validate argv against exact approved command templates."""

        if "command" in arguments:
            return "Shell command strings are not permitted; use argv"

        if "argv" not in arguments:
            return None

        argv = arguments["argv"]

        if (
            not isinstance(argv, list)
            or not argv
            or not all(isinstance(item, str) and item for item in argv)
        ):
            return "Command argv must be a non-empty list of strings"

        allowed = self._command_allowlist.get(tool_name, [])

        if not allowed:
            return f"No approved command templates for tool: {tool_name}"

        if not any(
            isinstance(template, list) and argv == template
            for template in allowed
        ):
            return "Command is not in the approved command allowlist"

        return None

    def _authorize(
        self,
        request: ToolRequest,
        agent_state: Any,
    ) -> str | None:
        """Call the policy engine. Any missing or failed check denies access."""

        if self._policy_engine is None:
            return "Policy engine unavailable; execution denied"

        if self._policy_context_factory is None:
            return "Policy context unavailable; execution denied"

        try:
            context = self._policy_context_factory(agent_state, request)

            if context is None:
                return "Policy context unavailable; execution denied"

            decision = self._policy_engine.check(
                tool=request.tool_name,
                agent_state=agent_state,
                context=context,
            )

            if decision is None:
                return "Policy returned no decision; execution denied"

            decision_value = getattr(decision, "value", decision)
            decision_name = getattr(decision, "name", decision_value)

            if str(decision_value).upper() == "ALLOW":
                return None

            return f"Policy denied tool execution: {decision_name}"

        except Exception:
            return "Policy evaluation failed; execution denied"

    @classmethod
    def _redact_string(cls, value: str) -> str:
        """Redact common credential patterns from output."""

        result = value

        for index, pattern in enumerate(cls.SECRET_PATTERNS):
            if index == 0:
                result = pattern.sub(r"\1[REDACTED]", result)
            else:
                result = pattern.sub("[REDACTED]", result)

        return result

    def _sanitize_output(self, output: Any) -> Any:
        """Redact secrets and bound the total returned output."""

        try:
            serialized = json.dumps(output, default=str)
        except (TypeError, ValueError):
            serialized = repr(output)

        sanitized = self._redact_string(serialized)

        if len(sanitized) > self._max_output_chars:
            sanitized = (
                sanitized[:self._max_output_chars]
                + "... [OUTPUT TRUNCATED]"
            )

        try:
            return json.loads(sanitized)
        except (json.JSONDecodeError, TypeError):
            return sanitized

    def route(
        self,
        request: ToolRequest,
        agent_state: Any,
        policy_engine: Any = None,
    ) -> ToolResult:
        """Validate, authorize, and execute an approved tool request."""

        if not isinstance(request, ToolRequest):
            return ToolResult(
                success=False,
                error="Invalid tool request",
            )

        definition = self._tools.get(request.tool_name)

        if definition is None:
            return ToolResult(
                success=False,
                error=f"Unknown tool: {request.tool_name}",
            )

        schema = getattr(definition, "parameters", None) or getattr(definition, "schema", {})
        error = self._validate_arguments(
            request.arguments,
            schema,
        )

        if error:
            return ToolResult(success=False, error=error)

        handler = self._handlers.get(request.tool_name)
        if handler is not None and getattr(handler, "_is_policy_guarded", False) is True:
            return handler(request, agent_state)

        error = self._validate_command(
            request.tool_name,
            request.arguments,
        )

        if error:
            return ToolResult(success=False, error=error)

        if policy_engine is not None and self._policy_engine is None:
            self._policy_engine = policy_engine

        error = self._authorize(request, agent_state)

        if error:
            return ToolResult(success=False, error=error)

        if handler is None:
            return ToolResult(
                success=False,
                error=(
                    "Tool execution is not enabled until policy checks "
                    "and argument validation are integrated."
                ),
            )

        try:
            try:
                output = handler(**request.arguments)
            except TypeError:
                output = handler(request, agent_state)

            return ToolResult(
                success=True,
                output=self._sanitize_output(output),
            )

        except Exception:
            return ToolResult(
                success=False,
                error="Tool execution failed",
            )
