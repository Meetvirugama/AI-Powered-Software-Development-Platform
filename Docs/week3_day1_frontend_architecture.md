# Week 3 Day 1 & Day 2 — Frontend Architecture & Integration Specification

**Assigned Owner:** Dharmraj
**Module Ownership:** Frontend Task Workflow, Intake, Plan Review, Approval & Execution Timeline (F38, F31, F32)
**Branch:** `Dharmraj06-W3-01-02-Task-Planning-Approval`
**Reference Document:** `Docs/week3.md` (Strictly excluding `Docs/daily_tasks.md`)

---

## 1. Executive Summary & Architecture Overview

The Week 3 Day 1 and Day 2 frontend deliverable establishes a production-grade, asynchronous task intake, plan review, approval governance, and audit timeline workflow for the AI-Powered Software Development Platform.

Because backend implementations for task orchestration (Yug), persistence (Om), planner engines (Meet), and GitHub integrations (Parth) evolve concurrently across Week 3, the frontend was architected with an **MSW-First (Mock Service Worker v2)** foundation. This enables the full interactive frontend application to be developed, thoroughly tested, and demonstrated end-to-end independently, while maintaining absolute contract compliance with backend schemas defined in `backend/app/schemas/task.py` and `backend/app/core/errors.py`.

### Key Architectural Pillars:
1. **Canonical State Integrity**: Full support for all 17 canonical `TaskStatus` states defined in `backend/app/schemas/task.py` without frontend deviations.
2. **Explicit Approval Governance**: Approval and rejection actions are strictly gated to `PENDING_APPROVAL` and bind explicitly to a specific `plan_version`. Plan revision automatically invalidates previous approvals.
3. **Execution Suppression in Day 1/2**: Execution triggers ("Run in Sandbox", "Execute", "Create Draft PR") are intentionally suppressed in the Day 1/2 user interface, preventing illegal state skips.
4. **Resilient Service & Query Layer**: Clean separation between presentation components, TanStack Query v5 hooks (`useTasks`), typed Axios services (`tasks.ts`), and centralized error normalization (`normaliseError`).
5. **Zero-Pollution MSW Engine**: Stateful in-memory mock API interceptor enabled strictly in development (`import.meta.env.DEV`) and Vitest environments, completely excluded from production builds.

---

## 2. Routing Hierarchy & Page Structure

All task workflow views integrate into the existing React Router v7 layout structure under the authenticated `/app` layout:

```
/app
 ├── /dashboard           -> Dashboard.tsx
 ├── /repositories        -> Repositories.tsx
 ├── /repositories/:id/*  -> Repository Workspace Studios (Chat, Explain, Bugs, Tests, Review)
 └── /tasks               -> Tasks.tsx (Task List view)
      ├── /new            -> CreateTask.tsx (Dual-mode intake: Manual Intake & GitHub Issue Import)
      └── /:taskId        -> TaskDetail.tsx (Task Detail, Plan Review, Approval History & Event Timeline)
```

### Route Specifications:
- **`/app/tasks`**:
  - Main task management dashboard.
  - Text search by task title and description.
  - Multi-status filter dropdown (supporting all 17 canonical states).
  - Repository filter dropdown linked to active user repositories.
  - Real-time empty states, skeleton loading indicators, and error/retry banners.
  - Direct navigation to `/app/tasks/new` and `/app/tasks/:taskId`.
- **`/app/tasks/new`**:
  - Two-mode tabbed interface:
    1. *Manual Task Intake*: Title, repository selector, markdown description, dynamic requirements list, dynamic assumptions, dynamic constraints, and target/forbidden files.
    2. *Import GitHub Issue*: Repository selection, candidate issue list retrieval with metadata preview, issue number input, and one-click import.
  - Client-side validation preventing empty requirements or overlapping target/forbidden files.
  - Automatic redirection to the generated task detail upon creation.
- **`/app/tasks/:taskId`**:
  - Comprehensive task view with persistent status header, repository linkage, and creation timestamps.
  - Tabbed or sectional layout presenting:
    1. *Task Intake Overview*: Original requirements, assumptions, constraints, and source issue reference.
    2. *Plan Review & Approval*: Structured display of current plan version, sequential steps, affected files, risks, mitigation strategies, and verification plan.
    3. *Plan Revision*: Prompt-driven plan regeneration input.
    4. *Approval History*: Chronological decision ledger tracking plan versions, approvers, timestamps, notes, and rejection reasons.
    5. *Execution Timeline*: Ordered audit stream of lifecycle events retrieved from `/api/v1/tasks/{task_id}/events`.

---

## 3. TypeScript Domain Models & Schemas

