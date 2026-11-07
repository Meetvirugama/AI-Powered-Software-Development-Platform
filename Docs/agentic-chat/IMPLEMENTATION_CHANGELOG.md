# Implementation Changelog: Bounded Agentic Repository Chat

All changes implemented for GitHub Issue #188 (F08) across backend, frontend, tests, and documentation.

---

## 1. Backend Architecture Changes

### 1.1 LLM Tool-Calling Layer (`backend/ai/llm/`)
- **`backend/ai/llm/schemas.py`:** Added normalized schemas (`ToolParameterSchema`, `LLMToolDefinition`, `LLMToolCall`, `LLMToolResult`, `LLMToolRequest`, `LLMToolResponse`). Extended `Message` with optional `tool_calls`, `tool_call_id`, `name`, and helper constructor `Message.tool_result()`.
- **`backend/ai/llm/__init__.py`:** Exported normalized tool schemas.
- **`backend/ai/llm/provider.py`:** Added abstract/default `generate_with_tools` method to `LLMProvider`.
- **`backend/ai/llm/client.py`:** Added `generate_with_tools` and fallback adapter `_build_fallback_tool_request` to `LLMGateway`.
- **`backend/ai/llm/gemini_provider.py`:** Added `_build_tool_payload` and implemented `generate_with_tools` converting to Gemini `FunctionDeclaration` and `types.Part.from_function_response`.
- **`backend/ai/llm/groq_provider.py`:** Added `_build_tool_payload`, `_parse_tool_response`, and implemented `generate_with_tools` converting to OpenAI-compatible `tools` array.

### 1.2 Agent Subsystem (`backend/ai/agent/`)
- **`schemas.py`:** Created `AgentEvidenceItem` (with `to_code_chunk()` conversion), `AgentToolContext`, `AgentToolCall`, `AgentToolResult`, `AgentActivityEvent`.
- **`errors.py`:** Created agent domain exceptions (`AgentBudgetExceeded`, `AgentToolNotFound`, `AgentToolValidationError`, `AgentToolExecutionError`).
- **`policy.py`:** Created security policies: `sanitize_relative_path`, `validate_line_range` (max 150 lines), `validate_search_query`, `validate_symbol_name`, `truncate_tool_output` (8 KB), and `sanitize_and_redact` (secret redactor).
- **`db.py`:** Implemented universal `run_db_query` runner supporting async sessionmaker, active AsyncSession, and sync Session.
- **`tools/search_code.py`:** Implemented hybrid code search tool.
- **`tools/read_file_range.py`:** Implemented line-range reader using file chunk reconstruction.
- **`tools/get_symbol.py`:** Implemented AST symbol definition lookup.
- **`tools/find_callers.py`:** Implemented caller edge lookup via `SymbolEdge`.
- **`tool_registry.py`:** Implemented `ToolRegistry` with read-only validation and `create_default_registry()`.
- **`tool_executor.py`:** Implemented `ToolExecutor` with 5s timeout, 8 KB truncation, and secret redaction.
- **`budget.py`:** Implemented `AgentBudget` tracking rounds, tool calls, model calls, tokens, timeouts, and duplicate call signatures.
- **`state.py`:** Implemented `AgentState` for tracking messages, evidence, and activity events.
- **`orchestrator.py`:** Implemented `AgentOrchestrator` multi-round loop, baseline retrieval bootstrapping, and evidence synthesis.
- **`benchmark.py`:** Implemented 35-case benchmark evaluation suite across 7 categories.

### 1.3 RAG Integration (`backend/ai/`)
- **`backend/ai/schemas/output.py` & `backend/ai/schemas/grounding.py`:** Added optional `agent_metadata: dict[str, Any] | None` to `RepositoryAnswer` and preserved it during grounding.
- **`backend/ai/pipeline.py`:** Added `finalize_agent_chat` to `RAGPipeline` (reuses `ContextBuilder`, `PromptBuilder`, `GroundingValidator`, secret redaction).

### 1.4 API Routing & Lifespan (`backend/app/`)
- **`backend/app/schemas/repository.py`:** Extended `RepositoryChatRequest` with `mode: Literal["normal", "agentic"] = "normal"`.
- **`backend/app/core/config.py`:** Added `agentic_chat_*` configuration settings; exported `get_settings()` and `settings`.
- **`backend/app/core/lifespan.py`:** Initialized `agent_orchestrator` and attached to `app.state.agent_orchestrator`.
- **`backend/app/api/v1/chat.py`:** Updated `repository_chat` endpoint to dispatch `mode="agentic"` to `AgentOrchestrator` while routing `mode="normal"` to standard RAG.

---

## 2. Frontend Changes (`frontend/src/`)

- **`types/api.ts`:**
  - Added `ChatMode = 'normal' | 'agentic'`.
  - Added `AgentToolActivity` and `AgentMetadata` interfaces.
  - Extended `RepositoryChatRequest` with `mode?: ChatMode`.
  - Extended `RepositoryChatResponse` with `agent_metadata?: AgentMetadata | null`.
  - Extended `ChatMessage` with `mode?: ChatMode` and `agentMetadata?: AgentMetadata | null`.
- **`hooks/useRepositoryChat.ts`:**
  - Added `mode` state (defaulting to `'normal'`) and `setMode`.
  - Updated `sendMessage` to pass `mode` to `askRepositoryQuestion`.
  - Attached `agent_metadata` to assistant message state upon response.
- **`pages/RepositoryChat.tsx`:**
  - Added Mode Selector segmented toggle in header ("Normal Chat" vs "Agentic Chat").
  - Added truthful pending state for agentic investigation.
  - Added `AgentMetadataBadge` displaying execution pill, tool call count, duration, and expandable tool list.
  - Safely handled `scrollIntoView?.()`.

---

## 3. Test Suites Added

- `backend/tests/test_llm_tool_calling.py` (10 tests)
- `backend/tests/test_agent_policy.py` (23 tests)
- `backend/tests/test_agent_tools.py` (8 tests)
- `backend/tests/test_agent_orchestrator.py` (4 tests)
- `backend/tests/test_agent_chat_api.py` (5 tests)
- `backend/tests/test_agent_security_and_budget.py` (6 tests)
- `backend/tests/test_agent_benchmark.py` (2 tests)
- `frontend/src/test/agenticChat.test.tsx` (3 tests)
