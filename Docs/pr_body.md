## Summary

Closes #201

This PR evolves the platform's `ToolRouter` into a production-grade **Unified Tool Registry** and **Tool Policy Bridge**, providing a secure, extensible foundation for workspace tools, Model Context Protocol (MCP) servers, and third-party marketplace plugins.

---

## Key Architectural Enhancements

### 1. Rich Metadata & Unified Tool Registry
- **Declarative Tool Contracts (`backend/agent/tools/models.py`, `backend/agent/tools/registry.py`):**
  - Introduced `ToolDefinition` with SemVer versioning (`MAJOR.MINOR.PATCH`), risk tier classification (`READ_ONLY`, `SAFE_WRITE`, `SYSTEM_WRITE`, `DANGEROUS`), MCP-aligned annotations (`read_only_hint`, `destructive_hint`, `idempotent_hint`, `open_world_hint`), per-tool rate limits, and custom execution timeouts.
  - Implemented `UnifiedToolRegistry` featuring semantic version resolution ordering, collision prevention, protected canonical built-in namespaces (`PROTECTED_BUILTIN_TOOL_NAMES`), and runtime lifecycle toggles (`enable_tool`, `disable_tool`, `unregister_tool`).

### 2. Standardized JSON Schema Draft 2020-12 Validation
- **`SchemaValidator` (`backend/agent/tools/schema_validator.py`):**
  - Standardized on JSON Schema Draft 2020-12 using `Draft202012Validator`.
  - Added thread-safe compiled validator caching indexed by SHA-256 schema fingerprint.
  - Enforced DoS and expansion guardrails: nesting depth $\le 10$, property count $\le 200$.
  - Enforced network isolation: blocks remote `$ref` URIs (`http://`, `https://`, `ftp://`, `file://`) to prevent SSRF vulnerabilities.
  - Added post-execution output schema validation.

### 3. Execution Adapters & Zero-Retry Guarantee
- **Adapter Subsystem (`backend/agent/tools/adapters/`):**
  - Created `ToolExecutionAdapter` protocol with `BuiltinWorkspaceAdapter` for the 19 canonical workspace tools.
  - Created clean boundary interfaces for `MCPToolAdapter` and `PluginToolAdapter`.
  - **Eliminated `TypeError` signature guessing:** Inspected function signatures (`inspect.signature`) ahead of time so handler internal errors never trigger duplicate destructive executions.

### 4. Sliding-Window Rate Limiting & Per-Tool Timeouts
- **`ToolRateLimiter` (`backend/agent/tools/rate_limiter.py`):**
  - Atomic sliding-window rate limiting executed via Redis Lua script (`SLIDING_WINDOW_LUA`).
  - Graceful thread-safe in-memory fallback when Redis is unreachable.
  - Multi-tier quota scoping (`task`, `user`, `provider`, `global`). Rate-limited requests are blocked before reaching handlers.
- **Timeout Enforcement:**
  - Invocation tasks are bounded by `asyncio.wait_for(timeout=timeout_s)`.
  - Timed-out requests produce normalized `ToolResult` with `timed_out=True` and `error_category="TIMEOUT_ERROR"`.

### 5. Common Sanitization & Output Boundary
- Outputs pass through a four-stage boundary:
  1. Result normalization into dictionary payloads.
  2. Output schema validation against registered schema.
  3. Sensitive token and secret redaction (`ghp_...`, `sk-...`, API keys, auth headers).
  4. Length truncation (50,000 characters) to prevent LLM context exhaustion.

### 6. Database Schema Extension & Auditing
- **Alembic Migration (`backend/migrations/versions/g4d5e6f7a8b9_extend_tool_invocations_audit_fields.py`):**
  - Added 9 audit columns to `tool_invocations`: `tool_version`, `tool_source`, `provider_id`, `risk_tier`, `schema_fingerprint`, `execution_timeout_s`, `execution_timed_out`, `rate_limit_status`, `error_category`.
  - Added `TIMEOUT` and `RATE_LIMITED` to `ToolInvocationStatus` enum.
  - Updated `ToolInvocation` ORM model, `TaskRepository`, `TaskHistoryService`, and `TaskExecutionOrchestrator` to capture audit logs.

### 7. Documentation Suite
- Created complete documentation suite in `Docs/tool-registry/`:
  - `00-existing-architecture-audit.md`
  - `01-requirements-and-scope.md`
  - `02-research-and-design-decisions.md`
  - `03-system-architecture.md`
  - `04-tool-definition-and-registry.md`
  - `05-schema-validation.md`
  - `06-execution-pipeline.md`
  - `07-security-and-permissions.md`
  - `08-database-and-auditing.md`
  - `09-testing-and-validation.md`
  - `10-implementation-changelog.md`
  - `11-future-mcp-and-plugin-integration.md`
  - `12-operations-and-troubleshooting.md`
  - `README.md`
- Updated `Docs/agentic-chat/07-tool-registry-and-tool-reference.md`.

---

## Testing & Verification

1. **Tool Router, Registry, Validator & Security Suites:**
   ```bash
   PYTHONPATH=backend python3 -m pytest \
       backend/tests/test_tool_router.py \
       backend/tests/test_unified_tool_registry.py \
       backend/tests/test_schema_validator.py \
       backend/tests/test_tool_execution_pipeline.py \
       backend/tests/test_tool_registry_security_and_policies.py -v
   ```
   **Result:** `78 passed in 5.27s` (100% pass rate).

2. **Workspace & Security Tool Regressions:**
   ```bash
   PYTHONPATH=backend python3 -m pytest \
       backend/tests/test_security_w3_tools.py \
       backend/tests/test_prit_w3_d3_workspace_execution.py \
       backend/tests/test_prit_w3_d4_restricted_test_runner.py -v
   ```
   **Result:** `118 passed in 16.38s` (zero regressions).
