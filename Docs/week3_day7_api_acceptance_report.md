# Week 3 Day 7 Final API, Security & Workflow Acceptance Report

**Owner:** Yug Malaviya (API & Workflow Orchestration Lead)  
**Target Milestone:** Week 3 — Planning, Approval, Isolated Execution, Bounded Self-Repair, Independent Verification & GitHub Draft PR Workflow (`F31`–`F39`)  
**Status:** **ACCEPTED (`0` Blocking Defects, Full 17-Step Workflow Verified)**

---

## 1. Executive Summary

Week 3 transforms the platform from an advisory code-intelligence assistant into a **human-governed, sandboxed software engineering workflow system**. Across Days 1–7, we implemented and verified the complete 17-step lifecycle from issue or finding intake to a verified **GitHub Draft Pull Request**:

1. **Issue & Task Intake (`F31`, `F32`)**: Segregates `requirements`, `assumptions`, and `constraints` (including `forbidden_files` disjointness and path-traversal rejection) with full traceability to GitHub Issues and Week 2 Bug/Review findings.
2. **Structured Implementation Planning & Human Approval Gate (`F32`, `ADR-010`)**: Synthesizes versioned `TaskPlan` records (`plan_version`, cryptographic `plan_hash`, `base_revision`, ordered `steps`, `expected_files`, `tests_to_run`, `risks`, `resource_budget`) and enforces server-side human approval (`verify_execution_approval_gate`) before any workspace provisioning or tool execution. Any plan revision or base-revision change automatically invalidates prior approvals.
3. **Isolated Workspace & Controlled Tool Routing (`F33`, `F34`, `ADR-007`)**: Provisions per-task sandboxes (`.workspaces/task-<id>`) on dedicated branches (`agent/task-<id>`), confines all file operations via `WorkspacePathGuard`, blocks shell interpolation and network egress, and enforces strict command allowlists (`pytest`, `git status/diff/log`, `ruff`, `npm test`).
4. **Restricted Test Runner & Bounded Self-Repair (`F35`, `ADR-009`)**: Executes project test suites inside the isolated sandbox, classifies failures (`TEST_FAILURE` vs `INFRASTRUCTURE_ERROR` vs `TIMEOUT`), and runs a bounded self-repair loop capped at **3 task-level attempts** with duplicate-patch cycle detection.
5. **Independent Verification & Final Review (`F36`)**: Evaluates modified workspace files independently across 5 gates (`tests`, `diff_scope`, `secret_scan`, Week 2 `static_analysis` via `BuiltinStaticBugScanner` + `ASTBugAnalyzer`, and `ai_code_review` via `RequirementToCodeVerifier`) bound to `verified_revision` and a SHA-256 diff fingerprint (`verification_diff_hash`).
6. **Git Branch, Commit, Push & Draft PR Publication (`F37`, `ADR-010`)**: Enforces protected-branch guards (`main`, `master`, `production`, `develop`, `release`), post-verification diff immutability, stale base-revision detection, and explicit human publication authorization (`publication_authorized=True`) before committing, pushing, and creating a GitHub Draft PR (`is_draft=True`, zero auto-merge).
7. **Checkpoints, Crash Recovery & Audit Timeline (`F38`, `F39`)**: Persists secret-scrubbed `TaskCheckpoint` snapshots, reconciles interrupted tasks/workspaces on startup (`reconcile_interrupted_tasks()`) and operator request (`POST /recover`) without resetting `repair_attempts_used`, and logs every state transition and tool invocation in an ordered `TaskEvent` timeline.

---

## 2. Week 3 Canonical API Route Inventory

