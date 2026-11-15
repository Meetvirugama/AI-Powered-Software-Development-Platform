# 02 — System Architecture

All diagrams describe the **current, discovered** architecture unless the heading says **PROPOSED**. Issue references point to 01.

---

## 1. Overall system architecture (current)

```mermaid
flowchart LR
  subgraph Browser
    SPA["React SPA (Vercel)<br/>TanStack Query + Zustand"]
  end
  subgraph Vercel
    RW["Rewrite /api/* → Azure"]
  end
  subgraph API["FastAPI process (Azure Web App / compose 'api')"]
    MW["Middleware: SecurityHeaders → CORS → RequestId → JWT → RateLimit"]
    R["Routers /api/v1 (125 routes)"]
    LS["lifespan: app.state services"]
    EWH["Embedded webhook worker loop (always on, ISS-014)"]
    ESW["Embedded sync worker loop (off in prod, ISS-005)"]
    WT["Autonomous workflow threads (in-memory, ISS-010)"]
  end
  subgraph Workers["Optional worker processes (startup.sh SERVICE_ROLE)"]
    SW["sync_worker"]
    WW["webhook_worker (not deployed)"]
  end
  subgraph Data
    PG[("PostgreSQL 15 + pgvector<br/>26 tables")]
    RD[("Redis 7<br/>blocklist, OAuth state, rate limits,<br/>sync queue, caches, SSE streams")]
  end
  subgraph External
    GH["GitHub App / OAuth / REST"]
    GEM["Gemini (chat + embeddings)"]
    GRQ["Groq (fallback chat)"]
  end
  subgraph Sandbox
    LOC["local subprocess (dev)"]
    CON["container (docker CLI) — missing in image (ISS-006)"]
    RUN["runner service (backend/runner) — not in compose"]
  end
  SPA -->|HTTPS + cookie| RW --> MW --> R
  SPA -.->|SSE /api/v1/events| R
  R --> LS
  LS --> PG & RD
  LS --> GEM & GRQ
  R --> GH
  SW --> PG & RD & GH & GEM
  EWH --> PG
  WT --> Sandbox
  R --> Sandbox
  GH -->|webhooks| R
```

**Observations.** The API process is also a worker host (webhook loop always, sync loop in dev, workflow threads). In production the sync loop is forced off (ISS-005) and no separate worker is deployed by the pipeline; the container sandbox cannot work in the image (ISS-006).

---

## 2. Frontend architecture and frontend ↔ backend communication

| Concern | Implementation | Notes |
|---|---|---|
| Routing | `frontend/src/App.tsx` — `/login`, `/auth/callback`, `/app/{dashboard,repositories,tasks,tasks/new,tasks/:taskId,tools}`, `/app/repositories/:id/{(index),chat,explain,bugs,tests,review,tasks}` | All pages lazy-loaded; `ProtectedRoute` gates `/app` |
| Server state | TanStack Query hooks in `src/hooks/*` (`useRepositories`, `useTasks` 567 LOC, `useAnalysis`, `useRepositoryChat`, `useStudioFile`, …) | Polling via `refetchInterval` for repos and tasks |
| Client state | Zustand: `useAuthStore` (user), `useAppStore` (sidebar) | Minimal, appropriate |
| HTTP | `src/services/api.ts` Axios: `withCredentials`, 30 s default, 180 s for URLs containing `/explain`, `/chat`, `/tests`, … | Substring matching also hits non-AI GETs (`/tasks/{id}/tests`) — OPT-02 |
| Auth | Cookie (httpOnly) set by backend; 401 → hard redirect to `/login?redirect=…` | No refresh (ISS-012) |
| Realtime | `src/realtime/index.ts` EventSource to `/api/v1/events` with Last-Event-ID and backoff; consumed only by `useRealtimeRepositories` (repo sync progress) | Tasks/chat do not use SSE |
| Types | Hand-written `src/types/{api,analysis,task,memory}.ts` (2,171 LOC) | Drift from backend (ISS-017) |
| Mocks | `src/lib/msw/*` (custom MSW clone) + `src/mocks/handlers/*` (4,319 LOC), enabled only with `VITE_ENABLE_MSW=true` in dev | DC-19 |

