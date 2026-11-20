# TASK_PLANNER_IMPLEMENTATION_PLAN.md: Universal Prompt-to-PR Implementation Blueprint

**Project:** AI-Powered Software Development Platform  
**Target Capability:** Universal AI Prompt-to-PR System (Natural Language Request $\to$ Investigated, Implemented, Tested, Verified GitHub Draft PR)  
**Reference Document:** `task.md` (Parts 1, 3–17)  
**Author:** Antigravity (Google DeepMind Agent)  
**Date:** November 19, 2026  
**Status:** Approved for Implementation

---

## 1. Product Vision & Experience Model

The system transforms from a manual task-creation tool into an autonomous software engineering partner:

```text
User provides natural-language request (Prompt)
       │
       ▼
[Phase 2] Intent Understanding & Requirement Decomposition
       │
       ▼
[Phase 2] Grounded Repository Intelligence (Code, Commits, PRs, Issues)
       │
       ▼
[Phase 2] Plan Generation with Adversarial Plan Critic
       │
       ▼
[Human Gate 1] User reviews and authorizes execution plan
       │
       ▼
[Phase 3] Sandboxed Multi-Agent Code Modification (AST Patches)
       │
       ▼
[Phase 4] Diff-Based Testing, Traceback Diagnosis & Bounded Self-Repair (<=3)
       │
       ▼
[Phase 4] Multi-Dimensional Independent Verification (5 Dimensions)
       │
       ▼
[Human Gate 2] User authorizes branch publication on verified SHA
       │
       ▼
[Phase 5] GitHub Draft Pull Request Created with Verification Evidence Matrix
       │
       ▼
[Phase 6] Traceability Graph & Execution Observability Dashboard
```

---

## 2. Six-Phase Implementation Roadmap

### Phase 1: Foundation Hardening & Defect Remediation (Current Phase)
* **Goal:** Remediate the 5 source-code defects identified in `TASK_PLANNER_GAP_MATRIX.md`.
* **Tasks:**
  1. *Fix 1.1:* Remove auto-pilot instant approval from `RepositoryTaskStudio.tsx`. Default to mandatory plan review.
  2. *Fix 1.2:* Add `durability_mode` flag to `autonomous_task_workflow.py` status reporting to indicate native vs DBOS execution.
  3. *Fix 1.3:* Replace hardcoded 100-file / 40-symbol limits in `task_planner.py` with dynamic dependency traversal.
  4. *Fix 1.4:* Eliminate guessed paths (`src/main.py`) in `task_planner.py` fallback. Emit explicit `UNRESOLVED` status.
  5. *Fix 1.5:* Update `task_test_planner.py` to distinguish Vitest from Jest and detect `package.json` test scripts.
  6. *Fix 1.6:* Wire `TaskCompletenessChecker` directly into `approve_task_plan()` endpoint to block incomplete plans.
* **Deliverables:**
  - `TASK_PLANNER_GAP_MATRIX.md` (Completed)
  - `TASK_PLANNER_AUDIT.md` (Completed)
  - `TASK_PLANNER_IMPLEMENTATION_PLAN.md` (This document)
  - Passing regression test suite.

---

### Phase 2: Universal Prompt Intake & Intent Router
* **Goal:** Accept freeform natural-language development prompts across multiple scenarios (Bug Fixes, Features, Refactoring, Security).
* **Architecture:**
  * **Intent Router (`TaskIntent`):**
    ```python
    class TaskIntent(str, Enum):
        BUG_FIX = "bug_fix"
        NEW_FEATURE = "new_feature"
        REFACTOR = "refactor"
        SECURITY_FIX = "security_fix"
        PERFORMANCE = "performance"
        FRONTEND = "frontend"
        BACKEND = "backend"
        DATABASE = "database"
        AI_ML = "ai_ml"
        DOCUMENTATION = "documentation"
        TESTING = "testing"
        MIXED = "mixed"
    ```
  * **Requirement Analyzer:** Decomposes freeform prompts into atomic `DiscoveredTaskRequirement` units with acceptance criteria.
  * **Ambiguity Detector:** Distinguishes open-ended requests ("Improve my app") from targeted requests ("Optimize API response"), presenting scoped proposals rather than guessing.
  * **Plan Critic:** Independent evaluator challenging the generated plan:
    - Verifies all user requirements are addressed.
    - Flags missing tests, invalid targets, or unaddressed database migrations.
* **Deliverables:**
  - `backend/ai/services/intent_router.py`
  - `backend/ai/services/plan_critic.py`
  - `POST /api/v1/tasks/prompt-to-plan` endpoint
  - Intent classification & critic test suite.

