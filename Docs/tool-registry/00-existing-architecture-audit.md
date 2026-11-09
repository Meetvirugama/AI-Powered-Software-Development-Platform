# 00 — Existing Architecture Audit

## 1. Executive Summary

This document captures the baseline architectural audit conducted for **F21 — Tool router and tool policy bridge** (GitHub Issue #201). Prior to this milestone, the platform provided tool routing primarily through `backend/agent/tools/router.py` (introduced in Week 3 Day 3) and connected to the isolated workspace sandbox via `backend/sandbox/tool_policy_bridge.py`.

While functional for initial Week 3 deliverables, the system had several architectural limitations that blocked enterprise extensibility, robust schema validation, safe multi-tenant rate limiting, and third-party protocol adapters (such as Model Context Protocol and external plugins).

---

## 2. Inventory of Existing Components

| Component | Path | Responsibility Prior to F21 |
|---|---|---|
| **ToolRouter** | `backend/agent/tools/router.py` | Dict-based tool registration, rudimentary handwritten schema checks, command allowlist verification, PolicyEngine authorization check, output redaction and bounding. |
| **ToolDefinition** | `backend/agent/tools/router.py` | Simple frozen dataclass with `name: str`, `description: str`, `parameters: dict`. Lacked versions, risk tiers, source provenance, rate limits, timeouts, annotations, and output schemas. |
| **WorkspaceToolPolicyBridge** | `backend/sandbox/tool_policy_bridge.py` | Bridge connecting 19 canonical workspace tools (`read_file`, `write_file`, `patch_file`, `delete_file`, `list_files`, `execute_command`, `run_tests`, `commit_task_changes`, `push_task_branch`, `create_draft_pr`, etc.) to the router. Marked with `_is_policy_guarded = True`. |
| **ToolInvocation Model** | `backend/app/models/task.py` | SQLAlchemy model tracking invocations in `tool_invocations` table with only `task_id`, `tool_name`, `sanitized_arguments`, `status`, `duration_ms`, `output_summary`. |
| **TaskRepository** | `backend/app/repositories/task_repository.py` | Database persistence helper `record_tool_invocation(...)`. |
| **TaskExecutionOrchestrator** | `backend/app/services/task_execution_orchestrator.py` | High-level coordinator instantiating `ToolRouter` and executing tools during task workflow. |

---

## 3. Key Architectural Limitations Identified

### 3.1 Hand-Rolled JSON Schema Validation
Prior to F21, `ToolRouter._validate_value` manually checked types and a tiny subset of JSON Schema draft keywords (`type`, `enum`, `properties`, `required`, `additionalProperties`, `minItems`, `maxItems`, `minLength`, `maxLength`, `minimum`, `maximum`). It lacked:
- Support for JSON Schema Draft 2020-12 keywords (`pattern`, `dependentRequired`, `oneOf`, `anyOf`, `allOf`, `prefixItems`).
- Recursion depth bounding, creating Denial of Service (DoS) risks from deeply nested schemas.
- Remote URI `$ref` blocking, creating potential Server-Side Request Forgery (SSRF) vulnerabilities.
- Compilation caching, recalculating schema structures on every invocation.

### 3.2 Double-Execution Hazard via TypeError Catching
In `ToolRouter.route`, execution dispatched using:
```python
try:
    output = handler(**request.arguments)
except TypeError:
    output = handler(request, agent_state)
```
If `handler(**request.arguments)` contained an internal `TypeError` (e.g. attempting `'string' + None` or calling an uncallable object), the router incorrectly interpreted this as a signature mismatch and immediately re-executed `handler(request, agent_state)`. For mutating or destructive operations (`patch_file`, `delete_file`, `commit_changes`), this caused inadvertent duplicate execution.

### 3.3 Asymmetric Output Sanitization Boundary
Handlers marked with `_is_policy_guarded = True` (such as `WorkspaceToolPolicyBridge.execute_tool`) bypassed the router's post-execution output sanitization:
```python
handler = self._handlers.get(request.tool_name)
if handler is not None and getattr(handler, "_is_policy_guarded", False) is True:
    return handler(request, agent_state)
```
Consequently, policy-guarded tools skipped output schema validation and bounding at the router level, relying exclusively on individual handler scrubbing.

### 3.4 Absence of Granular Governance & Rate Limiting
- No sliding-window rate limiting existed on tool execution. A compromised or looping LLM agent could execute excessive filesystem reads or subprocess calls without throttling.
- No execution timeout tracking was persisted in database audit records.
- Tools were unversioned, preventing non-breaking evolution or multi-provider routing.

---

## 4. Canonical Workspace Tools Preserved

All 19 canonical tools managed by `WorkspaceToolPolicyBridge` remain strictly intact and supported:
1. `read_file`
2. `write_file`
3. `patch_file`
4. `delete_file`
5. `list_files`
6. `execute_command`
7. `run_tests`
8. `record_repair_attempt`
9. `inspect_git_diff`
10. `validate_task_diff`
11. `commit_task_changes`
12. `push_task_branch`
13. `create_draft_pr`
14. `recover_workspace`
15. `check_stale_revision`
16. `verify_diff_immutability`
17. `cleanup_orphaned_workspaces`
18. `validate_workspace_invariants`
19. `check_disk_budget`
