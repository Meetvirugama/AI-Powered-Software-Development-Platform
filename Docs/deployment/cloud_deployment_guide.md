# Cloud Production Deployment & Operations Guide

This guide documents the production architecture, environment configuration, CI/CD secrets, database migration workflow, health verification, rollback steps, and troubleshooting for the **AI-Powered Software Development Platform** across **Vercel**, **Azure App Service**, **Supabase (PostgreSQL + pgvector)**, **Upstash (Redis)**, and **GitHub Actions**.

---

## 1. Production Architecture

| Tier | Service / Runtime | Role | Configuration Files |
| :--- | :--- | :--- | :--- |
| **Frontend (SPA)** | Vercel (`React 19`, TypeScript, Vite, Tailwind CSS, Zustand) | Static SPA delivery, CDN, security headers, optional `/api/:path*` rewrite | [`vercel.json`](../../vercel.json), [`frontend/vercel.json`](../../frontend/vercel.json), [`frontend/vite.config.ts`](../../frontend/vite.config.ts) |
| **Backend (API + SSE)** | Azure App Service for Linux (`Python 3.11+`, FastAPI, Uvicorn, Pydantic v2) | REST APIs, GitHub OAuth & App webhooks, SSE streams, Retrieval/RAG, Agent Orchestrator | [`Dockerfile`](../../Dockerfile), [`startup.sh`](../../startup.sh), [`main.py`](../../main.py), [`backend/app/core/config.py`](../../backend/app/core/config.py) |
| **Database** | Supabase Managed PostgreSQL (`SQLAlchemy 2.0 Async`, `psycopg3`, `pgvector`, HNSW + FTS) | Core relational persistence, vector embeddings (`768` dims), full-text search | [`backend/app/core/database.py`](../../backend/app/core/database.py), [`backend/alembic.ini`](../../backend/alembic.ini) |
| **Cache & Event Bus** | Upstash Managed Redis (`rediss://` TLS) | Rate limiting, repository sync state, SSE event stream pub/sub, caching | [`backend/app/core/redis.py`](../../backend/app/core/redis.py) |
| **CI/CD** | GitHub Actions (`OIDC` -> Azure App Service, artifact packaging, smoke checks) | Lint, typecheck, security gate, backend/frontend tests, Azure deployment & verification | [`.github/workflows/main_ai-powered-dev-platform-api.yml`](../../.github/workflows/main_ai-powered-dev-platform-api.yml) |

---

## 2. Environment Variable Reference Matrix

Templates are maintained in [`.env.example`](../../.env.example), [`.env.production.example`](../../.env.production.example), and [`frontend/.env.example`](../../frontend/.env.example). **Never commit real credentials or secrets to Git.**

### 2.1 Backend — Runtime, Startup & Server (`Azure App Service Application Settings`)

| Variable | Purpose | Required | Service | Secret? | Example Placeholder |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `APP_ENV` | Activates production guards (fail-fast Alembic, CORS/cookie/TLS validation) | Yes | Backend | No | `production` |
| `LOG_LEVEL` | Application log verbosity | No | Backend | No | `INFO` |
| `PORT` | Fallback HTTP port inside container (`Dockerfile` default `8000`) | No | Backend | No | `8000` |
| `WEBSITES_PORT` | Azure App Service target port (takes precedence over `PORT` in `startup.sh`) | Recommended | Azure / Backend | No | `8000` |
| `RUN_MIGRATIONS_ON_STARTUP` | Runs `alembic upgrade head` in `startup.sh`; fails fast in production on error | No (`true`) | Backend | No | `true` |
| `UVICORN_GRACEFUL_TIMEOUT` | Seconds to drain SSE/in-flight HTTP connections on SIGTERM (`startup.sh`) | No (`15`) | Backend | No | `15` |
| `DISABLE_EMBEDDED_SYNC_WORKER` | Disables in-process background sync loop (`true` recommended for Azure multi-worker) | Recommended | Backend | No | `true` |

### 2.2 Backend — Database & Redis

