# 11 — File-wise Change Plan

Action legend: **MODIFY** · **CREATE** · **MERGE** · **REMOVE** · **KEEP** (unchanged, listed when a reader might expect a change).
"Sequence" = roadmap task(s) in 10. "Tests" = 09/07 IDs. Paths are relative to the repository root. Line numbers refer to the audited snapshot.

---

## A. Repository root and deployment

| File | Action | Current responsibility | Problems | Proposed changes / why | Depends on · interacts with | Sequence | Tests |
|---|---|---|---|---|---|---|---|
| `docker-compose.yml` | MODIFY | Local/prod-like stack: pg, redis, api, sync_worker | Default JWT secret L44/L66 (ISS-001); unused `ASYNC_DATABASE_URL` L41/L64 (ISS-027); no webhook_worker/runner/task_worker (ISS-014, ISS-006) | `${JWT_SECRET:?…}`; remove async URL; add `webhook_worker`, `task_worker` (after T5.2), `runner` services; `DISABLE_EMBEDDED_*=true` on api; `SANDBOX_BACKEND=runner` + `RUNNER_*` | `startup.sh`, `Dockerfile`, `backend/runner` | T1.1, T2.11, T9.1 | TST-01, TST-E* |
| `Dockerfile` | MODIFY | API/worker image | Installs only `backend/requirements.txt` (no scanners, ISS-013); reranker model fetched at runtime (DEP-09) | Install from lock; pre-download reranker model; keep scanners out (they go to runner image) | lock file, runner Dockerfile | T2.1, T7.7 | image smoke |
| `backend/runner/Dockerfile` | CREATE | — | Runner service has no image | Image with gVisor-compatible runtime, Python/Node toolchains, pinned ruff, bandit, semgrep, osv-scanner, gitleaks; no network by default for test phase | `backend/runner/main.py`, `sandbox/*` | T5.3 | TST-13 |
| `startup.sh` | MODIFY | Role switch, migrations, uvicorn | Migrations on every replica start; `FORWARDED_ALLOW_IPS` default `*`; no `task_worker` role | Add `task_worker` role; default `RUN_MIGRATIONS_ON_STARTUP=false` for non-release roles; require `FORWARDED_ALLOW_IPS` when proxy headers trusted | compose, deploy workflow | T5.2, T9.2, T9.3 | deploy smoke |
| `pyproject.toml` | MODIFY | Package metadata + deps | Conflicts with requirements (ISS-026) | Single source of runtime deps + extras (`dev`, `scanners`, `eval`, `onnx`) | lock, Dockerfile, CI | T2.1 | `pip check` |
| `requirements.lock` | CREATE | — | No lock | Hash-pinned lock compiled from pyproject | Dockerfile, CI | T2.1 | — |
| `requirements.txt`, `backend/requirements.txt`, `backend/requirements-dev.txt` | MODIFY | Install entry points | Divergence; unused `gunicorn`; `responses` | Point to lock / extras; remove `gunicorn` (DEP-02), `responses` (DEP-08) after test port | pyproject | T2.1 | CI |
| `pytest.ini` | MODIFY | Pytest config | `--cov=app` only (ISS-035) | Cover all backend packages; per-package floors in CI | workflows | T8.1 | — |
| `.env.example`, `.env.production.example`, `frontend/.env.example` | MODIFY | Env templates | Non-empty secrets (`RUNNER_AUTH_SECRET`, JWT placeholder); SameSite guidance (ISS-021) | Empty secrets; `ENABLE_DEV_LOGIN=false`; `DISABLE_EMBEDDED_WEBHOOK_WORKER`; `COOKIE_SAMESITE=lax` (rewrite topology) | config.py | T1.1, T1.2, T1.7 | TST-01 |
| `vercel.json` | MODIFY | SPA hosting, `/api` rewrite, headers | No CSP | Add `Content-Security-Policy`, `Permissions-Policy` | — | T1.7 | TST-18 |
| `frontend/vercel.json` | REMOVE | Duplicate of root config | DC-22 | Remove after confirming Vercel project root | Vercel settings | T6.5 | deploy preview |
| `.github/workflows/main_ai-powered-dev-platform-api.yml` | MODIFY | Build/test/deploy | Single web app deploy (ISS-005); coverage scope; no contract test/E2E; migrations implicit | Deploy per role; release-step migrations; OpenAPI artifact → FE type gen + contract test; coverage for all packages | all | T1.4, T3.1, T8.1–T8.3, T9.1–T9.2 | CI |
| `.github/workflows/postgres-persistence-ci.yml` | MODIFY | PG16 + pgvector migration tests | No `alembic check`; PG version ≠ compose | Up/check/down/up cycle; align PG major (DEP-17) | migrations | T2.7 | TST-25 |
| `.github/workflows/nightly-quality-evaluation.yml` | MODIFY | AI quality gate | No retrieval variant benchmark | Add `benchmark_rag.py` with graph/reranker variants | scripts | T5.7 | TST-35 |
| `README.md` | MODIFY | Product overview | Inaccurate claims (ISS-028) | Correct model names, refresh-token and graph claims; link status to CI | — | T2.11, T9.6 | — |
| `task.md`, `task2.md`, `task3.md`, root `*_COMPREHENSIVE_TEST_PLAN.md`, `CODEBASE_CLEANUP_AND_OPTIMIZATION_AUDIT.md` | MOVE (to `Docs/archive/`) | Historical plans | Clutter; stale | Archive with index | `Docs/README.md` | T6.5 | — |
| `main.py` | KEEP | ASGI entry | — | — | — | — | — |

