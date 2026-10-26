# Week 3 Day 1 Architecture & Persistence Audit Report

**Owner:** Om (Database & Persistence Lead)  
**Milestone:** Week 3 — Workflow Automation, GitHub Ecosystem & Production Hardening  
**Status:** 🟢 Complete & Fully Verified (100/100 Total Persistence Tests Passing — 100% Pass Rate)  
**Date:** Week 3 Day 1  
**Branch:** `feature/W3-day1-om-persistence-architecture`  

---

## 1. Executive Summary

As the Database & Persistence Lead for the AI-Powered Software Development Platform, Om executed the mandatory **Day 1 Architecture, Contracts, and Dependencies** deliverables for Week 3 specified in [`Docs/week3.md`](file:///c:/Users/DC/OneDrive/Desktop/AI-Powered-Software-Development-Platform/Docs/week3.md) (§5, §6 F39, §7, §8) and [`Docs/daily_tasks.md`](file:///c:/Users/DC/OneDrive/Desktop/AI-Powered-Software-Development-Platform/Docs/daily_tasks.md):

1. **Existing Codebase Audit:** Audited existing data models, Alembic migrations, query repositories, and event storage in `backend/app/models/`, `backend/migrations/`, and `backend/app/repositories/`.
2. **Table Mapping & Gap Analysis:** Mapped existing Week 1 and Week 2 tables (`users`, `repositories`, `analysis_runs`, `analysis_findings`) to the Week 3 automated development lifecycle, identifying all missing persistence and recovery fields.
3. **Issue-to-Task Persistence & Foreign Keys:** Designed and implemented relational foreign keys connecting Week 2 defects (`analysis_findings.id`) and GitHub issues to `tasks`.
4. **Week 3 Workflow Schema & ORM Models:** Implemented all 12 core persistence entities in [`app/models/task.py`](file:///c:/Users/DC/OneDrive/Desktop/AI-Powered-Software-Development-Platform/backend/app/models/task.py).
5. **Linear Alembic Migration:** Authored migration [`b3c4d5e6f7a8_add_workflow_automation_tables.py`](file:///c:/Users/DC/OneDrive/Desktop/AI-Powered-Software-Development-Platform/backend/migrations/versions/b3c4d5e6f7a8_add_workflow_automation_tables.py), extending the acyclic 6-node chain to a 7-node chain with zero cycles and full downgrade capability.
6. **TaskRepository Query Layer:** Implemented [`app/repositories/task_repository.py`](file:///c:/Users/DC/OneDrive/Desktop/AI-Powered-Software-Development-Platform/backend/app/repositories/task_repository.py) providing strict state-transition validation (§7.1, §7.2), plan versioning, immutable approvals, approval invalidation upon plan edits, bounded repair counters (maximum 3 attempts), automated credential scrubbing, and ordered audit timelines.
7. **Canonical Pydantic Schemas:** Implemented [`app/schemas/task.py`](file:///c:/Users/DC/OneDrive/Desktop/AI-Powered-Software-Development-Platform/backend/app/schemas/task.py) establishing Day 1 agreed contracts (§7.3, §7.4).
8. **Automated Test Suite:** Created [`backend/tests/test_om_w3_d1_persistence.py`](file:///c:/Users/DC/OneDrive/Desktop/AI-Powered-Software-Development-Platform/backend/tests/test_om_w3_d1_persistence.py) with 13 comprehensive test cases. All 13 pass synchronously, with 0 regressions across all 87 Week 2 persistence tests.

---

## 2. Existing Codebase Audit & Gap Analysis

### 2.1. Audit of Pre-Existing State (Weeks 1 & 2)

Prior to Week 3 Day 1, the persistence layer supported:
- **Week 1:** Identity (`users`, `github_installations`, `repositories`), AST extraction (`repository_files`, `code_symbols`, `symbol_edges`), Vector RAG (`code_chunks`, `memory_entries`), and sync workers (`sync_jobs`).
- **Week 2:** Developer Intelligence Suite (`analysis_runs` and `analysis_findings`), supporting Code Explanation, Bug Detection, Test Generation, and Standalone AI Code Review.

### 2.2. Identified Gaps for Week 3 Workflow Automation

| Required Week 3 Capability | Pre-Existing Mechanism | Gap Identified | Remediation Implemented |
|---|---|---|---|
| **Issue-to-Task Traceability** | `AnalysisFinding` existed in isolation | No relational link between findings/issues and actionable tasks | Added `finding_id` foreign key (`tasks.finding_id -> analysis_findings.id`) with `ON DELETE SET NULL` |
| **Task State Machine** | Only `AnalysisRunStatus` (`PENDING`, `RUNNING`, `COMPLETED`, `FAILED`) | No workflow states (`PLANNING`, `PENDING_APPROVAL`, `APPROVED`, `WORKSPACE_SETUP`, `EXECUTING`, `TESTING`, `REPAIRING`, `VERIFYING`, `READY_FOR_PUBLICATION`, `PUBLISHING`, `DRAFT_PR_CREATED`) | Added `TaskStatus` enum & server-enforced `VALID_TRANSITIONS` table |
| **Plan Versioning & Approvals** | Static LLM prompts without versions | No record of plan steps, versions, or human approval records | Created `task_plans` (versioned) and `task_approvals` (immutable decisions) |
| **Isolated Workspace State** | None | No tracking of workspace directory paths, task branches, or cleanup timestamps | Created `workspaces` table with unique task constraint |
| **Tool Execution Auditing** | No tool routing tracking | No persistent audit trail of tool invocations, arguments, and outcomes | Created `tool_invocations` table with argument secret scrubbing |
| **Test Runs & Repair Loops** | None | No tracking of test exit codes, durations, or bounded repair attempts | Created `test_runs` and `repair_attempts` tables enforcing max 3 attempts ceiling |
| **Independent Verification** | Only raw review runs | No revision-bound verification gate recording passing/failing checks | Created `verification_results` tied strictly to `verified_revision` |
| **Worker Crash Recovery** | None | Worker crashes lost in-memory state, risked infinite loops or duplicate PRs | Created `task_checkpoints` with automated secret scrubbing |
| **Audit Timeline** | Ephemeral Redis SSE only | No persistent event log for dashboard reconstruction upon refresh | Created `task_events` recording ordered historical transitions |
| **GitHub Draft PR Publication** | None | No storage of Draft PR URLs, numbers, head branches, or SHAs | Created `task_pull_requests` table |

---

## 3. Entity-Relationship Architecture & Table Schema

### 3.1. Entity Map

```text
[repositories] <---------------------------+
  ^                                        |
  |                                        |
[tasks] ---------------------------> [users]
  |-- 1:N -> [task_plans]
  |-- 1:N -> [task_approvals] ---------> [users]
  |-- 1:1 -> [workspaces]
  |-- 1:N -> [task_executions]
  |-- 1:N -> [tool_invocations]
  |-- 1:N -> [test_runs]
  |-- 1:N -> [repair_attempts] (max 3)
  |-- 1:N -> [verification_results]
  |-- 1:N -> [task_checkpoints]
  |-- 1:N -> [task_events] ------------> [users]
  |-- 1:1 -> [task_pull_requests] -----> [repositories]
  |
  +-- FK -> [analysis_findings] (Issue-to-task relationship)
```

### 3.2. Detailed Entity Inventory (12 New Tables)

1. **`tasks`**:
   - `id`: UUID (PK, default `uuid4`)
   - `repository_id`: UUID (FK `repositories.id` ON DELETE CASCADE, indexed)
   - `user_id`: UUID (FK `users.id` ON DELETE SET NULL, indexed)
   - `finding_id`: UUID (FK `analysis_findings.id` ON DELETE SET NULL, indexed) — **Issue-to-task foreign key**
   - `title`: String(512), `description`: Text
   - `status`: String(32), default `"CREATED"`
   - `source_type`: String(64), default `"GITHUB_ISSUE"`
   - `source_id`: String(256), `source_metadata`: JSONB
   - `base_revision`: String(128), default `"main"`
   - `plan_version`: Integer, default 1
   - `approved_plan_version`: Integer, nullable
   - `repair_attempts_used`: Integer, default 0
   - `repair_attempts_max`: Integer, default 3
   - `created_at`, `updated_at`: DateTime(timezone=True)
   - Composite indexes: `ix_tasks_repo_status`, `ix_tasks_repo_created`, `ix_tasks_repo_source`

2. **`task_plans`**:
   - `id`: UUID (PK), `task_id`: UUID (FK `tasks.id` CASCADE)
   - `version`: Integer, `base_revision`: String(128)
   - `summary`: String(512), `problem_statement`: Text
   - `steps`: JSONB (ordered array of step objects)
   - `expected_files`, `tests_to_run`, `risks`: JSONB
   - `validation_strategy`: Text, `status`: String(32)
   - Composite index: `ix_task_plans_task_version` (`task_id`, `version`, UNIQUE)

3. **`task_approvals`**:
   - `id`: UUID (PK), `task_id`: UUID (FK `tasks.id` CASCADE)
   - `plan_version`: Integer
   - `user_id`: UUID (FK `users.id` SET NULL)
   - `decision`: String(32) (`"APPROVED"` / `"REJECTED"`)
   - `feedback`: Text, `created_at`: DateTime(timezone=True)
   - Composite index: `ix_task_approvals_task_plan` (`task_id`, `plan_version`)

4. **`workspaces`**:
   - `id`: UUID (PK), `task_id`: UUID (FK `tasks.id` CASCADE, UNIQUE)
   - `workspace_path`: String(1024), `task_branch`: String(256)
   - `base_revision`: String(128), `current_revision`: String(128)
   - `status`: String(32), `cleanup_at`: DateTime(timezone=True)

5. **`task_executions`**:
   - `id`: UUID (PK), `task_id`: UUID (FK `tasks.id` CASCADE)
   - `attempt_number`: Integer, `worker_id`: String(128)
   - `status`: String(32), `started_at`, `completed_at`, `error_message`

6. **`tool_invocations`**:
   - `id`: UUID (PK), `task_id`: UUID (FK `tasks.id` CASCADE)
   - `tool_name`: String(128), `sanitized_arguments`: JSONB (scrubbed)
   - `status`: String(32), `duration_ms`: Integer, `output_summary`: Text

7. **`test_runs`**:
   - `id`: UUID (PK), `task_id`: UUID (FK `tasks.id` CASCADE)
   - `command`: String(512), `status`: String(32), `exit_code`: Integer
   - `duration_ms`: Integer, `tests_total`, `tests_passed`, `tests_failed`
   - `sanitized_output`: Text, `target_revision`: String(128)

8. **`repair_attempts`**:
   - `id`: UUID (PK), `task_id`: UUID (FK `tasks.id` CASCADE)
   - `attempt_number`: Integer (1 to 3), `failure_classification`: String(128)
   - `diagnosis`: Text, `applied_patch`: Text, `result`: String(32)
   - Composite index: `ix_repair_attempts_task_attempt` (`task_id`, `attempt_number`, UNIQUE)

9. **`verification_results`**:
   - `id`: UUID (PK), `task_id`: UUID (FK `tasks.id` CASCADE)
   - `verified_revision`: String(128)
   - `status`: String(32), `checks`: JSONB, `blocking_findings`: JSONB
   - `warnings`: JSONB, `summary`: Text

10. **`task_checkpoints`**:
    - `id`: UUID (PK), `task_id`: UUID (FK `tasks.id` CASCADE)
    - `step_name`: String(128), `state_data`: JSONB (automatically scrubbed)
    - `recovery_instructions`: Text

11. **`task_events`**:
    - `id`: UUID (PK), `task_id`: UUID (FK `tasks.id` CASCADE)
    - `event_type`: String(64), `event_data`: JSONB (scrubbed)
    - `user_id`: UUID (FK `users.id` SET NULL)
    - Composite index: `ix_task_events_task_created` (`task_id`, `created_at`)

12. **`task_pull_requests`**:
    - `id`: UUID (PK), `task_id`: UUID (FK `tasks.id` CASCADE, UNIQUE)
    - `repository_id`: UUID (FK `repositories.id` CASCADE)
    - `github_pr_id`, `pr_number`: Integer
    - `pr_url`: String(512), `base_branch`: String(256), `head_branch`: String(256)
    - `head_sha`: String(128), `is_draft`: Boolean, `title`, `body`

---

## 4. State-Transition Specification & Enforcement (§7.1, §7.2)

The `TaskRepository.transition_status()` method enforces strict transition rules:

```text
CREATED -> PLANNING -> PENDING_APPROVAL -> APPROVED -> WORKSPACE_SETUP -> EXECUTING -> TESTING -> VERIFYING -> READY_FOR_PUBLICATION -> PUBLISHING -> DRAFT_PR_CREATED
                                  \            |                                           ^           |
                                   \-> REJECTED|                                           |-> REPAIR  |
                                               v                                           |   (max 3) |
                                            PLANNING <-------------------------------------+-----------+
```

### Enforced Invariants:
1. **Approval Gate:** `PENDING_APPROVAL` can transition only to `APPROVED` or `REJECTED`. Any attempt to transition directly to `EXECUTING` is rejected with `InvalidStateTransitionError`.
2. **Rejection Safety:** A `REJECTED` plan cannot be executed; it must return to `PLANNING` before any re-approval.
3. **Approval Invalidation:** Saving a new plan version while a task has an approved version automatically clears `approved_plan_version` and requires renewed approval.
4. **Repair Ceiling:** Transitions to `REPAIRING` are blocked once `repair_attempts_used >= repair_attempts_max` (3). Attempt 4 triggers `RETRY_EXHAUSTED` and sets task status to `FAILED`.
5. **Zero Silent Success:** Failures, timeouts, and policy violations trigger explicit `FAILED`, `BLOCKED`, or `RECOVERY_REQUIRED` states.

---

## 5. Security & Zero-Credential Persistence Invariant

All data entering `task_checkpoints`, `tool_invocations`, `test_runs`, and `task_events` passes through recursive sanitization (`scrub_sensitive_data`):
- **API Keys:** `sk-proj-*`, `sk-ant-*` -> `[REDACTED]`
- **GitHub Tokens:** `ghp_*`, `gho_*`, `ghu_*`, `ghs_*`, `github_pat_*` -> `[REDACTED]`
- **AWS Keys:** `AKIA*`, `ASIA*` -> `[REDACTED]`
- **JWT Tokens:** `eyJ...` -> `[REDACTED]`
- **Database Connection URIs:** `postgresql://user:pass@host:5432/db` -> `postgresql://user:[REDACTED]@host:5432/db`
- **Private Keys & Password Assignments:** Scrubbed before write.

---

## 6. Migration Continuity Verification

The Alembic migration chain was validated via automated test `test_alembic_chain_linear_and_unbroken_up_to_head`:

```text
24498ac67b3e (pgvector extension)
     |
     v
5f6dc031921b (identity schema: users, installations, repositories)
     |
     v
aef3bb17eb34 (content tables: files, symbols, edges, chunks)
     |
     v
cb4e2a7d0f31 (sync jobs tracking)
     |
     v
e7b8c9d0f1a2 (memory entries & chunk vector enhancements)
     |
     v
f1c2d3e4b5a6 (developer intelligence: analysis runs & findings)
     |
     v
b3c4d5e6f7a8 (Week 3 Day 1: workflow automation, tasks, plans, checkpoints) [HEAD]
```

- Exactly 7 migration nodes in linear sequence.
- Zero cycles, zero orphaned nodes, zero split heads.
- Full `upgrade()` and `downgrade()` symmetry.

---

## 7. Automated Test Suite Results

All 13 Day 1 tests passed synchronously:

```text
backend\tests\test_om_w3_d1_persistence.py .............                 [100%]
======================== 13 passed, 1 warning in 1.49s ========================
```

### Test Breakdown (`test_om_w3_d1_persistence.py`)

| Test Method | Category | Verified Acceptance Invariant | Status |
|---|---|---|---|
| `test_task_instantiation_and_defaults` | Model Schema | Verifies Task model defaults, fields, and canonical §7.3 `to_dict()` envelope | 🟢 Pass |
| `test_create_task_from_week2_bug_finding` | Issue-to-Task | Foreign key linking `AnalysisFinding` to `Task`, reverse `finding.tasks` relationship | 🟢 Pass |
| `test_create_task_from_cross_repository_finding_rejected` | Isolation | Multi-tenant defense: cannot link Repo A finding to Repo B task | 🟢 Pass |
| `test_finding_deletion_preserves_task_with_null_finding_id` | Referentials | Deleting finding sets `task.finding_id = NULL` (ON DELETE SET NULL); history intact | 🟢 Pass |
| `test_cross_repository_task_access_blocked` | Multi-Tenancy | Repo A task is never returned via Repo B lookups or lists | 🟢 Pass |
| `test_happy_path_state_progression` | State Machine | Valid full lifecycle: CREATED -> PLANNING -> PENDING_APPROVAL -> APPROVED -> WORKSPACE_SETUP -> EXECUTING -> TESTING -> VERIFYING -> READY_FOR_PUBLICATION -> PUBLISHING -> DRAFT_PR_CREATED | 🟢 Pass |
| `test_direct_execution_from_pending_approval_blocked` | Security Gate | Blocked: PENDING_APPROVAL cannot jump directly to EXECUTING | 🟢 Pass |
| `test_rejected_plan_cannot_be_executed` | Security Gate | Blocked: REJECTED plan cannot transition to EXECUTING | 🟢 Pass |
| `test_plan_revision_invalidates_previous_approval` | Plan Versioning | Editing plan increments version to 2 and invalidates previous approval | 🟢 Pass |
| `test_repair_budget_exhaustion_at_maximum_three_attempts` | Repair Limits | Attempts 1, 2, 3 succeed; Attempt 4 triggers RETRY_EXHAUSTED and fails task | 🟢 Pass |
| `test_checkpoint_persistence_and_secret_redaction` | Security & Privacy | Automated scrubbing of API keys, GitHub tokens, and DB URIs in checkpoints | 🟢 Pass |
| `test_task_deletion_cascades_to_all_child_entities` | Referentials | Deleting Task cascades to all 11 child tables cleanly | 🟢 Pass |
| `test_alembic_chain_linear_and_unbroken_up_to_head` | Migrations | Unbroken 7-node Alembic migration chain with `b3c4d5e6f7a8` as head | 🟢 Pass |

### Total Persistence Suite Summary
- **Week 2 Persistence Tests:** 87 / 87 passing
- **Week 3 Day 1 Persistence Tests:** 13 / 13 passing
- **Total:** **100 / 100 tests passing (100% pass rate, 0 failures)**

---

## 8. Day 1 Sign-Off & Handoff for Days 2–5

With the completion of Om's Day 1 deliverables:
- **Meet (Task Planner):** Can now generate plans against `TaskPlan` and call `TaskRepository.save_plan()` on Day 2.
- **Yug (API Orchestration):** Can bind FastAPI routes (`/api/v1/tasks/*`) directly to `TaskRepository` and Pydantic schemas in `app.schemas.task`.
- **Parth (GitHub Integration):** Can link GitHub issues to `Task.source_id` / `source_metadata` and save draft PRs using `record_pull_request()`.
- **Prit (Workspace) & Devu (Tool Router):** Have dedicated tables (`workspaces`, `tool_invocations`) with foreign keys and sanitized argument logging ready.
- **Dev (Verification) & Keval (QA):** Have revision-bound verification tables (`verification_results`) and a clean test database ready.
