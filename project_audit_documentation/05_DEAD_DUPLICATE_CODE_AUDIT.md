# 05 — Dead Code and Duplicate Code Audit

**Method.** (1) Python import graph over `backend/` (static `import`/`from` statements anywhere in a module, including function-local lazy imports, plus string constants equal to module names) from the entry points `app.main`, `app.workers.sync_worker`, `app.workers.webhook_worker`, `migrations.env`, `scripts/*`, `runner/*`. (2) For modules whose only production importer is their own package `__init__` (re-export), every public top-level symbol was searched by word-boundary regex across all non-test, non-`__init__` Python files. (3) Dynamic-loading check: `importlib.import_module`, `__import__`, `entry_points`, `getattr(module,…)` across `app ai agent sandbox scanner` — the only dynamic import is tree-sitter language bindings in `scanner/parser.py` L790. (4) FastAPI routing, `app.state` DI and event registration were considered (routes count as used; `app.state` assignments were checked for readers). (5) Frontend: TS import graph from `src/main.tsx` (static + `import()`), excluding tests/mocks.

**Rule applied:** nothing is classified "Remove" unless (a) no static or dynamic production reference exists **and** (b) it is not a route, decorator-registered handler, worker entrypoint, Alembic revision or script. Test-only usage is reported separately ("test-only") because deleting such code also requires deleting/porting its tests.

**Caveat:** The test suites were not executed (00 §1.2). Every removal batch must be validated with the full backend and frontend test suites plus `vite build` (see "Validation" column).

IDs `DC-01` … `DC-31`. Each row: File · Symbol · Category · Evidence · Dependencies (who uses it) · Risk · Recommendation · Validation.

---

## 1. Summary

| Category | Items | Approx. LOC |
|---|---|---|
| Dead backend modules (no production reference; test-only) | 14 modules (DC-04 … DC-14) | ≈ 3,800 |
| Dead/duplicate API endpoints | 9 routes (DC-01, DC-21, DC-26, DC-28) | ≈ 450 |
| Duplicate implementations (same responsibility twice) | 7 (DC-02, DC-16, DC-17, DC-20, DC-21, DC-30, DC-03) | — |
| Dead DI wiring | 4 `app.state` attributes (DC-15 / ISS-039) | ≈ 30 |
| Unused imports | 82 (DC-23) | 82 lines |
| Frontend dead code | 1 file + unused SSE event constants (DC-18, DC-31) | ≈ 160 |
| Dev-only duplication | custom MSW + 4.3k LOC mocks (DC-19) | ≈ 4,800 |
| Configuration / repository clutter | DC-22, DC-24, DC-25, DC-29 | — |

---

## 2. Backend dead code

### 2.1 Modules reachable only from tests

