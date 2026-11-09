# 07 — Durable Workflow Execution Architecture

## 1. Executive Summary

Autonomous software development workflows involve complex, multi-stage pipelines: workspace setup, plan execution, LLM synthesis, diff verification, test execution, bounded repair, independent verification, and draft PR publication.

Running this entire pipeline synchronously within a single HTTP request exposes users to HTTP client timeouts (typical 30s-60s proxy timeouts), lost connections on laptop sleep or WiFi switch, and inability to track multi-minute execution states.

`autonomous_task_workflow.py` (`backend/ai/workflows/`) implements a durable, asynchronous workflow architecture powered by DBOS (Database-Oriented Operating System) steps and workflows.

---

## 2. DBOS Durable Steps and Workflow Design

```mermaid
flowchart TD
    subgraph Client / UI
        A[User Clicks Run Auto-Pilot] -->|POST /run-workflow async=True| B(HTTP 202 Accepted)
        B --> C[Poll GET /workflow-status]
        B --> D[Subscribe SSE /events]
    end

    subgraph Durable DBOS Workflow Engine
        B -.->|Spawn Durable Thread| WF[run_autonomous_task_workflow]
        WF --> S1[step_validate_approval]
        S1 --> S2[step_initialize_workspace]
        S2 --> S3[step_execute_plan_and_synthesize]
        S3 --> S4[step_validate_plan_bound_diff]
        S4 --> S5[step_run_tests_and_repair]
        S5 --> S6[step_run_independent_verification]
        S6 --> S7[step_publish_draft_pr_if_authorized]
        S7 --> S8[Workflow Completed]
    end

    subgraph Persistence & Audit
        S1 --> CP1[(Checkpoint 1: APPROVED)]
        S2 --> CP2[(Checkpoint 2: WORKSPACE_INITIALIZED)]
        S3 --> CP3[(Checkpoint 3: PLAN_EXECUTED)]
        S4 --> CP4[(Checkpoint 4: DIFF_VERIFIED)]
        S5 --> CP5[(Checkpoint 5: TESTS_PASSED)]
        S6 --> CP6[(Checkpoint 6: INDEPENDENT_VERIFIED)]
        S7 --> CP7[(Checkpoint 7: PR_PUBLISHED)]
    end
```

### 2.1 The 7 Durable Steps
Each step is decorated with `@dbos_step()`, recording its execution status and output:

1. **`step_validate_approval`**: Enforces ADR-010 approval status, plan version consistency, and re-computes plan hash.
2. **`step_initialize_workspace`**: Prepares isolated workspace directory, cleans previous artifacts, and syncs base branch files.
3. **`step_execute_plan_and_synthesize`**: Runs `AgentExecutionLoop`, autonomously invoking `EditSynthesizer` when caller payloads are not provided.
4. **`step_validate_plan_bound_diff`**: Uses `WorkspaceDiffVerifier` to confirm modified files match `expected_files` and contain no forbidden files.
5. **`step_run_tests_and_repair`**: Executes repository test suite. If failures occur and `auto_repair=True`, runs `BoundedRepairLoop` (up to 3 repair attempts).
6. **`step_run_independent_verification`**: Executes fresh, independent secondary verification on the target commit.
7. **`step_publish_draft_pr_if_authorized`**: Commits verified changes, pushes feature branch, and opens GitHub Draft PR if human authorization is confirmed.

---

## 3. Stable Workflow IDs and Idempotency

- Every task submission generates a stable workflow identifier formatted as `wf-{task_id}-{uuid[:8]}`.
- An in-memory re-entrant lock (`_registry_lock = threading.RLock()`) guarantees duplicate submissions for the same active task do not spawn concurrent processes.
- If a client calls `/run-workflow` while a workflow is already running, the system returns `HTTP 202 Accepted` pointing to the existing workflow ID with `is_new=False`.

---

## 4. Checkpointing and Crash Recovery

Each step transition creates a secret-scrubbed `TaskCheckpoint` in the database. If a catastrophic system crash occurs:
- The persistent checkpoint preserves the verified revision, plan version, step records, and remaining repair budget.
- The `TaskRecovery` service inspects the latest checkpoint to resume or roll back safely without duplicate side-effects.
