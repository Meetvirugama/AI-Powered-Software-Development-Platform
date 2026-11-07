# 01 — Requirements and Scope

## 1. Problem Statement

Standard RAG pipelines process questions in a single turn:
1. Retrieve candidate chunks matching the question text.
2. Assemble chunks into prompt context.
3. Query the LLM for a final response.

While effective for direct code questions ("What does function X do in `auth.py`?"), this approach fails when answering complex architectural questions, such as:
- Cross-file dependency chains (e.g., tracing a request handler through middleware, service layer, and database models).
- Call hierarchies (e.g., finding all callers of a deprecated function across multiple packages).
- Ambiguous or partial terminology (where the initial keyword search misses critical files).

To address this, bounded autonomous agent exploration was required to inspect code incrementally.

---

## 2. Goals & In-Scope Deliverables

1. **Normalized LLM Tool-Calling Layer:**
   - Generic schemas (`LLMToolDefinition`, `LLMToolCall`, `LLMToolResult`, `LLMToolRequest`, `LLMToolResponse`).
   - Provider adapters for Google Gemini (`gemini-2.5-flash`) and Groq (`llama-3.3-70b-versatile`).
   - Strict backward compatibility with existing single-turn generation.

2. **Read-Only Repository Tools:**
   - `search_code`: Hybrid vector and keyword chunk retrieval.
   - `read_file_range`: Deterministic line-range reader with 150-line limit and path traversal guard.
   - `get_symbol`: AST symbol definition and documentation lookup.
   - `find_callers`: Symbol caller and callee relationship exploration.

3. **Autonomous Agent Orchestrator:**
   - Multi-round agent loop with baseline retrieval bootstrapping.
   - Request-level budget tracking (rounds, tool calls, model calls, tokens, timeouts).
   - Dynamic secret redaction and 8 KB output truncation.
   - Duplicate tool call detection and mitigation.

4. **API and Frontend UX:**
   - Extended `RepositoryChatRequest` with optional `mode: "normal" | "agentic"`.
   - Default mode remains `"normal"`.
   - Truthful pending activity indicators.
   - Compact metadata badge displaying execution metrics and tool summary.
   - Full cancellation support across route transitions.

---

## 3. Strict Out-of-Scope Boundaries

The following capabilities are explicitly excluded from this feature and prohibited by system policy:
- **Arbitrary Command Execution:** No terminal commands, bash scripts, or subprocesses.
- **File System Modification:** No file writes, edits, deletions, or staging.
- **Git Actions:** No autonomous git commits, branch creation, or pull request creation.
- **External Web Surfing:** No external network scraping or unauthenticated HTTP requests.
- **Paid Inference APIs:** Exclusively bounded to zero-cost / free-tier quotas.
- **Vector Database Migration:** Reuses existing PostgreSQL `pgvector` tables; no new external vector DBs added.