## B. Backend core (`backend/app/core`, `backend/app/main.py`)

| File | Action | Current responsibility | Problems | Proposed changes / why | Interacts with | Sequence | Tests |
|---|---|---|---|---|---|---|---|
| `backend/app/core/config.py` | MODIFY | Settings + prod validator | Weak secret check (L339–345); `app_env` default dev (L30); missing `disable_embedded_webhook_worker`, `enable_dev_login`, refresh-token settings, per-role pool sizes; unused `ai_max_concurrent_calls` | Add fields; strengthen validator; anchored-regex validation; fail-fast sandbox availability (prod) | lifespan, auth, database | T1.1, T1.2, T1.4, T1.7, T2.8 | TST-01, TST-28 |
| `backend/app/core/auth.py` | MODIFY | JWT middleware, CSRF | `re.match` (L185); dev-login in `PUBLIC_PATHS`; test sniffing (L56–58) | `re.fullmatch`; conditional public path; inject Redis client | config, security | T1.2, T1.7, T2.10 | TST-02, TST-05 |
| `backend/app/core/security.py` | MODIFY | Token creation/decoding | No refresh tokens | Add refresh token issue/rotate/revoke helpers (hashing, family IDs) | auth.py routes, Redis | T4.9 | TST-03 |
| `backend/app/core/lifespan.py` | MODIFY | Startup wiring | Graph expander flag/module (L162–166); reranker hard-wired (L145–146); dead DI (ISS-039); webhook flag (L520); `PYTEST_CURRENT_TEST` gates (L490, L520, L533) | Correct wiring via factory; remove dead assignments; settings-driven worker/reconciliation flags; readiness keys for workers/scanners/sandbox | ai.retrieval, services | T2.2, T6.1, T1.4, T2.10, T9.4 | TST-27, TST-28 |
| `backend/app/core/database.py` | MODIFY | Engines/sessions | Two pools per process (ISS-032) | Per-role engine enablement and pool sizes | config | T2.8 | load test |
| `backend/app/core/rate_limit.py` | MODIFY | Generic rate limiting | No AI-cost quotas | Per-user AI token bucket for AI routes | config | T5.4 | TST-16 |
| `backend/app/core/telemetry.py` | MERGE/RENAME → `backend/app/core/stage_metrics.py` | Stage latency/cost metrics | Name collision with OTel module (DC-27) | Rename; update imports in `api/v1/analysis/{explain,bugs,tests,review}.py` | analysis routes | T6.5 | pytest |
| `backend/app/main.py` | MODIFY | App factory | Health router double mount (L82–83) | Single mount; document probes | router.py | T2.12 | probes |
| `backend/app/api/deps.py` | CREATE | — | `getattr(app.state, …)` scattered | Typed providers (`get_llm_gateway`, `get_rag_pipeline`, `get_task_orchestrator`, …) raising 503 | all routers | T3.4 | override-based tests |

## C. Backend API routers (`backend/app/api/v1`, `backend/app/integrations/github/routes.py`)