The frontend domain types in `frontend/src/types/task.ts` strictly adhere to backend definitions:

### 3.1. Canonical `TaskStatus` Enum (17 States)
```typescript
export type TaskStatus =
  | 'CREATED'
  | 'PLANNING'
  | 'PENDING_APPROVAL'
  | 'APPROVED'
  | 'REJECTED'
  | 'WORKSPACE_SETUP'
  | 'EXECUTING'
  | 'TESTING'
  | 'REPAIRING'
  | 'VERIFYING'
  | 'READY_FOR_PUBLICATION'
  | 'PUBLISHING'
  | 'DRAFT_PR_CREATED'
  | 'FAILED'
  | 'CANCELLED'
  | 'RECOVERY_REQUIRED'
  | 'BLOCKED';
```

### 3.2. Verified Backend Schemas (Mapped from `backend/app/schemas/task.py`)
- `TaskSourceReference`: Source type (`GITHUB_ISSUE` | `BUG_FINDING` | `REVIEW_FINDING` | `USER_PROMPT`), `issue_number`, `issue_url`, `finding_id`, `repository_id`, `base_revision`.
- `TaskRequirement`: Unique ID (`req-1`), description, category (`functional` | `bug_fix` | `refactor` | `security` | `test`), `target_files` (array of file paths), `acceptance_criteria` (array of criteria).
- `TaskAssumption`: Unique ID (`asm-1`), description, `unresolved` (boolean), `risk_level` (`low` | `medium` | `high`).
- `TaskConstraint`: Unique ID (`cst-1`), description, `constraint_type` (`protected_file` | `forbidden_dependency` | `backward_compatibility` | `resource_limit` | `security_policy`), `forbidden_files`, `forbidden_packages`, `max_budget_tokens`.
- `TaskCreateRequest` / `TaskIntakePayload`: Full intake payload with repository ID, title, description, source reference, requirements, optional assumptions, optional constraints, and optional base revision.
- `TaskDetailResponse`: Canonical representation of a task, including status, plan version, approved plan version, repair attempts used/max, timestamps, requirements, assumptions, constraints, and source reference.
- `VALID_TASK_TRANSITIONS` & `canTransition()`: Client-side representation of the transition state machine for anticipatory UI gating.

### 3.3. Provisional Contracts (Documented for Teammate Alignment)
- `TaskPlan` & `PlanStep`: Models sequential execution steps, target files, tool names (`editor`, `bash`, `git`), risk level (`low` | `medium` | `high`), risk mitigation, and verification strategy.
- `PlanApproval`: Models approval/rejection decision records with `plan_version`, `decision` (`approved` | `rejected`), `decided_at`, `decided_by`, and `notes`/`reason`.
- `TaskEvent`: Models audit timeline records with `id`, `task_id`, `event_type`, `created_at`, `actor`, and payload details.
- `IssueImportRequest` & `IssueImportResponse`: Maps `POST /api/v1/repositories/{repo_id}/issues/import`.

---

## 4. Service Layer & API Client Integration

All network requests route through `frontend/src/services/tasks.ts`, utilizing the application's shared Axios client (`apiClient` in `frontend/src/services/api.ts`). Page components never issue raw HTTP calls directly.

### 4.1. Endpoint Mapping Table
| Frontend Service Method | HTTP Method & Path | Primary Backend Owner |
|---|---|---|
| `listTasks(params)` | `GET /api/v1/tasks` | Yug / Om |
| `getTask(taskId)` | `GET /api/v1/tasks/{task_id}` | Yug / Om |
| `createTask(payload)` | `POST /api/v1/tasks` | Yug / Om |
| `getTaskPlan(taskId, version)` | `GET /api/v1/tasks/{task_id}/plan` | Meet / Yug |
| `generateTaskPlan(taskId, payload)`| `POST /api/v1/tasks/{task_id}/plan` | Meet / Yug |
| `approveTaskPlan(taskId, payload)` | `POST /api/v1/tasks/{task_id}/approve` | Meet / Om |
| `rejectTaskPlan(taskId, payload)`  | `POST /api/v1/tasks/{task_id}/reject` | Meet / Om |
| `getTaskEvents(taskId, params)` | `GET /api/v1/tasks/{task_id}/events` | Om |
| `importGitHubIssue(repoId, payload)`| `POST /api/v1/repositories/{repo_id}/issues/import` | Parth / Yug |
| `listRepositoryIssues(repoId, params)`| `GET /api/v1/repositories/{repo_id}/issues` | Parth |
| `executeTask(taskId)` | `POST /api/v1/tasks/{task_id}/execute` | Yug / Prit |
| `getTaskTests(taskId)` | `GET /api/v1/tasks/{task_id}/tests` | Dev / Keval |
| `getTaskVerification(taskId)` | `GET /api/v1/tasks/{task_id}/verification` | Dev |

