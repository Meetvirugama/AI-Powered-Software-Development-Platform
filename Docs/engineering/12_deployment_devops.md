# 12. Deployment & DevOps
> **Version:** 1.0 | **Created:** 2026-09-24 | **Last Updated:** 2026-09-24 | **Status:** Development Only

---

## Current Environment

**Environment:** Local development only (no staging or production environment configured)

---

## Local Development Setup

### Prerequisites
- Python 3.11+
- Docker + Docker Compose
- Node.js (for frontend)

### Backend Setup

```bash
# 1. Copy env file
cp .env.example .env
# Edit .env: add JWT_SECRET, OpenAI API key, GitHub App credentials

# 2. Create virtual environment
python -m venv .venv
source .venv/bin/activate

# 3. Install backend dependencies
pip install -r backend/requirements.txt

# 4. Start infrastructure (PostgreSQL + Redis)
docker compose up -d

# 5. Run database migrations (when Om's migrations are ready)
cd backend
alembic upgrade head

# 6. Start backend dev server
uvicorn app.main:app --reload
```

**Backend URL:** `http://127.0.0.1:8000`
**Health check:** `http://127.0.0.1:8000/api/v1/health`
**API docs:** `http://127.0.0.1:8000/docs`

### Frontend Setup

```bash
cd frontend
npm install
npm run dev
```

**Frontend URL:** `http://localhost:5173`

---

## Docker Compose Services

Defined in [`docker-compose.yml`](file:///Users/meetvirugama/Desktop/AI-Powered-Software-Development-Platform/docker-compose.yml):

| Service | Image | Port | Volume | Health Check |
|---|---|---|---|---|
| `postgres` | `pgvector/pgvector:pg15` | 5432 | `postgres_data` | `pg_isready -U platform -d agent_platform` |
| `redis` | `redis:7-alpine` | 6379 | `redis_data` | `redis-cli ping` |

**Database credentials (dev only):**
- DB: `agent_platform`
- User: `platform`
- Password: `platform`

---

## Environment Configuration

All configuration loaded via `pydantic-settings` from `.env` file.

Source: [`backend/app/core/config.py`](file:///Users/meetvirugama/Desktop/AI-Powered-Software-Development-Platform/backend/app/core/config.py)

| Variable | Required | Default | Description |
|---|---|---|---|
| `APP_ENV` | No | `development` | Environment name |
| `LOG_LEVEL` | No | `INFO` | Logging level |
| `DATABASE_URL` | No | `postgresql+psycopg://platform:platform@localhost:5432/agent_platform` | PostgreSQL connection |
| `REDIS_URL` | No | `redis://localhost:6379/0` | Redis connection |
| `GITHUB_APP_ID` | Yes (for auth) | None | GitHub App ID |
| `GITHUB_APP_PRIVATE_KEY` | Yes (for auth) | None | GitHub App private key PEM |
| `GITHUB_CLIENT_ID` | Yes (for auth) | None | GitHub OAuth client ID |
| `GITHUB_CLIENT_SECRET` | Yes (for auth) | None | GitHub OAuth client secret |
| `JWT_SECRET` | Yes (for auth) | None | JWT signing secret |
| `JWT_ALGORITHM` | No | `HS256` | JWT signing algorithm |
| `OPENAI_API_KEY` | Yes (for AI) | Read from env | OpenAI API key |

> [!CAUTION]
> Never commit `.env` or any file with real credentials. Only `.env.example` is committed.

---

## Database Migrations

**Tool:** Alembic 1.13
**Migration path:** `backend/migrations/` (TBD — directory not yet created)
**Owner:** Om (only Om creates migration files)

```bash
# Create new migration
alembic revision --autogenerate -m "description"

# Apply migrations
alembic upgrade head

# Rollback one step
alembic downgrade -1
```

**Naming convention:** `YYYYMMDD_HHMMSS_description.py`

---

## Deployment Architecture (Planned — Future)

> [!NOTE]
> No production deployment is configured. The following is aspirational/planned.

```
Production (TBD):
  Frontend → Static hosting (Vercel / Netlify / S3+CDN)
  Backend  → Container (Docker) → Cloud run or ECS
  Database → PostgreSQL managed service (RDS / Supabase)
  Redis    → Managed Redis (Elasticache / Upstash)
  Sandbox  → Docker-in-Docker or gVisor isolated containers
```

---

## CI/CD (TBD)

No CI/CD pipeline is configured. Planned:
- GitHub Actions workflow for: lint, test, build
- Coverage gate: 70% minimum
- Pre-commit hooks: detect-secrets, linting

---

## Security Baseline (DevOps)

| Control | Status |
|---|---|
| `.gitignore` blocks `.env`, `*.pem`, `*.key` | 🟢 Done |
| `.env.example` has no real values | 🟢 Done |
| `detect-secrets` pre-commit hook | ⚪ Todo (Sukun) |
| JWT secret rotation | ⚪ Todo |
| Network egress blocked in agent sandbox | ⚪ Todo |
| No direct production DB access from sandbox | ⚪ Todo |
