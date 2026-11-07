# 17. Durable GitHub Webhook Automation Design

## 1. System Overview & Problem Statement

The platform integrates with GitHub App to link user accounts, synchronize repository content into vector databases, run AI code reviews, and automate developer workflows.

Previously:
- Incoming webhooks (`POST /api/v1/github/webhook`) executed operations synchronously within the HTTP request lifecycle.
- Unsupported events were dropped without persistence.
- There was no durable event store, leading to lost events during server restarts, network blips, or downstream outages.
- Push events did not trigger incremental synchronization.
- Installation updates did not automatically reconcile accessible repositories.
- PR reviews required manual triggering via API.

Issue #182 transforms the GitHub integration into a durable, asynchronous, recoverable event-processing architecture.

---

## 2. Existing Architecture & Audit Findings

### 2.1 Webhook Request Lifecycle
1. Request arrives at `POST /api/v1/github/webhook`.
2. HMAC-SHA256 signature is verified against raw body using `GITHUB_WEBHOOK_SECRET`.
3. Delivery ID format (`X-GitHub-Delivery`) is validated and deduplicated via Redis `SET ... NX EX 86400`.
4. Payload size limit (5 MB) is checked.
5. `ping` returns pong immediately.
6. Minimal synchronous handling for `installation` (created/deleted).

### 2.2 Existing Queue & Worker Architecture
- `RedisSyncJobQueue`: pushes sync jobs to Redis `sync_jobs`.
- `sync_worker_loop`: background polling loop using `brpoplpush` / `blmove` to a processing queue (`sync_jobs:processing`).
- Background job reconciliation: `reconcile_stale_sync_jobs` sweeps stuck jobs.
- `IncrementalIndexer`: performs hash-based difference detection, AST symbol extraction, vector embeddings, and chunk storage.

### 2.3 Existing Models
- `GitHubInstallation`: stores `user_id`, `installation_id`, `account_login`, `permissions`.
- `Repository`: stores `user_id`, `installation_id`, `github_repo_id`, `owner`, `name`, `default_branch`, `sync_status`, `last_synced_at`.
- `SyncJob`: tracks manual/initial repository indexing jobs.
- `PullRequest`: stores PR branch and verification metadata.
- `AnalysisRun` & `AnalysisFinding`: stores code review, bug detection, and explanation runs.

### 2.4 Gaps Identified
- No durable database table for webhook events.
- Redis-only deduplication without transactional persistence.
- No durable worker state machine (`pending` -> `processing` -> `succeeded` / `retry` / `dead_letter`).
- Absence of push-triggered incremental indexing.
- Lack of automatic installation repository reconciliation.
- PR review automation not integrated with webhook triggers.
- Issues events dropped completely.

---

## 3. Durable Webhook Architecture (Phase 1 & Phase 2)

### 3.1 Fast Ingestion & Persistence
The HTTP endpoint `POST /api/v1/github/webhook` maintains a p95 latency under 1 second:
1. Verify raw HMAC signature (`X-Hub-Signature-256`).
2. Validate required headers (`X-GitHub-Event`, `X-GitHub-Delivery`).
3. Enforce maximum payload size (5 MB).
4. Extract `event_type`, `action`, `installation_id`, `repository_id`.
5. Redis fast-path delivery deduplication (`webhook_delivery:{delivery_id}`).
6. **Durable Persistence**: Write the event to `webhook_events` table in PostgreSQL with status `pending`.
   - If PostgreSQL write fails, return a 500 retryable error so GitHub redelivers.
   - If unique constraint on `delivery_id` trips, acknowledge as duplicate.
7. Return `200 OK` promptly upon successful persistence.

### 3.2 Durable Event Lifecycle
Events transition through a strict state machine:
- `pending`: Newly ingested event ready for processing.
- `processing`: Claimed by a worker; protected by a lease timeout.
- `succeeded`: Terminal success state; processed timestamp recorded.
- `retry`: Transient error occurred; scheduled with exponential backoff + jitter.
- `dead_letter`: Permanent error or max attempts (default 5) exhausted.