---

## 5. TanStack React Query Caching Strategy

The frontend manages asynchronous state via `frontend/src/hooks/useTasks.ts` using TanStack React Query v5.

### 5.1. Query Key Hierarchy
```typescript
export const taskKeys = {
  all: ['tasks'] as const,
  lists: () => [...taskKeys.all, 'list'] as const,
  list: (filters?: TaskListFilterParams) => [...taskKeys.all, 'list', filters] as const,
  details: () => [...taskKeys.all, 'detail'] as const,
  detail: (taskId: string) => [...taskKeys.all, 'detail', taskId] as const,
  plans: () => [...taskKeys.all, 'plan'] as const,
  plan: (taskId: string, version?: number) =>
    [...taskKeys.all, 'detail', taskId, 'plan', version] as const,
  events: (taskId: string, params?: { limit?: number; since?: string }) =>
    [...taskKeys.all, 'detail', taskId, 'events', params] as const,
  tests: (taskId: string) => [...taskKeys.all, 'detail', taskId, 'tests'] as const,
  verification: (taskId: string) => [...taskKeys.all, 'detail', taskId, 'verification'] as const,
  repoIssues: (
    repoId: string,
    params?: { state?: 'open' | 'closed' | 'all'; page?: number; page_size?: number }
  ) => [...taskKeys.all, 'repoIssues', repoId, params] as const,
};
```

### 5.2. Mutation Invalidation Matrix
| Mutation Hook | Action | Invalidated Query Keys |
|---|---|---|
| `useCreateTask` | Task created | `taskKeys.lists()` |
| `useImportIssue` | Issue imported as task | `taskKeys.lists()`, `taskKeys.repoIssues(repoId)` |
| `useGeneratePlan` | Plan generated or revised | `taskKeys.detail(id)`, `taskKeys.plan(id)`, `taskKeys.events(id)` |
| `useApprovePlan` | Plan version approved | `taskKeys.detail(id)`, `taskKeys.plan(id)`, `taskKeys.events(id)`, `taskKeys.lists()` |
| `useRejectPlan` | Plan version rejected | `taskKeys.detail(id)`, `taskKeys.plan(id)`, `taskKeys.events(id)`, `taskKeys.lists()` |

---

## 6. MSW v2 Mock Architecture & In-Memory Store

To allow offline development and testing prior to backend completion, MSW v2 simulates all 13 endpoints with stateful in-memory tracking in `frontend/src/mocks/handlers/task.ts`:

- **Stateful In-Memory Store**: Holds collections of tasks, plans, approval history, and event streams.
- **Deterministic Seed Data**: Preloaded with tasks across multiple lifecycle stages (`CREATED`, `PENDING_APPROVAL`, `APPROVED`, `EXECUTING`).
- **Lifecycle Transition Guards**: Enforces valid status transitions according to `VALID_TASK_TRANSITIONS`.
- **Version Concurrency Mismatches (HTTP 409)**: If approval or rejection payload does not match current `task.plan_version`, returns `PLAN_VERSION_MISMATCH`.
- **Execution Shielding (HTTP 409)**: Calls to `/execute` on tasks not in `APPROVED` state return `APPROVAL_REQUIRED`.
- **Error Simulation**: Full support for HTTP 400, 403, 404, 409, 422, and 429 rate limiting.
- **Environment Gating**:
  - Enabled in Vitest via `setupServer` (`frontend/src/test/setup.ts`).
  - Enabled in browser development via `setupWorker` (`frontend/src/main.tsx` wrapped in `if (import.meta.env.DEV)`).
  - Excluded from production builds (`npm run build`), producing zero runtime overhead in production.

---

## 7. In-Memory Persistence Limitations & Refresh Behavior

> [!WARNING]
> In development mode under MSW, all created tasks, generated plans, and approval actions reside strictly in browser memory. Reloading the page or opening the application in a new session resets the mock store to its initial seed data. This is documented behavior for mock-first development and does not represent permanent persistence. Permanent persistence will be provided once Om's database models and Yug's backend routes are deployed.

---

## 8. Canonical Lifecycle Guardrails & Execution Suppression

