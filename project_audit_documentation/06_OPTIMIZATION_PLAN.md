# 06 — Optimization Plan

Every item: **Existing approach → Limitation → Recommended approach → Why better → Files → Steps → Risks → Benchmark method → Expected measurable outcome.**
No numbers below are measured results; "Expected outcome" states the target the benchmark must demonstrate. Prefer the existing stack (FastAPI, SQLAlchemy, Postgres/pgvector, Redis, React/TanStack Query); new technology is only proposed where the existing one cannot do the job, with alternatives compared.

ID index: Frontend OPT-01…04, OPT-12 · Backend OPT-05…11 · AI OPT-13…19 · Database OPT-20…23 · Architecture/Observability OPT-24.

---

## 1. Frontend

### OPT-01 — Split the heaviest components and measure the bundle
- **Existing:** Pages are lazy-loaded (`App.tsx`); manual vendor chunks (`vite.config.ts`). Several components are very large: `CodeReviewView.tsx` 1,361 LOC, `TestGenerationView.tsx` 1,240, `ExplanationResultView.tsx` 873, `BugScannerView.tsx` 869, `RepositoryTaskStudio.tsx` 1,552, `TaskPhasePanels.tsx` 926, `CreateTaskForm.tsx` 934.
- **Limitation:** Large components re-render as a whole on any state change and are hard to test; studio pages download all result-view code even before a result exists.
- **Recommended:** Split result views into lazily imported sub-panels (findings list, diff viewer, code block renderer) and memoize list rows (`React.memo` + stable keys); keep `utils/virtualizationAndSyntax.ts` for long lists.
- **Why better:** Smaller initial chunk for each studio; fewer re-renders when filters change.
- **Files:** components above; `pages/Repository*Studio.tsx`.
- **Steps:** add `rollup-plugin-visualizer` (dev only) → record baseline → split → re-measure.
- **Risks:** Prop drilling increases; keep TanStack Query as the data source.
- **Benchmark:** `vite build` chunk sizes (gzip) before/after; React Profiler commit time when toggling a severity filter on a 200-finding review.
- **Expected outcome:** studio route chunk reduced (target ≥ 25 %); filter toggle commit time reduced (target ≥ 40 %).

### OPT-02 — Explicit AI timeouts instead of URL substring matching
- **Existing:** `services/api.ts` L41–56 sets 180 s when the URL *contains* `/explain`, `/review`, `/tests`, `/plan`, `/chat`, …
- **Limitation:** Also matches cheap GETs (`/tasks/{id}/tests`, `/review/settings`, `/tasks/{id}/plan`), so failures on them take 3 minutes to surface.
- **Recommended:** Default 30 s; AI service functions pass `{ timeout: AI_ANALYSIS_TIMEOUT_MS }` explicitly.
- **Files:** `frontend/src/services/{api,analysis,tasks,chat}.ts`.
- **Risks:** Missing an AI call → 30 s timeout; covered by a unit test enumerating AI functions.
- **Benchmark/Outcome:** Unit test asserting timeouts per function; no GET has a 180 s timeout.

### OPT-03 — Generate API types from OpenAPI
- **Existing:** 2,171 LOC of hand-written types (`src/types/*`); mocks encode shapes (ISS-017).
- **Recommended:** `openapi-typescript` (dev dependency) generating `src/types/api.gen.ts` from the backend `/openapi.json` (exported in CI by `python -c "from app.main import app; import json; print(json.dumps(app.openapi()))"`); hand-written types become aliases of generated ones.
- **Why better:** Contract drift becomes a compile error.
- **Steps:** add CI step (backend job uploads `openapi.json` artifact; frontend job generates and runs `tsc -b`). Migrate types file by file.
- **Risks:** Some backend handlers return `dict` without `response_model` (03 §2 marks them "— (dict/JSONResponse)"); add response models to those first.
- **Benchmark/Outcome:** number of hand-written response interfaces → 0; CI fails on an intentional schema change.

### OPT-04 — Data-access hygiene
- **Existing:** One inline API call in a page (`pages/Repositories.tsx` L423); polling (`refetchInterval`) on Dashboard, RepositoryDetail, tasks.
- **Recommended:** Move the call to `services/repositoryDiscovery.ts`; centralise query keys (`queryKeys.ts`); replace polling with SSE invalidation (OPT-11) keeping a slow fallback poll (60 s).
- **Benchmark/Outcome:** Requests per minute from an idle Dashboard tab (Network panel or backend access log) reduced to ≈ 1/min when SSE is connected.

