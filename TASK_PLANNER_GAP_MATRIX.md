# TASK_PLANNER_GAP_MATRIX.md: Implementation-Level Gap & Defect Matrix

**System:** AI-Powered Software Development Platform  
**Repository:** `Meetvirugama/AI-Powered-Software-Development-Platform`  
**Reference Document:** `task.md` (Parts 1–17)  
**Audit Date:** November 19, 2026  
**Auditor:** Antigravity (Google DeepMind Agent)  
**Standardized Taxonomy:**  
`IMPLEMENTED_CORRECTLY` | `PARTIALLY_IMPLEMENTED` | `IMPLEMENTED_BUT_BROKEN` | `NOT_INTEGRATED` | `MISSING` | `DUPLICATE` | `INSECURE` | `UNVERIFIED`

---

## 1. Executive Summary of Audit Findings

| Classification | Count | Features / Areas Affected |
|---|:---:|---|
| **IMPLEMENTED_CORRECTLY** | 12 | DAG Scheduler, Workspace Provisioning, Execution Loop, Diff Verification, Test Sandbox, Self-Repair, Verification, Branch Isolation, Publication Gate, Draft PR, Traceability, Multi-Tenant Locks |
| **PARTIALLY_IMPLEMENTED** | 4 | Task Intake (lacks universal natural-language intent router), Plan Generation (fixed 100-file limit), Human Approval (frontend bypass), Durable Workflow (native fallback without durability disclosure) |
| **IMPLEMENTED_BUT_BROKEN** | 3 | Hierarchical Localizer (guesses `src/main.py`), Test Planner (Vitest/Jest confusion), Frontend Auto-Pilot (unauthorized auto-approval) |
| **NOT_INTEGRATED** | 1 | Task Completeness Checker (bypassed on custom plan approval) |
| **MISSING** | 5 | Universal Intent Router, Plan Critic, Hybrid Scoring Context Ranker, Multi-Agent Specialized Dispatcher, 80-Case Task Benchmark |
| **DUPLICATE** | 1 | Dual PullRequest metadata persistence (`TaskPullRequest` vs `PullRequest` table) |
| **INSECURE** | 1 | Frontend Auto-Pilot instant approval without explicit policy opt-in |

---

## 2. Exhaustive 19-Feature Group Audit Matrix (Six Dimensions)

For every feature group, six dimensions are audited:
1. *Exists?* (Does the code exist?)
2. *Correct?* (Is logic sound?)
3. *Connected?* (Integrated in end-to-end workflow?)
4. *Secure?* (Server-side enforcement?)
5. *Tested under Failure?* (Explicit failure test cases?)
6. *Persisted & Visible?* (User visibility and DB persistence?)