| File | Action | Problems | Proposed changes | Sequence | Tests |
|---|---|---|---|---|---|
| `auth.py` | MODIFY | Dev-login impersonation (L367–410), hard-coded login (L383), sync DB in async callback (L176), no refresh | Gate/limit dev-login; `POST /auth/refresh`; cookie path for refresh; make callback DB work thread-safe | T1.2, T2.3, T4.9 | TST-02, TST-03, TST-32 |
| `mcp_registry.py` | MODIFY (then rewrite) | No RBAC, in-memory state (L49–154) | Phase 1: `Depends(require_role(ADMIN))` on mutations, `require_min_role(DEVELOPER)` on GET. Phase 4: delegate to `MCPRegistryService` (DB) | T1.3, T4.1 | TST-04, TST-21 |
| `tasks.py` | MODIFY → split (T7.2) | Publication flag (L203–223, L1706–1752), `/publish` alias, repo-scoped duplicates (L2087, L2114), async `generate_task_plan` with sync session (L626), 2,121 LOC | Require persisted authorization; remove alias and repo-scoped routes; diff ranges param; enqueue task jobs (202) for execute/run-workflow; split into sub-routers | T1.5, T2.3, T3.2, T3.6, T5.2, T6.3, T7.2 | TST-20, TST-E3 |
| `chat.py` | MODIFY | No memory (L114), no streaming/persistence, fake token publish (L119–135), sync session to agent (L106–110) | Session-based history; memory injection; `/chat/stream`; remove fake token publish | T2.3, T4.2, T4.3, T5.1 | TST-23, TST-40 |
| `events.py` | MODIFY | Global channel (L195–250), sync DB at connect | Per-user channel; ownership refresh; async DB or cached ownership | T3.7 | TST-N2, TST-15 |
| `memories.py` | MODIFY | Automated routes public (L139–186) | Remove these routes (service already called internally) | T1.9 | TST-07 |
| `repositories.py` | MODIFY | Unpaginated list (L126); GET+POST search duplicate (L229/L253) | Pagination; remove GET search | T3.3, T6.3 | TST-24, TST-31 |
| `github.py` | MODIFY | 10 async handlers with sync DB; body-size check after read (L460) | Handler fixes; Content-Length precheck | T2.3, T2.13 | TST-10 |
| `health.py` | MODIFY | Readiness lacks worker/scanner/sandbox; sync DB in async handler | Extended readiness; `def` handler or threadpool | T2.3, T9.4 | — |
| `issues.py` | MODIFY | 3 async handlers with sync DB | Handler fixes | T2.3 | TST-29 |
| `analysis/{explain,bugs,tests,review}.py` | MODIFY | Async + sync DB (01 §3.1); `app.core.telemetry` import | Short-session pattern; rename import | T2.3, T6.5 | TST-29 |
| `analysis/history.py` | MODIFY | In-memory fallback (L113–158) | Remove fallback; 503 on DB error | T2.4 | TST-33 |
| `dependencies.py` | KEEP (extend) | RBAC/ownership helpers | — | Add `owned_repository`/`owned_task` `Depends` wrappers | T3.4 | TST-15 |
| `router.py` | MODIFY | Router registration | Health double mount | Align with main.py change | T2.12 | — |
| `backend/app/integrations/github/routes.py` | MODIFY | Deprecated stubs (L504–538); duplicate write routes (L256, L296, L338); diff ranges (L395); 10 async handlers with sync DB | Remove stubs after zero-hit release; remove duplicate writes; fold diff ranges into tasks; handler fixes; keep read-only source routes (tree/file/commits/pulls/diff/issues) | T2.3, T3.6, T6.3 | pytest |

## D. Backend services, integrations, workers

