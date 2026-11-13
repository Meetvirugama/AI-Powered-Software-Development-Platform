## Summary of Changes

Closes #202
Closes #203

This pull request implements **Feature F22: Autonomous Code Synthesis, Plan-Bound Editing, and Durable Workflow Execution** as specified in `task.md`.

It resolves the two core architectural gaps in post-approval task execution:
1. **Autonomous Code Modification**: The agent can now autonomously synthesize, validate, and apply precise code modifications for human-approved plan steps without requiring external callers to provide file content.
2. **Durable Workflow Execution**: Replaces fragile, synchronous HTTP workflow execution with a durable background execution engine powered by DBOS steps, providing HTTP 202 Accepted responses, idempotency, stable workflow IDs, persistent checkpoints, crash recovery, and real-time SSE progress streaming.

---

### Key Architectural Implementations

#### 1. `EditSynthesizer` Engine (`backend/ai/services/edit_synthesizer.py`)
- **Search/Replace Block Editing**: Implemented constrained search/replace blocks inspired by SWE-agent and Aider rather than risky whole-file generation.
- **7-Stage Validation Pipeline**: Evaluates all edits strictly in memory before touching physical disk state:
  - **Stage A**: Structured JSON and markdown fence extraction.
  - **Stage B**: Exact single-match validation (`occurrences == 1`), rejecting ambiguous or zero-match search blocks.
  - **Stage C**: Path traversal prevention, `fnmatch` forbidden file detection (`.env*`, `*.pem`, `id_rsa*`, `.git/*`, secrets), and plan-bound scope enforcement.
  - **Stage D**: Atomic in-memory dry-run patch application with instant rollback.
  - **Stage E**: Language AST syntax verification (`ast.parse` for Python, `json.loads` for JSON).
  - **Stage F**: Lint verification prohibiting debug prints and placeholder comments (`// TODO`).
  - **Stage G**: SHA-256 stale-content fingerprint verification against concurrent modifications.
- **Bounded Self-Refinement**: Governed by a hard ceiling of 3 total attempts (1 initial + up to 2 retries) with verbal error reinforcement.
- **Thread-Safe Synchronous Integration**: Provides `synthesize_sync` for direct execution loop integration.

#### 2. `AgentExecutionLoop` Integration (`backend/ai/services/agent_execution_loop.py`)
- **Payload Priority**: Caller-supplied payload for a specific plan step retains highest priority.
- **Elimination of Cross-Step Reuse**: Completely removed the legacy unsafe cross-step fallback loop (`for other_input in payload_map.values(): ...`), preventing payload cross-contamination between unrelated steps.
- **Autonomous Synthesis Dispatch**: Automatically triggers `EditSynthesizer.synthesize_sync` when modification payloads are omitted.
- **Extended Auditability**: Enriched `StepExecutionRecord` with `synthesis_attempts`, `patch_hashes`, `validation_status`, `changed_files`, and `failure_category`.

#### 3. Plan-Bound Edit Security (ADR-010 Compliance)
- Enforces 3 levels of defense-in-depth:
  - **Level 1**: Pre-execution approval gate and immutable plan hash verification.
  - **Level 2**: Synthesis-time scope gate rejecting any file not declared in `expected_files`.
  - **Level 3**: Post-execution `WorkspaceDiffVerifier` git diff inspection ensuring zero undeclared file modifications.

#### 4. Durable Workflow Architecture (`backend/ai/workflows/`)
- Created `workflow_models.py` and `autonomous_task_workflow.py` with 7 durable steps decorated with `@dbos_step()` and `@dbos_workflow()`:
  - `step_validate_approval`
  - `step_initialize_workspace`
  - `step_execute_plan_and_synthesize`
  - `step_validate_plan_bound_diff`
  - `step_run_tests_and_repair`
  - `step_run_independent_verification`
  - `step_publish_draft_pr_if_authorized`
- **Idempotency & Stable Workflow IDs**: Workflow IDs formatted as `wf-{task_id}-{uuid[:8]}` protected by re-entrant locking (`threading.RLock`) to prevent duplicate concurrent runs.
- **Durable Checkpointing**: Creates secret-scrubbed `TaskCheckpoint` records across each durable phase.

#### 5. REST API & Real-Time Event Streaming (`backend/app/api/v1/tasks.py`)
- **HTTP 202 Accepted**: `POST /api/v1/tasks/{task_id}/run-workflow` accepts `async_execution=True` (or `Prefer: respond-async` header) and immediately responds with `HTTP 202 Accepted` containing the tracking URL.
- **Status Endpoint**: `GET /api/v1/tasks/{task_id}/workflow-status` provides real-time progress percentage, completed steps, current active step, verification results, and PR details.
- **Redis PubSub Streaming**: Streams milestone events (`WORKFLOW_STARTED`, `STEP_SYNTHESIS_COMPLETED`, `DIFF_VALIDATION_COMPLETED`, etc.) to the Redis channel `platform_events` for SSE delivery.

#### 6. Frontend Studio Integration
- **`frontend/src/services/tasks.ts`**: Added `startAutonomousWorkflow` and `getWorkflowStatus`.
- **`frontend/src/pages/RepositoryTaskStudio.tsx`**: Updated `handleRunAutoPilot` to initiate asynchronous workflow execution with automatic fallback and state restoration across browser refreshes.

---

### Verification & Testing Results

- **Unit Tests (`backend/tests/test_edit_synthesizer.py`)**: 19/19 PASSED
- **Workflow & API Tests (`backend/tests/test_autonomous_task_workflow.py`)**: 6/6 PASSED
- **Existing Regression Suites**:
  - `test_meet_w3_all_days.py`: 19/19 PASSED
  - `test_week3_day3_day4_and_fixes.py`: 7/7 PASSED
  - `test_task_planner_and_executor_comprehensive.py`: 32/32 PASSED
- **Total Automated Backend Tests**: **83 passed**, 0 failed (100% pass rate)
- **Frontend Build**: Verified clean (`tsc -b && vite build` completed with 0 errors).

---

### Documentation Created & Updated
- `Docs/autonomous-execution/00-existing-architecture-audit.md`
- `Docs/autonomous-execution/01-requirements-and-scope.md`
- `Docs/autonomous-execution/02-research-and-technical-decisions.md`
- `Docs/autonomous-execution/03-edit-synthesizer-architecture.md`
- `Docs/autonomous-execution/04-patch-validation-and-application.md`
- `Docs/autonomous-execution/05-plan-bound-edit-security.md`
- `Docs/autonomous-execution/06-self-refinement-and-budget.md`
- `Docs/autonomous-execution/07-durable-workflow-architecture.md`
- `Docs/autonomous-execution/08-api-and-frontend-integration.md`
- `Docs/autonomous-execution/09-database-and-audit.md`
- `Docs/autonomous-execution/10-testing-and-validation.md`
- `Docs/autonomous-execution/11-implementation-changelog.md`
- `Docs/autonomous-execution/12-future-candidate-patch-selection.md`
- `Docs/autonomous-execution/13-operations-and-troubleshooting.md`
- `Docs/autonomous-execution/README.md`
- `Docs/engineering/13_architecture_decisions.md` (ADR-015 added)
- `Docs/engineering/14_changelog.md` (Updated)
- `Docs/README.md` (Updated)

