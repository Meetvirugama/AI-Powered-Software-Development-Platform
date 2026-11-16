# 00 — Project Overview

**Project:** AI-Powered Software Development Platform (`AI-Powered-Software-Development-Platform-main`)
**Audit date:** 2026-11-14
**Audit type:** Static, read-only analysis. No source file was modified, created, moved or deleted inside the project.
**Documentation set:** `project_audit_documentation/00` … `12` (this folder)

---

## 1. How to read this documentation set

| Document | Purpose | Primary IDs it defines |
|---|---|---|
| 00_PROJECT_OVERVIEW.md | Stack, structure, module inventory, headline observations | — |
| 01_COMPLETE_CODEBASE_AUDIT.md | **Master issue register** (every finding, with evidence) | `ISS-001` … `ISS-042` |
| 02_SYSTEM_ARCHITECTURE.md | Current architecture per layer, Mermaid diagrams (current + PROPOSED) | — |
| 03_INTEGRATION_AUDIT.md | API inventory (125 routes), data flows, integration matrix | `API-###` rows |
| 04_FEATURE_PARITY_AUDIT.md | Frontend ↔ backend feature parity and consolidation | `FEAT-01` … `FEAT-22` |
| 05_DEAD_DUPLICATE_CODE_AUDIT.md | Dead / duplicate / redundant code with removal validation | `DC-01` … `DC-31` |
| 06_OPTIMIZATION_PLAN.md | Frontend, backend, AI, DB optimizations | `OPT-01` … `OPT-24` |
| 07_SECURITY_AND_RELIABILITY_AUDIT.md | Security + reliability findings (severity-ranked) | uses `ISS-###` |
| 08_DEPENDENCY_AND_CONFIGURATION_AUDIT.md | Dependency inventory, config/env audit | `DEP-01` … `DEP-18` |
| 09_TESTING_AND_VALIDATION_PLAN.md | Test roadmap and scenarios | `TST-01` … `TST-40` |
| 10_IMPLEMENTATION_ROADMAP.md | Phased plan with priorities | `T1.1` … `T9.x` |
| 11_FILE_WISE_CHANGE_PLAN.md | Per-file Modify / Create / Merge / Remove / Keep plan | references all of the above |
| 12_FINAL_PROJECT_CHECKLIST.md | Completion checklist | — |

### 1.1 Evidence labels used everywhere

| Label | Meaning |
|---|---|
| **Verified** | Confirmed by reading the code / config at the cited lines. |
| **Verified (static)** | Confirmed structurally by an AST/grep scan across the repository; runtime impact still needs measurement. |
| **Suspected** | Strong evidence but depends on runtime, deployment or external state. Each one says what must be checked. |
| **Recommendation** | Architectural / quality improvement, not a defect. |
| **Not verified** | Could not be checked in this environment (reason stated). |

### 1.2 What was and was not executed

| Activity | Status |
|---|---|
| Unzip and recursive inspection of all 1,297 files | Done |
| Custom AST scans (route extraction, import graph, authorization signals, async/sync DB usage, unused imports, silent `except` handlers, `app.state` DI holes) | Done — scripts were run outside the project tree |
| Frontend ↔ backend route cross-match (regex over `frontend/src`, excluding tests/mocks) | Done |
| Backend test suite (`pytest`) | **Not executed** — FastAPI, SQLAlchemy and the rest of `backend/requirements.txt` are not installed in the audit environment, and package installation was not permitted (network disabled). |
| Frontend tests / lint / `tsc` / `vite build` | **Not executed** — `frontend/node_modules` is absent and `npm ci` was not permitted. |
| Database migrations, `alembic check` | **Not executed** — requires a live PostgreSQL + pgvector instance. |
| External services (GitHub, Gemini, Groq, Redis) | **Not contacted.** |

No performance numbers in this documentation are measurements. Where a gain is expected, the benchmark method to prove it is given instead.

---

## 2. Project introduction

The platform is a repository-aware AI developer workbench. A user signs in with GitHub, installs a GitHub App, connects repositories, and the backend clones, parses (tree-sitter), chunks, embeds (Gemini, 768-d) and indexes them in PostgreSQL/pgvector. On top of that index the product offers:

