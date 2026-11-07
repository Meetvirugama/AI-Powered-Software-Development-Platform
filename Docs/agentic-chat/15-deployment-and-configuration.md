# 15 — Deployment and Configuration

## 1. Environment Configuration

All agentic settings are integrated into `Settings` (`backend/app/core/config.py`):

| Variable | Type | Default | Description |
| :--- | :--- | :--- | :--- |
| `AGENTIC_CHAT_ENABLED` | `bool` | `true` | Master feature flag enabling `mode="agentic"` |
| `AGENT_MAX_ROUNDS` | `int` | `3` | Maximum model thought / tool execution rounds per request |
| `AGENT_MAX_TOOL_CALLS` | `int` | `6` | Maximum total tool calls permitted per request |
| `AGENT_MAX_MODEL_CALLS` | `int` | `4` | Maximum model inference invocations per request |
| `AGENT_MAX_PARALLEL_TOOL_CALLS` | `int` | `2` | Maximum concurrent tool executions per turn |
| `AGENT_MAX_INPUT_TOKENS` | `int` | `12000` | Input token ceiling per agent session |
| `AGENT_MAX_OUTPUT_TOKENS` | `int` | `2000` | Completion token ceiling per agent session |
| `AGENT_MAX_REQUEST_SECONDS` | `float` | `35.0` | Maximum overall request duration in seconds |
| `AGENT_TOOL_TIMEOUT_SECONDS` | `float` | `5.0` | Maximum duration allowed for any single tool execution |

---

## 2. Production Deployment Notes

1. **Docker / Container:**
   No additional OS packages or system binaries are required. All tool execution is pure Python / SQL within the container.
2. **Reverse Proxy / Nginx / Azure Web App:**
   Ensure HTTP proxy timeouts are set to at least 45 seconds to accommodate the 35-second agent timeout.
3. **Database Indexes:**
   Ensure PostgreSQL indexes on `code_symbols (repository_id, name)` and `symbol_edges (source_symbol_id, edge_type)` are present.