### 3.3 Atomic Worker Claims & Concurrency Control
Workers claim events using PostgreSQL row-level locks with skip locked:
```sql
UPDATE webhook_events
SET status = 'processing',
    claimed_at = NOW(),
    lease_expires_at = NOW() + INTERVAL '5 minutes',
    claimed_by = :worker_id
WHERE id = (
    SELECT id FROM webhook_events
    WHERE (status IN ('pending', 'retry') AND available_at <= NOW())
       OR (status = 'processing' AND lease_expires_at <= NOW())
    ORDER BY created_at ASC
    LIMIT 1
    FOR UPDATE SKIP LOCKED
)
RETURNING *;
```
Benefits:
- Multiple concurrent workers never claim or process the same event.
- Stalled or crashed workers' leases naturally expire and are recovered by any active worker.

### 3.4 Retry Policy & Exponential Backoff
- Default maximum attempts: 5.
- Backoff formula: `delay = min(300, base * (2 ** attempts) + uniform(0.1, 1.0))`.
- Errors are sanitized (removing tokens, passwords, private keys) before storing in `last_error`.

---

## 4. Push-Triggered Incremental Synchronization (Phase 3)

### 4.1 Push Event Workflow
1. Filter: Event must be `push` on the repository's `default_branch` (`refs/heads/{default_branch}`). Non-default branches are ignored unless configured.
2. Branch deletion check: If `deleted == true` or commit SHA is `0000000...`, ignore cleanly.
3. Commit deduplication: Compare `after` commit SHA against `repository.last_indexed_commit_sha`. If identical, skip.
4. Verify current branch HEAD via GitHub API to ensure out-of-order deliveries or force pushes do not overwrite newer indexed states.
5. Acquire repository-level synchronization lock to prevent conflicting concurrent sync jobs.
6. Shallow-clone or fetch changed files (`added`, `modified`, `removed`).
7. Invoke existing `IncrementalIndexer` to index added/modified files and delete removed files.
8. Atomically update `repository.last_indexed_commit_sha = head_sha`, `repository.sync_status = SYNCED`, `repository.last_synced_at = NOW()`.

---

## 5. Installation Repository Reconciliation (Phase 4)

### 5.1 Reconciliation Events
- `installation_repositories` (`added`, `removed`)
- `installation` (`deleted`, `suspend`)

### 5.2 Workflow
1. Treats GitHub's current installation repository list as authoritative.
2. Query `github_service.list_repositories(installation_id)`.
3. Verify installation ownership in `github_installations`.
4. Idempotently add newly accessible repositories for the user.
5. For removed repositories:
   - Revoke access immediately by disassociating the installation or setting status to revoked.
   - Cancel any pending `SyncJob`s.
   - **Data Preservation**: Retain historical `analysis_runs`, `analysis_findings`, and user-owned tasks. Do not delete analytical history.
6. When an installation is deleted: delete the installation record and revoke repository linkages.

---

## 6. Opt-In Pull Request Review Automation (Phase 5)

### 6.1 Supported PR Actions
`opened`, `synchronize`, `reopened`, `ready_for_review`, `closed`, `converted to draft`.

### 6.2 Opt-In Configuration
- Repository-level flag: `auto_pr_review_enabled` (default: `False`).
- Configurable draft PR review: `review_draft_prs` (default: `False`).
- If disabled, events are acknowledged and recorded without executing AI reviews.

### 6.3 Review Execution & Deduplication
- Deduplication key: `(repository_id, pr_number, head_sha)`.
- If a review has already completed or is running for this exact tuple, skip redundant execution.
- If `action == "closed"`, abort any in-flight reviews.

