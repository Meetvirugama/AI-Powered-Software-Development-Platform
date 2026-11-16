# Backend Architecture

Python 3.11 FastAPI application. Entry points: `main.py` (repository root, adds `backend/` to `sys.path`) → `backend/app/main.py` (application factory).

## Layers

```mermaid
flowchart TB
  subgraph HTTP["app/api/v1 (routers)"]
    AUTH[auth] --- REPO[repositories] --- CHAT[chat] --- AN["analysis/{explain,bugs,tests,review,history}"]
    GHR["github + integrations/github/routes (/source/*)"] --- ISS[issues] --- MEM[memories] --- TASKS[tasks] --- EVT[events] --- MCP[mcp_registry] --- HL[health]
  end
  subgraph SVC["app/services"]
    ORCH["explanation / bug_detection / test_generation / code_review orchestrators"]
    TEO["task_execution_orchestrator, task_recovery, tool_approval_gate, mcp_elicitation_service"]
    HIST["*_history_service, analysis_run_history_service"]
    SYNC["repository_sync, sync_worker, webhook_worker, webhook_handlers"]
    PUB["git_branch, independent_verifier, review_publication_service"]
    MEMS["memory_service, sse_redis_streams"]
  end
  subgraph DATA["app/repositories + app/models"]
    REPOS["Repository, Task (approvals/core/executions/plans/publication), Analysis (core/bug_scans/explanations/reviews/test_generation/retention), chunk, symbol, edge, memory, webhook_event, user, installation, pull_request"]
  end
  subgraph AI["backend/ai"]
    GW[llm.client.LLMGateway] --- RAG[pipeline.RAGPipeline] --- AGT[agent.AgentOrchestrator] --- CTX[context/*] --- AISVC["services/* (planner, localizer, edit/repair synthesizers, verifiers, engines)"] --- WF[workflows/autonomous_task_workflow] --- SEC["security (provenance, taint)"]
  end
  SBX["sandbox/*"] --- TOOLS["agent/tools/*"] --- SCN["scanner/*, review/static_reviewer"] --- IDX["indexer/*"]
  HTTP --> SVC --> DATA
  SVC --> AI
  TEO --> SBX & TOOLS
  ORCH --> SCN
  SYNC --> IDX & SCN
  CHAT --> RAG & AGT
```

## Application lifecycle (`app/core/lifespan.py`)

On startup the lifespan:

1. Configures logging (JSON formatter with request/trace ids, secret-redacting filter) and OpenTelemetry (if enabled).
2. Builds shared services on `app.state`: LLM gateway (primary + fallback provider, concurrency semaphore), embedding service, retrieval pipeline (vector, lexical, fusion, reranker from `create_reranker()`, optional `SymbolGraphExpander`, two-level cache), RAG pipeline, agent orchestrator.
3. Validates that required prompt templates exist.
4. Runs startup reconciliation (unless `RUN_STARTUP_RECONCILIATION=false`): stale sync jobs, interrupted tasks, orphaned workspaces.
5. Starts the embedded webhook worker loop (unless `DISABLE_EMBEDDED_WEBHOOK_WORKER`) and the embedded sync worker loop (unless `DISABLE_EMBEDDED_SYNC_WORKER`, which defaults to `true` in production).
6. On shutdown, drains Redis connection pools and stops loops.

## Configuration

`app/core/config.py` (`pydantic-settings`) is the single settings source. In production (`APP_ENV=production`) validation fails startup when: `JWT_SECRET` is shorter than 32 characters, has fewer than 12 distinct characters or matches a known dummy value; `ENABLE_DEV_LOGIN` is true; `COOKIE_SECURE` is false; CORS origins are empty or contain localhost; `CORS_ORIGIN_REGEX` is a wildcard or not anchored with `^…$`; JWT issuer/audience are empty. See [Environment configuration](../07-deployment/ENVIRONMENT_CONFIGURATION.md).

## Persistence

- SQLAlchemy 2 models in `app/models`; sync sessions (`get_db`) and an async engine for AI retrieval.
- Pool sizes are chosen per service role (`_get_role_pool_size` in `app/core/database.py`).
- Data access is organised as repository classes; the task and analysis repositories are split into aggregate mixins (`app/repositories/task/*`, `app/repositories/analysis/*`).
- Migrations: Alembic, single linear chain, 20 revisions. See [Database architecture](DATABASE_ARCHITECTURE.md).

## Redis usage (`app/core/redis.py`)

Thread/coroutine-safe singleton clients with bounded pools (`REDIS_MAX_CONNECTIONS`, default 50) and retry with backoff. Used for: JWT blocklist, OAuth state, rate limits, sync job queue and worker heartbeats/locks, retrieval and embedding caches, SSE streams, installation token cache.

## Scanner and indexer pipeline

```mermaid
flowchart LR
  CL["Clone (installation token)"] --> WK["walker: ignore rules,<br/>binary/size filters"] --> DT["detector: language"]
  DT --> PR["parser: tree-sitter<br/>(language pack) + CST fallback"]
  PR --> EX["extractor: symbols"] --> IM["import_tracker"] --> GR["graph: edges with provenance<br/>and resolution status"]
  GR --> RK["symbol_ranker: PageRank importance"]
  PR --> CH["indexer.chunker: symbol-aware chunks<br/>split &gt;512 tokens, merge small siblings"]
  CH --> INC["indexer.incremental: content-hash skip,<br/>batched inserts, index generation"]
  INC --> EMB["embedding service (Gemini, 768-d)"] --> DB[("code_chunks: embedding,<br/>code_search_text")]
```

## Static analysis integrations

| Tool | Used by | Availability |
|---|---|---|
| ruff, bandit | Static reviewer, static bug scanner | Installed from `requirements-dev.txt`; not in the production image |
| eslint, biome | Static reviewer (JS/TS) | Invoked with `npx --no-install`; only if present in the analysed repository/host |
| Semgrep CE, OSV-Scanner, Gitleaks, SCIP | Bug detection / verification | Optional binaries; results report when a scanner is unavailable |
| Built-in AST rules, taint analyzer, multi-language security scanner | Bug detection | Always available (pure Python) |

Scanner invocations are batched per scanner (one process per scanner, not per file), run concurrently, prefix targets with `--`, and use a minimal environment.

## Key cross-cutting rules

- **Single LLM entry point:** all inference goes through `LLMGateway`.
- **Prompt separation:** system prompts contain instructions only; repository content is rendered as delimited, untrusted data.
- **Redaction:** responses, logs, checkpoints and persisted payloads pass through `app/core/secret_redaction.py`.
- **Ownership:** every repository/task route resolves ownership before acting.