1. **Grounded repository chat** (hybrid RAG; optional bounded "agentic" tool-calling mode).
2. **Developer intelligence studios** — Explain, Bug Detection, Test Generation, Code Review (with GitHub publication).
3. **Agent tasks** — issue/requirement → plan → human approval → sandboxed execution → tests → bounded repair → independent verification → Draft PR.
4. **Project memory**, **analysis history**, **GitHub webhook automation**, **tool approvals / MCP elicitations**, and a **Tools & MCP admin** screen.

---

## 3. Technology stack

| Layer | Technology (as found in code) | Evidence |
|---|---|---|
| Frontend | React 19, TypeScript ~6.0, Vite 8, Tailwind CSS 4 (+ `tailwind.config.js` via `@config`), React Router 7, TanStack Query 5, Zustand 5, Axios, lucide-react | `frontend/package.json`, `frontend/src/index.css` |
| Frontend tests | Vitest 4, Testing Library, jsdom, **in-house MSW re-implementation** (`frontend/src/lib/msw/*`) | `frontend/vite.config.ts` aliases `msw` → local shim |
| Backend | Python 3.11 (Docker), FastAPI, Pydantic v2, pydantic-settings, SQLAlchemy 2 (sync **and** async engines, psycopg 3), Alembic | `backend/requirements.txt`, `backend/app/core/database.py` |
| Database | PostgreSQL 15 + pgvector (compose: `pgvector/pgvector:pg15`; CI uses PG16) | `docker-compose.yml`, `.github/workflows/postgres-persistence-ci.yml` |
| Cache / queues / pub-sub | Redis 7 (sync + async clients), Redis Streams for SSE replay | `backend/app/core/redis.py`, `backend/app/services/sse_redis_streams.py` |
| LLM | Gemini (`gemini-flash-lite-latest`) primary, Groq (`openai/gpt-oss-120b`) fallback | `backend/app/core/config.py` L73–80 |
| Embeddings | Gemini `gemini-embedding-001`, 768 dims; optional local CodeRank (eval only) | `config.py` L81–87 |
| Reranking | sentence-transformers cross-encoder; optional ONNX path (not wired — ISS-008) | `backend/ai/retrieval/reranker*.py` |
| Code parsing | tree-sitter + tree-sitter-language-pack + per-language bindings | `backend/scanner/parser.py` |
| Static analysis | Ruff, Bandit, ESLint/Biome, Semgrep, OSV-Scanner, Gitleaks (all invoked as external binaries) | `backend/review/static_reviewer.py`, `backend/scanner/*_runner.py` |
| Sandbox | `local` subprocess / `container` (Docker CLI, gVisor) / `runner` (separate FastAPI service `backend/runner/main.py`) | `backend/sandbox/factory.py` |
| Workflows | Raw `threading.Thread` + in-memory registry; DBOS decorator present but DBOS never launched (ISS-010) | `backend/ai/workflows/autonomous_task_workflow.py` |
| Observability | OpenTelemetry (off by default), Langfuse adapter (off by default), structured logging with request IDs | `backend/app/observability/*`, `backend/app/core/logging.py` |
| Deploy | Docker (multi-stage, non-root), docker-compose (api + sync_worker + pg + redis), Azure Web App via GitHub Actions, Vercel for frontend | `Dockerfile`, `.github/workflows/main_ai-powered-dev-platform-api.yml`, `vercel.json` |

---

## 4. Directory structure (source only; `node_modules`/caches excluded)