| ID | File | Symbol(s) | Category | Evidence | Dependencies | Risk if removed | Recommendation | Validation |
|---|---|---|---|---|---|---|---|---|
| DC-04 | `backend/ai/context/service.py` (535 LOC) | `RepositoryContextService`, `shared_context_service`, `RevisionDriftError`, `CacheEntry` | Dead (DI-only) | Instantiated in module; assigned to `app.state.context_service` in `lifespan.init_context_service` (L370–381) but **never read** (ISS-039); symbols referenced only in tests (2 files) | `ai/context/__init__.py` re-export; `lifespan.py`; 2 tests | Low | **Remove** module, re-export, `init_context_service`, readiness key — *or* adopt it as the single context entry point if the team intended to (then route all 4 studios through it). Decide once. | `grep -R "context_service\|RepositoryContextService" backend --include=*.py` → only tests; run `pytest backend/tests`; `/health/ready` still green |
| DC-05 | `backend/app/services/task_recovery.py` (166) | `TaskRecoveryService` | Test-only | No production reference; `/tasks/{id}/recover` uses the orchestrator | `app/services/__init__.py` re-export; 1 test | Low | **Remove** (port any unique assertions to orchestrator recovery tests) | pytest; recovery E2E (TST-E4) |
| DC-06 | `backend/sandbox/two_phase_pipeline.py` (196) | `TwoPhaseExecutionService` | Test-only | No production reference | `sandbox/__init__.py`; 1 test | Low | **Remove** | pytest sandbox suite |
| DC-07 | `backend/scanner/scip_runner.py` (534) | `SCIPRunner`, `SCIPIndexerConfig`, … (7 classes) | Test-only | No production reference; SCIP binaries not installed anywhere | `scanner/__init__.py`; 1 test | Low | **Remove** (or move to `experimental/` if SCIP indexing is on the roadmap) | pytest |
| DC-08 | `backend/scanner/task_test_planner.py` (350), `backend/scanner/workspace_preflight.py` (155) | `TaskTestPlanner`, `WorkspaceBaseValidator`, `WorkspacePreflightResult` | Test-only | No production reference | `scanner/__init__.py`; 3 tests | Low–Medium (overlap with `sandbox/test_runner.py` and `TestExecutionVerifier`) | **Remove** after confirming the canonical test selection lives in `sandbox/test_runner.py` | pytest; task `/tests` E2E |
| DC-09 | `backend/agent/tools/adapters/plugin.py` (53) | `PluginToolAdapter` | Dead | Zero references (prod or tests) | `agent/tools/adapters/__init__.py` | Very low | **Remove** | pytest; import `agent.tools` |
| DC-10 | `backend/ai/intelligence/impact.py` (192) | `DependencyImpactAnalyzer`, `ImpactAnalysisReport` | Test-only | Only `ai/intelligence/__init__.py` re-export + 2 tests | — | Low | **Keep and wire** if blast-radius analysis is wanted in review/planning (it is described in `Docs/task_planning_blast_radius_audit.md`), otherwise **remove** | pytest |
| DC-11 | `backend/app/observability/genai.py` (83) | `build_llm_span_attributes` | Test-only | LLM spans built inline in `ai/llm/client.py` | `app/observability/__init__.py`; 1 test | Low | **Merge**: use it from `LLMGateway` (removes duplicated attribute code) or remove | pytest; span attributes asserted in provider tests (TST-36) |
| DC-12 | `backend/app/services/test_generation_report.py` (80) | `format_test_suite_report_markdown` | Test-only | No production caller | `app/services/__init__.py`; 2 tests | Low | **Remove** or expose as `GET /analysis-runs/{id}/report.md` if users need export | pytest |
| DC-13 | `backend/ai/embeddings/local_provider.py` (189) | `CodeRankEmbedProvider`, `evaluate_local_embedding_candidate` | Eval-only | Guarded by `allow_local_embeddings`; not used by app | `ai/embeddings/__init__.py`; 1 test | Low | **Keep** under `ai/evaluation/` (move) — evaluation asset, not runtime | pytest evaluation suite |
| DC-14 | `backend/app/services/{incremental_review_service.py (141), review_deduplication_service.py (209), review_lifecycle_service.py (164), test_mutation_service.py (311)}` | `IncrementalReviewService`, `ReviewDeduplicationService`, `ReviewLifecycleService`, `TestMutationService` | Test-only | Not imported by any router/orchestrator; dedupe & lifecycle logic exists separately inside `code_review_orchestrator.py`/`review_validation_service.py` | tests only | Medium — they may contain better logic than the live path | **Evaluate then Merge or Remove**: diff their behaviour against the live review path; if superior, wire into `code_review_orchestrator.py`; otherwise delete | review quality benchmark (`tests/test_code_review_quality_benchmark.py`) before/after |
| DC-15 | `backend/app/core/lifespan.py` `init_history_services` (partially), `init_context_service` | `app.state.{explanation_history_service, bug_scan_history_service, task_history_service, context_service}` | Dead DI | Assigned, never read (ISS-039) | — | Very low | **Remove** assignments/readiness keys, or route consumers through them consistently | readiness endpoint output; pytest |

### 2.2 Modules exported only by their package `__init__` (but used by production code elsewhere — keep)
`app/repositories/analysis/{bug_scans,explanations,retention,reviews,test_generation}.py` and `app/repositories/task/publication.py` are mixins composed in their package `__init__` — **used**. `ai/agent/tools/*.py` are registered through `ai.agent.tools` — **used**. `app/workers/*`, `runner/main.py` are entrypoints — **used**. `app/observability/{instrumentation,telemetry}.py` are used by `lifespan.py` through the package — **used**. `poc/dbos/workflow.py` — see DC-24.

### 2.3 Duplicate implementations

