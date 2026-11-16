# Operational Runbooks

Procedures verified against the code at commit `5d0b3ff`. Replace `<…>` placeholders; never paste secrets into tickets or logs.

## 1. Deploy per role

| Role (`SERVICE_ROLE`) | Command run by `startup.sh` | Notes |
|---|---|---|
| `api` (default) | `uvicorn main:app` (proxy headers only when `TRUST_PROXY_HEADERS=true`) | Stateless HTTP/SSE. Set `DISABLE_EMBEDDED_WEBHOOK_WORKER=true` when a dedicated webhook worker runs. The embedded sync loop is off by default in production |
| `sync_worker` (alias `worker`) | `python -m app.workers.sync_worker` | Indexing, embeddings, retention maintenance |
| `webhook_worker` | `python -m app.workers.webhook_worker` | Durable webhook queue consumer |
| `runner` | `python -m runner.main` | Isolated execution host with Docker (+ gVisor); requires `RUNNER_AUTH_SECRET` |
| `migrate` | `alembic upgrade head` (one-shot) | Run once per release; set `RUN_MIGRATIONS_ON_STARTUP=false` on long-running roles |

There is no separate task-worker role: task workflows run in threads inside the API process.

Health: `GET /api/v1/health/live` (liveness) and `GET /api/v1/health/ready` (database, Redis, worker heartbeats, webhook backlog, scanner and sandbox availability). Workers publish heartbeats under `worker:heartbeat:*` in Redis.

## 2. Recover interrupted tasks

1. On startup (unless `RUN_STARTUP_RECONCILIATION=false`) the API:
   - fails sync jobs whose heartbeat is stale,
   - moves in-flight tasks to `RECOVERY_REQUIRED` and records a `RECOVERY_TRIGGERED` event,
   - recovers or schedules cleanup of orphaned workspaces.
2. Find tasks needing attention:
   ```sql
   SELECT id, repository_id, status, updated_at
   FROM tasks
   WHERE status IN ('RECOVERY_REQUIRED', 'FAILED')
   ORDER BY updated_at DESC;
   ```
3. Inspect the timeline and checkpoints: `GET /api/v1/tasks/<id>/events`, `GET /api/v1/tasks/<id>/checkpoints`, `GET /api/v1/tasks/<id>/workspace`, `GET /api/v1/tasks/<id>/stale-check`.
4. Recover through the API (preserves audit history): `POST /api/v1/tasks/<id>/recover`. Do not edit `tasks.status` by hand.
5. If a container is left running on a runner host: `docker ps --filter "name=task-<id>"` then `docker rm -f <container>`.

## 3. Replay webhook events

Statuses: `PENDING`, `PROCESSING`, `SUCCEEDED`, `RETRY`, `DEAD_LETTER`.

```sql
SELECT id, event_type, action, delivery_id, attempts, max_attempts, last_error, created_at
FROM github_webhook_events
WHERE status IN ('DEAD_LETTER', 'RETRY')
ORDER BY created_at DESC
LIMIT 50;
```

Replay (preferred, audited via `replay_count`):

```bash
curl -X POST "https://<api-host>/api/v1/github/events/<event-id>/replay" \
  --cookie "access_token=<token>"
```

List/inspect via `GET /api/v1/github/events` and `GET /api/v1/github/events/<event-id>`.

## 4. Rotate secrets

| Secret | Procedure | Impact |
|---|---|---|
| `JWT_SECRET` | Generate (`python -c "import secrets; print(secrets.token_urlsafe(48))"`), store in the secret manager, restart all API instances together | Access **and** refresh tokens are signed with this key, so all users must sign in again |
| `GITHUB_APP_PRIVATE_KEY` | Generate a new key in the GitHub App, update the environment, restart API and workers, verify `/health/ready` and a repository sync, then delete the old key | None if done in this order |
| `GITHUB_WEBHOOK_SECRET` | Update in GitHub App settings and in API/webhook worker environments at the same time; send a ping delivery | Deliveries signed with the old secret fail verification during the switch |
| `RUNNER_AUTH_SECRET` | Update on runner host and API together | Test execution fails closed while mismatched |
| Gemini / Groq keys | Add the new key to `GEMINI_API_KEYS` / `GROQ_API_KEYS`, deploy, remove the old key | Key rotation lists avoid downtime |

`JWT_SECRET` must be ≥32 characters with ≥12 distinct characters in production.

## 5. Backup and restore

```bash
# Backup (custom format)
pg_dump -Fc --no-acl --no-owner --dbname="$DATABASE_URL" -f "backup_$(date +%Y%m%d_%H%M%S).dump"

# Verify critical tables are present
pg_restore -l backup_*.dump | grep -E "(tasks|analysis_runs|code_chunks|code_symbols|users)"

# Restore into a scratch database
createdb restore_check
psql -d restore_check -c "CREATE EXTENSION IF NOT EXISTS vector;"
pg_restore -d restore_check --clean --if-exists --exit-on-error backup_*.dump
```

Use the managed provider's point-in-time recovery for production. Redis holds only rebuildable state (caches, queues, blocklist); after a Redis loss, re-run syncs for repositories left `queued`.

## 6. Repository stuck in `queued` or `syncing`

1. Check `/health/ready` for worker heartbeats.
2. Ensure a sync worker is running (`SERVICE_ROLE=sync_worker`) or the embedded loop is enabled.
3. Re-queue with `POST /api/v1/repositories/<id>/sync`.