### OPT-12 — Error boundaries, accessibility and error reporting
- **Existing:** Single root `ErrorBoundary` (`components/shared/ErrorBoundary.tsx`, TODO for reporting at L30).
- **Recommended:** Route-level boundaries inside `AppLayout`/`RepositoryStudioLayout` so one failing studio does not blank the app; optional Sentry (or OTel web) behind an env flag; run `@axe-core/react` in dev and add jest-axe checks for main pages.
- **Benchmark/Outcome:** Thrown error in a studio shows an inline fallback with retry; axe reports 0 critical violations on Login, Dashboard, Repositories, a studio, TaskDetail.

---

## 2. Backend

### OPT-05 — One coherent data-access model (fixes ISS-009)
- **Existing:** Sync sessions everywhere; 42 `async def` handlers use them; async engine used only by retrieval.
- **Limitation:** Event-loop blocking; sessions held across LLM awaits; two pools per process (ISS-032).
- **Options compared:**

| Option | Effort | Perf | Risk | Notes |
|---|---|---|---|---|
| A. Convert non-awaiting handlers to `def`; wrap DB blocks in `run_in_threadpool` in awaiting handlers | **S–M** | Good | Low | Immediate fix; threadpool (default 40) becomes the concurrency limit |
| B. Migrate hot paths to `AsyncSession` (chat, analysis, history, search, events) | M–L | Best | Medium | Repositories need async variants |
| C. Full async migration | XL | Best | High | Not justified now |

- **Recommended:** A now (Phase 2), B for the hot paths (Phase 7). Pattern for AI handlers: *read inputs in a short session → close → await LLM → new short session to persist*.
- **Files:** handlers in 01 §3.1; `app/core/database.py`; repositories used by those handlers.
- **Risks:** Lazy-loaded relationships after session close → use `selectinload` or DTOs.
- **Benchmark:** Locust/k6: 50 VUs on `POST /repositories/{id}/explain` (LLM mocked with 2 s latency via respx) + 20 VUs on `GET /api/v1/health/live`; record p50/p95 of both and DB pool checked-out connections (`engine.pool.status()`).
- **Expected:** `/health/live` p95 stays < 50 ms under AI load; checked-out connections during LLM wait ≈ 0.

### OPT-06 — Typed DI and decomposition of god objects
- **Existing:** `getattr(request.app.state, "x", None)` + ad-hoc construction; `tasks.py` 2,121 LOC; `task_execution_orchestrator.py` 2,458; `workspace_manager.py` 2,138; `git_branch.py` 1,429.
- **Recommended:** `app/api/deps.py` with `def get_llm_gateway(request) -> LLMGateway` etc. (raise 503 when absent) used via `Depends`; split `tasks.py` into `tasks/{crud,planning,execution,verification,publication,approvals}.py`; split the orchestrator along the same lines (`TaskPlanningService`, `TaskExecutionService`, `TaskVerificationService`, `TaskPublicationService`) sharing `TaskRepository`.
- **Why better:** Smaller units, test overrides via `app.dependency_overrides` (removes ISS-041 sniffing), clearer ownership.
- **Risks:** Large diff — do it file by file behind unchanged routes; OpenAPI must be identical before/after (diff check).
- **Benchmark/Outcome:** OpenAPI diff empty; largest Python file < 800 LOC; cyclomatic complexity (radon) of top 10 functions reduced.

### OPT-07 — Pagination and payload bounds
- **Existing:** `GET /repositories` unpaginated (ISS-024); memory list paginated; tasks paginated.
- **Recommended:** Add `page/page_size` with max 100 to every list endpoint lacking it (`/repositories`, `/repositories/{id}/symbols` – verify current params, `/github/events` – verify); return `total`.
- **Benchmark/Outcome:** Response size for a user with 200 repos ≤ page_size items; p95 latency flat as repos grow (seeded test).

### OPT-08 — Durable background execution for tasks (fixes ISS-010, ISS-011)
- **Existing:** `threading.Thread` + in-memory dicts; DBOS decorator without DBOS runtime.
- **Alternatives:**

| Option | New tech? | Durability | Ops cost | Fit |
|---|---|---|---|---|
| A. Reuse the sync-worker pattern: `task_jobs` table + Redis queue + lease/heartbeat + checkpoints (`task_checkpoints` exists) | No | Good (Postgres) | Low (one more worker role) | **Recommended** — mirrors proven code in `services/sync_worker.py` |
| B. DBOS (already in requirements, POC in `poc/dbos`) | Library only (uses Postgres) | Very good (exactly-once steps) | Medium (learning, system DB schema) | Good if many multi-step workflows are planned |
| C. Celery/RQ/Arq | Yes | Good | Medium | Adds a framework for one use case |
| D. Temporal | Yes (cluster) | Excellent | High | Over-engineering here |

