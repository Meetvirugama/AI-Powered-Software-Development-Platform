# Week 3 Day 2 Task Planning & Approval Persistence Report

**Owner:** Om (Database & Persistence Lead)  
**Milestone:** Week 3 — Workflow Automation, GitHub Ecosystem & Production Hardening  
**Status:** 🟢 Complete & Fully Verified (15/15 Day 2 Tests Passing, 28/28 Total Week 3 Tests Passing, 115/115 Total Persistence Tests Passing)  
**Date:** Week 3 Day 2  
**Branch:** `feature/W3-day2-om-planning-persistence`  

---

## 1. Executive Summary

As the Database & Persistence Lead for the AI-Powered Software Development Platform, Om executed the mandatory **Day 2 Task Planning, Plan Versioning & Human Approval Persistence** deliverables specified in [`Docs/week3.md`](file:///c:/Users/DC/OneDrive/Desktop/AI-Powered-Software-Development-Platform/Docs/week3.md) (§5, §6 F32, §6 F39, §7, §8) and [`Docs/daily_tasks.md`](file:///c:/Users/DC/OneDrive/Desktop/AI-Powered-Software-Development-Platform/Docs/daily_tasks.md):

1. **Plan Versioning & Supersession:** Enhanced `TaskRepository.save_plan()` to automatically compute monotonic plan versions ($v_1, v_2, \dots$), transition older proposed/approved plans to `SUPERSEDED`, invalidate prior approvals, and advance or reset task status to `PENDING_APPROVAL`.
2. **Immutable Approval & Rejection Query Layer:** Implemented `TaskRepository.approve_plan()`, `reject_plan()`, `get_approval()`, and `list_approvals()`, strictly verifying plan versions and immutably recording decisions and human feedback.
3. **Plan Inspection & History Queries:** Implemented `TaskRepository.get_plan()` (supporting both latest version and specific version lookups) and `list_plans()` (returning all versions ordered ascending), strictly scoped to authorized repositories.
4. **Context Gathering Persistence:** Implemented `TaskRepository.update_task_context()` connecting Week 2 intelligence context to tasks, with recursive credential scrubbing and audit event generation.
5. **Canonical Model Envelopes:** Implemented `to_dict()` methods across `TaskPlan`, `TaskApproval`, `Workspace`, `TaskCheckpoint`, `TaskEvent`, and `TaskPullRequest`, guaranteeing exact alignment with Day 1 Pydantic response schemas (`TaskPlanResponse`, `TaskApprovalResponse`, etc.).
6. **High-Level Orchestration Service:** Created [`backend/app/services/task_history_service.py`](file:///c:/Users/DC/OneDrive/Desktop/AI-Powered-Software-Development-Platform/backend/app/services/task_history_service.py) (`TaskHistoryService`), providing session-managed orchestration, multi-tenant isolation, credential scrubbing, and exported in `backend/app/services/__init__.py`.
7. **Application State Integration:** Mounted `TaskHistoryService` into FastAPI application state (`app.state.task_history_service`) in [`backend/app/main.py`](file:///c:/Users/DC/OneDrive/Desktop/AI-Powered-Software-Development-Platform/backend/app/main.py).
8. **Automated Test Suite:** Created [`backend/tests/test_om_w3_d2_planning_persistence.py`](file:///c:/Users/DC/OneDrive/Desktop/AI-Powered-Software-Development-Platform/backend/tests/test_om_w3_d2_planning_persistence.py) with 15 comprehensive test cases. All 15 pass synchronously (100% pass rate) with 0 regressions across all 87 Week 2 and 13 Week 3 Day 1 persistence tests.

---

## 2. Invariants & Workflow State Machine Enforcement

### 2.1. Plan Versioning & Approval Invalidation (§6 F32, §7.2)

```text
[Task: CREATED / PLANNING]
           |
           | save_plan(v1)
           v
[Plan v1: PROPOSED] ----> [Task: PENDING_APPROVAL]
                               |
            +------------------+------------------+
            | approve_plan(v1)                    | reject_plan(v1)
            v                                     v
   [Plan v1: APPROVED]                   [Plan v1: REJECTED]
   [Task: APPROVED]                      [Task: REJECTED]
   [approved_plan_version = 1]           [approved_plan_version = None]
            |                                     |
            +------------------+------------------+
                               | save_plan(v2 - Revision)
                               v
                     [Plan v1: SUPERSEDED]
                     [Plan v2: PROPOSED]
                     [Task: PENDING_APPROVAL]
                     [approved_plan_version = None]  <-- Invalidated!
```

### 2.2. Key Architectural Guarantees:
1. **Specific Version Binding:** Approval records (`TaskApproval`) record the exact `plan_version` decided. If a user attempts to approve a nonexistent plan version (e.g. version 99), `PlanNotFoundError` is raised.
2. **Approval Invalidation:** When an approved or rejected plan is revised via `save_plan()`, the previous active plan is marked `SUPERSEDED`, `task.approved_plan_version` is cleared to `None`, and `task.status` is reset to `PENDING_APPROVAL`.
3. **Execution Gate:** Unapproved or rejected tasks cannot transition to `EXECUTING` (`InvalidStateTransitionError` is raised).
4. **Multi-Tenant Boundary:** A plan or approval belonging to Repository A is strictly invisible to Repository B lookups or mutations (`TaskNotFoundError` is raised).

---

## 3. Deliverables Inventory

| File | Component | Role / Deliverable |
|---|---|---|
| `backend/app/models/task.py` | ORM Models | Added `to_dict()` methods to `TaskPlan`, `TaskApproval`, `Workspace`, `TaskCheckpoint`, `TaskEvent`, and `TaskPullRequest` |
| `backend/app/repositories/task_repository.py` | Repository Layer | Implemented `get_plan()`, `list_plans()`, `get_approval()`, `list_approvals()`, `update_task_context()`, and supersession in `save_plan()` |
| `backend/app/services/task_history_service.py` | Service Layer | Implemented `TaskHistoryService` with session management and multi-tenant validation |
| `backend/app/services/__init__.py` | Package API | Exported `TaskHistoryService` |
| `backend/app/main.py` | Application Lifespan | Registered `app.state.task_history_service` |
| `backend/tests/test_om_w3_d2_planning_persistence.py` | Test Suite | 15 unit and integration tests verifying all Day 2 invariants |
| `Docs/daily_tasks.md` | Task Tracking | Updated checklist for Week 3 Day 2 |
| `Docs/persistence_week3_day2_report.md` | Formal Documentation | Published Day 2 persistence deliverable report |

---

## 4. Automated Test Suite Results

```text
backend\tests\test_om_w3_d2_planning_persistence.py ...............      [100%]
======================== 15 passed, 1 warning in 2.36s ========================
```

### Test Case Breakdown (`test_om_w3_d2_planning_persistence.py`)

| Test Method | Category | Verified Acceptance Invariant | Status |
|---|---|---|---|
| `test_task_creation_and_persistence_from_issue_and_requirement` | Intake | Creates task from GITHUB_ISSUE and USER_REQUIREMENT; records source traceability and emits initial event | 🟢 Pass |
| `test_plan_creation_advances_task_to_pending_approval` | Planning | Proposing Plan v1 creates record with status PROPOSED and transitions task to PENDING_APPROVAL | 🟢 Pass |
| `test_get_plan_latest_and_by_specific_version` | Retrieval | `get_plan()` retrieves specific version or latest version when version=None | 🟢 Pass |
| `test_list_plans_returns_all_versions_ordered` | Versioning | `list_plans()` returns all versions (v1, v2, v3) in strictly ascending order | 🟢 Pass |
| `test_approve_plan_tied_to_specific_version` | Approval | Approving plan v1 sets task status to APPROVED, records immutable decision, and logs PLAN_APPROVED event | 🟢 Pass |
| `test_reject_plan_tied_to_specific_version_with_feedback` | Rejection | Rejecting plan v1 sets task status to REJECTED with human feedback and logs PLAN_REJECTED event | 🟢 Pass |
| `test_approving_nonexistent_plan_version_raises_error` | Error Handling | Attempting to approve plan version 99 raises `PlanNotFoundError` | 🟢 Pass |
| `test_plan_revision_supersedes_prior_plans_and_resets_status` | Revision | Plan v2 supersedes Plan v1, invalidates previous approval, and resets task status to PENDING_APPROVAL | 🟢 Pass |
| `test_rejected_plan_cannot_be_executed` | Security Gate | Rejected plan cannot transition to EXECUTING (raises `InvalidStateTransitionError`) | 🟢 Pass |
| `test_cross_repository_plan_access_blocked` | Isolation | Multi-tenant defense: Repo A's plan cannot be fetched or listed via Repo B | 🟢 Pass |
| `test_cross_repository_approval_blocked` | Isolation | Multi-tenant defense: Repo B user cannot approve Repo A's plan | 🟢 Pass |
| `test_update_task_context_persists_and_scrubs` | Context | Updates task context summary from Week 2 intelligence and scrubs sensitive API keys | 🟢 Pass |
| `test_sensitive_data_scrubbed_in_plan_and_feedback` | Zero-Credential | Automated redaction of tokens (ghp_*, sk-*, eyJ*) in plan steps, problem statement, and approval feedback | 🟢 Pass |
| `test_task_history_service_full_lifecycle` | Service Orchestration | Verifies complete `TaskHistoryService` lifecycle: intake -> context -> plan -> approve -> timeline | 🟢 Pass |
| `test_model_to_dict_matches_pydantic_schemas` | Serialization | `to_dict()` outputs validate directly against `TaskResponse`, `TaskPlanResponse`, and `TaskApprovalResponse` | 🟢 Pass |

### Consolidated Persistence Test Suite
- **Week 2 Persistence Tests:** 87 / 87 passing
- **Week 3 Day 1 Persistence Tests:** 13 / 13 passing
- **Week 3 Day 2 Persistence Tests:** 15 / 15 passing
- **Total:** **115 / 115 tests passing (100% pass rate, 0 regressions)**

---

## 5. Handoff for Days 3–5

With Om's Day 2 deliverables complete:
- **Yug (API Orchestration):** Can wire `/api/v1/tasks/{id}/plan`, `/api/v1/tasks/{id}/approve`, and `/api/v1/tasks/{id}/reject` directly to `app.state.task_history_service`.
- **Meet (Task Planner):** Can call `service.save_plan()` to generate and revise implementation plans.
- **Dhramraj (Frontend):** Has stable contracts (`TaskPlanResponse`, `TaskApprovalResponse`) and timeline event streaming ready for the Plan Review UI.
- **Prit (Workspace) & Devu (Tool Router):** Can rely on the invariant that workspaces are only initialized for tasks with `TaskStatus.APPROVED`.

