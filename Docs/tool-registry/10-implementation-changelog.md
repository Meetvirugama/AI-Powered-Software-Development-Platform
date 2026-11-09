# 10 — Implementation Changelog

## 1. Summary of Changes

This implementation satisfies Issue #201 ("F21 — Tool router and tool policy bridge") by transitioning the tool system from an ad-hoc router into a unified, extensible tool registry architecture.

---

## 2. New Files Created

| Path | Purpose |
| :--- | :--- |
| `backend/agent/tools/models.py` | Data structures: `ToolDefinition`, `ToolAnnotations`, `ToolRateLimit`, `ToolRequest`, `ToolResult`, `ToolRiskTier`, `ToolSource`. |
| `backend/agent/tools/schema_validator.py` | Draft 2020-12 validator with compilation caching, depth limits, property bounds, and remote `$ref` blocking. |
| `backend/agent/tools/registry.py` | `UnifiedToolRegistry` with SemVer resolution, collision prevention, built-in protection, and lifecycle states. |
| `backend/agent/tools/rate_limiter.py` | Multi-tier sliding-window rate limiter with atomic Redis Lua script and thread-safe memory fallback. |
| `backend/agent/tools/adapters/base.py` | `ToolExecutionAdapter` protocol and base class. |
| `backend/agent/tools/adapters/builtin.py` | `BuiltinWorkspaceAdapter` providing safe invocation with signature inspection (zero-retry on `TypeError`). |
| `backend/agent/tools/adapters/mcp.py` | `MCPToolAdapter` interface boundary for Model Context Protocol. |
| `backend/agent/tools/adapters/plugin.py` | `PluginToolAdapter` interface boundary for third-party marketplace plugins. |
| `backend/agent/tools/adapters/__init__.py` | Adapter exports. |
| `backend/migrations/versions/g4d5e6f7a8b9_extend_tool_invocations_audit_fields.py` | Alembic migration for 9 new audit columns on `tool_invocations`. |
| `backend/tests/test_unified_tool_registry.py` | Unit tests for registry operations and lifecycle. |
| `backend/tests/test_schema_validator.py` | Unit tests for schema validation and DoS protection. |
| `backend/tests/test_tool_execution_pipeline.py` | Integration tests for the complete tool execution pipeline. |
| `backend/tests/test_tool_registry_security_and_policies.py` | Comprehensive security and policy enforcement tests. |

---

## 3. Modified Files

| Path | Modifications |
| :--- | :--- |
| `backend/requirements.txt` | Added `jsonschema>=4.23,<5` dependency. |
| `backend/agent/tools/__init__.py` | Exported unified models, registry, validator, rate limiter, and adapters while preserving all legacy exports. |
| `backend/agent/tools/router.py` | Refactored `ToolRouter` to delegate to `UnifiedToolRegistry`, `SchemaValidator`, and `ToolRateLimiter` while maintaining 100% backward-compatible APIs (`register_tool`, `execute_tool`, `tools` dict, command allowlist). |
| `backend/app/models/task.py` | Added `TIMEOUT` and `RATE_LIMITED` to `ToolInvocationStatus`; added 9 new audit columns to `ToolInvocation` and updated `to_dict()`. |
| `backend/app/schemas/task.py` | Added 9 audit fields to `ToolInvocationResponse` schema. |
| `backend/app/repositories/task_repository.py` | Updated `record_tool_invocation` to accept and persist all 9 new audit parameters. |
| `backend/app/services/task_history_service.py` | Propagated audit metadata into task event logs. |
| `backend/app/services/task_execution_orchestrator.py` | Enriched tool execution logging with precise status classification (`TIMEOUT`, `RATE_LIMITED`, `BLOCKED`, `COMPLETED`). |
| `backend/sandbox/tool_policy_bridge.py` | Defined `CANONICAL_TOOL_METADATA` establishing risk tiers, timeouts, and rate limits for all 19 workspace tools. |

---

## 4. Backward Compatibility Guarantee

All existing routes, handlers, and unit tests continue to function without modification:
- `ToolRouter.tools` exposes registered tools as dictionaries matching legacy format (`parameters` alias mapping to `input_schema`).
- Legacy registration methods (`register_tool(name, parameters, handler, description)`) automatically wrap inputs into modern `ToolDefinition` instances.
- Zero breaking changes to existing agent workflows.