| Variable | Purpose | Required | Service | Secret? | Example Placeholder |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `DATABASE_URL` | PostgreSQL DSN; `supabase.co`/`.com` hosts automatically get `sslmode=require` if omitted | Yes | Supabase | **Yes** | `postgresql+psycopg://postgres.[PROJECT-REF]:[PASSWORD]@aws-0-[REGION].pooler.supabase.com:6543/postgres?sslmode=require` |
| `DB_POOL_SIZE` | Base async SQLAlchemy pool size | No (`10`) | Supabase | No | `10` |
| `DB_MAX_OVERFLOW` | Overflow connections allowed under bursts | No (`5`) | Supabase | No | `5` |
| `DB_POOL_TIMEOUT` | Seconds to wait for a pooled DB connection | No (`30`) | Supabase | No | `30` |
| `DB_POOL_RECYCLE` | Connection recycle interval in seconds (keeps pooler sockets fresh) | No (`1800`) | Supabase | No | `1800` |
| `REDIS_URL` | Redis connection URL; production requires `rediss://` for Upstash/Azure Redis | Yes | Upstash | **Yes** | `rediss://default:[PASSWORD]@[ENDPOINT].upstash.io:6379` |

### 2.3 Backend — Authentication, CORS & Security

| Variable | Purpose | Required | Service | Secret? | Example Placeholder |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `JWT_SECRET` | HS256 signing key (min 32 chars; placeholder/weak strings rejected in production) | Yes | Backend | **Yes** | `<32-byte-random-hex-or-base64>` |
| `JWT_ALGORITHM` | Token signing algorithm | No (`HS256`) | Backend | No | `HS256` |
| `JWT_EXPIRE_MINUTES` | JWT session expiry in minutes | No (`60`) | Backend | No | `60` |
| `JWT_ISSUER` | Expected JWT `iss` claim | No | Backend | No | `agent-platform` |
| `JWT_AUDIENCE` | Expected JWT `aud` claim | No | Backend | No | `agent-platform-web` |
| `AUTH_COOKIE_NAME` | HttpOnly authentication cookie name | No | Backend | No | `access_token` |
| `COOKIE_SECURE` | Must be `true` in production (HTTPS-only cookies) | Yes | Backend | No | `true` |
| `COOKIE_SAMESITE` | Set `none` when Vercel frontend calls Azure backend directly (`https://`) | Yes | Backend | No | `none` |
| `FRONTEND_URL` | Canonical deployed frontend URL used for post-OAuth redirects | Yes | Backend | No | `https://[YOUR-APP].vercel.app` |
| `CORS_ALLOWED_ORIGINS` | Comma-separated allowed origins (`*` is rejected in production) | Yes | Backend | No | `https://[YOUR-APP].vercel.app` |
| `CORS_ORIGIN_REGEX` | Optional preview-branch regex (broad patterns like `.*` or `https://.*` are rejected) | No | Backend | No | `https://.*\.vercel\.app` |
| `TRUST_PROXY_HEADERS` | Enables Uvicorn `--proxy-headers` behind Azure Envoy/reverse proxy | Recommended | Backend | No | `true` |
| `RATE_LIMIT_ENABLED` | Enables Redis-backed API rate limiting | No (`true`) | Backend | No | `true` |

### 2.4 Backend — GitHub App, OAuth, AI Providers & Sandbox Runner

