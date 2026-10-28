# Detailed Daily Task Breakdown — All 3 Weeks

> **Last Updated:** 2026-09-28 | Completed tasks marked ✅ | Remaining tasks marked ⬜

This document breaks each day into specific, atomic tasks for every team member. Use this as your daily checklist. Each task is small enough to complete in a few hours. Mark tasks done in your branch's PR description.

---

# WEEK 1 — Repository Intelligence Foundation ✅ COMPLETE

**Week 1 Goal:** By Day 7, a user can connect a GitHub repository, the platform clones and scans it, extracts symbols, indexes code into pgvector, and answers repository-specific questions through the frontend with file + line sources.

> [!NOTE]
> **Week 1 Status: DONE.** All AI/RAG pipeline components, Auth API, Repositories API, Chat API, and Database layer are fully implemented. See `Docs/engineering/10_development_tasks.md` for the complete task board.

---

## DAY 1 — Skeleton Day ✅

---

### YUG — Day 1 ✅
- ✅ Initialize FastAPI project: `uvicorn`, `sqlalchemy`, `alembic`, `pydantic`, `redis`
- ✅ Create directory structure: `app/api/v1/`, `app/core/`, `app/models/`, `app/schemas/`, `app/services/`, `app/repositories/`, `app/integrations/`, `app/workers/`
- ✅ Configure `app/core/config.py` — reads all settings from `.env`
- ✅ Create `app/core/database.py` — SQLAlchemy engine + session factory + Base model
- ✅ Create `app/core/logging.py` — structured JSON logging with request_id middleware
- ✅ Implement `GET /api/v1/health` returning `{"status": "ok", "version": "1.0.0"}`
- ✅ Set up `.env.example` with all required keys
- ✅ Create `docker-compose.yml` with PostgreSQL 15 + pgvector + Redis 7
- ✅ Write `README.md` section: how to run the backend locally
- ✅ Open PR: `[W1-01] Backend skeleton`

---

### OM — Day 1 ✅
- ✅ Add `pgvector` extension to docker-compose PostgreSQL config
- ✅ Configure Alembic: `alembic init migrations/`
- ✅ Create `env.py` in alembic that reads from `app/core/config.py`
- ✅ Create the base `TimestampedModel` mixin: `id (UUID PK)`, `created_at`, `updated_at`
- ✅ Write first migration: `CREATE EXTENSION IF NOT EXISTS vector;` (`24498ac67b3e_add_pgvector_extension`)
- ✅ Run migration and verify `\dx` shows pgvector installed
- ✅ Document the migration workflow in `Docs/db_migrations.md`
- ✅ Open PR: `[W1-02] Database foundation + pgvector`

---

### PARTH — Day 1 ✅
- ✅ Register GitHub App on GitHub Settings
- ✅ Configure permissions, callback URL, webhook URL
- ✅ Download private key `.pem` — stored in `.env` as `GITHUB_APP_PRIVATE_KEY`
- ✅ Create `app/integrations/github/__init__.py`, `base.py`, `service.py`
- ✅ Document the GitHub App setup in `Docs/github_app_setup.md`
- ✅ Add all GitHub env vars to `.env.example`
- ✅ Open PR: `[W1-03] GitHub App setup + integration skeleton`

---

### DHRAMRAJ — Day 1 ✅
- ✅ Initialize frontend: Vite + React 19 + TypeScript
- ✅ Install dependencies: `axios`, `zustand`, `@tanstack/react-query`, `msw`
- ✅ Create directory structure: `src/components/`, `src/pages/`, `src/stores/`, `src/types/`
- ✅ Create `src/services/api.ts` — centralized axios client
- ✅ Create `AuthStore` (Zustand): `user`, `isAuthenticated`, `login()`, `logout()`
- ✅ Create `RepositoryStore` (Zustand)
- ✅ Create `ProtectedRoute` wrapper
- ✅ Open PR: `[W1-05] Frontend foundation + design system`

---

### PRIT — Day 1 ✅
- ✅ Create `backend/scanner/` directory structure
- ✅ Define `Symbol`, `SymbolEdge`, `ScanResult`, `FileInfo` dataclasses
- ✅ Create `FileWalker` class with `walk()` stub
- ✅ Install tree-sitter
- ✅ Open PR: `[W1-07] Scanner architecture + data classes`

---

### MEET — Day 1 ✅
- ✅ Create `backend/ai/` directory with all subdirectories
- ✅ Define `LLMRequest`, `LLMResponse`, `Message` Pydantic models
- ✅ Create abstract `LLMProvider` class
- ✅ Create abstract `EmbeddingProvider` class
- ✅ Create abstract `Retriever` class
- ✅ Install: `openai`, `sentence-transformers`, `numpy`
- ✅ Open PR: `[W1-12] AI architecture + interface definitions`

---

