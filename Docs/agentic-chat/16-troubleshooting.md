# 16 — Troubleshooting

## 1. Common Operational Issues

### 1.1 "Agentic chat is currently disabled" (HTTP 400)
- **Cause:** `AGENTIC_CHAT_ENABLED=false` in environment or configuration.
- **Resolution:** Set `AGENTIC_CHAT_ENABLED=true` in `.env` and restart the backend server.

### 1.2 "Repeated tool call to '<tool>' detected"
- **Cause:** The model attempted to execute the exact same tool with identical arguments more than twice.
- **Resolution:** Normal agent behavior. The orchestrator intercepts the loop, injects a warning into the agent's context, and forces finalization to avoid infinite looping.

### 1.3 Primary Provider 429 Rate Limiting
- **Cause:** Gemini free-tier quota momentarily exceeded.
- **Resolution:** The system automatically fails over to Groq. Check structured logs for `llm_gateway_primary_tool_failed_trying_fallback`. If Groq is also rate-limited, the system falls back to baseline RAG retrieval chunks.

### 1.4 Path Traversal Rejected (Validation Error)
- **Cause:** Model attempted to call `read_file_range` with `../` or `/absolute/path`.
- **Resolution:** Expected security behavior. The tool executor intercepts the invalid path, records a tool error, and guides the model to supply a valid repository-relative path.
