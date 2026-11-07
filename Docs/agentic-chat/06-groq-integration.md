# 06 — Groq Provider Integration

## 1. Provider Overview

- **Provider:** Groq
- **Primary Model:** `llama-3.3-70b-versatile`
- **SDK:** `groq` (official Groq Python SDK)
- **Model Check Date:** November 2026

> [!NOTE]
> API inference may remain within the available free-tier allowance, subject to provider-specific quota and usage restrictions. Exceeding the free allowance may result in throttling or charges depending on provider account settings.

---

## 2. OpenAI-Compatible Tool-Calling Mapping

Groq exposes an OpenAI-compatible function calling API.

### Request Transformation
In `GroqProvider._build_tool_payload`:
- Tools are formatted as:
  ```json
  [
    {
      "type": "function",
      "function": {
        "name": "read_file_range",
        "description": "...",
        "parameters": {...}
      }
    }
  ]
  ```
- Tool result messages are represented with `role: "tool"`, `tool_call_id: "..."`, and `content: "..."`.

### Response Parsing
In `GroqProvider._parse_tool_response`:
- Assistant messages containing `tool_calls` are parsed. Arguments formatted as JSON strings are deserialized safely.
- Usage counters (`response.usage.prompt_tokens`, `response.usage.completion_tokens`) are mapped to `LLMToolResponse`.

---

## 3. Fallback Support

When Gemini experiences rate limits or outages, `LLMGateway` dispatches to Groq. The agent loop is agnostic to the underlying provider and continues seamlessly.