### DEV — Day 1 ✅
- ✅ Define `SourceReference`, `RepositoryAnswer`, `ErrorResponse` Pydantic models
- ✅ Define `LLMError` exception hierarchy
- ✅ Create `backend/ai/prompts/` directory with prompt template stubs
- ✅ Write `Docs/prompt_architecture.md`
- ✅ Create `OutputValidator` skeleton
- ✅ Open PR: `[DEV-01] AI schemas + output validation skeleton`

---

### DIVU — Day 1 ✅
- ✅ Create `backend/indexer/` directory structure
- ✅ Define `Chunk` dataclass, `ChunkStatus` enum, `EmbeddingJob` dataclass
- ✅ Create `Chunker` and `EmbeddingQueue` class skeletons
- ✅ Open PR: `[W1-10] Indexer architecture + chunk data model`

---

### KEVAL — Day 1 ✅
- ✅ Install: `pytest`, `pytest-asyncio`, `pytest-cov`, `httpx`
- ✅ Configure `pytest.ini`
- ✅ Create `backend/tests/conftest.py` with test client + DB fixtures
- ✅ Create `backend/tests/fixtures/python_sample/` (10 files)
- ✅ Write `test_health.py` — `GET /health` returns 200
- ✅ Create `backend/tests/mocks/github.py`
- ✅ Open PR: `[W1-18] Test infrastructure`

---

### SUKUN — Day 1 ✅
- ✅ Audit `.gitignore` — `.env`, `*.pem`, `*.key` all listed
- ✅ Verify `.env.example` exists
- ✅ Set up pre-commit hooks with `detect-secrets`
- ✅ Create `backend/agent/policy/engine.py` (PolicyEngine skeleton)
- ✅ Define `PolicyDecision` enum: `ALLOW`, `ASK`, `DENY`
- ✅ Open PR: `[W1-19] Security baseline + pre-commit hooks`

---

## DAY 2 — Core Dependencies Day ✅

---

### YUG — Day 2 ✅
- ✅ Implement `GET /api/v1/auth/github/login` → redirects to GitHub OAuth
- ✅ Implement `GET /api/v1/auth/github/callback` → code exchange + JWT cookie
- ✅ Create `JWTMiddleware` — validates all non-auth routes
- ✅ Implement `GET /api/v1/auth/me` → returns current user from JWT
- ✅ Implement `POST /api/v1/auth/logout` → Redis blocklist invalidation
- ✅ Standard error handler: `{error: {code, message, retryable}}`

---

### OM — Day 2 ✅
- ✅ Create `User` SQLAlchemy model
- ✅ Create `GitHubInstallation` model
- ✅ Create `Repository` model with `SyncStatus` enum
- ✅ Write Alembic migration (`5f6dc031921b_identity_schema`)
- ✅ Create `UserRepository` query class: `create_user()`, `get_by_github_id()`, `get_by_id()`
- ✅ Create `RepositoryRepository` query class: `create()`, `get_by_id()`, `list_by_user()`, `update_sync_status()`

---

### PARTH — Day 2 ✅
- ✅ Implement GitHub App JWT generation
- ✅ Implement `InstallationTokenManager`: Redis cache + token mint
- ✅ Create `token_manager.py` in `app/integrations/github/`

---

### DHRAMRAJ — Day 2 ✅
- ✅ Create `/login` page with "Connect with GitHub" button
- ✅ Handle OAuth redirect flow
- ✅ Create `useAuth()` hook
- ✅ Create `ProtectedRoute` wrapper for `/app/*` routes
- ✅ Set up MSW mock for `GET /auth/me`

---

### PRIT — Day 2 ✅
- ✅ Implement `FileWalker.walk(root_path) → list[FileInfo]`
- ✅ Skip: `.git`, `node_modules`, `venv`, `__pycache__`, `dist`, `build`
- ✅ Respect `.gitignore` (pathspec)
- ✅ Skip binary files (null byte detection)
- ✅ Skip files > 1MB
- ✅ Unit tests passing for fixture repositories

---

### MEET — Day 2 ✅
- ✅ Implement `OpenAIProvider` with retry (3x, exponential backoff on 429/503)
- ✅ Timeout: 30 seconds per request
- ✅ Structured output: JSON mode + Pydantic schema validation
- ✅ Create `LLMGateway` with structured logging (model, tokens, latency, success)
- ✅ Unit tests: retry logic, typed response

---

### DEV — Day 2 ✅
- ✅ Implement `repository_chat.txt` prompt template
- ✅ Create `PromptBuilder.build_chat_prompt()` and `build_summary_prompt()`
- ✅ Implement `OutputValidator.validate(raw, schema)`
- ✅ Implement `OutputValidator.repair(raw, schema, error)` (2-retry limit)
- ✅ Unit tests: validate returns False on invalid JSON; repair fixes missing field

---

