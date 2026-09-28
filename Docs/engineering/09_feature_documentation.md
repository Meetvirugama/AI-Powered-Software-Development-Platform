# 09. Feature-Level Documentation
> **Version:** 2.0 | **Created:** 2026-09-24 | **Last Updated:** 2026-09-28 | **Status:** Live

---

## Feature: LLM Gateway

**Status:** 🟢 Done | **Priority:** P0 | **Owner:** Meet

### Purpose
Single, centralized entry point for every LLM API call in the system. Enforces consistent logging, retry, timeout, and structured output across all AI features.

### Description
`LLMGateway` wraps any `LLMProvider` implementation. Currently the only provider is `OpenAIProvider`. No other module may call an LLM API directly.

### Actors
- System (all AI features call this)

### Main Flow
1. Caller constructs `LLMRequest(model, messages, temperature, max_tokens, response_schema?)`
2. Calls `LLMGateway.generate(request)`
3. Gateway delegates to `_provider.generate(request)`
4. Provider retries up to 3 times with exponential backoff on 429/5xx
5. Gateway logs: model, input_tokens, output_tokens, latency_ms, success/failure
6. Returns `LLMResponse(content, model, input_tokens, output_tokens, latency_ms)`

### Error Cases
| Error | When | Retryable |
|---|---|---|
| `LLMTimeoutError` | Request exceeds 30s | Yes |
| `LLMRateLimitError` | HTTP 429 after 3 retries | Yes |
| `LLMUnavailableError` | HTTP 5xx after 3 retries | Yes |
| `LLMValidationError` | JSON fails Pydantic schema validation | No |

### Frontend Components
None — internal system component

### Backend Components
- `backend/ai/llm/client.py` — `LLMGateway`
- `backend/ai/llm/provider.py` — `LLMProvider` (abstract)
- `backend/ai/llm/openai_provider.py` — `OpenAIProvider`
- `backend/ai/llm/schemas.py` — `LLMRequest`, `LLMResponse`, error hierarchy

### External Services
- OpenAI Chat Completions API: `https://api.openai.com/v1/chat/completions`

### Business Rules
1. LLM Gateway is the ONLY place in the codebase that calls an LLM API.
2. Every LLM call MUST log: model, input_tokens, output_tokens, latency_ms, success/failure.
3. Max retries: 3. Backoff: 1s, 2s, 4s.
4. Default timeout: 30 seconds.

### Current Status
🟢 Fully implemented and tested. Tests in `backend/tests/test_llm_gateway.py`.

---

## Feature: Embedding Service

**Status:** 🟢 Done | **Priority:** P0 | **Owner:** Meet

### Purpose
Batch embedding of code chunks and queries using OpenAI's embedding model, with retry and dimension validation.

### Description
`EmbeddingService` wraps an `EmbeddingProvider`. Supports single-text and batch embedding. Validates vector dimensions and parallelizes batch processing via `asyncio.gather`.

### Main Flow — Single Embed
1. Caller calls `EmbeddingService.embed(text)`
2. Delegates to `_provider.embed(text)`
3. Validates dimension (expected vs. actual)
4. Returns float vector

### Main Flow — Batch Embed
1. Split `texts` into sub-batches of 100
2. Run all sub-batches concurrently with `asyncio.gather`
3. Flatten results
4. Validate dimensions of each vector
5. Return list of vectors in original order

### Error Cases
- `EmbeddingError(retryable=False)`: Dimension mismatch — indicates config or provider mismatch

### Backend Components
- `backend/ai/embeddings/service.py` — `EmbeddingService`
- `backend/ai/embeddings/client.py` — `EmbeddingProvider` (abstract)
- `backend/ai/embeddings/openai_provider.py` — `OpenAIEmbeddingProvider`

### Business Rules
1. Never hard-code embedding dimensions — read from provider config.
2. Batch size capped at 100 (OpenAI limit is 2048, we cap for error recovery).
3. Dimension mismatch is non-retryable — requires human intervention.

### Current Status
🟢 Fully implemented. Tests in `backend/tests/test_embedding_service.py`.

---

