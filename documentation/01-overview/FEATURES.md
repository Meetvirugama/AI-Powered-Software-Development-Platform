# Features and Implementation Status

Status was verified against source code at commit `5d0b3ff`. "Partial" items are explained in [Known limitations](../08-reference/KNOWN_LIMITATIONS.md).

## Repository intelligence

| Feature | Status | Where |
|---|---|---|
| GitHub OAuth login (PKCE, state in Redis) and GitHub App installation linking | Implemented | `app/api/v1/auth.py`, `app/api/v1/github.py` |
| Connect repository → sync job → clone → index | Implemented | `app/services/repository_sync.py`, `app/services/sync_worker.py` |
| File walking with ignore rules and language detection | Implemented | `scanner/walker.py`, `scanner/detector.py` |
| tree-sitter parsing for Python, JavaScript, TypeScript, Go, Rust, Java, C, C++ (with CST fallback) | Implemented | `scanner/parser.py` |
| Symbols, imports, dependency edges with provenance/resolution status | Implemented | `scanner/extractor.py`, `scanner/import_tracker.py`, `scanner/graph.py` |
| PageRank-style symbol importance | Implemented | `scanner/symbol_ranker.py` |
| Git co-change coupling for related files | Implemented | `ai/intelligence/co_change.py` |
| Symbol-aware (cAST-style) chunking, content-hash incremental indexing, batched inserts | Implemented | `indexer/chunker.py`, `indexer/incremental.py` |
| Gemini embeddings (768-d, task types, L2-normalised, rate-limited, Redis-cached) | Implemented | `ai/embeddings/*` |
| Optional local embeddings (`nomic-ai/CodeRankEmbed`) | Implemented, off by default (`allow_local_embeddings`) | `ai/embeddings/local_provider.py` |
| Optional SCIP indexing | Implemented as optional runner | `scanner/scip_runner.py` |

## Retrieval and chat

| Feature | Status | Where |
|---|---|---|
| Vector search (pgvector HNSW, adaptive `ef_search` 40/64/120) | Implemented | `ai/retrieval/vector.py` |
| Code-aware lexical search (PostgreSQL FTS on `code_search_text`) | Implemented | `ai/retrieval/lexical.py`, `ai/retrieval/code_tokenizer.py` |
| Query-intent routing and RRF fusion (k=60) | Implemented | `ai/retrieval/fusion.py` |
| 1-hop symbol-graph expansion | Implemented, built from settings at startup | `ai/retrieval/graph_expansion.py`, `app/core/lifespan.py` |
| Cross-encoder reranking (PyTorch or ONNX) | Implemented | `ai/retrieval/reranker*.py` |
| Two-level retrieval cache (local LRU + Redis) with index-version invalidation | Implemented | `ai/retrieval/cache.py` |
| Grounded repository chat with citations | Implemented | `ai/pipeline.py`, `app/api/v1/chat.py` |
| Bounded agentic chat (read-only tools: `search_code`, `read_file_range`, `get_symbol`, `find_callers`) | Implemented | `ai/agent/*` |
| Project memory injected into chat context | Implemented | `app/services/memory_service.py`, `app/api/v1/chat.py` |
| Token streaming of chat answers | **Partial** — the complete answer is published once to the SSE stream after generation | `app/api/v1/chat.py` |
| Server-side conversation history | **Not implemented** — history is sent by the client per request and kept in React state | `frontend/src/hooks/useRepositoryChat.ts` |

## Developer intelligence

| Feature | Status | Where |
|---|---|---|
| Code explanation (file, symbol, line range; summary/detailed/deep levels; related files) | Implemented | `app/services/explanation_orchestrator.py` |
| Bug detection (AST rules, taint analysis, built-in scanners, optional Semgrep/OSV/Gitleaks, LLM investigation, ranking) | Implemented; external scanners used only if installed on the host | `app/services/bug_detection_orchestrator.py`, `scanner/*` |
| Framework-aware test generation (pytest, unittest, Jest, Vitest) with execution verification, coverage, stability (3 runs), mutation scoring | Implemented; execution requires a sandbox backend | `app/services/test_generation_orchestrator.py`, `app/services/test_*` |
| AI code review (file, commit, PR, diff) with static scanners, validation, deduplication, lifecycle, feedback | Implemented | `app/services/code_review_orchestrator.py`, `review/static_reviewer.py` |
| Publish review to a GitHub PR as inline comments | Implemented (opt-in per repository) | `app/services/review_publication_service.py` |
| Analysis history, summaries, JSONL evaluation export, retention purge | Implemented | `app/api/v1/analysis/history.py`, `app/services/analysis_run_history_service.py` |