---

### Phase 3: Autonomous Code Modification Engine
* **Goal:** Enable AI agents to perform safe, structured, multi-file code modifications.
* **Architecture:**
  * **Controlled ToolRouter:** Sandboxed tool dispatch for `read_file`, `search_code`, `create_file`, `edit_file`, `delete_file`, `apply_patch`, and `get_git_diff`.
  * **AST-Aware Patching:** Structured unified patches validated via AST compilation before disk writes.
  * **Safe File Deletion:** Prohibits file deletion unless dependency graphs confirm 0 inbound imports, 0 CI workflow dependencies, and 0 test references.
  * **Multi-Agent Specialization:**
    - *Backend Agent:* FastAPI endpoints, business logic, auth.
    - *Frontend Agent:* React components, TypeScript interfaces, state.
    - *Database Agent:* SQLAlchemy models, Alembic migrations.
    - *Testing Agent:* Unit, integration, and mock test authoring.
* **Deliverables:**
  - `backend/agent/tools/code_editor.py`
  - `backend/agent/specialized/` agent implementations
  - AST patch applicator and safety validator
  - Multi-file code modification integration tests.

---

### Phase 4: Diff-Based Testing, Diagnosis & Bounded Self-Repair
* **Goal:** Execute actual repository tests against modified diffs and autonomously repair failures within budget.
* **Architecture:**
  * **Diff-to-Test Mapping:** Maps modified files and symbol call edges to specific existing test suites.
  * **Restricted Execution Sandbox:** Containerized test execution enforcing CPU, memory, and timeout limits (120s ceiling).
  * **Traceback Diagnosis Engine:** Analyzes pytest/vitest stack traces to identify root-cause lines.
  * **Server-Authoritative Bounded Repair:** Caps autonomous repair at 3 task-level attempts, saving intermediate recovery checkpoints (`TaskCheckpoint`).
  * **Independent Multi-Dimensional Verification:** Runs 5-dimension verification (Syntax, Tests, Quality, Secrets, Diff Immutability) and stamps `verified_revision`.
* **Deliverables:**
  - `backend/scanner/diff_test_mapper.py`
  - Automated failure diagnosis service
  - Multi-dimensional verification suite.

---

### Phase 5: GitHub Draft PR Automation & Publication Gate
* **Goal:** Deliver reviewable GitHub Draft Pull Requests with complete audit traceability.
* **Architecture:**
  * **Task Branch Isolation:** Formats branch as `agent/task-<task_id[:8]>`, strictly enforcing `PROTECTED_BRANCHES` blocklist.
  * **Human Publication Gate (ADR-010):** Requires explicit human confirmation (`POST /{task_id}/authorize-publication`) before pushing.
  * **Diff Immutability Assertion:** Confirms that workspace diff hash matches `verified_revision` hash before pushing.
  * **Standardized GitHub Draft PR:** Generates rich markdown PR body with:
    - Summary of Changes & Problem Statement
    - Independent Verification Evidence Matrix
    - Test Execution Telemetry
    - Originating Finding / Issue Lineage
  * **Audit Traceability Graph:** `GET /{task_id}/traceability` returns the full JSON provenance graph.
* **Deliverables:**
  - End-to-end Draft PR publication pipeline
  - GitHub integration test suite
  - Audit graph serialization tests.

---

### Phase 6: Autonomous Development Studio Frontend
* **Goal:** Provide a responsive, real-time web interface for prompt-to-PR workflows.
* **Architecture:**
  * **Conversational Prompt Intake:** Large prompt input card with intent badges, repository selector, and proposal preview.
  * **Live Telemetry Stream:** SSE/WebSocket event stream rendering tool execution progress, active commands, and logs.
  * **Interactive Code Diff Viewer:** Virtualized, syntax-highlighted diff viewer with verification chips.
  * **Dual Human Governance Controls:**
    - *Plan Approval Panel:* Review ordered steps, risks, and criteria.
    - *Publication Panel:* Inspect verified commit SHA, review PR preview, and click "Authorize Publication".
* **Deliverables:**
  - Updated `RepositoryTaskStudio.tsx`
  - `PromptIntakeCard.tsx` and `PlanCriticFeedback.tsx`
  - Full frontend vitest component test suite.

---

## 3. Part 17: Final Acceptance Checklist (0/33 Target)

The following 33 acceptance criteria must be satisfied and verified by automated tests before declaring the Universal Prompt-to-PR System complete:

