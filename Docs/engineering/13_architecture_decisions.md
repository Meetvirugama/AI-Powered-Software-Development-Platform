# 13. Architecture Decision Records
> **Version:** 4.0 | **Created:** 2026-09-24 | **Last Updated:** 2026-11-08

---

## ADR-001: Single LLM Gateway Pattern

| Field | Value |
|---|---|
| **Title** | All LLM calls route through a single LLMGateway |
| **Date** | 2026-09-24 |
| **Status** | Accepted |
| **Owner** | Meet |

**Context:**
Multiple features (chat, agent planner, code review, verification, output repair) all need to call an LLM. Without centralization, each would implement its own retry, logging, and error handling differently.

**Problem:**
How do we ensure consistent retry behavior, structured logging, and token tracking across every LLM call in the system?

**Options Considered:**
1. Each module calls the OpenAI SDK directly
2. Single centralized gateway that all modules use
3. Per-feature LLM wrapper classes

**Decision:**
Option 2 — `LLMGateway` in `backend/ai/llm/client.py` is the single entry point.

**Reason:**
- Consistent logging: model, tokens, latency, success/failure on every call
- Single place to add/modify retry policy
- Providers are injectable → testable without real API keys
- Future provider swap (OpenAI → Anthropic) requires changing only one class

**Trade-offs:**
- Adds an indirection layer
- All callers must depend on `LLMGateway` (enforced by `team_rules.md`)

**Consequences:**
- `team_rules.md` rule: "The LLM Gateway is the ONLY place in the codebase that calls an LLM API."
- `OpenAIProvider` handles retry/timeout; `LLMGateway` handles logging
- Adding new providers requires implementing `LLMProvider` abstract class only