## Agentic task workflow

| Feature | Status | Where |
|---|---|---|
| Task intake (requirement, prompt, GitHub issue import, finding → task) | Implemented | `app/api/v1/tasks.py`, `app/api/v1/issues.py`, `ai/services/issue_task_adapter.py` |
| LLM planning with hierarchical localisation, completeness check, plan versions | Implemented | `ai/services/task_planner.py`, `ai/services/hierarchical_localizer.py` |
| Human approval gate bound to plan version/hash and base revision | Implemented | `app/repositories/task/approvals.py` |
| Isolated workspace (git worktree), path guard, disk/file budgets | Implemented | `sandbox/workspace_manager.py`, `sandbox/path_guard.py` |
| Policy-enforced tool router (19 workspace tools, risk tiers, rate limits, JSON Schema 2020-12) | Implemented | `agent/tools/*`, `sandbox/tool_policy_bridge.py` |
| Tool approval gate and MCP elicitation | Implemented | `app/services/tool_approval_gate.py`, `app/services/mcp_elicitation_service.py` |
| Edit synthesis (search/replace blocks, 7-stage validation) | Implemented | `ai/services/edit_synthesizer.py` |
| Restricted test runner (JUnit XML, coverage) | Implemented | `sandbox/test_runner.py`, `sandbox/test_reports.py` |
| Bounded self-repair (max 3 attempts, patch-hash dedup, no test-file edits unless planned) | Implemented | `ai/services/bounded_repair_loop.py`, `ai/services/llm_repair_synthesizer.py` |
| Independent verification (diff scope, secrets incl. Gitleaks, requirement verification, LLM-as-judge) | Implemented | `app/services/independent_verifier.py`, `ai/services/requirement_verifier.py` |
| Publication authorisation → host-side push → draft PR | Implemented | `app/repositories/task/publication.py`, `app/services/git_branch.py` |
| Background "durable" workflow | **Partial** — runs in a daemon thread with an in-memory registry; DBOS decorators are present but no DBOS runtime is launched; checkpoints are persisted | `ai/workflows/autonomous_task_workflow.py` |
| Crash recovery (`RECOVERY_REQUIRED` → `/recover`) and startup reconciliation | Implemented | `app/services/task_recovery.py`, `app/core/lifespan.py` |

## Platform

| Feature | Status | Where |
|---|---|---|
| Durable GitHub webhook ingestion (HMAC, dedupe, lease, dead-letter, replay) | Implemented | `app/services/webhook_worker.py`, `app/repositories/webhook_event_repository.py` |
| Push → incremental sync automation; PR → consolidated review (opt-in) | Implemented | `app/services/webhook_handlers.py` |
| Per-user SSE channel with Redis Streams and `Last-Event-ID` | Implemented | `app/api/v1/events.py`, `app/services/sse_redis_streams.py` |
| RBAC (`viewer` < `developer` < `admin`) | Implemented | `app/api/v1/dependencies.py` |
| Tools & MCP admin page | **Partial** — backend registry is an in-memory dict seeded with defaults; registrations are lost on restart and ping does not contact the server | `app/api/v1/mcp_registry.py`, `frontend/src/pages/ToolsIntegrationsAdminPage.tsx` |
| Platform MCP server (JSON-RPC 2.0 dispatcher for tools/resources) | Implemented in-process; used by the MCP tool adapter and registry ping; not exposed as a network endpoint | `app/mcp/server.py`, `agent/tools/adapters/mcp.py` |
| OpenTelemetry tracing/metrics, Langfuse adapter | Implemented, disabled by default | `app/observability/*` |
| AI quality evaluator, benchmark gates, Mini SWE-bench (25 tasks) | Implemented | `ai/evaluation/*`, `.github/workflows/nightly-quality-evaluation.yml` |