```mermaid
sequenceDiagram
  participant UI as Page / Component
  participant Q as TanStack Query hook
  participant S as services/*.ts
  participant AX as apiClient (Axios)
  participant API as FastAPI /api/v1
  UI->>Q: useXxx() / mutateAsync()
  Q->>S: fetcher(params)
  S->>AX: apiClient.get/post(path)
  AX->>API: HTTPS + cookie (Origin checked for writes)
  API-->>AX: JSON | error envelope {code,message,retryable,request_id}
  AX-->>S: data | normaliseError(err) → ApiError
  S-->>Q: typed result
  Q-->>UI: data / isLoading / error
  Note over AX: 401 -> window.location = /login?redirect=…
```

---

## 3. Backend service architecture

```mermaid
flowchart TB
  subgraph HTTP["app/api/v1"]
    AUTH[auth.py]
    REPO[repositories.py]
    CHAT[chat.py]
    AN["analysis/{explain,bugs,tests,review,history}.py"]
    GHR["github.py + integrations/github/routes.py (/source/*)"]
    ISSUES[issues.py]
    MEM[memories.py]
    TASKS["tasks.py (2,121 LOC, 47 routes)"]
    EVT["events.py (SSE)"]
    MCP["mcp_registry.py (in-memory, ISS-003)"]
  end
  subgraph Services["app/services"]
    EXO[explanation_orchestrator]
    BDO[bug_detection_orchestrator]
    TGO[test_generation_orchestrator]
    CRO[code_review_orchestrator]
    TEO["task_execution_orchestrator (2,458 LOC)"]
    HIST["*_history_service, analysis_run_history_service"]
    SYNC["sync_worker / repository_sync"]
    WH["webhook_worker / webhook_handlers"]
    SSE[sse_redis_streams]
    GITB["git_branch (pr-metadata → pull_requests, ISS-042)"]
    MEMS[memory_service]
  end
  subgraph Repos["app/repositories (data access)"]
    RR[RepositoryRepository]
    TR["TaskRepository (task/* mixins)"]
    AR["analysis/* mixins"]
    OTHER["chunk, symbol, edge, memory, webhook_event, installation, user"]
  end
  subgraph AI["backend/ai"]
    LLMGW[llm.client.LLMGateway]
    RAG[pipeline.RAGPipeline]
    AGENT[agent.AgentOrchestrator]
    CTX["context/* builders"]
    AISVC["services/* (planner, repair, synthesizers, verifiers, engines)"]
    WF["workflows/autonomous_task_workflow (threads)"]
  end
  SBX["sandbox/* (workspace_manager, command_runner, backends)"]
  AGT["agent/tools (ToolRouter, registry, policy)"]
  SCN["scanner/*, review/static_reviewer"]
  IDX["indexer/*"]
  AN --> EXO & BDO & TGO & CRO
  EXO & BDO & TGO & CRO --> CTX & AISVC & LLMGW & HIST
  CRO --> SCN
  BDO --> SCN
  CHAT --> RAG & AGENT
  TASKS --> TEO & WF & AISVC
  TEO --> SBX & AGT & AISVC & MEMS
  GHR --> GITB
  SYNC --> IDX & SCN
  HTTP --> Repos
  Services --> Repos
```

**Dependency injection pattern.** Long-lived services are created in `app/core/lifespan.py` and read with `getattr(request.app.state, "...", None)`, with lazy construction fallbacks in several routes (e.g., `chat.py` builds an `AgentOrchestrator` if none exists). Four `app.state` services are created but never read (ISS-039). Recommendation: typed accessor functions (`get_llm_gateway(request) -> LLMGateway`) used through `Depends`, which also simplifies test overrides and removes test sniffing (ISS-041).

