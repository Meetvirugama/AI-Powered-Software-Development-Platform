# 12. Deployment & DevOps
> **Version:** 3.0 | **Created:** 2026-09-24 | **Last Updated:** 2026-10-15 | **Status:** Live & Synchronized

---

## Current Environment

**Environment:** Local development & automated CI/testing.

---

## Local Development Setup

### Prerequisites
- Python 3.11+
- Node.js 18+ and npm
- Docker + Docker Compose

### Backend Setup

```bash
# 1. Configure environment variables
cp .env.example .env
# Edit .env: configure GEMINI_API_KEY, GROQ_API_KEY, JWT_SECRET, GitHub App keys

# 2. Set up Python virtual environment
python3 -m venv .venv
source .venv/bin/activate

# 3. Install backend dependencies
pip install -r backend/requirements.txt

# 4. Start infrastructure containers (PostgreSQL with pgvector + Redis)
docker compose up -d

# 5. Apply database migrations
cd backend
alembic upgrade head

# 6. Start the FastAPI development server
uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

- **Backend API:** `http://127.0.0.1:8000`
- **Health Check:** `http://127.0.0.1:8000/api/v1/health`
- **Interactive OpenAPI Documentation:** `http://127.0.0.1:8000/docs`

### Frontend Setup

```bash
cd frontend
npm install
npm run dev
```

- **Frontend Workbench:** `http://localhost:5173`

---

## Docker Compose Services

Configured in [`docker-compose.yml`](file:///Users/meetvirugama/Desktop/AI-Powered-Software-Development-Platform/docker-compose.yml):

| Service | Image | Exposed Port | Volume | Health Check |
|---|---|---|---|---|
| `postgres` | `pgvector/pgvector:pg15` | `5433:5432` or `5432:5432` | `postgres_data` | `pg_isready -U platform -d agent_platform` |
| `redis` | `redis:7-alpine` | `6379:6379` | `redis_data` | `redis-cli ping` |

**Database credentials (local development):**
- DB: `agent_platform`
- User: `platform`
- Password: `platform`

---

## Environment Configuration

All configuration is validated via `pydantic-settings` in [`backend/app/core/config.py`](file:///Users/meetvirugama/Desktop/AI-Powered-Software-Development-Platform/backend/app/core/config.py):

| Variable | Required | Default | Description |
|---|---|---|---|
| `APP_ENV` | No | `development` | Environment name |
| `LOG_LEVEL` | No | `INFO` | Logging level (`DEBUG`, `INFO`, `WARNING`, `ERROR`) |
| `DATABASE_URL` | No | `postgresql+psycopg://platform:platform@localhost:5433/agent_platform` | PostgreSQL connection string |
| `REDIS_URL` | No | `redis://localhost:6379/0` | Redis connection URL |
| `GITHUB_APP_ID` | Yes (for auth) | None | GitHub App numeric ID |
| `GITHUB_APP_PRIVATE_KEY` | Yes (for auth) | None | GitHub App `.pem` private key content |
| `GITHUB_CLIENT_ID` | Yes (for auth) | None | GitHub OAuth Client ID |
| `GITHUB_CLIENT_SECRET` | Yes (for auth) | None | GitHub OAuth Client Secret |
| `JWT_SECRET` | Yes (for auth) | None | Session signing secret key |
| `JWT_ALGORITHM` | No | `HS256` | JWT signing algorithm |
| `GEMINI_API_KEY` | Yes (for AI) | None | Google Gemini API key (`gemini-flash-lite-latest`) |
| `GROQ_API_KEY` | Yes (for AI) | None | Groq API key (`llama-3.3-70b-versatile`) |

> [!CAUTION]
> Real credentials must never be committed to Git. Only [`.env.example`](file:///Users/meetvirugama/Desktop/AI-Powered-Software-Development-Platform/.env.example) is committed.

---

## Database Migrations

- **Tool:** Alembic 1.13+
- **Location:** `backend/migrations/versions/` (5 migrations currently applied)
- **Owner:** Om

```bash
# Generate new migration (Om only)
cd backend
alembic revision --autogenerate -m "description_of_changes"

# Apply pending migrations
alembic upgrade head

# Rollback one migration
alembic downgrade -1
```

---

## DevOps & Security Controls

| Control | Status | Verified By |
|---|---|---|
| `.gitignore` blocks `.env`, `*.pem`, `*.key` | 🟢 Done | Sukun |
| `.secrets.baseline` + pre-commit hook active | 🟢 Done | Sukun |
| Automated backend test suite (369 tests, 71.31% coverage) | 🟢 Done | Keval |
| Automated frontend linter (`oxlint`) & production build | 🟢 Done | Dhramraj |
| Multi-tenant repository data isolation in queries | 🟢 Done | Sukun / Keval |
| Prompt-injection boundary tag enforcement | 🟢 Done | Sukun |
