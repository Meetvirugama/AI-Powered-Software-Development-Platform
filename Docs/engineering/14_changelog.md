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
| 2026-10-14 | All `Docs/` | Week 1 Foundation 100% completed, PR #72 opened and verified (369 passed, 71.3% coverage) | Meet / Team |
| 2026-10-15 | `Docs/week2.md`, `Docs/week3.md` | Week 2 Developer Intelligence Suite & Week 3 Workflow Automation plans finalized | Team |
| 2026-10-15 | `backend/ai/context/builder.py` | Meet implemented `IntelligenceContext`, `TargetSnippet`, `SymbolContext`, and caller graph enrichment | Meet |
| 2026-10-15 | `Docs/README.md` | Added master documentation index and roadmap matrix | Team |

---

## Week 2 Changes

---

### [W2-Day1] 2026-10-15 — Shared IntelligenceContext & Target Snippet Resolution
**Type:** Feature  
**Developer:** Meet  
**Changes:**
- `backend/ai/context/builder.py`:
  - Added `TargetSnippet` dataclass preserving file path, lines, and target code
  - Added `SymbolContext` dataclass capturing enclosing class/function and caller references
  - Added `IntelligenceContext` container unifying repository metadata, target snippet, symbols, and token budgets
  - Implemented `build_intelligence_context()` and `render_intelligence_data()` with prompt-isolation boundaries
- `backend/tests/test_context_builder.py`:
  - Added comprehensive test coverage for `IntelligenceContext` (all 39 tests passing)

**Impact:** Dev can directly consume `IntelligenceContext` for Code Explanation, Bug Detection, Test Generation, and Review services.

**Related Docs:** `Docs/week2.md`, `Docs/engineering/00_dashboard.md`, `Docs/engineering/10_development_tasks.md`

---

### [W2-Day1] 2026-10-15 — AST Symbol Range Resolution, Source Location & Import Tracking
**Type:** Feature  
**Developer:** Prit  
**Changes:**
- `backend/scanner/parser.py`:
  - Added `is_language_supported()` and `get_supported_languages()`
  - Added `parse_with_status()` returning structured `ParseResult` with explicit syntax error detection (`has_syntax_errors`) and unsupported language status
- `backend/scanner/symbols.py`:
  - Added `SourceRange` and `ParseResult` dataclasses
- `backend/scanner/source_location.py`:
  - Created `SourceLocationResolver` for exact 1-indexed start/end line mapping
  - Implemented `resolve_symbol_range()` supporting simple and qualified names (`Class.method`)
  - Implemented `find_enclosing_symbol()` and `find_enclosing_scope()` for tightest scope resolution
  - Implemented safe `extract_snippet()` with boundary clamping
  - Implemented `resolve_target()` returning typed `ResolutionResult` with explicit error codes (`UNSUPPORTED_LANGUAGE`, `SYMBOL_NOT_FOUND`, `LINE_OUT_OF_BOUNDS`)
- `backend/scanner/import_tracker.py`:
  - Created `ImportTracker` and `FileImportMap`
  - Added full import parsing for Python (PEP 328 relative/absolute), TypeScript (ES6 named/default/namespace), and JavaScript (CommonJS `require`)
  - Added automated categorization (standard library vs third-party vs local repo file)
- `backend/scanner/extractor.py`:
  - Added Python standard library AST fallback when tree-sitter grammars are unavailable
- `backend/tests/fixtures/ast_sample/`:
  - Added fixtures: `supported_python.py`, `supported_typescript.ts`, `supported_javascript.js`, `local_module.py`, `malformed_syntax.py`, `unsupported_lang.xyz`
- `backend/tests/test_source_location.py`:
  - 15 unit and integration tests verifying symbol ranges, enclosing symbols, import tracking, and syntax error resilience
- `Docs/scanner_languages.md`:
  - Published comprehensive language support specification, line range semantics, and limitations

**Impact:** Provides exact source line mapping and import dependencies for Meet's `IntelligenceContext` and Dev's Code Intelligence features (Explanation, Bug Detection, Test Generation, and Review).

