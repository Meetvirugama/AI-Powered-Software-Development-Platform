# 09. Feature-Level Documentation
> **Version:** 1.0 | **Created:** 2026-09-24 | **Last Updated:** 2026-09-24

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
- [`backend/ai/llm/client.py`](file:///Users/meetvirugama/Desktop/AI-Powered-Software-Development-Platform/backend/ai/llm/client.py) — `LLMGateway`
- [`backend/ai/llm/provider.py`](file:///Users/meetvirugama/Desktop/AI-Powered-Software-Development-Platform/backend/ai/llm/provider.py) — `LLMProvider` (abstract)
- [`backend/ai/llm/openai_provider.py`](file:///Users/meetvirugama/Desktop/AI-Powered-Software-Development-Platform/backend/ai/llm/openai_provider.py) — `OpenAIProvider`
- [`backend/ai/llm/schemas.py`](file:///Users/meetvirugama/Desktop/AI-Powered-Software-Development-Platform/backend/ai/llm/schemas.py) — `LLMRequest`, `LLMResponse`, error hierarchy

### External Services
- OpenAI Chat Completions API: `https://api.openai.com/v1/chat/completions`

### Business Rules
1. LLM Gateway is the ONLY place in the codebase that calls an LLM API.
2. Every LLM call MUST log: model, input_tokens, output_tokens, latency_ms, success/failure.
3. Max retries: 3. Backoff: 1s, 2s, 4s.
4. Default timeout: 30 seconds.

### Current Status
🟢 Fully implemented and tested. Tests in [`test_llm_gateway.py`](file:///Users/meetvirugama/Desktop/AI-Powered-Software-Development-Platform/backend/tests/test_llm_gateway.py).

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
- [`backend/ai/embeddings/service.py`](file:///Users/meetvirugama/Desktop/AI-Powered-Software-Development-Platform/backend/ai/embeddings/service.py) — `EmbeddingService`
- [`backend/ai/embeddings/client.py`](file:///Users/meetvirugama/Desktop/AI-Powered-Software-Development-Platform/backend/ai/embeddings/client.py) — `EmbeddingProvider` (abstract)
- [`backend/ai/embeddings/openai_provider.py`](file:///Users/meetvirugama/Desktop/AI-Powered-Software-Development-Platform/backend/ai/embeddings/openai_provider.py) — `OpenAIEmbeddingProvider`

### Business Rules
1. Never hard-code embedding dimensions — read from provider config.
2. Batch size capped at 100 (OpenAI limit is 2048, we cap for error recovery).
3. Dimension mismatch is non-retryable — requires human intervention.

### Current Status
🟢 Fully implemented. Tests in [`test_embedding_service.py`](file:///Users/meetvirugama/Desktop/AI-Powered-Software-Development-Platform/backend/tests/test_embedding_service.py).

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
- [`backend/ai/retrieval/vector.py`](file:///Users/meetvirugama/Desktop/AI-Powered-Software-Development-Platform/backend/ai/retrieval/vector.py) — `VectorRetriever`
- [`backend/ai/retrieval/base.py`](file:///Users/meetvirugama/Desktop/AI-Powered-Software-Development-Platform/backend/ai/retrieval/base.py) — `CodeChunk`, `Retriever`

### Database Tables
- `code_chunks` — reads only

### Business Rules
1. Every query MUST filter by `repository_id` — no cross-repository leakage.
2. `top_k` default = 30 (for RRF input).
3. Score formula: `score = max(0.0, 1.0 - distance)`.

### Current Status
🟢 Fully implemented. Tests in [`test_vector_retrieval.py`](file:///Users/meetvirugama/Desktop/AI-Powered-Software-Development-Platform/backend/tests/test_vector_retrieval.py).

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
- [`backend/ai/schemas/validator.py`](file:///Users/meetvirugama/Desktop/AI-Powered-Software-Development-Platform/backend/ai/schemas/validator.py) — `OutputValidator`

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
- [`backend/ai/schemas/prompt_builder.py`](file:///Users/meetvirugama/Desktop/AI-Powered-Software-Development-Platform/backend/ai/schemas/prompt_builder.py) — `PromptBuilder`
- [`backend/ai/prompts/repository_chat.txt`](file:///Users/meetvirugama/Desktop/AI-Powered-Software-Development-Platform/backend/ai/prompts/repository_chat.txt)
- [`backend/ai/prompts/context_summary.txt`](file:///Users/meetvirugama/Desktop/AI-Powered-Software-Development-Platform/backend/ai/prompts/context_summary.txt)
- [`backend/ai/prompts/source_grounding.txt`](file:///Users/meetvirugama/Desktop/AI-Powered-Software-Development-Platform/backend/ai/prompts/source_grounding.txt)

### Business Rules
1. Repository content is ALWAYS data — NEVER in the system prompt (prompt injection prevention).
2. Every prompt change requires a regression test.
3. Every prompt change must be reviewed by Dev.

### Current Status
🟢 Done. Two methods implemented: `build_chat_prompt` and `build_summary_prompt`.

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
- [`backend/scanner/walker.py`](file:///Users/meetvirugama/Desktop/AI-Powered-Software-Development-Platform/backend/scanner/walker.py) — `FileWalker`
- [`backend/scanner/symbols.py`](file:///Users/meetvirugama/Desktop/AI-Powered-Software-Development-Platform/backend/scanner/symbols.py) — `FileInfo`

### Business Rules
1. Scanner must never raise on malformed files — catch, log, skip.
2. Path traversal validation is scanner's responsibility.

### Current Status
🟢 Done. Tests in [`test_walker.py`](file:///Users/meetvirugama/Desktop/AI-Powered-Software-Development-Platform/backend/tests/test_walker.py).

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
- [`backend/indexer/chunker.py`](file:///Users/meetvirugama/Desktop/AI-Powered-Software-Development-Platform/backend/indexer/chunker.py) — `SymbolChunker`
- [`backend/indexer/models.py`](file:///Users/meetvirugama/Desktop/AI-Powered-Software-Development-Platform/backend/indexer/models.py) — `Chunk`

### Database Tables
- Produces data for `code_chunks` table

### Current Status
🟢 Done.

---

## Feature: Grounding Validator

**Status:** 🟢 Skeleton done (DB query stub) | **Priority:** P0 | **Owner:** Dev

### Purpose
Remove hallucinated file/line citations from LLM answers before they reach the user.

### Description
`GroundingValidator.validate_sources()` checks each `SourceReference` against the database:
1. File existence check (`repository_files.path`)
2. Line range validity check (`repository_files.line_count`)
3. Removes ungrounded sources from the answer
4. Downgrades confidence to "low" if >50% ungrounded

### Preconditions
- `repository_files` table populated (Om Day 3+)
- DB session injected

### Known Issues / Limitations
- DB query is a stub (`NotImplementedError`) until Om's `get_file_by_path` repository layer is available.
- With no DB session, all sources are treated as grounded (safe fallback).

### Backend Components
- [`backend/ai/schemas/grounding.py`](file:///Users/meetvirugama/Desktop/AI-Powered-Software-Development-Platform/backend/ai/schemas/grounding.py) — `GroundingValidator`, `GroundingResult`
- [`backend/ai/schemas/output.py`](file:///Users/meetvirugama/Desktop/AI-Powered-Software-Development-Platform/backend/ai/schemas/output.py) — `RepositoryAnswer`, `SourceReference`

### Database Tables
- `repository_files` — read-only (stub until Day 4)

### Current Status
🟢 Skeleton with logic; DB query pending Om's repository layer (Day 4).

---

## Feature: Context Builder

**Status:** 🔵 Stub (Day 6) | **Priority:** P0 | **Owner:** Meet

### Purpose
Assemble reranked code chunks + memory entries + conversation history into a single `AgentContext` for the LLM, enforcing token limits.

### Planned Flow
1. Deduplicate memory entries by ID
2. Sort memory by `created_at` desc
3. Count tokens per section (tiktoken)
4. Truncate chunks/memory if total > `max_context_tokens` (default: 100,000)
5. Set `ctx.total_tokens`
6. Return `AgentContext`

### Backend Components
- [`backend/ai/context/builder.py`](file:///Users/meetvirugama/Desktop/AI-Powered-Software-Development-Platform/backend/ai/context/builder.py) — `ContextBuilder`, `AgentContext`, `MemoryEntry`, `ChatMessage`, `RepositoryFile`

### Current Status
🔵 Stub — `NotImplementedError`. Planned for Day 6.

---

## Feature: RRF Fusion

**Status:** 🔵 Stub (Day 5) | **Priority:** P0 | **Owner:** Meet

### Purpose
Merge vector and lexical retrieval results using Reciprocal Rank Fusion (k=60).

### Algorithm
```
score(chunk) = Σ 1 / (k + rank_i)
```
Where k=60 and rank_i is the chunk's 1-based position in each result list.

### Backend Components
- [`backend/ai/retrieval/fusion.py`](file:///Users/meetvirugama/Desktop/AI-Powered-Software-Development-Platform/backend/ai/retrieval/fusion.py) — `RRFFusion`

### Current Status
🔵 Stub — `NotImplementedError`. Planned for Day 5.

---

## Feature: Cross-Encoder Reranker

**Status:** 🔵 Stub (Day 5) | **Priority:** P0 | **Owner:** Meet

### Purpose
Rerank top-30 RRF candidates to top-8 using a cross-encoder model that scores (query, chunk) pairs jointly.

### Model
`cross-encoder/ms-marco-MiniLM-L-6-v2` (sentence-transformers)

### Backend Components
- [`backend/ai/retrieval/reranker.py`](file:///Users/meetvirugama/Desktop/AI-Powered-Software-Development-Platform/backend/ai/retrieval/reranker.py) — `CrossEncoderReranker`

### Current Status
🔵 Stub — `NotImplementedError`. Planned for Day 5.

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

| Store | File | Purpose |
|---|---|---|
| `useAuthStore` | [`useAuthStore.ts`](file:///Users/meetvirugama/Desktop/AI-Powered-Software-Development-Platform/frontend/src/stores/useAuthStore.ts) | Auth state: user, isAuthenticated, login(), logout() |
| `useRepositoryStore` | [`useRepositoryStore.ts`](file:///Users/meetvirugama/Desktop/AI-Powered-Software-Development-Platform/frontend/src/stores/useRepositoryStore.ts) | UI state: selectedRepository, syncStatus |
| `useAppStore` | [`useAppStore.ts`](file:///Users/meetvirugama/Desktop/AI-Powered-Software-Development-Platform/frontend/src/stores/useAppStore.ts) | Global app state (TBD) |

### Route Protection
All `/app/*` routes are wrapped in `ProtectedRoute` — redirects to `/login` if not authenticated.

### Current Status
🔵 Skeleton structure in place. Real API integration pending backend endpoints.