### 6.4 Pre-Publish Validation
Before publishing comments to GitHub:
1. Verify installation and repository authorization.
2. Verify PR still exists and is open on GitHub.
3. Confirm current PR head SHA matches reviewed SHA (reject stale results).
4. Run static and AI review via `CodeReviewOrchestrator` (`target="pr"`).
5. Map findings to diff ranges. Any findings that cannot be mapped to modified line ranges are placed in the consolidated review summary (never invent fake line coordinates).
6. Post one consolidated review. Never auto-merge or auto-approve.

---

## 7. GitHub Issues Event Foundation (Phase 6)

### 7.1 Supported Actions
`opened`, `edited`, `closed`, `reopened`, `assigned`, `labeled`.

### 7.2 Foundation Design
- Upserts issue metadata in `github_issues` table.
- Resolves linked repository and validates authorization.
- Provides an extensible `IssueEventHandler` protocol.
- **Strict Boundary**: Never executes automatic writes (no AI comments, label additions, or issue closing). Write actions require explicit user opt-in and task workflows.

---

## 8. Database Schema & Migration Strategy (Phase 7)

### 8.1 New Tables & Columns
1. `webhook_events`:
   - `id`: UUID (PK)
   - `delivery_id`: String (Unique, Indexed)
   - `event_type`: String (Indexed)
   - `action`: String (Nullable, Indexed)
   - `installation_id`: String (Nullable, Indexed)
   - `repository_id`: UUID (Nullable, FK `repositories.id`)
   - `github_repo_id`: String (Nullable, Indexed)
   - `payload`: JSONB (Sanitized)
   - `status`: String (Indexed)
   - `attempts`: Integer (Default 0)
   - `max_attempts`: Integer (Default 5)
   - `available_at`: DateTime (Indexed)
   - `claimed_at`: DateTime (Nullable)
   - `claimed_by`: String (Nullable)
   - `lease_expires_at`: DateTime (Nullable, Indexed)
   - `processed_at`: DateTime (Nullable)
   - `last_error`: Text (Nullable)
   - `replay_count`: Integer (Default 0)
   - `last_replayed_at`: DateTime (Nullable)
   - `created_at`, `updated_at`: DateTime

2. `repositories` modifications:
   - `last_indexed_commit_sha`: String(64) (Nullable)
   - `auto_pr_review_enabled`: Boolean (Default False)
   - `review_draft_prs`: Boolean (Default False)
   - `auto_sync_enabled`: Boolean (Default True)

3. `github_issues`:
   - `id`: UUID (PK)
   - `repository_id`: UUID (FK `repositories.id`)
   - `issue_number`: Integer (Indexed)
   - `title`: String
   - `state`: String
   - `author`: String
   - `assignees`: JSONB
   - `labels`: JSONB
   - `body_snippet`: Text
   - `last_action`: String
   - `created_at`, `updated_at`: DateTime

### 8.2 Migration Safety
- Migration script added to Alembic revision chain.
- Non-destructive: adds new tables and nullable/default columns.
- Fully reversible down_revision.

---

## 9. API & Operational Visibility (Phase 8)

- `GET /api/v1/github/events`: List webhook events with filters (`status`, `event_type`, `repository_id`) and pagination.
- `GET /api/v1/github/events/{id}`: Detailed view of event and error traces.
- `POST /api/v1/github/events/{id}/replay`: Replay failed or dead-lettered events safely. Actively processing events cannot be replayed.
- `GET /api/v1/github/repositories/{id}/automation`: View repository automation settings.
- `PATCH /api/v1/github/repositories/{id}/automation`: Configure automation settings (enable/disable push sync, PR reviews, draft reviews).

---

## 10. Required GitHub App Permissions

- `Repository permissions`:
  - `Contents`: Read & Write (for cloning, reading diffs)
  - `Pull requests`: Read & Write (for inspecting diffs, posting review comments)
  - `Issues`: Read (for intake and event foundation)
  - `Metadata`: Read (mandatory for all apps)
- `Subscribe to events`:
  - `Push`
  - `Pull request`
  - `Installation`
  - `Installation repositories`
  - `Issues`

---

## 11. Deployment & Operations Runbook