**Related Docs:** `Docs/scanner_languages.md`, `Docs/week2.md`, `Docs/daily_tasks.md`, `Docs/engineering/10_development_tasks.md`

---

### [W2-Day2] 2026-10-16 — Target Selector & Symbol Resolution Integration
**Type:** Feature  
**Developer:** Prit  
**Changes:**
- `backend/scanner/target_selector.py`:
  - Created `TargetSelector` connecting workbench / API target selections to AST and source location utilities
  - Implemented `select_target()` supporting `'file'`, `'symbol'`, and `'range'` targets
  - Added qualified symbol resolution (`Class.method`) and member symbol extraction
  - Implemented ambiguous symbol detection and multi-level disambiguation (qualified naming, cursor/line proximity, scope ranking)
  - Added consistent 1-indexed inclusive line range enforcement with boundary clamping and enclosing symbol identification
  - Added `TargetSelectionResult.to_target_snippet()` converting targets directly into `TargetSnippet` for Meet's `IntelligenceContext`
  - Integrated parse failure resilience with explicit `parse_status` (`OK`, `SYNTAX_WARNING`, `PARSE_ERROR`, `UNSUPPORTED_LANGUAGE`) and case-insensitive suggestions
- `backend/scanner/__init__.py`:
  - Re-exported `TargetSelector` and `TargetSelectionResult`
- `backend/tests/fixtures/ast_sample/ambiguous_sample.py`:
  - Added multi-scope ambiguous symbol fixture for testing disambiguation heuristics
- `backend/tests/test_target_selector.py`:
  - Added 14 unit and integration tests covering whole file, function, class, qualified method, ambiguous symbols, line ranges, syntax warnings, and TargetSnippet conversion
- `Docs/scanner_languages.md`:
  - Updated specification with TargetSelector API contracts, ambiguous symbol handling, and line range interpretation rules
- `Docs/daily_tasks.md`:
  - Marked Prit's Day 2 Symbol Resolution task as completed

**Impact:** Downstream Code Explanation (`POST /api/v1/repositories/{id}/explain`) and Intelligence Workbench can resolve any target file, symbol, or range with verified boundaries and enclosing context.

**Related Docs:** `Docs/week2.md`, `Docs/daily_tasks.md`, `Docs/scanner_languages.md`

---

### [W2-Day3] 2026-10-20 — AST Rule Integration & Structural Bug Analysis Engine
**Type:** Feature  
**Developer:** Prit  
**Changes:**
- `backend/scanner/ast_rules.py`:
  - Created `ASTBugAnalyzer` and `BaseASTRule` base class for structural defect checking
  - Implemented 10 deterministic structural defect rules:
    - `AST-RES-001` (`resource_leak`): Detects unclosed resources allocated outside `with` context managers
    - `AST-EXC-001` (`unhandled_exception`): Detects bare `except:` or `except Exception:` swallowed with `pass`
    - `AST-ARG-001` (`logic_error`): Detects mutable default arguments (lists, dicts, sets) in functions
    - `AST-NULL-001` (`null_dereference`): Flags PEP 8 equality comparisons (`== None`) and dereferencing inside None-check blocks
    - `AST-ITER-001` (`off_by_one`): Detects modifying collections (`.remove()`, `.append()`, `del`) while actively iterating over them
    - `AST-LOGIC-001` (`logic_error`): Flags identical if-else execution branches and duplicated elif conditions
    - `AST-DEAD-001` (`logic_error`): Flags unreachable dead code following unconditional return/raise/break/continue
    - `AST-SEC-001` (`security`): Detects dangerous dynamic code execution via `eval()`, `exec()`, and `__import__()`
    - `AST-LOGIC-002` (`logic_error`): Detects redundant self-assignments (`x = x`) and tautological comparisons (`x == x`)
    - `AST-BOUND-001` (`off_by_one`): Flags index boundary violations such as `items[len(items)]`
  - Added multi-language Tree-sitter inspection for JavaScript/TypeScript (eval detection and empty catch clauses)
  - Added explicit `AST-SYNTAX-ERROR` reporting on malformed syntax without crashing repository scans
  - Enforced exact 1-indexed start/end line range preservation and target scoping (via `SourceRange` and `TargetSelector`)
  - Added Devu `StaticFinding` normalization adapter (`to_static_findings()`) and standard dictionary serialization
