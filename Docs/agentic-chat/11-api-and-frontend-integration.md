# 11 — API and Frontend Integration

## 1. REST API Specification

### Endpoint
`POST /api/v1/repositories/{repository_id}/chat`

### Request Payload (`RepositoryChatRequest`)
```json
{
  "question": "How does user token authentication work across the API?",
  "history": [
    { "role": "user", "content": "Hello" },
    { "role": "assistant", "content": "Hi! How can I help with this repository?" }
  ],
  "mode": "agentic"
}
```

- `mode`: `"normal" | "agentic"` (Optional; defaults to `"normal"`).

### Response Payload (`RepositoryAnswer`)
```json
{
  "answer": "User token authentication is handled by `verify_token` in `backend/app/core/auth.py`...",
  "sources": [
    {
      "file": "backend/app/core/auth.py",
      "start_line": 20,
      "end_line": 55,
      "symbol": "verify_token"
    }
  ],
  "confidence": "high",
  "status": "completed",
  "agent_metadata": {
    "mode": "agentic",
    "provider": "gemini",
    "model": "gemini-2.5-flash",
    "model_calls": 2,
    "tool_calls": 3,
    "stop_reason": "completed",
    "total_input_tokens": 4200,
    "total_output_tokens": 380,
    "execution_time_ms": 2150.5,
    "evidence_count": 3
  }
}
```

---

## 2. Frontend User Interface

### 2.1 Mode Selector Toggle
Located in the chat header, the segmented pill allows instant toggling between:
- **Normal Chat:** Fast, 1-shot retrieval. Default mode.
- **Agentic Chat:** Deep autonomous multi-step repository investigation.

### 2.2 Truthful Pending State
When an agentic request is in flight, the UI displays an active investigation banner:
- Pulsing `Sparkles` icon.
- Truthful message: *"Investigating repository code… Running bounded read-only investigation (code search, symbol inspection, caller graphs)."*
- No synthetic or fabricated progress steps are invented.

### 2.3 Agent Metadata Badge
Assistant responses in agentic mode include a compact summary badge:
- `Agentic mode` pill badge.
- Tool call count (`X tool calls`).
- Execution duration (`1.4s`).
- Expandable tool inspection drawer showing the exact tool names (`search_code`, `get_symbol`, `read_file_range`) and target files/symbols without exposing raw hidden chain-of-thought.

### 2.4 Cancellation Behavior
The frontend hooks into `AbortController`:
- Switching repositories immediately aborts in-flight requests.
- Navigating away or clearing conversation resets state without leaking responses.