```text
AI-Powered-Software-Development-Platform-main/
├── main.py                     # Root ASGI entry (adds backend/ to sys.path, exports app.main:app)
├── startup.sh                  # Container entry: role switch (api | sync_worker | webhook_worker), alembic upgrade, uvicorn
├── run_local.sh, Makefile      # Local dev runners
├── Dockerfile, docker-compose.yml, .dockerignore
├── vercel.json                 # Frontend hosting + /api rewrite to Azure (duplicated in frontend/vercel.json)
├── pyproject.toml, requirements.txt (→ backend/requirements.txt), pytest.ini
├── .github/workflows/          # 4 workflows: main build/deploy, nightly AI quality, PG persistence, security
├── task.md, task2.md, task3.md, *_COMPREHENSIVE_TEST_PLAN.md, CODEBASE_CLEANUP_AND_OPTIMIZATION_AUDIT.md
├── Docs/                       # 253 Markdown files (sprint reports, audits, ADR-like docs)
├── tests/e2e/                  # 4 "tier" suites using FastAPI TestClient (not browser E2E)
├── backend/
│   ├── app/                    # FastAPI application (165 files, ~54.6k LOC)
│   │   ├── main.py             # App factory, middleware chain, router mount
│   │   ├── api/v1/             # Routers: auth, repositories, chat, analysis/*, github, issues, memories, tasks, events, health, mcp_registry
│   │   ├── core/               # config, database, redis, auth middleware, rate limit, errors, lifespan, security headers, telemetry
│   │   ├── integrations/github/# GitHub App client/service, source service, token manager, extra routes (/source/*)
│   │   ├── models/             # 26 SQLAlchemy tables (15 files)
│   │   ├── repositories/       # Data-access layer (incl. analysis/* and task/* mixins)
│   │   ├── schemas/            # Pydantic DTOs
│   │   ├── services/           # Orchestrators, history services, workers, webhook handlers, SSE streams
│   │   ├── workers/            # Standalone worker entrypoints (sync, webhook)
│   │   ├── mcp/server.py       # In-process MCP JSON-RPC server + default tool catalogue
│   │   └── observability/      # OTel + Langfuse
│   ├── ai/                     # AI layer (112 files, ~30.3k LOC)
│   │   ├── llm/                # LLMGateway + Gemini/Groq providers
│   │   ├── embeddings/         # Gemini provider, cached service, rate limiter, local (eval) provider
│   │   ├── retrieval/          # Vector, lexical, hybrid (RRF), reranker(+ONNX), graph expansion, cache, evaluation
│   │   ├── pipeline.py         # Canonical RAGPipeline (chat)
│   │   ├── agent/              # Agentic chat orchestrator, tool registry/executor, budget, policy, 4 read-only tools
│   │   ├── context/            # Context builders per feature, token budget
│   │   ├── services/           # Planner, repair loops, edit synthesizers, verifiers, engines
│   │   ├── intelligence/       # Co-change, related files, impact, snapshot
│   │   ├── prompts/            # 14 .txt prompt templates
│   │   ├── schemas/, security/ # Output/grounding validation; provenance/taint tracking
│   │   ├── workflows/          # Autonomous task workflow (thread-based)
│   │   └── evaluation/         # Quality gate, mini-SWE-bench (25 tasks)
│   ├── agent/tools/            # Task tool registry/router/rate limiter/schema validator + MCP/plugin adapters
│   ├── sandbox/                # Workspace manager, command runner, backends, diff verifier, test runner, gitleaks
│   ├── scanner/                # Walker, parser, symbols, graph, rules, static bug scanner, external runners, test analyzers
│   ├── indexer/                # Chunker, incremental indexer
│   ├── review/                 # StaticReviewer (Ruff/Bandit/ESLint/Biome)
│   ├── runner/                 # Separate sandbox runner FastAPI service
│   ├── poc/dbos/               # DBOS proof-of-concept
│   ├── migrations/             # Alembic env + 18 linear revisions
│   ├── scripts/                # Benchmarks, seeding, security gate
│   └── tests/                  # 227 test modules (+7 symlinked duplicates, DC-29d), ~2,792 test functions, ~93k LOC
└── frontend/
    ├── src/pages/              # 16 pages (dashboard, repositories, 7 studios, tasks, tools admin, auth)
    ├── src/components/         # explorer/, tasks/, taskStudio/, studios/, shared/
    ├── src/services/           # api.ts (axios), repositories, analysis, tasks, memory, chat, auth, discovery
    ├── src/hooks/, src/stores/ # TanStack Query hooks; 2 Zustand stores
    ├── src/realtime/           # SSE client (EventSource + reconnect + Last-Event-ID)
    ├── src/lib/msw/, src/mocks/# Home-grown MSW shim + 4.3k LOC of mock handlers
    └── src/test/               # 32 test files, ~352 test cases
```

