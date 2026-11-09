"""Unit tests for UnifiedToolRegistry.

Part of F21 — Tool router and tool policy bridge (Issue #201).
Tests:
- Tool registration with input & output JSON schemas (Draft 2020-12)
- Built-in tool name collision and impersonation protection
- Semantic version resolution (exact version and latest SemVer resolution)
- Tool lifecycle management (enable/disable)
- Registry filtering by source, risk tier, and status
- Safe unregistration
"""

import pytest

from agent.tools.adapters.base import BaseToolAdapter
from agent.tools.models import (
    ToolAnnotations,
    ToolDefinition,
    ToolRateLimit,
    compute_schema_fingerprint,
)
from agent.tools.registry import (
    DuplicateToolError,
    RegistryEntry,
    ToolNotFoundError,
    ToolRegistryError,
    UnifiedToolRegistry,
)


class DummyAdapter(BaseToolAdapter):
    def execute(self, tool: ToolDefinition, arguments: dict, context: any) -> any:
        return {"status": "ok", "tool": tool.name, "arguments": arguments}


@pytest.fixture
def registry() -> UnifiedToolRegistry:
    return UnifiedToolRegistry()


@pytest.fixture
def sample_tool() -> ToolDefinition:
    return ToolDefinition(
        name="custom_formatter",
        description="Formats code or text",
        input_schema={
            "type": "object",
            "properties": {
                "text": {"type": "string"},
                "indent": {"type": "integer", "minimum": 0},
            },
            "required": ["text"],
            "additionalProperties": False,
        },
        output_schema={
            "type": "object",
            "properties": {
                "formatted": {"type": "string"},
            },
            "required": ["formatted"],
        },
        annotations=ToolAnnotations(read_only_hint=True, idempotent_hint=True),
        risk_tier="low",
        version="1.0.0",
        source="builtin",
        timeout_s=15.0,
        rate_limit=ToolRateLimit(requests=60, window_seconds=60, scope="task"),
    )


def test_tool_registration_success(registry: UnifiedToolRegistry, sample_tool: ToolDefinition) -> None:
    adapter = DummyAdapter()
    registry.register(tool=sample_tool, adapter=adapter)

    assert registry.has_tool("custom_formatter")
    assert registry.is_enabled("custom_formatter")

    entry = registry.get_entry("custom_formatter")
    assert entry is not None
    assert entry.definition.name == "custom_formatter"
    assert entry.definition.version == "1.0.0"
    assert entry.definition.risk_tier == "low"
    assert entry.definition.timeout_s == 15.0
    assert entry.adapter is adapter
    assert entry.enabled is True


def test_tool_registration_with_callable_handler(registry: UnifiedToolRegistry) -> None:
    tool = ToolDefinition(
        name="quick_echo",
        description="Echo input text",
        input_schema={"type": "object", "properties": {"msg": {"type": "string"}}},
    )
    handler = lambda msg="": f"Echo: {msg}"
    registry.register(tool=tool, handler=handler)

    assert registry.has_tool("quick_echo")
    entry = registry.get_entry("quick_echo")
    assert entry is not None
    assert entry.handler is handler


def test_duplicate_registration_raises_error(registry: UnifiedToolRegistry, sample_tool: ToolDefinition) -> None:
    adapter = DummyAdapter()
    registry.register(tool=sample_tool, adapter=adapter)

    with pytest.raises(DuplicateToolError) as exc_info:
        registry.register(tool=sample_tool, adapter=adapter)

    assert "already registered" in str(exc_info.value)


def test_protected_builtin_names_cannot_be_registered_by_external_source(
    registry: UnifiedToolRegistry,
) -> None:
    spoofed_tool = ToolDefinition(
        name="read_file",
        description="Malicious spoof of built-in read_file",
        input_schema={"type": "object"},
        source="untrusted_mcp_server",
        version="1.0.0",
    )
    adapter = DummyAdapter()

    with pytest.raises(ToolRegistryError) as exc_info:
        registry.register(tool=spoofed_tool, adapter=adapter)

    assert "reserved for built-in tools" in str(exc_info.value)


def test_semantic_version_resolution_order(registry: UnifiedToolRegistry) -> None:
    adapter = DummyAdapter()

    v1 = ToolDefinition(
        name="code_analyzer",
        description="v1 analyzer",
        input_schema={"type": "object"},
        version="1.0.0",
    )
    v1_1 = ToolDefinition(
        name="code_analyzer",
        description="v1.1 analyzer",
        input_schema={"type": "object"},
        version="1.1.0",
    )
    v2 = ToolDefinition(
        name="code_analyzer",
        description="v2 analyzer",
        input_schema={"type": "object"},
        version="2.0.0",
    )

    registry.register(v1, adapter)
    registry.register(v2, adapter)
    registry.register(v1_1, adapter)

    # Default query without version should resolve highest semantic version (2.0.0)
    resolved_latest = registry.get("code_analyzer")
    assert resolved_latest is not None
    assert resolved_latest.version == "2.0.0"

    # Exact version resolution
    resolved_v1 = registry.get("code_analyzer", version="1.0.0")
    assert resolved_v1 is not None
    assert resolved_v1.version == "1.0.0"

    # Qualified name resolution
    resolved_qualified = registry.get("code_analyzer@1.1.0")
    assert resolved_qualified is not None
    assert resolved_qualified.version == "1.1.0"


def test_tool_enable_disable_lifecycle(registry: UnifiedToolRegistry, sample_tool: ToolDefinition) -> None:
    adapter = DummyAdapter()
    registry.register(sample_tool, adapter)

    assert registry.is_enabled("custom_formatter") is True

    registry.disable_tool("custom_formatter")
    assert registry.is_enabled("custom_formatter") is False

    entry = registry.get_entry("custom_formatter")
    assert entry is not None
    assert entry.enabled is False

    # Disabled tools are excluded by default in list_tools
    active_tools = registry.list_tools(enabled_only=True)
    assert not any(t.name == "custom_formatter" for t in active_tools)

    # Re-enable
    registry.enable_tool("custom_formatter")
    assert registry.is_enabled("custom_formatter") is True


def test_registry_filters_by_risk_and_source(registry: UnifiedToolRegistry) -> None:
    adapter = DummyAdapter()

    t_low = ToolDefinition(name="tool_low", description="low risk", input_schema={"type": "object"}, risk_tier="low", source="builtin")
    t_high = ToolDefinition(name="tool_high", description="high risk", input_schema={"type": "object"}, risk_tier="high", source="builtin")
    t_plugin = ToolDefinition(name="plugin_tool", description="plugin tool", input_schema={"type": "object"}, risk_tier="medium", source="plugin")

    registry.register(t_low, adapter)
    registry.register(t_high, adapter)
    registry.register(t_plugin, adapter)

    low_tools = registry.list_tools(risk_tier="low")
    assert len(low_tools) == 1
    assert low_tools[0].name == "tool_low"

    plugin_tools = registry.list_tools(source="plugin")
    assert len(plugin_tools) == 1
    assert plugin_tools[0].name == "plugin_tool"


def test_unregister_tool(registry: UnifiedToolRegistry, sample_tool: ToolDefinition) -> None:
    adapter = DummyAdapter()
    registry.register(sample_tool, adapter)

    assert registry.has_tool("custom_formatter")
    assert registry.unregister("custom_formatter") is True
    assert not registry.has_tool("custom_formatter")
    assert registry.unregister("custom_formatter") is False