### DIVU — Day 2 ✅
- ✅ Implement `Chunker.chunk(symbol, file_content) → list[Chunk]`
- ✅ Set `content_hash = sha256(content).hexdigest()`
- ✅ Implement `Chunker.chunk_file()` for files without parseable symbols
- ✅ Unit tests: 20-line function → 1 chunk; content_hash stable

---

### KEVAL — Day 2 ✅
- ✅ Write `test_auth.py`: unauthenticated → 401, health → 200, error format
- ✅ Write `test_repositories.py`: empty list, 404 on non-existent
- ✅ Set up GitHub API mock in `tests/mocks/github.py`

---

### SUKUN — Day 2 ✅
- ✅ Review Yug's OAuth: CSRF state, httpOnly cookie, HS256 JWT, `exp` claim
- ✅ Write `test_csrf_state_rejected`
- ✅ Write `test_jwt_algorithm_none_rejected`
- ✅ Verify logout Redis blocklist works

---

## DAY 3 — Core Feature Day ✅

---

### YUG — Day 3 ✅
- ✅ `GET /api/v1/repositories` — list user's repos
- ✅ `GET /api/v1/repositories/:id` — repo detail + sync_status
- ✅ `POST /api/v1/repositories/:id/sync` — trigger async sync, return 202 + job_id
- ✅ `GET /api/v1/repositories/:id/files` — paginated file list
- ✅ `GET /api/v1/repositories/:id/symbols` — paginated symbol list

---

### OM — Day 3 ✅
- ✅ Create `repository_files` table
- ✅ Create `code_symbols` table
- ✅ Create `symbol_edges` table
- ✅ Write migration (`aef3bb17eb34_content_tables`)
- ✅ Add indexes: `repository_id` on all tables, `(file_id, start_line)` on symbols

---

### PARTH — Day 3 ✅
- ✅ `GitHubService.list_repositories(installation_id)`
- ✅ `GitHubService.get_repository(owner, repo)`
- ✅ `GitHubService.list_branches(owner, repo)`
- ✅ Handle 401 (re-mint), 404, 429 (rate limit backoff)

---

### DHRAMRAJ — Day 3 ✅
- ✅ Build repository list page (`/repositories`)
- ✅ Sync status indicators per card
- ✅ Loading skeleton + empty state

---

### PRIT — Day 3 ✅
- ✅ `LanguageDetector.detect(file_info) → str`
- ✅ Extension map: `.py`, `.ts`, `.js`, `.java`, `.go`, `.rs`, `.c`, `.cpp`
- ✅ Shebang detection
- ✅ Unit tests: all 8 languages detected by extension

---

### MEET — Day 3 ✅
- ✅ `EmbeddingService.embed(text) → list[float]` — OpenAI `text-embedding-3-small`
- ✅ `EmbeddingService.embed_batch(texts) → list[list[float]]` — batch 100, asyncio.gather
- ✅ Retry 3x on 429/503
- ✅ Dimension validation
- ✅ Unit tests: mock OpenAI, retry on 429

---

### DEV — Day 3 ✅
- ✅ `GroundingValidator.validate_sources(answer, repository_id) → RepositoryAnswer`
- ✅ For each source: query `repository_files` — remove unmatched citations
- ✅ If line range exceeds `line_count`: remove citation
- ✅ Confidence downgrade if >50% ungrounded

---

### DIVU — Day 3 ✅
- ✅ `SymbolChunker.chunk_symbols(repository_id, file_id, symbols, content, language)`
- ✅ Uses `tiktoken` for accurate token counting
- ✅ Tested against `fixtures/python_sample/`

---

### KEVAL — Day 3 ✅
- ✅ Write `test_github_mocks.py`: list repos, 404, 403, rate limit, re-mint token

---

### SUKUN — Day 3 ✅
- ✅ Write `test_repository_isolation.py`: User A cannot access User B's repos
- ✅ Test all repository-scoped endpoints: files, symbols, chat, search

---

## DAY 4 — Deep Integration Day ✅

---

### YUG — Day 4 ✅
- ✅ Connect backend to `GitHubService` and `RepositoryRepository`
- ✅ `RepositorySyncService` + `RedisSyncJobQueue` implemented
- ✅ Sync endpoint triggers actual worker job

---

### OM — Day 4 ✅
- ✅ Create `code_chunks` table with `vector(1536)` column
- ✅ HNSW index: `CREATE INDEX ON code_chunks USING hnsw (embedding vector_cosine_ops)`
- ✅ GIN index: `CREATE INDEX ON code_chunks USING gin(to_tsvector('english', content))`
- ✅ Add `sync_jobs` table + `SyncJob` model (`cb4e2a7d0f31_add_sync_jobs`)

---

