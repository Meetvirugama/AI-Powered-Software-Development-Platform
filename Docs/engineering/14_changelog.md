# 14. Changelog
> **Version:** 4.0 | **Created:** 2026-09-24 | **Last Updated:** 2026-11-08

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

---

### [W2-Day5] 2026-10-21 — Review Source Mapping & Diff AST Integration
**Type:** Feature  
**Developer:** Prit  
**Changes:**
- `backend/scanner/source_mapper.py`:
  - Created `ReviewSourceMapper` with dataclasses: `SymbolSummary`, `HunkASTContext`, `MappingLimitation`, `HunkMapping`, `FileSourceMapping`, and `ReviewSourceMapResult`
  - Implemented unified git diff parser supporting file additions, modifications, renames, deletions, and standard chunk headers (`@@ -old_start,old_lines +new_start,new_lines @@`)
  - Implemented symbol mapper resolving changed lines and diff hunks to enclosing functions, methods, classes, and scopes
  - Implemented structural AST context provider (`HunkASTContext`) extracting node types, scope hierarchies, and syntax validation across Python and TypeScript/JavaScript
  - Integrated `ASTBugAnalyzer` scoped strictly to modified line ranges `[start_line, end_line]` within diff hunks, surfacing immediate structural defects
  - Implemented 1-indexed inclusive line preservation, revision metadata retention (`base_revision`, `head_revision`, `commit_sha`), and file path tracking
  - Implemented explicit limitation reporting (`UNSUPPORTED_LANGUAGE`, `MODULE_LEVEL_CODE`, `DELETED_FILE`, `BINARY_FILE`, `LINE_OUT_OF_BOUNDS`, `SYNTAX_ERROR`)
  - Added adapter methods:
    - `to_source_references()`: Generates `AnalysisSourceReference` for review finding schemas
    - `to_modified_files()`: Generates Meet's `ModifiedFile` dataclass objects for multi-file review context
    - `map_commit_changes()`: Ingests commit change records directly (Parth's `CommitFileChange` format)
- `backend/scanner/__init__.py`:
  - Exported `ReviewSourceMapper`, `ReviewSourceMapResult`, `FileSourceMapping`, `HunkMapping`, `SymbolSummary`, `HunkASTContext`, and `MappingLimitation`
- `backend/tests/test_source_mapper.py`:
  - Added 21 unit and integration tests (100% passing) covering unified diff parsing, symbol mapping, AST context extraction, scoped defect evaluation, additions/renames/deletions, boundary out-of-bounds, syntax error tolerance, commit change mapping, and conversion adapters
- `Docs/scanner_languages.md`:
  - Added Section 9 documenting the Review Source Mapping specification, data contracts, and limitation reporting
- `Docs/daily_tasks.md` & `Docs/engineering/10_development_tasks.md`:
  - Marked Prit's Day 5 Review Source Mapping deliverable as completed

**Impact:** Provides AST-aware diff mapping and immediate structural defect signals for the Standalone AI Code Review Engine (`backend/ai/review/`), linking modified lines to enclosing symbols and multi-file review context.

**Related Docs:** `Docs/scanner_languages.md`, `Docs/week2.md`, `Docs/daily_tasks.md`, `Docs/engineering/10_development_tasks.md`

---

### [W2-Day7] 2026-10-22 — Shared Context Verification, Revision Hardening & Budget Audit
**Type:** Feature  
**Developer:** Meet  
**Changes:**
- `backend/ai/context/service.py`:
  - Added `RevisionDriftError` exception with fail-closed semantics for drift detection
  - Implemented `verify_revision_consistency` supporting both strict equality and loose branch matching with explicit drift detail reporting
  - Implemented `assert_revision_consistency` raising `RevisionDriftError` on drift detection
  - Fixed multi-file review cache key collisions by hashing sorted modified file paths and diff lengths into a deterministic SHA-256 digest
  - Implemented `invalidate_cache_for_repository` with optional revision targeting, eviction tracking, and metric logging
  - Added repository-aware `CacheEntry` tracking `repository_id`
  - Added static budget audit and estimation utilities: `audit_context_budget` and `estimate_context_tokens`
  - Enforced `ALLOWED_AI_PROVIDERS = frozenset({"gemini", "groq"})` across all four intelligence context retrievers (`get_explanation_context`, `get_bug_context`, `get_test_context`, `get_review_context`)
- `backend/ai/context/__init__.py`:
  - Exported `RevisionDriftError` in public package API
- `backend/tests/test_meet_day7_context_verification.py`:
  - Added 12 comprehensive unit and integration tests covering shared retrieval across all 4 features, review cache collision resolution, revision drift handling, repository cache invalidation, provider policy enforcement, token budget audits, hard truncation limits, missing context transparency, LRU eviction, and acceptance scenarios
- `Docs/engineering/10_development_tasks.md` & `Docs/daily_tasks.md`:
  - Updated Week 2 Day 7 verification and quality gate task status

**Impact:** Guarantees deterministic, fail-closed context retrieval, tamper-resistant caching, and strict provider/token budget enforcement across all four Week 2 developer intelligence features.

**Related Docs:** `Docs/week2.md`, `Docs/daily_tasks.md`, `Docs/engineering/10_development_tasks.md`

---

### [W2-Day6] 2026-10-23 — AST and Framework Reliability Verification & Test Report
**Type:** Feature / Reliability  
**Developer:** Prit  
**Changes:**
- `backend/scanner/extractor.py`:
  - Added support for `method_definition` and `method_declaration` in Tree-sitter extractor for TypeScript, JavaScript, and other class-based languages, ensuring member methods are correctly extracted with `parent_id` and `kind="method"`.
- `backend/ai/context/test_context.py`:
  - Normalized candidate test paths using `.as_posix()` to prevent Windows backslash path divergence.
- `backend/tests/test_parser_reliability.py`:
  - Added 24 comprehensive reliability and acceptance tests (100% passing) verifying:
    - Multi-language source range fidelity on Python, TypeScript, and JavaScript sample fixtures.
    - Class and method extraction, container enclosing invariants, and ambiguous symbol disambiguation.
    - Framework detection across `pytest`, `unittest`, `jest`, `vitest`, and ambiguous manifests.
    - Test path proposal logic and POSIX slash normalization across platforms.
    - Zero-crash error resilience on malformed syntax, syntax errors, empty files (0 bytes), and unsupported languages.
    - Strict 1-indexed line number agreement across all scanner components.
- `Docs/parser_and_framework_test_report.md`:
  - Authored and published the formal Day 6 deliverable: Parser and Framework Reliability Test Report documenting the test matrix, architectural invariants, 111-test suite inventory, and SLA benchmarks.
- `Docs/daily_tasks.md`, `Docs/engineering/10_development_tasks.md`, `Docs/scanner_languages.md`:
  - Updated task tracking, release gate status, and language verification documentation.

**Impact:** Provides bulletproof, zero-crash AST parsing, symbol extraction, framework convention discovery, and diff source mapping across all Developer Intelligence features (Code Explanation, Bug Detection, Test Generation, and Standalone AI Code Review).

**Related Docs:** `Docs/parser_and_framework_test_report.md`, `Docs/scanner_languages.md`, `Docs/week2.md`, `Docs/daily_tasks.md`, `Docs/engineering/10_development_tasks.md`

---

### [W2-Day7] 2026-10-24 — Final AST, Framework & Parser Failure Handling Acceptance Verification
**Type:** Feature / Acceptance & Reliability  
**Developer:** Prit  
**Changes:**
- `backend/scanner/parser.py`:
  - Hardened string-to-byte encoding (`content.encode("utf-8", errors="replace")`) to eliminate `UnicodeEncodeError` crashes on lone surrogates (`\ud800`) or malformed UTF-8 source inputs.
- `backend/scanner/extractor.py`:
  - Hardened node text decoding (`node.text.decode("utf-8", errors="replace")`) to ensure zero-crash decoding of raw syntax tree slices.
- `backend/scanner/ast_rules.py`:
  - Hardened Python AST analysis to catch `(SyntaxError, UnicodeEncodeError)`, treating encoding anomalies gracefully as syntax warnings rather than unhandled exceptions.
  - Safe byte length calculation using `errors="replace"`.
- `backend/scanner/source_mapper.py`:
  - Hardened diff file encoding with `errors="replace"`.
- `backend/tests/test_prit_day7_acceptance.py`:
  - Added 24 comprehensive Day 7 acceptance tests (100% passing) verifying:
    - Final AST and 1-indexed inclusive source-range fidelity across Python, TypeScript, and JavaScript.
    - Framework and convention detection across `pytest`, `unittest`, `jest`, `vitest` (unsupported), and ambiguous manifests.
    - Comprehensive parser failure handling: zero-crash resilience on malformed syntax, 0-byte empty files, lone surrogates, path traversal guards, and unsupported language contracts.
    - Seamless downstream feature bridges: Code Explanation `TargetSnippet`, Bug Detection `StaticFinding`, Test Generation `FrameworkProfile`, and AI Code Review `AnalysisSourceReference`.
    - Mandatory Week 2 Acceptance Scenarios A through E scanner invariants.
- `Docs/scanner_languages.md`:
  - Added Section 11 documenting the Week 2 Day 7 Final Language Support Matrix (Tiers 1, 2, and 3), language-by-language capability specifications, documented limitations, failure handling guarantees, and 143-test verification inventory.
- `Docs/week2_day7_ast_acceptance_report.md`:
  - Authored and published the formal Day 7 deliverable report documenting verified invariants, downstream feature bridges, test suite inventory, SLA benchmarks, and Week 3 handoff.
- `Docs/daily_tasks.md` & `Docs/engineering/10_development_tasks.md`:
  - Updated Week 2 Day 7 task board and milestone completion status.

**Impact:** Guarantees production-ready, zero-crash AST syntax parsing, symbol extraction, test runner convention discovery, and review source mapping across all Developer Intelligence features, ready for Week 3 Workflow Automation and Git execution sandboxes.

**Related Docs:** `Docs/week2_day7_ast_acceptance_report.md`, `Docs/scanner_languages.md`, `Docs/week2.md`, `Docs/daily_tasks.md`, `Docs/engineering/10_development_tasks.md`

---

## Week 3 Changes

---

### [W3-Day1] 2026-10-27 — Workspace & Sandbox Architecture Audit, WorkspaceManager Interface & Resource Guardrails
**Type:** Feature / Architecture & Isolation  
**Developer:** Prit  
**Changes:**
- `backend/app/schemas/workspace.py`:
  - Implemented `WorkspaceStatus`, `WorkspaceResourceLimits`, and `WorkspaceMetadata` schemas, plus request/result schemas for create, file, and cleanup operations.
- `backend/sandbox/workspace_manager.py`:
  - Implemented `WorkspaceManager` interface providing isolated directory provisioning under `.workspaces/task-<task_id>/`.
  - Built path traversal containment and resource limits enforcement.
- `Docs/workspace_sandbox_architecture_audit.md`:
  - Authored comprehensive architectural audit for workspace and sandbox isolation.
- `backend/tests/test_prit_w3_d1_workspace.py`:
  - 38 unit and integration tests verifying workspace creation, boundary enforcement, and cleanup.

**Impact:** Provides secure, isolated workspace directory provisioning for task execution and safe agent tool containment.

**Related Docs:** `Docs/workspace_sandbox_architecture_audit.md`, `Docs/daily_tasks.md`, `Docs/engineering/10_development_tasks.md`

---

### [W3-Day2] 2026-10-28 — Symbol-Level Blast Radius Engine, Test Discovery Planner & Task Planning Context
**Type:** Feature / Analysis & Planning  
**Developer:** Prit  
**Changes:**
- `backend/app/schemas/planner_context.py`:
  - Implemented `LineRange`, `FileDiffRange`, `TaskDiffRanges`, `AffectedSymbol`, `RiskLevel`, `RiskAssessment`, `ProposedTest`, `TestExecutionPlan` (with `__test__ = False`), `TaskImpactAssessment`, and `TaskPlanningContext` Pydantic schemas.
- `backend/app/schemas/__init__.py`:
  - Re-exported all planner context schemas in public schemas package.
- `backend/scanner/symbol_blast_radius.py`:
  - Implemented `SymbolBlastRadiusEngine` with 1-indexed interval intersection (`map_diff_ranges_to_symbols`), multi-hop BFS graph traversal across dependency edges (`compute_symbol_blast_radius`) with cycle protection, and multi-tier risk evaluation (`LOW`, `MEDIUM`, `HIGH`, `CRITICAL`).
- `backend/scanner/task_test_planner.py`:
  - Implemented `TaskTestPlanner` providing framework detection (`pytest`, `unittest`, `jest`), reverse test mapping via `FileTestMapper`, missing coverage discovery for modified symbols, standardized test proposals, and CLI command formulation.
- `backend/scanner/workspace_preflight.py`:
  - Implemented `WorkspaceBaseValidator` providing base-revision SHA validation, workspace path boundary confinement (`WorkspacePathGuard`), framework detection, and lifecycle status validation.
- `backend/scanner/__init__.py`:
  - Re-exported `SymbolBlastRadiusEngine`, `TaskTestPlanner`, `WorkspaceBaseValidator`, and `WorkspacePreflightResult`.
- `backend/review/blast_radius.py`:
  - Enhanced existing `BlastRadiusEngine` with `compute_symbols()` delegating to `SymbolBlastRadiusEngine` while maintaining full backward compatibility.
- `Docs/task_planning_blast_radius_audit.md`:
  - Authored comprehensive Week 3 Day 2 Architecture, Blast Radius & Test Planning Report with mathematical models, component specifications, and SLA benchmarks.
- `backend/tests/test_prit_w3_d2_blast_radius_and_test_planner.py`:
  - 35 comprehensive unit/integration tests covering line-range matching, multi-hop BFS, recursion/cycle safety, risk tiers, framework detection, test discovery, proposed tests, pre-flight checks, schema validation, and real-world multi-language fixtures.

**Impact:** Ingests Git diff line ranges from Parth (`feat(git): Week 3 Day 2`) and AST symbols to deliver symbol-level impact assessment, automated test execution planning, and pre-flight workspace validation for Meet's `TaskPlanner` and human approval gate.

**Related Docs:** `Docs/task_planning_blast_radius_audit.md`, `Docs/daily_tasks.md`, `Docs/engineering/10_development_tasks.md`

---

### [W3-Day3] 2026-10-29 — Workspace Execution Start, Tool Policy Bridge, Sandboxed Command Runner & Execution Timeline
**Type:** Feature / Execution & Sandbox Security  
**Developer:** Prit  
**Changes:**
- `backend/app/schemas/workspace.py`:
  - Implemented `WorkspaceExecutionEventType`, `WorkspaceExecutionEvent`, `WorkspaceStartExecutionRequest`, `WorkspaceStartExecutionResult`, `WorkspaceCommandRequest`, `WorkspaceCommandResult`, `WorkspaceToolPolicyRequest`, and `WorkspaceToolPolicyResult`.
  - Added `STOPPED -> IN_USE` transition to `VALID_WORKSPACE_TRANSITIONS` for execution resumption.
- `backend/app/schemas/__init__.py`:
  - Re-exported all new Day 3 workspace execution schemas.
- `backend/sandbox/constants.py`:
  - Defined `ALLOWED_COMMAND_TEMPLATES`, `DISALLOWED_COMMAND_TOKENS`, `SENSITIVE_ENV_VARS`, `MAX_COMMAND_OUTPUT_BYTES`, and `DEFAULT_COMMAND_TIMEOUT_SECONDS`.
- `backend/sandbox/exceptions.py`:
  - Defined `WorkspaceAuthorizationError`, `WorkspaceStaleApprovalError`, `WorkspaceCommandError`, `WorkspaceCommandTimeoutError`, and `WorkspacePolicyViolationError`.
- `backend/sandbox/command_runner.py`:
  - Implemented `WorkspaceCommandRunner` with allowlist enforcement, shell injection detection (rejecting metacharacters/operators/null bytes), environment sanitization (purging host credentials), timeout budgeting, bounded output capture (100 KB), and secret redaction.
- `backend/sandbox/tool_policy_bridge.py`:
  - Implemented `WorkspaceToolPolicyBridge` and `register_workspace_tools()` connecting Devu's `ToolRouter` with `WorkspaceManager`.
  - Registered 6 canonical tools (`read_file`, `write_file`, `patch_file`, `delete_file`, `list_files`, `execute_command`) with strict JSON parameter schemas, `WorkspacePathGuard` boundary checks, and fail-closed policy enforcement.
- `backend/sandbox/workspace_manager.py`:
  - Implemented `start_execution()` enforcing human approval check (ADR-010, Docs/week3.md §8 Day 3) and stale revision invalidation.
  - Implemented `pause_execution()`, `resume_execution()`, `stop_execution()`, and `fail_execution()`.
  - Implemented `execute_command()` strictly bounded to `IN_USE` workspace states.
  - Implemented `record_timeline_event()` and `get_execution_timeline()` for task observability.
- `backend/agent/tools/router.py`:
  - Updated `ToolRouter.route()` to permit execution when policy engine is verified while maintaining fail-closed default for unverified handlers.
- `backend/sandbox/__init__.py`:
  - Re-exported `WorkspaceCommandRunner`, `WorkspaceToolPolicyBridge`, `register_workspace_tools`, and Day 3 exceptions and constants.
- `Docs/workspace_execution_start_audit.md`:
  - Authored comprehensive Week 3 Day 3 Architecture, Execution Start & Tool Policy Security Report.
- `backend/tests/test_prit_w3_d3_workspace_execution.py`:
  - 16 comprehensive unit and integration tests covering approval gates, stale revision checks, pause/resume, sandboxed commands, shell injection defense, environment purging, ToolRouter policy bridge, path traversal defense, and concurrency isolation (100% pass rate).

**Impact:** Provides safe, authorized workspace execution start and tool routing for Meet's agent execution loop, Yug's execution APIs, and Dhramraj's live execution progress timeline.

**Related Docs:** `Docs/workspace_execution_start_audit.md`, `Docs/daily_tasks.md`, `Docs/engineering/10_development_tasks.md`

---

### [W3-Day4] 2026-10-29 — Restricted Test Runner, Failure Classification & Bounded Auto-Repair Loop
**Type:** Feature / Test Execution & Bounded Self-Repair  
**Developer:** Prit  
**Changes:**
- `backend/app/schemas/workspace.py`:
  - Implemented `TestOutcomeStatus` (`PASSED`, `FAILED`, `ERROR`, `TIMEOUT`, `UNSUPPORTED_FRAMEWORK`, `AMBIGUOUS`, `NO_TESTS_FOUND`).
  - Implemented `TestFailureClassification` (`NONE`, `TEST_FAILURE`, `INFRASTRUCTURE_ERROR`, `TIMEOUT`, `SECURITY_VIOLATION`).
  - Implemented `WorkspaceTestExecutionRequest`, `WorkspaceTestExecutionResult`, `RepairAttemptRecord`, and `WorkspaceRepairBudgetStatus`.
  - Added new test and repair timeline events to `WorkspaceExecutionEventType`: `TESTS_STARTED`, `TESTS_PASSED`, `TESTS_FAILED`, `TEST_INFRASTRUCTURE_FAILURE`, `TEST_TIMEOUT`, `REPAIR_ATTEMPT_STARTED`, `REPAIR_ATTEMPT_COMPLETED`, and `REPAIR_BUDGET_EXHAUSTED`.
- `backend/app/schemas/__init__.py`:
  - Re-exported all Day 4 test runner and repair schemas.
- `backend/sandbox/exceptions.py`:
  - Added `WorkspaceTestExecutionError`, `WorkspaceUnsupportedFrameworkError`, `WorkspaceRepairBudgetExhaustedError`, and `WorkspaceDuplicateRepairPatchError`.
- `backend/sandbox/test_runner.py`:
  - Implemented `WorkspaceTestRunner` with automatic framework detection (`pytest`, `unittest`, `jest`), graceful handling of unsupported frameworks (`vitest`, `go test`), command allowlisting, dependency install prevention (`npm install`, `pip install`), shell injection blocking, path traversal containment, timeout budgeting (default 60s, max 300s), 100 KB output log bounding with truncation notices, and automatic secret redaction.
  - Implemented structured output parser and failure classifier distinguishing assertion/test failures (`is_repair_eligible=True`) from infrastructure crashes, timeouts, and security violations (`is_repair_eligible=False`).
  - Implemented bounded auto-repair tracker enforcing the strict 3-attempt task-level budget ceiling per ADR-010, emitting `REPAIR_BUDGET_EXHAUSTED` timeline events upon exhaustion, and detecting duplicate failed repair patches via SHA-256 hashing.
- `backend/sandbox/workspace_manager.py`:
  - Integrated `run_tests()`, `get_test_history()`, `get_repair_budget_status()`, `record_repair_attempt()`, and `get_repair_history()`.
  - Recorded timeline events across the entire test execution and repair attempt lifecycle.
- `backend/sandbox/tool_policy_bridge.py`:
  - Registered canonical tools `TOOL_RUN_TESTS` (`run_tests`) and `TOOL_RECORD_REPAIR` (`record_repair_attempt`) with Devu's `ToolRouter`.
- `backend/sandbox/__init__.py`:
  - Re-exported `WorkspaceTestRunner`, `TOOL_RUN_TESTS`, `TOOL_RECORD_REPAIR`, and Day 4 exceptions.
- `Docs/restricted_test_runner_bounded_repair_audit.md`:
  - Authored comprehensive Week 3 Day 4 Architecture, Restricted Test Runner, Failure Classification, and Bounded Repair Loop Audit Report.
- `backend/tests/test_prit_w3_d4_restricted_test_runner.py`:
  - 18 comprehensive unit and integration tests covering framework autodetection, explicit overrides, unsupported frameworks, allowlist enforcement, shell injection blocking, path traversal containment, output parsing, failure classification, secret redaction, output truncation, 3-attempt repair budget enforcement, duplicate patch rejection, WorkspaceManager integration, timeline events, and ToolRouter dispatch (100% pass rate).

**Impact:** Delivers sandboxed test execution and bounded auto-repair enforcement for Meet's agent self-repair loop, Dev's failure diagnosis, Yug's test APIs, and Dhramraj's live repair counter UI.

**Related Docs:** `Docs/restricted_test_runner_bounded_repair_audit.md`, `Docs/daily_tasks.md`, `Docs/engineering/10_development_tasks.md`, `Docs/engineering/14_changelog.md`

---

### [W3-Day5] 2026-10-30 — Independent Diff Verification, Secret Leak Scanning, Authorized Git Push & Draft PR Preparation
**Type:** Feature / Git Publication & Independent Verification  
**Developer:** Prit  
**Changes:**
- `backend/sandbox/constants.py`:
  - Added `PROTECTED_BRANCHES` (`main`, `master`, `develop`, `dev`, `release`, `production`, `prod`, `staging`).
  - Added `CRITICAL_PROJECT_FILES` (`README.md`, `package.json`, `pyproject.toml`, `setup.py`, `requirements.txt`, `tsconfig.json`, `Cargo.toml`, `go.mod`, `pom.xml`, `Dockerfile`).
  - Added `SECRET_SCAN_PATTERNS` regex detectors for OpenAI API keys, GitHub tokens, AWS access key IDs, Google API keys, private keys, and generic credential assignments.
- `backend/sandbox/exceptions.py`:
  - Added `WorkspaceDiffError`, `WorkspaceDiffValidationError`, `WorkspaceSecretLeakDetectedError`, `WorkspaceProtectedBranchError`, `WorkspaceCommitError`, `WorkspacePublicationUnauthorizedError`, `WorkspacePushError`, and `WorkspaceDraftPRError`.
- `backend/app/schemas/workspace.py`:
  - Added 8 new timeline event types: `DIFF_INSPECTED`, `DIFF_VALIDATED`, `DIFF_VALIDATION_FAILED`, `PUBLICATION_AUTHORIZED`, `CHANGES_COMMITTED`, `BRANCH_PUSHED`, `PR_CREATED`, and `PUBLICATION_FAILED`.
  - Implemented `FileChangeType` (`MODIFIED`, `ADDED`, `DELETED`), `FileDiffHunk`, `FileDiffSummary`, `WorkspaceDiffRequest`, `WorkspaceDiffResult`, `SecretScanFinding`, `DiffValidationRequest`, `DiffValidationResult`, `WorkspaceCommitRequest`, `WorkspaceCommitResult`, `WorkspacePushRequest`, `WorkspacePushResult`, `WorkspaceDraftPRRequest`, and `WorkspaceDraftPRResult`.
- `backend/app/schemas/__init__.py`:
  - Re-exported all Day 5 diff verification, commit, push, and draft PR schemas.
- `backend/sandbox/diff_verifier.py`:
  - Implemented `WorkspaceDiffVerifier` providing unified and per-file diff extraction against base revisions, hunk-level diff parsing, task plan scope boundary validation, critical manifest deletion protection, and diff addition-level secret leak scanning.
- `backend/sandbox/workspace_manager.py`:
  - Bound `_diff_verifier = WorkspaceDiffVerifier()`.
  - Implemented `get_workspace_diff()` emitting `DIFF_INSPECTED` timeline events.
  - Implemented `validate_workspace_diff()` with scope verification, critical manifest protection, and addition-level secret scanning, emitting `DIFF_VALIDATED` or `DIFF_VALIDATION_FAILED`.
  - Implemented `commit_task_changes()` enforcing protected branch guards, sanitized commit messages, `Task-ID` metadata trailers, and `CHANGES_COMMITTED` timeline events.
  - Implemented `push_task_branch()` enforcing the mandatory human publication authorization gate (ADR-010, F37), protected branch guards, credential redaction, and `BRANCH_PUSHED` timeline events.
  - Implemented `create_draft_pr()` guaranteeing unconditional Draft PR status (`is_draft=True`, zero auto-merge per ADR-010), automated Markdown task summary synthesis, and `PR_CREATED` timeline events.
- `backend/sandbox/tool_policy_bridge.py`:
  - Added canonical tool constants: `TOOL_INSPECT_DIFF`, `TOOL_VALIDATE_DIFF`, `TOOL_COMMIT_CHANGES`, `TOOL_PUSH_BRANCH`, `TOOL_CREATE_DRAFT_PR`.
  - Added policy validation rules and execution dispatch for all 5 Day 5 tools.
  - Registered all 5 tools with Devu's `ToolRouter` via `register_workspace_tools()`.
- `backend/sandbox/__init__.py`:
  - Re-exported `WorkspaceDiffVerifier`, Day 5 constants, exceptions, and canonical tool constants.
- `Docs/independent_verification_and_draft_pr_audit.md`:
  - Authored comprehensive Week 3 Day 5 Architecture, Independent Diff Verification, Security Scanning, Git Push & Draft PR Preparation Audit Report.
- `backend/tests/test_prit_w3_d5_verification_and_draft_pr.py`:
  - 30 comprehensive unit and integration tests covering diff extraction, scope validation, manifest deletion protection, addition secret scanning, protected branch guards, publication authorization gates, commit creation, git push credential redaction, draft PR synthesis, timeline event emissions, and ToolRouter dispatch (100% pass rate).

**Impact:** Provides verified, security-scanned, and human-authorized Git publication and Draft PR preparation for Dev's independent verifier, Parth's GitHub service, Yug's PR endpoints, and Dhramraj's PR status UI.

**Related Docs:** `Docs/independent_verification_and_draft_pr_audit.md`, `Docs/daily_tasks.md`, `Docs/engineering/10_development_tasks.md`, `Docs/week3.md`

---

### [W3-Day6] 2026-10-30 — Workspace Reliability, Crash Recovery, Stale Revision Detection, Diff Immutability, and Hardened Orphan Collection
**Type:** Feature / Reliability, Security & Failure Recovery  
**Developer:** Prit  
**Changes:**
- `backend/sandbox/constants.py`:
  - Added Day 6 constants: `DEFAULT_MAX_ORPHAN_AGE_SECONDS` (86400s), `DEFAULT_MAX_WORKSPACE_FILES` (1000), `RECOVERY_STALE_TIMEOUT_SECONDS` (3600s), and `MAX_TASK_LOCK_TIMEOUT_SECONDS` (30s).
  - Enhanced `SECRET_SCAN_PATTERNS` regex to detect GitHub personal access tokens (`ghp_[a-zA-Z0-9]{20,}`).
- `backend/sandbox/exceptions.py`:
  - Added 7 reliability and security exceptions: `WorkspaceStaleRevisionError`, `WorkspacePostVerificationMutationError`, `WorkspaceDiffDivergedError`, `WorkspaceDiskQuotaExceededError`, `WorkspaceConcurrentOperationError`, `WorkspaceInvariantViolationError`, and `WorkspaceRecoveryError`.
- `backend/app/schemas/workspace.py`:
  - Added 5 new timeline event types: `WORKER_CRASH_RECOVERED`, `STALE_REVISION_DETECTED`, `POST_VERIFICATION_MUTATION_DETECTED`, `ORPHANED_WORKSPACES_CLEANED`, and `INVARIANT_VIOLATION_DETECTED`.
  - Added `last_active_at` and `verification_diff_hash` fields to `WorkspaceMetadata`.
  - Implemented Day 6 schemas: `StaleRevisionCheckRequest`, `StaleRevisionCheckResult`, `DiffImmutabilityCheckRequest`, `DiffImmutabilityCheckResult`, `WorkspaceRecoveryRecord`, `WorkspaceRecoveryResult`, `WorkspaceOrphanCleanupResult`, `WorkspaceInvariantCheckResult`, and `WorkspaceDiskUsageResult`.
- `backend/app/schemas/__init__.py`:
  - Re-exported all Day 6 recovery, stale check, diff immutability, and cleanup schemas.
- `backend/sandbox/command_runner.py`:
  - Added `execute_raw_command` and `RawCommandResult` for safe internal git operations and unit-test mocking.
- `backend/sandbox/diff_verifier.py`:
  - Excluded `*metadata.json` from git diff pathspecs (`-- . ":(exclude)*metadata.json"`) so internal state writes do not mutate git diffs.
- `backend/sandbox/workspace_manager.py`:
  - Added atomic metadata disk persistence (`_save_metadata_file`) on every state transition and workspace creation.
  - Implemented `recover_workspaces()`: discovers and reconstructs workspace state after worker crashes/restarts, safely marks interrupted creation as `FAILED`, and transitions stale `IN_USE` tasks to `STOPPED`.
  - Implemented `reconcile_workspace(task_id)`: dynamically reloads evicted workspace metadata from disk into in-memory caches.
  - Implemented `detect_stale_base_revision()` and `assert_not_stale()`: compares base revisions against remote tracking branches, computes commits behind via `git rev-list --count`, and halts stale publication with rebase remediation.
  - Implemented `compute_verification_diff_hash()` and `verify_diff_immutability()`: computes SHA-256 fingerprint of verified diffs, asserts post-verification immutability, and raises `WorkspacePostVerificationMutationError` upon tampering.
  - Implemented `cleanup_orphaned_workspaces()`: sweeps abandoned or untracked directories older than threshold, strictly protects active workspaces, and supports non-destructive `dry_run=True`.
  - Implemented `validate_workspace_invariants()`: audits sandbox containment, directory existence, git repo validity, approval consistency, and secret hygiene.
  - Implemented `get_task_lock()`: thread-safe task mutex locks to serialize concurrent workspace operations.
  - Implemented `sanitize_log()`: scrubs tokens, API keys, and credentials from logs and output payloads.
  - Implemented `check_disk_budget()`: audits byte and file usage against resource limits.
- `backend/sandbox/tool_policy_bridge.py`:
  - Registered 6 canonical Day 6 tools: `TOOL_RECOVER_WORKSPACE`, `TOOL_CHECK_STALE_REVISION`, `TOOL_VERIFY_DIFF_IMMUTABILITY`, `TOOL_CLEANUP_ORPHANED`, `TOOL_VALIDATE_INVARIANTS`, and `TOOL_CHECK_DISK_BUDGET`.
  - Added argument validation schemas and execution routing handlers for all Day 6 tools.
- `backend/sandbox/__init__.py`:
  - Re-exported Day 6 constants, exceptions, tools, and schemas.
- `Docs/reliability_security_and_failure_recovery_audit.md`:
  - Authored comprehensive Week 3 Day 6 Architecture, Crash Recovery, Stale Revision Detection, Diff Immutability, and Invariant Audit Report.
- `backend/tests/test_prit_w3_d6_reliability_and_recovery.py`:
  - 32 comprehensive unit and integration tests across 9 test suites (100% pass rate; 169/169 passed across all Week 3 test suites).

**Impact:** Guarantees failure recovery across worker crashes/restarts, protects against silent remote branch divergence, enforces post-verification diff immutability, prevents storage exhaustion via orphan collection, and provides tamper-proof execution integrity for the entire agent pipeline.

**Related Docs:** `Docs/reliability_security_and_failure_recovery_audit.md`, `Docs/daily_tasks.md`, `Docs/engineering/10_development_tasks.md`, `Docs/week3.md`

---

### [W3-Day7] 2026-10-31 — End-to-End Acceptance, Scenarios A–J Verification, and Live Demo
**Type:** Feature / Acceptance & Demonstration  
**Developer:** Prit  
**Changes:**
- `backend/sandbox/command_runner.py`:
  - Added Windows path fallback in `run_command` resolving `pytest` to `[sys.executable, "-m", "pytest", *args]` when `shutil.which("pytest")` is `None`.
  - Added `APPDATA` and `LOCALAPPDATA` to `safe_keys` in `sanitize_environment` so Windows Python user packages (`site-packages`) are recognized in subprocesses.
- `backend/sandbox/diff_verifier.py`:
  - Updated `_run_git_diff` excludes to add `:(exclude)*__pycache__*`, `:(exclude)*.pyc`, and `:(exclude)*.pytest_cache*` ensuring bytecode never leaks into verified diffs.
- `backend/sandbox/workspace_manager.py`:
  - Updated `record_timeline_event` to redact `message` and string values in `payload` with `redact()`.
  - Fixed `_format_draft_pr_summary` to map `passed_count`, `failed_count`, `skipped_count`, and `duration_ms / 1000.0`.
  - Updated `recover_workspaces` stale check to accept `stale_timeout_seconds >= 0` for sub-second crash recovery assertions.
- `backend/tests/test_prit_w3_d7_acceptance.py`:
  - Implemented 25 comprehensive end-to-end acceptance tests across 13 test suites covering:
    - 17-step full lifecycle workflow execution and zero manual intervention audit.
    - Scenarios A through J (happy path, plan rejection, plan mutation, repair budget exhaustion, malicious tool requests, verification failures, GitHub uncertainty, worker restart, permission revocation, diff tampering).
    - Week 2 shared intelligence integration (AST parser, framework detector, review source mapper).
    - Latency SLA benchmarks (creation <1s, command execution <3s, diff validation <500ms, crash recovery <1s).
    - Timeline event audit trail provenance and zero secret leakage.
  - 100% pass rate (25/25 passed; 194/194 total Week 3 tests passing).
- `Docs/week3_day7_workspace_acceptance_report.md`:
  - Authored comprehensive Week 3 Day 7 Acceptance & Demo Report detailing 17-step workflow, Scenarios A–J verification, SLA benchmarks, and release checklist.
- `Docs/daily_tasks.md` & `Docs/engineering/10_development_tasks.md`:
  - Updated task tracking boards and deliverables for Day 7 signoff.

**Impact:** Certifies the Repository Engine & Sandbox Execution system for production release, guaranteeing mathematically isolated, human-gated, and fail-safe autonomous code modification.

**Related Docs:** `Docs/week3_day7_workspace_acceptance_report.md`, `Docs/daily_tasks.md`, `Docs/engineering/10_development_tasks.md`, `Docs/week3.md`
---

### [W3-Day2] 2026-10-27 — Task Planning, Plan Versioning & Human Approval Persistence
**Type:** Feature / Database & Persistence  
**Developer:** Om  
**Changes:**
- `backend/app/models/task.py`:
  - Added canonical `to_dict()` serialization methods across `TaskPlan`, `TaskApproval`, `Workspace`, `TaskCheckpoint`, `TaskEvent`, and `TaskPullRequest`, guaranteeing exact conformity with Week 3 Pydantic response schemas.
- `backend/app/repositories/task_repository.py`:
  - Enhanced `save_plan()` to automatically mark older proposed/approved plans as `SUPERSEDED`, invalidate prior approvals (`task.approved_plan_version = None`), and transition task status to `PENDING_APPROVAL`.
  - Implemented `get_plan()` supporting both latest and specific plan version retrieval.
  - Implemented `list_plans()` returning all historical plan versions ordered ascending.
  - Implemented `approve_plan()` and `reject_plan()` with immutable decision recording and human feedback.
  - Implemented `get_approval()` and `list_approvals()` for decision history inspection.
  - Implemented `update_task_context()` linking Week 2 intelligence context with automated credential scrubbing.
- `backend/app/services/task_history_service.py`:
  - Implemented `TaskHistoryService` providing production-grade session management, multi-tenant isolation, and high-level orchestration across task intake, planning, approvals, and recovery.
- `backend/app/services/__init__.py`:
  - Exported `TaskHistoryService` in public service API.
- `backend/app/main.py` & `backend/app/core/lifespan.py`:
  - Registered `app.state.task_history_service` in FastAPI application lifespan.
- `backend/tests/test_om_w3_d2_planning_persistence.py`:
  - Added 15 comprehensive unit and integration tests (100% pass rate) verifying plan versioning, approval/rejection lifecycle, approval invalidation upon plan revision, multi-tenant boundaries, secret scrubbing, and Pydantic schema validation.
- `Docs/daily_tasks.md`, `Docs/engineering/10_development_tasks.md`:
  - Updated Week 3 Day 2 milestone tasks and active team assignments.
- `Docs/persistence_week3_day2_report.md`:
  - Authored and published formal Week 3 Day 2 Persistence Deliverable Report.

**Impact:** Establishes a rock-solid persistence and service layer for Day 2 task planning and human approval gating, enabling Meet (TaskPlanner), Yug (API Orchestration), and Dhramraj (Frontend Plan Review) to build seamlessly against persisted task plans and approvals.

**Related Docs:** `Docs/persistence_week3_day2_report.md`, `Docs/week3.md`, `Docs/daily_tasks.md`, `Docs/engineering/10_development_tasks.md`

---

### [W3-Day3-Day4] 2026-10-28 — Workspace Tracking, Tool Auditing, Test Run Logging & Bounded Repair Persistence
**Type:** Feature / Database & Persistence  
**Developer:** Om  
**Changes:**
- `backend/app/models/task.py`:
  - Added canonical `to_dict()` serialization methods to `TaskExecution`, `ToolInvocation`, `TestRun`, and `RepairAttempt` conforming to Pydantic responses.
  - Added `__test__ = False` on `TestRun` and `TestRunResponse` to prevent pytest collection warnings.
- `backend/app/schemas/task.py`:
  - Added Pydantic response models: `WorkspaceResponse`, `TaskExecutionResponse`, `ToolInvocationResponse`, `TestRunResponse` (`__test__ = False`), and `RepairAttemptResponse`. Added to `__all__`.
- `backend/app/repositories/task_repository.py`:
  - Day 3 Workspace & Execution: `get_workspace()`, `update_workspace_status()`, `record_execution_start()`, `record_execution_finish()`, `get_executions()`, and `get_tool_invocations()`.
  - Day 3 Precondition Enforcement: Blocked `EXECUTING` state without `approved_plan_version` and initialized workspace.
  - Day 3 Tool Auditing: Credential scrubbing (`ghp_*`, `sk-*`, `eyJ*`) in arguments and output summaries.
  - Day 4 Test Run Logging: `record_test_run()`, `get_test_runs()`, `get_latest_test_run()` capturing test command, status, exit code, test counts, duration, sanitized logs, and target revision.
  - Day 4 Bounded Repair Loop: Hardened `increment_repair_attempt()` and `get_repair_attempts()` enforcing the strict **3-attempt ceiling** (`RETRY_EXHAUSTED` -> `FAILED`), blocking transitions to `REPAIRING` when budget is exhausted, and ensuring retry counters survive worker/app restarts.
- `backend/app/services/task_history_service.py`:
  - Added Day 3 & Day 4 orchestration methods wrapping `TaskRepository` with session management: `record_workspace`, `get_workspace`, `update_workspace_status`, `record_execution_start`, `record_execution_finish`, `get_executions`, `record_tool_invocation`, `get_tool_invocations`, `record_test_run`, `get_test_runs`, `get_latest_test_run`, `increment_repair_attempt`, `get_repair_attempts`.
- `backend/tests/test_om_w3_d3_d4_execution_persistence.py`:
  - Added 11 comprehensive automated tests (100% passing) verifying workspace lifecycle, execution tracking, tool auditing and secret scrubbing, execution start preconditions, test run logging, bounded repair loop 3-attempt ceiling, budget persistence across restarts, cross-repository multi-tenant isolation, ordered timeline events, and model-to-schema serialization.
- `Docs/daily_tasks.md`, `Docs/engineering/10_development_tasks.md`:
  - Updated Week 3 Day 3 and Day 4 task boards and milestone progress.
- `Docs/persistence_week3_day3_day4_report.md`:
  - Authored formal Week 3 Day 3 & Day 4 Persistence Deliverable Report.

**Impact:** Provides the core persistence foundation for Prit (WorkspaceManager), Devu (ToolRouter & PolicyEngine), Meet (Agent Execution Loop & Bounded Repair), and Dev (Test Strategy & Diagnosis). All workspace lifecycles, execution states, tool audit trails, test runs, and repair attempts are reliably persisted with tamper-proof budget bounds.

**Related Docs:** `Docs/persistence_week3_day3_day4_report.md`, `Docs/week3.md`, `Docs/daily_tasks.md`, `Docs/engineering/10_development_tasks.md`

---

### [W3-Day5] 2026-10-29 — Independent Verification, Publication Gate, Draft PR Persistence & End-to-End Traceability
**Type:** Feature / Database & Persistence  
**Developer:** Om  
**Changes:**
- `backend/app/models/task.py`:
  - Added canonical `to_dict()` serialization method to `VerificationResult` matching `VerificationResultResponse` schema.
- `backend/app/schemas/task.py`, `backend/app/schemas/__init__.py`:
  - Added and exported `PublicationAuthorizationRequest`, `PublicationAuthorizationResponse`, and `TaskTraceabilityResponse` schemas with comprehensive field definitions and documentation.
- `backend/app/repositories/task_repository.py`:
  - Eagerly loads `Task.finding` with `selectinload(Task.finding)` in `get_task()`.
  - Enhanced `record_verification_result()`: validates non-terminal task status, sets `task.status = READY_FOR_PUBLICATION` if `PASSED` without blockers, sets `task.status = BLOCKED` if `FAILED` or has blocking findings, and logs `VERIFICATION_COMPLETED` event.
  - Added `get_verification_results()` and `get_latest_verification_result()`.
  - Added `authorize_publication()`: verifies `READY_FOR_PUBLICATION`, enforces `head_sha` match with latest verified revision with `PASSED` status and zero blockers, transitions task to `PUBLISHING`, and logs `PUBLICATION_AUTHORIZED` event.
  - Enhanced `record_pull_request()`: validates `PUBLISHING` or `READY_FOR_PUBLICATION` status, guarantees idempotency on retry, transitions task to `DRAFT_PR_CREATED`, and logs `DRAFT_PR_CREATED` event.
  - Added `get_pull_request()`.
  - Added `get_task_traceability()`: constructs complete end-to-end graph (`task`, `finding`, `latest_plan`, `latest_approval`, `workspace`, `latest_execution`, `latest_test_run`, `repair_attempts_used`, `latest_repair`, `latest_verification`, `pull_request`, `timeline`, `traceability_status`).
  - Added idempotent self-transition in `transition_status()`.
- `backend/app/services/task_history_service.py`:
  - Added Day 5 orchestration methods wrapping `TaskRepository` with session management: `record_verification_result`, `get_verification_results`, `get_latest_verification_result`, `authorize_publication`, `record_pull_request`, `get_pull_request`, `get_task_traceability`.
- `backend/tests/test_om_w3_d5_verification_pr_traceability.py`:
  - Authored 15 comprehensive automated tests (100% passing) verifying verification persistence, publication authorization gate, draft PR persistence, end-to-end traceability graph, multi-tenant isolation, and Pydantic schema validation.
- `Docs/daily_tasks.md`, `Docs/engineering/10_development_tasks.md`:
  - Marked Om's Day 5 deliverables complete with all 54 Week 3 tests passing.
- `Docs/persistence_week3_day5_report.md`:
  - Published formal Week 3 Day 5 Persistence Deliverable Report.

**Impact:** Provides the core persistence foundation and state machine gates for Dev & Keval (W3-08 Independent Verification), Parth & Yug (W3-09 Authorized Push & Draft PR Creator), and Dhramraj (W3-10 Task Dashboard, Progress & Timeline UI). All artifacts from original finding to GitHub Draft PR are interconnected in an auditable, tamper-resistant graph.

**Related Docs:** `Docs/persistence_week3_day5_report.md`, `Docs/week3.md`, `Docs/daily_tasks.md`, `Docs/engineering/10_development_tasks.md`


---

### [W3-Day6-Day7] 2026-10-30 — Query Performance, Audit Consistency, Crash Recovery & 17-Step E2E Acceptance
**Type:** Feature / Performance / Database & Persistence  
**Developer:** Om  
**Changes:**
- ackend/app/models/task.py:
  - Added composite indexes across all core tables for sub-millisecond query performance:
    - Workspace: ix_workspaces_task_status on (task_id, status)
    - TaskExecution: ix_task_executions_task_attempt on (task_id, attempt_number), ix_task_executions_task_created on (task_id, created_at)
    - ToolInvocation: ix_tool_invocations_task_created on (task_id, created_at), ix_tool_invocations_task_tool on (task_id, tool_name)
    - TestRun: ix_test_runs_task_created on (task_id, created_at), ix_test_runs_task_status on (task_id, status)
    - VerificationResult: ix_verification_results_task_revision on (task_id, verified_revision), ix_verification_results_task_created on (task_id, created_at)
    - TaskCheckpoint: ix_task_checkpoints_task_created on (task_id, created_at)
    - TaskPullRequest: ix_task_pull_requests_repo_pr on (repository_id, pr_number)
  - Added new audit event types: CRASH_DETECTED, CRASH_RECOVERED, RECOVERY_FAILED.
- ackend/app/schemas/task.py, ackend/app/schemas/__init__.py:
  - Added and exported TaskRecoveryResponse Pydantic response schema.
  - Enhanced TaskTraceabilityResponse with 	ool_invocations, 	est_runs, 
epair_attempts, and is_complete_workflow: bool.
- ackend/app/repositories/task_repository.py:
  - Implemented get_active_tasks_for_repository() leveraging composite index (repository_id, status) with pagination and terminal status filtering.
  - Enforced audit event consistency & immutability: delete_event(), update_event(), update_approval() raise PermissionError to preserve append-only compliance.
  - Implemented worker crash recovery & restart resilience: 
econcile_crashed_task() and 
ecover_interrupted_tasks(). Automatically identifies volatile states (EXECUTING, TESTING, REPAIRING, WORKSPACE_SETUP), marks dangling running executions as FAILED, restores latest checkpoint with CRASH_RECOVERED event into RECOVERY_REQUIRED, preserves retry counter 
epair_attempts_used, and marks FAILED with RECOVERY_FAILED if retry budget ($\ge 3$) is exhausted.
  - Made crash recovery strictly idempotent on non-volatile terminal or publication-ready tasks.
  - Enhanced get_task_traceability(): deterministic approval retrieval by (plan_version, created_at), eager tool invocation / test run / repair attempt tracking, and computation of is_complete_workflow.
- ackend/app/services/task_history_service.py:
  - Added session-managed wrappers: get_active_tasks, 
econcile_crashed_task, 
ecover_interrupted_tasks.
- ackend/tests/test_om_w3_d6_d7_performance_recovery_acceptance.py:
  - Authored 20 automated tests (100% passing) verifying query performance, composite indexes, query SLA benchmarks (<100ms), audit event immutability, worker crash recovery, 17-step end-to-end lifecycle acceptance, and multi-tenant isolation.
- Docs/daily_tasks.md, Docs/engineering/10_development_tasks.md:
  - Marked Om's Week 3 Day 6 and Day 7 deliverables complete with all 74 cumulative persistence tests passing.
- Docs/persistence_week3_day6_day7_report.md:
  - Published comprehensive Week 3 Day 6 & Day 7 Deliverable Report.

**Impact:** Completes Om's entire Week 3 persistence deliverables (Days 1–7), delivering an ultra-fast, crash-resilient, immutable, and fully traceable persistence backbone. Supports all downstream team modules with guaranteed query performance SLAs (<100ms) and complete referential integrity across the 17-step autonomous development lifecycle.

**Related Docs:** Docs/persistence_week3_day6_day7_report.md, Docs/week3.md, Docs/daily_tasks.md, Docs/engineering/10_development_tasks.md

---

## Post-Week 3 Enterprise Hardening & Advanced Intelligence Changes

---

### [Post-Week3-Batch1] 2026-11-02 — JWT & OAuth Security Hardening (Issue #181, PR #202)
**Type:** Security / Hardening / Auth  
**Developer:** Meet / Sukun  
**Changes:**
- `backend/app/core/security.py`:
  - Enforced timing-safe HMAC-SHA256 signature verification using `hmac.compare_digest`.
  - Added strict minimum 32-byte (256-bit) secret validation at startup (`SecurityError`).
- `backend/app/api/v1/auth.py`:
  - Switched OAuth CSRF state verification to cryptographically random state nonces stored in Redis (`oauth_state:{state}`).
  - Used atomic `GETDEL` (with fallback pipeline) to ensure single-use replay protection.
  - Hardened cookie flags: `httpOnly=True`, `secure=True`, `SameSite=Lax`.
- `backend/tests/test_jwt_and_oauth_hardening.py`:
  - 14 automated tests verifying secret validation, timing safety, state replay protection, and cookie security.

**Impact:** Eliminates timing side-channels in authentication and protects against OAuth replay and CSRF attacks.

**Related Docs:** `Docs/engineering/15_authentication_authorization_audit.md`, `Docs/engineering/16_issue181_implementation_plan.md`, `Docs/engineering/17_jwt_oauth_hardening.md`

---

### [Post-Week3-Batch2] 2026-11-04 — Durable GitHub Webhook Ingestion & Event Automation (Issue #182, PR #219)
**Type:** Feature / Reliability / Automation  
**Developer:** Meet / Parth  
**Changes:**
- `backend/app/models/webhook_event.py`:
  - Created `github_webhook_events` table tracking `id`, `delivery_id`, `event_type`, `status` (`pending`, `processing`, `completed`, `failed`, `dead_letter`), `attempts`, `lease_token`, `lease_expires_at`, `payload`.
- `backend/app/workers/webhook_worker.py`:
  - Autonomous lease-based background worker acquiring pending events with distributed atomic locks.
  - Automatic re-indexing on GitHub `push` events to default branch.
  - Automated AI code review comments posted directly to pull requests (`pull_request` events).
  - Dead-letter queue transition after 3 consecutive failures.
- `backend/app/api/v1/github.py`:
  - Added webhook management endpoints: `GET /api/v1/github/events`, `GET /api/v1/github/events/{id}`, `POST /api/v1/github/events/{id}/replay`.
  - Added repository automation settings endpoints: `GET /repositories/{id}/automation`, `PATCH /repositories/{id}/automation`.
- `backend/migrations/versions/e1f2a3b4c5d6_add_github_webhook_events_and_repo_automation.py`:
  - Alembic migration adding `github_webhook_events` table and automation flags to `repositories`.
- `backend/tests/test_durable_webhook_automation.py`:
  - 18 automated tests verifying idempotent delivery, lease timeout recovery, replay, and automation settings.

**Impact:** Guarantees zero-loss webhook handling, automatic repo re-indexing on push, and autonomous PR code reviews.

**Related Docs:** `Docs/engineering/17_github_webhook_automation_design.md`, `Docs/db_migrations.md`

---

### [Post-Week3-Batch3] 2026-11-06 — Multi-Stage Code Retrieval Engine & 150-Query Benchmark (Issue #187, PR #220)
**Type:** Feature / Performance / AI Retrieval  
**Developer:** Meet  
**Changes:**
- `backend/app/retrieval/`:
  - Created 7-stage retrieval pipeline: intent detection, simple GIN lexical FTS (`code_search_text`), adaptive HNSW savepoints (`ef_search` scaling), 1-hop symbol graph expansion, ONNX cross-encoder reranking, and Redis query caching.
  - `code_aware_search.py`: Lexical retrieval with CamelCase and snake_case sub-tokenization against PostgreSQL simple dictionary.
  - `adaptive_hnsw.py`: Dynamic `hnsw.ef_search` configuration based on query intent and candidate pool size.
  - `graph_expansion.py`: 1-hop AST caller/callee symbol expansion.
  - `onnx_reranker.py`: ONNX Runtime cross-encoder (`ms-marco-MiniLM-L-6-v2`) with PyTorch fallback and fallback score consistency.
  - `retrieval_cache.py`: Shared Redis cache keyed by `(repo_id, active_index_generation, query_hash)` with TTL and hit/miss telemetry.
- `backend/migrations/versions/e8f9a0b1c2d3_add_code_search_text_and_index_generation.py`:
  - Added `code_search_text` column and GIN index to `code_chunks`; added `active_index_generation` and `active_commit_sha` to `repositories`.
- `backend/tests/`:
  - `test_hybrid_retrieval.py`, `test_adaptive_hnsw.py`, `test_reranker_onnx.py`, `test_retrieval_cache.py`, `test_retrieval_benchmark.py` (150-query golden evaluation suite achieving MRR@10 > 0.85 and P95 latency < 350ms).

**Impact:** Drastically improves code retrieval accuracy and recall across complex symbol names and natural language questions.

**Related Docs:** `Docs/retrieval/`, `Docs/db_migrations.md`

---

### [Post-Week3-Batch4] 2026-11-08 — Bounded Agentic Repository Chat & Tool Calling (Issue #188, PR #220)
**Type:** Feature / Agentic AI / UX  
**Developer:** Meet / Dhramraj  
**Changes:**
- `backend/app/ai/agent/`:
  - `orchestrator.py`: `AgentOrchestrator` coordinating multi-round tool-augmented repository exploration.
  - `llm_client.py`: Normalized tool-calling client supporting both Google Gemini and Groq with unified function calling schemas and error handling.
  - `tools.py`: Read-only repository tool registry (`search_code`, `read_file_range`, `find_symbol`, `list_directory`).
  - `execution_policy.py`: Strict read-only policy enforcing directory jail, denylists (`.env`, secrets, `.git`), and path traversal defense.
  - `budget_manager.py`: Enforces hard limits: 8,000 prompt/completion tokens, 5 execution rounds, 30-second wall-clock timeout.
- `backend/app/api/v1/chat.py`:
  - Dual-mode chat API accepting `"mode": "normal" | "agentic"`. Returns grounded `RepositoryAnswer` with inspection metadata in `agent_metadata`.
- `frontend/src/pages/RepositoryChat.tsx`:
  - Added Normal / Agentic mode toggle with mode badges.
  - Implemented tool call inspection pill badges showing invoked tools, token counts, and execution latency.
- `backend/tests/`:
  - Authored comprehensive test suites: `test_agent_tools.py`, `test_agent_policy.py`, `test_agent_security_and_budget.py`, `test_agent_orchestrator.py`, `test_agent_chat_api.py`.
- Alembic linear migration chain resolved and linearized from `24498ac67b3e` down through `e8f9a0b1c2d3`.

**Impact:** Provides developers with an interactive, autonomous, yet strictly bounded agent for interactive repository exploration, fully verified across both Gemini and Groq providers.

**Related Docs:** `Docs/agentic-chat/`, `Docs/engineering/08_api_documentation.md`, `frontend/README.md`

---

### [Post-Week3-Batch5] 2026-11-08 — Execution-Verified, Coverage-Guided Automated Test Generation (Issue #193)
**Type:** Feature / Test Automation / Security  
**Developer:** Meet / Dev / Dhramraj / Keval  
**Changes:**
- `backend/app/services/`:
  - `test_stability_service.py`: `TestStabilityValidator` with 3-consecutive-run stability validation (`MAX_STABILITY_RUNS = 3`), classifying 3/3 `STABLE`, 2/3 `UNSTABLE`, $\le 1/3$ `FAILED`.
  - `test_coverage_service.py`: `TestCoverageService` calculating baseline vs post-gen coverage deltas and attributing newly exercised source lines specifically to generated tests.
  - `test_iteration_service.py`: `TestIterationOrchestrator` implementing CoverUp (P-11) iterative feedback loop (up to 3 rounds) targeting uncovered lines.
  - `test_mutation_service.py`: `MutationTestingService` implementing offline AST mutant synthesis (MuTAP P-12) and mutation kill score calculations.
  - `test_execution_verifier.py`: 5-stage pipeline coordinator linking static validation, isolated sandbox execution, 3 stability runs, and coverage attribution.
- `backend/scanner/framework_detector.py`:
  - Added full detection for Vitest configs (`vitest.config.ts`, `vitest.config.js`, `vite.config.ts`).
- `backend/scripts/benchmark_quality_suite.py`:
  - Corrected benchmark evaluator gate (`evaluate_metric`) to dynamically evaluate thresholds and fail on below-target metrics.
- `frontend/src/components/explorer/TestGenerationView.tsx`:
  - Added Verification Pipeline Status banner (`VERIFIED`, `UNVERIFIED`, `REJECTED`, `EXECUTION_ERROR`).
  - Added 3-run Stability Validation summary card.
  - Added Runtime Coverage Attribution comparison card.
  - Added Coverage-Guided Iteration rounds indicator.
  - Added collapsible Sandboxed Execution Logs console.
- `backend/tests/`:
  - `test_test_stability_service.py`: 7 tests.
  - `test_test_coverage_service.py`: 6 tests.
  - `test_test_mutation_service.py`: 4 tests.
  - `test_test_iteration_service.py`: 5 tests.
  - `test_test_execution_verifier.py`: 5 tests.
  - `test_test_generation_vitest.py`: 6 tests.
  - `test_test_generation_execution_verified.py`: 22 tests validating Scenarios A through V.
  - `test_benchmark_gate_evaluator.py`: 8 tests.
- `Docs/test-generation/`:
  - Authored complete 22-part documentation suite, 6 Mermaid diagrams, and 5 research/tool evaluations.

**Impact:** Generated test files are no longer unverified syntax previews; they are execution-verified, flakiness-tested, and coverage-attributed in isolated sandboxes with end-to-end Vitest support.

**Related Docs:** `Docs/test-generation/`, `Docs/README.md`, `Docs/quality_benchmark_report.md`

---

### [Post-Week3-Batch6] 2026-11-09 — Autonomous Code Synthesis, Plan-Bound Editing & Durable Workflow Execution (Issue #202 / Issue #203)
**Type:** Feature / Security / Distributed Systems  
**Developer:** Meet Virugama (Lead Agent Architect)  
**Changes:**
- `backend/ai/services/edit_synthesizer.py`:
  - Implemented `EditSynthesizer` providing search/replace editing (`search_block`, `replace_block`) inspired by SWE-agent and Aider.
  - Implemented 7-stage validation pipeline: JSON fence parsing, exact single-match validation (`occurrences == 1`), path safety & `fnmatch` forbidden file detection, plan-bound scope enforcement (`expected_files`), atomic in-memory patch application, AST syntax validation (`ast.parse`, `json.loads`), and SHA-256 stale-content fingerprinting.
  - Implemented bounded self-refinement (up to 3 total attempts) with verbal failure feedback.
  - Provided thread-safe synchronous wrapper `synthesize_sync` for direct execution loop integration.
- `backend/ai/services/agent_execution_loop.py`:
  - Extended `StepExecutionRecord` with `synthesis_attempts`, `patch_hashes`, `validation_status`, `changed_files`, `failure_category`.
  - Injected `EditSynthesizer` and eliminated dangerous cross-step payload fallback loop.
  - Preserved caller-supplied payload priority while autonomously synthesizing modifications when payloads are missing.
- `backend/ai/workflows/`:
  - Created `workflow_models.py` defining `AutonomousWorkflowInput`, `AutonomousWorkflowResult`, `AutonomousWorkflowStatus`, and `WorkflowStatusResponse`.
  - Created `autonomous_task_workflow.py` with 7 durable steps (`step_validate_approval`, `step_initialize_workspace`, `step_execute_plan_and_synthesize`, `step_validate_plan_bound_diff`, `step_run_tests_and_repair`, `step_run_independent_verification`, `step_publish_draft_pr_if_authorized`).
  - Added re-entrant registry locking (`threading.RLock`) to guarantee idempotent submission and prevent duplicate workflows.
  - Added Redis pubsub streaming to `platform_events` channel.
- `backend/app/api/v1/tasks.py`:
  - Updated `POST /api/v1/tasks/{task_id}/run-workflow` to accept `async_execution=True` and `Prefer: respond-async`, returning `HTTP 202 Accepted` with `TaskWorkflowAcceptedResponse`.
  - Added `GET /api/v1/tasks/{task_id}/workflow-status` endpoint returning real-time progress, completed steps, and verification results.
- `backend/app/repositories/task_repository.py`:
  - Added `get_approved_plan(task_id)` helper.
- `frontend/src/services/tasks.ts`:
  - Added `startAutonomousWorkflow` and `getWorkflowStatus`.
- `frontend/src/pages/RepositoryTaskStudio.tsx`:
  - Updated `handleRunAutoPilot` to invoke `startAutonomousWorkflow` with async execution and auto-fallback.
- `backend/tests/`:
  - Added `test_edit_synthesizer.py` (19 tests).
  - Added `test_autonomous_task_workflow.py` (6 tests).
  - Validated 58 regression tests (total 83/83 passing).
- `Docs/autonomous-execution/`:
  - Authored comprehensive 14-part documentation suite (`00` through `13` and `README.md`).

**Impact:** The platform can now autonomously synthesize code changes following human plan approval without requiring caller-provided payloads, while executing workflows durably in the background with HTTP 202 acceptance and SSE streaming.

**Related Docs:** `Docs/autonomous-execution/`, `Docs/engineering/13_architecture_decisions.md` (ADR-015), `Docs/README.md`

---

### [Post-Week3-Batch7] 2026-11-10 — Evaluation Dataset Export from Analysis History (Issue #195 / F15)
**Type:** Feature / Evaluation / MLOps  
**Developer:** Meet Virugama & Parth  
**Changes:**
- `backend/app/services/analysis_run_history_service.py`:
  - Implemented `export_evaluation_records` to structure developer intelligence runs (explanations, bugs, tests, reviews) into standardized evaluation samples with input coordinates, output results, findings, and attached user feedback.
  - Implemented `export_evaluation_dataset` supporting `jsonl` (plain JSONL), `langfuse` (Langfuse-compatible dataset items with `input`, `expected_output`, and `metadata`), `json` (formatted array), and `records`.
  - Added multi-tenant isolation, alias normalization (`code_review` -> `review`), and `include_feedback_only` filtering.
- `backend/app/api/v1/analysis/history.py`:
  - Added `GET /api/v1/repositories/{repository_id}/analysis-runs/export` endpoint with format selection, feature filtering, status filtering, and streaming attachment headers.
- `backend/app/schemas/analysis.py`:
  - Added `"code_review": "review"` mapping to `_FEATURE_TYPE_ALIASES`.
- `frontend/src/services/analysis.ts`:
  - Added `exportAnalysisRunsDataset` client method for non-blocking file downloads.
- `frontend/src/components/explorer/AnalysisHistoryDrawer.tsx`:
  - Added one-click **Export** dataset dropdown menu in the drawer header with JSONL, Langfuse, and JSON options and feedback filtering.
- `backend/tests/test_analysis_run_export.py`:
  - 9 comprehensive unit and HTTP integration tests validating JSONL, JSON, Langfuse format, aliases, multi-tenant isolation, error handling, and client downloads.
- `frontend/src/test/analysisHistoryExport.test.tsx`:
  - 3 unit tests verifying UI drawer export button, dropdown menu, and download triggers.
- `Docs/engineering/24_analysis_history_evaluation_export.md`:
  - Authored full technical architecture specification.

**Impact:** Historical developer intelligence interactions and user feedback are now directly exportable into benchmark regression datasets and Langfuse evaluation suites for continuous LLM calibration.

**Related Docs:** `Docs/engineering/24_analysis_history_evaluation_export.md`, `Docs/README.md`

---

### [Post-Week3-Batch8] 2026-11-10 — GitHub Source Browsing & Execution Surface Consolidation (Issue #196)
**Type:** Feature / Refactor / Consolidation  
**Developer:** Parth & Meet Virugama  
**Changes:**
- `backend/app/integrations/github/source_service.py`:
  - Added `list_issues`, `get_issue_detail`, and compatibility `get_issue` for `IssueToTaskAdapter`.
  - Implemented pull request demuxing to filter out PRs from the issue stream while preserving PR metadata.
  - Added consistent 404 handling when upstream repositories are not found on GitHub.
- `backend/app/integrations/github/schemas.py`:
  - Added `RemoteIssueInfo` schema.
- `backend/app/integrations/github/routes.py`:
  - Added `GET /api/v1/repositories/{id}/source/issues` and `GET /api/v1/repositories/{id}/source/issues/{issue_number}`.
  - Deprecated legacy duplicate execution endpoints under `/source/task/*` and `/source/task-workspace/*` with `HTTP 410 Gone` and `X-Canonical-Endpoint: /api/v1/tasks`.
- `backend/app/api/v1/tasks.py`:
  - Deleted unreachable `/{repo_id}/tasks` route aliases.
- `frontend/src/types/api.ts`:
  - Added `RemoteIssueInfo` TypeScript interface.
- `frontend/src/services/repositories.ts`:
  - Added `listRemoteSourceIssues` and `getRemoteSourceIssue` client functions.
- `frontend/src/mocks/handlers/task.ts`:
  - Added MSW mock handlers for remote issues and 410 deprecated execution endpoints.
- `backend/tests/test_github_source_browsing_consolidation.py`:
  - Added 7 unit and integration tests covering issue listing, PR filtering, issue detail lookup, API endpoints, deprecation headers, and 404/invalid number handling.
- `frontend/src/test/sourceIssuesBrowsing.test.ts`:
  - Added 6 frontend tests verifying client methods and MSW mock doubles.
- `Docs/engineering/25_github_source_browsing_and_consolidation.md`:
  - Authored comprehensive architectural and interface specification.

**Impact:** Eliminates duplicate task execution surfaces across the codebase, provides first-class remote issue browsing through GitHubSourceService, and cleans up dead route aliases.

**Related Docs:** `Docs/engineering/25_github_source_browsing_and_consolidation.md`, `Docs/README.md`

---

### [Post-Week3-Batch9] 2026-11-10 — Project Memory Entries, Semantic Retrieval & MCP Resources (Issue #217 / F36)
**Type:** Feature / Episodic Memory / MCP  
**Developer:** Parth & Meet Virugama  
**Changes:**
- `backend/app/models/memory_entry.py` & Alembic Migration `i6f7a8b9c0d1_add_memory_entries_embedding_and_hnsw.py`:
  - Added `embedding vector(768)` nullable column and HNSW cosine distance index `ix_memory_entries_embedding_hnsw` to `memory_entries`.
- `backend/app/repositories/memory_repository.py`:
  - Implemented `semantic_search_entries` utilizing pgvector cosine operator `<=>` (with in-memory fallback for non-Postgres environments) and strict repository isolation.
  - Implemented CRUD and multi-criteria filtering operations.
- `backend/app/services/memory_service.py`:
  - Implemented Reflexion-style automated writers: `record_task_completion_memory`, `record_task_failure_memory`, and `record_architectural_rule` with idempotency deduplication.
  - Implemented Model Context Protocol (MCP 2025-11-25) resource exposure: `list_mcp_resources` and `resolve_mcp_resource` (`memory://repo/{id}/rules`, `decisions`, `task-summaries`, `failures`, `all`).
- `backend/app/services/task_execution_orchestrator.py`:
  - Wired automated memory writers to record task completion memories upon passing independent verification and task failure memories upon verification rejection or exhausted repair attempts.
- `backend/app/api/v1/memories.py`:
  - Mounted CRUD, automated writers, pgvector `/semantic-search`, and `/mcp-resources` endpoints with tenant ownership checks.
- `frontend/src/types/memory.ts` & `frontend/src/services/memory.ts`:
  - Defined memory TypeScript types and client functions for CRUD, rule pinning, and MCP inspection.
- `frontend/src/mocks/handlers/memory.ts`:
  - Added MSW mock handlers for all project memory and MCP routes.
- `frontend/src/components/explorer/ProjectMemoryPanel.tsx`:
  - Built interactive Project Memory management panel with category tabs, real-time search, rule pinning, inline edit/delete, and MCP resource URI inspector.
- `frontend/src/pages/RepositoryDetail.tsx` & `WorkbenchHeader.tsx`:
  - Added memory toggle button to the workbench toolbar to open the Project Memory panel.
- `backend/tests/test_project_memory_service.py`:
  - 7 comprehensive tests covering repository CRUD, automated writers, multi-tenant boundary checks, semantic vector search, and MCP resource resolution.
- `frontend/src/test/projectMemory.test.tsx`:
  - 10 unit and integration tests verifying service calls, badge rendering, category filtering, rule pinning, and MCP URI copying.
- `Docs/engineering/26_project_memory_entries.md`:
  - Authored complete architecture specification.

**Impact:** The platform now maintains persistent episodic memory across tasks, preventing repetitive failures, enforcing pinned architectural standards, and exposing memory to external tools and agents via MCP.

**Related Docs:** `Docs/engineering/26_project_memory_entries.md`, `Docs/README.md`

---

### [Post-Week3-Batch10] 2026-11-10 — Branch, Commit, Push, and Draft PR Publication (Issue #207 / F26)
**Type:** Security / Feature / Git Architecture  
**Developer:** Prit Zania  
**Changes:**
- `backend/sandbox/command_runner.py`:
  - Enforced strict sandbox policy in `WorkspaceCommandRunner.validate_command`: all git network operations (`push`, `pull`, `fetch`, `remote`, `clone`) are rejected with `WorkspacePolicyViolationError`, guaranteeing untrusted containers cannot execute remote Git pushes.
- `backend/app/schemas/workspace.py`:
  - Added `installation_token: str | None = None` to `WorkspacePushRequest` for ephemeral host-side authentication without persisting credentials to disk.
- `backend/sandbox/workspace_manager.py`:
  - Hardened `push_task_branch`: dynamically passes `-c http.extraheader=AUTHORIZATION: basic <base64>` during host subprocess execution, ensuring zero token writes to `.git/config`, zero token leakage into container sandboxes, and full `redact()` scrubbing of errors.
- `backend/app/services/task_execution_orchestrator.py`:
  - Updated `push_verified_branch` to resolve GitHub App installation tokens host-side and supply them securely to `WorkspacePushRequest`.
- `backend/app/integrations/github/routes.py`:
  - Restored contract compatibility endpoint `POST /api/v1/repositories/{id}/source/agent-branch` with `AgentBranchRequest` and `AgentBranchResponse`.
- `backend/tests/test_host_git_push_credential_isolation.py`:
  - Authored 16 unit and security regression tests covering host-side execution, sandbox command rejection, token isolation, error redaction, protected branch guards, authorization gates, and draft PR rules.
- `Docs/engineering/27_branch_commit_push_draft_pr_publication.md`:
  - Authored complete architecture, threat boundary, and sequence specification.

**Impact:** Guarantees strict boundary separation between untrusted sandbox environments and privileged Git operations, ensuring credentials never enter container runtimes and git push operations run host-side exclusively.

**Related Docs:** `Docs/engineering/27_branch_commit_push_draft_pr_publication.md`, `Docs/README.md`

---

### [Post-Week3-Batch11] 2026-11-11 — Bounded Self-Repair Loop & Anti-Reward Hacking (Issue #205 / F24)
**Type:** Feature / AI Architecture / Safety  
**Developer:** Prit Zania  
**Changes:**
- `backend/ai/services/llm_repair_synthesizer.py`:
  - Implemented `LLMRepairSynthesizer` replacing the legacy hardcoded placeholder diff (`def handler(): pass -> return True`).
  - Integrated `EditSynthesizer` (F22) for structured SEARCH/REPLACE block generation, exact match validation, dry-run in-memory patch application, AST syntax validation, and unified diff output.
  - Implemented `format_reflexion_memory` for multi-turn verbal reinforcement history (Reflexion P-19 & Self-Refine P-20).
  - Implemented spectrum-based fault localization (`identify_target_file_and_line`, AgentFL) extracting workspace application frames from tracebacks rather than mistakenly targeting test files.
  - Built robust deterministic fallback generating attempt-differentiated, targeted code repairs with anti-cycling hash variation when LLM gateway is offline.
- `backend/app/schemas/repair.py`:
  - Added `FailureClassification = Literal["infra", "test-bug", "code-bug"]`.
  - Added `failure_classification` to `DiagnosedFailure`.
  - Added `primary_classification` to `TracebackDiagnosisResult`.
- `backend/app/services/repair_service.py`:
  - Implemented `is_test_file`, `extract_application_frames_from_traceback`, `classify_failure`, and `classify_diagnosis`.
  - Added Gate 8: Anti-Reward Hacking Gate to `RepairPatchValidator.validate_patch`: strictly forbids modifying test files to force a test pass during repair unless the approved plan scope explicitly whitelists the test file (`allow_test_edits=True`).
- `backend/ai/prompts/repair_code_system.txt` & `__init__.py`:
  - Created and registered `repair_code_system` prompt template enforcing minimal code repairs, Reflexion memory adherence, and anti-reward hacking constraints.
- `backend/ai/services/bounded_repair_loop.py`:
  - Replaced placeholder stub in `_synthesize_patch` with `LLMRepairSynthesizer` delegation.
  - Enforced immediate halt on infrastructure failures (`TIMEOUT`, `ENVIRONMENT_ERROR`, missing binaries) without consuming repair attempts.
  - Wired Reflexion memory and anti-reward hacking parameters through `run_repair_cycle`.
  - Enhanced `_extract_patched_content` to apply multi-hunk unified diffs with high fidelity.
- `backend/ai/services/__init__.py`:
  - Exported `LLMRepairSynthesizer`.
- `backend/app/services/task_execution_orchestrator.py`:
  - Wired shared `edit_synthesizer` into `BoundedRepairLoop`.
- `backend/tests/test_bounded_repair_loop_f24.py`:
  - Authored 14 comprehensive unit and regression tests verifying LLM repair synthesis, Reflexion memory, anti-reward hacking rejection, fault localization, 3-attempt ceiling, and E2E recovery.
- `Docs/engineering/28_bounded_self_repair_loop.md`:
  - Authored complete architecture, control flow, sequence diagrams, and security specification.

**Impact:** Resolves autonomous recovery loops by replacing placeholder stubs with real LLM-driven repair synthesis, enforcing multi-turn Reflexion memory, preventing reward hacking against test suites, and guaranteeing strict 3-attempt budget containment.

**Related Docs:** `Docs/engineering/28_bounded_self_repair_loop.md`, `Docs/README.md`

---

### [Post-Week3-Batch12] 2026-11-13 — API Security, Role-Based Access Control (RBAC) & CI Pipeline (Issue #211 / F30)
**Type:** Feature / Security / CI
**Developer:** Om / Sukun
**Changes:**
- `.pre-commit-config.yaml`:
  - Added Gitleaks hook (`v8.24.0`) targeting `.gitleaks.toml` for developer-side secret prevention.
- `backend/app/models/user.py`:
  - Implemented `UserRole` enum (`admin`, `developer`, `viewer`) and added indexed `role` column defaulting to `developer`.
- `backend/app/schemas/auth.py` & `backend/app/core/security.py`:
  - Added `role` and `permissions` claims to access tokens and JWT encoding payloads.
- `backend/app/core/auth.py`:
  - Decoded and populated `request.state.role` and `request.state.permissions` in `JWTMiddleware` and `_try_populate_user_state`.
- `backend/app/api/v1/dependencies.py`:
  - Implemented `ROLE_HIERARCHY`, `require_role`, `require_min_role`, and `require_permission` dependency guards.
  - Enhanced `get_owned_repository` and `get_owned_task` to enforce tenant isolation and minimum RBAC role with 403 Forbidden on role deficits and 404 on cross-tenant attempts.
- `backend/app/api/v1/repositories.py`:
  - Guarded `POST /sync` and `DELETE /{repository_id}` with `min_role=UserRole.DEVELOPER`.
- `backend/app/api/v1/tasks.py`:
  - Enforced `min_role=UserRole.DEVELOPER` across task creation, planning, approval/rejection gates, execution, pause/resume/cancel, workspace tools, test execution, bounded repair, independent verification, git branch/commit/push, draft PR publication, checkpoints, and recovery.
- `backend/app/api/v1/memories.py`:
  - Guarded memory creation, updates, and deletion with `min_role=UserRole.DEVELOPER`.
- `backend/migrations/versions/k8b9c0d1e2f3_add_user_role_for_rbac.py`:
  - Added Alembic migration revising `j7a8b9c0d1e2` to add `role` column and index to `users` table.
- `.github/workflows/security-ci.yml`:
  - Built dedicated CI security workflow executing Gitleaks, Bandit, Ruff, pip-audit, `security_gate.py`, and security unit tests on PRs and pushes.
- `backend/scripts/security_gate_allowlist.txt`:
  - Added reviewed test/doc placeholder fingerprints to ensure clean PASS on `security_gate.py`.
- `backend/tests/test_rbac_and_api_security.py`:
  - Authored 12 comprehensive unit and integration tests verifying RBAC hierarchy, JWT claims, route guards, viewer blocks, developer access, and tenant isolation precedence.
- `Docs/security/api_security_rbac_and_ci_report.md`:
  - Published comprehensive F30 architecture, threat model, and verification report.

**Impact:** Provides production-grade API security, role-based access control, and automated CI security gates while strictly preserving multi-tenant isolation and 100% backward compatibility.

**Related Docs:** `Docs/security/api_security_rbac_and_ci_report.md`, `Docs/engineering/10_development_tasks.md`

---

### [Post-Week3-Batch13] 2026-11-14 — Independent Verification Multi-Engine & LLM-as-Judge (Issue #206 / F25)
**Type:** Feature / Security / Verification  
**Developer:** Om (`OM202401238`)  
**Changes:**
- `backend/sandbox/gitleaks_scanner.py`:
  - Implemented `GitleaksDiffScanner` with native `gitleaks` CLI piping and fallback built-in canonical Gitleaks rules engine.
  - Added detection for AWS access key IDs & secret keys, GitHub PATs & OAuth tokens, Slack webhooks, Private RSA/OpenSSH keys, OpenAI keys, Stripe secret keys, and generic high-entropy API tokens.
  - Implemented `.gitleaks.toml` path/allowlist support and benign placeholder skipping (`[REDACTED]`, `<YOUR_KEY>`, doc examples).
  - Ensured all leaked token previews are sanitized and redacted.
  - Added `is_gitleaks_cli_available()` helper.
- `backend/sandbox/diff_verifier.py`:
  - Integrated secondary `GitleaksDiffScanner` inside `WorkspaceDiffVerifier.validate_diff`, checking diff hunks and raw diffs with finding deduplication.
- `backend/app/schemas/verification.py`:
  - Defined `DiffHunkCitation` model (`file_path`, `hunk_index`, `old_start`, `old_lines`, `new_start`, `new_lines`, `line_range`, `hunk_header`, `snippet`).
  - Defined `CriterionJudgeEvidence` model (`criterion_id`, `requirement_id`, `verdict`, `confidence`, `reasoning`, `citations`, `judge_model`, `evaluated_at`).
  - Added `requirement_evidence` fields to `VerificationContext` and `VerificationResult`.
  - Added `"UNMET"` to `CriterionJudgeEvidence.verdict` Literal.
- `backend/ai/services/requirement_verifier.py`:
  - Implemented `extract_diff_hunks_from_diff` supporting `WorkspaceDiffResult`, `TaskDiffRanges`, `FileDiffRange`, and raw unified diff strings.
  - Implemented `LLMRequirementJudge` evaluating each acceptance criterion with calibrated confidence and diff hunk citations.
  - Integrated `LLMRequirementJudge` into `RequirementToCodeVerifier.verify_requirements_against_diff`, attaching `judge_evidence` and `citations` to `RequirementComplianceItem` and `RequirementVerificationResult`.
  - Updated `_generate_pr_markdown_summary` to render the `### Acceptance Criteria Verification (LLM-as-Judge P-28)` table with diff hunk citations.
- `backend/app/services/independent_verifier.py`:
  - Enhanced `scan_diff_for_secrets` to run secondary Gitleaks scanning alongside primary regex patterns.
  - Enhanced `_check_secret_scan` with dual-engine execution, populating check `details` with primary and secondary finding counts and triggered Gitleaks rules.
  - Added `_check_llm_judge_acceptance` evaluating acceptance criteria and enforcing diff hunk citations.
  - Updated `_generate_dev_pr_markdown_summary` to render the `### 📋 P-28 Acceptance Criteria Citations (LLM-as-Judge)` table.
- `backend/app/services/task_execution_orchestrator.py`:
  - Passed `criteria_evidence` through `run_independent_verification` and attached it to `VerificationResultSchema`.
- `backend/tests/test_independent_verification_f25.py`:
  - Authored comprehensive test suite covering `GitleaksDiffScanner`, diff hunk extraction, `LLMRequirementJudge`, `RequirementToCodeVerifier`, `IndependentVerifier`, and `WorkspaceDiffVerifier` (19/19 tests passing).
- `Docs/security/independent_verification_f25_report.md`:
  - Authored comprehensive architecture, sequence, and verification acceptance report.
- `Docs/engineering/10_development_tasks.md`:
  - Recorded PW3-06 under Om and updated master task board.

**Impact:** Establishes defense-in-depth verification by adding a secondary Gitleaks secret engine and eliminating reward hacking/hallucinations via P-28 LLM-as-judge diff hunk citation evidence.

**Related Docs:** `Docs/security/independent_verification_f25_report.md`, `Docs/engineering/10_development_tasks.md`

---

### [PW3-10] 2026-11-14 — F23 Restricted Test Runner (Issue #204)
**Type:** Feature / Testing / Sandbox / Quality  
**Developer:** Om (`OM202401238`)  
**Changes:**
- `backend/app/schemas/workspace.py`:
  - Defined `TestCaseResult` model (`name`, `classname`, `file`, `time_s`, `status`, `failure_message`, `failure_type`, `traceback`) with `__test__ = False`.
  - Defined `TestSuiteResult` model (`name`, `tests_total`, `passed`, `failed`, `skipped`, `errors`, `time_s`, `test_cases`, `raw_xml_path`) with `__test__ = False`.
  - Defined `CoverageMetric` model (`total`, `covered`, `skipped`, `percent`).
  - Defined `FileCoverageDetail` model (`file_path`, `lines`, `branches`, `statements`, `functions`, `missing_lines`, `executed_lines`).
  - Defined `TestCoverageSummary` model (`lines`, `branches`, `statements`, `functions`, `files`, `total_percent`, `raw_report_path`) with `__test__ = False`.
  - Extended `WorkspaceTestExecutionRequest` with `collect_coverage`, `junit_xml`, and `sandbox_backend`.
  - Extended `WorkspaceTestExecutionResult` with `junit_report: TestSuiteResult | None` and `coverage: TestCoverageSummary | None`.
  - Updated `__all__` and exported schemas in `backend/app/schemas/__init__.py`.
- `backend/sandbox/test_reports.py`:
  - Implemented `JUnitReportParser` parsing standard JUnit XML files and strings (`pytest`, `jest`, `vitest`), extracting exact counts, failure assertion messages, failure types, and stack tracebacks with resilient error handling.
  - Implemented `CoverageReportParser` parsing Python `coverage.py` / `pytest-cov` JSON and JavaScript `jest` / `istanbul` summary JSON, extracting statement, line, branch, and function metrics with per-file missing lines breakdown.
- `backend/sandbox/test_runner.py`:
  - Added `backend: SandboxBackend | None = None` parameter to `WorkspaceTestRunner.__init__`, configuring `_command_runner.backend` for container isolation (F20).
  - Added `backend` property with getter and setter.
  - Created `.test_reports/` directory in task workspace for isolated test artifact storage.
  - Injected standard structured report CLI flags: `--junitxml=.test_reports/junit.xml`, `-o junit_family=xunit2`, `--cov=. --cov-report=json:.test_reports/coverage.json` for pytest; `--coverage --coverageReporters=json-summary` for Jest/Vitest.
  - Integrated `JUnitReportParser` to parse emitted XML, replacing fragile stdout regex scraping with high-precision failure diagnosis and exact failure names/tracebacks.
  - Integrated `CoverageReportParser` to parse emitted coverage reports, serving as the quantitative foundation for framework-aware test generation (F13).
- `backend/sandbox/workspace_manager.py`:
  - Passed `backend=self._backend` to `WorkspaceTestRunner` on initialization.
- `backend/sandbox/tool_policy_bridge.py`:
  - Updated `TOOL_RUN_TESTS` input parameter schema with `collect_coverage`, `junit_xml`, and `sandbox_backend`.
  - Wired `junit_report` and `coverage` into `ToolResult.output`.
- `backend/app/services/task_execution_orchestrator.py`:
  - Updated `execute_task_tests` to accept and pass `collect_coverage`, `junit_xml`, and `sandbox_backend` into `WorkspaceTestExecutionRequest`.
- `backend/tests/test_restricted_test_runner_f23.py`:
  - Authored comprehensive test suite covering `JUnitReportParser`, `CoverageReportParser`, container backend binding with `network_enabled=False`, argument injection, and `ToolPolicyBridge` integration (14/14 tests passing).
- `Docs/testing/restricted_test_runner_f23_report.md`:
  - Published comprehensive technical architecture and verification acceptance report.
- `Docs/engineering/10_development_tasks.md`:
  - Recorded PW3-07 under Om on the master task board.

**Impact:** Fulfills all recommendations of Issue #204 by enforcing container backend execution (F20) with offline network isolation, replacing fragile stdout scraping with high-precision JUnit XML failure diagnosis, and collecting line and branch coverage metrics required for F13 test generation.

**Related Docs:** `Docs/testing/restricted_test_runner_f23_report.md`, `Docs/engineering/10_development_tasks.md`

---
### [PW3-11] 2026-11-14 — Amortized Static Scanner Subprocess Execution & Parallel Analysis (F39)
**Type:** Feature / Performance / Code Review  
**Developer:** Meet (`MEET202401001`) & Dev (`DEV202401002`)  
**Changes:**
- `backend/review/static_reviewer.py`:
  - Implemented `_sanitize_target_paths` with strict validation against command and option injection (`-` prefix, `\x00`, empty strings).
  - Implemented `_build_scanner_command` with `--` end-of-options delimiter preceding batch file targets for `ruff`, `bandit`, `eslint`, and `biome`.
  - Implemented `_parse_scanner_output` consolidating JSON parsing, line offset derivation, and schema normalization across sync and async callers.
  - Implemented `_group_files_by_scanner` to partition modified files into tool-specific target lists based on file extension and repository configuration.
  - Enhanced `run_scanner` to accept `target_path: str | Sequence[str]` for full backward compatibility and batch amortization.
  - Implemented `run_scanner_async` using `asyncio.create_subprocess_exec` with non-blocking pipe reads, 60s timeout handling, and process termination guarantees.
  - Enhanced `review_modified_files` with default `batch=True` and `parallel=True` via `ThreadPoolExecutor`, reducing sequential launches from $O(M \times S)$ to $O(S)$.
  - Implemented `review_modified_files_async` leveraging `asyncio.gather` for concurrent scanner subprocess execution.
- `backend/scanner/static_bug_scanner.py`:
  - Added `scan_files` for multi-file AST scanning with optional parallel thread pool execution and aggregated metrics.
  - Added `scan_files_async` for non-blocking asynchronous multi-file AST analysis.
- `backend/app/api/v1/analysis/review.py`:
  - Updated review endpoint static analysis resolver to prefer `review_modified_files_async` on `ext_reviewer`, executing coroutine functions directly without thread hopping.
- `backend/tests/test_amortized_static_reviewer_f39.py`:
  - Added 19 comprehensive unit and integration tests covering single/multi-target invocations, option injection defense, scanner grouping, async timeout reaping, scanner fault tolerance, and API reviewer resolution.
- `backend/tests/test_static_reviewer.py`:
  - Updated `test_review_modified_files_handles_multiple_files` to verify amortized single-invocation batch execution and added `test_review_modified_files_legacy_unbatched_mode`.
- Documentation:
  - Added **ADR-019: Amortized Batch Target Invocations & Concurrent Static Scanner Execution** to `Docs/engineering/13_architecture_decisions.md`.
  - Created `Docs/code-review/AMORTIZED_STATIC_SCANNER_PERFORMANCE.md` and `Docs/engineering/32_amortized_static_scanner_parallel_analysis.md`.
  - Updated `Docs/engineering/README.md` and `Docs/README.md`.

**Impact:** Reduces multi-file static analysis latency by 85–90% (from ~22s down to ~1.6s for 10 files) while maintaining 100% schema backward compatibility and hardening against option injection.

**Related Docs:** `Docs/engineering/32_amortized_static_scanner_parallel_analysis.md`, `Docs/code-review/AMORTIZED_STATIC_SCANNER_PERFORMANCE.md`, `Docs/engineering/13_architecture_decisions.md`

---

### [PW3-12] 2026-11-14 — Redis Thread/Coroutine-Safe Singleton & Bounded Connection Pooling (F40)
**Type:** Feature / Reliability / Infrastructure  
**Developer:** Meet (`MEET202401001`) & Dev (`DEV202401002`)  
**Changes:**
- `backend/app/core/redis.py`:
  - Implemented thread-safe double-checked locking using `threading.Lock` within `get_async_redis_client()` and `get_redis()`, preventing race conditions during application bootstrap and traffic bursts.
  - Added coroutine-safe synchronization with running-loop-aware `asyncio.Lock` in `get_redis_async()`.
  - Configured explicit connection pool limits using `redis.asyncio.ConnectionPool` and `redis.ConnectionPool` with `max_connections=settings.redis_max_connections` (default: 50).
  - Implemented `run_with_redis_retry` and `is_redis_pool_exhausted_error` with exponential backoff and jitter for transient connection pool exhaustion, raising descriptive `RedisPoolExhaustedError` on persistent failure.
  - Enhanced `close_redis_async()` and `close_redis()` to disconnect underlying connection pools alongside client handles for leak-free draining.
  - Preserved backward compatibility with `get_redis.cache_clear()` alias and seamless synchronous/asynchronous calling conventions.
- `backend/app/core/config.py`:
  - Added Redis connection pooling and reliability settings: `redis_max_connections` (50), `redis_connection_timeout` (5.0s), `redis_socket_timeout` (10.0s), `redis_health_check_interval` (30s), and `redis_retry_on_timeout` (True).
- `backend/tests/test_redis_reliability_f40.py`:
  - Added 12 comprehensive unit and integration tests covering concurrent coroutine singleton creation (50 coroutines), multithreaded singleton access (32 worker threads), pool size bounding, custom settings overrides, clean lifecycle draining, transient exhaustion backoff, persistent exhaustion error handling, and zero breaking changes.
- Documentation:
  - Added **ADR-020: Thread/Coroutine-Safe Redis Singleton Initialization and Bounded Connection Pooling** to `Docs/engineering/13_architecture_decisions.md`.
  - Created `Docs/engineering/33_redis_singleton_and_bounded_connection_pooling.md`.
  - Updated `Docs/engineering/README.md`, `Docs/README.md`, and `Docs/engineering/10_development_tasks.md` (PW3-08).

**Impact:** Eliminates Redis connection pool race conditions, prevents `ConnectionError: Too many connections` socket exhaustion on hosted Redis tiers, and ensures graceful degradation under peak load.

**Related Docs:** `Docs/engineering/33_redis_singleton_and_bounded_connection_pooling.md`, `Docs/engineering/13_architecture_decisions.md`

---

### [PW3-13] 2026-11-14 — Stream Unified Git Diffs & Memory-Bound Patch Verification (F40/F41)
**Type:** Feature / Performance / Sandbox Reliability  
**Developer:** Meet (`MEET202401001`) & Dev (`DEV202401002`)  
**Changes:**
- `backend/sandbox/diff_verifier.py`:
  - Implemented streaming line generator `iter_diff_lines` with bounded byte accounting (`DEFAULT_MAX_DIFF_BYTES = 10MB`) and truncation markers (`DIFF_TRUNCATION_MARKER`), eliminating $O(\text{diff\_size})$ contiguous heap allocations.
  - Implemented streaming diff parser `iter_parse_unified_diff` state machine consuming lines iteratively with $O(1)$ buffer consumption, yielding `FileDiffSummary` as each file completes.
  - Added early path guard checking on file headers (`diff --git`, `---`, `+++`), validating `validate_repo_relative_path` and workspace containment immediately, halting with `UnsafePathError` before consuming subsequent diff chunks.
  - Added streaming primary secret scanning `iter_scan_secrets_lines` evaluating added lines line-by-line via generator pipelines.
  - Enhanced `extract_diff` to stream from git (`_stream_git_diff_lines`) or filesystem (`_stream_fs_diff_lines`), safely terminating git subprocesses upon exceeding 10MB and setting truncation errors without memory explosion.
  - Added streaming verification entrypoint `stream_validate_diff` for end-to-end evaluation with minimal peak memory.
- `backend/sandbox/gitleaks_scanner.py`:
  - Added `scan_diff_stream` and `iter_scan_rules` to evaluate canonical Gitleaks rules iteratively across streamed diff lines without full-diff text duplication.
- `backend/app/services/repair_service.py`:
  - Implemented `iter_modified_files_from_diff` and upgraded `extract_modified_files_from_diff` to accept both raw strings and streaming line iterables with optional early path guard checking.
  - Updated `RepairPatchValidator.validate_patch` with early path guard checking support.
- `backend/sandbox/__init__.py`:
  - Exported `DEFAULT_MAX_DIFF_BYTES`, `DIFF_TRUNCATION_MARKER`, `iter_diff_lines`, and `iter_parse_unified_diff`.
- `backend/tests/test_stream_diff_verifier_f40.py`:
  - Added 19 comprehensive unit and integration tests verifying incremental line streaming, multi-file generator parsing, early path guard interception halting generators, byte threshold truncation marker enforcement, subprocess termination on limit, peak heap memory strictly bounded under 20MB (`tracemalloc` across 400-file, 30MB+ diff streams), streaming secret scanning, and 100% schema backward compatibility.
- Documentation:
  - Added **ADR-021: Streaming Unified Git Diffs and Memory-Bound Patch Verification for Large Refactors** to `Docs/engineering/13_architecture_decisions.md`.
  - Created `Docs/engineering/34_stream_unified_git_diffs_and_memory_bound_patch_verification.md`.
  - Updated `Docs/engineering/README.md`, `Docs/README.md`, and `Docs/engineering/10_development_tasks.md` (PW3-09).

**Impact:** Eliminates Out-Of-Memory (OOM) risks during large refactor diff verification in memory-constrained Docker containers, guarantees peak heap memory < 20MB, intercepts path traversal attacks on header lines, and preserves complete backward compatibility.

**Related Docs:** `Docs/engineering/34_stream_unified_git_diffs_and_memory_bound_patch_verification.md`, `Docs/engineering/13_architecture_decisions.md`

