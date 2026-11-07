# 17 — Future Enhancements

The following roadmap items represent architectural extensions considered for future milestones beyond Issue #188. They are explicitly out of scope for v1.

---

## 1. Candidate Enhancements

### 1.1 Read-Only Model Context Protocol (MCP) Integration
- **Benefits:** Allows the agent to query standard external developer tools and documentation servers.
- **Complexity:** Medium (implementing JSON-RPC client over stdio/SSE).
- **Security Risks:** Outbound network egress, untrusted remote tool schemas.
- **Cost Implications:** Minimal (read-only queries).
- **Dependencies & Prerequisites:** MCP SDK client adapter; sandboxed network transport.

### 1.2 GitHub Issue and Pull Request Context Integration
- **Benefits:** Agent can reference past bug reports, PR review discussions, and commit messages.
- **Complexity:** Medium (syncing GitHub issues into PostgreSQL).
- **Security Risks:** Exposure of private issue comments; rate limit on GitHub API.
- **Cost Implications:** Token usage increase from large issue threads.
- **Dependencies & Prerequisites:** GitHub App installation token management; issue indexing pipeline.

### 1.3 Documentation and Architecture Markdown Search Tools
- **Benefits:** Allows the agent to search `Docs/` or architectural RFCs alongside code.
- **Complexity:** Low (extending `HybridRetriever` filter to markdown files).
- **Security Risks:** Minimal (read-only repository contents).
- **Cost Implications:** Low.
- **Dependencies & Prerequisites:** Parser support for markdown heading chunks.

### 1.4 Deep Symbol Graph Traversal
- **Benefits:** Recursive multi-hop caller/callee path discovery (e.g., call graphs > 1 hop).
- **Complexity:** High (recursive graph queries or graph database backend).
- **Security Risks:** High database load from cyclic or unbounded graph traversals.
- **Cost Implications:** Minimal LLM token impact, moderate database memory usage.
- **Dependencies & Prerequisites:** Graph index optimization on `symbol_edges`.

### 1.5 Sandboxed Read-Only Test Runner Tool
- **Benefits:** Agent could run a targeted test to verify if a suspected bug reproduces.
- **Complexity:** Very High (containerized, network-isolated runner per user).
- **Security Risks:** Critical (remote code execution risk in un-isolated runners).
- **Cost Implications:** Dedicated compute infrastructure costs.
- **Dependencies & Prerequisites:** Docker-in-Docker or Firecracker microVM sandboxing.

### 1.6 User-Approved Patch & PR Creation
- **Benefits:** Bridges chat investigation to autonomous task execution.
- **Complexity:** High (generating unified diffs, running verification suite).
- **Security Risks:** Unreviewed code modifications to production repositories.
- **Cost Implications:** Higher token usage for code generation.
- **Dependencies & Prerequisites:** Human-in-the-loop approval UI; task execution orchestrator.

### 1.7 Server-Sent Events (SSE) Streaming for Agent Activity
- **Benefits:** Live, real-time rendering of tool call events in the browser as they occur.
- **Complexity:** Medium (FastAPI `StreamingResponse` + EventSource adapter in React).
- **Security Risks:** Low (streaming events must redact secrets in real time).
- **Cost Implications:** None.
- **Dependencies & Prerequisites:** Frontend streaming chat adapter.