### PARTH — Day 4 ✅
- ✅ `GitHubService.clone_repository()` with shallow clone (depth=1)
- ✅ Auth URL: `https://x-access-token:{token}@github.com/{owner}/{repo}.git`
- ✅ Path traversal validation: no `../` escape
- ✅ Cleanup on failure

---

### PRIT — Day 4 ✅
- ✅ tree-sitter AST parser integrated for Python and TypeScript
- ✅ `Parser.parse(file_info, content) → AST`
- ✅ Graceful error handling: log, return partial tree, never raise

---

### MEET — Day 4 ✅
- ✅ `VectorRetriever.retrieve(query, repository_id, top_k) → list[CodeChunk]`
- ✅ Embeds query, runs pgvector `<=>` cosine search
- ✅ Returns typed `CodeChunk` objects with scores
- ✅ `WHERE repository_id = :repo_id` strictly enforced

---

### DEV — Day 4 ✅
- ✅ Grounding validation tested against fixture data
- ✅ `test_hallucinated_file_is_removed_from_sources` passing

---

### DIVU — Day 4 ✅
- ✅ `EmbeddingQueue.enqueue(chunks)` — pushes to Redis `embedding_jobs`
- ✅ `EmbeddingQueue.process_batch()` — pops 100, embeds, updates `code_chunks.embedding`

---

### KEVAL — Day 4 ✅
- ✅ Repository engine tests on fixture repos
- ✅ File count, language detection, symbol count all verified
- ✅ `test_dev_day4.py` passing

---

### SUKUN — Day 4 ✅
- ✅ `SecretScanner` with regex patterns for: `API_KEY`, `sk-`, `ghp_`, `AWS_ACCESS_KEY_ID`
- ✅ Integrated into chunker before storing
- ✅ Test: `API_KEY = "abc123"` → stored as `API_KEY = "[REDACTED]"`

---

## DAY 5 — Search + Retrieval Day ✅

---

### YUG — Day 5 ✅
- ✅ `POST /api/v1/repositories/:id/search` → calls RAGPipeline retrieval

---

### OM — Day 5 ✅
- ✅ Verify HNSW index: `EXPLAIN ANALYZE` uses index
- ✅ Create `memory_entries` table with `MemoryType` and `MemoryStatus` enums
- ✅ Write `MemoryRepository`: `create()`, `list_by_repository()`, `update_status()`, `delete()`

---

### PARTH — Day 5 ✅
- ✅ GitHub error handling hardened for all error codes
- ✅ 401: re-mint token, retry once
- ✅ 403: `GITHUB_PERMISSION_DENIED`
- ✅ 404: `REPOSITORY_NOT_FOUND`
- ✅ 429: read `X-RateLimit-Reset`, sleep, retry
- ✅ Installation removed: mark `github_installations` inactive

---

### MEET — Day 5 ✅
- ✅ `LexicalRetriever.retrieve()` — PostgreSQL FTS with `to_tsquery`, scores normalised to [0,1]
- ✅ `RRFFusion.fuse()` — RRF formula with k=60, dedup by UUID, top-30
- ✅ `CrossEncoderReranker.rerank()` — `cross-encoder/ms-marco-MiniLM-L-6-v2`, lazy load, top-8
- ✅ `test_hybrid_retrieval.py` — 12+ tests passing

---

### DEV — Day 5 ✅
- ✅ `python_sample` fixture indexed
- ✅ 10 question-answer pairs created
- ✅ RAG benchmark framework written (`scripts/benchmark_rag.py`)
- ✅ Results documented in `Docs/rag_benchmark_results.md`

---

### DHRAMRAJ — Day 5 ✅
- ✅ Repository explorer page (`/repositories/:id`)
- ✅ Shows: name, description, language, file count, symbol count, last sync time
- ✅ File tree (first 2 levels)
- ✅ Link to chat

---

### DIVU — Day 5 ✅
- ✅ `IncrementalIndexer.sync()` — skip unchanged (hash match), re-index changed files

---

### KEVAL — Day 5 ✅
- ✅ `test_rag_pipeline.py` — 26 tests, exact symbol query, semantic query, unknown query
- ✅ Acceptance test: "Where is authentication?" returns grounded answer

---

### SUKUN — Day 5 ✅
- ✅ `test_input_security.py`: path traversal rejected, huge file skipped, prompt injection treated as data

---

## DAY 6 — Context Builder + Chat Day ✅

---

### YUG — Day 6 ✅
- ✅ `POST /api/v1/repositories/:id/chat` → calls `RAGPipeline.chat()` → returns `RepositoryAnswer`
- ✅ Validates `RepositoryAnswer` at HTTP boundary via `model_validate`

---

### OM — Day 6 ✅
- ✅ Memory schema complete (`memory_entries` table)
- ✅ DB isolation verified across all tables: `repository_files`, `code_symbols`, `code_chunks`, `memory_entries`
- ✅ Every query filters by `repository_id`