- `backend/scanner/__init__.py`:
  - Re-exported `ASTBugAnalyzer`, `ASTBugFinding`, `ASTRuleAnalysisResult`, `BaseASTRule`, and `DEFAULT_RULES`
- `backend/tests/fixtures/ast_sample/defect_sample.py` & `defect_sample.js`:
  - Created verified known-defect fixtures containing deterministic defects across all 7 categories
- `backend/tests/test_ast_rules.py`:
  - Added comprehensive test suite with 22 unit and integration tests (all passing) verifying rule detection, clean code tolerance, syntax error handling, target scoping, path traversal protection, and static adapter output
- `Docs/scanner_languages.md`:
  - Published Section 6 on AST Rule Integration, rule catalog, and bug scanner pipeline contracts
- `Docs/daily_tasks.md` & `Docs/engineering/10_development_tasks.md`:
  - Marked Prit's Day 3 AST Rule Integration deliverable as completed

**Impact:** Provides deterministic, AST-backed defect detection that Devu's `StaticBugScanner` and Yug's Bug Detection API (`POST /api/v1/repositories/{id}/detect-bugs`) can directly merge with external scanner and AI findings.

**Related Docs:** `Docs/scanner_languages.md`, `Docs/week2.md`, `Docs/daily_tasks.md`, `Docs/engineering/10_development_tasks.md`

---

### [W2-Day4] 2026-10-20 — Framework and Convention Detector
**Type:** Feature  
**Developer:** Prit  
**Changes:**
- `backend/scanner/framework_detector.py`:
  - Created `FrameworkDetector` and `FrameworkDetectionResult`
  - Added multi-manifest inspection for Python (`pytest.ini`, `pyproject.toml`, `setup.cfg`, `tox.ini`, `requirements.txt`, `Pipfile`) and JavaScript/TypeScript (`package.json`, `jest.config.*`, `tsconfig.json`)
  - Added support for `pytest`, `unittest`, and `jest` with explicit verification against actual project dependencies
  - Implemented AST-based fixture introspection on `conftest.py` files (extracting fixture name, scope, autouse, and docstrings)
  - Implemented automatic test directory and file naming pattern discovery (`prefix:test_`, `suffix:_test`, `suffix:.test.ts`, `suffix:.spec.ts`)
  - Implemented `propose_test_path()` generating idiomatic, convention-matching test paths for Python, TypeScript, and JavaScript source files
  - Added robust handling of ambiguous or conflicting runners (e.g. Jest vs Vitest in dependencies) with explicit `is_ambiguous` flag and candidates
  - Added explicit unsupported runner detection (`vitest`, `mocha`, `go test`, `junit`) returning actionable warnings
- `backend/scanner/__init__.py`:
  - Re-exported `FrameworkDetector` and `FrameworkDetectionResult`
- `backend/tests/fixtures/framework_samples/`:
  - Added deterministic test fixtures: `pytest_repo/`, `unittest_repo/`, `jest_repo/`, `vitest_repo/`, `ambiguous_repo/`
- `backend/tests/test_framework_detector.py`:
  - Added 15 unit and integration tests covering pytest options, conftest fixtures, unittest detection, Jest detection, Vitest/ambiguous handling, test path proposals, and dictionary serialization
- `Docs/scanner_languages.md`:
  - Added Section 8 documenting the Framework and Convention Detector specification and contracts
- `Docs/daily_tasks.md` & `Docs/engineering/10_development_tasks.md`:
  - Marked Prit's Day 4 Framework and Convention Detector deliverable as completed

**Impact:** Downstream `TestGenerationService` (Dev) and `POST /api/v1/repositories/{id}/generate-tests` (Yug) can detect exact test framework rules, test commands, fixtures, and target file paths before generating tests.

**Related Docs:** `Docs/scanner_languages.md`, `Docs/week2.md`, `Docs/daily_tasks.md`, `Docs/engineering/10_development_tasks.md`