## Feature: Vector Retrieval

**Status:** 🟢 Done | **Priority:** P0 | **Owner:** Meet

### Purpose
Retrieve the most semantically relevant code chunks for a query using pgvector cosine similarity.

### Description
`VectorRetriever` embeds a query string, then executes a pgvector `<=>` cosine distance query on the `code_chunks` table, scoped to a specific `repository_id`.

### Main Flow
1. `embed(query)` → query vector
2. Execute SQL: `SELECT ... FROM code_chunks WHERE repository_id = :id ORDER BY embedding <=> :vec LIMIT :top_k`
3. Score = `1 - cosine_distance` (clamped to [0, 1])
4. Return `list[CodeChunk]` sorted by descending score

### Preconditions
- `code_chunks` table exists with HNSW index on `embedding` column
- `repository_id` must be provided (no cross-repository queries)

### Error Cases
- `EmbeddingError` — if embedding service fails
- `SQLAlchemyError` — if database is unreachable
- Returns empty list if no chunks found (not an error)

### Backend Components
- `backend/ai/retrieval/vector.py` — `VectorRetriever`
- `backend/ai/retrieval/base.py` — `CodeChunk`, `Retriever`

### Database Tables
- `code_chunks` — reads only

### Business Rules
1. Every query MUST filter by `repository_id` — no cross-repository leakage.
2. `top_k` default = 30 (for RRF input).
3. Score formula: `score = max(0.0, 1.0 - distance)`.

### Current Status
🟢 Fully implemented. Tests in `backend/tests/test_vector_retrieval.py`.

---

## Feature: Lexical Retrieval

**Status:** 🟢 Done | **Priority:** P0 | **Owner:** Meet

### Purpose
Retrieve code chunks using PostgreSQL full-text search (tsvector / tsquery), complementing vector search for exact keyword matches.

### Description
`LexicalRetriever` sanitizes the query into a tsquery expression, executes a GIN-indexed full-text search on `code_chunks.content`, and normalises ts_rank scores to [0, 1] for RRF combination.

### Main Flow
1. `_sanitize_query(query)` → tokens joined with `&` (e.g. `'authenticate & user & service'`)
2. Execute SQL with `to_tsquery` + `ts_rank` against GIN index on `code_chunks.content`
3. Normalise ts_rank: divide by max rank in result set (handled in CTE)
4. Map rows to `CodeChunk` with normalised score
5. Return `list[CodeChunk]` sorted by descending rank

### Error Cases
- Returns `[]` gracefully if the query produces no searchable tokens
- Returns `[]` if no FTS matches found
- `SQLAlchemyError` if database is unreachable

### Backend Components
- `backend/ai/retrieval/lexical.py` — `LexicalRetriever`, `_sanitize_query`

### Database Tables
- `code_chunks` — reads only (GIN tsvector index on `content`)

### Business Rules
1. Every query MUST filter by `repository_id` — enforced at SQL level.
2. Scores normalised to [0, 1] so RRF can combine fairly with vector scores.
3. Queries with zero searchable tokens return `[]` — no error raised.

### Current Status
🟢 Fully implemented. Tests in `backend/tests/test_hybrid_retrieval.py`.

---

## Feature: RRF Fusion

**Status:** 🟢 Done | **Priority:** P0 | **Owner:** Meet

### Purpose
Merge vector and lexical retrieval results using Reciprocal Rank Fusion (k=60).

### Algorithm
```
score(chunk) = sum(1 / (k + rank_i))
```
Where k=60 and rank_i is the chunk's 1-based position in each result list.

### Description
`RRFFusion.fuse()` accepts any number of ranked result lists, accumulates RRF scores across sources (rewarding chunks appearing consistently across methods), deduplicates by UUID, and returns top-N sorted by RRF score descending. Each returned chunk's `.score` is replaced with the computed RRF score.

### Backend Components
- `backend/ai/retrieval/fusion.py` — `RRFFusion`

### Business Rules
1. k=60 is the standard constant — do not tune without benchmarking.
2. Default top_n=30 — feeds the CrossEncoderReranker.
3. Input lists must be ranked best-first.

