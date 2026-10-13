# 14. Changelog
> **Version:** 2.0 | **Created:** 2026-09-24 | **Last Updated:** 2026-09-28

---

## Changelog Format

```
[VERSION] YYYY-MM-DD — Description
Type: Feature | Fix | Refactor | Docs | Config | Breaking
Developer: <name>
Impact: What changes for other modules
Related Docs: Which documentation may need updating
```

---

## Week 1 Changes

---

### [W1-Day1] 2026-09-24 — Backend Skeleton
**Type:** Feature  
**Developer:** Yug  
**Changes:**
- FastAPI project created: `backend/app/main.py`
- `GET /api/v1/health` endpoint implemented
- `app/core/config.py` — `Settings` class with pydantic-settings
- `app/core/database.py` — SQLAlchemy engine, `Base`, `get_db()`
- `app/core/logging.py` — structured logging + `RequestIdMiddleware`
- `docker-compose.yml` — PostgreSQL 15 + pgvector, Redis 7
- `.env.example` — all required keys

**Impact:** All team members can now run the backend and depend on the `Settings` and `get_db()` interfaces.

**Related Docs:** `12_deployment_devops.md`, `08_api_documentation.md`

---

### [W1-Day1] 2026-09-24 — AI Architecture + LLM Interface Definitions
**Type:** Feature  
**Developer:** Meet  
**Changes:**
- `backend/ai/llm/` — `LLMRequest`, `LLMResponse`, `Message`, `LLMError` hierarchy, `LLMProvider` (abstract), `LLMGateway` skeleton
- `backend/ai/embeddings/` — `EmbeddingProvider` (abstract), `EmbeddingService` skeleton
- `backend/ai/retrieval/` — `Retriever` (abstract), `CodeChunk` dataclass
- `backend/ai/context/builder.py` — `AgentContext`, `ContextBuilder` skeleton
- `backend/ai/prompts/` — prompt template files created

**Impact:** Dev can implement AI schemas; Keval can write tests against AI interfaces.

**Related Docs:** `06_uml_diagrams.md`, `09_feature_documentation.md`

---

### [W1-Day1] 2026-09-24 — AI Schemas + Output Validation Skeleton
**Type:** Feature  
**Developer:** Dev  
**Changes:**
- `backend/ai/schemas/output.py` — `SourceReference`, `RepositoryAnswer`, `ErrorResponse`
- `backend/ai/schemas/validator.py` — `OutputValidator` skeleton (`validate()`, `repair()` stubs)
- `Docs/prompt_architecture.md` — system/data separation rule documented

**Impact:** Meet and others can use `RepositoryAnswer` as the final output contract.

**Related Docs:** `09_feature_documentation.md`, `02_requirements.md`

---

### [W1-Day1] 2026-09-24 — Scanner Architecture + FileWalker
**Type:** Feature  
**Developer:** Prit  
**Changes:**
- `backend/scanner/walker.py` — `FileWalker.walk()` fully implemented
- `backend/scanner/symbols.py` — `FileInfo`, `Symbol`, `SymbolEdge` dataclasses
- `backend/scanner/detector.py`, `parser.py`, `graph.py` — stubs

**Impact:** Divu's `SymbolChunker` can now consume `Symbol` objects.

**Related Docs:** `09_feature_documentation.md`, `07_database_documentation.md`

---

### [W1-Day1] 2026-09-24 — Indexer Architecture + SymbolChunker
**Type:** Feature  
**Developer:** Divu  
**Changes:**
- `backend/indexer/chunker.py` — `SymbolChunker.chunk_symbols()` fully implemented
- `backend/indexer/models.py` — `Chunk` dataclass

**Impact:** When scanner produces symbols, indexer can immediately create chunks.

**Related Docs:** `07_database_documentation.md`, `09_feature_documentation.md`

---

### [W1-Day1] 2026-09-24 — Frontend Foundation
**Type:** Feature  
**Developer:** Dhramraj  
**Changes:**
- Frontend Vite + React 19 + TypeScript project initialized
- `useAuthStore.ts` — auth state (user, isAuthenticated, login, logout)
- `useRepositoryStore.ts` — repository selection state
- `App.tsx` — routing with `ProtectedRoute`, `BrowserRouter`
- Pages: Login, Dashboard, Repositories, RepositoryDetail, RepositoryChat (skeletons)

