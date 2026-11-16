# Runbook: Task Recovery and Workspace Reconciliation

## 1. Overview
Tasks progress through an explicit state machine:
`NOT_STARTED` -> `PLANNING` -> `PLANNED` -> `APPROVED` -> `EXECUTING` -> `VERIFYING` -> `DRAFT_PR_CREATED` (or `FAILED` / `REJECTED`).

If a worker crashes or an Azure instance restarts while a task is `EXECUTING` or `VERIFYING`, the task must be safely recovered without leaving orphaned container processes or corrupted workspaces.

---

## 2. Startup Reconciliation Loop
On startup, `lifespan.py` executes automated reconciliation when `run_startup_reconciliation=True`:
1. **Stale Sync Jobs**: Any job in `RUNNING` status with heartbeat older than 600s is marked `FAILED` with message `"Reconciled after worker crash or timeout"`.
2. **Interrupted Tasks**: Tasks in `EXECUTING` status with no active worker lease are transitioned to `FAILED` with diagnostic reason `"Worker node terminated during execution; safe restart required"`.

---

## 3. Manual Task Recovery

### Step 1: Identify Stalled Tasks
```sql
SELECT id, repository_id, status, current_step, updated_at
FROM tasks
WHERE status IN ('EXECUTING', 'VERIFYING')
  AND updated_at < NOW() - INTERVAL '30 MINUTES';
```

### Step 2: Release Locked Workspaces
If the task workspace is locked on disk:
```bash
# Check if container or process is still running
docker ps -a --filter "name=task-<task-id>"

# Stop and remove stale container
docker rm -f task-<task-id>

# Clean up task workspace directory safely
rm -rf .workspaces/task-<task-id>
```

### Step 3: Reset Task to PLANNED or RECOVERED
```sql
UPDATE tasks
SET status = 'PLANNED',
    error_message = 'Recovered from interrupted execution via operations runbook.'
WHERE id = '<task-id>';
```

User can now click **Start Execution** from the UI to resume the task with a clean workspace.
