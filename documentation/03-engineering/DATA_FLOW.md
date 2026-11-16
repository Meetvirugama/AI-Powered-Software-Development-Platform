# Data Flows

## 1. Authentication (GitHub OAuth)

```mermaid
sequenceDiagram
  participant B as Browser
  participant API as FastAPI
  participant R as Redis
  participant GH as GitHub
  B->>API: GET /auth/github/login?redirect_url=…
  API->>R: store OAuth state (+ PKCE verifier), TTL
  API-->>B: 302 to GitHub authorize (state, code_challenge S256)
  B->>GH: authorize
  GH-->>B: 302 /auth/github/callback?code&state
  B->>API: callback
  API->>R: atomically consume state (GETDEL)
  API->>GH: exchange code, fetch user
  API->>API: upsert user, issue HS256 access JWT (15 min, iss/aud/jti/role) + refresh token (7 days)
  API-->>B: 302 to frontend, Set-Cookie access_token + refresh_token (httpOnly)
  B->>API: /api/v1/... (cookie)
  API->>API: JWTMiddleware: decode, blocklist check, Origin check on writes
  Note over B,API: On 401 the SPA calls POST /auth/refresh once, then retries
  B->>API: POST /auth/logout → jti added to Redis blocklist
```

If Redis is unavailable during state handling or blocklist checks, auth fails closed with `503`.

## 2. Connect and index a repository

```mermaid
sequenceDiagram
  participant UI as Repositories page
  participant API
  participant DB as Postgres
  participant Q as Redis queue
  participant W as Sync worker
  participant GH as GitHub
  participant E as Gemini embeddings
  UI->>API: GET /github/repositories
  UI->>API: POST /github/repositories/{github_repo_id}/connect
  API->>DB: insert repository + sync_job (queued)
  API->>Q: enqueue job
  API-->>UI: repository_id, job_id
  W->>Q: claim with lease + heartbeat + repo lock
  W->>GH: installation token, clone
  W->>W: walk, parse, symbols/edges, chunk (skip unchanged by content hash)
  W->>E: embed new/changed chunks (rate-limited, batched)
  W->>DB: batched upserts, bump active_index_generation
  W->>Q: publish repository.updated, invalidate retrieval cache
  UI-->>API: SSE /events → refetch repository
```

## 3. Ask a question

`RepositoryChat` → `useRepositoryChat` (history in React state) → `POST /repositories/{id}/chat {question, history, mode}` → ownership check → project memory lookup → `RAGPipeline.chat` (normal) or `AgentOrchestrator` (agentic) → `RepositoryAnswer` validated and redacted → response with citations. The final answer is also published once to the user's SSE stream.

## 4. Run an analysis

Studio page → `useAnalysis` → `POST /repositories/{id}/{explain|detect-bugs|generate-tests|review}` (long AI timeout) → orchestrator (target resolution → context → deterministic analysis → LLM → validation) → `analysis_runs` + `analysis_findings` → response → history drawer via `/analysis-runs`.

## 5. Webhook automation

```mermaid
sequenceDiagram
  participant GH as GitHub
  participant API
  participant DB as Postgres
  participant WW as Webhook worker
  participant Q as Sync queue
  GH->>API: POST /github/webhook
  API->>API: size guard (5 MB), HMAC verify, delivery-id dedupe
  API->>DB: github_webhook_events (pending)
  API-->>GH: 202
  WW->>DB: atomic claim with lease
  alt push to default branch and auto_sync_enabled
    WW->>Q: enqueue incremental sync (commit SHA dedupe)
  else pull_request and pr_review_enabled
    WW->>WW: consolidated AI + static review, publish
  end
  WW->>DB: processed | retry with backoff | dead_letter after max attempts
```

Dead-letter events can be replayed with `POST /github/events/{id}/replay`.

## 6. Task to draft PR

See [Agent execution architecture](../02-architecture/AGENT_EXECUTION_ARCHITECTURE.md). Every step writes `task_events`; tool calls write `tool_invocations`; tests write `test_runs`; repairs write `repair_attempts`; verification writes `verification_results`; publication writes `task_pull_requests`. `GET /tasks/{id}/traceability` returns the chain from the originating finding/issue to the draft PR.
