"""Standardized metadata models and schemas for Unified Tool Registry.

Part of F21 — Tool router and tool policy bridge (Issue #201).
Defines ToolDefinition, ToolAnnotations, ToolRateLimit, ToolRequest, and ToolResult.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
import re
from typing import Any, Literal

_SEMVER_PATTERN = re.compile(r"^(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)(?:-[\da-z\-]+(?:\.[\da-z\-]+)*)?(?:\+[\da-z\-]+(?:\.[\da-z\-]+)*)?$", re.IGNORECASE)
_TOOL_NAME_PATTERN = re.compile(r"^[a-zA-Z0-9_\.\:\-]{1,128}$")

RiskTier = Literal["low", "medium", "high", "critical"]
RateLimitScope = Literal["user", "task", "provider", "global"]


@dataclass(frozen=True)
class ToolAnnotations:
    """MCP-compatible semantic annotations describing tool behavioral hints."""

    read_only_hint: bool = False
    destructive_hint: bool = False
    idempotent_hint: bool = False
    open_world_hint: bool = False

    def to_dict(self) -> dict[str, bool]:
        """Convert annotations to dictionary representation."""
        return {
            "readOnlyHint": self.read_only_hint,
            "destructiveHint": self.destructive_hint,
            "idempotentHint": self.idempotent_hint,
            "openWorldHint": self.open_world_hint,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> ToolAnnotations:
        """Create ToolAnnotations from a dictionary supporting camelCase and snake_case."""
        if not data:
            return cls()
        return cls(
            read_only_hint=bool(data.get("read_only_hint", data.get("readOnlyHint", False))),
            destructive_hint=bool(data.get("destructive_hint", data.get("destructiveHint", False))),
            idempotent_hint=bool(data.get("idempotent_hint", data.get("idempotentHint", False))),
            open_world_hint=bool(data.get("open_world_hint", data.get("openWorldHint", False))),
        )


@dataclass(frozen=True)
class ToolRateLimit:
    """Configurable rate limit rule for a tool."""

    requests: int
    window_seconds: int
    scope: RateLimitScope = "task"

    def __post_init__(self) -> None:
        """Validate rate limit configuration."""
        if self.requests <= 0:
            raise ValueError(f"Rate limit requests must be positive integer, got {self.requests}")
        if self.window_seconds <= 0:
            raise ValueError(f"Rate limit window_seconds must be positive integer, got {self.window_seconds}")
        if self.scope not in ("user", "task", "provider", "global"):
            raise ValueError(f"Invalid rate limit scope '{self.scope}'")

    def to_dict(self) -> dict[str, Any]:
        """Convert rate limit to dictionary representation."""
        return {
            "requests": self.requests,
            "window_seconds": self.window_seconds,
            "scope": self.scope,
        }


def compute_schema_fingerprint(schema: dict[str, Any] | None) -> str:
    """Compute deterministic SHA-256 fingerprint for a JSON schema."""
    if not schema:
        return ""
    canonical = json.dumps(schema, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


@dataclass(frozen=True)
class ToolDefinition:
    """Comprehensive metadata contract describing an agent tool in the Unified Tool Registry."""

    name: str
    description: str
    input_schema: dict[str, Any] = field(default_factory=lambda: {"type": "object"})
    output_schema: dict[str, Any] | None = None
    annotations: ToolAnnotations = field(default_factory=ToolAnnotations)
    risk_tier: RiskTier = "medium"
    version: str = "1.0.0"
    source: str = "builtin"
    timeout_s: float = 30.0
    rate_limit: ToolRateLimit | None = None
    schema_fingerprint: str = field(default="", init=False)

    def __init__(
        self,
        name: str,
        description: str,
        input_schema: dict[str, Any] | None = None,
        parameters: dict[str, Any] | None = None,
        output_schema: dict[str, Any] | None = None,
        annotations: ToolAnnotations | dict[str, Any] | None = None,
        risk_tier: RiskTier = "medium",
        version: str = "1.0.0",
        source: str = "builtin",
        timeout_s: float = 30.0,
        rate_limit: ToolRateLimit | None = None,
    ) -> None:
        """Initialize and validate ToolDefinition supporting both input_schema and legacy parameters."""
        if not name or not isinstance(name, str) or not _TOOL_NAME_PATTERN.match(name.strip()):
            raise ValueError(f"Invalid tool name '{name}'. Must be non-empty matching {_TOOL_NAME_PATTERN.pattern}")

        resolved_schema = input_schema if input_schema is not None else parameters
        if resolved_schema is None or not isinstance(resolved_schema, dict):
            raise ValueError(f"Tool '{name}' must provide an input_schema/parameters dictionary of type 'object'")

        if not _SEMVER_PATTERN.match(version.strip()):
            raise ValueError(f"Tool '{name}' has invalid semantic version '{version}'. Must follow SemVer (e.g. '1.0.0')")

        if risk_tier not in ("low", "medium", "high", "critical"):
            raise ValueError(f"Tool '{name}' has invalid risk_tier '{risk_tier}'. Must be low, medium, high, or critical")

        if timeout_s <= 0:
            raise ValueError(f"Tool '{name}' timeout_s must be positive, got {timeout_s}")

        if not source or not isinstance(source, str):
            raise ValueError(f"Tool '{name}' source must be a non-empty string")

        resolved_annotations = (
            ToolAnnotations.from_dict(annotations)
            if isinstance(annotations, dict)
            else (annotations or ToolAnnotations())
        )

        object.__setattr__(self, "name", name.strip())
        object.__setattr__(self, "description", description or "")
        object.__setattr__(self, "input_schema", resolved_schema)
        object.__setattr__(self, "output_schema", output_schema)
        object.__setattr__(self, "annotations", resolved_annotations)
        object.__setattr__(self, "risk_tier", risk_tier)
        object.__setattr__(self, "version", version.strip())
        object.__setattr__(self, "source", source.strip())
        object.__setattr__(self, "timeout_s", float(timeout_s))
        object.__setattr__(self, "rate_limit", rate_limit)
        object.__setattr__(self, "schema_fingerprint", compute_schema_fingerprint(resolved_schema))

    @property
    def parameters(self) -> dict[str, Any]:
        """Backward-compatibility alias for input_schema."""
        return self.input_schema

    @property
    def qualified_name(self) -> str:
        """Fully qualified identity including version: name@version."""
        return f"{self.name}@{self.version}"

    def to_dict(self) -> dict[str, Any]:
        """Convert ToolDefinition to canonical dictionary representation."""
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.input_schema,
            "parameters": self.input_schema,  # backward compatibility
            "output_schema": self.output_schema,
            "annotations": self.annotations.to_dict(),
            "risk_tier": self.risk_tier,
            "version": self.version,
            "source": self.source,
            "timeout_s": self.timeout_s,
            "rate_limit": self.rate_limit.to_dict() if self.rate_limit else None,
            "schema_fingerprint": self.schema_fingerprint,
        }


@dataclass
class ToolRequest:
    """A validated request to execute a tool with arguments and context."""

    tool_name: str
    arguments: dict[str, Any] = field(default_factory=dict)
    version: str | None = None
    request_id: str | None = None


@dataclass
class ToolResult:
    """Standard result returned from tool execution pipeline."""

    success: bool
    output: Any = None
    error: str | None = None
    error_category: str | None = None  # VALIDATION_ERROR, POLICY_DENIED, TIMEOUT, RATE_LIMITED, EXECUTION_ERROR
    duration_ms: int | None = None
    timed_out: bool = False
    rate_limited: bool = False
