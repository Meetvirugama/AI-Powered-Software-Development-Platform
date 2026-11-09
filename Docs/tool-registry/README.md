# Unified Tool Registry Documentation Suite

## 1. Overview

The Unified Tool Registry architecture powers the AI-Powered Software Development Platform's agentic tool execution system. It provides unified tool discovery, Draft 2020-12 schema validation, atomic sliding-window rate limiting, fail-closed policy enforcement, multi-adapter execution (Builtin, MCP, Plugins), and comprehensive audit logging.

---

## 2. Documentation Directory

| Document | Title | Description |
| :--- | :--- | :--- |
| [00 — Existing Architecture Audit](00-existing-architecture-audit.md) | Legacy Architecture Audit | Analysis of the legacy `ToolRouter`, limitations, and security gaps. |
| [01 — Requirements & Scope](01-requirements-and-scope.md) | Requirements & Scope | Functional, security, performance, and compatibility requirements (Issue #201). |
| [02 — Research & Design Decisions](02-research-and-design-decisions.md) | Research & Design Decisions | Decision logs covering SemVer, Draft 2020-12, adapters, Lua rate limiting, and zero-retry on `TypeError`. |
| [03 — System Architecture](03-system-architecture.md) | System Architecture | Architectural diagrams, component structure, data flow, and boundaries. |
| [04 — Tool Definition & Registry](04-tool-definition-and-registry.md) | Tool Definition & Registry | Rich metadata contract, SemVer resolution, collision prevention, built-in namespace defense, and lifecycle. |
| [05 — Schema Validation](05-schema-validation.md) | Schema Validation | Draft 2020-12 validator, SHA-256 fingerprint caching, depth limits, property bounds, and remote `$ref` blocking. |
| [06 — Execution Pipeline & Adapters](06-execution-pipeline.md) | Execution Pipeline & Adapters | 9-stage execution sequence, `ToolExecutionAdapter` protocol, signature inspection, timeouts, and output boundary. |
| [07 — Security & Permissions](07-security-and-permissions.md) | Security, Permissions & Policies | Zero-trust model, PolicyEngine integration, argv metacharacter defense, path traversal guards, and rate limiting. |
| [08 — Database & Auditing](08-database-and-auditing.md) | Database & Auditing | Migration `g4d5e6f7a8b9`, 9 new audit fields, status enums, and API schemas. |
| [09 — Testing & Validation](09-testing-and-validation.md) | Testing & Validation | Testing strategy, baseline preservation (213 tests), new test suites (45 tests), and verification results. |
| [10 — Implementation Changelog](10-implementation-changelog.md) | Implementation Changelog | Detailed list of created and modified files, architectural rationale, and backward compatibility. |
| [11 — Future MCP & Plugin Integration](11-future-mcp-and-plugin-integration.md) | Future MCP & Plugins | Forward-looking design for Model Context Protocol (stdio/SSE) and marketplace plugin containment. |
| [12 — Operations & Troubleshooting](12-operations-and-troubleshooting.md) | Operations & Troubleshooting | Operational runbook, failure codes, Redis key inspection, database migration, and SQL audit queries. |

---

## 3. Quick Start

### Registering a Tool
```python
from agent.tools import ToolDefinition, ToolRiskTier, UnifiedToolRegistry

registry = UnifiedToolRegistry()
definition = ToolDefinition(
    name="sample_tool",
    description="Calculates a hash for a string.",
    input_schema={
        "type": "object",
        "properties": {"data": {"type": "string"}},
        "required": ["data"],
        "additionalProperties": False,
    },
    risk_tier=ToolRiskTier.READ_ONLY,
    timeout_s=10.0,
)

registry.register(definition, handler=lambda data: f"hash:{hash(data)}")
```

### Executing via ToolRouter
```python
from agent.tools import ToolRouter, ToolRequest

router = ToolRouter(registry=registry, policy_engine=policy_engine)
result = await router.execute_tool(
    ToolRequest(
        tool_name="sample_tool",
        arguments={"data": "hello world"},
        context={"workspace_id": "ws-123"},
    )
)
print(result.success, result.output)
```
