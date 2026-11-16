# Azure Deployment Checklist

> Use this checklist when setting up the AI-Powered Software Development Platform on Azure from scratch.
> Architecture: **Vercel (Frontend)** → **Azure App Service (Backend API + Sync Worker)** → **Supabase (Postgres + pgvector)** + **Upstash (Redis)**

---

## 1. Azure Resources to Create

> [!NOTE]
> All resources should be created in the same Resource Group and region for lowest latency and no egress costs.

- [ ] **Resource Group:** `ai-platform-rg` (region: **Central India** — matches existing deployment)
- [ ] **Azure Database for PostgreSQL Flexible Server**
  - Enable the `pgvector` extension: `CREATE EXTENSION IF NOT EXISTS vector;`
  - Alternatively use Supabase (already configured in `.env.production.example`)
- [ ] **Azure Cache for Redis** — Basic C1 tier minimum, TLS enabled (`rediss://`)
  - Alternatively use Upstash serverless Redis (already configured in `.env.production.example`)
- [ ] **Azure App Service Plan** — B2 or P1v3 tier (required for AI workloads with always-on workers)
- [ ] **Azure Web App: `ai-powered-dev-platform-api`**
  - OS: Linux
  - Runtime: Docker (from `Dockerfile`) or Python 3.11
  - Always-on: enabled
  - Startup command: `bash startup.sh`
- [ ] **Azure Web App: `ai-powered-dev-platform-worker`**
  - OS: Linux
  - Runtime: Python 3.11
  - Always-on: **enabled** (critical for the sync worker)
  - Startup command: `bash startup.sh`
  - App setting: `SERVICE_ROLE=sync_worker`

---

## 2. GitHub Repository Secrets Required

> [!IMPORTANT]
> These secrets enable OIDC (passwordless) authentication from GitHub Actions to Azure. Create them under **Settings → Secrets and variables → Actions**.

- [ ] `AZUREAPPSERVICE_CLIENTID_F1F2BA1EFA6A44DC9C67E52CC542446A`
- [ ] `AZUREAPPSERVICE_TENANTID_F5CA4B1BDC3647FFBF114253AA948A4D`
- [ ] `AZUREAPPSERVICE_SUBSCRIPTIONID_FBC8B15832C5410083B5503431A35776`

To get these values:
```bash
# Client ID: the app registration (service principal) used by the GitHub federated credential
az ad app list --display-name "ai-powered-dev-platform" --query "[].appId" -o tsv

# Tenant ID
az account show --query tenantId -o tsv

# Subscription ID
az account show --query id -o tsv
```

---

## 3. Azure Web App Environment Variables (Application Settings)

Set these in **Azure Portal → App Service → Configuration → Application Settings** (or via `az webapp config appsettings set`).

> [!CAUTION]
> Never commit real secrets to source control. All values marked `REPLACE_ME` must be set in Azure — not in `.env` files.

### Runtime & Application

| Setting | Value |
|---|---|
| `APP_ENV` | `production` |
| `LOG_LEVEL` | `INFO` |
| `PORT` | `8000` |
| `WEBSITES_PORT` | `8000` |
| `RUN_MIGRATIONS_ON_STARTUP` | `true` |
| `UVICORN_GRACEFUL_TIMEOUT` | `15` |
| `DISABLE_EMBEDDED_SYNC_WORKER` | `true` (API app) / `false` (worker app) |
| `SERVICE_ROLE` | _(not set on API)_ / `sync_worker` (worker app) |

### Database (Supabase / Azure PostgreSQL)

| Setting | Value |
|---|---|
| `DATABASE_URL` | `postgresql+psycopg://postgres.[PROJECT-REF]:[PASSWORD]@aws-0-[REGION].pooler.supabase.com:6543/postgres?sslmode=require` |
| `DB_POOL_SIZE` | `10` |
| `DB_MAX_OVERFLOW` | `5` |
| `DB_POOL_TIMEOUT` | `30` |
| `DB_POOL_RECYCLE` | `1800` |

### Redis (Upstash / Azure Cache for Redis)

| Setting | Value |
|---|---|
| `REDIS_URL` | `rediss://default:[PASSWORD]@[ENDPOINT].upstash.io:6379` |

### Authentication & Cookies

| Setting | Value |
|---|---|
| `JWT_SECRET` | `REPLACE_ME` — min 32 random chars: `python -c "import secrets; print(secrets.token_urlsafe(48))"` |
| `JWT_ALGORITHM` | `HS256` |
| `JWT_EXPIRE_MINUTES` | `60` |
| `JWT_ISSUER` | `agent-platform` |
| `JWT_AUDIENCE` | `agent-platform-web` |
| `AUTH_COOKIE_NAME` | `access_token` |
| `ENABLE_DEV_LOGIN` | `false` |
| `COOKIE_SECURE` | `true` |
| `COOKIE_SAMESITE` | `lax` |
| `TRUST_PROXY_HEADERS` | `true` (Azure ARR reverse proxy) |
| `RATE_LIMIT_ENABLED` | `true` |

### CORS & Frontend

| Setting | Value |
|---|---|
| `FRONTEND_URL` | `https://[YOUR-APP].vercel.app` |
| `CORS_ALLOWED_ORIGINS` | `https://[YOUR-APP].vercel.app` |
| `CORS_ORIGIN_REGEX` | `^https://[a-zA-Z0-9-]+\.vercel\.app$` |

