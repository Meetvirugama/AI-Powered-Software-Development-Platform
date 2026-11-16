# Architecture Decisions (current)

Condensed record of decisions that shape the current system. Numbers follow the original ADR series. Where the implementation differs from the original decision text, the **Current state** column states what the code does.

| ADR | Decision | Current state |
|---|---|---|
| 001 | Single `LLMGateway` for all inference | In force (`ai/llm/client.py`) with concurrency semaphore, fallback, telemetry |
| 002 | System/data prompt separation | In force (`PromptBuilder`, context renderers, delimited untrusted data) |
| 003 | PostgreSQL + pgvector instead of a dedicated vector DB | In force; vectors are 768-d Gemini embeddings with HNSW |
| 004 | Hybrid retrieval: vector + lexical → RRF (k=60) → cross-encoder (top 8) | In force, extended by ADR-013 |
| 005 | JWT in httpOnly cookie; frontend never reads the token | In force; refresh tokens added |
| 006 | Vite + React 19 + TypeScript, Zustand, TanStack Query, Tailwind | In force |
| 007 | Isolated execution for agent actions | Implemented as pluggable sandbox backends (local dev / container / runner) |
| 008 | Approved LLM providers: Gemini and Groq only | In force; Groq default model is now `openai/gpt-oss-120b` |
| 009 | Shared `IntelligenceContext` for the four analysis features | In force |
| 010 | Mandatory human approval gate, 3-attempt repair ceiling, draft PR only | In force |
| 011 | PyJWT only, dual trust domains (HS256 platform / RS256 GitHub App), fail-closed Redis, PKCE + atomic OAuth state | In force |
| 012 | Durable webhook table with lease-based workers and dead-letter replay | In force (`max_attempts` default 5) |
| 013 | Multi-stage retrieval with intent routing, code-aware FTS, adaptive HNSW, graph expansion, reranking, generation-keyed cache | In force |
| 014 | Normalised tool calling and bounded read-only agentic chat | In force; limits are 3 rounds / 6 tool calls / 4 model calls / 35 s; tools `search_code`, `read_file_range`, `get_symbol`, `find_callers` |
| 015 | Search/replace edit synthesis with staged validation; durable workflow via DBOS | Edit synthesis in force. Workflow runs in a thread; DBOS is not launched (decorators fall back to native execution) |
| 016 | Embedding profile v2: task types, cAST chunking, contextual headers, L2 normalisation, gated local embeddings | In force |
| 017 | OpenTelemetry tracing with GenAI conventions, fail-safe Langfuse, privacy-by-default | In force, disabled by default |
| 018 | Two-level retrieval cache with index-version invalidation | In force |
| 019 | Batched, concurrent static scanner execution with option-injection defence | In force |
| 020 | Thread/coroutine-safe Redis singletons with bounded pools | In force |
| 021 | Streaming diff parsing with 10 MB cap and early path checks | In force |

The full history of these decisions, including superseded parameters and alternatives considered, is kept outside the repository documentation.