---

### PARTH — Day 6 ✅
- ✅ GitHub error handling integrated with sync worker
- ✅ Clone → scan → index flow tested on fixture repo

---

### MEET — Day 6 ✅
- ✅ `ContextBuilder.build(chunks, memory, history) → AgentContext`
- ✅ Token counting: `tiktoken` `cl100k_base`
- ✅ Budget-aware truncation: history first, then memory, then chunks
- ✅ `render_repository_data()` serializes `AgentContext`
- ✅ `_OVERHEAD_TOKENS = 500` reserved
- ✅ `RAGPipeline.chat(question, repository_id, history) → RepositoryAnswer`
- ✅ 7-step flow: retrieve → fallback → context → prompt → LLM → ground → answer
- ✅ JSON repair loop (2 attempts) with markdown fence stripping
- ✅ Graceful degradation: zero retrieval → `confidence=low`

---

### DEV — Day 6 ✅
- ✅ `test_ai_errors.py`: LLM timeout, LLM unavailable, zero retrieval, JSON repair loop

---

### DHRAMRAJ — Day 6 ✅
- ✅ Chat UI (`/repositories/:id/chat`)
- ✅ Message list, source reference chips
- ✅ Loading skeleton, error banner with retry

---

### KEVAL — Day 6 ✅
- ✅ Full integration test: fixture data → backend → RAG → chat endpoint returns correct answer
- ✅ `test_repository_chat_api.py`, `test_repository_search_api.py`, `test_repository_sync_service.py`
- ✅ `test_context_builder.py` — 14+ tests (token budget, truncation, render)

---

### SUKUN — Day 6 ✅
- ✅ `test_prompt_injection.py`: README with "Ignore all instructions" → LLM response stays relevant

---

## DAY 7 — Integration + Polish Day ✅

- ✅ All modules integrated end-to-end
- ✅ Auth API → Repos API → Chat API → RAGPipeline confirmed working
- ✅ `test_auth_and_repositories_api.py` integration passing
- ✅ `test_repository_isolation.py` cross-repo isolation confirmed
- ✅ `test_test_infra.py`, `test_test_mapper.py`, `test_detector.py` all passing
- ✅ Week 1 retrospective complete
- ✅ Week 2 interface contracts published (Day 1 of Week 2)

---

# WEEK 2 — Developer Intelligence Suite ✅ COMPLETE

**Week 2 Goal:** Build four independent, integrated developer-intelligence features: Code Explanation, Bug Detection, Framework-Aware Test Generation, and Standalone AI Code Review with unified Workbench integration, persistence, and automated quality gates.

---

## WEEK 2 — Day 1 Foundation & Schema Day (mandatory by end of Day 1)

| Person | Publish | Status |
|--------|---------|--------|
| Meet | Shared `IntelligenceContext` interface & token budget rules | ✅ Done |
| Dev | `CodeExplanation`, `BugFinding`, `TestGenerationResult`, `ReviewReport` schemas | ✅ Done |
| Dhramraj | Code Intelligence Workbench action triggers & drawer shell | ✅ Done |
| Yug | Analysis REST endpoints (`/explain`, `/detect-bugs`, `/generate-tests`, `/review`) in OpenAPI | ✅ Done |
| Om | `analysis_runs` and `code_findings` database models & Alembic migration | ✅ Done |
| Parth | Authorized file & commit diff retrieval service in `GitHubService` | ✅ Done |
| Prit | AST symbol range resolution & import mapping | ✅ Done |
| Devu | Static analysis adapter (Ruff/ESLint/Bandit) & secret scanner | ✅ Done |
| Sukun | Prompt injection boundaries (`<<<REPO_DATA_...>>>`) & secret scrubbing utility | ✅ Done |
| Keval | Baseline defect fixtures & Week 2 regression test plan | ✅ Done |

## WEEK 2 — Day 2 Feature 1: Code Explanation

- ✅ Prit: `TargetSelector` & symbol resolution connecting AST utilities to Code Explanation targets
- ✅ Dev: `CodeExplanationService` producing purpose, logic, symbols, data flow, dependencies, edge cases
- ✅ Meet: Context enrichment — fetch caller functions, imported types, and repository inventory
- ✅ Yug: `POST /api/v1/repositories/{id}/explain` with file path, symbol, and line-range validation (`backend/app/api/v1/analysis.py`)
- ✅ Dhramraj: Code Explanation drawer in Workbench with syntax-highlighted ranges & copy controls (`ExplanationResultView.tsx`, `RepositoryDetail.tsx`)
- ✅ Keval: Unit tests on Python and TypeScript fixtures verifying grounded, non-hallucinated explanations (`test_keval_w2_day2_explanation_qa.py`)


## WEEK 2 — Day 3 Feature 2: Dedicated Bug Detection