| File | Action | Problems | Proposed changes | Sequence | Tests |
|---|---|---|---|---|---|
| `backend/app/services/task_execution_orchestrator.py` | MODIFY → split | Publication flag (L1916); simulated push (L1775–1885); 2,458 LOC; thread/async bridges | Require persisted authorization; no simulated success in prod; split into planning/execution/verification/publication services; idempotent steps with checkpoints | T1.5, T1.6, T5.2, T7.2 | TST-E3, TST-E4 |
| `backend/app/services/explanation_orchestrator.py` (+ `bug_detection_orchestrator.py`, `test_generation_orchestrator.py`, `code_review_orchestrator.py`) | MODIFY | In-memory history store (L878–895); swallowed `record_run` errors; `_is_mock_db` (code_review L208) | Single `AnalysisRunRecorder`; remove in-memory store and test sniffing; prompt version + model in payload; optional result cache | T2.4, T2.10, T5.5, T5.6 | TST-33, TST-34 |
| `backend/app/services/git_branch.py` | MODIFY | Writes `pull_requests` table (L612–700) | Write task PR model only | T2.5 | TST-26 |
| `backend/app/services/memory_service.py` | MODIFY | No read API for AI | `get_context_memories()`; `source` marking (user/system) | T5.1 | TST-40 |
| `backend/app/services/sse_redis_streams.py` | MODIFY | Global channel publishing; `publish_chat_token` misuse | Per-user channels; `XTRIM` maxlen; streaming chat events from real stream | T3.7, T4.3, T7.4 | TST-N2 |
| `backend/app/services/webhook_handlers.py` | MODIFY (small) | Handles installation `deleted`/`suspend` (L253) — must match new FK policy | Align deletion/deactivation with ISS-034 policy | T2.6 | TST-E5 |
| `backend/app/services/mcp_registry_service.py` | CREATE | — | Persistence, probes (SSRF-safe), policy lookups | T4.1 | TST-21, TST-09 |
| `backend/app/services/chat_session_service.py` | CREATE | — | Server-side history with token budget | T4.2 | TST-E1 |
| `backend/app/services/sync_worker.py`, `webhook_worker.py`, `app/workers/*.py` | KEEP (minor) | Solid lease/heartbeat design | Reuse helpers for task worker; heartbeat exposed to readiness | T5.2, T9.4 | TST-26c |
| `backend/app/workers/task_worker.py` | CREATE | — | Durable task job consumer | T5.2 | TST-E4 |
| `backend/app/integrations/github/service.py` & `source_service.py` | MERGE (responsibility split) | Overlapping issue/branch methods; push paths | `GitHubService` = API writes/admin; `GitHubSourceService` = read-only content; remove duplicates | T6.4 | GitHub integration tests |
| `backend/app/services/task_recovery.py`, `incremental_review_service.py`, `review_deduplication_service.py`, `review_lifecycle_service.py`, `test_mutation_service.py`, `test_generation_report.py` | REMOVE (or MERGE after evaluation for review services) | Test-only (DC-05, DC-12, DC-14) | Evaluate review services against live path; delete the rest with their tests | T6.2, T6.4 | review benchmark |

## E. Backend models, repositories, migrations

| File | Action | Change | Sequence | Tests |
|---|---|---|---|---|
| `backend/app/models/pull_request.py` | REMOVE (after data migration) | Consolidated into `TaskPullRequest` (ISS-042) | T2.5 | TST-26 |
| `backend/app/models/task.py` | MODIFY | Add prepared-metadata fields to `TaskPullRequest`; FK cascades | T2.5 | TST-26 |
| `backend/app/models/{repository,github_installation,sync_job}.py` | MODIFY | `ondelete` policies (ISS-034); `repositories(user_id, created_at)` index | T2.6, T3.3 | TST-25 |
| `backend/app/models/mcp.py` | CREATE | `MCPServer`, `MCPToolPolicy` | T4.1 | TST-21 |
| `backend/app/models/chat.py` | CREATE | `ChatSession`, `ChatMessage` | T4.2 | — |
| `backend/app/models/task_job.py` | CREATE | Durable job table | T5.2 | TST-E4 |
| `backend/app/repositories/repository_repository.py` | MODIFY | Paginated `list_by_user`; silent excepts | T3.3, T2.9 | TST-31 |
| `backend/app/repositories/task/publication.py` | MODIFY | Authorization lookup by task + head SHA | T1.5 | TST-20 |
| `backend/app/repositories/chat_repository.py` | CREATE | Chat persistence | T4.2 | — |
| `backend/migrations/versions/<new>_*.py` | CREATE (several) | (1) PR consolidation; (2) FK ondelete; (3) repositories pagination index; (4) mcp tables; (5) chat tables; (6) task_jobs; (7) index cleanup after OPT-20 | T2.5, T2.6, T3.3, T4.1, T4.2, T5.2, T7.3 | TST-25 |
| `backend/migrations/versions/*` (existing 18) | KEEP | Linear chain; never edit applied revisions | — | — |

