# 04 — LLM Tool-Calling Integration

## 1. Normalized Tool-Calling Schemas

To avoid coupling the core agent logic to provider-specific wire protocols, the system introduces normalized schemas in `backend/ai/llm/schemas.py`:

```python
class ToolParameterSchema(BaseModel):
    type: str = "object"
    properties: dict[str, Any] = Field(default_factory=dict)
    required: list[str] = Field(default_factory=list)

class LLMToolDefinition(BaseModel):
    name: str
    description: str
    parameters: ToolParameterSchema
    strict: bool | None = None

class LLMToolCall(BaseModel):
    id: str
    name: str
    arguments: dict[str, Any]

class LLMToolResult(BaseModel):
    tool_call_id: str
    tool_name: str
    content: str
    is_error: bool = False

class LLMToolRequest(BaseModel):
    messages: list[Message]
    tools: list[LLMToolDefinition]
    tool_choice: Literal["auto", "none", "required"] | None = "auto"
    temperature: float = 0.2
    max_tokens: int = 1000
    model: str | None = None

class LLMToolResponse(BaseModel):
    content: str | None = None
    tool_calls: list[LLMToolCall] = Field(default_factory=list)
    model: str
    provider: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
```

---

## 2. Backward Compatibility Guarantee

The existing `generate()` method on `LLMProvider` and `LLMGateway` remains completely untouched and is used by normal RAG, code review, explanation, and test generation modules. 

`generate_with_tools()` is an additive method on `LLMProvider` and `LLMGateway`. Existing tests and single-turn completions continue to execute without any schema or payload alterations.

---

## 3. Fallback and Telemetry in `LLMGateway`

`LLMGateway.generate_with_tools` wraps provider calls with:
- Structured logging of latency, token counts, and tool count.
- Automatic fallback: if the primary provider (`gemini`) fails or throws a provider error (e.g. rate limit 429), it builds a fallback tool request and dispatches to the secondary provider (`groq`).
