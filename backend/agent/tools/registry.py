"""Unified Tool Registry managing tool metadata, versions, and adapters.

Part of F21 — Tool router and tool policy bridge (Issue #201).
Acts as the single source of truth for tool definitions and execution adapters.
Enforces:
- Schema validation at registration time (Draft 2020-12)
- Collision-safe namespace and version resolution
- Built-in tool identity protection against external spoofing
- Lifecycle management (enabled / disabled)
"""

from __future__ import annotations

from dataclasses import dataclass
import logging
from typing import Any, Callable
import packaging.version

from agent.tools.adapters.base import ToolExecutionAdapter
from agent.tools.models import ToolDefinition
from agent.tools.schema_validator import SchemaValidator, default_schema_validator

logger = logging.getLogger(__name__)

# Protected names that cannot be registered by non-builtin sources
PROTECTED_BUILTIN_TOOL_NAMES: frozenset[str] = frozenset(
    {
        "read_file",
        "write_file",
        "patch_file",
        "delete_file",
        "list_files",
        "execute_command",
        "run_tests",
        "record_repair_attempt",
        "inspect_git_diff",
        "validate_task_diff",
        "commit_task_changes",
        "push_task_branch",
        "create_draft_pr",
        "recover_workspace",
        "check_stale_revision",
        "verify_diff_immutability",
        "cleanup_orphaned_workspaces",
        "validate_workspace_invariants",
        "check_disk_budget",
    }
)


class ToolRegistryError(Exception):
    """Base exception for tool registry operations."""
    pass


class DuplicateToolError(ToolRegistryError):
    """Raised when registering a tool that already exists with the same version."""
    pass


class ToolNotFoundError(ToolRegistryError):
    """Raised when requesting a tool that does not exist."""
    pass


@dataclass(frozen=True)
class RegistryEntry:
    """A registered tool entry containing definition, adapter/handler, and enablement."""

    definition: ToolDefinition
    adapter: ToolExecutionAdapter | None = None
    handler: Callable[..., Any] | None = None
    enabled: bool = True