**Layering health.** Routers mostly delegate to services/repositories, but `tasks.py` (2,121 LOC) and `github.py` contain substantial logic (serialization, fallbacks, inline imports). `task_execution_orchestrator.py` (2,458 LOC) and `workspace_manager.py` (2,138 LOC) are god-objects — see OPT-06.

---

## 4. AI / LLM architecture

```mermaid
flowchart LR
  subgraph Gateway["ai/llm"]
    GW["LLMGateway<br/>generate · generate_with_tools · generate_stream(unused)"]
    GP["GeminiProvider (key rotation)"]
    QP["GroqProvider (key rotation)"]
    GW --> GP
    GW -. fallback on non-auth errors .-> QP
  end
  subgraph Consumers
    RAGP["RAGPipeline.chat"]
    AG["AgentOrchestrator (bounded tool loop:<br/>≤3 rounds, ≤6 tool calls, ≤4 model calls, 35 s)"]
    ORC["Explain / Bug / TestGen / Review orchestrators"]
    PLN["TaskPlanner + HierarchicalLocalizer"]
    REP["BoundedRepairLoop / LLMRepairSynthesizer / EditSynthesizer"]
    VER["RequirementVerifier / IndependentVerifier"]
  end
  subgraph Tools["ai/agent/tools (read-only)"]
    T1[search_code] --- T2[read_file_range] --- T3[get_symbol] --- T4[find_callers]
  end
  PROMPTS["ai/prompts/*.txt (14) + validate_required_prompts()"]
  VALID["ai/schemas: output models, GroundingValidator, PromptBuilder"]
  SEC["ai/security: provenance + taint tracking"]
  RAGP & AG & ORC & PLN & REP & VER --> GW
  AG --> Tools
  ORC & RAGP --> PROMPTS & VALID
  REP & PLN --> SEC
```

| Capability | Status |
|---|---|
| Provider selection / fallback | Implemented (`lifespan.init_llm_gateway`; no fallback on auth errors by default) |
| Retry | Provider-level retries (`ai_max_retries=3`) + fallback |
| Concurrency / rate control | **Missing** for chat LLM calls (ISS-025); present for embeddings |
| Streaming | Implemented in gateway, **unused**; simulated over SSE (ISS-015) |
| Tool calling | Implemented for chat agent (Gemini & Groq normalized); task tools go through `agent/tools/ToolRouter` |
| Output validation | Pydantic schemas + `GroundingValidator` (citations checked against retrieved chunks / DB) |
| Context/token management | `ai/context/token_budget.py` (tiktoken), per-feature budgets `context_budget_*` |
| Cost tracking | `app/core/telemetry.py` stage metrics + static price table (Gemini Flash prices hard-coded — verify current pricing before relying on cost numbers) |
| Prompt management | Plain-text files loaded at runtime; no versioning in DB; prompts not hashed into run records (OPT-18) |
| Memory | Pipeline supports it; never supplied (ISS-036) |
| Conversation history | Client-supplied only (ISS-016) |

---

## 5. RAG pipeline (current)

```mermaid
flowchart TB
  Q["User question + client history"] --> INT["Intent routing (retrieval_intent_routing_enabled)"]
  INT --> EMB["Query embedding<br/>Gemini CODE_RETRIEVAL_QUERY, 768-d<br/>CachedEmbeddingService (Redis)"]
  INT --> LEX["Lexical: PostgreSQL FTS on code_search_text<br/>+ code-aware tokenizer"]
  EMB --> VEC["Vector: pgvector HNSW<br/>adaptive ef_search 40/64/120"]
  VEC --> RRF["RRF fusion"]
  LEX --> RRF
  RRF --> GX{"Graph expansion<br/>(SymbolGraphExpander)"}
  GX -. "never constructed (ISS-007)" .-> RRK
  RRF --> RRK["Cross-encoder rerank<br/>(pytorch only; factory unused, ISS-008)"]
  RRK --> CACHE["Retrieval cache (Redis + local LRU,<br/>generation-based invalidation)"]
  CACHE --> CB["ContextBuilder<br/>chunks + history (+ memory: always empty, ISS-036)"]
  CB --> LLM["LLMGateway.generate"]
  LLM --> GV["GroundingValidator<br/>(citations ↔ chunks)"]
  GV --> RED["Secret redaction (redact_obj)"]
  RED --> A["RepositoryAnswer {answer, sources[file, lines]}"]
  A -. "full answer published once as 'chat token' (ISS-015)" .-> SSE[(Redis Stream)]
```

