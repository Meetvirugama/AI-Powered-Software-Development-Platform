# 08 — API and Frontend Integration

## 1. REST API Endpoints

### 1.1 Asynchronous Execution Initiation
- **Endpoint**: `POST /api/v1/tasks/{task_id}/run-workflow`
- **Headers**:
  - `Authorization: Bearer <jwt>`
  - `Prefer: respond-async` (optional header triggering async mode)
- **Request Body**:
  ```json
  {
    "async_execution": true,
    "run_tests": true,
    "auto_repair": true,
    "publication_authorized": false
  }
  ```
- **Response**: `HTTP 202 Accepted`
  ```json
  {
    "task_id": "4b6c8e31-...",
    "workflow_id": "wf-4b6c8e31-...-a1b2c3d4",
    "status": "QUEUED",
    "message": "Autonomous workflow accepted and executing in background.",
    "status_url": "/api/v1/tasks/4b6c8e31-.../workflow-status"
  }
  ```

### 1.2 Workflow Status and Progress Endpoint
- **Endpoint**: `GET /api/v1/tasks/{task_id}/workflow-status`
- **Headers**: `Authorization: Bearer <jwt>`
- **Response**: `HTTP 200 OK`
  ```json
  {
    "task_id": "4b6c8e31-...",
    "workflow_id": "wf-4b6c8e31-...-a1b2c3d4",
    "status": "SYNTHESIZING",
    "current_step": "EXECUTE_APPROVED_PLAN",
    "completed_steps": [
      "VALIDATE_APPROVAL",
      "INITIALIZE_WORKSPACE"
    ],
    "progress_percentage": 28,
    "verification": null,
    "pull_request": null,
    "error_summary": null,
    "started_at": "2026-11-09T07:30:00Z",
    "updated_at": "2026-11-09T07:30:15Z",
    "completed_at": null,
    "status_url": "/api/v1/tasks/4b6c8e31-.../workflow-status"
  }
  ```

---

## 2. Server-Sent Events (SSE) Progress Streaming

Throughout workflow execution, progress events are published to the Redis channel `platform_events`:
- `WORKFLOW_STARTED`: Published upon entry.
- `WORKSPACE_INITIALIZED`: Workspace clean and ready.
- `PLAN_EXECUTION_STARTED`: Synthesis loop initiated.
- `STEP_SYNTHESIS_STARTED`: Synthesizing code for specific step.
- `STEP_SYNTHESIS_COMPLETED`: Search/replace block verified and written.
- `DIFF_VALIDATION_COMPLETED`: Workspace git diff verified against plan scope.
- `TESTS_STARTED`: Unit and integration test suite executing.
- `VERIFICATION_COMPLETED`: Independent verification completed.
- `WORKFLOW_COMPLETED`: Workflow finished successfully.
- `WORKFLOW_FAILED`: Workflow failed safely with scrubbed error message.

---

## 3. Frontend Studio Integration

### 3.1 Task Service (`frontend/src/services/tasks.ts`)
Exposes:
- `startAutonomousWorkflow(taskId, options)`: Sends `POST /api/v1/tasks/{taskId}/run-workflow` with `async_execution: true`.
- `getWorkflowStatus(taskId)`: Polls `GET /api/v1/tasks/{taskId}/workflow-status`.

### 3.2 Repository Task Studio (`frontend/src/pages/RepositoryTaskStudio.tsx`)
In `handleRunAutoPilot`:
- Calls `startAutonomousWorkflow` to initiate background execution.
- If the server accepts `HTTP 202`, sets `isAutoPilotRunning(true)` and begins polling status.
- Seamlessly falls back to synchronous execution if an older backend version does not support async execution.
- On browser refresh or reconnection, queries `getWorkflowStatus` to restore active execution state and progress bars.

