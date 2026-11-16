# Runbook: Webhook Replay and Dead-Letter Queue Reconciliation

## 1. Overview
The platform uses a durable, two-stage webhook processing architecture:
1. **Ingestion Stage (`/api/v1/github/webhook`)**:
   - HMAC-SHA256 signature verification (`X-Hub-Signature-256`).
   - Content-Length pre-check (max 5 MB).
   - Ingests event into PostgreSQL `github_webhook_events` table with status `PENDING`.
   - Returns immediate `202 Accepted` to GitHub to avoid timeouts.
2. **Execution Stage (`webhook_worker`)**:
   - Claims batches via lease lock (`FOR UPDATE SKIP LOCKED`).
   - Dispatches to event handlers (push-to-sync, issue triage, PR review).
   - Transitions event to `PROCESSED` or `FAILED`.

---

## 2. Investigating Failed Webhook Events

Query failed events:
```sql
SELECT id, event_type, delivery_id, attempts, error_message, created_at, updated_at
FROM github_webhook_events
WHERE status = 'FAILED'
ORDER BY created_at DESC
LIMIT 50;
```

Inspect event payload:
```sql
SELECT payload
FROM github_webhook_events
WHERE id = '<event-uuid>';
```

---

## 3. Replaying Failed Events

### Option A: Via Management API
```bash
curl -X POST "https://api.dev-platform.example.com/api/v1/github/webhook/events/<event-uuid>/replay" \
  -H "Authorization: Bearer <ADMIN_JWT>"
```

### Option B: Direct SQL Re-queue (Single or Batch)
Reset event status to `PENDING` and reset attempt counter:
```sql
UPDATE github_webhook_events
SET status = 'PENDING',
    attempts = 0,
    error_message = NULL,
    locked_until = NULL
WHERE id = '<event-uuid>' OR (status = 'FAILED' AND created_at > NOW() - INTERVAL '24 HOURS');
```

The `webhook_worker` will automatically claim and process the reset events on its next polling cycle (every 2.0s).