---

## 5. Module inventory (what each major module does and what it talks to)

| Module | Responsibility | Key symbols | Talks to |
|---|---|---|---|
| `main.py` (root) | ASGI entry for uvicorn/Azure | imports `app.main.app` | backend app |
| `backend/app/main.py` | App factory, middleware order (SecurityHeaders → CORS → RequestId → JWT → RateLimit), error handlers, routers | `app` | `app.core.*`, `app.api.v1.router` |
| `backend/app/core/lifespan.py` | Startup wiring of LLM gateway, RAG pipeline, intelligence services, history services, GitHub service, OTel, reconciliation, embedded workers | `init_llm_gateway`, `init_rag_pipeline`, `init_intelligence_services`, `lifespan` | `ai.*`, `app.services.*`, Redis, DB |
| `backend/app/core/auth.py` | JWT middleware (cookie or Bearer), Origin-based CSRF check, Redis blocklist with local cache | `JWTMiddleware`, `PUBLIC_PATHS` | Redis, `app.core.security` |
| `backend/app/core/config.py` | Settings + production validator | `Settings.validate_production_security` | env vars |
| `backend/app/core/database.py` | Sync engine + async engine (psycopg3), `get_db` | `engine`, `SessionLocal`, `async_engine`, `AsyncSessionLocal` | PostgreSQL |
| `backend/app/api/v1/*` | HTTP surface (125 routes incl. `/source/*`) | see 03 | services, repositories |
| `backend/app/api/v1/dependencies.py` | RBAC helpers + ownership guards | `get_owned_repository`, `get_owned_task`, `require_min_role` | repositories |
| `backend/app/services/task_execution_orchestrator.py` (2,458 LOC) | Task execution, tests, repair, verification, push, Draft PR | `TaskExecutionOrchestrator` | sandbox, ai.services, GitHub, DB |
| `backend/app/services/*_orchestrator.py` | Explain / Bug / Test-gen / Review orchestration | `LLMCodeExplanationService`, `LLMBugDetectionService`, … | ai.context, ai.services, LLM |
| `backend/app/services/sync_worker.py` | Repository clone → parse → chunk → embed → index job processor + loop | `process_sync_job`, `sync_worker_loop` | GitHub, scanner, indexer, embeddings, DB, Redis |
| `backend/app/services/webhook_worker.py` | Durable webhook event processing loop (lease-based) | `webhook_worker_loop` | DB, sync jobs, review automation |
| `backend/app/services/sse_redis_streams.py` | SSE broker over Redis Streams | `get_sse_broker`, `publish_chat_token` | Redis |
| `backend/app/integrations/github/*` | GitHub App auth, API client, cache, source service, `/source/*` routes | `GitHubService`, `GitHubSourceService` | GitHub REST |
| `backend/ai/llm/client.py` | Provider gateway with fallback, tracing | `LLMGateway.generate/generate_with_tools/generate_stream` | Gemini/Groq providers |
| `backend/ai/pipeline.py` | Canonical RAG chat pipeline | `RAGPipeline.chat` | HybridRetriever, ContextBuilder, LLMGateway, GroundingValidator |
| `backend/ai/retrieval/hybrid.py` | Vector + lexical + RRF + rerank + graph expansion + cache | `HybridRetriever` | pgvector, PG FTS, Redis |
| `backend/ai/agent/orchestrator.py` | Bounded tool-calling chat agent | `AgentOrchestrator.run` | `ai.agent.tools/*`, LLMGateway |
| `backend/agent/tools/*` | Task tool registry/router with policy + rate limits (used by task execution) | `ToolRouter`, `ToolRegistry` | sandbox, `app.core.tool_api_policy` |
| `backend/sandbox/workspace_manager.py` (2,138 LOC) | Disposable task workspaces, git ops, push | `WorkspaceManager` | git CLI, filesystem |
| `backend/sandbox/command_runner.py` | Allow-listed command execution with env scrubbing | `WorkspaceCommandRunner` | subprocess |
| `backend/runner/main.py` | Remote sandbox runner service (Bearer auth) | `verify_runner_auth` | sandbox |
| `backend/scanner/*` | File walking, tree-sitter parsing, symbols/edges, rule-based bug scan, external scanners | `StaticBugScanner`, `SemgrepRunner`, `OSVRunner` | filesystem, binaries |
| `backend/indexer/*` | Symbol-aware chunking and incremental indexing with content hashes | `incremental.py`, `chunker.py` | DB, embeddings |
| `frontend/src/services/api.ts` | Axios client, AI timeouts (180 s), error normalisation, 401 → `/login` redirect | `apiClient`, `normaliseError` | backend `/api/v1` |
| `frontend/src/realtime/index.ts` | SSE client to `/api/v1/events` | `RealtimeClient` | backend SSE |
| `frontend/src/pages/RepositoryTaskStudio.tsx` (1,552 LOC) & `TaskDetail.tsx` | Two UIs for the same task lifecycle (DC-20) | — | `services/tasks.ts` |
| `frontend/src/pages/ToolsIntegrationsAdminPage.tsx` | MCP admin UI — **local state only** (ISS-033) | `INITIAL_SERVERS` | none |