| ID | Duplicates | Category | Evidence | Recommendation | Validation |
|---|---|---|---|---|---|
| DC-01 | `/repositories/{id}/source/task/{action}` and `/source/task-workspace/{action}` (deprecated stubs, `integrations/github/routes.py` L504–538); `/source/agent-branch` (L256), `/source/commit` (L296), `POST /source/pr-metadata` (L338) vs `/tasks/{id}/branch`, `/tasks/{id}/commit`; `/source/diff-ranges/task/{id}` (L395) vs `/tasks/{id}/diff` | Duplicate / dead endpoints | Stubs return a deprecation response; the 3 write routes have no FE caller; diff exists twice and FE calls both (`services/tasks.ts` L350, L358) | **Remove** stubs after one release with deprecation logs at zero hits; **remove** the 3 `/source/*` write routes (verify their guards are a subset of `/tasks/*` guards first); **merge** diff ranges into `/tasks/{id}/diff?ranges=true` | Access logs show zero calls; pytest; FE diff panel E2E |
| DC-02 | `ai/retrieval/pipeline.py` `RAGPipeline` (177) vs canonical `ai/pipeline.py` `RAGPipeline` (781) | Duplicate class name | Module docstring says it is a facade for Day-5/Week-1 tests; production imports `ai.pipeline` | **Remove** facade; update 4 tests to use `HybridRetriever` directly | pytest retrieval tests |
| DC-03 | `ai/retrieval/reranker_factory.py` (81) + `reranker_onnx.py` (182) vs direct `CrossEncoderReranker()` in `lifespan.py` L146 | Unwired abstraction | `create_reranker` has no production caller | **Wire** (ISS-008) — do not delete | factory unit tests; rerank benchmark |
| DC-16 | `ai/agent/tool_registry.py` + `tool_executor.py` (chat agent tools) vs `agent/tools/registry.py` + `router.py` (task tools) | Parallel tool frameworks | Different policies/rate limits/schemas; both define tool specs and validation | **Refactor**: extract shared `ToolSpec`/schema validation into one module (`agent/tools/schema_validator.py` already uses `jsonschema`); keep two runtimes (different trust levels) | Both tool suites green |
| DC-17 | `app/integrations/github/service.py` `GitHubService` (1,071) vs `source_service.py` `GitHubSourceService` (1,071) | Overlapping service layers | Both implement `list_issues`, `get_issue`; branch creation in both (`create_task_branch` vs `setup_task_branch`); push via `GitHubService.push_branch` **and** git CLI in `WorkspaceManager.push_task_branch` | **Merge** issue/branch responsibilities: `GitHubService` = GitHub API (installations, repos, PRs, issues, reviews); `GitHubSourceService` = read-only content access (files, tree, commits, diffs). Single push path: `WorkspaceManager` (git) with token via env (ISS-019) | GitHub integration tests (`tests/test_github_source_integration.py`) |
| DC-20 | `frontend/src/pages/TaskDetail.tsx` (628) + `components/tasks/*` vs `pages/RepositoryTaskStudio.tsx` (1,552) + `components/taskStudio/TaskPhasePanels.tsx` (926) | Duplicate UI feature | Two task-detail experiences on two routes (04 C-1) | **Merge** into one `TaskWorkspace` component reused by both routes | Vitest task suites; manual walkthrough |
| DC-21 | `POST /tasks/{id}/publish` (alias, `tasks.py` L1741) + FE 404 fallback (`services/tasks.ts` L598–620) | Duplicate endpoint | Alias simply calls `create_task_draft_pr_endpoint` | **Remove** alias + fallback; FE calls `create-pr` | API + FE publish tests |
| DC-26 | `GET/POST /repositories/{id}/tasks` (`tasks.py` L2087, L2114) | Duplicate endpoints | Equivalent to `/tasks?repository_id=` and `POST /tasks {repository_id}`; no FE caller | **Remove** | pytest; OpenAPI diff |
| DC-28 | `GET` and `POST /repositories/{id}/search` (`repositories.py` L229, L253) | Duplicate endpoint | Same operation, two verbs; no FE caller | **Keep POST** when building FP-BE-02; remove GET | pytest |
| DC-30 | Tables `pull_requests` vs `task_pull_requests` | Duplicate data model | ISS-042 | **Merge** into `task_pull_requests` (migration) | migration test (TST-26) |
| DC-27 | `app/core/telemetry.py` (stage metrics/cost) vs `app/observability/telemetry.py` (OTel) | Name collision (not duplicate logic) | Different responsibilities | **Rename** `app/core/telemetry.py` → `app/core/stage_metrics.py` (update 4 imports in `api/v1/analysis/*`) | pytest; grep for old import |