### GitHub App Integration

| Setting | Value |
|---|---|
| `GITHUB_APP_ID` | `REPLACE_ME` |
| `GITHUB_APP_PRIVATE_KEY` | `REPLACE_ME` — full RSA private key PEM string |
| `GITHUB_CLIENT_ID` | `REPLACE_ME` |
| `GITHUB_CLIENT_SECRET` | `REPLACE_ME` |
| `GITHUB_WEBHOOK_SECRET` | `REPLACE_ME` |
| `GITHUB_OAUTH_REDIRECT_URI` | `https://ai-powered-dev-platform-api-ehgdcmdfbseufsc6.indiasouthcentral-01.azurewebsites.net/api/v1/auth/github/callback` |

### AI Providers

| Setting | Value |
|---|---|
| `AI_PRIMARY_PROVIDER` | `gemini` |
| `AI_FALLBACK_PROVIDER` | `groq` |
| `GEMINI_API_KEY` | `REPLACE_ME` |
| `GEMINI_API_KEYS` | `REPLACE_ME` (comma-separated for rotation) |
| `GEMINI_CHAT_MODEL` | `gemini-flash-lite-latest` |
| `AI_EMBEDDING_PROVIDER` | `gemini` |
| `GEMINI_EMBEDDING_MODEL` | `gemini-embedding-001` |
| `EMBEDDING_DIMENSIONS` | `768` |
| `ALLOW_LOCAL_EMBEDDINGS` | `false` |
| `GROQ_API_KEY` | `REPLACE_ME` |
| `GROQ_API_KEYS` | `REPLACE_ME` |
| `GROQ_CHAT_MODEL` | `openai/gpt-oss-120b` |

### Secure Sandbox & Runner

| Setting | Value |
|---|---|
| `SANDBOX_BACKEND` | `runner` |
| `RUNNER_BASE_URL` | `https://[YOUR-RUNNER-VM-PRIVATE-IP]:8080` |
| `RUNNER_AUTH_SECRET` | `REPLACE_ME` — 32-char random secret |
| `RUNNER_REQUEST_TIMEOUT` | `60.0` |
| `SANDBOX_CPU_LIMIT` | `2.0` |
| `SANDBOX_MEMORY_LIMIT` | `4g` |
| `SANDBOX_PID_LIMIT` | `512` |
| `SANDBOX_DISK_LIMIT_MB` | `500` |
| `SANDBOX_FILE_LIMIT_MB` | `5` |
| `SANDBOX_OUTPUT_LIMIT_BYTES` | `102400` |
| `SANDBOX_DEFAULT_TIMEOUT` | `30` |
| `SANDBOX_RUNTIME` | `runsc` |
| `SANDBOX_USE_GVISOR` | `true` |
| `SANDBOX_PYTHON_IMAGE` | `python:3.12-slim` |
| `SANDBOX_NODE_IMAGE` | `node:20-slim` |

---

## 4. Azure-Specific Startup Command

Set in **Azure App Service → Configuration → General Settings → Startup Command**:

```
bash startup.sh
```

`startup.sh` auto-detects the `SERVICE_ROLE` environment variable:
- `SERVICE_ROLE` unset or `api` → runs Uvicorn API server on `$WEBSITES_PORT`
- `SERVICE_ROLE=sync_worker` → runs `python -m app.workers.sync_worker`
- `SERVICE_ROLE=migrate` → runs Alembic migrations and exits

---

## 5. Vercel Frontend Configuration

The `vercel.json` already proxies `/api/*` to the Azure backend:

```
https://ai-powered-dev-platform-api-ehgdcmdfbseufsc6.indiasouthcentral-01.azurewebsites.net
```

Set these **environment variables in Vercel Project Settings**:

| Variable | Value |
|---|---|
| `VITE_API_BASE_URL` | _(leave blank to use `/api/v1` Vercel rewrite, recommended)_ |
| `VITE_GITHUB_APP_SLUG` | `[YOUR-GITHUB-APP-SLUG]` |
| `VITE_ENABLE_MSW` | `false` |

---

## 6. Verify Deployment

### API Health Check
```bash
curl -f https://ai-powered-dev-platform-api-ehgdcmdfbseufsc6.indiasouthcentral-01.azurewebsites.net/health
# Expected: {"status": "ok", ...}
```

### Worker App State
```bash
az webapp show \
  --name ai-powered-dev-platform-worker \
  --resource-group ai-platform-rg \
  --query "state" -o tsv
# Expected: Running
```

### Database Migration
```bash
# Run once after first deploy (or set RUN_MIGRATIONS_ON_STARTUP=true)
az webapp ssh --name ai-powered-dev-platform-api --resource-group ai-platform-rg
# Inside SSH session:
bash startup.sh migrate
```

### GitHub Webhook
```bash
# In GitHub App settings, send a ping and confirm 200 response from:
# https://ai-powered-dev-platform-api-ehgdcmdfbseufsc6.indiasouthcentral-01.azurewebsites.net/api/v1/github/webhook
```

### Logs
```bash
# Stream live logs from API
az webapp log tail --name ai-powered-dev-platform-api --resource-group ai-platform-rg

# Stream live logs from worker
az webapp log tail --name ai-powered-dev-platform-worker --resource-group ai-platform-rg
```