### Task Planner Audit & Foundation
- [ ] **1. All existing planner services inventoried** (`TaskPlanner`, `HierarchicalLocalizer`, `TaskTestPlanner`, `PlanReplanner`).
- [ ] **2. All API and frontend integration paths mapped** (Full endpoint inventory verified).
- [ ] **3. Missing, broken and duplicate implementations classified** (`TASK_PLANNER_GAP_MATRIX.md` published).
- [ ] **4. Approval and execution state transitions tested** (Zero illegal state jumps).
- [ ] **5. Fallback and exception behaviour validated** (Deterministic fallback verified).

### Prompt Understanding & Intake
- [ ] **6. Natural-language requests accepted** (Freeform text accepted without manual requirement pre-formatting).
- [ ] **7. Multiple intents supported** (Classification across bug fixes, features, refactoring, security).
- [ ] **8. Atomic requirements generated** (Compound requests broken into verifiable criteria).
- [ ] **9. Ambiguous requests handled safely** (Clarification requested for unbounded prompts).
- [ ] **10. Repository context included in planning** (Context grounded in code, tests, and documentation).

### Code Modification & Workspace
- [ ] **11. Actual files can be read and searched** (Controlled tool access via `ToolRouter`).
- [ ] **12. Files can be created, edited and deleted safely** (Safe file deletion criteria enforced).
- [ ] **13. Multi-file changes supported** (Cross-module modifications coordinated).
- [ ] **14. Changes restricted to approved workspace** (`WorkspacePathGuard` blocks path escapes).
- [ ] **15. Real Git diffs generated** (Streaming diff parser computes insertions and deletions).

### Execution, Testing & Repair
- [ ] **16. DAG dependencies respected** (Topological sort drives execution sequence).
- [ ] **17. Execution survives worker interruption** (Durable recovery checkpoints persisted).
- [ ] **18. Correct test framework detected** (Vitest, Jest, Pytest accurately identified).
- [ ] **19. Existing and generated tests executed** (Diff-to-test mapping verified).
- [ ] **20. Repair loop is bounded** (Server-authoritative 3-attempt limit enforced).
- [ ] **21. Independent verification performed** (5 orthogonal verification dimensions passed).

### Security & GitHub Governance
- [ ] **22. Sandbox isolation validated** (CPU, memory, and network limits enforced).
- [ ] **23. Prompt injection defences tested** (Cryptographic nonce fencing neutralizes injection).
- [ ] **24. Secrets and unauthorized paths blocked** (Gitleaks scan blocks credential commits).
- [ ] **25. Protected branches protected** (`main`/`master` blocklist active).
- [ ] **26. Publication authorization bound to verified SHA** (`authorized_head_sha == verified_revision`).
- [ ] **27. GitHub Draft PR created and synchronized** (`is_draft=True`, `auto_merge=False`).

### Frontend & Observability
- [ ] **28. Task progress comes from persisted events** (Zero fabricated UI metrics).
- [ ] **29. Diff viewer shows actual changes** (Syntax-highlighted diff matching git diff).
- [ ] **30. Test logs and repair history visible** (Tracebacks and patch attempts displayed).
- [ ] **31. Cancellation and resume supported** (Active tasks can be cancelled safely).
- [ ] **32. Failure messages are actionable** (Explicit gap descriptions surfaced to user).
- [ ] **33. Execution cost and duration recorded** (Token counts and latency logged).

---

## 4. Evaluation Benchmark (80-Case Task Suite)

An evaluation benchmark of 80 real-world tasks across 10 categories will be executed to evaluate system reliability:

| Category | Test Case Count | Focus Area |
|---|:---:|---|
| Simple bug fixing | 10 | Traceback diagnosis, targeted one-file fixes |
| New backend features | 10 | FastAPI endpoints, service logic, Pydantic schemas |
| Frontend development | 10 | React components, Tailwind styling, state management |
| Cross-layer features | 10 | API + UI + integration contracts |
| Database changes | 5 | SQLAlchemy models, Alembic migrations |
| Refactoring | 10 | Dead code removal, modularization, preserving tests |
| Security fixes | 10 | Input sanitization, auth boundaries, secret handling |
| Test generation | 5 | Unit tests covering uncovered symbols |
| Documentation | 5 | API docs, markdown synchronization |
| Complex architectural tasks | 5 | Multi-agent coordination, dependency graphs |
| **Total Benchmark** | **80** | **Comprehensive Engineering Capability** |

---

## 5. Immediate Next Actions

1. Review and approve `TASK_PLANNER_GAP_MATRIX.md` and `TASK_PLANNER_AUDIT.md`.
2. Implement Phase 1 source code defect fixes (Auto-pilot approval policy, Vitest mapping, Fabricated path fallback).
3. Proceed to Phase 2: Implement `IntentRouter` and `PlanCritic`.