### 2.4 Repeated logic worth consolidating (refactor, not delete)
- Lazy service construction in routers (`chat.py` builds `AgentOrchestrator`; analysis routes fall back to constructing services) duplicates `lifespan.py` logic → typed `Depends` providers (OPT-06).
- Ownership helpers re-declared per router (`_owned_repository`, `_owned_task`, `_verify_owned_repository`, `_request_user_id`) wrap `dependencies.py` functions → use `Depends(owned_repository)` directly.
- Error-swallowing wrappers around persistence (`record_run` try/except in each orchestrator) → one `AnalysisRunRecorder` with explicit failure metric (ISS-038).
- Four studio orchestrators each implement target resolution (DB file vs GitHub source) → shared `TargetResolver` (already partially in `ai/context` builders; verify before extracting).

### 2.5 `poc/` and evaluation assets
| ID | Item | Recommendation |
|---|---|---|
| DC-24a | `backend/poc/dbos/` (386 LOC; imported only by `tests/test_reliable_worker_architecture.py`) | Decide with ISS-010: if DBOS is adopted, promote patterns into `ai/workflows`; otherwise **remove** POC + `dbos` dependency (DEP-05) |
| DC-24b | `backend/ai/evaluation/mini_swebench/dataset/tasks/TASK-0xx/*.py` (125 files) | **Keep** (benchmark data; intentionally not imported). Exclude from Ruff/coverage and from the Docker image (they are already under `backend/`, which is copied) |