Indexing side (sync worker): `scanner.walker` → `scanner.parser` (tree-sitter) → symbols/edges (`code_symbols`, `symbol_edges`, PageRank-style `importance_score`) → `indexer.chunker` (symbol-aware) → `indexer.incremental` (content-hash skip, `active_index_generation`) → Gemini document embeddings (rate-limited) → `code_chunks` (HNSW index `ix_code_chunks_embedding_hnsw`, FTS on `code_search_text`).

---

## 6. Database architecture

**Technology:** PostgreSQL + pgvector; SQLAlchemy 2 declarative models (`app/models`), Alembic with a single linear chain of 18 revisions (`24498ac67b3e` → … → `k8b9c0d1e2f3`). All 26 model tables are created by migrations (every table has a matching `op.drop_table` in a downgrade). Column-level parity could **not** be verified without a live DB — run `alembic upgrade head && alembic check` in CI (TST-25).

### 6.1 ER diagram (current; key columns only)

```mermaid
erDiagram
  users ||--o{ github_installations : "user_id"
  users ||--o{ repositories : "user_id"
  github_installations ||--o{ repositories : "installation_id"
  users ||--o{ sync_jobs : "user_id"
  repositories ||--o{ sync_jobs : "repository_id"
  repositories ||--o{ repository_files : "repository_id"
  repository_files ||--o{ code_symbols : "file_id"
  code_symbols ||--o{ code_symbols : "parent_id"
  repositories ||--o{ code_chunks : "repository_id"
  repository_files ||--o{ code_chunks : "file_id"
  code_symbols ||--o{ code_chunks : "symbol_id"
  code_symbols ||--o{ symbol_edges : "source/target_symbol_id"
  repositories ||--o{ memory_entries : "repository_id"
  repositories ||--o{ analysis_runs : "repository_id"
  users ||--o{ analysis_runs : "user_id"
  analysis_runs ||--o{ analysis_findings : "analysis_run_id"
  repositories ||--o{ github_issues : "repository_id"
  analysis_findings ||--o{ github_issues : "origin_finding_id"
  repositories ||--o{ tasks : "repository_id"
  users ||--o{ tasks : "user_id"
  github_issues ||--o{ tasks : "source"
  tasks ||--o{ task_plans : "task_id"
  tasks ||--o{ task_approvals : "task_id"
  task_plans ||--o{ task_approvals : "plan_id"
  tasks ||--|| workspaces : "task_id"
  tasks ||--o{ task_executions : "task_id"
  tasks ||--o{ tool_invocations : "task_id"
  tasks ||--o{ test_runs : "task_id"
  tasks ||--o{ repair_attempts : "task_id"
  tasks ||--o{ verification_results : "task_id"
  tasks ||--o{ task_checkpoints : "task_id"
  tasks ||--o{ task_events : "task_id"
  tasks ||--o{ task_pull_requests : "task_id"
  repositories ||--o{ pull_requests : "repository_id"
  repositories ||--o{ github_webhook_events : "repository_id"
  users {
    uuid id
    string github_id
    string login
    string role
  }
  repositories {
    uuid id
    uuid user_id
    string owner
    string name
    string sync_status
    int active_index_generation
    bool auto_sync_enabled
    bool pr_review_enabled
  }
  code_chunks {
    uuid id
    vector embedding
    text code_search_text
    string content_hash
  }
  memory_entries {
    uuid id
    string type_
    string source
    vector embedding
  }
  tasks {
    uuid id
    string status
    int plan_version
    int approved_plan_version
    int repair_attempts_used
  }
  pull_requests {
    uuid id
    uuid task_id "NO FK (ISS-042)"
  }
```