### Current Status
🟢 Fully implemented. Tests in `backend/tests/test_hybrid_retrieval.py`.

---

## Feature: Cross-Encoder Reranker

**Status:** 🟢 Done | **Priority:** P0 | **Owner:** Meet

### Purpose
Rerank top-30 RRF candidates to top-8 using a cross-encoder model that scores (query, chunk) pairs jointly.

### Model
`cross-encoder/ms-marco-MiniLM-L-6-v2` (sentence-transformers, ~22M params, <200ms for 30 pairs)

### Description
`CrossEncoderReranker.rerank()` loads the cross-encoder lazily on first use, builds `(query, chunk.content)` pairs, batch-predicts logit scores, and returns the top-N chunks with `.score` set to the cross-encoder logit.

### Backend Components
- `backend/ai/retrieval/reranker.py` — `CrossEncoderReranker`

### Business Rules
1. Model is loaded lazily — no startup overhead.
2. Default top_n=8 — feeds the ContextBuilder.
3. If sentence-transformers is not installed, raises `RuntimeError` with install instructions.

### Current Status
🟢 Fully implemented. Tests in `backend/tests/test_hybrid_retrieval.py`.

---

## Feature: Context Builder

**Status:** 🟢 Done | **Priority:** P0 | **Owner:** Meet

### Purpose
Assemble reranked code chunks + memory entries + conversation history into a single `AgentContext` for the LLM, enforcing token limits via tiktoken.

### Description
`ContextBuilder.build()` produces a token-budget-aware `AgentContext`. Memory entries are de-duplicated by id and sorted by `created_at` descending. Items are greedily truncated from the tail when the budget is exceeded. `render_repository_data()` serialises the context into the REPOSITORY DATA + MEMORY string injected into the user message.

### Main Flow
1. De-duplicate memory entries by id (last-write wins)
2. Sort memory by `created_at` desc (most recent first)
3. Allocate token budget: `max_context_tokens - 500` (overhead)
4. Fit history first (newest-to-oldest, then re-order chronologically)
5. Fit memory entries within remaining budget
6. Fit code chunks within remaining budget
7. Set `ctx.total_tokens` and return `AgentContext`

### Backend Components
- `backend/ai/context/builder.py` — `ContextBuilder`, `AgentContext`, `MemoryEntry`, `ChatMessage`, `RepositoryFile`

### Key Dataclasses
| Class | Fields |
|---|---|
| `AgentContext` | `code_chunks`, `memory_chunks`, `related_files`, `recent_history`, `total_tokens` |
| `MemoryEntry` | `id`, `content`, `type` (architecture/decision/rule/task/failure), `created_at` |
| `ChatMessage` | `role` (user/assistant), `content` |
| `RepositoryFile` | `id`, `path`, `language`, `size_bytes`, `line_count` |

### Business Rules
1. Repository content goes into `REPOSITORY DATA:` section — NEVER the system prompt.
2. Token encoding: `cl100k_base` (GPT-4o compatible).
3. Default max: 100,000 tokens (500 reserved for overhead).
4. History preserved newest-first; older turns dropped if over budget.

### Current Status
🟢 Fully implemented. Tests in `backend/tests/test_context_builder.py`.

---

## Feature: RAG Pipeline

**Status:** 🟢 Done | **Priority:** P0 | **Owner:** Meet

### Purpose
End-to-end orchestration of the full repository-aware chat flow: retrieval → context → prompt → LLM → grounding validation → answer.

### Description
`RAGPipeline.chat()` coordinates all AI components. Uses dependency injection for full testability. Includes a JSON repair loop (up to 2 LLM retries for malformed JSON) and graceful fallback when retrieval returns zero chunks.

### Main Flow
1. **Hybrid retrieval** — `retriever.retrieve(query, repository_id, top_k=30)`
2. **Graceful fallback** — returns `confidence=low` answer if zero chunks retrieved
3. **Context assembly** — `ContextBuilder.build(chunks, memory, history)` → `AgentContext`
4. **Prompt construction** — `render_repository_data(ctx)` + `PromptBuilder.build_chat_prompt()` → `[system_msg, user_msg]`
5. **LLM call with JSON repair loop** — up to 2 attempts; strips markdown code fences; injects repair prompt on malformed JSON
6. **Grounding validation** — `GroundingValidator.validate_sources(answer, repo_id)` removes hallucinated citations
7. **Return** `RepositoryAnswer` with grounded sources and confidence level

