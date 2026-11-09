# 00 — Existing Architecture Audit & Problem Analysis

## 1. Executive Summary

This audit examines the platform's autonomous task execution pipeline prior to the implementation of autonomous code synthesis, plan-bound editing, and durable workflow execution.

The current system has strong foundations for planning, approvals, workspace isolation, loop detection, test running, bounded repair, independent verification, and draft PR generation. However, two critical architectural gaps prevent the platform from operating autonomously from the user interface:
1. **Missing Autonomous Code Synthesis:** When plan steps require modifications (`edit`, `create`, `write`, `modify`, `refactor`), the system requires the HTTP caller to provide the code content in `step_payloads`. Without caller-supplied content, execution fails with: `"No content payload provided. Placeholder synthetic writes are prohibited."`
2. **Synchronous HTTP Request Execution:** Autonomous post-approval execution runs synchronously inside a standard HTTP POST request (`/api/v1/tasks/{task_id}/execute` and `/api/v1/tasks/{task_id}/run-workflow`), making executions vulnerable to HTTP timeouts, socket resets, worker process recycling, and browser disconnects.

---

## 2. Core Execution Subsystem Audit

### 2.1 `AgentExecutionLoop` ([`backend/ai/services/agent_execution_loop.py`](file:///Users/meetvirugama/Desktop/AI-Powered-Software-Development-Platform/backend/ai/services/agent_execution_loop.py))
- **Responsibilities:**
  - Traverses `StructuredPlan` steps in topological dependency order (`_resolve_step_dependencies`).
  - Dispatches actions via `WorkspaceManager` and `WorkspaceToolPolicyBridge`.
  - Enforces workspace status requirements (`IN_USE` or `READY`).
  - Records chronological timeline events for step lifecycle transitions.
- **Current Action Dispatch:**
  | Action | Handler | Content Requirement |
  | :--- | :--- | :--- |
  | `patch` | `workspace_manager.patch_file` | Requires `target_content` and `replacement_content` in `step_input` |
  | `edit`, `create`, `write`, `modify`, `refactor` | `workspace_manager.write_file` | Requires `content` in `step_input` |
  | `delete` | `workspace_manager.delete_file` | Deletes files in `expected_files` |
  | `inspect`, `read` | `workspace_manager.read_file` | Returns file content or `[FILE_NOT_YET_CREATED]` |
  | `command`, `test` | `workspace_manager.execute_command` | Executes command (default `pytest`) |

### 2.2 Cross-Step Content Fallback Bug
In `AgentExecutionLoop.execute_plan` (lines 325-330):
```python
step_input = dict(payload_map.get(step_id, {}) or {})
if "content" not in step_input and action_type in ("edit", "create", "write", "modify", "refactor"):
    for other_input in payload_map.values():
        if isinstance(other_input, dict) and "content" in other_input:
            step_input["content"] = other_input["content"]
            break
```
> [!CAUTION]
> If a task has multiple modification steps and only Step 1 has a payload, Steps 2 and 3 will silently copy and write Step 1's content into unrelated target files! This cross-step fallback must be eliminated.

### 2.3 Multiple Target File Duplication Bug
In `_execute_single_step` (lines 458-465):
```python
for target_file in expected_files:
    res = self.workspace_manager.write_file(
        task_id=task_id,
        file_path=target_file,
        content=content,
        create_parents=True,
    )
```
If a step lists multiple files (e.g., `["src/auth.py", "tests/test_auth.py"]`), `write_file` writes the identical `content` into both files. The system must support per-file edits.

### 2.4 Anti-Cyclic `LoopDetector`
- Deterministic action fingerprinting (`ActionFingerprint(step_id, action_type, target_files, payload_hash)`).
- Detects immediate duplicate actions and repeating cyclic oscillations (up to window 4).
- Enforces `max_iterations = 25`.
- Halts execution safely on cycle detection, emitting `LOOP_DETECTED` events.

---

## 3. Task Orchestration & Workflow Execution Audit

