# 07 — Tool Registry and Tool Reference

## 1. Tool Registry Architecture

The `ToolRegistry` (`backend/ai/agent/tool_registry.py`) maintains definitions, schemas, and execution handlers for all registered repository tools. Every tool is guaranteed to be:
1. **Read-Only:** No write operations, state mutations, or external network requests.
2. **Repository-Scoped:** Restricts all queries to the authorized `context.repository_id`.
3. **Budget-Bounded:** Subject to global and turn-level limits enforced by `ToolExecutor`.

---

## 2. Tool 1: `search_code`

- **Purpose:** Semantic and keyword search across indexed repository code chunks.
- **Model Description:** *"Search repository code chunks to find relevant functions, classes, and logic. Input a semantic or keyword query describing the code logic you are investigating."*
- **Argument Schema:**
  ```json
  {
    "type": "object",
    "properties": {
      "query": { "type": "string", "description": "Search query" },
      "top_k": { "type": "integer", "description": "Number of candidates (1-10)", "default": 5 }
    },
    "required": ["query"]
  }
  ```
- **Example Input:** `{"query": "verify_token jwt auth", "top_k": 3}`
- **Example Output:**
  ```json
  {
    "total": 1,
    "results": [
      {
        "file_path": "backend/app/core/auth.py",
        "start_line": 25,
        "end_line": 60,
        "content": "def verify_token(token: str) -> TokenPayload: ...",
        "score": 0.89
      }
    ]
  }
  ```
- **Backend Implementation:** `backend/ai/agent/tools/search_code.py` (`run_search_code`).
- **Existing Service Reused:** `HybridRetriever.retrieve`.
- **Authorization Requirements:** Valid user session with access to the specified repository.
- **Maximum Output:** 8 KB (truncated by `ToolExecutor`).
- **Timeout:** 5.0 seconds.
- **Failure Cases:** Query whitespace-only, retriever offline, DB query timeout.
- **Test Coverage:** `test_agent_tools.py::test_search_code_tool_success`, `test_agent_policy.py::test_validate_search_query_*`.

---

## 3. Tool 2: `read_file_range`

- **Purpose:** Read exact source code lines from a repository file.
- **Model Description:** *"Read a contiguous range of source code lines (up to 150 lines) from a file in the repository."*
- **Argument Schema:**
  ```json
  {
    "type": "object",
    "properties": {
      "file_path": { "type": "string", "description": "Relative file path" },
      "start_line": { "type": "integer", "description": "Start line (1-indexed)", "default": 1 },
      "end_line": { "type": "integer", "description": "End line (inclusive)", "default": 100 }
    },
    "required": ["file_path"]
  }
  ```
- **Example Input:** `{"file_path": "backend/app/main.py", "start_line": 1, "end_line": 50}`
- **Example Output:**
  ```json
  {
    "file_path": "backend/app/main.py",
    "start_line": 1,
    "end_line": 50,
    "lines": "from fastapi import FastAPI\n...",
    "total_lines_read": 50
  }
  ```
- **Backend Implementation:** `backend/ai/agent/tools/read_file_range.py` (`run_read_file_range`).
- **Existing Service Reused:** `reconstruct_file_from_chunks` from `CodeChunk` repository.
- **Authorization Requirements:** Valid user session with access to the repository.
- **Maximum Output:** 8 KB / 150 lines max.
- **Timeout:** 5.0 seconds.
- **Failure Cases:** Path traversal attempted (`../`), absolute path (`/etc/passwd`), line range $>150$, file not found.
- **Test Coverage:** `test_agent_tools.py::test_read_file_range_success`, `test_agent_policy.py::test_sanitize_relative_path_*`, `test_agent_policy.py::test_validate_line_range_*`.

---

## 4. Tool 3: `get_symbol`

- **Purpose:** Retrieve definition, signature, and documentation of a specific code symbol.
- **Model Description:** *"Look up the definition, kind, file location, and signature of a symbol (class, function, method) in the repository."*
- **Argument Schema:**
  ```json
  {
    "type": "object",
    "properties": {
      "name": { "type": "string", "description": "Symbol name" },
      "file_path": { "type": "string", "description": "Optional file path" }
    },
    "required": ["name"]
  }
  ```
- **Example Input:** `{"name": "AgentBudget"}`
- **Example Output:**
  ```json
  {
    "found": true,
    "symbols": [
      {
        "name": "AgentBudget",
        "kind": "class",
        "file_path": "backend/ai/agent/budget.py",
        "start_line": 25,
        "end_line": 140,
        "signature": "class AgentBudget:",
        "docstring": "Central request-level budget tracker for agentic chat."
      }
    ]
  }
  ```
- **Backend Implementation:** `backend/ai/agent/tools/get_symbol.py` (`run_get_symbol`).
- **Existing Service Reused:** Queries `CodeSymbol` and associated `CodeChunk`.
- **Authorization Requirements:** Repository access verified.
- **Maximum Output:** 8 KB.
- **Timeout:** 5.0 seconds.
- **Failure Cases:** Symbol name empty or containing illegal characters, symbol not found.
- **Test Coverage:** `test_agent_tools.py::test_get_symbol_success`, `test_agent_policy.py::test_validate_symbol_name_*`.

---

## 5. Tool 4: `find_callers`

- **Purpose:** Discover functions and methods that call or invoke a specific target symbol.
- **Model Description:** *"Find functions or methods in the repository that call, invoke, or reference a target symbol."*
- **Argument Schema:**
  ```json
  {
    "type": "object",
    "properties": {
      "symbol_name": { "type": "string", "description": "Target symbol name" },
      "file_path": { "type": "string", "description": "Optional file path" }
    },
    "required": ["symbol_name"]
  }
  ```
- **Example Input:** `{"symbol_name": "sanitize_and_redact"}`
- **Example Output:**
  ```json
  {
    "target_symbol": "sanitize_and_redact",
    "total_callers": 2,
    "callers": [
      {
        "caller_name": "execute",
        "caller_file": "backend/ai/agent/tool_executor.py",
        "caller_line": 64,
        "edge_type": "calls"
      }
    ]
  }
  ```
- **Backend Implementation:** `backend/ai/agent/tools/find_callers.py` (`run_find_callers`).
- **Existing Service Reused:** Queries `SymbolEdge` table where `edge_type IN ('calls', 'invokes')`.
- **Authorization Requirements:** Repository access verified.
- **Maximum Output:** 8 KB.
- **Timeout:** 5.0 seconds.
- **Failure Cases:** Empty symbol name, symbol has no recorded edges in the repository graph.
- **Test Coverage:** `test_agent_tools.py::test_find_callers_success`.

---

## 6. Relationship to Unified Tool Registry

While the agentic chat subsystem utilizes dedicated read-only semantic exploration tools (`search_code`, `read_file_range`, `get_symbol`, `find_callers`), all platform-wide tools (including the 19 canonical workspace tools, future MCP servers, and marketplace plugins) are governed by the platform's **`UnifiedToolRegistry`** and **`ToolRouter`** (`backend/agent/tools/`).

For full architectural specifications, execution adapters, Draft 2020-12 schema validation, atomic sliding-window rate limiting, and database audit schemas, refer to the complete documentation suite:
- [Unified Tool Registry Architecture Overview](../tool-registry/README.md)
- [System Architecture](../tool-registry/03-system-architecture.md)
- [Execution Pipeline & Adapters](../tool-registry/06-execution-pipeline.md)
- [Security & Permissions](../tool-registry/07-security-and-permissions.md)