### 6.2 Observations

| Topic | Finding | Ref |
|---|---|---|
| Duplicate structures | `pull_requests` vs `task_pull_requests` | ISS-042 |
| Missing relationships | `pull_requests.task_id` no FK; user FKs without `ondelete` | ISS-042, ISS-034 |
| Missing tables for features | chat sessions/messages; MCP servers/tool policies; durable workflow jobs | ISS-016, ISS-003, ISS-010 |
| Indexes | HNSW on `code_chunks.embedding` and `memory_entries.embedding`; `(repository_id, content_hash)`; 112 `index=True`/`Index(` declarations. Repository listing lacks `(user_id, created_at)` for pagination (ISS-024) | OPT-20 |
| Transactions | Sync sessions per request (`get_db`); long LLM awaits happen while a session is open in several async handlers | ISS-009 |
| Connection management | Two engines per process | ISS-032 |
| Data lifecycle | `AnalysisRunHistoryService.purge_expired_runs(retention_days=30)` (`app/services/analysis_run_history_service.py` L239) and `app/repositories/analysis/retention.py` exist, but **nothing calls the purge** (no route, worker or scheduler) — Verified (static). `analysis_runs.result_payload`, `task_events`, `tool_invocations`, `github_webhook_events` grow without bound. Workspace cleanup via `workspaces.cleanup_at` + startup recovery | OPT-21 |
| Bypass of migrations | `scripts/seed_database.py` uses `drop_all/create_all` | ISS-029 |

---

## 7. Authentication workflow (current)

```mermaid
sequenceDiagram
  participant B as Browser (SPA)
  participant API as FastAPI
  participant R as Redis
  participant GH as GitHub
  B->>API: GET /api/v1/auth/github/login?redirect_url=…
  API->>R: SETEX oauth_state:{state} 600s (redirect validated against CORS origins)
  API-->>B: 302 → github.com/login/oauth/authorize?state=…
  B->>GH: authorize
  GH-->>B: 302 → /api/v1/auth/github/callback?code&state
  B->>API: callback
  API->>R: GET+DEL oauth_state
  API->>GH: exchange code, fetch user
  API->>API: upsert user, create HS256 JWT (15 min, iss/aud, jti, role)
  API-->>B: 302 → frontend + Set-Cookie access_token (httpOnly, Secure, SameSite=None in prod)
  B->>API: any /api/v1 request (cookie)
  API->>API: JWTMiddleware: Origin check for writes (ISS-021), decode, blocklist check (local cache 5 s / Redis)
  Note over B,API: After 15 min -> 401 -> redirect to /login (no refresh, ISS-012)
  B->>API: POST /auth/logout -> SETEX auth:blocklist:{jti}
  Note over API: Dev path: POST /auth/dev-login (public path - enabled when APP_ENV ∈ dev/local, ISS-002)
```

Authorization: role claim (`viewer < developer < admin`) via `require_min_role`/`require_role`; tenant isolation via `get_owned_repository` / `get_owned_task` / `_request_user_id` lookups in every router except `mcp_registry.py` (ISS-003) and the public webhook (HMAC-verified).

---

## 8. Major user workflows (actual data flow)

### 8.1 Connect and index a repository

```mermaid
sequenceDiagram
  participant UI as Repositories page
  participant API
  participant DB as Postgres
  participant Q as Redis queue
  participant W as Sync worker (embedded dev / separate prod)
  participant GH as GitHub
  participant E as Gemini embeddings
  UI->>API: GET /github/repositories (installations → repos)
  UI->>API: POST /github/repositories/{github_repo_id}/connect
  API->>DB: insert repositories + sync_jobs(queued)
  API->>Q: enqueue job_id
  API-->>UI: {repository_id, job_id}
  W->>Q: claim (lease + heartbeat + repo lock)
  W->>GH: installation token, shallow clone
  W->>W: walk → parse → symbols/edges → chunk (content-hash skip)
  W->>E: embed new/changed chunks (rate-limited)
  W->>DB: upsert files/symbols/edges/chunks - bump active_index_generation
  W->>Q: publish repository.updated (SSE) and invalidate retrieval cache
  UI-->>API: SSE /events → useRealtimeRepositories → refetch repo
```
Break points: no worker in production (ISS-005); global SSE fan-out (ISS-020).

