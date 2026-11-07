# 08 — Agent Budget and Cost Control

## 1. Budget Architecture & Limits

To prevent model spin, runaway loops, or unexpected billing events, the agentic subsystem strictly enforces multi-dimensional ceilings on every request through `AgentBudget` (`backend/ai/agent/budget.py`).

| Metric | Config Setting | Default Value | Description |
| :--- | :--- | :--- | :--- |
| **Investigation Rounds** | `agentic_chat_max_rounds` | `3` | Maximum model thought / tool execution cycles per request |
| **Tool Invocations** | `agentic_chat_max_tool_calls` | `6` | Total repository tools executed across all rounds |
| **Model Invocations** | `agentic_chat_max_model_calls` | `4` | Maximum model inference requests per user turn |
| **Parallel Tool Calls** | `agentic_chat_max_parallel_tool_calls` | `2` | Maximum concurrent tool executions dispatched in a single round |
| **Input Tokens** | `agentic_chat_max_input_tokens` | `12,000` | Hard cumulative ceiling on prompt tokens sent to provider |
| **Output Tokens** | `agentic_chat_max_output_tokens` | `2,000` | Hard cumulative ceiling on completion tokens generated |
| **Overall Request Timeout** | `agentic_chat_request_timeout_seconds` | `35.0s` | Wall-clock timeout after which the agent loop breaks and finalizes |
| **Per-Tool Timeout** | `agentic_chat_tool_timeout_seconds` | `5.0s` | Maximum time allowed for any single tool database query |
| **Tool Output Cap** | Fixed in policy | `8 KB` | Content exceeding 8 KB is safely truncated with an ellipsis notice |

---

## 2. Duplicate Tool Call Guardrails

Models occasionally loop by submitting identical tool arguments repeatedly. `AgentBudget` maintains a canonical signature of all tool calls:

```python
signature = f"{tool_name}:{json.dumps(arguments, sort_keys=True)}"
```

- **Call 1:** Permitted.
- **Call 2 (Immediate retry):** Permitted (in case an intermittent failure occurred).
- **Call 3+ (Repeated identical call):** Blocked immediately. The orchestrator returns a warning to the model (`"Repeated tool call with identical arguments detected"`) and ceases repeated execution.

---

## 3. Cost-Control Strategy & Free-Tier Guarantees

> [!NOTE]
> API inference may remain within the available free-tier allowance, subject to provider-specific quota and usage restrictions. Exceeding the free allowance may result in throttling or charges depending on provider account settings.

### Mitigation Strategies:
1. **Model Selection:** Free-tier Gemini 2.5 Flash and Groq Llama 3.3 70B Versatile are explicitly targeted.
2. **Context Window Management:** Rather than forwarding raw file contents, tools emit compact, targeted snippets (max 150 lines, max 8 KB).
3. **Structured Usage Logging:** Every agent request logs `agent_metadata` containing exact prompt and completion token counts to facilitate auditing.