### Backend Components
- `backend/ai/pipeline.py` — `RAGPipeline`

### Constants
| Constant | Value | Purpose |
|---|---|---|
| `_MAX_RETRIEVAL_TOP_K` | 30 | Top-K per retriever path (RRF input) |
| `_MAX_RERANKED_CHUNKS` | 8 | Chunks after reranking passed to ContextBuilder |
| `_LLM_MODEL` | `gpt-4o` | LLM model used for answer generation |
| `_MAX_REPAIR_ATTEMPTS` | 2 | JSON repair loop limit |

### Error Handling
| Scenario | Raised Error |
|---|---|
| LLM timeout | `APIError(503, SERVICE_UNAVAILABLE, retryable=True)` |
| LLM unavailable | `APIError(503, SERVICE_UNAVAILABLE, retryable=True)` |
| JSON repair exhausted | `APIError(500, INTERNAL_SERVER_ERROR)` |
| No retriever configured | Empty list → graceful fallback (not an error) |
| Retriever exception | Empty list → graceful fallback (not an error) |

### Business Rules
1. All dependencies injected at construction time — fully testable.
2. Zero retrieval → safe "no relevant code" response, never hallucinates.
3. Markdown code fences are stripped before JSON parsing.
4. Grounding validation ALWAYS runs before returning to caller.

### Current Status
🟢 Fully implemented (Day 7). 26 tests in `backend/tests/test_rag_pipeline.py`.

---

## Feature: Output Validator

**Status:** 🟢 Done | **Priority:** P0 | **Owner:** Dev

### Purpose
Validate and repair LLM structured output against Pydantic schemas, preventing malformed JSON from propagating through the system.

### Description
`OutputValidator` has two methods:
1. `validate(raw, schema)` — parse JSON + Pydantic validate. Never raises.
2. `repair(raw, schema, error)` — calls LLM to fix invalid JSON. Max 2 repair attempts.

### Main Flow — Validate
1. `json.loads(raw)` — parse JSON
2. `schema.model_validate(parsed)` — validate against Pydantic schema
3. Return `(instance, True)` on success, `(None, False)` on failure

### Main Flow — Repair
1. Build repair prompt: "Fix this JSON so it matches the schema..."
2. Call `LLMGateway.generate(LLMRequest(model='gpt-4o', ...))`
3. Run `validate()` on LLM response
4. If valid: return instance
5. If still invalid after 2 attempts: raise `LLMValidationError`

### Backend Components
- `backend/ai/schemas/validator.py` — `OutputValidator`

### Business Rules
1. `validate()` never raises — callers always check the bool flag.
2. Repair model: `gpt-4o`, temperature=0.0, max_tokens=1024.
3. Max repair attempts: 2.

### Current Status
🟢 Fully implemented.

---

## Feature: Prompt Builder

**Status:** 🟢 Done | **Priority:** P0 | **Owner:** Dev

### Purpose
Assemble structured message lists for LLM calls, enforcing the system/data separation rule.

### Description
`PromptBuilder` always returns `[system_message, user_message]`. Repository content is NEVER in the system message.

### Main Flow — Chat Prompt
1. System message: fixed instructions only
2. User message: `"REPOSITORY DATA:\n...\nUSER QUESTION:\n{question}"`
3. Return `[Message(role='system', ...), Message(role='user', ...)]`

### Backend Components
- `backend/ai/schemas/prompt_builder.py` — `PromptBuilder`
- `backend/ai/prompts/repository_chat.txt`
- `backend/ai/prompts/context_summary.txt`
- `backend/ai/prompts/source_grounding.txt`

### Business Rules
1. Repository content is ALWAYS data — NEVER in the system prompt (prompt injection prevention).
2. Every prompt change requires a regression test.
3. Every prompt change must be reviewed by Dev.