### 8.2 Ask a question (chat)
`RepositoryChat.tsx` → `useRepositoryChat` (history in React state) → `services/chat.ts` `POST /repositories/{id}/chat {question, history, mode}` → ownership check → `RAGPipeline.chat` or `AgentOrchestrator.run` → `RepositoryAnswer` (redacted) → render with citations; full answer also published to Redis Stream as one "token". Break points: ISS-007/008 (retrieval quality), ISS-015, ISS-016, ISS-036.

### 8.3 Explain / Bugs / Tests / Review
Studio page → `useAnalysis` hook → `POST /repositories/{id}/{explain|detect-bugs|generate-tests|review}` (180 s timeout) → orchestrator: resolve target (DB file / GitHub source service) → context builder (budgeted) → static scanners (bugs/review; absent in prod image, ISS-013) → LLM → schema validation → persist `analysis_runs` + `analysis_findings` (+ in-memory copy, ISS-038) → response → `AnalysisHistoryDrawer` via `/analysis-runs`. Review can publish to GitHub (`/review/publish`) and bugs can create issues (`/issues`).

### 8.4 Agent task lifecycle

```mermaid
stateDiagram-v2
  [*] --> CREATED: POST /tasks or /issues/import
  CREATED --> PLANNING: POST /tasks/{id}/plan (TaskPlanner, LLM)
  PLANNING --> PENDING_APPROVAL
  PENDING_APPROVAL --> APPROVED: POST /approve (bound to plan_hash and base_revision)
  PENDING_APPROVAL --> REJECTED: POST /reject
  APPROVED --> WORKSPACE_SETUP: POST /execute or /run-workflow (thread - ISS-010)
  WORKSPACE_SETUP --> EXECUTING
  EXECUTING --> TESTING: POST /tests (sandbox backend)
  TESTING --> REPAIRING: failures and budget left (POST /repair)
  REPAIRING --> TESTING
  TESTING --> VERIFYING: POST /verify (IndependentVerifier)
  VERIFYING --> READY_FOR_PUBLICATION
  READY_FOR_PUBLICATION --> PUBLISHING: POST /authorize-publication (not called by UI)
  READY_FOR_PUBLICATION --> DRAFT_PR_CREATED: POST /create-pr with publication_authorized flag (ISS-004)
  PUBLISHING --> DRAFT_PR_CREATED
  EXECUTING --> BLOCKED: pending tool approval / MCP elicitation
  BLOCKED --> EXECUTING
  EXECUTING --> CANCELLED: /cancel
  EXECUTING --> FAILED
  EXECUTING --> RECOVERY_REQUIRED: restart then reconcile_interrupted_tasks
  RECOVERY_REQUIRED --> EXECUTING: POST /recover
```
Statuses are the `TaskStatus` values in `backend/app/models/task.py`. Pause/resume (`/pause`, `/resume`) act on the execution/workspace state rather than adding a `TaskStatus` value; the exact transitions should be confirmed against `app/repositories/task/core.py` before relying on this diagram for implementation.
Approvals for risky tools (`/tool-approvals/*`) and MCP elicitations (`/mcp/elicitations/*`) can block execution until a human responds (`ApprovalHistoryPanel`). The UI polls `/tasks/{id}` and `/tasks/{id}/events` rather than using SSE.

---

## 9. Background job processing (current)