| Variable | Purpose | Required | Service | Secret? | Example Placeholder |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `GITHUB_APP_ID` | Numeric GitHub App ID for repository installation tokens | If using GitHub App | GitHub | No | `123456` |
| `GITHUB_APP_PRIVATE_KEY` | PEM private key (escaped `\n` supported) | If using GitHub App | GitHub | **Yes** | `"-----BEGIN RSA PRIVATE KEY-----\n...\n-----END RSA PRIVATE KEY-----"` |
| `GITHUB_CLIENT_ID` | GitHub OAuth / App Client ID | Yes (for GitHub login) | GitHub | No | `Iv1.0123456789abcdef` |
| `GITHUB_CLIENT_SECRET` | GitHub OAuth / App Client Secret | Yes (for GitHub login) | GitHub | **Yes** | `<github-client-secret>` |
| `GITHUB_WEBHOOK_SECRET` | HMAC-SHA256 secret verifying GitHub webhook payloads | Recommended | GitHub | **Yes** | `<webhook-secret>` |
| `GITHUB_OAUTH_REDIRECT_URI` | Exact callback URL registered in GitHub OAuth App settings | Yes (for GitHub login) | GitHub | No | `https://[YOUR-AZURE-APP].azurewebsites.net/api/v1/auth/github/callback` |
| `AI_PRIMARY_PROVIDER` | Primary LLM provider (`gemini` or `groq`) | No (`gemini`) | Gemini | No | `gemini` |
| `AI_FALLBACK_PROVIDER` | Secondary LLM failover provider | No (`groq`) | Groq | No | `groq` |
| `GEMINI_API_KEY` | Primary Google Gemini API key | Yes (if Gemini active) | Gemini | **Yes** | `<gemini-api-key>` |
| `GEMINI_API_KEYS` | Optional comma-separated Gemini key rotation pool | No | Gemini | **Yes** | `<key1>,<key2>` |
| `GEMINI_CHAT_MODEL` | Default Gemini chat model | No | Gemini | No | `gemini-flash-lite-latest` |
| `AI_EMBEDDING_PROVIDER` | Embedding backend (`gemini`) | No | Gemini | No | `gemini` |
| `GEMINI_EMBEDDING_MODEL` | Embedding model name | No | Gemini | No | `gemini-embedding-001` |
| `EMBEDDING_DIMENSIONS` | Vector dimension matching pgvector schema (`768`) | No (`768`) | Gemini / DB | No | `768` |
| `ALLOW_LOCAL_EMBEDDINGS` | Keeps deterministic fallback disabled in production (`false`) | No (`false`) | Backend | No | `false` |
| `GROQ_API_KEY` | Primary Groq API key | Recommended | Groq | **Yes** | `<groq-api-key>` |
| `GROQ_API_KEYS` | Optional comma-separated Groq key rotation pool | No | Groq | **Yes** | `<key1>,<key2>` |
| `GROQ_CHAT_MODEL` | Default Groq fallback chat model | No | Groq | No | `openai/gpt-oss-120b` |
| `SANDBOX_BACKEND` | Code execution isolation mode (`runner`, `docker`, or `local`) | Production: `runner` | Runner VM | No | `runner` |
| `RUNNER_BASE_URL` | Private/internal URL of remote gVisor sandbox runner VM | If `SANDBOX_BACKEND=runner` | Runner VM | No | `https://[RUNNER-PRIVATE-HOST]:8080` |
| `RUNNER_AUTH_SECRET` | Shared HMAC/Bearer secret between backend & runner VM | If `SANDBOX_BACKEND=runner` | Runner VM | **Yes** | `<32-char-runner-secret>` |
| `RUNNER_REQUEST_TIMEOUT` | HTTP timeout (seconds) for runner execution requests | No (`60.0`) | Runner VM | No | `60.0` |
| `SANDBOX_CPU_LIMIT`, `SANDBOX_MEMORY_LIMIT`, `SANDBOX_PID_LIMIT`, `SANDBOX_DISK_LIMIT_MB`, `SANDBOX_FILE_LIMIT_MB`, `SANDBOX_OUTPUT_LIMIT_BYTES`, `SANDBOX_DEFAULT_TIMEOUT`, `SANDBOX_RUNTIME`, `SANDBOX_USE_GVISOR`, `SANDBOX_PYTHON_IMAGE`, `SANDBOX_NODE_IMAGE` | Sandbox container resource quotas & gVisor runtime settings | Optional | Runner VM | No | `2.0` / `4g` / `512` / `runsc` |

### 2.5 Frontend — Vercel Build-Time Variables (`VITE_*`)

> [!CAUTION]
> Every `VITE_*` variable is compiled into client-side JavaScript during `vite build`. **Never store secrets in `VITE_*` variables.**

| Variable | Purpose | Required | Service | Secret? | Example Placeholder |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `VITE_API_BASE_URL` | Direct Azure backend API base URL (recommended in production so SSE & long AI calls bypass Vercel serverless rewrite timeouts) | Recommended | Vercel | No | `https://[YOUR-AZURE-APP].azurewebsites.net/api/v1` |
| `VITE_GITHUB_APP_SLUG` | GitHub App URL slug used when linking repository installations | Recommended | Vercel | No | `ai-powered-dev-platform` |
| `VITE_GITHUB_APP_INSTALLATION_URL` | Optional explicit GitHub App installation override URL | No | Vercel | No | `https://github.com/apps/[SLUG]/installations/new` |
| `VITE_ENABLE_MSW` | Must be `false` in production (disables Mock Service Worker) | Yes | Vercel | No | `false` |

### 2.6 GitHub Actions CI/CD Secrets & Variables

| Name | Kind | Purpose | Used In |
| :--- | :--- | :--- | :--- |
| `AZUREAPPSERVICE_CLIENTID_F1F2BA1EFA6A44DC9C67E52CC542446A` | GitHub Secret | Federated Azure Entra Application Client ID (OIDC) | `.github/workflows/main_ai-powered-dev-platform-api.yml` |
| `AZUREAPPSERVICE_TENANTID_F5CA4B1BDC3647FFBF114253AA948A4D` | GitHub Secret | Azure Entra Directory (Tenant) ID | `.github/workflows/main_ai-powered-dev-platform-api.yml` |
| `AZUREAPPSERVICE_SUBSCRIPTIONID_FBC8B15832C5410083B5503431A35776` | GitHub Secret | Target Azure Subscription ID | `.github/workflows/main_ai-powered-dev-platform-api.yml` |
| `AZURE_WEBAPP_URL` | GitHub Variable (optional) | Override base URL for post-deployment `/api/v1/health`, `/api/v1/health/ready`, and `/docs` checks | `post-deployment-verification` job |
| `DOCKER_REGISTRY_IMAGE` | GitHub Variable (optional) | Target GHCR/ACR tag if pushing built Docker image on `main` | `docker-build` job |