- **Recommended:** A. Steps: migration `task_jobs(id, task_id FK, kind, payload jsonb, status, attempts, available_at, lease_expires_at, worker_id, created_at)`; `app/workers/task_worker.py` (copy lease/heartbeat helpers); API enqueues and returns 202; `/workflow-status` reads the table; make orchestrator steps idempotent using `task_checkpoints`; cap concurrency with `sandbox_max_concurrent_tasks`.
- **Risks:** Idempotency of git operations — use checkpoint guards before each step.
- **Benchmark:** chaos test — kill the worker mid-repair; measure recovery time and verify no duplicate commits.
- **Expected:** 100 % of interrupted workflows end in a resumed or explicitly failed state; status consistent across replicas.

### OPT-09 — Error handling and logging
- **Existing:** 115 silent broad handlers (ISS-040); structured JSON logging with request IDs (good).
- **Recommended:** Ruff rules `BLE001`, `S110`, `TRY`, `SIM105` with a baseline file; replace `pass` with `logger.warning(..., exc_info=True)` + Prometheus/OTel counters for expected-degradation paths (scanner unavailable, cache miss errors, persistence failure).
- **Benchmark/Outcome:** Silent handler count ≤ 10 (each annotated); dashboards show degradation counters.

### OPT-10 — Remove test-aware production branches (ISS-041)
- **Recommended:** Settings flags (`run_background_workers`, `run_startup_reconciliation`) set by the test fixture; DI overrides for Redis/DB; delete `_is_mock_db` / `PYTEST_CURRENT_TEST` checks.
- **Outcome:** grep returns 0 hits; tests still pass.

### OPT-11 — Per-user SSE channels and SSE-driven UI updates (fixes ISS-020)
- **Existing:** Global `platform_events` pub/sub, Python-side filtering, 0.5 s sleep loop; UI polls tasks.
- **Recommended:** Publish to `events:user:{uid}` (and keep Redis Streams `XADD` per user for replay); each SSE connection subscribes only to its channel with `await pubsub.get_message(timeout=15)` + heartbeat comments; frontend subscribes to task/tool events and invalidates TanStack Query keys.
- **Benchmark:** 500 idle SSE connections + 50 events/s for one user: measure API CPU and per-connection messages processed.
- **Expected:** Messages processed per connection = only its own; CPU roughly constant w.r.t. other users' event rate.

---

## 3. AI

### OPT-13 — Activate and tune symbol-graph expansion (ISS-007)
- **Existing:** Implemented (`ai/retrieval/graph_expansion.py`) but never constructed.
- **Steps:** fix lifespan wiring; pass `retrieval_graph_max_seeds/hops/neighbors/candidates`; run `scripts/benchmark_rag.py` (dataset in `ai/retrieval/evaluation.py`) with flag on/off.
- **Benchmark:** recall@5/@10 and MRR per query category (definition, references, impact), plus p95 retrieval latency.
- **Expected:** improved recall on graph-category queries with ≤ 100 ms added p95 (targets to confirm with the benchmark).

### OPT-14 — Reranker backend selection and ONNX (ISS-008)
- **Existing:** PyTorch cross-encoder always (when Gemini keys exist).
- **Recommended:** `create_reranker(settings)`; evaluate ONNX/quantized on CPU App Service; lazy model load at first use with a warm-up on startup in background.
- **Benchmark:** rerank 50 candidates × 100 queries: p50/p95 latency, memory RSS, NDCG@10 delta vs PyTorch.
- **Expected:** ONNX path chosen only if NDCG@10 delta ≥ −0.01 and latency improves.

### OPT-15 — LLM concurrency, quotas and cost control (ISS-025)
- **Recommended:** Gateway semaphore (`ai_max_concurrent_calls`); per-user token bucket in Redis for AI endpoints (e.g., N analyses/min, configurable); record tokens per user per day (from existing stage metrics) and enforce a daily budget flag.
- **Benchmark:** burst 100 concurrent explain requests with mocked provider; assert ≤ N in-flight provider calls; 429 with `Retry-After` beyond quota.

### OPT-16 — Feed project memory into prompts safely (ISS-036, ISS-023)
- **Recommended:** `ProjectMemoryService.get_context_memories()` (pinned rules + semantic top-k, token-budgeted), injected via `ContextBuilder` in a delimited "Project rules (user-authored, may be wrong)" section; record used memory IDs in `analysis_runs.result_payload` and chat responses.
- **Benchmark:** small eval set (20 prompts) where a pinned rule changes the correct answer; measure adherence rate with memory on/off.

### OPT-17 — Streaming chat, server-side history, context budgeting (ISS-015, ISS-016)
- **Recommended:** See FP-FE-02/03. History truncated server-side by token budget (`ai/context/token_budget.py`), summarizing older turns with `summary_system.txt` (already present) when over budget.
- **Benchmark:** time-to-first-token p50/p95; prompt tokens per turn for a 20-turn conversation (should plateau).

