# System Architecture

## 1. Context

```mermaid
flowchart LR
  subgraph Browser
    SPA["React SPA<br/>TanStack Query + Zustand"]
  end
  subgraph Edge["Vercel (static hosting)"]
    RW["Rewrite /api/* to API host<br/>SPA fallback to index.html"]
  end
  subgraph APIProc["API process (FastAPI, SERVICE_ROLE=api)"]
    MW["Middleware chain"]
    R["Routers /api/v1"]
    LS["Lifespan: shared services on app.state"]
    EWH["Embedded webhook worker loop<br/>(unless DISABLE_EMBEDDED_WEBHOOK_WORKER)"]
    ESW["Embedded sync worker loop<br/>(off by default when APP_ENV=production)"]
    WT["Task workflow threads"]
  end
  subgraph Roles["Optional dedicated processes (startup.sh)"]
    SW["sync_worker"]
    WW["webhook_worker"]
    RUN["runner (isolated execution host)"]
    MIG["migrate (one-shot)"]
  end
  subgraph Data
    PG[("PostgreSQL + pgvector")]
    RD[("Redis")]
  end
  subgraph External
    GH["GitHub App / OAuth / REST"]
    GEM["Gemini: chat + embeddings"]
    GRQ["Groq: fallback chat"]
  end
  SPA --> RW --> MW --> R
  SPA -. "SSE /api/v1/events" .-> R
  R --> LS
  LS --> PG & RD & GEM & GRQ
  R --> GH
  GH -- webhooks --> R
  SW --> PG & RD & GH & GEM
  WW --> PG & RD
  WT --> RUN
  ESW --> PG
  EWH --> PG
```

The API process serves HTTP and also hosts the webhook worker loop and task-workflow threads. The embedded sync worker loop runs in development and is **disabled by default in production** (the settings validator sets `DISABLE_EMBEDDED_SYNC_WORKER=true` unless it is set explicitly), so production needs either a dedicated `sync_worker` process or an explicit `DISABLE_EMBEDDED_SYNC_WORKER=false`. Roles are selected with `SERVICE_ROLE` (see [Deployment guide](../07-deployment/DEPLOYMENT_GUIDE.md)).

## 2. Request pipeline

Middleware is registered so that the outermost layer runs first:

```mermaid
flowchart LR
  REQ[Request] --> SH["SecurityHeadersMiddleware<br/>CSP, X-Frame-Options, HSTS on HTTPS"]
  SH --> CORS["CORSMiddleware<br/>configured origins / anchored regex"]
  CORS --> RID["RequestIdMiddleware<br/>X-Request-ID, structured logs"]
  RID --> JWT["JWTMiddleware<br/>cookie/bearer decode, blocklist, Origin check on writes"]
  JWT --> RL["RateLimitMiddleware<br/>Redis per-route limits"]
  RL --> ROUTE["Router + dependencies<br/>RBAC, ownership checks"]
```

Errors are returned as an envelope `{code, message, retryable, request_id}` (`app/core/errors.py`).

## 3. Main subsystems

| Subsystem | Responsibility | Primary code |
|---|---|---|
| API layer | HTTP contracts, auth, RBAC, tenant isolation | `backend/app/api/v1` |
| Services | Orchestrators for analysis, tasks, sync, webhooks, history, publication | `backend/app/services` |
| Data access | Repository classes / aggregates over SQLAlchemy models | `backend/app/repositories`, `backend/app/models` |
| AI | LLM gateway, embeddings, retrieval, context, prompts, agents, verifiers | `backend/ai` |
| Scanner and indexer | Parsing, symbols, graphs, framework detection, rules, chunking, incremental indexing | `backend/scanner`, `backend/indexer` |
| Tools and sandbox | Tool registry/router/policy; workspaces, command runner, backends, test runner, diff verification | `backend/agent/tools`, `backend/sandbox`, `backend/runner` |
| Frontend | Studios for chat/explain/bugs/tests/review/tasks, task pages, admin page | `frontend/src` |

Details: [Backend](BACKEND_ARCHITECTURE.md) · [Frontend](FRONTEND_ARCHITECTURE.md) · [AI and RAG](AI_AND_RAG_ARCHITECTURE.md) · [Database](DATABASE_ARCHITECTURE.md) · [Agent execution](AGENT_EXECUTION_ARCHITECTURE.md).

## 4. Background processing

```mermaid
flowchart LR
  subgraph Producers
    C["POST /github/repositories/{id}/connect<br/>POST /repositories/{id}/sync"] -->|sync_jobs row + Redis enqueue| SQ[(Redis sync queue)]
    WH["POST /github/webhook<br/>HMAC, 5 MB size guard, delivery-id dedupe"] -->|github_webhook_events row| WE[(webhook events table)]
    RWF["POST /tasks/{id}/run-workflow"] --> TH["Workflow thread<br/>(in-memory registry)"]
  end
  subgraph Consumers
    SWL["Sync worker<br/>lease 60 s, heartbeat 15 s, 3 retries, repo lock 120 s"]
    WWL["Webhook worker<br/>atomic claim + lease, retries, dead-letter"]
  end
  SQ --> SWL
  WE --> WWL
  WWL -->|push to default branch| SQ
  WWL -->|pull_request, if pr_review_enabled| REV["Consolidated review"]
  SWL --> RET["Retention maintenance loop<br/>purge runs older than retention_days"]
  STARTUP["Lifespan startup: reconcile stale sync jobs,<br/>reconcile interrupted tasks, recover workspaces"]
```

## 5. Real-time events

`GET /api/v1/events` is an SSE endpoint backed by Redis Streams with `Last-Event-ID` resume. Events are published to a per-user channel (`events:user:{user_id}`). The repositories list consumes sync progress through `useRealtimeRepositories`; task pages poll task and event endpoints.

## 6. Deployment topology (reference)

| Component | Where it runs | Notes |
|---|---|---|
| SPA | Vercel | `vercel.json` rewrites `/api/*` to the API host and sets security headers incl. CSP |
| API | Azure Web App (Python runtime) | CI jobs `build-and-package` → `deploy` upload the source tree as an artifact and zip-deploy it on pushes to `main`; `post-deployment-verification` probes it. The multi-stage `Dockerfile` is used for container deployments and `docker-compose.yml` |
| Workers | Same image with `SERVICE_ROLE=sync_worker` / `webhook_worker` | Not deployed by CI; embedded loops run in the API unless disabled |
| Runner | Dedicated Linux host with Docker (+ gVisor when available) | `scripts/setup_runner_host.sh`; required for isolated execution in production |
| PostgreSQL / Redis | Managed services (e.g. Supabase, Upstash/Azure) or compose | |