---

## 3. Database Provisioning & Migration Procedure (Supabase + pgvector)

1. In Supabase **SQL Editor**, verify the vector extension is enabled:
   ```sql
   CREATE EXTENSION IF NOT EXISTS vector;
   ```
2. Copy the **Connection String** from Supabase **Project Settings -> Database -> Connection String**:
   - Runtime traffic (`DATABASE_URL` on Azure): use the **Transaction Pooler** (`port 6543`, `?sslmode=require`). `backend/app/core/database.py` automatically disables `psycopg` prepared statements when `prepare_threshold=None` and forces `sslmode=require` on `supabase.co` / `supabase.com` hosts.
   - Manual schema migrations (`alembic upgrade head`): use the **Session Pooler** or direct IPv6/IPv4 host (`port 5432`) if long DDL transactions encounter Transaction Pooler restrictions.
3. Run migrations cleanly against the target database:
   ```bash
   cd backend
   alembic -c alembic.ini upgrade head
   alembic -c alembic.ini current
   ```
   Confirm Alembic reports the latest head revision (`j7a8b9c0d1e2` across all 17 revisions).
4. At Azure container boot, [`startup.sh`](../../startup.sh) executes `alembic -c backend/alembic.ini upgrade head` automatically when `RUN_MIGRATIONS_ON_STARTUP=true` and **aborts startup immediately if migrations fail in production** (`APP_ENV=production` or `prod`).

---

## 4. Backend Deployment Procedure (Azure App Service)

1. Configure all Section 2.1–2.4 variables in **Azure Portal -> App Service -> Settings -> Environment variables**.
2. Verify **Health Check Path** in **App Service -> Monitoring -> Health check** is set to `/api/v1/health/ready`.
3. Verify the GitHub Actions workflow [`.github/workflows/main_ai-powered-dev-platform-api.yml`](../../.github/workflows/main_ai-powered-dev-platform-api.yml) passes:
   - `Quality Gate` (Ruff lint, Bandit SAST, `security_gate.py`, Python syntax/import checks)
   - `Migration Check` (`alembic heads`, SQLite migration chain check, PostgreSQL 16 + `pgvector` migration verification, seeded persistence verification)
   - `Unit & Integration Tests` (`pytest` with `--cov=app --cov-fail-under=71` against PostgreSQL 16 + Redis 7)
   - `Frontend Checks` (`npm ci`, `npm run lint`, `npm test -- --run`, `npx tsc -b`, `npm run build`)
   - `Package: Build Artifacts` (Docker container build & `.zip` deploy bundle excluding dev caches)
4. Merge the PR to `main` (or run `workflow_dispatch`):
   - `deploy-to-azure` authenticates via OIDC (`azure/login@v2`) and deploys `python-app` to `ai-powered-dev-platform-api`.
   - `post-deployment-verification` polls HTTP `200` on `/api/v1/health`, `/api/v1/health/ready`, and `/docs`.

---

## 5. Frontend Deployment Procedure (Vercel)

Choose **one** project root layout in Vercel Dashboard (do not mix settings):

- **Option A — Monorepo Root Directory (default repo root `.`)**:
  - Uses root [`vercel.json`](../../vercel.json): installs & builds inside `frontend/` via `npm ci --prefix frontend && npm run build --prefix frontend` and outputs `frontend/dist`.
- **Option B — Subdirectory Root (`frontend`)**:
  - Set Vercel **Root Directory** to `frontend`. Uses [`frontend/vercel.json`](../../frontend/vercel.json) (`npm ci && npm run build`, output `dist`).