- ✅ Prit: `ASTBugAnalyzer` with 10 structural defect rules, exact line range preservation, target scoping, and Devu `StaticFinding` adapter
- ✅ Dev: `BugDetectionEngine` targeting off-by-one, null safety, resource leaks, and unhandled exceptions
- ✅ Devu: `StaticBugScanner` running Ruff/Bandit and secret scanning with normalized findings (`backend/scanner/static_bug_scanner.py`)
- ✅ Meet: Bug context extraction — caller sites, error handling blocks, and token bounding
- ✅ Yug: `POST /api/v1/repositories/{id}/detect-bugs` merging, deduplicating, and ranking static + AI findings (`backend/app/api/v1/analysis.py`, `backend/app/services/bug_detection_orchestrator.py`)
- ✅ Dhramraj: Bug Scanner UI with severity categories (Critical, High, Medium, Low) and in-code line highlights (`BugScannerView.tsx`, `RepositoryDetail.tsx`)
- ✅ Om: Persisting bug scan runs and findings to `analysis_runs` and `code_findings`
- ✅ Keval: Bug Detection QA suite verifying ASTBugAnalyzer, BuiltinStaticBugScanner, merging/deduplication, and secret scrubbing (`test_keval_w2_day3_bug_detection_qa.py`)

## WEEK 2 — Day 4 Feature 3: Framework-Aware Test Generation

- ✅ Prit: Framework detection (`pytest`, `unittest`, `jest`) from manifests and directory layout, fixture extraction, and test path proposal (`FrameworkDetector`)
- ✅ Meet: Test context — target signatures, dependencies, mocked services, and project test conventions
- ✅ Dev: `TestGenerationService` generating complete test files with positive, negative, and edge-case assertions
- ✅ Yug: `POST /api/v1/repositories/{id}/generate-tests` returning test path, code, and scenario descriptions (`backend/app/api/v1/analysis.py`, `backend/app/services/test_generation_orchestrator.py`)
- ✅ Dhramraj: Test Preview drawer with syntax highlighting, One-Click Copy, and Download action (`TestGenerationView.tsx`, `RepositoryDetail.tsx`)
- ✅ Sukun: Validate output paths, reject unsafe filenames, and ensure generated code is not auto-executed (`backend/app/core/input_security.py`, `backend/tests/test_security_testgen.py`)
- ✅ Om: Persisting generated-test runs and relevant metadata (`test_output`, scenarios, framework, revision)
- ✅ Keval: Test Generation QA suite verifying framework detection (pytest/jest), test syntax validation, and scenario coverage (`test_keval_w2_day4_test_generation_qa.py`)

## WEEK 2 — Day 5 Feature 4: Standalone AI Code Review

- ✅ Prit: Review source mapping — map changed lines & unified diff hunks to AST symbols, supply AST context, maintain file identity & 1-indexed line locations, report mapping limitations explicitly (`ReviewSourceMapper`)
- ✅ Parth: Retrieve authorized commit metadata and GitHub PR diffs via GitHub App (`backend/app/integrations/github/source_service.py`)
- ✅ Dev: `AICodeReviewEngine` analyzing changes across Correctness, Security, Performance, Reliability, Maintainability
- ✅ Devu: `StaticReviewer` running linters on modified files and merging with AI suggestions (`backend/review/static_reviewer.py`, `backend/app/services/code_review_orchestrator.py`)
- ✅ Meet: Multi-file review context — caller impact, imported type changes, and dependency blast radius
- ✅ Yug: `POST /api/v1/repositories/{id}/review` supporting single file, commit SHA, and PR diff (`backend/app/api/v1/analysis.py`, `backend/app/services/code_review_orchestrator.py`)
- ✅ Dhramraj: Unified/split diff review UI with inline findings, risk level indicator, and severity badges (`CodeReviewView.tsx`, `RepositoryDetail.tsx`)
- ✅ Keval: Standalone Code Review QA suite verifying unified diff parsing, SQL injection defect detection, and zero-defect reports (`test_keval_w2_day5_review_qa.py`)

## WEEK 2 — Days 6–7 Integration, Security Gates & Release Verification