| Endpoint | Method | Feature | Auth / Tenant Guard | Rate Limit | Description |
| :--- | :---: | :---: | :---: | :---: | :--- |
| `/api/v1/repositories/{repo_id}/issues` | `GET` | `F31` | JWT + Repo Owner | — | List/sync candidate GitHub issues with import status |
| `/api/v1/repositories/{repo_id}/issues` | `POST` | `F31` | JWT + Repo Owner | 20/min/user | Create GitHub issue from Week 2 finding (+ optional task) |
| `/api/v1/repositories/{repo_id}/issues/import` | `POST` | `F31` | JWT + Repo Owner | 20/min/user | Idempotently import GitHub issue into a Week 3 `Task` |
| `/api/v1/tasks` | `POST` | `F32` | JWT + Repo Owner | 30/min/user | Create task with segregated requirements, assumptions, constraints |
| `/api/v1/tasks` | `GET` | `F38` | JWT + User Scope | — | List tasks with repository, status, and search filters |
| `/api/v1/tasks/{task_id}` | `GET` | `F32` | JWT + Task Owner | — | Get task detail, latest plan, and immutable approval history |
| `/api/v1/tasks/{task_id}/plan` | `POST` | `F32` | JWT + Task Owner | 15/min/user | Generate or revise structured plan (`plan_version++`) |
| `/api/v1/tasks/{task_id}/plan` | `GET` | `F32` | JWT + Task Owner | — | Retrieve latest or specified `plan_version` |
| `/api/v1/tasks/{task_id}/approve` | `POST` | `F32` | JWT + Task Owner | — | Record immutable human approval bound to `(plan_version, plan_hash)` |
| `/api/v1/tasks/{task_id}/reject` | `POST` | `F32` | JWT + Task Owner | — | Reject current plan version with reviewer feedback |
| `/api/v1/tasks/{task_id}/execute` | `POST` | `F33/F34` | JWT + Approval Gate | 20/min/user | Verify approval gate, provision workspace, and execute steps |
| `/api/v1/tasks/{task_id}/pause` | `POST` | `F33` | JWT + Task Owner | — | Pause active workspace execution (`IN_USE -> STOPPED`) |
| `/api/v1/tasks/{task_id}/resume` | `POST` | `F33` | JWT + Approval Gate | — | Resume paused workspace execution (`STOPPED -> IN_USE`) |
| `/api/v1/tasks/{task_id}/cancel` | `POST` | `F33` | JWT + Task Owner | — | Cancel non-terminal task and stop workspace |
| `/api/v1/tasks/{task_id}/workspace` | `GET` | `F33` | JWT + Task Owner | — | Inspect isolated workspace status, branch, and resource limits |
| `/api/v1/tasks/{task_id}/diff` | `GET` | `F36` | JWT + Task Owner | — | Extract modified files and unified git diff from workspace |
| `/api/v1/tasks/{task_id}/tools/{tool_name}` | `POST` | `F34` | JWT + Approval Gate | 20/min/user | Invoke policy-guarded sandbox tool via `ToolRouter` |
| `/api/v1/tasks/{task_id}/tests` | `GET/POST` | `F35` | JWT + Task Owner | 20/min/user | Trigger or inspect restricted sandbox test runs |
| `/api/v1/tasks/{task_id}/repair-budget` | `GET` | `F35` | JWT + Task Owner | — | Get server-authoritative 3-attempt self-repair budget status |
| `/api/v1/tasks/{task_id}/repair` | `POST` | `F35` | JWT + Task Owner | 20/min/user | Trigger bounded self-repair cycle (`max 3` task-level attempts) |
| `/api/v1/tasks/{task_id}/verify` | `POST` | `F36` | JWT + Approval Gate | 20/min/user | Run independent 5-gate verification over workspace diff |
| `/api/v1/tasks/{task_id}/verification` | `GET` | `F36` | JWT + Task Owner | — | Get latest `VerificationResult` bound to `verified_revision` |
| `/api/v1/tasks/{task_id}/branch` | `POST` | `F37` | JWT + Approval Gate | 20/min/user | Ensure isolated branch `agent/task-<id>` & block protected branches |
| `/api/v1/tasks/{task_id}/commit` | `POST` | `F37` | JWT + Approval Gate | 20/min/user | Stage & commit validated workspace changes with task trailers |
| `/api/v1/tasks/{task_id}/push` | `POST` | `F37` | JWT + Pub Auth Gate | 20/min/user | Push verified branch (`publication_authorized=True` required) |
| `/api/v1/tasks/{task_id}/create-pr` (`/publish`) | `POST` | `F37` | JWT + Pub Auth Gate | 20/min/user | Create GitHub Draft PR (`is_draft=True`, zero auto-merge) |
| `/api/v1/tasks/{task_id}/pull-request` | `GET` | `F37` | JWT + Task Owner | — | Get published `TaskPullRequestResponse` metadata |
| `/api/v1/tasks/{task_id}/checkpoints` | `GET/POST` | `F39` | JWT + Task Owner | 20/min/user | Save or list secret-scrubbed recovery checkpoints |
| `/api/v1/tasks/{task_id}/recover` | `POST` | `F39` | JWT + Task Owner | 20/min/user | Reconcile interrupted/failed task preserving `repair_attempts_used` |
| `/api/v1/tasks/{task_id}/invariants` | `GET` | `F39` | JWT + Task Owner | — | Validate sandbox path confinement, disk quota & diff immutability |
| `/api/v1/tasks/{task_id}/run-workflow` | `POST` | `F31–F39` | JWT + Approval Gate | 20/min/user | Execute autonomous post-approval pipeline end-to-end |
| `/api/v1/tasks/{task_id}/events` | `GET` | `F38` | JWT + Task Owner | — | Retrieve ordered audit timeline events |