| No. | Feature Group | Primary Source Files | Classification | Dimensions (1-6) | Detailed Gap / Defect Analysis & Required Fix |
|:---:|---|---|:---:|:---:|---|
| **1** | **Task Intake** | [`backend/app/api/v1/tasks.py`](file:///Users/meetvirugama/Desktop/AI-Powered-Software-Development-Platform/backend/app/api/v1/tasks.py#L532), [`backend/app/schemas/task.py`](file:///Users/meetvirugama/Desktop/AI-Powered-Software-Development-Platform/backend/app/schemas/task.py), [`backend/ai/services/task_planner.py`](file:///Users/meetvirugama/Desktop/AI-Powered-Software-Development-Platform/backend/ai/services/task_planner.py#L103) | `PARTIALLY_IMPLEMENTED` | 1: Yes<br>2: Partial<br>3: Yes<br>4: Yes<br>5: Yes<br>6: Yes | **Current:** Solid schema for pre-structured requirements, assumptions, constraints, and nonce prompt fencing (`_fence_block`).<br>**Gap:** Lacks freeform natural-language prompt intake and Intent Router (Part 3). Compound user prompts cannot be classified or routed dynamically without manual pre-structuring. |
| **2** | **Hierarchical Localizer** | [`backend/ai/services/hierarchical_localizer.py`](file:///Users/meetvirugama/Desktop/AI-Powered-Software-Development-Platform/backend/ai/services/hierarchical_localizer.py), [`backend/ai/services/task_planner.py`](file:///Users/meetvirugama/Desktop/AI-Powered-Software-Development-Platform/backend/ai/services/task_planner.py#L238-L245) | `IMPLEMENTED_BUT_BROKEN` | 1: Yes<br>2: Defect<br>3: Yes<br>4: Yes<br>5: Yes<br>6: Yes | **Current:** 3-stage funnel (Files $\to$ Symbols $\to$ Line ranges) exists and runs.<br>**Defect (task.md §2.2 Item 4):** In `task_planner.py` lines 239–242, when no files are localized, fallback fabricates guessed paths: `fallback_candidate = "src/main.py" if language == "python" else "src/index.ts"`.<br>**Fix:** Never invent non-existent files. Flag unresolved localization explicitly. |
| **3** | **Requirement Discovery** | [`backend/ai/services/task_requirement_discovery.py`](file:///Users/meetvirugama/Desktop/AI-Powered-Software-Development-Platform/backend/ai/services/task_requirement_discovery.py) | `IMPLEMENTED_CORRECTLY` | 1: Yes<br>2: Yes<br>3: Yes<br>4: Yes<br>5: Yes<br>6: Yes | **Current:** Decomposes tasks/issues into atomic `DiscoveredTaskRequirement` units across 10 categories with criteria.<br>**Enhancement Needed:** Needs connection to freeform Intent Router in Phase 2. |
| **4** | **Plan Generation** | [`backend/ai/services/task_planner.py`](file:///Users/meetvirugama/Desktop/AI-Powered-Software-Development-Platform/backend/ai/services/task_planner.py#L169-L190), [`backend/app/schemas/plan.py`](file:///Users/meetvirugama/Desktop/AI-Powered-Software-Development-Platform/backend/app/schemas/plan.py) | `PARTIALLY_IMPLEMENTED` | 1: Yes<br>2: Partial<br>3: Yes<br>4: Yes<br>5: Yes<br>6: Yes | **Current:** Synthesizes `PlannerSchema`, fences prompts, enforces token budgets, and provides deterministic fallback.<br>**Defect (task.md §2.2 Item 3):** Context retrieval in lines 172 & 186 uses hardcoded limits: `db.query(RepositoryFile).limit(100)` and `db.query(CodeSymbol).limit(40)`. Lacks hybrid ranking formula and Plan Critic (Part 5). |
| **5** | **DAG Scheduler** | [`backend/app/schemas/plan.py`](file:///Users/meetvirugama/Desktop/AI-Powered-Software-Development-Platform/backend/app/schemas/plan.py#L539-L635) (`PlanDependencyGraph`) | `IMPLEMENTED_CORRECTLY` | 1: Yes<br>2: Yes<br>3: Yes<br>4: Yes<br>5: Yes<br>6: Yes | **Current:** Enforces step uniqueness, blocks self-dependencies, detects dangling references/transitions, detects 2-step and multi-step cycles via DFS, and generates topological sort. Verified by 23 tests. |
| **6** | **Test Planner** | [`backend/scanner/task_test_planner.py`](file:///Users/meetvirugama/Desktop/AI-Powered-Software-Development-Platform/backend/scanner/task_test_planner.py#L55-L90), [`backend/app/schemas/planner_context.py`](file:///Users/meetvirugama/Desktop/AI-Powered-Software-Development-Platform/backend/app/schemas/planner_context.py) | `IMPLEMENTED_BUT_BROKEN` | 1: Yes<br>2: Defect<br>3: Yes<br>4: Yes<br>5: Yes<br>6: Yes | **Current:** Framework detection, existing test mapping, untested symbol detection, test command generation.<br>**Defect (task.md §2.2 Item 5):** In lines 75 & 90: `if "jest" in fw_name or "vitest" in fw_name: return "jest"`. Vitest is conflated with Jest; unknown frameworks default to pytest without reading package scripts. |
| **7** | **Completeness Checker** | [`backend/ai/services/task_completeness_checker.py`](file:///Users/meetvirugama/Desktop/AI-Powered-Software-Development-Platform/backend/ai/services/task_completeness_checker.py), [`backend/app/api/v1/tasks.py`](file:///Users/meetvirugama/Desktop/AI-Powered-Software-Development-Platform/backend/app/api/v1/tasks.py#L695-L729) | `NOT_INTEGRATED` | 1: Yes<br>2: Yes<br>3: **No**<br>4: Partial<br>5: Yes<br>6: Yes | **Current:** `TaskCompletenessChecker` calculates coverage, missing critical counts, and issues.<br>**Defect (task.md §2.1 & §2.3):** The approval endpoint `POST /{task_id}/approve` does NOT call or enforce `check_plan_completeness()`. Incomplete plans can be approved without server-side blocking. |
| **8** | **Human Approval** | [`backend/app/api/v1/tasks.py`](file:///Users/meetvirugama/Desktop/AI-Powered-Software-Development-Platform/backend/app/api/v1/tasks.py#L695-L756), [`frontend/src/pages/RepositoryTaskStudio.tsx`](file:///Users/meetvirugama/Desktop/AI-Powered-Software-Development-Platform/frontend/src/pages/RepositoryTaskStudio.tsx#L400-L406) | `INSECURE` / `PARTIALLY_IMPLEMENTED` | 1: Yes<br>2: Defect<br>3: Yes<br>4: Partial<br>5: Yes<br>6: Yes | **Current:** Server enforces `PENDING_APPROVAL` status and exact `plan_version` (HTTP 409 Conflict).<br>**Defect (task.md §2.2 Item 1):** In `RepositoryTaskStudio.tsx` lines 402–405: `if (autoPilotOnCreate) { await approveTaskPlan(...); await executeTask(...); }` auto-approves without explicit user policy confirmation. |
| **9** | **Workspace Provisioning** | [`backend/sandbox/workspace_manager.py`](file:///Users/meetvirugama/Desktop/AI-Powered-Software-Development-Platform/backend/sandbox/workspace_manager.py), [`backend/sandbox/path_guard.py`](file:///Users/meetvirugama/Desktop/AI-Powered-Software-Development-Platform/backend/sandbox/path_guard.py) | `IMPLEMENTED_CORRECTLY` | 1: Yes<br>2: Yes<br>3: Yes<br>4: Yes<br>5: Yes<br>6: Yes | **Current:** Isolates `.workspaces/task-<id>/`, manages Git worktrees, enforces `WorkspacePathGuard` against path escapes (`../../`), and checks base revision freshness. |
| **10** | **Execution Loop** | [`backend/ai/services/agent_execution_loop.py`](file:///Users/meetvirugama/Desktop/AI-Powered-Software-Development-Platform/backend/ai/services/agent_execution_loop.py), [`backend/app/services/task_execution_orchestrator.py`](file:///Users/meetvirugama/Desktop/AI-Powered-Software-Development-Platform/backend/app/services/task_execution_orchestrator.py) | `IMPLEMENTED_CORRECTLY` | 1: Yes<br>2: Yes<br>3: Yes<br>4: Yes<br>5: Yes<br>6: Yes | **Current:** Dispatches steps in topological order, routes tools via `ToolRouter`, enforces bounded diff scope, and streams progress.<br>**Future Extension:** Needs multi-agent specialization (Backend, Frontend, DB agents). |
| **11** | **Diff Verification** | [`backend/sandbox/diff_verifier.py`](file:///Users/meetvirugama/Desktop/AI-Powered-Software-Development-Platform/backend/sandbox/diff_verifier.py) | `IMPLEMENTED_CORRECTLY` | 1: Yes<br>2: Yes<br>3: Yes<br>4: Yes<br>5: Yes<br>6: Yes | **Current:** Streaming $O(1)$ unified diff parser (10MB ceiling), plan scope boundary check, `CRITICAL_PROJECT_FILES` deletion guard, and dual-engine secret scanning (`GitleaksDiffScanner`). Verified by 38 tests. |
| **12** | **Test Sandbox** | [`backend/sandbox/test_runner.py`](file:///Users/meetvirugama/Desktop/AI-Powered-Software-Development-Platform/backend/sandbox/test_runner.py), [`backend/scanner/task_test_planner.py`](file:///Users/meetvirugama/Desktop/AI-Powered-Software-Development-Platform/backend/scanner/task_test_planner.py) | `IMPLEMENTED_CORRECTLY` | 1: Yes<br>2: Yes<br>3: Yes<br>4: Yes<br>5: Yes<br>6: Yes | **Current:** Isolated test execution with CPU/timeout caps; detects exit code 5 as `NO TESTS COLLECTED` (never treated as pass). |
| **13** | **Self-Repair** | [`backend/app/services/task_recovery.py`](file:///Users/meetvirugama/Desktop/AI-Powered-Software-Development-Platform/backend/app/services/task_recovery.py), [`backend/ai/services/execution_budget_manager.py`](file:///Users/meetvirugama/Desktop/AI-Powered-Software-Development-Platform/backend/ai/services/execution_budget_manager.py) | `IMPLEMENTED_CORRECTLY` | 1: Yes<br>2: Yes<br>3: Yes<br>4: Yes<br>5: Yes<br>6: Yes | **Current:** Server-authoritative 3-attempt repair budget, diagnosis of test tracebacks, AST patch generation, and checkpoint rollback. |
| **14** | **Independent Verification** | [`backend/app/services/task_execution_orchestrator.py`](file:///Users/meetvirugama/Desktop/AI-Powered-Software-Development-Platform/backend/app/services/task_execution_orchestrator.py), [`backend/ai/services/execution_verifier.py`](file:///Users/meetvirugama/Desktop/AI-Powered-Software-Development-Platform/backend/ai/services/execution_verifier.py) | `IMPLEMENTED_CORRECTLY` | 1: Yes<br>2: Yes<br>3: Yes<br>4: Yes<br>5: Yes<br>6: Yes | **Current:** Verifies 5 orthogonal dimensions (AST Syntax, Tests exit 0, Code Review, Secrets, Diff Immutability), stamping immutable `verified_revision`. |
| **15** | **Branch Management** | [`backend/app/services/git_branch.py`](file:///Users/meetvirugama/Desktop/AI-Powered-Software-Development-Platform/backend/app/services/git_branch.py) | `IMPLEMENTED_CORRECTLY` | 1: Yes<br>2: Yes<br>3: Yes<br>4: Yes<br>5: Yes<br>6: Yes | **Current:** Canonical `agent/task-<id>` naming, active blocklist on `PROTECTED_BRANCHES` (`main`, `master`, `production`, `release`), token-scrubbed commits. |
| **16** | **Publication Authorization** | [`backend/app/api/v1/tasks.py`](file:///Users/meetvirugama/Desktop/AI-Powered-Software-Development-Platform/backend/app/api/v1/tasks.py#L1689), [`backend/app/repositories/task_repository.py`](file:///Users/meetvirugama/Desktop/AI-Powered-Software-Development-Platform/backend/app/repositories/task_repository.py) | `IMPLEMENTED_CORRECTLY` | 1: Yes<br>2: Yes<br>3: Yes<br>4: Yes<br>5: Yes<br>6: Yes | **Current:** Explicit human authorization gate (`POST /{task_id}/authorize-publication`); verifies `authorized_head_sha == verified_revision`. |
| **17** | **Draft PR Creation** | [`backend/app/services/task_execution_orchestrator.py`](file:///Users/meetvirugama/Desktop/AI-Powered-Software-Development-Platform/backend/app/services/task_execution_orchestrator.py#L1949), [`backend/sandbox/workspace_manager.py`](file:///Users/meetvirugama/Desktop/AI-Powered-Software-Development-Platform/backend/sandbox/workspace_manager.py) | `IMPLEMENTED_CORRECTLY` | 1: Yes<br>2: Yes<br>3: Yes<br>4: Yes<br>5: Yes<br>6: Yes | **Current:** Enforces `is_draft=True`, `auto_merge=False`, formats comprehensive evidence table, links Origin Issue/Finding, and syncs GitHub PR URL. |
| **18** | **Traceability** | [`backend/app/api/v1/tasks.py`](file:///Users/meetvirugama/Desktop/AI-Powered-Software-Development-Platform/backend/app/api/v1/tasks.py#L1786) | `IMPLEMENTED_CORRECTLY` | 1: Yes<br>2: Yes<br>3: Yes<br>4: Yes<br>5: Yes<br>6: Yes | **Current:** Traverses Finding $\to$ Task $\to$ Plan $\to$ Tests $\to$ Verification $\to$ Commit $\to$ Draft PR, redacting secrets at all nodes. |
| **19** | **Frontend Task Studio** | [`frontend/src/pages/RepositoryTaskStudio.tsx`](file:///Users/meetvirugama/Desktop/AI-Powered-Software-Development-Platform/frontend/src/pages/RepositoryTaskStudio.tsx), [`frontend/src/components/taskStudio/TaskPhasePanels.tsx`](file:///Users/meetvirugama/Desktop/AI-Powered-Software-Development-Platform/frontend/src/components/taskStudio/TaskPhasePanels.tsx) | `PARTIALLY_IMPLEMENTED` | 1: Yes<br>2: Partial<br>3: Yes<br>4: Yes<br>5: Yes<br>6: Yes | **Current:** 6 execution phases rendered with live tool streaming, tokenized diff viewer, and verification badges.<br>**Gap:** Lacks conversational / prompt-first interaction (Part 11) and contains auto-pilot instant approval flaw. |

---

## 3. Specific Source Code Defects & Required Code Actions

### Defect 1: Auto-Pilot Plan Approval Without Opt-In Policy
* **Location:** `frontend/src/pages/RepositoryTaskStudio.tsx:402–405`
* **Vulnerability:**
  ```typescript
  if (autoPilotOnCreate) {
    await approveTaskPlan(created.task_id, { comment: 'Auto-pilot instant approval' });
    await executeTask(created.task_id, { run_steps: true, run_tests_after: true, auto_repair: true });
  }
  ```
* **Required Fix:** Disable automatic plan approval by default. Require an explicit user settings policy toggle with clear risk warnings before enabling autonomous plan execution.

### Defect 2: Silent Durable Workflow Fallback
* **Location:** `backend/ai/workflows/autonomous_task_workflow.py:53–65`
* **Vulnerability:**
  ```python
  if HAS_DBOS and DBOS is not None:
      wrapped = DBOS.workflow(*dargs, **dkwargs)(fn)
      ...
  return fn  # Falls back to in-memory native execution
  ```
* **Required Fix:** When DBOS is not initialized, do not return durable status. Explicitly tag the execution mode as `NATIVE_TRANSIENT` and disclaim crash-recovery guarantees in the workflow status API.

### Defect 3: Arbitrary Context Truncation Limits
* **Location:** `backend/ai/services/task_planner.py:172, 186`
* **Vulnerability:** Hardcoded `db.query(RepositoryFile).limit(100)` and `db.query(CodeSymbol).limit(40)`.
* **Required Fix:** Implement relevance scoring based on task intent and dependencies:
  $$Score(f) = w_1 R(f) + w_2 D(f) + w_3 G(f) + w_4 T(f) + w_5 S(f)$$
  Flag insufficient context when dependent modules are omitted.

### Defect 4: Fabricated Fallback Localization Targets
* **Location:** `backend/ai/services/task_planner.py:239–242`
* **Vulnerability:**
  ```python
  fallback_candidate = "src/main.py" if language.lower() == "python" else "src/index.ts"
  req_target_files = [fallback_candidate]
  ```
* **Required Fix:** Never invent non-existent file paths. Return an explicit `LocalizationTarget(status="UNRESOLVED")` requiring clarification or repository exploration.

### Defect 5: Framework Conflation (Vitest / Jest)
* **Location:** `backend/scanner/task_test_planner.py:75, 90`
* **Vulnerability:**
  ```python
  if "jest" in fw_name or "vitest" in fw_name:
      return "jest"
  ```
* **Required Fix:** Inspect `package.json` scripts directly. If `"test": "vitest"`, set framework to `vitest` and format command as `npx vitest run <test_files>` instead of `npm test -- <test_files>`.

---

## 4. Missing Audit Dimensions (task.md §2.3)

### A. Architecture Integration Audit
* **Traceability Invariant:** Does every plan approval pass through completeness checking?
  * **Finding:** When `custom_plan` is supplied in `POST /{task_id}/plan`, `check_plan_completeness()` is bypassed.
  * **Remedy:** Enforce `TaskCompletenessChecker.check_plan_completeness()` inside `approve_task_plan()` before committing approval status to PostgreSQL.

### B. Data Consistency Audit
* **Finding:** Dual tables exist for PR records (`TaskPullRequest` and legacy `PullRequest`). The system synchronizes them via `git_branch_svc.prepare_pr_metadata()`, but a migration plan should unify them into a single authoritative model.

### C. Failure & Recovery Audit
* **LLM API Failures:** Covered by deterministic plan fallback (`_build_deterministic_plan`).
* **Hanging Tests:** Addressed by `--timeout=120` in CI and sandbox process timeouts.
* **Worker Restarts:** DBOS durable workflow handles recovery when DBOS is enabled; transient execution relies on recovery checkpoints (`TaskCheckpoint`).

### D. Frontend Integration Audit
* **Finding:** Frontend components (`PlanReviewPanel`, `CodeChangesPanel`, `VerificationPanel`, `PublicationPanel`) correctly bind to backend API responses without fabricating metrics. 64 vitest tests pass.