### 11.1 Database Migration
Run database schema migration to head revision (`e1f2a3b4c5d6`):
```bash
cd backend
alembic upgrade head
```

Rollback verification (if required):
```bash
alembic downgrade -1
alembic upgrade head
```

### 11.2 Background Worker Startup & Management
The worker can be run either as an embedded background task inside FastAPI (default via `backend/app/core/lifespan.py`) or as a dedicated standalone service process in production:
```bash
# Standalone worker execution:
cd backend
python -m app.workers.webhook_worker
```

Kubernetes Pod / Deployment Spec snippet:
```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: github-webhook-worker
spec:
  replicas: 2
  template:
    spec:
      containers:
        - name: worker
          image: ai-platform-backend:latest
          command: ["python", "-m", "app.workers.webhook_worker"]
          envFrom:
            - secretRef:
                name: github-app-secrets
            - configMapRef:
                name: backend-config
```

### 11.3 Required Environment Variables
| Variable | Required | Description |
|---|---|---|
| `DATABASE_URL` | Yes | PostgreSQL connection string with pgvector support |
| `REDIS_URL` | Yes | Redis connection string for in-flight delivery deduplication |
| `GITHUB_WEBHOOK_SECRET` | Yes | HMAC-SHA256 secret configured in GitHub App settings |
| `GITHUB_APP_ID` | Yes | Numerical GitHub App ID |
| `GITHUB_APP_PRIVATE_KEY` | Yes | PEM-formatted private key for GitHub App JWT signing |
| `JWT_SECRET` | Yes | Authentication signing secret for operational API endpoints |

### 11.4 Operational Verification Steps
1. Verify endpoint health and HMAC verification:
   ```bash
   curl -X POST https://api.yourdomain.com/api/v1/github/webhook \
     -H "Content-Type: application/json" \
     -H "X-GitHub-Event: ping" \
     -H "X-GitHub-Delivery: $(uuidgen)" \
     -H "X-Hub-Signature-256: sha256=..." \
     -d '{"zen": "testing"}'
   # Expected response: {"status": "pong"}
   ```
2. Verify durable event persistence:
   Send test push or PR event and verify HTTP `202 Accepted` response with `delivery_id` and `event_id`.
3. Check worker processing status:
   ```bash
   curl -X GET https://api.yourdomain.com/api/v1/github/events?page_size=5 \
     -H "Authorization: Bearer <ADMIN_OR_USER_JWT>"
   ```

### 11.5 Secret Rotation Procedures
1. Generate new GitHub Webhook Secret in GitHub App Settings.
2. Update Kubernetes / cloud secret:
   ```bash
   kubectl create secret generic github-app-secrets \
     --from-literal=GITHUB_WEBHOOK_SECRET="<NEW_SECRET>" \
     --dry-run=client -o yaml | kubectl apply -f -
   ```
3. Restart backend API pods:
   ```bash
   kubectl rollout restart deployment/backend-api
   ```
4. Update webhook secret in GitHub App developer settings.
5. Ingest a test event to verify HMAC verification succeeds with the new secret.

### 11.6 Dead-Letter Event Inspection & Replay Instructions
1. Inspect dead-lettered events:
   ```bash
   curl -X GET "https://api.yourdomain.com/api/v1/github/events?status=dead_letter" \
     -H "Authorization: Bearer <ADMIN_JWT>"
   ```
2. Inspect individual event error trace:
   ```bash
   curl -X GET "https://api.yourdomain.com/api/v1/github/events/<EVENT_ID>" \
     -H "Authorization: Bearer <ADMIN_JWT>"
   ```
3. Replay dead-lettered event once underlying issue (network, rate-limit, permissions) is resolved:
   ```bash
   curl -X POST "https://api.yourdomain.com/api/v1/github/events/<EVENT_ID>/replay" \
     -H "Authorization: Bearer <ADMIN_JWT>"
   # Expected response: {"status": "replayed", "event_id": "<EVENT_ID>", "replay_count": 1}
   ```
