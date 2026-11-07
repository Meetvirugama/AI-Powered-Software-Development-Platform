# 05 — Gemini Provider Integration

## 1. Provider Overview

- **Provider:** Google Gemini
- **Primary Model:** `gemini-2.5-flash`
- **SDK:** `google-genai` (official Google GenAI Python SDK)
- **Model Check Date:** November 2026

> [!NOTE]
> API inference may remain within the available free-tier allowance, subject to provider-specific quota and usage restrictions. Exceeding the free allowance may result in throttling or charges depending on provider account settings.

---

## 2. Function Calling Mapping

The Gemini SDK expects tool declarations as `FunctionDeclaration` objects within a `Tool` list.

### Request Transformation
In `GeminiProvider._build_tool_payload`:
- Each `LLMToolDefinition` is converted into a dictionary matching Gemini's `FunctionDeclaration` format:
  ```json
  {
    "name": "search_code",
    "description": "...",
    "parameters": {
      "type": "OBJECT",
      "properties": {...},
      "required": [...]
    }
  }
  ```
- Tool results from previous rounds are passed into `types.Part.from_function_response` with `name` and `response={"result": ...}`.

### Response Parsing
When Gemini returns candidate parts:
- Text parts are concatenated into `response.content`.
- Function call parts (`part.function_call`) are extracted into `LLMToolCall(id=..., name=..., arguments=...)`.
- Usage metadata (`usage_metadata.prompt_token_count`, `candidates_token_count`) is mapped to normalized token counters.

---

## 3. Error Handling & Rate Limits

- **429 Resource Exhausted:** Caught by `GeminiProvider` and wrapped into `ProviderUnavailableError`.
- `LLMGateway` automatically catches this error and fails over to Groq without crashing the agent session.