### 3.1 `TaskExecutionOrchestrator` ([`backend/app/services/task_execution_orchestrator.py`](file:///Users/meetvirugama/Desktop/AI-Powered-Software-Development-Platform/backend/app/services/task_execution_orchestrator.py))
- Coordinates the complete autonomous post-approval pipeline:
  1. `start_task_execution` (runs plan steps via `AgentExecutionLoop`)
  2. `save_task_checkpoint(step_name="post_step_execution")`
  3. `execute_task_tests` (runs tests via `WorkspaceExecutionService` / `RestrictedRunner`)
  4. `execute_bounded_repair` (up to 3 repair attempts via `BoundedRepairLoop`)
  5. `save_task_checkpoint(step_name="post_test_and_repair")`
  6. `run_independent_verification` (`IndependentVerifier` / `WorkspaceDiffVerifier`)
  7. `save_task_checkpoint(step_name="post_independent_verification")`
  8. `create_draft_pull_request` (if verified and publication is authorized)
- **Synchronous Bottleneck:**
  `run_autonomous_post_approval_workflow` is executed synchronously. In `backend/app/api/v1/tasks.py`, the endpoint blocks on this method call until the entire pipeline finishes or fails.

---

## 4. Workspace & Security Boundary Audit

### 4.1 `WorkspaceDiffVerifier` ([`backend/sandbox/diff_verifier.py`](file:///Users/meetvirugama/Desktop/AI-Powered-Software-Development-Platform/backend/sandbox/diff_verifier.py))
- Extracts git diffs between the task workspace and base revision.
- Inspects file modifications against `allowed_files` (approved plan scope).
- Blocks deletions of critical project files (`README.md`, `package.json`, `pyproject.toml`, etc.).
- Scans added lines for credential leaks (AWS keys, GitHub tokens, Slack tokens, private keys).
- Traversal protection via `validate_repo_relative_path`.

### 4.2 Mandatory Human Approval Gate (ADR-010)
- Execution is strictly prohibited until a human reviews and approves a specific plan version.
- Re-planning or modifying the plan invalidates approval and halts execution.

---

## 5. Frontend & UI Audit

### 5.1 `RepositoryTaskStudio.tsx` ([`frontend/src/pages/RepositoryTaskStudio.tsx`](file:///Users/meetvirugama/Desktop/AI-Powered-Software-Development-Platform/frontend/src/pages/RepositoryTaskStudio.tsx))
- Lines 402 and 503 invoke:
  ```typescript
  await executeTask(tid, {
      run_steps: true,
      run_tests_after: true,
      auto_repair: true,
  });
  ```
- Because no `step_payloads` are passed from the UI, any task with an `edit` step currently fails.
- The UI currently awaits the HTTP response, which times out if test execution or repair takes longer than the browser's request timeout limit.

---

## 6. Durable Workflow (DBOS) Audit

### 6.1 `poc/dbos/workflow.py` ([`backend/poc/dbos/workflow.py`](file:///Users/meetvirugama/Desktop/AI-Powered-Software-Development-Platform/backend/poc/dbos/workflow.py))
- Proof of concept demonstrated:
  - `@DBOS.workflow` and `@DBOS.step` decorators.
  - Step checkpointing, resumption from failure, and bounded retries.
  - Fallback stub (`_DBOSStub`) when DBOS is unconfigured or in development mode.
- Requirement: Evolve this POC into a production-grade durable execution workflow for autonomous task execution, returning HTTP 202 Accepted.

---

## 7. Real-Time Streaming & SSE Audit

### 7.1 `backend/app/api/v1/events.py`
- Endpoints subscribe to the Redis pubsub channel `platform_events`.
- Events are scoped to users and repositories with fail-closed security.
- Need: Publish workflow lifecycle events (`WORKFLOW_QUEUED`, `SYNTHESIS_STARTED`, `SYNTHESIS_RETRY`, `PATCH_APPLIED`, `WORKFLOW_COMPLETED`) to this channel and persist them in `task_timeline_events`.
