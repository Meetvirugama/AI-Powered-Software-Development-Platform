# 02 — Research and Design Decisions

## 1. JSON Schema Validation Library Selection

### Research & Options Evaluated
1. **Manual Dictionary Validation (Status Quo):**
   - *Pros:* Zero external dependencies, fast execution for simple schemas.
   - *Cons:* Incomplete schema specification, fragile regexes, cannot validate complex schemas (`oneOf`, `pattern`, `prefixItems`, `dependentRequired`), high maintenance burden.
2. **`pydantic`:**
   - *Pros:* Widely used in FastAPI for request parsing.
   - *Cons:* Designed for static Python type classes rather than dynamic runtime JSON Schema Draft 2020-12 documents; converting dynamic schemas to dynamic Pydantic models incurs significant metaclass overhead.
3. **`fastjsonschema`:**
   - *Pros:* High execution speed via dynamic code generation.
   - *Cons:* Only supports Draft 4 / Draft 7; does not support modern Draft 2020-12 standard used by modern AI tool-calling specifications (MCP, OpenAI, Anthropic).
4. **`jsonschema` (>= 4.23.0) with Draft202012Validator (Chosen):**
   - *Pros:* Official, fully compliant implementation of JSON Schema Draft 2020-12; built-in `FormatChecker`; supports validator precompilation and caching; robust error iteration.
   - *Selected Design:* Use `jsonschema.Draft202012Validator` with a thread-safe LRU compilation cache indexed by SHA-256 schema fingerprint. Add custom pre-compilation AST inspection to bound recursion depth ($\le 10$) and reject remote `$ref` URIs.

---

## 2. Sliding-Window Rate Limiting Architecture

### Distributed vs. In-Memory
- **Challenge:** Multi-worker deployments (Celery/Gunicorn) require shared, atomic counters to prevent rate limit bypass via concurrent requests distributed across worker nodes.
- **Decision:** Implement a Redis sorted set (ZSET) sliding-window algorithm executed via an atomic Lua script (`EVAL`):
  - Key: `tool_ratelimit:{tool_name}:{scope}:{identifier}`
  - Operations in single atomic Lua execution:
    1. Remove expired timestamps: `ZREMRANGEBYSCORE key 0 (now - window)`
    2. Count active events: `ZCARD key`
    3. If `current < limit`: `ZADD key now member` and `EXPIRE key window+1`, return `allowed=1`.
    4. If `current >= limit`: calculate `retry_after = oldest_score + window - now`, return `allowed=0`.
- **Fallback Design:** For unit testing environments or temporary Redis connection failures, a thread-safe in-memory sliding window using Python dictionaries, lists, and `threading.Lock` activates automatically when `fallback_to_memory=True`.

---

## 3. Handler Signature Resolution & Zero-Retry Guarantee

### The Bug in Legacy Routing
Legacy routing caught `TypeError`:
```python
try:
    output = handler(**request.arguments)
except TypeError:
    output = handler(request, agent_state)
```
If `handler` raised a `TypeError` due to an internal bug, the router re-executed `handler(request, agent_state)`, creating double execution.

### Architectural Solution: Upfront Signature Inspection
In `BuiltinWorkspaceAdapter` and `ToolRouter`:
1. Inspect `inspect.signature(handler)` during execution preparation.
2. Determine whether the handler accepts `(request, context)` by:
   - Presence of `_is_policy_guarded = True`.
   - First parameter named `request`, `req`, or `tool_request`.
   - Explicit 2-argument signature without `**kwargs`.
3. Dispatch to the exact signature directly without catching `TypeError` to fallback.
4. Any `TypeError` within the handler execution is caught strictly as a fatal `EXECUTION_ERROR` and logged with full stacktrace, guaranteeing zero repeated executions.

---

## 4. Risk Classification Matrix

To decouple semantic provider hints (like `readOnlyHint`) from platform authorization and auditing, tools are assigned an internal immutable `RiskTier`:

| Risk Tier | Characteristics | Examples | Default Timeout |
|---|---|---|---|
| **low** | Non-mutating, idempotent, read-only queries. | `read_file`, `list_files`, `inspect_git_diff`, `check_disk_budget` | 30s |
| **medium** | Sandbox-confined mutations, test runs, reversible workspace changes. | `write_file`, `patch_file`, `validate_diff`, `run_tests`, `commit_changes` | 30s – 300s |
| **high** | Arbitrary allowlisted command execution, irreversible file deletions. | `execute_command`, `delete_file` | 30s – 120s |
| **critical** | External remote modifications, branch publishing, PR publications. | `push_task_branch`, `create_draft_pr` | 120s |

> [!IMPORTANT]
> External tool metadata provided by MCP servers or plugins cannot downgrade a tool's internal risk tier.
