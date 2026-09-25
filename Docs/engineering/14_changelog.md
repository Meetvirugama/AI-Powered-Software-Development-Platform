# 14. Changelog
> **Version:** 1.0 | **Created:** 2026-09-24 | **Last Updated:** 2026-09-24

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

## Documentation Changelog

| Date | Document | Change | Author |
|---|---|---|---|
| 2026-09-24 | All `Docs/engineering/` files | Initial creation of complete documentation system | Documentation system |