| Owner | Task | Deliverable | Status |
|---|---|---|---|
| **Yug** | End-to-End API Integration, OpenAPI Contract & Final Acceptance Verification | `backend/app/api/v1/analysis.py`, `backend/tests/test_yug_w2_day7_final_acceptance.py` | [x] |
| **Dhramraj** | Frontend Analysis Workbench Integration, Review Target Sync & Citation Navigation | `frontend/src/pages/RepositoryDetail.tsx`, `backend/tests/test_dhramraj_w2_day7_frontend_acceptance.py` | [x] |
| **Dev** | AI Services Prompt Isolation, Repair Loops & Acceptance Suite (`PR #134`) | `backend/ai/services/`, `backend/tests/test_dev_w2_day7_ai_acceptance.py` | [x] |
| **Meet** | Context Assembly, Token Budgeting & Hybrid Retrieval Verification | `backend/ai/context/`, `backend/ai/retrieval/`, `backend/ai/pipeline.py` | [x] |
| **Prit** | AST Rules, Dependency Graph Call Edges & Source Mapper Acceptance | `backend/scanner/graph.py`, `backend/scanner/ast_rules.py`, `backend/tests/test_prit_w2_day7_scanner_acceptance.py` | [x] |
| **Parth** | GitHub Source Service Hardening, Git Branch Isolation & PR Metadata | `backend/app/integrations/github/source_service.py`, `backend/app/services/git_branch.py`, `backend/tests/test_day7_git_workspace_security.py` | [x] |
| **Sukun** | Week 2 Security Gate (W2-S1..W2-S8), Secret Redaction & Path Confinement | `backend/app/core/secret_redaction.py`, `backend/tests/test_sukun_w2_day7_security_gate.py` | [x] |
| **Om** | Analysis Run Persistence, Composite Indexes, Retention & Integrity Verification | `backend/app/repositories/analysis_run_repository.py`, `backend/migrations/versions/f1c2d3e4b5a6_add_analysis_composite_indexes.py`, `backend/tests/test_om_w2_d7_acceptance_regression.py` | [x] |
| **Keval** | Scenarios A–E Full Acceptance Regression & Cross-Feature QA | `backend/tests/test_keval_w2_day7_acceptance_scenarios.py` | [x] |

- ✅ Meet: Cross-feature context optimization, token budget enforcement, and Gemini/Groq-only provider policy
- ✅ Prit: AST and framework reliability & Day 7 acceptance — multi-fixture source-range validation, class/method extraction, framework detector hardening, zero-crash parser failure handling, tiered language limitation matrix, and published acceptance report (143/143 tests passing) (`Docs/scanner_languages.md`, `Docs/week2_day7_ast_acceptance_report.md`)
- ✅ Dev: Schema validation error handling and self-healing repair loops across all 4 services, milestone acceptance suite & published AI acceptance report (105/105 tests passing) (`test_dev_w2_day7_ai_acceptance.py`, `Docs/week2_day7_ai_acceptance_report.md`)
- ✅ Dhramraj: End-to-end UI polish on all 4 drawers in Code Intelligence Workbench
- ✅ Yug: Route registration, auth guards, OpenAPI documentation & Day 7 API acceptance suite (`test_yug_w2_day7_final_acceptance.py`, `Docs/week2_day7_api_acceptance_report.md`)
- ✅ Om: Database migration verification, run history queries (`GET /repositories/{id}/analysis-runs`), acceptance & regression suite (87/87 tests passing)
- ✅ Sukun: Security audit — prompt injection defense, secret redaction, and multi-tenant isolation
- ✅ Keval: End-to-end acceptance suite execution (100% test pass, coverage >= 70%, 7/7 security gates) & published QA acceptance report (`test_keval_w2_day6_integration_qa.py`, `test_keval_w2_day7_acceptance_scenarios.py`, `Docs/week2_qa_acceptance_report.md`)

---

# WEEK 3 — Workflow Automation, GitHub Ecosystem & Production Hardening ⬜ NOT STARTED

**Week 3 Goal:** Transform developer-intelligence into an end-to-end workflow: Bug Finding -> GitHub Issue -> Task Plan -> Approval -> Sandbox Edit -> Test & Repair -> Verification -> GitHub Draft PR.

---

## WEEK 3 — Day 1 GitHub Issue Creation & Task Intake

- ⬜ Parth: `GitHubService.create_issue(owner, repo, title, body, labels)` using GitHub App tokens
- ⬜ Yug: `POST /api/v1/repositories/{id}/issues` validating finding ownership and returning issue URL
- ⬜ Dhramraj: Create Issue modal & button in Bug Inspector and Review UI
- ⬜ Meet: Issue-to-Task context adapter converting issue details into implementation objectives
- ✅ Dev: Validated task-intake schema separating requirements, assumptions, and constraints (`backend/app/schemas/task.py`, `backend/app/schemas/verification.py`, `backend/tests/test_dev_w3_day1_task_intake.py`)
- ✅ Prit: Workspace & sandbox architecture audit, Git worktree verification, WorkspaceManager interface & resource limits (`Docs/workspace_sandbox_architecture_audit.md`, `backend/app/schemas/workspace.py`, `backend/sandbox/workspace_manager.py`, `backend/tests/test_prit_w3_d1_workspace.py`)
- ⬜ Om: Issue-to-task persistence relationships and foreign keys
- ⬜ Sukun: GitHub issue creation security checks & token confidentiality
- ⬜ Keval: Acceptance tests for issue creation from bug and review findings