## F. Backend AI layer

| File | Action | Problems | Proposed changes | Sequence | Tests |
|---|---|---|---|---|---|
| `backend/ai/llm/client.py` | MODIFY | No concurrency cap; stream fallback duplicates output; inline span attributes | Semaphore; fallback only before first chunk; use `observability.genai` helper | T5.4, T4.3, T6.4 | TST-36 |
| `backend/ai/pipeline.py` | MODIFY | Memory unused by callers | `chat_stream()`; accept server history + memory | T4.3, T5.1 | TST-40 |
| `backend/ai/context/builder.py` (+ feature context builders) | MODIFY | — | Provenance-labelled memory section; budget | T5.1 | TST-17, TST-40 |
| `backend/ai/services/task_planner.py` | MODIFY | No memory; test sniffing | Memory input; DI | T5.1, T2.10 | TST-40 |
| `backend/ai/workflows/autonomous_task_workflow.py` | MODIFY (heavy) | Threads + in-memory registry; DBOS shim; 6 unused imports | Become a job definition executed by `task_worker`; remove thread registry and DBOS shim (unless OPT-08 option B chosen) | T5.2 | TST-E4 |
| `backend/ai/services/{llm_repair_synthesizer,edit_synthesizer,ai_quality_evaluator}.py` | MODIFY | `asyncio.run` bridges | Async-first APIs called from async worker | T5.2 | TST-36 |
| `backend/ai/retrieval/reranker_factory.py`, `reranker_onnx.py` | KEEP (wire) | Unused today | Used by lifespan | T2.2 | TST-27 |
| `backend/ai/retrieval/graph_expansion.py` | KEEP (wire) | Never constructed | Constructed with settings limits | T2.2 | TST-35 |
| `backend/ai/retrieval/pipeline.py` | REMOVE | Duplicate `RAGPipeline` facade (DC-02) | Port 4 tests to `HybridRetriever` | T6.2 | pytest |
| `backend/ai/context/service.py` | REMOVE (or adopt) | Dead DI (DC-04) | Decide; default remove | T6.2 | pytest |
| `backend/ai/embeddings/local_provider.py` | MOVE → `backend/ai/evaluation/` | Eval-only (DC-13) | Relocate | T6.5 | eval tests |
| `backend/ai/intelligence/impact.py` | KEEP+WIRE or REMOVE | Test-only (DC-10) | Product decision | T6.4 | — |
| `backend/ai/prompts/__init__.py` | MODIFY | No versioning | Template hashing, per-feature model routing config | T5.5 | TST-34 |
| `backend/ai/agent/*`, `backend/agent/tools/*` | MODIFY (shared schema) | Two tool frameworks (DC-16); MCP policy not enforced | Shared `ToolSpec`; router reads DB policies | T6.4, T4.1 | tool suites |
| `backend/agent/tools/adapters/plugin.py` | REMOVE | Unreferenced (DC-09) | Delete + re-export | T6.1 | pytest |
| `backend/ai/security/*` | KEEP | Provenance/taint tracking | — | — | TST-17 |

## G. Sandbox, scanner, review, runner, scripts, POC

| File | Action | Problems / change | Sequence | Tests |
|---|---|---|---|---|
| `backend/sandbox/workspace_manager.py` | MODIFY | Token in argv (L1306–1316); 6 silent excepts; 2,138 LOC → split git ops vs workspace lifecycle | T1.8, T2.9, T7.2 | TST-06 |
| `backend/sandbox/command_runner.py`, `path_guard.py` | KEEP (+tests) | Strong controls; add fuzz/symlink tests | T8.x | TST-11, TST-12 |
| `backend/sandbox/container_backend.py` | MODIFY | Fail-fast availability check; silent excepts | T5.3, T2.9 | — |
| `backend/sandbox/two_phase_pipeline.py` | REMOVE | Test-only (DC-06) | T6.2 | pytest |
| `backend/review/static_reviewer.py` | MODIFY | Runs in API process; tools absent in prod | Execute through runner; report availability | T5.3 | TST-E2 |
| `backend/scanner/{semgrep_runner,osv_runner,gitleaks_runner}.py` | MODIFY | Silent degradation | Availability reporting; run in runner | T5.3 | — |
| `backend/scanner/scip_runner.py`, `task_test_planner.py`, `workspace_preflight.py` | REMOVE | Test-only (DC-07, DC-08) | T6.2 | pytest |
| `backend/runner/main.py` | MODIFY | Reads env directly (duplicates Settings); 3 unused imports | Use Settings; endpoints for scanner execution | T5.3 | TST-13 |
| `backend/scripts/seed_database.py` | MODIFY | Unguarded `drop_all` (L46–47) | Environment guard; Alembic-based | T1.10 | TST-08 |
| `backend/scripts/benchmark_rag.py` | MODIFY | Variants | Graph/reranker matrix | T5.7 | TST-35 |
| `backend/poc/dbos/` | REMOVE (or promote) | DC-24a | T6.5 | pytest |