**Related Components:**
[`client.py`](file:///Users/meetvirugama/Desktop/AI-Powered-Software-Development-Platform/backend/ai/llm/client.py), [`provider.py`](file:///Users/meetvirugama/Desktop/AI-Powered-Software-Development-Platform/backend/ai/llm/provider.py), [`openai_provider.py`](file:///Users/meetvirugama/Desktop/AI-Powered-Software-Development-Platform/backend/ai/llm/openai_provider.py)

---

## ADR-002: System/Data Prompt Separation

| Field | Value |
|---|---|
| **Title** | Repository content is always DATA — never in the system prompt |
| **Date** | 2026-09-24 |
| **Status** | Accepted |
| **Owner** | Dev |

**Context:**
The system processes untrusted repository content (code from user repositories). If this content were placed in the system prompt, it could override the AI's instructions (prompt injection).

**Problem:**
How do we prevent repository content from being used as a prompt injection vector?

**Options Considered:**
1. Place repository content in the system prompt for context
2. Strict separation: system message = instructions only; user message = repository data + question
3. Sanitize repository content before including it anywhere

**Decision:**
Option 2 — `PromptBuilder` enforces: system message = instructions only, user message = `REPOSITORY DATA:` section + question.

**Reason:**
- If an attacker embeds `IGNORE ALL PREVIOUS INSTRUCTIONS` in their repo, the LLM sees it as user data, not as a system command
- Clear audit trail: system prompt never changes at runtime
- Every prompt change is reviewed by Dev before merging

**Trade-offs:**
- Slightly longer prompts (labeled sections)
- Developers must always use `PromptBuilder` — can't build prompts ad-hoc

**Consequences:**
- `team_rules.md` rule: "Repository content is always DATA, never SYSTEM instructions."
- `PromptBuilder.build_chat_prompt()` is the only valid way to build chat prompts
- Prompt template changes require regression tests

**Related Components:**
[`prompt_builder.py`](file:///Users/meetvirugama/Desktop/AI-Powered-Software-Development-Platform/backend/ai/schemas/prompt_builder.py), [`prompt_architecture.md`](file:///Users/meetvirugama/Desktop/AI-Powered-Software-Development-Platform/Docs/prompt_architecture.md)

---

## ADR-003: PostgreSQL + pgvector for Vector Storage

| Field | Value |
|---|---|
| **Title** | Use PostgreSQL 15 + pgvector extension for vector similarity search |
| **Date** | 2026-09-24 |
| **Status** | Accepted |
| **Owner** | Om / Meet |

**Context:**
The RAG pipeline requires fast cosine similarity search over millions of code embeddings (1536 dimensions).

**Problem:**
Which vector store to use: a dedicated vector DB (Pinecone, Weaviate, Qdrant) or extend the existing PostgreSQL database?

**Options Considered:**
1. Dedicated vector database (Pinecone, Qdrant, Weaviate)
2. PostgreSQL + pgvector extension

**Decision:**
Option 2 — PostgreSQL 15 with pgvector.

**Reason:**
- Single database for relational data and vectors — no extra infrastructure
- HNSW index support in pgvector for fast approximate nearest neighbor search
- `repository_id` scoping is enforced at SQL level — no cross-repo leakage
- Simpler operational model — team already uses PostgreSQL

**Trade-offs:**
- Performance ceiling is lower than dedicated vector DB at extreme scale
- pgvector `<=>` operator requires raw SQL (`text()`) since SQLAlchemy ORM doesn't support it cleanly

**Consequences:**
- `code_chunks.embedding` column is `VECTOR(1536)`
- HNSW index created on `embedding` column
- `VectorRetriever` uses `sqlalchemy.text()` with pgvector's `<=>` operator
- Cross-repo leakage prevented by `WHERE repository_id = :repository_id` in all queries

**Related Components:**
[`docker-compose.yml`](file:///Users/meetvirugama/Desktop/AI-Powered-Software-Development-Platform/docker-compose.yml), [`vector.py`](file:///Users/meetvirugama/Desktop/AI-Powered-Software-Development-Platform/backend/ai/retrieval/vector.py)

---

## ADR-004: Hybrid Retrieval — Vector + Lexical + RRF + Reranker

| Field | Value |
|---|---|
| **Title** | Use hybrid retrieval (vector + lexical) with RRF fusion and cross-encoder reranking |
| **Date** | 2026-09-24 |
| **Status** | Accepted |
| **Owner** | Meet |

**Context:**
Repository-aware chat requires finding the most relevant code chunks for a query. Pure vector search misses exact keyword matches; pure lexical search misses semantic matches.

**Problem:**
How do we maximize retrieval quality for code queries that may be semantic ("where is auth handled?") or lexical ("find all AuthService")?

**Options Considered:**
1. Vector-only search
2. Lexical-only (FTS) search
3. Hybrid: vector + lexical → RRF fusion → cross-encoder rerank

**Decision:**
Option 3 — Full hybrid pipeline:
1. Vector search (top-30) via pgvector
2. Lexical search (top-30) via PostgreSQL FTS
3. RRF fusion (k=60) → merged top-30 unique chunks
4. Cross-encoder rerank → top-8 final chunks for LLM context

**Reason:**
- Vector: handles semantic/conceptual queries
- Lexical: handles exact identifier and keyword searches
- RRF: merges without needing normalized scores from heterogeneous retrievers
- Cross-encoder: more accurate than bi-encoder similarity; runs only on small candidate set (30)

**Trade-offs:**
- More complex pipeline with more failure points
- Cross-encoder adds ~100ms latency (runs locally)

**Consequences:**
- Default `top_k=30` for each retriever (RRF input)
- Default `top_n=8` for reranker (LLM context)
- `RRFFusion` uses k=60 constant (do not change without benchmarking)

**Status:** 🟢 All components fully implemented (2026-09-28)

**Related Components:**
[`vector.py`](file:///Users/meetvirugama/Desktop/AI-Powered-Software-Development-Platform/backend/ai/retrieval/vector.py), [`lexical.py`](file:///Users/meetvirugama/Desktop/AI-Powered-Software-Development-Platform/backend/ai/retrieval/lexical.py), [`fusion.py`](file:///Users/meetvirugama/Desktop/AI-Powered-Software-Development-Platform/backend/ai/retrieval/fusion.py), [`reranker.py`](file:///Users/meetvirugama/Desktop/AI-Powered-Software-Development-Platform/backend/ai/retrieval/reranker.py)

---

## ADR-005: JWT with httpOnly Cookie (No Bearer Token in Frontend)

| Field | Value |
|---|---|
| **Title** | Store JWT in httpOnly cookie, not localStorage or JS-accessible memory |
| **Date** | 2026-09-24 |
| **Status** | Accepted |
| **Owner** | Yug / Dhramraj |

**Context:**
After GitHub OAuth, the backend must give the frontend a way to authenticate subsequent requests.

**Problem:**
How should the JWT be stored and transmitted?

**Options Considered:**
1. JWT in `localStorage` (XSS-vulnerable)
2. JWT in JS memory (lost on refresh)
3. JWT in httpOnly cookie (XSS-safe, persistent across tabs)

**Decision:**
Option 3 — httpOnly cookie set by backend. Frontend never reads the raw token.

**Reason:**
- httpOnly cookies are not accessible from JavaScript (XSS protection)
- Browser automatically sends cookie with `credentials: include`
- `useAuthStore.token` field intentionally `null` — the cookie is the token

**Trade-offs:**
- Requires `withCredentials: true` on all Axios requests
- CSRF protection needed if using cookie-based auth (TBD)
- More complex logout (must blocklist JWT in Redis)

**Related Components:**
[`useAuthStore.ts`](file:///Users/meetvirugama/Desktop/AI-Powered-Software-Development-Platform/frontend/src/stores/useAuthStore.ts), `backend/app/api/v1/auth.py`

---

## ADR-006: Frontend Framework — Vite + React 19 + TypeScript

| Field | Value |
|---|---|
| **Title** | Use Vite + React 19 + TypeScript for frontend |
| **Date** | 2026-09-24 |
| **Status** | Accepted |
| **Owner** | Dhramraj |

**Context:**
Team needs a modern, fast frontend framework for the developer dashboard and chat UI.

**Decision:**
Vite + React 19 + TypeScript with:
- Zustand 5 for client state
- TanStack Query 5 for server state  
- Axios for HTTP
- MSW 2 for API mocking during development
- Tailwind CSS 4 for styling

**Reason:**
- Vite: fast HMR, native ESM
- React 19: latest stable with concurrent features
- Zustand: minimal, no boilerplate
- TanStack Query: handles caching, loading, error states for server data
- MSW: enables frontend development before backend endpoints are ready

**Related Components:**
[`package.json`](file:///Users/meetvirugama/Desktop/AI-Powered-Software-Development-Platform/frontend/package.json), [`App.tsx`](file:///Users/meetvirugama/Desktop/AI-Powered-Software-Development-Platform/frontend/src/App.tsx)

---

## ADR-007: Agent Sandbox Isolation

| Field | Value |
|---|---|
| **Title** | All agent code execution runs in isolated Docker containers |
| **Date** | 2026-09-24 |
| **Status** | Proposed |
| **Owner** | Prit |

**Context:**
The agent needs to execute arbitrary code (run tests, write files) without affecting the developer's machine or the live repository.

**Problem:**
How do we safely execute untrusted agent actions?

**Decision:**
Docker-based sandbox (or gVisor for stronger isolation):
- Resource limits: 2 vCPU, 4 GiB RAM, 10 GiB disk, 512 processes
- Network egress: denied by default
- Host filesystem: completely invisible
- Workspace destroyed after task completion/failure/cancellation

**Status:** Proposed — scheduled for Week 3 workflow isolation.

**Related Components:**
`backend/agent/sandbox/` (Week 3)

---

## ADR-008: Approved LLM Provider Policy (Google Gemini & Groq Only)

| Field | Value |
|---|---|
| **Title** | Restrict LLM inference strictly to Google Gemini and Groq |
| **Date** | 2026-10-14 |
| **Status** | Accepted |
| **Owner** | Meet / Dev |

**Context:**
The platform relies on fast, high-quality, cost-efficient LLM inference for code analysis, prompt repair, and grounded chat. Uncontrolled proliferation of API keys and third-party models causes rate limit unpredictability and security risk.

**Decision:**
Enforce strict restriction to two approved providers through `LLMGateway`:
1. **Google Gemini** (`gemini-flash-lite-latest` or `gemini-1.5-flash`) for large context analysis and reasoning.
2. **Groq** (`llama-3.3-70b-versatile`) for ultra-low-latency structured inference and JSON output.

**Consequences:**
- No unauthorized external LLM providers are permitted.
- Both providers implement `LLMProvider` abstract base class with exponential backoff and 30-second timeouts.
- Deterministic mock providers are used across all automated test suites.

---

## ADR-009: Shared IntelligenceContext for Developer Intelligence Suite

| Field | Value |
|---|---|
| **Title** | Unified TargetSnippet, SymbolContext, and bounded context container for Week 2 |
| **Date** | 2026-10-15 |
| **Status** | Accepted |
| **Owner** | Meet |

**Context:**
Week 2 introduces four independent intelligence features: Code Explanation, Bug Detection, Test Generation, and Standalone AI Code Review. If each feature implemented its own AST target resolution and context truncation, code duplication and token budget overflows would occur.

**Decision:**
Create `IntelligenceContext` in `backend/ai/context/builder.py`:
- `TargetSnippet`: Holds file path, selected start/end line range, and verified target code.
- `SymbolContext`: Captures enclosing class/function and caller/dependency references from the AST symbol graph.
- Budget-bounded truncation: Enforces strict token ceilings (`tiktoken` `cl100k_base`) ensuring target snippet is preserved while distant callers are cleanly truncated.
- Untrusted boundary tagging: Formats repository code inside prompt-isolated delimiters (`<<<REPO_DATA_...>>>`).

**Consequences:**
- Used by all 4 developer intelligence services (`CodeExplanationService`, `BugDetectionEngine`, `TestGenerationService`, `AICodeReviewEngine`).
- Guaranteed source traceability with exact file and line references.

---

## ADR-010: Mandatory Human Approval Gate & Bounded Repair Loop

| Field | Value |
|---|---|
| **Title** | Server-enforced approval gate and 3-attempt ceiling for task workflow |
| **Date** | 2026-10-15 |
| **Status** | Accepted |
| **Owner** | Meet / Dev / Sukun |

**Context:**
Autonomous agents operating on codebases risk unreviewed changes, infinite loops, and runaway token expenses without hard structural boundaries.

**Decision:**
1. **Mandatory Approval Gate:** No task can transition to `EXECUTING` or modify workspace files without explicit human approval of the structured plan. If a plan or base revision changes, previous approval is invalidated.
2. **Bounded Repair Ceiling:** In the event of test failures, the self-repair loop is restricted to a maximum of **3 task-level attempts**. If the budget is exhausted, execution terminates in a safe failure state requiring human escalation.
3. **No Automatic Merge:** The agent creates a GitHub Draft Pull Request only; merging and production deployment remain exclusively human actions.

---

## ADR-011: Cryptographic JWT Consolidation and Fail-Closed OAuth Security

| Field | Value |
|---|---|
| **Title** | PyJWT consolidation, claim hardening, dual trust-domain separation, and fail-closed OAuth state |
| **Date** | 2026-11-07 |
| **Status** | Accepted |
| **Owner** | Dharmraj / Security Architecture |

**Context:**
Issue #181 identified dual JWT dependencies (`python-jose` and `PyJWT`), missing platform token claims (`iss`, `aud`, `token_type`, `jti`), potential fail-open behavior if Redis was offline during revocation checks, and non-atomic OAuth state consumption.

**Decision:**
1. **PyJWT Consolidation:** Fully retire `python-jose` across the backend. Standardize all JWT operations on `PyJWT`.
2. **Dual Trust-Domain Separation:** Isolate platform user tokens (symmetric `HS256`, `jwt_secret`, `agent-platform` issuer) from GitHub App integration tokens (asymmetric `RS256`, RSA private key PEM, GitHub App numeric ID issuer). Key material and validation algorithms are mutually exclusive.
3. **Platform Token Hardening:** Require strict algorithm allowlist (`HS256`, `HS384`, `HS512`), mandatory claims (`sub`, `jti`, `iss`, `aud`, `token_type="access"`, `iat`, `exp`), and safe error abstraction behind standard 401 envelopes.
4. **Fail-Closed Redis Operations:** If Redis is down, times out, or missing during token blocklist checks or OAuth state creation/consumption, fail closed immediately with HTTP 503 (`SERVICE_UNAVAILABLE`).
5. **Atomic OAuth State & PKCE S256:** Enforce RFC 7636 PKCE (`code_verifier` + `code_challenge` S256), bind OAuth state to browser via HTTP-only cookie, and atomically consume state using Redis `GETDEL` (with Lua script fallback) to prevent replay and race conditions. Clear state cookies on both success and failure paths.
6. **Redirect and CSRF Protection:** Reject untrusted open redirects by strictly validating callback URLs against configured CORS origins and `frontend_url`. Require valid `Origin` or `Referer` headers on cookie-authenticated state-changing endpoints in production.

**Consequences:**
- Zero dependence on `python-jose`.
- Full compliance with modern OAuth 2.0 PKCE and JWT best practices.
- Legacy unhardened tokens expire naturally and cleanly prompt re-authentication via GitHub OAuth.

---

## ADR-012: Durable Webhook State Machine & Lease Worker Pattern

| Field | Value |
|---|---|
| **Title** | Durable Webhook State Machine & Lease-Based Worker Execution |
| **Date** | 2026-11-04 |
| **Status** | Accepted |
| **Owner** | Meet / Parth |

**Context:**
GitHub webhooks arrive asynchronously and must never be lost due to server crashes, cold starts, or transient network partitions. In-memory queues fail when workers restart. Furthermore, multiple workers must not process the same webhook delivery concurrently.

**Decision:**
1. **Durable Ingestion Table:** Store incoming webhooks immediately in PostgreSQL `github_webhook_events` with status `pending` upon HMAC validation, returning HTTP 202 Accepted.
2. **Lease-Based Worker:** Background workers acquire events using atomic lease tokens (`lease_token`, `lease_expires_at = now() + 30s`) to ensure mutual exclusion across distributed replicas without centralized orchestrators.
3. **Dead-Letter Queue:** If an event fails after 3 retry attempts, it transitions to `dead_letter` for operator inspection and replay via `POST /api/v1/github/events/{id}/replay`.
4. **Autonomous Event Automation:** `push` events to the default branch trigger automatic repository re-indexing; `pull_request` events automatically post AI code review findings as comments when enabled.

---

## ADR-013: 7-Stage Code Retrieval Engine with Active Generation Invalidation

| Field | Value |
|---|---|
| **Title** | Multi-Stage Hybrid Code Retrieval with Graph Expansion and Generation Caching |
| **Date** | 2026-11-06 |
| **Status** | Accepted |
| **Owner** | Meet |

**Context:**
Dense vector search alone suffers on exact identifier lookups (e.g. `UserRepository.get_by_id`), while lexical FTS misses conceptual semantic matches. Furthermore, naive cache invalidation on Git pushes is either over-aggressive (flushing entire caches) or under-invalidating (serving stale snippets).

**Decision:**
1. **7-Stage Retrieval Pipeline:**
   - Stage 1: Query Intent Detection (`SYMBOL_LOOKUP`, `CONCEPTUAL`, `HYBRID`)
   - Stage 2: Code-Aware Lexical FTS (`code_search_text` GIN index with CamelCase/snake_case tokenization)
   - Stage 3: Dense Vector Search (pgvector cosine `<=>` with adaptive `hnsw.ef_search`)
   - Stage 4: Reciprocal Rank Fusion ($k=60$)
   - Stage 5: 1-Hop Symbol Graph Expansion (AST caller/callee context injection)
   - Stage 6: Cross-Encoder Reranking (`ms-marco-MiniLM-L-6-v2` in ONNX with PyTorch fallback)
   - Stage 7: Shared Redis Cache with Generation Invalidation
2. **Active Generation Keying:** Cache entries are keyed by `(repo_id, active_index_generation, query_hash)`. When a repository sync completes, incrementing `active_index_generation` instantly invalidates all cached queries for that repository without expensive wildcard cache deletes.

---

## ADR-014: Normalized LLM Tool Calling & Bounded Agentic Chat Architecture

| Field | Value |
|---|---|
| **Title** | Normalized Multi-Provider Tool Calling and Strictly Bounded Agentic Repository Chat |
| **Date** | 2026-11-08 |
| **Status** | Accepted |
| **Owner** | Meet / Dhramraj |

**Context:**
Developers require an interactive assistant capable of iteratively discovering, inspecting, and navigating repository files to answer complex architectural questions. However, agentic loops risk runaway token usage, infinite tool calling loops, and filesystem tampering if unconstrained.

**Decision:**
1. **Normalized Tool-Calling Abstraction:** Implement a vendor-neutral tool calling layer normalizing Google Gemini Function Calling and Groq/OpenAI tool formats, isolating application code from proprietary LLM schemas.
2. **Read-Only Tool Registry:** Restrict the agent's repository tools strictly to read-only operations: `search_code`, `read_file_range`, `find_symbol`, and `list_directory`. Write operations are forbidden in chat mode.
3. **Execution Policy & Directory Jail:** Sandboxed execution via `ExecutionPolicy` strictly confines file access to the designated repository path and blocks sensitive files (`.env`, secrets, `.git`, credentials).
4. **Three-Tiered Budget Ceilings:** `BudgetManager` enforces hard stops:
   - Maximum 8,000 total tokens per invocation
   - Maximum 5 tool-calling rounds per query
   - Maximum 30-second execution timeout
   When budgets are exhausted, the agent halts tool invocation and synthesizes a grounded answer from collected evidence, tagging `truncated: true` in `agent_metadata`.
5. **Dual-Mode API & UI:** The `/chat` endpoint accepts `"mode": "normal" | "agentic"`, allowing developers to seamlessly switch between ultra-fast RAG and multi-step agentic exploration directly from the Workbench UI.

---

## ADR-015: Autonomous Code Synthesis, Search/Replace Patching & Durable Workflow Execution

| Field | Value |
|---|---|
| **Title** | Autonomous Code Synthesis via Search/Replace Blocks and Durable DBOS Workflow Execution |
| **Date** | 2026-11-09 |
| **Status** | Accepted |
| **Owner** | Meet Virugama (Lead Agent Architect) |

**Context:**
Prior to this decision, autonomous execution after human plan approval exhibited two major architectural vulnerabilities:
1. When HTTP callers did not provide code modification payloads, `AgentExecutionLoop` was unable to autonomously synthesize modifications, or fell back onto a dangerous cross-step content loop that reused unrelated file payloads across steps.
2. The entire post-approval autonomous workflow (workspace setup, step execution, testing, repair, verification, draft PR) ran synchronously within a single HTTP request, making it susceptible to socket timeouts, connection drops, and process crashes.

**Decision:**
1. **EditSynthesizer Engine:** Implement `EditSynthesizer` using SWE-agent and Aider-inspired search/replace blocks (`search_block`, `replace_block`) rather than whole-file generation.
2. **7-Stage Validation Pipeline:** Evaluate patches in memory through 7 strict stages prior to disk modification:
   - Stage A: Structured JSON and fence validation.
   - Stage B: Exact single-match validation (`occurrences == 1`).
   - Stage C: Path traversal safety, `fnmatch` forbidden file detection, and approved plan scope enforcement.
   - Stage D: Atomic in-memory patch application.
   - Stage E: Language AST syntax checks (`ast.parse` for Python, `json.loads` for JSON).
   - Stage F: Lint checks prohibiting placeholder comments and raw secrets.
   - Stage G: SHA-256 stale-content fingerprint verification against concurrent modifications.
3. **Bounded Self-Refinement:** Govern iterative correction with a hard ceiling of 3 total attempts (1 initial + 2 retries) with verbal failure feedback.
4. **Elimination of Cross-Step Reuse:** Eliminate the cross-step payload fallback loop. Caller payloads have first priority; missing payloads autonomously trigger `EditSynthesizer`. If synthesis fails, execution fails closed.
5. **Durable Workflow Architecture:** Wrap multi-stage post-approval workflows into 7 durable steps with DBOS (`@dbos_step()` and `@dbos_workflow()`), utilizing stable workflow IDs, re-entrant registry locks (`threading.RLock`), and persistent `TaskCheckpoint` records.
6. **Asynchronous HTTP 202 Initiation & Progress Streaming:**
   - `POST /api/v1/tasks/{task_id}/run-workflow` accepts `async_execution=True` or `Prefer: respond-async`, returning `HTTP 202 Accepted` with a workflow status URL.
   - `GET /api/v1/tasks/{task_id}/workflow-status` returns real-time progress percentage, completed steps, and verification results.
   - Real-time step transitions stream over Redis pubsub (`platform_events`) to frontend SSE clients.

---

## ADR-016: Embedding Profile v2, cAST AST Chunking, Contextual Headers, L2 Normalization & Local Embedding Policy Review

| Field | Value |
|---|---|
| **Title** | Task-Aware Gemini EmbeddingProfile v2, cAST Chunking, Contextual Headers, L2 Normalization, and ADR-008 Local Model Gating |
| **Date** | 2026-11-11 |
| **Status** | Accepted |
| **Owner** | Yug / Meet |

**Context:**
Code retrieval quality and embedding efficiency exhibited five engineering gaps:
1. Gemini `batchEmbedContents` requests omitted `taskType`, using symmetric embeddings instead of asymmetric document/code-query representations.
2. Small sibling symbols (helper functions, methods, constants) produced numerous tiny chunks, inflating API calls and fragmenting retrieval context.
3. Embedding input lacked structural hierarchy context (`file_path`, enclosing class, function signature), while displayed `code_chunks.content` must remain raw source code for accurate line citations.
4. Stored vectors were not explicitly L2-normalized on write.
5. Evaluating optional local code embeddings (`nomic-ai/CodeRankEmbed`) required explicit governance alignment with ADR-008 (`ai_quality_evaluator.py`).

**Decision:**
1. **Gemini Task Types & EmbeddingProfile v2:**
   - Centralize `GeminiTaskType.RETRIEVAL_DOCUMENT` for corpus indexing (`embed_documents`) and `GeminiTaskType.CODE_RETRIEVAL_QUERY` for search queries (`embed_query`).
   - Introduce `EmbeddingProfile` `profile_version="v2"` (`EmbeddingProfile.v2_gemini()`) and isolate L1/Redis L2 cache keys by `profile_version` and `task_type`.
   - Enforce strict compatibility checks (`is_compatible_with`) so `v1` and `v2` profiles or incompatible providers/models are never mixed.
   - Support staged blue/green re-embedding (`ReembeddingMigrationManager`) preserving the active `v1` index during background `v2` staging, with resumable file progress, vector validation, atomic activation, and instant rollback.
2. **cAST-Style AST Chunking (`SymbolChunker`):**
   - Walk the symbol/AST hierarchy: recursively split classes exceeding `MAX_CHUNK_TOKENS = 512` along child method boundaries before falling back to line-boundary splitting, and greedily merge adjacent small sibling symbols (`<= 128` tokens) up to `512` tokens.
   - Retain a deterministic dominant `symbol_id` (`group[0].id`), store all constituent symbol IDs in `metadata["symbol_ids"]`, compute deterministic UUIDv5 chunk IDs (`compute_stable_chunk_id`), and reconcile obsolete chunks on boundary changes.
3. **Contextual Embedding Headers:**
   - Prepend deterministic, secret-redacted headers (`# path: app/x.py | class Foo | def bar(a, b)`) strictly to `chunk.embedding_text` while keeping `chunk.content` unmodified so source offsets and `reconstruct_file_from_chunks` remain exact.
4. **L2 Normalization on Write:**
   - Normalize all persisted and query vectors via `l2_normalize_vector` (`||v||_2 = 1.0`), rejecting zero-norm, `NaN`/`Inf`, or wrong-dimensionality vectors with `InvalidVectorError` / `DimensionMismatchError`. Retain `<=>` cosine search by default while providing `evaluate_vector_storage_modes` for inner-product (`<#>`) and `halfvec` float16 precision benchmarking.
5. **ADR-008 Review for Optional Local Embeddings (`CodeRankEmbed`):**
   - Keep ADR-008 (`_PERMITTED_PROVIDERS = {"gemini", "groq"}` in `ai_quality_evaluator.py` and `_ALLOWED_EMBEDDING_PROVIDERS = {"gemini"}` in `config.py`) strictly enforced by default.
   - Gate `CodeRankEmbedProvider` (`nomic-ai/CodeRankEmbed`, 768-d, 8192 context, query prefix `"Represent this query for searching relevant code: "`) behind explicit `allow_local_embeddings=True` opt-in with an isolated `EmbeddingProfile(provider="local_coderank", model="nomic-ai/CodeRankEmbed", dimensions=768, profile_version="v2")`.

---

## ADR-017: OpenTelemetry Distributed Tracing, GenAI Semantic Spans & Fail-Safe Langfuse Observability

| Field | Value |
|---|---|
| **Title** | OpenTelemetry Distributed Tracing, GenAI Semantic Conventions, Autonomous Tool Tracing & Fail-Safe Langfuse Observability |
| **Date** | 2026-11-13 |
| **Status** | Accepted |
| **Owner** | Meet |

**Context:**
As the platform expanded from single LLM requests into autonomous multi-turn agents, workflow loops, and tool-assisted code modifications, visibility across boundaries became fractured:
1. Tracing across FastAPI ingress, database queries, Redis caching, outbound HTTP calls, and internal LLM gateway invocations lacked unified context propagation.
2. Debugging LLM degradation, token consumption spikes, and transient rate-limiting required dedicated GenAI semantic tracing without fragmenting logs.
3. Autonomous agent execution loops and tool routing (`ToolRouter.route()`) lacked hierarchical parent-child span correlation.
4. LLM-specific observability (evaluations, prompt versioning, token cost tracking) required a dedicated dashboard interface (Langfuse) without creating a single point of failure or violating enterprise privacy.
5. In-app stage-level telemetry (`AnalysisRun.result_payload["stage_metrics"]`) and existing health check contracts (`/health/ready`) needed strict preservation.

**Decision:**
1. **OpenTelemetry as the Unified Tracing Standard:**
   - Establish `TelemetryManager` as the process-wide OpenTelemetry singleton managing `TracerProvider`, `MeterProvider`, and resource attributes (`service.name`, `service.version`, `deployment.environment`).
   - Propagate trace context via W3C TraceContext standards (`traceparent`).
   - Implement framework auto-instrumentation for FastAPI (excluding health endpoints), HTTPX, SQLAlchemy, and Redis with secret redaction.
   - Enrich existing structured logging (`JsonFormatter`) with dynamic `trace_id`, `span_id`, `request_id`, `analysis_run_id`, and `agent_execution_id`.
2. **GenAI Semantic Spans & Fallback Tracking:**
   - Instrument `LLMGateway.generate` and `LLMGateway.generate_stream` with standardized OpenTelemetry GenAI semantic conventions (`gen_ai.system`, `gen_ai.request.model`, `gen_ai.response.model`, `gen_ai.usage.input_tokens`, `gen_ai.usage.output_tokens`, `gen_ai.usage.total_tokens`).
   - Explicitly track provider fallback events (`gen_ai.fallback.attempted`, `gen_ai.fallback.provider`, `gen_ai.fallback.status`, `gen_ai.primary.error`).
   - Monitor streaming latency (TTFT) and token cost estimation based on model-aware pricing.
3. **Autonomous Agent & Tool Invocation Tracing:**
   - Create root `agent.execution` spans around autonomous agent reasoning loops via `trace_agent_execution`.
   - Wrap tool executions in child spans `tool:{tool_name}` within `ToolRouter.route()` via `trace_tool_invocation`, capturing duration, execution ID, and sanitized tool metadata.
4. **Fail-Safe Langfuse Adapter & Privacy Opt-in:**
   - Wrap the `langfuse` SDK inside `LangfuseAdapter` with defensive error boundaries and no-op fallback when unconfigured.
   - Enforce zero raw content retention by default (`OBSERVABILITY_CAPTURE_PROMPTS=False`, `OBSERVABILITY_CAPTURE_RESPONSES=False`), transmitting only model identifiers, token counts, latency, and cost unless explicit user opt-in is granted.
   - Redact all sensitive tokens and credentials via `app.core.secret_redaction` even when debugging capture is active.
5. **Decoupled Health Endpoints & Metric Cardinality Governance:**
   - Preserve `/health`, `/health/live`, and `/health/ready` checking only database and cache connectivity; external OTLP or Langfuse outages never affect platform readiness.
   - Enforce strict low-cardinality governance on OpenTelemetry metrics (`llm_requests_total`, `llm_request_duration_seconds`, `agent_executions_total`, `tool_invocations_total`), forbidding high-cardinality IDs from metric label sets.
   - Retain full backwards compatibility with `AnalysisRun.result_payload["stage_metrics"]` and `StageExecutionTimer`.