**Impact:** All pages can now be developed independently using MSW mocks.

**Related Docs:** `09_feature_documentation.md`

---

### [W1-Day2] 2026-09-24 — LLM Gateway + OpenAI Provider (Full Implementation)
**Type:** Feature  
**Developer:** Meet  
**Changes:**
- `backend/ai/llm/client.py` — `LLMGateway` fully implemented (logging, retry delegation)
- `backend/ai/llm/openai_provider.py` — `OpenAIProvider` fully implemented
  - Retry: 3 attempts, exponential backoff (1s, 2s, 4s) on 429/5xx
  - Timeout: 30s per request
  - JSON mode support when `response_schema` provided
  - Token tracking from OpenAI `usage` field

**Impact:** Any module can now use `LLMGateway` for production LLM calls.

**Related Docs:** `09_feature_documentation.md`, `13_architecture_decisions.md` (ADR-001)

---

### [W1-Day2] 2026-09-24 — Output Validator + PromptBuilder (Full Implementation)
**Type:** Feature  
**Developer:** Dev  
**Changes:**
- `backend/ai/schemas/validator.py` — `OutputValidator.validate()` + `.repair()` fully implemented (2-retry repair loop using gpt-4o)
- `backend/ai/schemas/prompt_builder.py` — `PromptBuilder` fully implemented (`build_chat_prompt`, `build_summary_prompt`)

**Impact:** Meet can now use `PromptBuilder` in the RAG pipeline. Output validation available for all LLM response handlers.

**Related Docs:** `09_feature_documentation.md`, `13_architecture_decisions.md` (ADR-002)

---

### [W1-Day3] 2026-09-24 — Embedding Service (Full Implementation)
**Type:** Feature  
**Developer:** Meet  
**Changes:**
- `backend/ai/embeddings/service.py` — `EmbeddingService` fully implemented
  - Single embed with dimension validation
  - Batch embed: sub-batches of 100, async parallelism via `asyncio.gather`
- `backend/ai/embeddings/openai_provider.py` — `OpenAIEmbeddingProvider` implemented

**Impact:** `VectorRetriever` and indexer can now produce embeddings.

**Related Docs:** `09_feature_documentation.md`

---

### [W1-Day3] 2026-09-24 — GroundingValidator (Skeleton)
**Type:** Feature  
**Developer:** Dev  
**Changes:**
- `backend/ai/schemas/grounding.py` — `GroundingValidator` skeleton with full logic
  - `validate_sources()` implemented
  - DB query stubbed (`NotImplementedError`) until Om's `get_file_by_path` is available

**Impact:** Can be wired into chat pipeline immediately; DB check activates on Day 4.

**Related Docs:** `09_feature_documentation.md`

---

### [W1-Day4] 2026-09-24 — Vector Retriever (Full Implementation)
**Type:** Feature  
**Developer:** Meet  
**Changes:**
- `backend/ai/retrieval/vector.py` — `VectorRetriever` fully implemented
  - pgvector `<=>` cosine distance query scoped by `repository_id`
  - Score = `1 − cosine_distance` (clamped to [0, 1])
  - HNSW index used automatically by PostgreSQL query planner

**Impact:** Chat pipeline can now retrieve code chunks by semantic similarity.

**Related Docs:** `07_database_documentation.md` (HNSW index), `09_feature_documentation.md`

---

### [W1-Day5] 2026-09-24 — RRF Fusion + Cross-Encoder Reranker (Stubs)
**Type:** Feature (stub)  
**Developer:** Meet  
**Changes:**
- `backend/ai/retrieval/fusion.py` — `RRFFusion.fuse()` interface defined, implementation deferred to Day 5
- `backend/ai/retrieval/reranker.py` — `CrossEncoderReranker.rerank()` interface defined, implementation deferred to Day 5

**Impact:** Callers can depend on the interface; full implementation unlocks complete RAG pipeline.

**Related Docs:** `13_architecture_decisions.md` (ADR-004)