### Current Status
🟢 Done. Two methods implemented: `build_chat_prompt` and `build_summary_prompt`.

---

## Feature: Grounding Validator

**Status:** 🟢 Done | **Priority:** P0 | **Owner:** Dev

### Purpose
Remove hallucinated file/line citations from LLM answers before they reach the user.

### Description
`GroundingValidator.validate_sources()` checks each `SourceReference` against the database:
1. File existence check (`repository_files.path`)
2. Line range validity check (`repository_files.line_count`)
3. Removes ungrounded sources from the answer
4. Downgrades confidence to "low" if >50% ungrounded

### Known Issues / Limitations
- With no DB session injected, all sources are treated as grounded (safe fallback).

### Backend Components
- `backend/ai/schemas/grounding.py` — `GroundingValidator`, `GroundingResult`
- `backend/ai/schemas/output.py` — `RepositoryAnswer`, `SourceReference`

### Database Tables
- `repository_files` — read-only

### Current Status
🟢 Implemented and wired into RAGPipeline on every chat request.

---

## Feature: Auth API (GitHub OAuth + JWT)

**Status:** 🟢 Done | **Priority:** P0 | **Owner:** Yug

### Purpose
Authenticate users via GitHub OAuth 2.0, issue short-lived JWTs, and manage logout via Redis blocklist.

### Endpoints Implemented
| Method | Path | Description |
|---|---|---|
| `GET` | `/api/v1/auth/github/login` | Generates CSRF state, redirects to GitHub OAuth |
| `GET` | `/api/v1/auth/github/callback` | Exchanges code, upserts user, issues JWT cookie |
| `GET` | `/api/v1/auth/me` | Returns current authenticated user |
| `POST` | `/api/v1/auth/logout` | Adds JWT to Redis blocklist, clears cookie |

### Backend Components
- `backend/app/api/v1/auth.py`
- `backend/app/core/security.py`
- `backend/app/core/auth.py` — `JWTMiddleware`

### Business Rules
1. CSRF state validated via `oauth_state` httpOnly cookie + `secrets.compare_digest`.
2. JWT stored as httpOnly cookie; Redis blocklist on logout.
3. `JWTMiddleware` validates all non-auth routes automatically.

### Current Status
🟢 Fully implemented. Tests in `backend/tests/test_auth.py` and `backend/tests/test_auth_and_repositories_api.py`.

---

## Feature: Repositories API

**Status:** 🟢 Done | **Priority:** P0 | **Owner:** Yug

### Purpose
CRUD and search endpoints for repositories owned by the authenticated user.

### Endpoints Implemented
| Method | Path | Description |
|---|---|---|
| `GET` | `/api/v1/repositories` | List repositories for authenticated user |
| `GET` | `/api/v1/repositories/{id}` | Get repository details |
| `POST` | `/api/v1/repositories/{id}/sync` | Queue repository sync (returns 202) |
| `POST` | `/api/v1/repositories/{id}/search` | Hybrid code search via RAG pipeline |
| `GET` | `/api/v1/repositories/{id}/files` | List indexed files (paginated) |
| `GET` | `/api/v1/repositories/{id}/symbols` | List extracted symbols (paginated) |

### Backend Components
- `backend/app/api/v1/repositories.py`
- `backend/app/services/repository_sync.py`