class UnifiedToolRegistry:
    """Centralized registry for tool definitions, semantic versions, and execution adapters."""

    def __init__(self, schema_validator: SchemaValidator | None = None) -> None:
        self._schema_validator = schema_validator or default_schema_validator
        # Key: tool_name -> dict of version_str -> RegistryEntry
        self._tools: dict[str, dict[str, RegistryEntry]] = {}

    def register(
        self,
        tool: ToolDefinition,
        adapter: ToolExecutionAdapter | None = None,
        handler: Callable[..., Any] | None = None,
        enabled: bool = True,
    ) -> None:
        """Register a validated tool definition and its execution adapter or handler."""
        if not isinstance(tool, ToolDefinition):
            raise ToolRegistryError("tool must be an instance of ToolDefinition")

        if adapter is None and handler is None:
            raise ToolRegistryError("Either adapter or handler must be provided for execution")

        if adapter is not None and not isinstance(adapter, ToolExecutionAdapter):
            raise ToolRegistryError("adapter must implement ToolExecutionAdapter protocol")

        if handler is not None and not callable(handler):
            raise ToolRegistryError("handler must be callable")

        name = tool.name
        version = tool.version
        source = tool.source

        # Protect built-in tool namespace: non-builtin sources cannot impersonate built-in tools
        if name in PROTECTED_BUILTIN_TOOL_NAMES and source != "builtin":
            raise ToolRegistryError(f"Cannot register external tool '{name}' from source '{source}': name is reserved for built-in tools")

        # Validate input schema at registration time
        self._schema_validator.validate_schema_definition(tool.input_schema, is_input=True)

        # Validate output schema if provided
        if tool.output_schema is not None:
            self._schema_validator.validate_schema_definition(tool.output_schema, is_input=False)

        if name not in self._tools:
            self._tools[name] = {}

        if version in self._tools[name]:
            existing_entry = self._tools[name][version]
            raise DuplicateToolError(
                f"Tool '{name}' version '{version}' is already registered with fingerprint {existing_entry.definition.schema_fingerprint}"
            )

        entry = RegistryEntry(
            definition=tool,
            adapter=adapter,
            handler=handler,
            enabled=enabled,
        )
        self._tools[name][version] = entry
        logger.info("tool_registered", extra={"tool": name, "version": version, "source": source, "risk_tier": tool.risk_tier})

    def unregister(self, name: str, version: str | None = None) -> bool:
        """Unregister a tool or specific version. Returns True if removed."""
        if name not in self._tools:
            return False

        if version is not None:
            if version in self._tools[name]:
                del self._tools[name][version]
                if not self._tools[name]:
                    del self._tools[name]
                return True
            return False

        del self._tools[name]
        return True

    def enable_tool(self, name: str, version: str | None = None) -> None:
        """Enable an existing tool."""
        self._set_enabled_status(name, version, True)

    def disable_tool(self, name: str, version: str | None = None) -> None:
        """Disable an existing tool so it cannot be resolved for execution."""
        self._set_enabled_status(name, version, False)

    def _set_enabled_status(self, name: str, version: str | None, status: bool) -> None:
        if name not in self._tools:
            raise ToolNotFoundError(f"Tool '{name}' is not registered")

        if version is not None:
            if version not in self._tools[name]:
                raise ToolNotFoundError(f"Tool '{name}' version '{version}' is not registered")
            entry = self._tools[name][version]
            self._tools[name][version] = RegistryEntry(
                definition=entry.definition,
                adapter=entry.adapter,
                handler=entry.handler,
                enabled=status,
            )
            return

        for ver, entry in list(self._tools[name].items()):
            self._tools[name][ver] = RegistryEntry(
                definition=entry.definition,
                adapter=entry.adapter,
                handler=entry.handler,
                enabled=status,
            )

    def is_enabled(self, name: str, version: str | None = None) -> bool:
        """Check if tool is enabled."""
        entry = self._resolve_entry(name, version)
        if entry is None:
            return False
        return entry.enabled

    def has_tool(self, name: str, version: str | None = None) -> bool:
        """Check whether tool is registered."""
        return self._resolve_entry(name, version) is not None

    def _resolve_entry(
        self,
        name: str,
        version: str | None = None,
    ) -> RegistryEntry | None:
        """Resolve entry by exact version or highest semantic version."""
        if "@" in name and version is None:
            name, version = name.split("@", 1)

        if name not in self._tools or not self._tools[name]:
            return None

        versions_map = self._tools[name]
        if version is not None:
            return versions_map.get(version)

        # Resolve latest semantic version
        try:
            sorted_vers = sorted(versions_map.keys(), key=packaging.version.parse, reverse=True)
            return versions_map[sorted_vers[0]]
        except Exception:
            sorted_vers = sorted(versions_map.keys(), reverse=True)
            return versions_map[sorted_vers[0]]

    def get_entry(self, name: str, version: str | None = None) -> RegistryEntry | None:
        """Retrieve full RegistryEntry by name and optional version."""
        return self._resolve_entry(name, version)

    def get(self, name: str, version: str | None = None) -> ToolDefinition | None:
        """Retrieve ToolDefinition by name and optional version."""
        entry = self._resolve_entry(name, version)
        if entry is None:
            return None
        return entry.definition

    def get_adapter(self, name: str, version: str | None = None) -> ToolExecutionAdapter | None:
        """Retrieve execution adapter for tool by name and optional version."""
        entry = self._resolve_entry(name, version)
        if entry is None:
            return None
        return entry.adapter

    def list_tools(
        self,
        source: str | None = None,
        risk_tier: str | None = None,
        enabled_only: bool = True,
    ) -> list[ToolDefinition]:
        """List registered tools matching optional filters."""
        results: list[ToolDefinition] = []
        for name in sorted(self._tools.keys()):
            for ver, entry in self._tools[name].items():
                if enabled_only and not entry.enabled:
                    continue
                if source is not None and entry.definition.source != source:
                    continue
                if risk_tier is not None and entry.definition.risk_tier != risk_tier:
                    continue
                results.append(entry.definition)
        return results

    def clear(self) -> None:
        """Clear all registered tools (primarily used for test teardown)."""
        self._tools.clear()


# Default singleton registry instance
default_tool_registry = UnifiedToolRegistry()