Size summary (non-test): backend ≈ 115k LOC Python, frontend ≈ 31k LOC TS/TSX (plus 4.3k LOC mocks). Tests: backend ≈ 93k LOC, frontend ≈ 9k LOC.

---

## 6. Current architecture (summary)

A single FastAPI process hosts the HTTP API **and**, by default, two background loops (sync worker and webhook worker) plus ad-hoc worker threads for autonomous workflows. All AI services are constructed once in `lifespan` and stored on `app.state`. Most routes are synchronous `def` handlers using a sync SQLAlchemy session; 42 `async def` handlers also use the sync session (ISS-009). Redis carries the JWT blocklist, OAuth state, rate limits, sync queue, retrieval cache, embedding cache and SSE streams. The frontend is a SPA on Vercel that reaches the API through a Vercel rewrite to Azure. Detailed diagrams: **02_SYSTEM_ARCHITECTURE.md**.

---

## 7. Major observations (headline)

1. **The core product loop is genuinely integrated.** 81 of the 125 backend routes have a live frontend caller and **no frontend call targets a non-existent endpoint** (03 §2). The prior cleanup audit (`CODEBASE_CLEANUP_AND_OPTIMIZATION_AUDIT.md`) was largely acted on: the duplicate `/source/task/*` stack is now a deprecation stub, `StaticReviewer` is wired, missing `repository_files` constraints were migrated.
2. **Three critical, configuration-driven security risks**: a publicly known fallback `JWT_SECRET` in `docker-compose.yml` that passes the production validator (ISS-001), an impersonating dev-login that is live whenever `APP_ENV` is not explicitly production (ISS-002), and unauthenticated-by-role, globally shared MCP registry mutation endpoints (ISS-003).
3. **Several advertised capabilities are not actually wired**: symbol-graph retrieval expansion (ISS-007), configurable/ONNX reranking (ISS-008), durable workflows (ISS-010), token refresh (ISS-012), project memory feeding AI prompts (ISS-036), chat token streaming (ISS-015), production static scanners (ISS-013).
4. **Deployment topology risk**: production forces the embedded sync worker off, while the CI/CD deploy job ships a single Azure Web App with no separate worker (ISS-005 — must be verified against the live Azure setup).
5. **Event-loop blocking** remains the largest backend performance risk: 42 `async def` handlers perform synchronous DB I/O (ISS-009).
6. **Backend features without UI**: code search, symbol browser, webhook event console, repository automation settings, commit/PR browser, task checkpoints/invariants/traceability (04 §3).
7. **Maintainability load**: 115 silent `except Exception: pass` handlers (ISS-040), 28 test-aware branches in production code (ISS-041), a 4,016-line hand-written mock for tasks that already drifts from the real API (ISS-017), sprint-named test files, and 253 Markdown reports with stale claims (ISS-028).

Counts of findings by priority (from 01): **P0: 4 · P1: 11 · P2: 19 · P3: 8** (42 total; 37 Verified / Verified (static), 5 Suspected — one of them latent).