### Business Rules
1. All endpoints validate ownership (403 if user doesn't own the repository, 404 if not found).
2. Search endpoint requires `rag_pipeline` on `app.state` — returns 503 if not configured.
3. Sync endpoint returns `202 Accepted` with `job_id`.
4. Files and Symbols endpoints are paginated (`page`, `page_size` query params).

### Current Status
🟢 Fully implemented. Tests in `backend/tests/test_repositories.py`, `test_repository_search_api.py`, `test_repository_chat_api.py`.

---

## Feature: Repository Chat API

**Status:** 🟢 Done | **Priority:** P0 | **Owner:** Yug

### Purpose
Accept natural-language questions about a repository and return grounded answers via the RAG pipeline.

### Endpoint
`POST /api/v1/repositories/{repository_id}/chat`

### Request Body
```json
{
  "question": "Where is authentication implemented?",
  "history": [
    { "role": "user", "content": "previous question" },
    { "role": "assistant", "content": "previous answer" }
  ]
}
```

### Response
```json
{
  "answer": "Authentication is handled in backend/app/core/auth.py...",
  "sources": [
    { "file": "backend/app/core/auth.py", "start_line": 1, "end_line": 50, "symbol": "JWTMiddleware" }
  ],
  "confidence": "high"
}
```

### Backend Components
- `backend/app/api/v1/chat.py` — `chat_with_repository`
- `backend/ai/pipeline.py` — `RAGPipeline`

### Business Rules
1. Validates repository ownership before calling RAG pipeline.
2. RAG pipeline injected via `app.state.rag_pipeline` — 503 if not configured.
3. `RepositoryAnswer` validated at the HTTP boundary via `model_validate`.

### Current Status
🟢 Fully implemented. Tests in `backend/tests/test_repository_chat_api.py`.

---

## Feature: File Walker (Scanner)

**Status:** 🟢 Done | **Priority:** P0 | **Owner:** Prit

### Purpose
Traverse a repository's file tree, filtering out non-relevant files for AST parsing and indexing.

### Description
`FileWalker.walk(root_path)` returns sorted `list[FileInfo]` skipping: known directories, .gitignore patterns, binary files, and files >1 MB.

### Main Flow
1. Load `.gitignore` if exists (uses `pathspec`)
2. `os.walk(root_path)`
3. Skip directories: `.git`, `node_modules`, `venv`, `__pycache__`, `dist`, `build`, `.next`, `.cache`
4. Skip files matching .gitignore
5. Skip files >1 MB
6. Skip binary files (null byte detection in first 8 KB)
7. Return sorted `list[FileInfo]`

### Backend Components
- `backend/scanner/walker.py` — `FileWalker`
- `backend/scanner/symbols.py` — `FileInfo`

### Business Rules
1. Scanner must never raise on malformed files — catch, log, skip.
2. Path traversal validation is scanner's responsibility.

### Current Status
🟢 Done. Tests in `backend/tests/test_walker.py`.

---

## Feature: Symbol Chunker (Indexer)

**Status:** 🟢 Done | **Priority:** P0 | **Owner:** Divu

### Purpose
Convert parsed symbols into embedable code chunks, preserving line numbers and metadata.

### Description
`SymbolChunker.chunk_symbols()` creates `Chunk` objects from symbol list:
- Functions/methods → `chunk_type="function"`
- Classes → `chunk_type="class"`
- Remaining module-level symbols → grouped into `chunk_type="module"`

### Backend Components
- `backend/indexer/chunker.py` — `SymbolChunker`
- `backend/indexer/models.py` — `Chunk`

### Database Tables
- Produces data for `code_chunks` table

### Current Status
🟢 Done.

---

## Feature: Frontend Application

**Status:** 🔵 In Progress | **Priority:** P0 | **Owner:** Dhramraj

### Description
React 19 + TypeScript SPA built with Vite. Uses Zustand for client state, TanStack Query for server state, Axios for API calls, MSW for development mocks.

### Pages (Implemented)

| Page | Route | Status |
|---|---|---|
| Login | `/login` | 🔵 Skeleton |
| Dashboard | `/app/dashboard` | 🔵 Skeleton |
| Repositories | `/app/repositories` | 🔵 Skeleton |
| Repository Detail | `/app/repositories/:id` | 🔵 Skeleton |
| Repository Chat | `/app/repositories/:id/chat` | 🔵 Skeleton |

### State Stores

| Store | Purpose |
|---|---|
| `useAuthStore` | Auth state: user, isAuthenticated, login(), logout() |
| `useRepositoryStore` | UI state: selectedRepository, syncStatus |
| `useAppStore` | Global app state (TBD) |

### Route Protection
All `/app/*` routes are wrapped in `ProtectedRoute` — redirects to `/login` if not authenticated.

### Current Status
🔵 Skeleton structure in place. Real API integration pending backend endpoints.