## WEEK 3 — Day 2 Task Planner & Human Approval Gate

- ⬜ Meet: `TaskPlanner` generating ordered implementation steps, affected files, tests, and risk analysis
- ⬜ Dev: `PlannerSchema` and step dependency validation
- ⬜ Yug: Task lifecycle endpoints (`POST /tasks`, `GET /tasks/{id}`, `POST /tasks/{id}/approve`, `POST /tasks/{id}/reject`)
- ⬜ Dhramraj: New Task UI and Plan Approval screen with step preview and risk badges
- ⬜ Sukun: Server-enforced approval gate blocking execution for unapproved plans
- ⬜ Keval: Acceptance tests for valid plans, rejected plans, and unapproved execution attempts

## WEEK 3 — Day 3 Isolated Workspace, Tool Routing & Code Execution

- ⬜ Prit: `WorkspaceManager` managing disposable `.workspaces/task-<id>/` with path traversal guards
- ⬜ Parth: Task branch isolation creating `agent/task-<id>` from base revision
- ⬜ Devu: `ToolRouter` and `PolicyEngine` enforcing command allowlists and argument schemas
- ⬜ Meet: Agent execution loop executing approved plan steps with loop detection
- ⬜ Yug: Execution APIs (`POST /tasks/{id}/execute`, `/pause`, `/resume`, `/cancel`, `/events`)
- ⬜ Dhramraj: Live Execution Timeline UI tracking step progress and terminal logs
- ⬜ Sukun: Tool-level permission checks and workspace boundary security tests

## WEEK 3 — Day 4 Restricted Test Execution & Bounded Auto-Fix

- ⬜ Prit: Restricted test runner executing `pytest` or `npm test` with timeout and resource limits
- ⬜ Devu: Command allowlist enforcement and argument validation
- ⬜ Meet: Bounded self-repair loop: collect failures -> targeted patch -> re-test -> max 3 repair attempts
- ⬜ Dev: Failure traceback diagnosis and repair patch validation
- ⬜ Yug: Test and repair progress APIs and failure reporting
- ⬜ Dhramraj: Test execution & repair attempt counter UI with human intervention alerts
- ⬜ Keval: Acceptance tests for passing tests, failing tests, repair success, and 3-attempt ceiling

## WEEK 3 — Day 5 Independent Verification, Code Review & Draft PR

- ⬜ Dev: `IndependentVerifier` returning PASS/FAIL/INCONCLUSIVE and generating Markdown PR summary
- ⬜ Meet: Requirement-to-code verification comparing final diff against original plan
- ⬜ Parth: Push `agent/task-<id>` branch and open GitHub Draft PR via `GitHubService.create_pull_request(draft=True)`
- ⬜ Yug: `POST /api/v1/tasks/{id}/create-pr` verifying task passed verification before opening PR
- ⬜ Dhramraj: PR Status screen with side-by-side diff viewer and link to created GitHub Draft PR
- ⬜ Om: End-to-end traceability linking finding -> issue -> task -> commit -> Draft PR
- ⬜ Sukun: PR security checks ensuring zero credentials in PR title, body, or diff

## WEEK 3 — Day 6 Security, Reliability & Performance Hardening

- ⬜ Sukun: Full attack matrix testing (prompt injection, path traversal, unauthorized approvals, secret leaks)
- ⬜ Meet: Retrieval latency optimization (target P95 < 400ms) and agent token budget checks
- ⬜ Dev: AI quality evaluation, false-positive metrics, and Gemini/Groq provider validation
- ⬜ Yug: API reliability, concurrent request handling, and error response standardization
- ⬜ Om: Database query performance, index optimization, and audit event consistency
- ⬜ Keval: Consolidated regression test suite across backend and frontend builds

## WEEK 3 — Day 7 Final Integration & Live Demonstration

- ⬜ All Leads: Execute full 17-step end-to-end acceptance demo on a real GitHub repository
- ⬜ Verify complete chain: Finding -> GitHub Issue -> Task Plan -> Approval -> Edit -> Test & Repair -> Verify -> Draft PR
- ⬜ Verify zero manual interventions between Plan Approval and Draft PR creation
- ⬜ Keval: Publish final engineering acceptance report and release signoff

---

# Task Sizing Guide

| Complexity | Time estimate | Example |
|------------|--------------|---------| 
| Tiny | 30 min | Write a test, add a migration column |
| Small | 1-2 hours | Implement one API endpoint, one service method |
| Medium | 3-4 hours | Implement a full feature (FileWalker, LLM Gateway) |
| Large | Full day | ReAct execution loop, hybrid retrieval, sandbox setup |
| Too large | Split it | If a task takes > 1 day, break it into sub-tasks |

Each Day listed in this document is scoped to be achievable by one person in a working day. If you find a day's tasks are taking longer than expected, flag it by Day 3 at the latest — not Day 7.