In Vercel **Project Settings -> Environment Variables (Production)**:
1. Set `VITE_API_BASE_URL=https://[YOUR-AZURE-APP].azurewebsites.net/api/v1`.
2. Set `VITE_GITHUB_APP_SLUG=<your-github-app-slug>`.
3. Set `VITE_ENABLE_MSW=false`.
4. Ensure Azure has `CORS_ALLOWED_ORIGINS=https://[YOUR-VERCEL-DOMAIN]`, `FRONTEND_URL=https://[YOUR-VERCEL-DOMAIN]`, `COOKIE_SECURE=true`, and `COOKIE_SAMESITE=none` so `withCredentials: true` cookies and `EventSource` SSE connections work cross-origin without buffering or Vercel proxy timeouts.
5. Both `vercel.json` configs enforce SPA fallback (`/(.*) -> /index.html`), `/api/:path*` proxy fallback to Azure, `X-Frame-Options: DENY`, `X-Content-Type-Options: nosniff`, `Referrer-Policy: strict-origin-when-cross-origin`, and `Strict-Transport-Security`.

---

## 6. Post-Deployment Verification Checklist

Run against your live deployment URLs after every release:

```bash
export API_URL="https://ai-powered-dev-platform-api-ehgdcmdfbseufsc6.indiasouthcentral-01.azurewebsites.net"
export APP_URL="https://[YOUR-APP].vercel.app"

# 1. Liveness (returns 200 {"status": "ok", ...})
curl -fsS "$API_URL/api/v1/health"

# 2. Readiness (verifies PostgreSQL SELECT 1 and Redis PING -> returns 200 {"status": "ready", ...})
curl -fsS "$API_URL/api/v1/health/ready"

# 3. OpenAPI / Swagger Docs
curl -fsSI "$API_URL/docs"

# 4. Frontend SPA load & asset integrity
curl -fsSI "$APP_URL"
```

Verify interactively in a browser:
1. GitHub OAuth sign-in redirects back to `FRONTEND_URL` and stores the HttpOnly `access_token` cookie (`Secure; SameSite=None`).
2. Protected endpoint `/api/v1/auth/me` returns `200`.
3. Repository indexing triggers live `text/event-stream` SSE updates on `/api/v1/events/stream`.

---

## 7. Rollback Procedure

### Backend (Azure App Service)
1. **Deployment Slots / Previous Release**: Re-run the previous green GitHub Actions run (`workflow_dispatch`) from the last stable tag/commit on `main`, or swap back the staging/production slot in **Azure Portal -> Deployment slots**.
2. **Database Schema Caution**: Do **not** blindly run `alembic downgrade` against production data without first taking a Supabase Point-in-Time Recovery (PITR) snapshot. Prefer forward-fix migrations or restoring Supabase PITR before rolling back code if a schema change dropped/altered columns.

### Frontend (Vercel)
1. Open **Vercel Dashboard -> Deployments**.
2. Select the last known working Production deployment -> **... -> Instant Rollback**. Rollback completes atomically without rebuilding.

---

## 8. Troubleshooting

| Symptom | Likely Cause | Fix |
| :--- | :--- | :--- |
| Azure container exits with `startup.sh: syntax error near unexpected token 'elif'` | Windows CRLF line endings committed in `startup.sh` | Ensure [`.gitattributes`](../../.gitattributes) enforces `*.sh text eol=lf` and run `git add --renormalize startup.sh`. |
| App starts on wrong port on Azure (`500` / health probe timeout) | `PORT` overrode `WEBSITES_PORT` | `startup.sh` now resolves `WEBSITES_PORT` first; ensure Azure App Setting `WEBSITES_PORT=8000` matches exposed port. |
| Backend crashes at startup with `ValidationError` | Invalid prod config (`JWT_SECRET` too short/placeholder, `CORS_ALLOWED_ORIGINS=*`, `CORS_ORIGIN_REGEX=.*`, non-TLS Upstash Redis URL, `COOKIE_SECURE=false`) | Inspect Azure Log Stream (`az webapp log tail`) and align settings with Section 2. |
| `401 Unauthorized` right after GitHub OAuth redirect | Cross-site cookie blocked (`COOKIE_SAMESITE=lax` between `vercel.app` and `azurewebsites.net`) | Set `COOKIE_SAMESITE=none`, `COOKIE_SECURE=true`, and exact HTTPS `CORS_ALLOWED_ORIGINS` (no trailing slash). |
| SSE stream stalls or drops after ~10–60s | Vercel serverless rewrite buffering long requests or `proxy_buffering` | Set `VITE_API_BASE_URL=https://[YOUR-AZURE-APP].azurewebsites.net/api/v1` on Vercel so `EventSource` connects directly to Azure (`X-Accel-Buffering: no`). |
| `psycopg` prepared-statement or SSL errors against Supabase | Non-TLS DSN or Transaction Pooler incompatible settings | Keep `?sslmode=require` in `DATABASE_URL`; `database.py` enforces `sslmode=require` on Supabase hosts and disables prepared statements automatically. |
