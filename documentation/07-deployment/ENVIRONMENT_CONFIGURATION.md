# Environment Configuration

All backend settings are read by `backend/app/core/config.py` (`pydantic-settings`) from environment variables or `.env`. Variable names are the upper-case field names. Templates: `.env.example` (local) and `.env.production.example` (production). Never commit real values.

## Production rules (enforced at startup when `APP_ENV=production`)

| Rule | Failure |
|---|---|
| `JWT_SECRET` ≥ 32 characters, ≥ 12 distinct characters, not a known dummy value | Startup error |
| `ENABLE_DEV_LOGIN=false` | Startup error |
| `COOKIE_SECURE=true` | Startup error |
| `CORS_ALLOWED_ORIGINS` non-empty and without localhost | Startup error |
| `CORS_ORIGIN_REGEX` not a wildcard and anchored `^…$` | Startup error |
| `JWT_ISSUER`, `JWT_AUDIENCE` non-empty | Startup error |
| `DISABLE_EMBEDDED_SYNC_WORKER` defaults to `true` unless set explicitly | Behaviour change |
| `SANDBOX_BACKEND=local` refused by the sandbox factory | Execution error |

## Cookie topology

- SPA served by Vercel with `/api/*` rewritten to the API: requests are same-origin from the browser's perspective; `COOKIE_SAMESITE=lax` works.
- SPA calling the API host directly (cross-site): use `COOKIE_SAMESITE=none` with `COOKIE_SECURE=true`, and list the SPA origin in `CORS_ALLOWED_ORIGINS`.

## Frontend (build-time)

| Variable | Purpose |
|---|---|
| `VITE_API_BASE_URL` | API base URL (default `/api/v1`) |
| `VITE_GITHUB_APP_SLUG`, `VITE_GITHUB_APP_INSTALLATION_URL` | GitHub App install link |
| `VITE_ENABLE_MSW` | `false` in production |
| `VITE_DEV_LOGIN` | Show developer login (development only) |

## Process-level variables (`startup.sh`, Docker)