```mermaid
flowchart LR
  subgraph Producers
    C["POST /connect, /sync"] -->|sync_jobs row + Redis enqueue| SQ[(Redis sync queue)]
    WHK["POST /github/webhook (HMAC, dedupe by delivery id 24 h)"] -->|github_webhook_events row| WE[(DB table: status, attempts, available_at, lease)]
    RW["POST /tasks/{id}/run-workflow?async=true"] --> TH["threading.Thread + _active_workflows dict"]
  end
  subgraph Consumers
    SWL["sync_worker_loop<br/>lease TTL 60 s, heartbeat 15 s, retries 3, repo lock 120 s"]
    WWL["webhook_worker_loop (atomic claim + lease)<br/>push → sync job (SHA dedupe); PR → consolidated review"]
  end
  SQ --> SWL
  WE --> WWL
  WWL --> SQ
  SWL --> HB[(Redis worker:heartbeat:*)]
  STARTUP["lifespan startup: reconcile_stale_sync_jobs(600 s), reconcile_interrupted_tasks, recover_workspaces"]
```

---

## 10. Inter-module dependencies (import-graph facts)

- Reachability from `app.main`, `app.workers.*`, `migrations.env`: almost every module is reachable, frequently only through package `__init__` re-exports, which hides dead code. Modules whose **only** production importer is their own package `__init__` are listed in 05 §2.2.
- Two tool systems: `ai/agent/*` (chat agent, read-only tools) and `agent/tools/*` (task tool router with policy, rate limiting, MCP/plugin adapters). They share concepts (schemas, risk tiers) but not code (DC-16).
- Two GitHub access layers with overlapping methods: `GitHubService` (`list_issues`, `get_issue`, `create_task_branch`, `push_branch`) and `GitHubSourceService` (`list_issues`, `get_issue`, `setup_task_branch`) (DC-17). Push also happens via git CLI in `WorkspaceManager.push_task_branch` (three push paths).
- Two `RAGPipeline` classes (`ai/pipeline.py` canonical; `ai/retrieval/pipeline.py` test facade) (DC-02).
- `app/core/telemetry.py` (stage metrics/cost) vs `app/observability/telemetry.py` (OTel) — different responsibilities, confusing names (DC-27 rename only).

---

## 11. PROPOSED optimized architecture

> **PROPOSED** — keeps the existing stack (FastAPI, Postgres/pgvector, Redis, React). No new infrastructure technology is introduced; DBOS is optional (see 06 OPT-08).

```mermaid
flowchart LR
  subgraph FE["SPA (PROPOSED changes)"]
    GEN["Types generated from OpenAPI"]
    RQ["TanStack Query + SSE invalidation for tasks & chat"]
    STR["Chat streaming via fetch-SSE"]
  end
  subgraph API["API role (stateless, N replicas)"]
    DEP["Typed DI via Depends(get_x)"]
    ASY["Async-safe handlers (no sync DB on loop)"]
    AUTHN["Access 15 min + rotating refresh"]
    RBAC["RBAC on all admin routes"]
    LIM["LLM semaphore + per-user AI token bucket"]
  end
  subgraph JOBS["Worker roles (separate deployments)"]
    SYNCW["sync_worker"]
    HOOKW["webhook_worker"]
    TASKW["task_worker (durable task jobs:<br/>lease + heartbeat + checkpoints in Postgres)"]
  end
  subgraph EXEC["Isolation boundary"]
    RUNNER["Runner service (gVisor) — tests, repair, static scanners"]
  end
  subgraph DATA["Data"]
    PG[("Postgres: + chat_sessions/messages,<br/>mcp_servers/tool_policies, task_jobs;<br/>single PR table")]
    RD[("Redis: per-user SSE channels, queues,<br/>caches, rate limits")]
  end
  FE -->|REST + SSE| API
  API -->|enqueue| RD
  RD --> SYNCW & HOOKW & TASKW
  TASKW --> RUNNER
  API --> PG
  JOBS --> PG
  API -->|per-user channel| RD
```

Key differences from current: (1) no work executed inside API processes except request handling; (2) every long-running job durable in Postgres and leased via Redis; (3) scanners and untrusted code only in the runner; (4) per-user event channels; (5) contracts generated from OpenAPI; (6) single PR model; (7) memory wired into prompts with provenance separation.
