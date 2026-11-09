# 12 — Operations & Troubleshooting Guide

## 1. Overview

This guide provides operational runbooks, failure mode diagnostics, and troubleshooting procedures for the Unified Tool Registry and Execution Pipeline.

---

## 2. Common Failure Modes & Diagnostic Codes

| Error Category | HTTP / Status | Root Cause | Resolution |
| :--- | :--- | :--- | :--- |
| `NOT_FOUND` | `404` / `BLOCKED` | Tool name or version not registered, or tool is currently disabled. | Verify tool spelling with `registry.list_tools()`. Check `registry.get_tool(name).enabled`. |
| `INVALID_ARGUMENTS` | `422` / `FAILED` | Tool arguments violate Draft 2020-12 input schema. | Inspect error details for missing required fields or type mismatches. Compare against schema definition. |
| `RATE_LIMITED` | `429` / `RATE_LIMITED`| Sliding-window quota exceeded for tool or user scope. | Wait for the `retry_after` window, or adjust `ToolRateLimit.requests` / `window_seconds`. |
| `TIMEOUT_ERROR` | `504` / `TIMEOUT` | Handler execution exceeded configured `timeout_s`. | Check network/IO bottlenecks or subprocess hanging. Increase `timeout_s` if legitimate heavy workload. |
| `SECURITY_BLOCKED` | `403` / `BLOCKED` | Policy engine returned `DENY`, or shell metacharacters/dangerous flags detected. | Review policy logs in `tool_invocations`. Ensure commands are split into structured `argv` arrays without shell metacharacters. |
| `SYSTEM_ERROR` | `500` / `FAILED` | Unhandled exception inside adapter or output schema mismatch. | Inspect backend stack traces. Verify handler return structure matches registered `output_schema`. |

---

## 3. Database Migration Runbook

To apply the latest database schema updates including the new audit columns:

```bash
# Verify current migration status
alembic current

# Apply upgrade to head (includes g4d5e6f7a8b9)
alembic upgrade head

# If needed, rollback
alembic downgrade -1
```

---

## 4. Redis Rate Limiter Operations

The rate limiter connects to Redis using the platform's standard Redis pool.

### 4.1 Key Inspection
Rate limiting keys follow the convention:
```text
ratelimit:tool:{tool_name}:{scope}:{scope_id}
```
Example:
```text
ratelimit:tool:run_command:task:c653b591-408e-4674-93e6-2af06b0c9d1a
```

To inspect active invocation timestamps in Redis CLI:
```bash
redis-cli ZRANGEBYSCORE ratelimit:tool:run_command:task:12345 0 +inf WITHSCORES
```

### 4.2 Fallback Diagnostics
If Redis is down or unreachable:
- The rate limiter logs a warning: `Redis unavailable for rate limiting. Falling back to in-memory limiter.`
- Execution **does not fail**; in-memory sliding window tracking takes over immediately per worker process.

---

## 5. Structured Audit Log Analysis

Query recent failed or timed-out tool invocations directly in PostgreSQL:

```sql
SELECT 
    id,
    task_id,
    tool_name,
    tool_version,
    tool_source,
    risk_tier,
    status,
    error_category,
    execution_timeout_s,
    execution_timed_out,
    created_at
FROM tool_invocations
WHERE status IN ('failed', 'timeout', 'rate_limited', 'blocked')
ORDER BY created_at DESC
LIMIT 50;
```