| Variable | Purpose |
|---|---|
| `SERVICE_ROLE` | `api` (default), `sync_worker`/`worker`, `webhook_worker`, `runner`, `migrate` |
| `PORT`, `WEBSITES_PORT` | Listen port (Azure's `WEBSITES_PORT` wins) |
| `FORWARDED_ALLOW_IPS` | Trusted proxy addresses when `TRUST_PROXY_HEADERS=true` |

## Backend settings (all 150 fields)

### Application

| Variable | Type | Default | Secret |
|---|---|---|---|
| `APP_NAME` | `str` | `'Agentic Software Engineering Platform'` |  |
| `APP_VERSION` | `str` | `'1.0.0'` |  |
| `APP_ENV` | `str` | `'development'` |  |
| `API_V1_PREFIX` | `str` | `'/api/v1'` |  |
| `LOG_LEVEL` | `str` | `'INFO'` |  |
| `RUN_STARTUP_RECONCILIATION` | `bool` | `True` |  |
| `RUN_MIGRATIONS_ON_STARTUP` | `bool` | `True` |  |
| `UVICORN_GRACEFUL_TIMEOUT` | `int` | `15` |  |

### Database

| Variable | Type | Default | Secret |
|---|---|---|---|
| `DATABASE_URL` | `str` | `'postgresql+psycopg://platform:platform@localhost:5433/agent_platform'` |  |
| `DB_POOL_SIZE` | `int` | `20` |  |
| `DB_MAX_OVERFLOW` | `int` | `10` |  |
| `DB_POOL_TIMEOUT` | `int` | `30` |  |
| `DB_POOL_RECYCLE` | `int` | `1800` |  |

### Redis

| Variable | Type | Default | Secret |
|---|---|---|---|
| `REDIS_URL` | `str` | `'redis://localhost:6379/0'` |  |
| `REDIS_MAX_CONNECTIONS` | `int` | `50` |  |
| `REDIS_CONNECTION_TIMEOUT` | `float` | `5.0` |  |
| `REDIS_SOCKET_TIMEOUT` | `float` | `10.0` |  |
| `REDIS_HEALTH_CHECK_INTERVAL` | `int` | `30` |  |
| `REDIS_RETRY_ON_TIMEOUT` | `bool` | `True` |  |

### Context budgets

| Variable | Type | Default | Secret |
|---|---|---|---|
| `CONTEXT_BUDGET_EXPLAIN` | `int` | `4000` |  |
| `CONTEXT_BUDGET_BUGS` | `int` | `6000` |  |
| `CONTEXT_BUDGET_TESTS` | `int` | `6000` |  |
| `CONTEXT_BUDGET_REVIEW` | `int` | `8000` |  |

### GitHub

| Variable | Type | Default | Secret |
|---|---|---|---|
| `GITHUB_APP_ID` | `str \| None` | `None` |  |
| `GITHUB_APP_PRIVATE_KEY` | `str \| None` | `None` | yes |
| `GITHUB_CLIENT_ID` | `str \| None` | `None` |  |
| `GITHUB_CLIENT_SECRET` | `str \| None` | `None` | yes |
| `GITHUB_WEBHOOK_SECRET` | `str \| None` | `None` | yes |
| `GITHUB_WORKSPACE_ROOT` | `str \| None` | `None` |  |
| `GITHUB_OAUTH_REDIRECT_URI` | `str` | `'http://localhost:8000/api/v1/auth/github/callback'` |  |

### Authentication and cookies

| Variable | Type | Default | Secret |
|---|---|---|---|
| `JWT_SECRET` | `str \| None` | `None` | yes |
| `JWT_ALGORITHM` | `str` | `'HS256'` |  |
| `JWT_EXPIRE_MINUTES` | `int` | `15` |  |
| `JWT_REFRESH_EXPIRE_DAYS` | `int` | `7` |  |
| `REFRESH_COOKIE_NAME` | `str` | `'refresh_token'` |  |
| `JWT_ISSUER` | `str` | `'agent-platform'` |  |
| `JWT_AUDIENCE` | `str` | `'agent-platform-web'` |  |
| `AUTH_COOKIE_NAME` | `str` | `'access_token'` |  |
| `COOKIE_SECURE` | `bool` | `False` |  |
| `COOKIE_SAMESITE` | `str \| None` | `None` |  |
| `ENABLE_DEV_LOGIN` | `bool` | `False` |  |

### AI providers and embeddings

| Variable | Type | Default | Secret |
|---|---|---|---|
| `AI_PRIMARY_PROVIDER` | `str` | `'gemini'` |  |
| `AI_FALLBACK_PROVIDER` | `str \| None` | `'groq'` |  |
| `GEMINI_API_KEY` | `str \| None` | `None` | yes |
| `GEMINI_API_KEYS` | `str \| None` | `None` | yes |
| `GEMINI_CHAT_MODEL` | `str` | `'gemini-flash-lite-latest'` |  |
| `GROQ_API_KEY` | `str \| None` | `None` | yes |
| `GROQ_API_KEYS` | `str \| None` | `None` | yes |
| `GROQ_CHAT_MODEL` | `str` | `'openai/gpt-oss-120b'` |  |
| `AI_EMBEDDING_PROVIDER` | `str` | `'gemini'` |  |
| `GEMINI_EMBEDDING_MODEL` | `str` | `'gemini-embedding-001'` |  |
| `EMBEDDING_DIMENSIONS` | `int` | `768` |  |
| `EMBEDDING_PROFILE_VERSION` | `str` | `'v2'` |  |
| `EMBEDDING_DOCUMENT_TASK_TYPE` | `str` | `'RETRIEVAL_DOCUMENT'` |  |
| `EMBEDDING_QUERY_TASK_TYPE` | `str` | `'CODE_RETRIEVAL_QUERY'` |  |
| `ALLOW_LOCAL_EMBEDDINGS` | `bool` | `False` |  |
| `AI_REQUEST_TIMEOUT_SECONDS` | `float` | `30.0` |  |
| `AI_MAX_RETRIES` | `int` | `3` |  |
| `AI_MAX_OUTPUT_TOKENS` | `int` | `2048` |  |
| `AI_TEMPERATURE_DEFAULT` | `float` | `0.2` |  |
| `AI_MAX_CONTEXT_TOKENS` | `int` | `100000` |  |
| `AI_MAX_REPAIR_ATTEMPTS` | `int` | `2` |  |
| `AI_MAX_CONCURRENT_CALLS` | `int` | `10` |  |
| `EMBEDDING_MAX_REQUESTS_PER_MINUTE` | `int` | `120` |  |
| `EMBEDDING_MAX_CONCURRENCY` | `int` | `5` |  |

### Agentic chat

| Variable | Type | Default | Secret |
|---|---|---|---|
| `AGENTIC_CHAT_ENABLED` | `bool` | `True` |  |
| `AGENT_PRIMARY_PROVIDER` | `str` | `'gemini'` |  |
| `AGENT_MODEL` | `str` | `'gemini-flash-lite-latest'` |  |
| `AGENT_FALLBACK_ENABLED` | `bool` | `True` |  |
| `AGENT_FALLBACK_PROVIDER` | `str \| None` | `'groq'` |  |
| `AGENT_MAX_ROUNDS` | `int` | `3` |  |
| `AGENT_MAX_TOOL_CALLS` | `int` | `6` |  |
| `AGENT_MAX_MODEL_CALLS` | `int` | `4` |  |
| `AGENT_MAX_PARALLEL_TOOL_CALLS` | `int` | `2` |  |
| `AGENT_MAX_INPUT_TOKENS` | `int` | `12000` |  |
| `AGENT_MAX_OUTPUT_TOKENS` | `int` | `2000` |  |
| `AGENT_MAX_REQUEST_SECONDS` | `float` | `35.0` |  |
| `AGENT_TOOL_TIMEOUT_SECONDS` | `float` | `5.0` |  |
| `AGENT_MAX_TOOL_RESULT_BYTES` | `int` | `8192` |  |
| `AGENT_MAX_TOTAL_EVIDENCE_BYTES` | `int` | `24576` |  |

### Retrieval

| Variable | Type | Default | Secret |
|---|---|---|---|
| `RETRIEVAL_HNSW_ENABLED` | `bool` | `True` |  |
| `RETRIEVAL_HNSW_EXACT_EF_SEARCH` | `int` | `40` |  |
| `RETRIEVAL_HNSW_NORMAL_EF_SEARCH` | `int` | `64` |  |
| `RETRIEVAL_HNSW_COMPLEX_EF_SEARCH` | `int` | `120` |  |
| `RETRIEVAL_HNSW_ITERATIVE_SCAN` | `str` | `'relaxed_order'` |  |
| `RETRIEVAL_CACHE_ENABLED` | `bool` | `True` |  |
| `RETRIEVAL_REDIS_CACHE_ENABLED` | `bool` | `True` |  |
| `RETRIEVAL_CACHE_TTL_SECONDS` | `int` | `300` |  |
| `RETRIEVAL_CACHE_MAX_LOCAL_ENTRIES` | `int` | `1000` |  |
| `RETRIEVAL_CACHE_MAX_PAYLOAD_BYTES` | `int` | `500000` |  |
| `RETRIEVAL_CODE_LEXICAL_ENABLED` | `bool` | `True` |  |
| `RETRIEVAL_GRAPH_EXPANSION_ENABLED` | `bool` | `True` |  |
| `RETRIEVAL_GRAPH_MAX_SEEDS` | `int` | `5` |  |
| `RETRIEVAL_GRAPH_MAX_HOPS` | `int` | `1` |  |
| `RETRIEVAL_GRAPH_MAX_NEIGHBORS_PER_SEED` | `int` | `10` |  |
| `RETRIEVAL_GRAPH_MAX_CANDIDATES` | `int` | `30` |  |
| `RETRIEVAL_INTENT_ROUTING_ENABLED` | `bool` | `True` |  |
| `RERANKER_BACKEND` | `str` | `'pytorch'` |  |
| `RERANKER_ONNX_ENABLED` | `bool` | `False` |  |
| `RERANKER_ONNX_MODEL_PATH` | `str \| None` | `None` |  |
| `RERANKER_QUANTIZATION` | `str` | `'none'` |  |

### Observability

| Variable | Type | Default | Secret |
|---|---|---|---|
| `OTEL_ENABLED` | `bool` | `False` |  |
| `OTEL_SERVICE_NAME` | `str` | `'ai-dev-platform'` |  |
| `OTEL_SERVICE_VERSION` | `str` | `'1.0.0'` |  |
| `OTEL_ENVIRONMENT` | `str` | `'development'` |  |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | `str \| None` | `None` |  |
| `OTEL_EXPORTER_OTLP_HEADERS` | `str \| None` | `None` |  |
| `OTEL_TRACES_EXPORTER` | `str` | `'none'` |  |
| `OTEL_METRICS_ENABLED` | `bool` | `False` |  |
| `OTEL_TRACE_SAMPLE_RATE` | `float` | `1.0` |  |
| `LANGFUSE_ENABLED` | `bool` | `False` |  |
| `LANGFUSE_PUBLIC_KEY` | `str \| None` | `None` | yes |
| `LANGFUSE_SECRET_KEY` | `str \| None` | `None` | yes |
| `LANGFUSE_BASE_URL` | `str` | `'https://cloud.langfuse.com'` |  |
| `OBSERVABILITY_CAPTURE_PROMPTS` | `bool` | `False` |  |
| `OBSERVABILITY_CAPTURE_RESPONSES` | `bool` | `False` |  |

### API security and workers

| Variable | Type | Default | Secret |
|---|---|---|---|
| `CORS_ALLOWED_ORIGINS` | `str` | `'http://localhost:5173,http://127.0.0.1:5173,http://localhost:5174,…` |  |
| `CORS_ORIGIN_REGEX` | `str \| None` | `None` |  |
| `FRONTEND_URL` | `str \| None` | `None` |  |
| `RATE_LIMIT_ENABLED` | `bool` | `True` |  |
| `TRUST_PROXY_HEADERS` | `bool` | `False` |  |
| `DISABLE_EMBEDDED_SYNC_WORKER` | `bool` | `False` |  |
| `DISABLE_EMBEDDED_WEBHOOK_WORKER` | `bool` | `False` |  |
| `ALLOW_MOCK_GIT_PUSH` | `bool` | `False` |  |
| `SYNC_WORKER_LEASE_TTL_SECONDS` | `int` | `60` |  |
| `SYNC_WORKER_HEARTBEAT_INTERVAL_SECONDS` | `int` | `15` |  |
| `SYNC_WORKER_MAX_RETRIES` | `int` | `3` |  |
| `SYNC_WORKER_RETRY_BASE_DELAY_SECONDS` | `float` | `2.0` |  |
| `SYNC_WORKER_REPO_LOCK_TTL_SECONDS` | `int` | `120` |  |
| `RETENTION_PURGE_INTERVAL_SECONDS` | `float` | `3600.0` |  |
| `RETENTION_DAYS` | `int` | `30` |  |

### Sandbox and runner

| Variable | Type | Default | Secret |
|---|---|---|---|
| `SANDBOX_BACKEND` | `str` | `'local'` |  |
| `RUNNER_BASE_URL` | `str \| None` | `None` |  |
| `RUNNER_AUTH_SECRET` | `str \| None` | `None` | yes |
| `RUNNER_REQUEST_TIMEOUT` | `float` | `60.0` |  |
| `RUNNER_ALLOW_UNAUTHENTICATED_DEV` | `bool` | `False` |  |
| `SANDBOX_CPU_LIMIT` | `float` | `2.0` |  |
| `SANDBOX_MEMORY_LIMIT` | `str` | `'4g'` |  |
| `SANDBOX_PID_LIMIT` | `int` | `512` |  |
| `SANDBOX_DISK_LIMIT_MB` | `int` | `500` |  |
| `SANDBOX_FILE_LIMIT_MB` | `int` | `5` |  |
| `SANDBOX_OUTPUT_LIMIT_BYTES` | `int` | `102400` |  |
| `SANDBOX_DEFAULT_TIMEOUT` | `int` | `30` |  |
| `SANDBOX_MAX_LIFETIME` | `int` | `3600` |  |
| `SANDBOX_IDLE_TIMEOUT` | `int` | `600` |  |
| `SANDBOX_MAX_CONCURRENT_TASKS` | `int` | `5` |  |
| `SANDBOX_RUNTIME` | `str` | `'runc'` |  |
| `SANDBOX_PYTHON_IMAGE` | `str` | `'python:3.12-slim'` |  |
| `SANDBOX_NODE_IMAGE` | `str` | `'node:20-slim'` |  |
| `SANDBOX_USE_GVISOR` | `bool` | `True` |  |
