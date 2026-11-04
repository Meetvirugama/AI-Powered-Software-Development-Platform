# Cloud Deployment Guide: Vercel, Azure, Upstash & Supabase

This guide provides end-to-end instructions for deploying the **AI-Powered Software Development Platform** across a modern cloud stack:

| Component | Cloud Provider | Technology |
|---|---|---|
| **Frontend** | [Vercel](https://vercel.com) | React 18, Vite, TypeScript, Tailwind CSS, SPA Router |
| **Backend API** | [Azure App Service](https://azure.microsoft.com/products/app-service) | FastAPI, Uvicorn, Python 3.11, Docker / Linux App Service |
| **Cache & Task Queue** | [Upstash](https://upstash.com) | Serverless Redis over TLS (`rediss://`) |
| **Database & Vector Store**| [Supabase](https://supabase.com) | PostgreSQL 15+, `pgvector`, Connection Pooler (Supavisor) |

---

## 1. Supabase Setup (PostgreSQL & pgvector)

1. Create a project at [Supabase](https://supabase.com).
2. Go to **Database** $\rightarrow$ **Extensions** and ensure `vector` is enabled (the platform's Alembic migrations also execute `CREATE EXTENSION IF NOT EXISTS vector;` automatically).
3. Under **Project Settings** $\rightarrow$ **Database**, find your connection string:
   - **Session Pooler (Port 5432)** or **Direct Connection**:
     ```text
     postgresql+psycopg://postgres.[project-ref]:[password]@aws-0-[region].pooler.supabase.com:5432/postgres?sslmode=require
     ```
   - **Transaction Pooler (Port 6543 / Supavisor)**:
     ```text
     postgresql+psycopg://postgres.[project-ref]:[password]@aws-0-[region].pooler.supabase.com:6543/postgres?sslmode=require
     ```
     > [!TIP]
     > The backend automatically detects port `6543` and configures `prepare_threshold=None` to avoid prepared statement collisions in transaction pooling mode.

---

## 2. Upstash Setup (Serverless Redis)

1. Create a Redis database at [Upstash Console](https://console.upstash.com).
2. Select your nearest region to Azure.
3. In the database overview, copy the **`rediss://`** connection string (under the *Node / Python / General* connection tab):
   ```text
   rediss://default:[YOUR_TOKEN]@[YOUR_ENDPOINT].upstash.io:6379
   ```
   > [!IMPORTANT]
   > Ensure the scheme is `rediss://` (Redis over TLS). The platform automatically enables connection health checks (`health_check_interval=30`) and auto-reconnection (`retry_on_timeout=True`) to handle serverless idle dropouts.

---

## 3. Azure App Service Setup (Backend API)

You can deploy the backend to Azure App Service as Python code (via GitHub Actions or Git) or as a container (using the root `Dockerfile`).

### A. Environment Configuration in Azure
In the Azure Portal, navigate to **Your Web App** $\rightarrow$ **Configuration** $\rightarrow$ **Application settings**, and configure:

| Key | Example Value | Description |
|---|---|---|
| `APP_ENV` | `production` | Enables strict production security guards |
| `DATABASE_URL` | `postgresql+psycopg://postgres.[ref]:[pass]@[host]:6543/postgres?sslmode=require` | Supabase connection string |
| `REDIS_URL` | `rediss://default:[token]@[host].upstash.io:6379` | Upstash TLS Redis connection string |
| `JWT_SECRET` | *(64-character random hex string)* | Generate with `openssl rand -hex 32` |
| `FRONTEND_URL` | `https://your-platform.vercel.app` | Your Vercel frontend domain |
| `CORS_ALLOWED_ORIGINS` | `https://your-platform.vercel.app` | Permitted browser origins |
| `CORS_ORIGIN_REGEX` | `https://.*\.vercel\.app` | Permitted preview deployments |
| `COOKIE_SECURE` | `true` | Required for HTTPS and cross-site cookies |
| `COOKIE_SAMESITE` | `none` | Required for cross-site auth cookies from Vercel |
| `TRUST_PROXY_HEADERS` | `true` | Trusts Azure ARR reverse proxy headers |
| `GITHUB_APP_ID` | `123456` | GitHub App ID |
| `GITHUB_CLIENT_ID` | `Iv23...` | GitHub Client ID |
| `GITHUB_CLIENT_SECRET` | `...` | GitHub Client Secret |
| `GITHUB_WEBHOOK_SECRET`| `...` | GitHub Webhook secret |
| `GITHUB_APP_PRIVATE_KEY` | `"-----BEGIN RSA PRIVATE KEY-----\n...\n-----END RSA PRIVATE KEY-----"` | Escaped PEM key |
| `GITHUB_OAUTH_REDIRECT_URI` | `https://<your-azure-app>.azurewebsites.net/api/v1/auth/github/callback` | OAuth callback |
| `GEMINI_API_KEY` | `AIzaSy...` | Google Gemini API key |
| `PORT` | `8000` | Port (Azure automatically sets `WEBSITES_PORT`) |

### B. Startup Command
If using the Azure Linux Python runtime (non-container), set the **Startup Command** under **Configuration** $\rightarrow$ **General settings**:
```bash
/home/site/wwwroot/startup.sh
```

---

## 4. Vercel Setup (Frontend)

### Option A: Import GitHub Repository (Recommended)
1. Go to [Vercel](https://vercel.com) and click **Add New** $\rightarrow$ **Project**.
2. Import your GitHub repository:
   - If Root Directory is left as `.`, Vercel uses the root [`vercel.json`](file:///Users/meetvirugama/Desktop/AI-Powered-Software-Development-Platform/vercel.json).
   - If Root Directory is set to `frontend`, Vercel uses [`frontend/vercel.json`](file:///Users/meetvirugama/Desktop/AI-Powered-Software-Development-Platform/frontend/vercel.json).
3. Under **Environment Variables**, add:
   ```env
   VITE_API_BASE_URL=https://<your-azure-app>.azurewebsites.net/api/v1
   VITE_GITHUB_APP_SLUG=your-github-app-slug
   VITE_ENABLE_MSW=false
   ```
4. Click **Deploy**.

---

## 5. GitHub App Configuration

In your GitHub App settings at [GitHub Developer Settings](https://github.com/settings/apps):

1. **Homepage URL**:
   `https://your-platform.vercel.app`
2. **User authorization callback URL**:
   `https://<your-azure-app>.azurewebsites.net/api/v1/auth/github/callback`
3. **Webhook URL**:
   `https://<your-azure-app>.azurewebsites.net/api/v1/github/webhook`
4. **Permissions**:
   - Repository:
     - `Contents`: Read & Write
     - `Issues`: Read & Write
     - `Pull requests`: Read & Write
     - `Metadata`: Read-only

---

## 6. Verification Checklist

After deploying all 4 services:

- [ ] Check backend health: `https://<your-azure-app>.azurewebsites.net/api/v1/health` returns `HTTP 200` with `status: "healthy"`.
- [ ] Verify Supabase migrations: Inspect Supabase Table Editor and verify all 14 tables are present.
- [ ] Open frontend on Vercel: `https://your-platform.vercel.app/login`.
- [ ] Click **Sign in with GitHub**: Completes OAuth flow, sets cookie, and redirects to `/app/dashboard`.
- [ ] Run an AI Code Analysis: Verify response is returned without CORS or timeout errors.