The frontend adheres strictly to the Week 3 lifecycle rules:
1. **Approval Gating**: The "Approve Plan" and "Reject Plan" actions are only rendered in an active state when `task.status === 'PENDING_APPROVAL'`.
2. **Version Pinning**: The approval payload explicitly submits `{ plan_version: currentPlan.version }`.
3. **Invalidation upon Revision**: Triggering plan revision increments the plan version and invalidates prior approvals, returning the task to `PENDING_APPROVAL`.
4. **Execution Action Suppression**: Per Day 1/2 requirements, no execution controls ("Run in Sandbox", "Execute", "Create PR") are exposed in the Day 1/2 UI. Attempting direct API execution on unapproved tasks yields `409 APPROVAL_REQUIRED`.

---

## 9. Error Normalization & Domain Error Codes

The centralized `normaliseError()` utility in `frontend/src/services/api.ts` was extended to handle all Week 3 domain error codes:

| Backend Error Code | HTTP Status | User Message / Action |
|---|---|---|
| `APPROVAL_REQUIRED` | 409 | Task requires explicit human approval before execution can begin. |
| `PLAN_VERSION_MISMATCH`| 409 | Plan version changed concurrently. UI presents an inline refresh button. |
| `INVALID_STATE_TRANSITION`| 409 | Requested transition is not permitted from the current task state. |
| `TASK_NOT_FOUND` | 404 | The requested task was not found or was removed. |
| `POLICY_VIOLATION` | 403 | Action blocked by command or security policy constraints. |
| `RATE_LIMITED` | 429 | GitHub API rate limit reached. UI advises waiting before retrying. |
| `RECOVERY_REQUIRED` | 409 | Task is in an unrecoverable state requiring manual intervention. |
| `GITHUB_API_ERROR` | 502 | Upstream GitHub communication failure. |

---

## 10. Component Hierarchy

```
frontend/src/
 ├── components/
 │    └── tasks/
 │         ├── TaskStatusBadge.tsx    (Badges with distinct colorways for all 17 states + unknown fallback)
 │         ├── TaskCard.tsx           (Interactive task item card for list view)
 │         ├── CreateTaskForm.tsx     (Manual task intake with dynamic requirements, assumptions, constraints)
 │         ├── ImportIssueForm.tsx    (GitHub issue selector, preview card, and intake trigger)
 │         ├── PlanReviewPanel.tsx    (Step-by-step plan viewer, risk summary, Approve/Reject/Revise actions)
 │         ├── ApprovalHistoryPanel.tsx (Chronological decision history with reason/notes)
 │         └── ExecutionTimeline.tsx  (Audit timeline of all task lifecycle events)
 ├── pages/
 │    ├── Tasks.tsx                   (Main task list, search, status & repo filtering, empty/loading states)
 │    ├── CreateTask.tsx              (Intake host page with tab switcher)
 │    └── TaskDetail.tsx              (Full task detail host page with tabbed views)
 ├── services/
 │    └── tasks.ts                    (Typed API wrapper for all 13 endpoints)
 ├── hooks/
 │    └── useTasks.ts                 (React Query v5 hooks with structured cache invalidation)
 ├── types/
 │    └── task.ts                     (TypeScript domain interfaces and transition state machine)
 └── mocks/
      └── handlers/task.ts            (Stateful MSW v2 mock engine)
```

---

## 11. Backend Teammate Integration Checklist & Migration Guide

When backend teammates deploy their live endpoints, transition from MSW to real APIs requires zero UI changes:

1. **Meet (Task Planner & Approval Orchestration)**:
   - Ensure `POST /api/v1/tasks/{id}/plan` returns a JSON object matching `TaskPlan` (`summary`, `steps`, `version`, `risk_level`, `risk_mitigation`, `verification_strategy`).
   - Verify that approving a plan (`POST /api/v1/tasks/{id}/approve`) verifies `payload.plan_version === task.plan_version` and transitions status to `APPROVED`.
2. **Yug (Backend API & Router)**:
   - Mount task routes under `/api/v1/tasks` and issue routes under `/api/v1/repositories/{repo_id}/issues`.
   - Ensure error responses return JSON with `{ detail: string, code: string }`.
3. **Parth (GitHub Issue Integration)**:
   - Implement `GET /api/v1/repositories/{repo_id}/issues` returning open issues for repository selection.
   - Implement `POST /api/v1/repositories/{repo_id}/issues/import` converting GitHub issues into task intake payloads.
4. **Om (Persistence & Task History)**:
   - Implement `GET /api/v1/tasks/{id}/events` to return persistent chronological audit logs.
   - Ensure task approval/rejection decisions are stored with timestamps and user identifiers.
5. **Switching to Real APIs**:
   - Simply start the backend server. If the backend is running, disable the MSW browser worker by toggling the MSW initialization flag in `frontend/src/main.tsx` or configuring `VITE_ENABLE_MSW=false`.
