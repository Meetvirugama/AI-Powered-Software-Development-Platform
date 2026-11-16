# 09 — Testing and Validation Plan

## 0. Current testing infrastructure (as found)

| Area | Assets | Observations |
|---|---|---|
| Backend unit/integration | 227 modules in `backend/tests` plus **7 symlinks to other test modules** that make pytest run those tests twice (DC-29d) (~2,792 test functions, ~93k LOC); fixtures for AST samples, frameworks, defects, prompt injection, provenance; cassettes dir; `pytest.ini` with `asyncio_mode=auto`, markers `unit/integration/slow` | 75 modules named by sprint/person/day (DC-29c); some suites use SQLite with PG type shims (`tests/e2e/test_tier1_features.py` compiles `JSONB`/`UUID` for SQLite) so PG-specific behaviour (pgvector, FTS, constraints) is covered only by the PG persistence workflow |
| "E2E" | `tests/e2e/test_tier{1..4}_*.py` (FastAPI `TestClient`) | API-level, not browser E2E |
| Frontend | 32 Vitest files (~352 cases) with Testing Library + custom MSW shim | Mocks drift from backend (ISS-017); no browser E2E (Playwright/Cypress absent) |
| AI quality | `ai/evaluation/quality_gate.py`, mini-SWE-bench (25 tasks), `scripts/benchmark_quality_suite.py`, `scripts/benchmark_rag.py`, nightly workflow | Good foundation; graph expansion and reranker settings not exercised through the app wiring (ISS-007/008) |
| CI | Lint (Ruff, Bandit), backend tests (+ `tests/e2e`, coverage ≥ 71 % of `app` only), frontend lint/tsc/test/build, migration validation, security scan, deploy | Coverage scope (ISS-035); no `alembic check`; no contract test; no load test |
| **Executed in this audit** | **None** | Dependencies unavailable; see 00 §1.2 |

Guiding rules: (1) every ISS fix ships with a regression test that fails before the fix; (2) tests are organised by feature, not sprint; (3) external services are mocked at the HTTP boundary (`respx`) and recorded cassettes are used for AI quality runs; (4) PostgreSQL-specific behaviour is tested against real PostgreSQL + pgvector (service container).

---

## 1. Frontend

| ID | Type | Scenario | Expected outcome | Acceptance |
|---|---|---|---|---|
| TST-19 | Unit | `services/api.ts` timeout policy (OPT-02): enumerate AI service functions vs non-AI GETs | AI calls 180 s, others 30 s | Test fails if a GET gets 180 s |
| TST-20 | Component | `PublicationPanel`: confirm dialog calls `authorize-publication` then `create-pr`; no 404 fallback | Two calls in order; one PR request | Mock server records exact sequence |
| TST-21 | Component | `ToolsIntegrationsAdminPage` with API (after ISS-033): loads servers; non-admin sees read-only | Rendered from API; controls hidden | — |
| TST-22 | Integration (Vitest + msw real) | Task lifecycle panels driven by generated OpenAPI types | Type-checked fixtures compile; panels render each status | `tsc -b` passes |
| TST-23 | Component | Chat streaming hook: tokens appended; abort cancels; error event shows retry | As stated | — |
| TST-24 | Component | Repositories pagination uses server params (after ISS-024) | Correct `page/page_size` query; shim removed | — |
| TST-E0 | Workflow (Playwright, new) | Login (dev flag in test env) → connect fixture repo (mock GitHub) → wait for `repository.updated` → open explorer → run explain | Explanation visible with citation links | Runs in CI against docker-compose test stack |
| TST-N5 | Accessibility | axe on Login, Dashboard, Repositories, one studio, TaskDetail | 0 critical violations | — |

## 2. Backend

| ID | Type | Scenario | Expected | Acceptance |
|---|---|---|---|---|
| TST-01…TST-16 | Security/API | Defined in 07 §5 | — | — |
| TST-27 | Unit | `init_rag_pipeline` wiring: graph expander present when flag true; reranker class follows `RERANKER_BACKEND` (ISS-007/008) | As stated | — |
| TST-28 | Unit | Settings: `disable_embedded_webhook_worker` honoured; production defaults; unknown `getattr` settings forbidden (test that every `getattr(settings, "x", …)` name exists in `Settings.model_fields`) | Static test over source | Fails on typos like ISS-007 |
| TST-29 | API | Async handler audit: AST test asserting no `async def` route receives a sync `Session` (encodes ISS-009 fix) | 0 offenders | — |
| TST-30 | Contract | Load `app.openapi()`; for every FE call extracted from `frontend/src/services/*.ts` (script in CI) assert path+method exist and response schema fields used by FE exist | 0 mismatches | Blocks merge |
| TST-31 | API | Pagination contracts for list endpoints (`total`, bounds, `page_size ≤ 100`) | — | — |
| TST-32 | Auth | Token refresh/rotation/reuse detection (ISS-012); logout blocklist; Redis outage → 503 not 500 | — | — |
| TST-33 | API | Analysis history: DB error → 503 (no in-memory fallback, ISS-038) | — | — |

