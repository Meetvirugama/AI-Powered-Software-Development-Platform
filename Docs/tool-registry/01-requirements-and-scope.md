# 01 — Requirements and Scope

## 1. Problem Statement
The platform requires a production-grade, extensible, and secure `UnifiedToolRegistry` and routing pipeline capable of serving native workspace tools, local adapters, and future external tool sources (such as Model Context Protocol servers and marketplace plugins) without compromising authorization, sandboxing, or audit integrity.

---

## 2. Functional Requirements

1. **Unified Tool Registry:**
   - Central repository managing tool definitions, versions, and adapters.
   - Support semantic versioning (`major.minor.patch`) with exact and latest version resolution.
   - Prevent name collisions and protect canonical built-in tool names from external impersonation.
   - Dynamic lifecycle control: enable and disable tools without service restarts.

2. **JSON Schema Draft 2020-12 Validation:**
   - Strict argument validation against Draft 2020-12 specifications.
   - Caching of compiled validators to minimize runtime overhead.
   - Input schema validation at tool registration time.
   - Runtime output schema validation to enforce response contracts.

3. **Execution Adapters:**
   - `ToolExecutionAdapter` protocol defining standardized synchronous and asynchronous tool invocation.
   - `BuiltinWorkspaceAdapter` bridging `WorkspaceToolPolicyBridge` and custom callable handlers.
   - Concrete boundary contracts for `MCPToolAdapter` and `PluginToolAdapter`.

4. **Guaranteed Zero-Double-Execution:**
   - Eliminate `TypeError` signature fallback.
   - Inspect signatures explicitly prior to execution. Internal handler errors must fail without retrying.

5. **Sliding-Window Rate Limiting:**
   - Multi-tier rate limiting supporting `task`, `user`, `provider`, and `global` scopes.
   - Atomic Redis Lua script evaluation with in-memory thread-safe fallback.
   - Rate-limited requests must terminate before reaching tool handlers.

6. **Execution Timeouts:**
   - Configurable per-tool timeout limits (`timeout_s`).
   - Normalization of timeout failures into `ToolResult` with `timed_out=True` and `error_category="TIMEOUT_ERROR"`.

7. **Unified Post-Execution Output Boundary:**
   - Common processing flow for all tools: execution -> normalization -> schema validation -> secret redaction -> size bounding -> audit logging.

8. **Extended Invocation Auditing:**
   - Add database columns to `tool_invocations` table: `tool_version`, `tool_source`, `provider_id`, `risk_tier`, `schema_fingerprint`, `execution_timeout_s`, `execution_timed_out`, `rate_limit_status`, and `error_category`.
   - Provide zero-downtime, bidirectional Alembic migrations.

---

## 3. Non-Functional & Security Requirements

- **Security Isolation:** External adapters (MCP, plugins) must never modify core authorization policies or access paths outside the sandbox.
- **Fail-Closed Principle:** Any missing policy engine, context, or schema validation failure must deny execution.
- **Backwards Compatibility:** 100% of existing tests for `ToolRouter`, `WorkspaceToolPolicyBridge`, and `TaskExecutionOrchestrator` must pass without regressions.
- **Performance:** Schema compilation must be cached; in-memory/Redis checks must complete in under 5ms.

---

## 4. Scope Boundaries

### In Scope
- Core `UnifiedToolRegistry` architecture.
- Full `SchemaValidator` with Draft 2020-12 compliance and DoS/SSRF defenses.
- `ToolRateLimiter` with Redis Lua script and memory fallback.
- `BuiltinWorkspaceAdapter` for the 19 canonical workspace tools.
- Interface boundaries for MCP and Plugin adapters.
- Extended database schema and Alembic migration.
- Task orchestration integration.
- Full automated test suites and complete documentation.

### Out of Scope (Future Milestones)
- Live MCP stdio/SSE sub-process lifecycle management.
- External plugin marketplace package download or dynamic package installation.