## H. Frontend

| File | Action | Problems | Proposed changes | Sequence | Tests |
|---|---|---|---|---|---|
| `frontend/package.json` | MODIFY | Custom msw shim; autoprefixer | Add `msw`, `openapi-typescript`, `@playwright/test` (dev); remove `autoprefixer` after CSS diff | T3.1, T6.5, T8.3 | CI |
| `frontend/vite.config.ts` | MODIFY | Aliases `msw` → shim | Remove aliases after DC-19 | T6.5 | vitest |
| `frontend/postcss.config.js` | MODIFY | autoprefixer | Remove plugin | T6.5 | CSS diff |
| `frontend/src/types/api.gen.ts` | CREATE | — | Generated types | T3.1 | `tsc -b` |
| `frontend/src/types/{api,analysis,task,memory}.ts` | MODIFY → thin aliases | Hand-written drift | Re-export generated types; keep UI-only types | T3.1 | TST-30 |
| `frontend/src/services/api.ts` | MODIFY | Substring timeouts; no refresh | Explicit timeouts; 401 → refresh once → retry | T3.5, T4.9 | TST-19, TST-32 |
| `frontend/src/services/tasks.ts` | MODIFY | Publish fallback (L598–620); two diff sources (L350/L358); missing calls for authorize/traceability/invariants/checkpoints | Remove fallback; authorize-then-create; single diff; add new functions | T1.5, T3.2, T3.6, T4.7 | TST-20 |
| `frontend/src/services/repositories.ts` | MODIFY | Pagination shim (L39–57) | Server pagination; `searchRepository`, `listSymbols` | T3.3, T4.5 | TST-24 |
| `frontend/src/services/chat.ts`, `hooks/useRepositoryChat.ts`, `pages/RepositoryChat.tsx` | MODIFY | No sessions/streaming | Sessions sidebar; streaming via fetch-SSE; abort | T4.2, T4.3 | TST-23 |
| `frontend/src/services/auth.ts`, `pages/Login.tsx` | MODIFY | Hard-coded dev login (L30) | Use `VITE_DEV_LOGIN` only when enabled | T1.2 | — |
| `frontend/src/services/repositoryDiscovery.ts`, `pages/Repositories.tsx` | MODIFY | Inline API call (L423) | Move call into service | T3.5 | — |
| `frontend/src/services/mcp.ts`, `hooks/useMcpServers.ts` | CREATE | — | MCP API client and hooks | T4.1 | TST-21 |
| `frontend/src/pages/ToolsIntegrationsAdminPage.tsx` | MODIFY (or REMOVE with route) | Hard-coded state (L25, L89) | Bind to API; role-aware controls | T4.1 | TST-21 |
| `frontend/src/services/github.ts`; `components/explorer/{RepositoryAutomationSettings,WebhookEventsTable}.tsx`; route `/app/repositories/:id/settings` in `App.tsx`; `components/studios/StudioSubNav.tsx` | CREATE / MODIFY | Missing UI (FEAT-15) | New settings page | T4.4 | E2E |
| `frontend/src/components/explorer/{CodeSearchPanel,SymbolList}.tsx`; `pages/RepositoryDetail.tsx` | CREATE / MODIFY | Missing UI (FEAT-16) | Search + symbols tab | T4.5 | — |
| `frontend/src/components/explorer/PullRequestPicker.tsx`; `pages/RepositoryReviewStudio.tsx` | CREATE / MODIFY | FEAT-17 subset | PR picker | T4.6 | — |
| `frontend/src/components/tasks/{PublicationPanel,RecoveryPanel,VerificationPanel}.tsx`; `TraceabilityPanel.tsx` (CREATE) | MODIFY | Authorization flow; new data | As in FP-BE-04 | T1.5, T4.7 | TST-20 |
| `frontend/src/pages/TaskDetail.tsx`, `pages/RepositoryTaskStudio.tsx`, `components/taskStudio/TaskPhasePanels.tsx` | MERGE → `components/tasks/TaskWorkspace.tsx` | Duplicate task UIs (DC-20) | One component reused by both routes | T6.4 | vitest task suites |
| `frontend/src/components/explorer/ProjectMemoryPanel.tsx`, `services/memory.ts` | MODIFY | No semantic search | Search box | T4.8 | — |
| `frontend/src/realtime/{index,events}.ts`, `hooks/useTasks.ts`, `hooks/useRealtimeRepositories.ts` | MODIFY | Only repo events consumed | Task/tool event invalidation; reduce polling | T3.7 | TST-N2 |
| `frontend/src/components/shared/ErrorBoundary.tsx`, `layouts/{AppLayout,RepositoryStudioLayout}.tsx` | MODIFY | Root-only boundary | Route-level boundaries; reporting hook | T7.6 | TST-N5 |
| `frontend/src/lib/classifyAnalysisError.ts` (+ its test) | REMOVE (or wire) | DC-18 | T6.1 | build |
| `frontend/src/lib/msw/*`, `src/lib/mswBootstrap.ts`, `src/mocks/handlers/*` | MODIFY/REMOVE | DC-19 | Real msw + generated types; small per-test fixtures | T6.5 | vitest |
| `frontend/src/test/*` (challenger_*, pr161_*) | MODIFY (reorganise) | DC-29c | Group by feature | T8.6 | same coverage |
| `backend/tests/{test_github_service,test_github_source_service,test_github_client,test_task_schemas,test_scanner,test_day7_git_workspace_security,test_prit_w2_day7_scanner_acceptance}.py` | REMOVE (symlinks) | DC-29d — duplicate collection of 5 target modules | Delete symlinks only | T6.1 | pytest count drops by the duplicated tests, no target lost |
| Large result views (`CodeReviewView.tsx`, `TestGenerationView.tsx`, `ExplanationResultView.tsx`, `BugScannerView.tsx`) | MODIFY | Size/perf | Lazy sub-panels, memoized rows | T7.5 | Profiler |

