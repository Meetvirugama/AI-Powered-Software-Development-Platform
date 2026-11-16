# Development Setup

## Prerequisites

| Tool | Version |
|---|---|
| Python | 3.11 (CI and Docker image use 3.11) |
| Node.js / npm | 20 (CI uses Node 20) |
| PostgreSQL with pgvector | 15+ (`docker compose` provides `pgvector/pgvector:pg15` on host port 5433) |
| Redis | 7 (`docker compose` provides `redis:7-alpine` on 6379) |
| Docker | Optional; required for the `container` sandbox backend |
| GitHub App | Required for OAuth login and repository access |
| Gemini API key | Required for chat and embeddings; Groq key optional (fallback) |

## 1. Clone and install

```bash
python3.11 -m venv .venv
.venv/bin/pip install -r backend/requirements-dev.txt     # includes backend/requirements.txt
cd frontend && npm ci && cd ..
```

## 2. Start infrastructure

```bash
docker compose up -d postgres redis      # or: make docker-up (also starts api and sync_worker containers)
```

Alternatively use managed Postgres (with pgvector) and Redis and set their URLs in `.env`.

## 3. Register a GitHub App

1. GitHub → Settings → Developer settings → GitHub Apps → New GitHub App.
2. Callback URL: `http://localhost:8000/api/v1/auth/github/callback` (must match `GITHUB_OAUTH_REDIRECT_URI`).
3. Webhook URL: a public tunnel to `http://localhost:8000/api/v1/github/webhook` (for example `ngrok http 8000`); webhook secret from `openssl rand -hex 32`.
4. Permissions: Contents (read & write), Metadata (read), Pull requests (read & write), Issues (read & write).
5. Events: Push, Pull request, Issues, Installation.
6. Generate a private key; record App ID, client ID and client secret.

## 4. Configure environment

```bash
cp .env.example .env
```

Minimum values for local development:

| Variable | Example |
|---|---|
| `DATABASE_URL` | `postgresql+psycopg://platform:platform@localhost:5433/agent_platform` |
| `REDIS_URL` | `redis://localhost:6379/0` |
| `JWT_SECRET` | 32+ random characters |
| `GITHUB_APP_ID`, `GITHUB_APP_PRIVATE_KEY`, `GITHUB_CLIENT_ID`, `GITHUB_CLIENT_SECRET`, `GITHUB_WEBHOOK_SECRET` | From the GitHub App |
| `GEMINI_API_KEY` (or `GEMINI_API_KEYS`) | Gemini key(s) |
| `GROQ_API_KEY` | Optional fallback |
| `FRONTEND_URL`, `CORS_ALLOWED_ORIGINS` | `http://localhost:5173` |
| `ENABLE_DEV_LOGIN` | `true` only if you want the local login shortcut (also set `VITE_DEV_LOGIN=true`) |

Full list: [Environment configuration](../07-deployment/ENVIRONMENT_CONFIGURATION.md).

## 5. Migrate and run

```bash
make migrate          # alembic -c backend/alembic.ini upgrade head
make run              # run_local.sh: migrations, backend :8000, frontend :5173
# or separately
make backend          # uvicorn main:app --reload --port 8000
make frontend         # vite on :5173 (proxies /api to :8000)
```

Check: `http://localhost:8000/api/v1/health/ready`, `http://localhost:8000/docs`, `http://localhost:5173`.

## 6. Optional components

| Component | How |
|---|---|
| Separate workers | `SERVICE_ROLE=sync_worker ./startup.sh`, `SERVICE_ROLE=webhook_worker ./startup.sh` (set `DISABLE_EMBEDDED_*` on the API) |
| Container sandbox | Install Docker; `SANDBOX_BACKEND=container` |
| Runner service | `SERVICE_ROLE=runner ./startup.sh` on a Docker host; API: `SANDBOX_BACKEND=runner`, `RUNNER_BASE_URL`, `RUNNER_AUTH_SECRET` |
| Static scanners | `ruff`/`bandit` come with dev requirements; install `semgrep`, `osv-scanner`, `gitleaks` binaries to enable them |
| Tracing | `OTEL_ENABLED=true`, `OTEL_TRACES_EXPORTER=otlp`, `OTEL_EXPORTER_OTLP_ENDPOINT=…`; Langfuse via `LANGFUSE_*` |
| Mock frontend | `VITE_ENABLE_MSW=true npm run dev` (no backend needed) |
| Seed data | `python backend/scripts/seed_database.py` (local databases only) |

## Troubleshooting

| Symptom | Check |
|---|---|
| Startup fails with "Production configuration error" | `APP_ENV` is `production`; satisfy the validator or use `development` locally |
| Login loops back to `/login` | Cookie settings (`COOKIE_SECURE=false` on http), `CORS_ALLOWED_ORIGINS`, callback URL |
| `503` on authenticated requests | Redis unreachable (auth fails closed) |
| Repository stays `queued` | Sync worker not running (embedded loop disabled or `SERVICE_ROLE` worker absent) |
| Chat answers without citations | Repository not indexed yet; embeddings key missing; check `/health/ready` |
| Static findings missing | Scanner binaries not installed; results report scanner availability |