---

---

### [W1-Day5] 2026-09-28 — LexicalRetriever + RRFFusion + CrossEncoderReranker (Full Implementation)
**Type:** Feature  
**Developer:** Meet  
**Changes:**
- `backend/ai/retrieval/lexical.py` — `LexicalRetriever` fully implemented
  - PostgreSQL FTS using `to_tsquery` + `ts_rank` via GIN index on `code_chunks.content`
  - Query sanitization: strips non-alphanumeric, joins tokens with `&` operator
  - Scores normalised to [0, 1] by dividing by max rank in result set (CTE)
  - Graceful empty return if query has no searchable tokens
- `backend/ai/retrieval/fusion.py` — `RRFFusion` fully implemented
  - RRF formula: `score = sum(1 / (k + rank_i))` with k=60
  - Deduplicates by UUID, replaces `.score` with RRF score
  - Returns up to top-30 fused candidates
- `backend/ai/retrieval/reranker.py` — `CrossEncoderReranker` fully implemented
  - Model: `cross-encoder/ms-marco-MiniLM-L-6-v2` (lazy load on first use)
  - Batch-predicts logit scores for (query, chunk) pairs
  - Returns top-8 by descending score

**Impact:** Hybrid retrieval (vector + lexical + RRF + rerank) pipeline is now complete end-to-end.

**Related Docs:** `09_feature_documentation.md`, `13_architecture_decisions.md`

---

### [W1-Day6] 2026-09-28 — ContextBuilder (Full Implementation)
**Type:** Feature  
**Developer:** Meet  
**Changes:**
- `backend/ai/context/builder.py` — `ContextBuilder` fully implemented
  - Token counting via `tiktoken` (`cl100k_base` / GPT-4o compatible)
  - Memory de-duplication by id (last-write wins), sorted by `created_at` desc
  - Budget-aware truncation: history first (newest-to-oldest), then memory, then chunks
  - `render_repository_data()` serializes `AgentContext` into REPOSITORY DATA + MEMORY sections
  - `_OVERHEAD_TOKENS = 500` reserved for structural overhead
  - Logs: `context_built` event with token counts, chunks in/kept, memory in/kept

**Impact:** RAGPipeline can now assemble complete token-bounded context for LLM calls.

**Related Docs:** `09_feature_documentation.md`

---

### [W1-Day7] 2026-09-28 — RAGPipeline (Full End-to-End Integration)
**Type:** Feature  
**Developer:** Meet  
**Changes:**
- `backend/ai/pipeline.py` — `RAGPipeline` fully implemented
  - 7-step flow: retrieval → graceful fallback → context → prompt → LLM → grounding → answer
  - JSON repair loop (up to 2 attempts) with markdown fence stripping
  - Graceful degradation: zero retrieval returns `confidence=low` answer, never hallucinates
  - All dependencies injected at construction time (fully testable)
  - `LLMTimeoutError` / `LLMUnavailableError` mapped to `APIError(503, retryable=True)`
  - Logs: `rag_pipeline_complete` with chunks_used, total_tokens, sources before/after grounding

**Impact:** Full repository-aware chat is now available via the Chat API.

**Related Docs:** `09_feature_documentation.md`, `08_api_documentation.md`

---

### [W1-Day7] 2026-09-28 — Auth API (Full Implementation)
**Type:** Feature  
**Developer:** Yug  
**Changes:**
- `backend/app/api/v1/auth.py` — all 4 endpoints fully implemented
  - `GET /auth/github/login` — CSRF state + `oauth_state` httpOnly cookie (TTL 600s)
  - `GET /auth/github/callback` — code exchange, user upsert, JWT cookie issuance
  - `GET /auth/me` — returns current user from JWT
  - `POST /auth/logout` — JWT JTI added to Redis blocklist with remaining TTL
- `JWTMiddleware` — validates all non-auth routes automatically
- Standard error handler — `{error: {code, message, retryable}}` format

**Impact:** Full authentication flow is operational. All other APIs can now rely on JWT auth.

**Related Docs:** `08_api_documentation.md`, `09_feature_documentation.md`

---