### OPT-18 — Prompt versioning and model routing
- **Existing:** Prompt text files, single `active_chat_model` for all features.
- **Recommended:** Hash each template at startup (`sha256`) and store `prompt_version` + `model` in every `analysis_runs` row and chat message; route cheap tasks (summaries, classification, grounding checks) to the lite model and complex ones (planning, repair) to a stronger model via settings per feature (`AI_MODEL_<FEATURE>`).
- **Why:** Reproducibility of results and cost/latency control.
- **Benchmark:** existing quality suite (`scripts/benchmark_quality_suite.py`, nightly workflow) per feature/model pair; cost per run from stage metrics.

### OPT-19 — Deterministic-analysis result cache
- **Existing:** Retrieval and embedding caches exist; analysis results are recomputed for identical inputs.
- **Recommended:** Cache key `(feature, repository_id, target path, content_hash, prompt_version, model, options)` → reuse a recent successful `analysis_runs` row (return with `cached=true`) unless the user forces refresh.
- **Benchmark:** re-run explain on an unchanged file: latency and LLM tokens.
- **Expected:** second call served without an LLM request.

---

## 4. Database

### OPT-20 — Index review with real query plans
- **Existing:** Rich indexing (112 declarations). `analysis_runs` has single-column indexes on several columns **and** composites with the same leading `repository_id` (`ix_analysis_runs_repo_created`, `…_repo_feature_status`, `…_repo_revision`, `…_repo_target_path`), so some single-column indexes are likely redundant (write amplification). `repositories` lacks `(user_id, created_at)` for paginated listing.
- **Steps:** on a staging copy, enable `pg_stat_statements`; collect top queries; `EXPLAIN (ANALYZE, BUFFERS)`; check `pg_stat_user_indexes.idx_scan = 0` after a representative period; drop unused/redundant indexes via migration; add `(user_id, created_at)` on `repositories`.
- **Risks:** Dropping an index used by a rare admin query — keep a 2-week observation window.
- **Expected:** No sequential scans on list endpoints for tenants with > 1,000 rows; index count on `analysis_runs` reduced without plan regressions.

### OPT-21 — Data retention jobs
- **Existing:** `purge_expired_runs` exists but is never called; unbounded growth of `analysis_runs.result_payload`, `task_events`, `tool_invocations`, `github_webhook_events`, Redis Streams.
- **Recommended:** A daily maintenance job in the worker role (no new scheduler: a loop with `next_run_at` stored in Redis/DB) calling purge functions with configurable retention per table; `XTRIM` on SSE streams (MAXLEN ~).
- **Benchmark/Outcome:** Table sizes stable over a 30-day soak; purge runtime < 1 min in batches of 1,000 rows.

### OPT-22 — Connection pool budget per role (ISS-032)
- **Recommended:** `DB_POOL_SIZE`/`DB_MAX_OVERFLOW` per deployment role; disable the unused engine per role (e.g., workers need only sync or only async); for Supabase use the transaction pooler (6543) for API roles (already supported: `prepare_threshold=None`).
- **Outcome:** Documented budget table; `pg_stat_activity` peak ≤ 80 % of `max_connections` under load test.

### OPT-23 — Schema and migration consistency
- **Recommended:** CI step: fresh DB → `alembic upgrade head` → `alembic check` (autogenerate diff must be empty) → `alembic downgrade base` → `upgrade head`; consolidate PR tables (ISS-042); add `ON DELETE` policies (ISS-034); remove `drop_all` seed path (ISS-029).
- **Outcome:** CI fails on any model/migration drift.

---

## 5. Architecture and observability

### OPT-24 — Operational visibility
- **Existing:** OTel and Langfuse off by default; readiness covers DB/Redis/service construction, not workers or scanners.
- **Recommended:** Enable OTel traces in production with 5–10 % sampling (exporter to the team's chosen backend — Azure Monitor supports OTLP); add readiness fields: `sync_worker_heartbeat_age_s`, `webhook_backlog`, `scanner_availability`, `sandbox_backend_ok`; RED metrics per route and per AI feature (latency, errors, tokens, cost).
- **Outcome:** On-call can answer "are syncs being processed?" from one endpoint; alerts on backlog growth.

---

## 6. Performance improvement strategy (order)
1. Correctness-first quick wins with measurable effect: OPT-05A, OPT-02, OPT-13, OPT-14 wiring, OPT-15 semaphore.
2. Scalability: OPT-11, OPT-07, OPT-22, OPT-20.
3. Durability: OPT-08, OPT-21.
4. Product quality: OPT-16, OPT-17, OPT-18, OPT-19.
5. Maintainability: OPT-06, OPT-09, OPT-10, OPT-03, OPT-01.

Every optimization PR must include the benchmark command, baseline numbers and after numbers in its description.