## 3. AI

| ID | Type | Scenario | Expected | Acceptance |
|---|---|---|---|---|
| TST-34 | Prompt | Golden-prompt snapshot per feature: render prompts for fixed inputs; hash recorded with `prompt_version` (OPT-18) | Changes require snapshot update review | — |
| TST-35 | Retrieval | `scripts/benchmark_rag.py` dataset: recall@5/@10, MRR, per category, with graph on/off and reranker variants (OPT-13/14) | Recall not below baseline; latency budget | Stored as CI artifact; nightly gate |
| TST-36 | Model integration | Provider adapters with `respx`: success, 429 → retry, 5xx → fallback, auth error → no fallback, timeout; streaming: fallback only before first chunk (ISS-015) | As stated | — |
| TST-37 | Agent tools | Chat agent: budgets (rounds, calls, bytes, timeouts), duplicate-call stop, tool errors surfaced as evidence-less answer | As stated | — |
| TST-38 | Output validation / hallucination | GroundingValidator rejects citations to non-retrieved files/lines; answers without sources flagged; quality gate thresholds fail the build when below (existing `quality_gate.py`) | As stated | Nightly workflow fails on regression |
| TST-17 | Prompt injection | 07 §5 | — | — |
| TST-39 | Failure/fallback | LLM unavailable at startup → AI routes 503 retryable; memory service unavailable → chat still answers without memory and logs metric | As stated | — |
| TST-40 | Memory usage | Pinned rule appears in prompt (captured by mocked LLM) for chat/planner/review (ISS-036) | Present, delimited, with provenance label | — |

## 4. Database

| ID | Type | Scenario | Expected |
|---|---|---|---|
| TST-25 | Migration | Fresh PG+pgvector → `alembic upgrade head` → `alembic check` (empty diff) → `downgrade base` → `upgrade head` | All succeed; no drift |
| TST-26 | Migration | PR-table consolidation (ISS-042) with fixture rows in both tables | Rows merged, FK enforced, no data loss |
| TST-26b | Constraint | Unique `(repository_id, path)` on files; cascades on repository delete (existing `tests/test_repository_deletion_cascades.py` — run on PG, not SQLite) | Violations raise; children deleted |
| TST-26c | Transaction | Sync job lease: two workers race for the same job → one wins; lease expiry → re-claim | Exactly-once processing |
| TST-26d | Consistency | Retention purge (OPT-21) deletes runs older than N days with findings; leaves recent | Counts as expected |

## 5. End-to-end

| ID | Flow | Stack | Pass criteria |
|---|---|---|---|
| TST-E1 | Login → connect → index → chat with citations | compose test profile (api, sync_worker, webhook_worker, runner, pg, redis) + GitHub/LLM mocks | Answer cites an indexed file; SSE update received |
| TST-E2 | Explain/Bugs/Tests/Review on fixture repo; review publish to mocked GitHub | same | Runs persisted; history lists them; publish call made once |
| TST-E3 | Task: import issue → plan → approve → execute → tests → repair → verify → authorize → Draft PR (mock GitHub) | same | Final status `DRAFT_PR_CREATED`; audit events complete; no PR without authorization |
| TST-E4 | Worker crash mid-task (kill container) | same | Task resumes or ends `RECOVERY_REQUIRED` deterministically (OPT-08) |
| TST-E5 | Webhook push → auto-sync; PR opened → auto-review (automation flags on) | same | Sync job and review run created; dedupe on redelivery |
| TST-E6 | Multi-tenant isolation (two users) across UI and API | same | No cross-user data in responses or SSE |

## 6. Regression and non-functional

| ID | Type | Method | Target |
|---|---|---|---|
| TST-N1 | Load | k6/Locust scenario from OPT-05 | `/health/live` p95 < 50 ms during AI load |
| TST-N2 | SSE scale | 500 idle connections + event bursts (OPT-11) | Per-connection CPU ~ constant |
| TST-N3 | Soak | 24 h with periodic syncs and analyses | No memory growth > 10 %; table sizes bounded with retention |
| TST-N4 | Regression | Full suites on every PR; nightly AI quality; weekly dependency audit | Green |
| TST-39b | Test hygiene | Re-organise sprint-named test modules by feature; remove duplicates (DC-29c) | Same or higher coverage after move |

Coverage policy: measure `app, ai, sandbox, scanner, indexer, review, agent`; start at measured baseline per package; ratchet +2 %/month; security-critical modules (`sandbox/path_guard.py`, `sandbox/command_runner.py`, `core/auth.py`, `core/security.py`) ≥ 90 % branch coverage.