### [W1-Day7] 2026-09-28 — Repositories API + Chat API (Full Implementation)
**Type:** Feature  
**Developer:** Yug  
**Changes:**
- `backend/app/api/v1/repositories.py` — 6 endpoints fully implemented
  - `GET /repositories` — list by authenticated user
  - `GET /repositories/{id}` — ownership-validated detail
  - `POST /repositories/{id}/sync` — 202 Accepted + job_id
  - `POST /repositories/{id}/search` — hybrid search via RAG pipeline
  - `GET /repositories/{id}/files` — paginated file list
  - `GET /repositories/{id}/symbols` — paginated symbol list
- `backend/app/api/v1/chat.py` — `POST /repositories/{id}/chat` fully implemented
  - Delegates to `RAGPipeline.chat()` via `app.state.rag_pipeline`
  - Validates `RepositoryAnswer` at HTTP boundary via `model_validate`

**Impact:** Complete backend API surface for Week 1 is now operational.

**Related Docs:** `08_api_documentation.md`, `09_feature_documentation.md`

---

### [W1-Day7] 2026-09-28 — Database Models (Full Implementation)
**Type:** Feature  
**Developer:** Om  
**Changes:**
- All SQLAlchemy models implemented in `backend/app/models/`:
  - `User`, `GitHubInstallation`, `Repository` (+ `SyncStatus` enum)
  - `RepositoryFile`, `CodeSymbol`, `SymbolEdge`, `CodeChunk`
  - `SyncJob` (+ `SyncJobStatus` enum), `MemoryEntry` (+ `MemoryType`, `MemoryStatus`)
- Repository and User query layers implemented in `backend/app/repositories/`
- `backend/app/services/repository_sync.py` — `RepositorySyncService` + `RedisSyncJobQueue`

**Impact:** All API endpoints can now read/write from the database.

**Related Docs:** `07_database_documentation.md`

---

### [W1-Day7] 2026-09-28 — Test Suite Expansion (26+ Tests)
**Type:** Feature  
**Developer:** Keval  
**Changes:**
- `backend/tests/test_hybrid_retrieval.py` — LexicalRetriever, RRFFusion, CrossEncoderReranker
- `backend/tests/test_context_builder.py` — ContextBuilder token budget + truncation (14 tests)
- `backend/tests/test_rag_pipeline.py` — RAGPipeline end-to-end (26 tests):
  - Happy path, zero retrieval, error handling, JSON repair loop, normalise history
  - Acceptance test: "Where is authentication?" returns grounded answer
- `backend/tests/test_auth.py` — Auth API
- `backend/tests/test_auth_and_repositories_api.py` — Auth + repo API integration
- `backend/tests/test_repositories.py` — Repository API
- `backend/tests/test_repository_chat_api.py` — Chat API
- `backend/tests/test_repository_search_api.py` — Search API
- `backend/tests/test_repository_sync_service.py` — Sync service
- `backend/tests/test_repository_isolation.py` — Cross-repo isolation
- Various: `test_ai_errors.py`, `test_detector.py`, `test_github_mocks.py`, `test_test_infra.py`, `test_test_mapper.py`

**Impact:** High test coverage across all Week 1 deliverables.

**Related Docs:** `11_testing_qa.md`

---

## Documentation Changelog

| Date | Document | Change | Author |
|---|---|---|---|
| 2026-09-28 | `08_api_documentation.md` | Updated all endpoints to Done, added search/files/symbols/chat | Documentation system |
| 2026-09-28 | `09_feature_documentation.md` | Updated all features to Done, added RAGPipeline, Auth API, Repos API, Chat API | Documentation system |
| 2026-09-28 | `05_system_architecture.md` | Updated module ownership table to reflect actual implementation state | Documentation system |
| 2026-09-28 | `00_dashboard.md` | Updated feature status, progress to ~90%, recent changes | Documentation system |
| 2026-09-28 | `10_development_tasks.md` | All W1 AI/API tasks updated to DONE | Documentation system |
| 2026-09-28 | `11_testing_qa.md` | Updated test suite status with all new test files | Documentation system |
| 2026-09-24 | All `Docs/engineering/` files | Initial creation of complete documentation system | Documentation system |
