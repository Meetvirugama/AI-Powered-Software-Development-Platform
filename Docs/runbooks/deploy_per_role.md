# Runbook: Deploy Per Role (API, Sync Worker, Webhook Worker, Task Worker, Runner)

## 1. Overview
The platform architecture separates execution into dedicated, independently scalable roles to prevent noisy neighbors and long-running AI/sync workloads from degrading API responsiveness:

1. **`api`**: Serves HTTP REST and SSE connections. Stateles and scalable.
2. **`sync_worker`**: Background repository indexing, AST parsing, and embeddings ingestion (`app.workers.sync_worker`).
3. **`webhook_worker`**: Durable queue consumer for GitHub webhook events (`app.services.webhook_worker`).
4. **`task_worker`**: Autonomous task execution, bounded repair loop, and workspace operations.
5. **`runner`**: Sandboxed command execution backend with isolated networking and resource limits.

---

## 2. Environment Configuration Per Role

| Role | Entrypoint / Command | Recommended Scaling | Required Variables |
|---|---|---|---|
| **`api`** | `uvicorn main:app --host 0.0.0.0 --port 8000` | Horizontal (2+ replicas) | `DISABLE_EMBEDDED_SYNC_WORKER=true`, `DISABLE_EMBEDDED_WEBHOOK_WORKER=true`, `DATABASE_URL`, `REDIS_URL`, `JWT_SECRET` |
| **`sync_worker`** | `python -m app.workers.sync_worker` | 1–3 replicas | `DATABASE_URL`, `REDIS_URL`, `GROQ_API_KEYS`, `GEMINI_API_KEYS` |
| **`webhook_worker`**| `python -m app.services.webhook_worker` | 1–2 replicas | `DATABASE_URL`, `REDIS_URL`, `GITHUB_WEBHOOK_SECRET` |
| **`task_worker`** | `python -m app.workers.task_worker` | 1–2 replicas | `DATABASE_URL`, `REDIS_URL`, `SANDBOX_BACKEND=container` |
| **`runner`** | `python -m runner.main` | Dedicated host/VM | `RUNNER_AUTH_SECRET`, `RUNNER_PORT=8001` |

---

## 3. Database Migration Policy
- **Rule**: Run database migrations (`alembic upgrade head`) **once per release** during the pre-deployment deployment phase (e.g., via GitHub Actions release step or init container), **never** simultaneously from every worker replica on startup.
- Set `RUN_MIGRATIONS_ON_STARTUP=false` on all worker roles.

---

## 4. Health and Readiness Checks
- `api` role: Check `GET /health/live` (p95 < 50ms) and `GET /health/ready` (validates DB, Redis, LLM gateway, and worker heartbeats).
- Workers: Each worker publishes heartbeats into Redis key `worker:heartbeat:<role>:<id>`.