### 2.6 Unused imports (DC-23)
82 unambiguous unused imports (the imported name occurs exactly once in its file). Fix with `ruff check --select F401 --fix backend --exclude backend/tests` (Ruff is the project's configured linter) and review the diff; keep intentional availability probes with `# noqa: F401` (e.g., `import onnxruntime` in `ai/retrieval/reranker_factory.py` L54).

- `ai/workflows/autonomous_task_workflow.py`: 'asyncio@16', 'redact_obj@29', 'AgentTask@30', 'TaskStatus@30', 'WorkspaceExecutionEventType@32', 'TaskExecutionOrchestrator@33'
- `app/services/test_execution_verifier.py`: 'TestOutcomeStatus@35', 'WorkspaceIsolationType@35', 'WorkspaceTestExecutionRequest@35', 'WorkspaceTestExecutionResult@35', 'TargetCoverageData@42', 'MAX_STABILITY_RUNS@44'
- `app/services/review_publication_service.py`: 'hashlib@18', 'UUID@22', 'redact_obj@24', 'ReviewCategory@25', 'GitHubError@393'
- `app/services/incremental_review_service.py`: 'timezone@14', 'UUID@17', 'CodeReviewRequest@19', 'ReviewFinding@19', 'ReviewReportResponse@19'
- `ai/services/edit_synthesizer.py`: 'UTC@28', 'CRITICAL_PROJECT_FILES@37', 'WorkspaceError@38', 'WorkspacePathGuard@39'
- `ai/services/llm_repair_synthesizer.py`: 'ast@24', 'Mapping@32', 'PlanStep@37', 'classify_failure@45'
- `runner/main.py`: 'CORSMiddleware@16', 'JSONResponse@17', 'WorkspaceCommandError@34'
- `app/services/review_validation_service.py`: 'field@15', 'UUID@18', 'ReviewCategory@21'
- `agent/tools/router.py`: 'field@16', 'math@20', 'RateLimitDecision@33'
- `scripts/benchmark_rag.py`: 'uuid4@18', 'evaluate_retriever@22', 'RAG_BENCHMARK_DATASET@26'
- `scripts/benchmark_quality_suite.py`: 'QualityGateConfig@41', 'SemgrepRunner@57', 'TaintAnalyzer@58'
- `sandbox/two_phase_pipeline.py`: 'WorkspaceCommandError@17', 'WorkspaceTestExecutionError@17'
- `sandbox/container_backend.py`: 'SandboxConfigurationError@32', 'SandboxResourceLimitError@32'
- `ai/evaluation/mini_swebench/models.py`: 'Any@5', 'Dict@5'
- `ai/security/taint_policy.py`: 'DataProvenance@22', 'TrustLevel@22'
- `app/services/test_iteration_service.py`: 'Any@28', 'IterationRound@30'
- `app/services/review_history_service.py`: 'get_repo_review_settings@33', 'set_repo_review_settings@33'
- `sandbox/local_backend.py`: 'SandboxConfigurationError@28'
- `ai/evaluation/mini_swebench/runner.py`: 'Path@8'
- `ai/services/agent_execution_loop.py`: 'EditSynthesizer@44'
- `ai/services/bounded_repair_loop.py`: 'FailureClassification@26'
- `ai/services/hierarchical_localizer.py`: 'SymbolEdge@28'
- `ai/services/issue_task_adapter.py`: 'create_provenance@24'
- `ai/retrieval/cache.py`: 'time@18'
- `ai/retrieval/reranker_factory.py`: 'onnxruntime@54'
- `ai/security/provenance.py`: 'secrets@13'
- `app/services/webhook_worker.py`: 'GitHubWebhookEvent@19'
- `app/services/review_lifecycle_service.py`: 'field@14'
- `app/services/review_feedback_service.py`: 'AnalysisRun@25'
- `app/services/independent_verifier.py`: 'DiffHunkCitation@26'
- `app/services/memory_service.py`: 'Any@15'
- `app/services/test_mutation_service.py`: 'Any@29'
- `app/observability/telemetry.py`: 'PeriodicExportingMetricReader@15'
- `app/observability/metrics.py`: 'Any@12'
- `app/observability/genai.py`: 'BaseModel@11'
- `app/api/v1/memories.py`: 'RepositoryRepository@30'
- `app/api/v1/mcp_registry.py`: 'Any@7'
- `agent/tools/adapters/builtin.py`: 'ToolResult@15'
- `scanner/gitleaks_runner.py`: 'Sequence@24'
- `scanner/taint_specs.py`: 'Sequence@14'
- `scanner/multilang_security_scanner.py`: 'Sequence@22'
- `scanner/osv_runner.py`: 'Sequence@25'

Format: `name@line`.

---

## 3. Frontend dead and duplicate code

| ID | File | Symbol | Category | Evidence | Dependencies | Risk | Recommendation | Validation |
|---|---|---|---|---|---|---|---|---|
| DC-18 | `frontend/src/lib/classifyAnalysisError.ts` (142) | `classifyAnalysisError` | Dead in production | Not reachable from `src/main.tsx`; imported only by `src/test/classifyAnalysisError.test.ts` | 1 test | Very low | **Remove** with its test, or **wire** into `useAnalysis` error handling if its categorisation is richer than `normaliseError` | `npx tsc -b`, `vitest run`, `vite build` |
| DC-19 | `frontend/src/lib/msw/{index,node,browser}.ts` (custom re-implementation of MSW), `src/lib/mswBootstrap.ts`, `src/mocks/handlers/{task.ts 4,016 LOC, memory.ts 271, …}` | Mock layer | Dev/test-only duplication | `vite.config.ts` aliases `msw` to the local shim; handlers encode response shapes that already diverge from the backend (ISS-017 `summary`) | Vitest suites, `VITE_ENABLE_MSW` dev mode | Medium (tests depend on it) | **Replace** the shim with the real `msw` package (dev dependency) and generate handlers' types from OpenAPI; shrink `task.ts` mock to fixtures per test | full vitest suite |
| DC-31 | `frontend/src/realtime/events.ts` | `TASK_STATUS_UPDATED`, `TASK_STEP_UPDATED`, `CHAT_*`, `TOOL_INVOCATION_*` constants | Unused (no consumer) | Only `REPO_UPDATED` is consumed (`hooks/useRealtimeRepositories.ts`) | — | Low | **Keep and wire** (FP-BE-06, FP-FE-02); remove any that remain unused after OPT-11 | vitest realtime tests |
| DC-25 | `frontend/postcss.config.js` `autoprefixer` + devDependency | Redundant plugin (suspected) | Tailwind v4's `@tailwindcss/postcss` performs vendor prefixing via Lightning CSS | — | Low | **Remove** after visual check of built CSS (compare `dist/assets/*.css` before/after) | `vite build` + CSS diff |
| DC-20 | see §2.3 | | | | | | | |

Frontend dependency usage check (non-test imports): `@tanstack/react-query` 13 files, `axios` 2, `clsx` 1, `tailwind-merge` 1, `zustand` 2, `lucide-react` 52, `react-router-dom` 29 — all used.

---

## 4. Configuration and repository redundancy

| ID | Item | Evidence | Recommendation |
|---|---|---|---|
| DC-22 | `vercel.json` (root) and `frontend/vercel.json` | Same rewrites/headers; root one also sets build command | Keep **one** (root, since Vercel project builds from repo root per `buildCommand`); remove the other after confirming the Vercel project's root directory setting |
| DC-29a | Root sprint documents: `task.md`, `task2.md`, `task3.md`, `BUG_DETECTION_COMPREHENSIVE_TEST_PLAN.md`, `EXPLAIN_CODE_COMPREHENSIVE_TEST_PLAN.md`, `TASK_PLANNER_EXECUTOR_COMPREHENSIVE_TEST_PLAN.md`, `TEST_GENERATION_COMPREHENSIVE_TEST_PLAN.md`, `CODEBASE_CLEANUP_AND_OPTIMIZATION_AUDIT.md` | Historical; changelog already claims `task2.md`/`task3.md` were removed (ISS-028) | Move to `Docs/archive/` with an index; keep README, TEST_INFRA.md at root |
| DC-29b | `Docs/` — 253 Markdown files incl. per-day/per-person reports | Hard to find current truth | Create `Docs/README.md` "current architecture & runbooks" section; archive dated reports |
| DC-29c | Sprint/person-named test modules — 75 files in `backend/tests` match patterns like `*_w2_d7_*`, `*_day3*`, `om_*`, `yug_*`, `prit_*`, `challenger_*`, `*acceptance*` (e.g., `test_om_w2_d7_acceptance_regression.py`, `test_prit_w3_d7_acceptance.py`); frontend `src/test/challenger_m{1,2,3}_*`, `pr161_*` | Overlapping coverage, unclear ownership | Reorganise by feature (`tests/{auth,repositories,analysis,tasks,sandbox,ai,…}/`); dedupe overlapping cases (TST-39b) |
| DC-29d | **7 symlinked test modules** in `backend/tests`: `test_github_service.py → test_github_mocks.py`, `test_github_source_service.py → test_github_source_integration.py`, `test_github_client.py → test_github_source_integration.py`, `test_task_schemas.py → test_dev_w3_day1_task_intake.py`, `test_scanner.py → test_parser_reliability.py`, `test_day7_git_workspace_security.py → test_commit_staging.py`, `test_prit_w2_day7_scanner_acceptance.py → test_prit_day7_acceptance.py` | Pytest collects each target twice (under two module names), inflating pass counts and CI time; symlinks break on Windows checkouts without `core.symlinks` | **Remove** the 7 symlinks (keep targets); if old names are referenced in docs/CI, update them |
| DC-24c | `ASYNC_DATABASE_URL` in compose | Unused (ISS-027) | Remove |
| DC-24d | `health_router` mounted twice | ISS-030 | Keep one mount |

---

## 5. Safe removal order (validation-gated)

1. **Batch A (zero-risk):** DC-23 unused imports, DC-09, DC-15, DC-24c, DC-29d (test symlinks), DC-18 (or wire). Gate: backend + frontend test suites, `vite build`.
2. **Batch B (test-only modules):** DC-04, DC-05, DC-06, DC-07, DC-08, DC-12, DC-02 (port tests). Gate: test suites; `/health/ready`.
3. **Batch C (endpoints):** DC-21, DC-26, DC-28, DC-01 (after a release with deprecation logging at zero hits). Gate: OpenAPI diff reviewed; FE contract test (TST-30).
4. **Batch D (merges):** DC-17, DC-20, DC-30 (with migration), DC-16 (shared schema), DC-14 (evaluate). Gate: feature E2E suites (TST-E1…TST-E6), migration tests (TST-25, TST-26).
5. **Batch E (repository hygiene):** DC-22, DC-29a/b/c, DC-19, DC-25.

Never delete in the same PR as behavioural changes; one batch per PR with the validation listed.
