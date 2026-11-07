# 03 — Agent Execution Flow

## 1. Sequence Diagram

```mermaid
sequenceDiagram
    autonumber
    actor User as User / Frontend
    participant API as Chat API (/chat)
    participant Orch as AgentOrchestrator
    participant State as AgentState / Budget
    participant Gateway as LLMGateway
    participant LLM as LLM Provider (Gemini / Groq)
    participant Exec as ToolExecutor
    participant Tools as Repository Tools
    participant RAG as RAGPipeline (Finalize)

    User->>API: POST /chat (question, mode="agentic")
    API->>Orch: run(question, repository_id)
    Orch->>State: initialize(request_id, budget)
    
    rect rgb(240, 248, 255)
        Note over Orch,RAG: Step 1: Baseline Retrieval
        Orch->>RAG: _retrieve(question, repo_id)
        RAG-->>Orch: initial_chunks
        Orch->>State: add_evidence(initial_chunks)
    end

    loop Investigation Rounds (1 to 3)
        Orch->>State: check budget.can_continue()
        alt Budget exhausted
            Note over Orch: Break loop
        end
        Orch->>State: start_round()
        Orch->>Gateway: generate_with_tools(messages, tool_definitions)
        Gateway->>LLM: API Call with Function Declarations
        LLM-->>Gateway: Response (content, tool_calls)
        Gateway-->>Orch: LLMToolResponse
        Orch->>State: record_model_call(input_tokens, output_tokens)

        alt No tool calls requested (Model is ready)
            Note over Orch: Model completed investigation
        else Tool calls returned
            loop For each tool call (max 2 parallel)
                Orch->>State: record_tool_call(name, args)
                alt Duplicate signature detected (>2 calls)
                    Orch->>State: append repeated call warning
                else Normal execution
                    Orch->>Exec: execute(tool_call, context)
                    Exec->>Tools: run_tool(args, db_session)
                    Tools-->>Exec: Raw results & evidence
                    Exec->>Exec: sanitize_and_redact() & truncate(8KB)
                    Exec-->>Orch: AgentToolResult
                    Orch->>State: add_evidence(tool_evidence)
                    Orch->>State: append Message.tool_result()
                end
            end
        end
    end

    rect rgb(245, 255, 245)
        Note over Orch,RAG: Step 2: Unified RAG Finalization & Grounding
        Orch->>RAG: finalize_agent_chat(question, deduplicated_evidence, history)
        RAG->>RAG: ContextBuilder -> PromptBuilder -> LLM Answer
        RAG->>RAG: GroundingValidator (check citations against evidence)
        RAG-->>Orch: RepositoryAnswer (with sources & confidence)
    end

    Orch->>API: RepositoryAnswer + agent_metadata
    API-->>User: HTTP 200 OK
```

---

## 2. Step-by-Step Flow Description

1. **Bootstrap Phase:**
   When a user submits an agentic query, the orchestrator first runs an initial vector search using the platform's `HybridRetriever`. This ensures that even before making its first tool decision, the agent has candidate files to anchor its thought process.

2. **Investigation Loop (Rounds 1–3):**
   - The orchestrator formats the prompt and provides the 4 JSON Schemas.
   - The model inspects the current state and either requests tool invocations or emits a final synthesized thought.
   - Up to 2 tool calls are dispatched per round.
   - Every tool execution is isolated, timed out at 5.0 seconds, stripped of credentials, and capped at 8 KB.

3. **Termination Conditions:**
   The loop terminates as soon as any of the following occur:
   - The model makes no tool calls (declares investigation finished).
   - Maximum 3 rounds reached.
   - Maximum 6 tool calls reached.
   - Maximum 4 model calls reached.
   - Token budget (12,000 input / 2,000 output) exceeded.
   - Request timeout (35.0 seconds) exceeded.
   - Duplicate tool invocation detected.

4. **Finalization Phase:**
   All gathered evidence items are converted into `CodeChunk` representations, deduplicated, and passed through `RAGPipeline.finalize_agent_chat`. This guarantees that the final answer is validated against actual repository code lines by `GroundingValidator`.
