# 13 — Operations, Runbooks, and Troubleshooting Guide

## 1. Overview
This operational guide provides diagnostic procedures, failure recovery steps, and incident runbooks for the autonomous code synthesis and durable workflow engine.

---

## 2. Common Operational Issues and Resolutions

### 2.1 Workflow In "QUEUED" or "RUNNING" Indefinitely
- **Symptoms**: `GET /api/v1/tasks/{task_id}/workflow-status` remains in `RUNNING` or `SYNTHESIZING` without step progression for >10 minutes.
- **Root Cause**: Worker thread unhandled crash, background DB lock timeout, or unhandled socket hang.
- **Diagnostic Command**:
  ```bash
  # Check backend container/process logs for unhandled workflow errors
  grep "autonomous_workflow_step_failed" backend/logs/*.log
  ```
- **Remediation**:
  1. Trigger task recovery endpoint:
     `POST /api/v1/tasks/{task_id}/recover`
  2. The recovery manager inspects the latest valid `TaskCheckpoint`, restores repository state to the last verified commit, and resets status to `APPROVED` for a clean retry.

### 2.2 Patch Application Rejection (`occurrences == 0`)
- **Symptoms**: Workflow fails at `step_execute_plan_and_synthesize` with error: `Zero matches found for search_block in file ...`.
- **Root Cause**: LLM generated a `search_block` based on stale knowledge or hallucinated line contents that do not match current workspace file state verbatim.
- **Diagnostic**:
  Inspect step record in `TaskEvent` timeline to view the attempted `search_block` and target file diff.
- **Remediation**:
  Trigger re-planning with fresh repository context:
  `POST /api/v1/tasks/{task_id}/plan`

### 2.3 Python AST / Syntax Error Rejection
- **Symptoms**: Step execution record logs `SYNTAX_ERROR` after 3 refinement attempts.
- **Root Cause**: LLM failed to close quotation marks, mismatched indentation, or produced invalid syntax that was not corrected within the 3-attempt ceiling.
- **Remediation**:
  Task fails closed safely without corrupting the workspace. Review requirements and submit an updated plan.

### 2.4 SSE Event Stream Disconnection
- **Symptoms**: Frontend stops updating live status bars in `RepositoryTaskStudio`.
- **Root Cause**: Client network switch, laptop closed, or proxy buffer timeout.
- **Automatic Handling**:
  The frontend `EventSource` listener automatically reconnects. Upon reconnect, the frontend queries `GET /api/v1/tasks/{task_id}/workflow-status` to immediately synchronize UI state and restore progress bars.

### 2.5 Duplicate Workflow Submission (Idempotency)
- **Symptoms**: User double-clicks "Run Auto-Pilot".
- **Expected Behavior**: The server detects active workflow via `_registry_lock` and returns `HTTP 202 Accepted` referencing the existing `workflow_id` with `is_new=False`. No duplicate threads or processes are launched.