## I. Tests (new)

| File | Action | Purpose | Sequence |
|---|---|---|---|
| `backend/tests/security/test_settings_validation.py` | CREATE | TST-01, TST-28 | T1.1 |
| `backend/tests/security/test_dev_login.py` | CREATE | TST-02 | T1.2 |
| `backend/tests/api/test_mcp_rbac.py` | CREATE | TST-04 | T1.3 |
| `backend/tests/tasks/test_publication_authorization.py` | CREATE | TST-20 backend part | T1.5 |
| `backend/tests/static/test_no_sync_db_in_async_routes.py` | CREATE | TST-29 (AST guard) | T2.3 |
| `backend/tests/contract/test_frontend_contract.py` | CREATE | TST-30 | T3.1 |
| `backend/tests/security/test_tenant_isolation_sweep.py` | CREATE | TST-15 | T8.4 |
| `tests/e2e/playwright/*` + `docker-compose.test.yml` | CREATE | TST-E0…E6 | T8.3 |
| `loadtests/*.js` (k6) or `loadtests/locustfile.py` | CREATE | TST-N1…N3 | T8.5 |

## J. Explicitly KEEP (no change required by this audit)

`backend/app/services/sync_worker.py` (lease/heartbeat design), `backend/indexer/*` (content-hash incremental indexing), `backend/ai/retrieval/{hybrid,vector,lexical,fusion,cache*,code_tokenizer}.py`, `backend/ai/schemas/*` (grounding/validation), `backend/sandbox/{command_runner,path_guard,diff_verifier}.py` (beyond tests and logging), `backend/app/core/{errors,logging,security_headers,secret_redaction,input_security}.py`, `backend/app/repositories/analysis/*` mixins, all existing Alembic revisions, `frontend/src/App.tsx` routing structure (only additions), `frontend/src/realtime/index.ts` reconnect logic, `.gitleaks.toml`, `.pre-commit-config.yaml`.