---

## 3. Security & Policy Gate Verification Matrix

| Security / Governance Gate | Expected Behavior | HTTP Status & Error Code | Verification Test |
| :--- | :--- | :---: | :--- |
| **Unapproved Execution Bypass (`ADR-010`)** | Reject `/execute` or `/tools/*` when `status != APPROVED` or `approved_plan_version != plan_version` | `403 APPROVAL_REQUIRED` / `409 PLAN_VERSION_MISMATCH` | `test_yug_w3_day3_day4_execution_and_repair.py` |
| **Plan Tampering / Base Drift (`F32`)** | Recompute SHA-256 `plan_hash` on execution & check remote HEAD drift before push/PR | `409 PLAN_VERSION_MISMATCH` | `test_yug_w3_day5_day6_day7_acceptance.py` |
| **Protected File Modification (`F34`)** | Block `write_file`/`patch_file`/`delete_file` and fail verification if `forbidden_files` touched | `403 POLICY_VIOLATION` | `test_yug_w3_day3_day4_execution_and_repair.py` |
| **Disallowed Command Execution (`F34`)** | Reject shell commands outside `DEFAULT_COMMAND_ALLOWLIST` or containing metacharacters | `403 COMMAND_NOT_ALLOWED` | `test_yug_w3_day3_day4_execution_and_repair.py` |
| **Bounded Repair Ceiling (`F35`, `ADR-009`)** | Halt repair after 3 attempts (`repair_attempts_used >= 3`) and transition task to `FAILED` | `409 RETRY_BUDGET_EXHAUSTED` | `test_yug_w3_day3_day4_execution_and_repair.py` |
| **Secret Leak / Out-of-Scope Diff (`F36`)** | Fail `POST /verify`, redact raw secrets (`[REDACTED]`), and block publication | `409 VERIFICATION_FAILED` | `test_yug_w3_day5_day6_day7_acceptance.py` |
| **Post-Verification Diff Mutation (`F36/F37`)** | Invalidate verification if workspace diff hash changes after `POST /verify` | `409 VERIFICATION_FAILED` | `test_yug_w3_day5_day6_day7_acceptance.py` |
| **Unauthorized Publication (`F37`, `ADR-010`)** | Block `/push` and `/create-pr` unless `publication_authorized=True` | `403 PUBLICATION_AUTHORIZATION_REQUIRED` | `test_yug_w3_day5_day6_day7_acceptance.py` |
| **Protected Branch Push/Commit (`F37`)** | Block `main`, `master`, `production`, `develop`, `release` on `/branch`, `/commit`, `/push`, `/create-pr` | `403 POLICY_VIOLATION` | `test_yug_w3_day5_day6_day7_acceptance.py` |
| **Crash Recovery Budget Integrity (`F39`)** | Reconcile interrupted tasks to `RECOVERY_REQUIRED` without resetting `repair_attempts_used` | `200 OK` | `test_yug_w3_day5_day6_day7_acceptance.py` |
| **Cross-Tenant Isolation (`F38/F39`)** | Block User B from reading or mutating User A's tasks, plans, diffs, verification, or PRs | `404 TASK_NOT_FOUND` | `test_yug_w3_day5_day6_day7_acceptance.py` |
