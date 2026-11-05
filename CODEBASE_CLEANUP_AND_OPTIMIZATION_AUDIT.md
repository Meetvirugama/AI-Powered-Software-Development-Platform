# CODEBASE CLEANUP & OPTIMIZATION AUDIT
## AI-Powered Software Development Platform — dead code removal, duplicate features, and frontend / backend / AI / database / Redis optimization

| Field | Value |
|---|---|
| Input | `AI-Powered-Software-Development-Platform-main.zip` (snapshot dated 2026-11-04) |
| Audit date | 2026-11-05 |
| Mode | **Read-only.** Nothing in the project was modified. This file is the deliverable |
| Companion | `DEEP_TECHNICAL_RESEARCH_AND_INTEGRATION_GUIDE.md` (MCP, plugins, research roadmap). This file covers **cleanup** and **performance** only |

---

## 0. Summary

### 0.1 How the audit was done (so you can reproduce it)

| Check | Tool / method | What it finds |
|---|---|---|
| Unused imports, variables, redefinitions, undefined names | `ruff check backend --select F401,F811,F841,F821 --exclude backend/tests` | Lint-level dead code and latent bugs |
| Blocking calls in async code, slow loops | `ruff … --select ASYNC,PERF,SIM` | Event-loop blocking, inefficient loops |
| Unreachable Python modules | Custom AST import graph starting from `app.main`, `app.workers.sync_worker` and `scripts/*` | Modules only tests import |
| Unreferenced Python functions/classes | Custom AST scan: definition names with **zero** references anywhere in non-test backend code | Dead functions (with known false positives, see §A4) |
| Frontend dead files and exports | Custom TypeScript import graph from `src/main.tsx`, plus exported names never imported | Orphan files and unused exports |
| Dead API endpoints | Cross-reference of every backend route with every API path string in `frontend/src` | Endpoints the UI never calls |
| Dependency injection holes | Compare `app.state.X = …` assignments with `getattr(app.state, "X")` reads | Features wired to nothing |
| DB drift and indexes | Compare SQLAlchemy models with Alembic migrations, and query patterns with indexes | Missing constraints/indexes |

**Limitations:**
- Static analysis cannot see `getattr`-by-variable calls, string-based dispatch, or framework callbacks.
- Every "delete" item below was spot-checked with grep. Still, run the full test suite after each removal batch (§A10).
- The code was not executed.

### 0.2 Headline numbers

| Item | Count |
|---|---|
| Unused imports in backend (excluding `__init__` re-exports) | **348** across ~60 files |
| Unused local variables | **17** |
| Undefined-name references | **9** (8 harmless annotations, **1 real bug**) |
| Duplicate method definitions overriding each other | **1** (`TaskRepository.get_task_for_user`) |
| Python modules reachable **only from tests** | **9 modules, ~1,160 LOC** |
| Unreferenced functions/classes | **177 candidates, ~4,900 LOC** (117 are used only by tests) |
| A second, parallel task-execution stack (services + routes) | **~1,800 LOC** |
| Backend endpoints the frontend never calls | **~30** |
| Frontend orphan files | **8 files (~870 LOC)** |
| Frontend exported service functions never called | **15** |
| Unused/duplicate dependencies | Python: 4 · frontend: 1 (+ shim duplication) |
| Async route handlers doing synchronous DB I/O on the event loop | **42** |

### 0.3 Top ten actions (ordered)

1. **Fix four bugs found during the sweep** (§A1). They are latent production issues that look like dead code.
2. **Delete the duplicate task-execution stack** (`app/services/task_orchestrator.py`, `app/services/test_runner.py`, `app/services/repair_loop.py`, and 22 `/source/*` routes). Keep 2 endpoints the UI uses (§A2).
3. **Decide "wire or delete"** for 9 test-only modules. Most should be deleted. `StaticReviewer` should be *wired*, because code review currently never runs Ruff/Bandit (§A3).
4. **Auto-remove 348 unused imports and 17 unused variables** with Ruff in one PR (§A5).
5. **Collapse the reflection-based analysis-run persistence chain** into one repository call (§A6).
6. **Frontend cleanup:** 8 orphan files, 15 unused service functions, and the MSW duplication (shim + real package + worker file) (§A7).
7. **Stop blocking the event loop:** 42 `async def` handlers run synchronous SQLAlchemy and Redis calls (§B2.1).
8. **Re-use embeddings by `content_hash`** and batch the chunk inserts. This is the biggest AI and DB cost saving during re-indexing (§B3.1, §B4.3).
9. **Add the missing indexes and fix model/migration drift** (§B4.1–B4.2).
10. **Redesign SSE fan-out in Redis.** Today one global channel feeds every connection and is filtered in Python (§B5.2).

---

# PART A — REMOVE: dead code, duplicate features, unnecessary files

## A1. Bugs found during the dead-code sweep (fix first)

These showed up as "unused" or "undefined" in the scans, but they are real defects.

| # | Location | What is wrong | Impact | Fix |
|---|---|---|---|---|
| A1.1 | `backend/app/services/task_execution_orchestrator.py` L287 | `json.loads(...)` is used but `json` is **never imported** (Ruff F821). The call sits inside `try/except Exception: pass`, so the `NameError` is swallowed silently | The fallback that reads `verification_diff_hash` from `metadata.json` **never works**. It always falls through to the DB lookup, and the error is hidden | Add `import json`, and narrow the `except` to `(OSError, json.JSONDecodeError)` so future errors are visible |
| A1.2 | `backend/app/repositories/task_repository.py` L351 and L2064 | `get_task_for_user` is **defined twice**. Python keeps the second one, so the first is dead (F811). The live version eager-loads `plans, approvals, events, workspace, executions` with `selectinload` on **every ownership check** | Every `/tasks/{id}/…` call pays for up to 5 extra queries and loads the full event history | Delete the first definition. Split into `get_task_for_user(id, user)` (no eager loads) and `get_task_detail_for_user(...)` (eager loads) and use the light one for authorization (§B4.4) |
| A1.3 | `backend/app/api/v1/analysis/review.py` L149, `backend/app/api/v1/analysis/bugs.py`, `backend/app/core/lifespan.py` | The routes read `app.state.static_reviewer` and `app.state.static_bug_scanner`, but **nothing ever sets them** (no assignment anywhere). `review/static_reviewer.py` (`StaticReviewer`, Ruff + Bandit) is imported only by tests | **Code review never runs Ruff/Bandit in production**, although docs and the README say it does. *Correction to the earlier research guide, which described Ruff/Bandit as part of the live review path.* | Either wire it in `lifespan.py` (`app.state.static_reviewer = StaticReviewer()`), which is recommended and better done inside the sandbox runner, or delete the hooks and update the docs |
| A1.4 | `backend/app/api/v1/events.py` `_should_deliver_event` | If the owned-repository lookup fails at connect time (`owned_repo_ids = None` in the `except`), repository-scoped events skip the ownership check, and **any authenticated user receives them** | Cross-tenant event leak whenever the DB hiccups during SSE connect | Fail closed: if `owned_repo_ids is None` and the caller is authenticated, drop repository-scoped events. Delete the unused wrapper `_is_event_authorized_for_user` (never called) |
| A1.5 | `backend/app/models/repository_file.py` vs migration `aef3bb17eb34_content_tables.py` | The model declares `UniqueConstraint(repository_id, path)`, an index on `(repository_id, path)`, and `ondelete="CASCADE"`. **The migration creates none of them** | Duplicate file rows are possible under concurrent syncs; slow path lookups; repo deletion does not cascade | New Alembic migration adding the constraint, index and FK `ON DELETE CASCADE` (dedupe existing rows first). Add `alembic check` to CI to catch future drift |

Ruff also reports 8 more F821 hits in annotations (`Sequence`, `Any`, `BugFinding`) inside files that use `from __future__ import annotations`. They are harmless at runtime but break type-checking. Add the missing imports: `ai/schemas/grounding.py`, `app/api/v1/analysis/bugs.py` L286, `app/api/v1/analysis/tests.py` L259, `app/services/git_branch.py` L1100/L1147.

---

## A2. Duplicate feature stack: the second task-execution API

The repository contains **two independent implementations** of "run tests → repair → verify → publish" for agent tasks.

| | **Stack A (canonical; used by the UI)** | **Stack B (duplicate)** |
|---|---|---|
| HTTP surface | `/api/v1/tasks/{id}/…` (`app/api/v1/tasks.py`) | `/api/v1/repositories/{id}/source/task/…` and `/source/task-workspace/…` (`app/integrations/github/routes.py` L455–1022) |
| Orchestrator | `app/services/task_execution_orchestrator.py` | `app/services/task_orchestrator.py` (420 LOC; it even defines a class with the same name, `TaskExecutionOrchestrator`) |
| Test runner | `sandbox/test_runner.py` (via `WorkspaceCommandRunner`) | `app/services/test_runner.py` (482 LOC; separate async runner with its own `CommandPolicyValidator` allowlist) |
| Repair | `ai/services/bounded_repair_loop.py` | `app/services/repair_loop.py` (`BoundedRepairManager`, 333 LOC) |
| Used by frontend? | **Yes** (all task panels) | **No.** Only `GET /source/diff-ranges/task/{task_id}` and `GET /source/pr-metadata/{task_id}` are called (`frontend/src/services/tasks.ts` L230, L479) |

**Why it matters.** There are two command allowlists, two repair budgets and two state machines. Security fixes must be applied twice, and Stack B can bypass invariants enforced in Stack A.

**Remove** (after moving the two used GET endpoints under `/tasks/{id}/diff-ranges` and `/tasks/{id}/pr-metadata`, or keeping only those two):

| File / block | LOC | Action |
|---|---|---|
| `app/services/task_orchestrator.py` | 420 | Delete |
| `app/services/test_runner.py` | 482 | Delete (Stack A has `sandbox/test_runner.py`) |
| `app/services/repair_loop.py` | 333 | Delete (Stack A has `ai/services/bounded_repair_loop.py`) |
| `app/integrations/github/routes.py` routes at L267 `agent-branch`, L308 `commit`, L350/380 `pr-metadata` (POST), L407 `diff-ranges` (POST), L455 `branch-isolation`, L484 `task-branch/isolate`, L511 `validate-base`, L538 `task-workspace/tests`, L590 `task-workspace/repair`, L647 `task-workspace/status`, L688 `task/verify`, L760 `task/publish-pr`, L848 `task/{id}/pull-request`, L887 `task/recover`, L928 `task/cleanup`, L970 `task/execute-pipeline` | ~560 | Delete |
| `app/services/__init__.py` re-exports of the above | — | Remove lines |
| Related tests (find them with `grep -rl "app.services.test_runner\|app.services.repair_loop\|app.services.task_orchestrator\|/source/task" backend/tests tests/e2e`) | — | Delete or port the assertions to Stack A |

Keep `app/services/repair_service.py`. Stack A uses it (`FailureTracebackAnalyzer`, `extract_modified_files_from_diff`).

### A2.1 Other backend endpoints the frontend never calls

Decision key:
- **Delete** = no client, no external contract.
- **Keep (external)** = called by GitHub or intended for API/MCP use.
- **Keep (hidden)** = useful for ops; hide from docs.

| Endpoint | Decision | Reason |
|---|---|---|
| `GET/POST /repositories/{id}/search` | **Keep (external)** | Becomes the `search_code` MCP tool; also useful for a future search UI |
| `GET /repositories/{id}/symbols` | Keep (external) | Same (MCP `get_symbol`) |
| `GET /repositories/{id}/related-files` | **Delete** | Alias of `/explain/related-files`, which the UI uses |
| `GET /repositories/{id}/source/tree`, `/file`, `/commits`, `/commits/{sha}`, `/pulls`, `/pulls/{n}/diff` | Delete *or* keep for a future "live GitHub browse" feature | The UI browses indexed files via `/files` instead. If you keep them, they are the natural backing for an MCP read tool |
| `POST /tasks/{id}/tools/{tool_name}` | **Delete** (or admin-only) | Raw tool invocation API, unused by the UI. It is the largest attack surface in the task API |
| `POST /tasks/{id}/branch`, `/push`, `/checkpoints` (POST), `GET /invariants`, `/traceability`, `POST /authorize-publication`, `/run-workflow` | Keep, but remove the 15 unused frontend wrappers (§A7) or wire them into the UI | Server-side steps of the workflow; `run-workflow` becomes the async entry once durable workflows land |
| `issues.py` "alias" routes `/{repo_id}/issues…` (L540–583) | **Delete** | Same URL pattern as `/{repository_id}/issues…`, which is registered first, so these handlers are **unreachable** |
| `/github/webhook`, `/github/installation/callback`, `/auth/github/callback` | Keep (external) | Called by GitHub |

---

## A3. Modules reachable only from tests

Found by walking imports from the real entrypoints (`app.main`, `app.workers.sync_worker`, `scripts/*`). These modules are never loaded in production.

| Module | LOC | What it is | Overlaps with (live code) | Decision |
|---|---|---|---|---|
| `review/static_reviewer.py` | 193 | Ruff + Bandit runner with normalisation | Nothing live (see A1.3) | **WIRE** (preferably in the sandbox runner), then keep |
| `review/blast_radius.py` | 73 | `BlastRadiusEngine` | `ai/context/review_context.py::ReviewBlastRadius` (live) | **Delete** |
| `review/__init__.py` | 0 | Package marker | — | Delete with the package (if `static_reviewer` moves elsewhere) |
| `ai/services/bug_investigator.py` | 180 | Two-pass LLM investigator | `app/services/bug_validation_service.py` (live; supplies `counterevidence`) | **Delete** (or merge its prompt ideas into the live validator) |
| `ai/services/bug_finding_validator.py` | 88 | Hallucinated-finding filter used only by the investigator | `GroundingValidator` + `bug_validation_service` | **Delete** |
| `ai/services/test_requirement_service.py` | 177 | Test planning via LLM | `scanner/test_requirement_discovery.py` + `app/services/test_requirement_orchestrator.py` (live) | **Delete** |
| `indexer/embedding_queue.py` | 138 | Separate Redis embedding queue | `sync_worker.py` + `EmbeddingService` (live) | **Delete** |
| `scanner/task_acceptance_mapper.py` | 147 | Requirement → test scenario mapping | `ai/services/requirement_verifier.py` (live) | **Delete** |
| `scanner/task_impact_analyzer.py` | 162 | Task impact via `SymbolBlastRadius` | Planner heuristics (live) | **Delete**, and with it `scanner/symbol_blast_radius.py` (355 LOC), whose only importer is this module (plus a re-export in `scanner/__init__.py`) |

Notes:
- **Four blast-radius implementations exist**: `review/blast_radius.py`, `scanner/symbol_blast_radius.py`, `ai/intelligence/impact.py::DependencyImpactAnalyzer` (only `analyze_impact`, tests-only), and `ai/context/review_context.py::ReviewBlastRadius`. Keep **one** (`ReviewBlastRadius`) and move the best graph logic into it.
- Delete the matching tests together with each module, so the suite doesn't keep dead code alive.

**Total removable here:** about 1,500 LOC including `symbol_blast_radius.py`.

---

## A4. Unreferenced functions and classes

The custom AST scan found **177 definitions (~4,900 LOC)** whose name is never referenced anywhere in non-test backend code. 117 of them are referenced only by tests. The full list is in **Appendix 1**.

**Known false positives — do NOT delete:**
- `dispatch` methods in `app/core/{rate_limit,auth,logging}.py`: Starlette calls them.
- `validate_and_redact_content` and `validate_embedding` in `app/models/code_chunk.py`: SQLAlchemy `@validates` hooks.
- `_compile_jsonb_sqlite` and `_compile_vector_sqlite` in `scripts/seed_database.py`: `@compiles` hooks.
- `RetrieverProtocol` and `LLMGatewayProtocol` in `ai/pipeline.py`: typing protocols. They can still be removed if unused in type hints.

**High-confidence groups to remove:**

| Group | Examples (file:line) | ~LOC | Why it is dead |
|---|---|---|---|
| Per-feature history service methods | `explanation_history_service.py`: `save_explanation`, `record_failure`, `list_history`, `get_explanation` · `review_history_service.py`: `save_review`, `record_failure`, `list_history`, `get_review_summary`, `delete_review` · `bug_scan_history_service.py`: `record_failure`, `list_history`, `get_scan`, `get_latest_scan`, `find_existing_scan` · `test_generation_history_service.py`: `save_test_generation`, `record_failure`, `list_history`, `get_run_by_id`, `find_duplicate_run` · `analysis_run_history_service.py:find_duplicate` | ~650 | Only `record_run` is used, through reflection (§A6). History reads go through `analysis_run_repository` |
| GitHub service methods never called | `integrations/github/service.py`: `push_branch` (101 LOC), `create_task_branch`, `get_installation`, `list_branches`, `get_pull_request_detail`, `compare_branches`, `create_issue_from_finding` · `source_service.py`: `setup_task_branch`, `invalidate_cache` | ~300 | Publication uses `git_branch.py` |
| Context service getters | `ai/context/service.py`: `get_test_context`, `get_review_context`, `get_explanation_context`, `get_bug_context`, `audit_context_budget`, `estimate_context_tokens`, `invalidate_cache_for_repository`, `clear_cache`, `assert_revision_consistency` | ~330 | Orchestrators build contexts directly. **Note:** `invalidate_cache_for_repository` *should* be called after sync (§B2.6), so wire it rather than delete it |
| Prompt builders never used | `ai/schemas/prompt_builder.py`: `build_summary_prompt`, `build_grounding_prompt`, `build_repair_prompt`, `_load_prompt` | ~110 | Prompts `summary_system`, `grounding_system` and `repair_system` are loaded nowhere else. Keep `build_repair_prompt` **only if** you implement the LLM repair synthesizer from the research guide |
| Repository-layer helpers | `chunk_repository.py` (`get_chunks`, `get_by_content_hash`, `delete_by_file_id`) · `symbol_edge_repository.py` (both getters) · `code_symbol_repository.py:get_symbols_for_file` · `memory_repository.py` (both getters) · `repository_repository.py:get_stale_sync_jobs` · `task_repository.py`: `list_tool_invocations`, `_append_event`, `delete_event`, `update_event`, `update_approval` | ~150 | The indexer and orchestrators use raw SQL or other helpers. `get_by_content_hash` becomes useful for embedding reuse (§B3.1) |
| Budget/optimizer methods | `execution_budget_manager.py`: `record_token_usage`, `record_elapsed_time`, `get_remaining_budget`, `record_omitted_context` · `retrieval_optimizer.py`: `check_headroom`, `reset_stats`, `get_history`, `execute_optimized_retrieval`, `execute_concurrent_search` | ~130 | The orchestrator only records step attempts and file modifications (`task_execution_orchestrator.py` L457–459). **Token and wall-time budgets are never recorded or enforced**, and the retrieval optimizer is not on the live path. Wire token/time budgets into the agent loop (recommended for cost safety) or delete them |
| Misc. unused | `code_review_orchestrator.py:run_static_review_checks` (44) · `test_generation_orchestrator.py`: `detect_test_framework_and_conventions` (66), `sanitize_and_ground_test_result` · `issue_task_adapter.py:from_finding` (78) · `diff_verifier.py:assert_revision_integrity` · `test_coverage_analyzer.py:estimate_symbol_coverage` · `ast_rules.py`: `analyze_target_selection`, `register_rule` · `import_tracker.py:track_repository_imports` · `parser.py:get_supported_languages` · `core/database.py:init_async_db` · `telemetry.py:record_stage` · `github/cache.py:RevisionMismatchError` · `github/schemas.py`: `CommitListRequest`, `PullRequestListRequest`, `FileTargetType` · `bounded_repair_loop.py:RepairBudgetExhaustedError` | ~450 | Zero references |
| `ai/embeddings/service.py:CachedEmbeddingService` | 66 | Tests-only | **Wire it for query embeddings** (§B3.2), don't delete |

---

## A5. Unused imports and variables (one automated PR)

- **348 unused imports** outside `__init__.py`. The worst files:
  - `sandbox/workspace_manager.py` (28)
  - `app/services/bug_detection_orchestrator.py` (21)
  - `explanation_orchestrator.py` (15)
  - `test_generation_orchestrator.py` (13)
  - `code_review_orchestrator.py` (10)
  - `ai/context/service.py` (9)
  - `ai/context/task_context.py` (9)
  - `task_history_service.py` (9)
  - `task_execution_orchestrator.py` (9)
- **17 unused locals:** e.g. `ai/llm/client.py` L229 `primary_name`, `independent_verifier.py` L304 `start_time`, `git_branch.py` L1405 `old_start`, `workspace_manager.py` L808/L846 `meta`, `taint_analyzer.py` L361 `shell_true`, `import_tracker.py` L133 `current_dir`.
  - `taint_analyzer.py` L361 deserves a look: a computed `shell_true` that is never used suggests a check that was meant to happen but doesn't.
- **2 unused loop variables** (B007): `agent_execution_loop.py` L327, `ast_rules.py` L823.

How to apply it:

```bash
ruff check backend --exclude backend/tests --select F401,F841 --fix
ruff check backend --exclude backend/tests --select F401 --unsafe-fixes --fix   # review diff first
```

Keep intentional re-exports in `__init__.py` by declaring `__all__`. Then turn on Ruff in CI (`select = ["E","F","B","ASYNC","PERF","SIM","UP"]`) so this does not regrow. Today the CI "lint" stage only runs `compileall`.

---

## A6. Over-engineered patterns to simplify

| Pattern | Where | Problem | Simplification |
|---|---|---|---|
| **Reflection-based persistence chain** | `app/services/explanation_orchestrator.py` (persist function around L650–720), reused by bug/test/review orchestrators | For every analysis run it: picks a feature-specific history service; tries `record_run`/`save_run`/`create_run` by name; calls `inspect.signature` each time; falls back to `AnalysisRunRepository.create_run/create/save` by name; and **always** writes into an in-memory dict on `app.state._analysis_run_history` (not shared across processes; lost on restart) | One call: `AnalysisRunRepository(db).create_run(**record)`. Delete the four per-feature history services' unused methods (A4), the in-memory history store, and the `getattr` loops |
| Two SQLAlchemy engines | `app/core/database.py` | Sync engine (pool 20 + overflow 10) **and** async engine with the same kwargs → up to **60 connections per process** | Pick one. Async is recommended because the handlers are already `async def` (§B2.1). If you keep both, size the pools separately and small |
| Duck-typed workspace calls | `ai/services/agent_execution_loop.py` (`hasattr(self.workspace_manager, "patch_file")` …) | Branches for objects that don't exist in production | Type the dependency as `WorkspaceManager`; remove the `hasattr` fallbacks |
| Unused optional hooks on `app.state` | `static_reviewer`, `static_bug_scanner` | See A1.3 | Wire or delete |
| Test-only in-memory rate-limit store | `app/core/rate_limit.py::InMemoryRateLimitStore` (no expiry) | Never used in prod (the bounded variant is) | Move to `tests/` |
| Silent model remap | `ai/llm/gemini_provider.py` L124–125 maps `gemini-flash-lite-latest` → `gemini-flash-latest` | Config says one model; another (more expensive) one is used | Delete the remap; honour `GEMINI_CHAT_MODEL` |
| Root `main.py` + `backend/app/main.py` + `sys.path` hacks | `main.py`, `startup.sh`, `Dockerfile` `PYTHONPATH` | Three ways to locate the package | Install the backend as a package (`pyproject.toml` already declares packages) and run `uvicorn app.main:app` |

---

## A7. Frontend dead code

### A7.1 Orphan files (not reachable from `src/main.tsx`)

| File | LOC | Notes | Action |
|---|---|---|---|
| `src/components/explorer/CodeViewerEmptyState.tsx` | 2 | Re-export stub | Delete |
| `src/components/studios/StudioMobileTabs.tsx` | 2 | Re-export stub | Delete |
| `src/components/studios/StudioWorkspace.tsx` | 2 | Re-export stub | Delete |
| `src/hooks/useAnalysisState.ts` | 228 | Only its own test imports it | Delete with `src/test/useAnalysisState.test.ts` |
| `src/lib/classifyAnalysisError.ts` | 142 | Only its own test imports it | Delete with its test, **or** use it in the studios' error handling. It looks finished |
| `src/lib/msw/{index,node,browser}.ts` | 493 | A home-made MSW clone that `vite.config.ts` aliases over the real `msw` package | See A7.3 |

### A7.2 Exported but never used

- **`src/services/analysis.ts` (5):** `getBugScanHistory`, `reopenBugScan`, `getTestGenerationHistory`, `reopenTestGeneration`, `getAnalysisRunsSummary`.
- **`src/services/tasks.ts` (10):** `getTaskDetail`, `invokeTaskTool`, `ensureTaskBranch`, `pushTaskBranch`, `saveTaskCheckpoint`, `listTaskCheckpoints`, `checkTaskInvariants`, `runTaskAutonomousWorkflow`, `authorizeTaskPublication`, `getTaskTraceability`.
- **`src/realtime/events.ts`:** `TASK_UPDATED`, `AGENT_EVENT`, `VERIFY_RESULT`, `PR_UPDATED`. The backend never publishes task events over SSE, so the UI polls instead (§B1.2).
- **Components:** `ReviewTargetSelector` (exported from `CodeReviewView.tsx`, unused elsewhere).
- **Types:** `CodeExplanationResult`, `AnalysisResult`, `PaginatedTaskListResponse`, `SecurityEventItem`, `PlanStepActionType`.

**Action:** delete them, or wire `getAnalysisRunsSummary` into the Dashboard and `runTaskAutonomousWorkflow` into the Task Studio when async workflows land. Add **`knip`** (MIT) to CI to keep this list at zero.

### A7.3 MSW is implemented three times

| Piece | Status |
|---|---|
| `msw` ^2.15 in `devDependencies` | **Unused**. `vite.config.ts` aliases `msw`, `msw/node` and `msw/browser` to `src/lib/msw/*` |
| `src/lib/msw/*` (493 LOC shim) | Used by tests and the dev mock bootstrap; its `setupWorker` doesn't use a service worker at all |
| `public/mockServiceWorker.js` (9.7 KB) + `"msw": {"workerDirectory": …}` in `package.json` | **Unused**, and shipped publicly with every production build |

**Pick one.**
- **Recommended:** delete the shim and the alias, and use the real `msw` (it's maintained and works with Vitest).
- **Or:** keep the shim, then remove the `msw` dependency, the `package.json` `msw` block, and `public/mockServiceWorker.js`.

Either way, guard the dev bootstrap with `if (import.meta.env.DEV)` so Vite tree-shakes `src/mocks/handlers/task.ts` (3,533 LOC) out of the production build entirely. Also render the app immediately in production instead of awaiting `enableMocking()` (`src/main.tsx`).

---

## A8. Dependencies to remove or replace

| Dependency | Where | Status | Action |
|---|---|---|---|
| `python-jose[cryptography]` | `backend/requirements.txt`, `pyproject.toml` | Duplicates `PyJWT`; used in 2 files | Port to PyJWT; remove |
| `factory-boy` | `requirements-dev.txt` | 0 imports | Remove |
| `Faker` | `pyproject.toml [dev]` | 0 imports | Remove |
| `gunicorn` | `requirements.txt`, `pyproject.toml` | Unused (`startup.sh` runs uvicorn directly) | Remove, or actually use it (`gunicorn -k uvicorn.workers.UvicornWorker -w N`) (§B2.3) |
| `tree-sitter-languages` + `tree-sitter<0.22` pin | `requirements.txt` | Unmaintained | Replace with `tree-sitter-language-pack` |
| `ruff`, `bandit` | **production** `requirements.txt` | Only needed if scanners run in the API process (they don't, A1.3) | Move to the sandbox/runner image or dev requirements |
| `sentence-transformers` (pulls PyTorch, ~1–2 GB image) | `requirements.txt` | Used for one 22M-parameter reranker | Run the reranker via ONNX Runtime, or make it optional (§B3.5) |
| Dev requirements in the prod image | `Dockerfile` installs root `requirements.txt` → `requirements-dev.txt` | pytest, respx, etc. ship to production | Install `backend/requirements.txt` only, using a multi-stage build |
| Two dependency lists | `requirements*.txt` **and** `pyproject.toml` (already drifted: `responses` and `factory-boy` vs `Faker` and `pre-commit`) | Drift | Keep `pyproject.toml` as the single source and generate a lock (`uv lock` / `pip-compile`) |
| `msw` (frontend) | `package.json` | Unused because of the alias | See A7.3 |
| `greenlet` | `requirements.txt` | 0 direct imports, but **needed** by SQLAlchemy async | **Keep** (add a comment) |

---

## A9. Repository files and documentation clutter

| Item | Size | Action |
|---|---|---|
| `Docs/Acad/` (poster.png 1.9 MB, two mermaid PNGs 1.8 MB, activity diagram 0.3 MB, PDF) | ~4 MB of binaries in git | Move to GitHub Releases / a wiki / Git LFS; it bloats every clone |
| Root test plans: `BUG_DETECTION_…`, `EXPLAIN_CODE_…`, `TASK_PLANNER_EXECUTOR_…`, `TEST_GENERATION_COMPREHENSIVE_TEST_PLAN.md`, `TEST_INFRA.md`, `task.md` | ~220 KB | Move to `Docs/testing/` and `Docs/planning/` (root should hold only README, LICENSE, config) |
| `Docs/week*.md`, `Docs/*_day*_report.md`, `persistence_week3_*`, `Docs/audits/*` | ~40 files | Archive to `Docs/archive/2026-sprints/`. Keep `Docs/engineering/00–14` as the living docs |
| Backend tests named after people/days/audit rounds | **91 of 167** test files (e.g. `test_om_w2_d3_…`, `test_keval_w2_day4_…`, `test_meet_day5_…`, `test_final_codebase_audit_fixes.py`, `test_new_fixes_comprehensive_audit.py`) | Reorganise into `tests/unit/<package>/`, `tests/integration/`, `tests/security/`. Deduplicate the 11 test names that appear in several files (e.g. `test_multi_tenant_repository_isolation` ×4, `test_secrets_in_source_are_not_sent_to_the_llm` ×3) |
| Frontend tests named after review rounds | `pr161_*`, `challenger_m1/m2/m3_*`, `empirical_adversarial_challenge` | Rename by feature; merge overlapping ones |
| Tests for deleted modules (A2, A3) | — | Delete together with the code |

---

## A10. Safe removal order

1. **PR 1 – bug fixes (A1).** No deletions; adds tests for each bug.
2. **PR 2 – Ruff autofix (A5).** Mechanical; the full test suite must stay green.
3. **PR 3 – Stack B removal (A2)**, after moving the 2 used GET endpoints. Run the frontend tests and e2e tier suites.
4. **PR 4 – test-only modules and dead functions (A3, A4)**, in feature-sized batches with their tests.
5. **PR 5 – frontend cleanup (A7)** + `knip` in CI.
6. **PR 6 – dependencies and Dockerfile (A8).** Compare image size and cold start before and after.
7. **PR 7 – docs and test reorganisation (A9).**

Each PR must:
- keep the OpenAPI diff limited to the intended removals (`/openapi.json` before and after);
- pass `pytest` (full, not the CI subset) and `vitest`;
- report LOC removed.

Expected net reduction: **~8,000–9,000 LOC** of backend source (Stack B ~1.8k, test-only modules ~1.5k, dead functions ~3–4k, imports/misc), plus the matching tests, ~870 LOC of frontend, and ~4 MB of binaries.

---

# PART B — OPTIMIZE: frontend, backend, AI, database, Redis

Each item gives:
- **Evidence** — what the code does today, with a path.
- **Change** — what to do.
- **Gain** — the expected effect.
- **Effort** — S (≤1 day), M (2–5 days), L (1–2 weeks).

Gains are directional estimates. Measure each change with the benchmarks in §C.2.

## B1. Frontend

| # | Evidence | Change | Gain | Effort |
|---|---|---|---|---|
| B1.1 | `src/services/api.ts` `DEFAULT_TIMEOUT_MS = 30000`. Task actions (`executeTask`, `runTaskTests`, repair, verify) don't override it, but the backend runs these synchronously, with commands of up to 300 s | Short term: give long task calls their own timeout (e.g. 330 s). Proper fix: backend returns `202 + job id`, and the UI follows progress over SSE (§B2.2) | No false "request failed" while work continues server-side | S / M |
| B1.2 | `src/hooks/useTasks.ts` L109–120 polls task lists **every 3 s** while any task is active; `Dashboard.tsx` and `RepositoryDetail.tsx` poll sync status. The SSE stream exists (`src/realtime/*`), but the backend publishes only repository-sync events, and the task constants in `realtime/events.ts` are unused | Publish task state transitions to Redis (one line in `TaskRepository.transition_status`). In the UI, on an SSE event call `queryClient.invalidateQueries(taskKeys.detail(id))`. Keep polling as a 30 s fallback | ~90% fewer task API calls; instant UI updates | M |
| B1.3 | `useTasks.ts` spreads `...options` **after** setting `refetchInterval`, so a caller-supplied `refetchInterval` replaces the smart function wholesale | Destructure `refetchInterval` out of `options` before spreading | Correct polling behaviour | S |
| B1.4 | `src/components/explorer/CodeViewer.tsx` (649 LOC) splits the whole file and runs a custom regex `tokenizeLine` on **every line**, then renders every line (L229–233, L483). There's no virtualisation; `FileTree.tsx` is the same. *(Correction to the research guide: a simple custom highlighter does exist.)* | Virtualise with `@tanstack/react-virtual` (only visible lines are tokenised and rendered). For large files, tokenise lazily per visible window or move to Shiki in a Web Worker | Smooth scrolling on 5k–20k-line files; less memory | M |
| B1.5 | `src/main.tsx` awaits `enableMocking()` before the first render, even in production; `src/mocks/handlers/task.ts` (3,533 LOC) sits behind a runtime check, so Vite still emits it as a chunk | `if (import.meta.env.DEV) await enableMocking()` (a static guard enables tree-shaking); render immediately in prod | Smaller build; faster first paint | S |
| B1.6 | Large page components: `RepositoryTaskStudio.tsx` 1,977 LOC, `CodeReviewView.tsx` 1,365, `TestGenerationView.tsx` 960, `CreateTaskForm.tsx` 934, `BugScannerView.tsx` 867 | Split by phase/panel. Wrap heavy lists (findings, timeline events) in `React.memo` with stable keys. Lazy-load rarely opened panels (`PublicationPanel`, `RecoveryPanel`, `VerificationPanel`) with `React.lazy` | Fewer re-renders; smaller initial chunk for the Task Studio | M |
| B1.7 | React Query defaults: `retry: 1`, `refetchOnWindowFocus: false`; `staleTime` is set in only one hook (`useAnalysis.ts` 60 s), so most queries refetch on every mount | Set a global `staleTime` (e.g. 30 s) and per-query values for immutable data (file content by revision: `Infinity`; analysis runs: 5 min) | Fewer duplicate requests on navigation | S |
| B1.8 | Route-level `React.lazy` is already used in `App.tsx`, and `vite.config.ts` has vendor chunking | **Keep.** Add `build.reportCompressedSize` and a bundle analyzer (`rollup-plugin-visualizer`, MIT) run in CI to watch chunk sizes | Regression visibility | S |
| B1.9 | Chat is non-streaming (`useRepositoryChat.ts` header comment) | Stream tokens (`fetch` + `ReadableStream` or SSE) once the backend supports it | First token in ~1 s instead of waiting for the full answer | M |
| B1.10 | Dead frontend code (§A7) | Remove; add `knip` to CI | Smaller bundle; less to maintain | S |

## B2. Backend (FastAPI / Python)

### B2.1 Blocking the event loop (the biggest backend issue)

**Evidence.** 42 route handlers are declared `async def`, but they receive a **synchronous** `Session = Depends(get_db)` and run synchronous psycopg queries directly on the event loop. Examples:
- `app/api/v1/chat.py` L59.
- `app/api/v1/analysis/{explain,bugs,tests,review,history}.py`.
- `app/api/v1/issues.py`.
- `app/api/v1/github.py` (including the webhook).
- 18 handlers in `app/integrations/github/routes.py`.

Ruff ASYNC also flags blocking file I/O inside `async def`:
- `app/integrations/github/service.py` L412–474, L646.
- `app/services/repair_loop.py` L152/L227.
- `app/services/test_runner.py` L277.
- `indexer/incremental.py` L208.

On top of that, the intelligence snapshot JSON is read from disk on every explain/bug request (`ai/intelligence/snapshot_manager.py` L166, called from `explanation_orchestrator.py` L400 and `bug_detection_orchestrator.py` L420).

While one such request waits on the DB or disk, **every other request on that worker stalls**, including all SSE streams.

**Change (pick one per handler):**
- (a) Make handlers that don't need `await` plain `def`. FastAPI then runs them in its threadpool.
- (b) Use the async engine (`AsyncSessionLocal`, which already exists) with `AsyncSession` in async handlers.
- (c) Wrap the remaining blocking calls in `await asyncio.to_thread(...)`. `bugs.py` already does this for scanners.

Use `anyio.Path` or `to_thread` for file I/O. Cache snapshots in memory (an LRU keyed by `repo_id:commit`), or move them to Postgres JSONB (§B4.6).

**Gain:** large p95 improvement under concurrency; SSE stops stuttering. **Effort:** M.

### B2.2 Long work inside HTTP requests

**Evidence.**
- `execute`, `tests`, `repair`, `verify`, `publish` and `run-workflow` in `app/api/v1/tasks.py` are synchronous and can run for minutes. Commands are capped at `MAX_TIMEOUT_SECONDS = 300` (`sandbox/constants.py`).
- The Azure front end cuts requests at about 230 s, and the browser gives up at 30 s (B1.1).

**Change.**
- Return `202 Accepted` with a job id, and run the work in the worker process.
- The research guide recommends DBOS (Postgres-backed, MIT). A minimal interim is to reuse the existing Redis job-queue pattern from `sync_worker.py`.
- Stream progress over SSE.

**Gain:** no timeouts; API workers stay free. **Effort:** M–L.

### B2.3 Process model and startup

| # | Evidence | Change | Gain | Effort |
|---|---|---|---|---|
| B2.3a | `startup.sh` runs **one** uvicorn process (`python -m uvicorn main:app`, no `--workers`). CPU-bound work (tree-sitter parsing, the cross-encoder reranker, JSON diffing) shares that single process | Run `gunicorn -k uvicorn.workers.UvicornWorker -w $((2*CPU))` (gunicorn is already a dependency), or `uvicorn --workers N`. Run the sync worker as a **separate** process (`DISABLE_EMBEDDED_SYNC_WORKER=true`) | Uses all cores; indexing no longer slows the API | S |
| B2.3b | `startup.sh` runs `alembic upgrade head` on **every boot** and ignores failures (`|| echo "…Continuing startup."`) | Run migrations as a separate deploy step (CI job or pre-deploy hook). Fail the deploy on migration errors. Never race migrations across replicas | Safe deploys; faster cold start | S |
| B2.3c | `--forwarded-allow-ips='*'` in `startup.sh` | Restrict to the Azure front-end range, or keep `*` only behind a trusted proxy, consistent with `TRUST_PROXY_HEADERS` | Correct client IPs for rate limiting; no spoofing | S |
| B2.3d | `sentence-transformers` + PyTorch loaded in the API process for the reranker; the model downloads from Hugging Face at first use | Bake the model into the image at build time, or switch to ONNX Runtime (§B3.5). Warm it up in lifespan | Faster and predictable first chat; smaller image | S / M |

### B2.4 Code-level efficiency

| # | Evidence | Change | Effort |
|---|---|---|---|
| B2.4a | Reflection persistence chain per analysis run (`inspect.signature`, `getattr` loops, plus an in-memory dict on `app.state`) (§A6) | Single repository call | S |
| B2.4b | `get_task_for_user` eager-loads 5 relationships on every ownership check (§A1.2) | Light ownership query + a separate detail query | S |
| B2.4c | `scanner/graph.py` links a call to **every symbol with the same name** across the repo (`symbols_by_name[callee]`, L45–116). Common names (`get`, `run`, `save`, `process`) explode the edge count and slow sync and graph queries | Resolve in priority order: same file → imported module (`import_tracker`) → same package. Cap fan-out per call site (e.g. ≤3). Store `confidence` on the edge | M |
| B2.4d | Ruff PERF401/402: 56 list-building loops, e.g. `scanner/graph.py` (7), `ai/context/test_context.py` (6), `independent_verifier.py` (5), `ai/context/renderers.py` (5) | List comprehensions / `extend`. Micro-gains, but mechanical with `ruff --fix` | S |
| B2.4e | Very large modules: `task_execution_orchestrator.py` 2,338, `task_repository.py` 2,667, `analysis_run_repository.py` 2,612, `workspace_manager.py` 2,135, `bug_detection_orchestrator.py` 1,277 LOC | Split by responsibility (e.g. orchestrator → `execution.py`, `testing.py`, `verification.py`, `publication.py`). This is not a runtime gain, but it makes the optimizations above safe to do | M |
| B2.4f | `GitHubSourceService` uses the **sync** Redis client from async code (`source_service.py` L95 → `SourceRevisionCache(redis_client=get_redis())`) | Use the async client (§B5.1) | S |

### B2.5 Configuration

- **DB pool.** The pool is 20 + 10 overflow for each of the two engines (`app/core/config.py` L38–41). With N workers that is up to 60·N connections, while Supabase free/small plans allow far fewer direct connections **[verify for your plan]**.
  - Use the Supabase **pooler** (port 6543, transaction mode; the code already special-cases `:6543`).
  - Shrink pools to about 5 + 5 per process.
  - Keep `pool_pre_ping`.
- **Uvicorn.** Set `--timeout-keep-alive` and `--limit-concurrency`. Add `--proxy-headers` only behind a trusted proxy.
- **Logging.** Structured JSON logs at INFO in production. Log `llm_call` at DEBUG if volume is high; it fires on every LLM call.

### B2.6 Cache invalidation that already exists but isn't called

`ai/context/service.py::invalidate_cache_for_repository` exists but is never called. The context cache holds 128 entries for 5 minutes, so a just-synced repo can be explained from stale context. Call it at the end of a successful sync (`sync_worker.py`) and publish a `repo.synced` event so other workers invalidate theirs.

## B3. AI pipeline (LLM, embeddings, retrieval)

| # | Evidence | Change | Gain | Effort |
|---|---|---|---|---|
| B3.1 | **Re-embedding unchanged chunks.** When a file's hash changes, `indexer/incremental.py` re-chunks it and calls `embed_batch` on **all** its chunks (L365–370), although `code_chunks` has an index on `(repository_id, content_hash)` and `chunk_repository.get_by_content_hash` exists (unused) | Before embedding, `SELECT content_hash, embedding FROM code_chunks WHERE repository_id=:r AND content_hash = ANY(:hashes)` and reuse vectors that match the current `embedding_profile_version`; only embed misses. Also reuse across branches and forks with the same content | Typically **70–95% fewer embedding calls** on small edits (most chunks of a touched file are unchanged); faster syncs; stays inside Gemini free-tier limits | S |
| B3.2 | **Query embeddings recomputed every time.** `CachedEmbeddingService` (L1 LRU + optional Redis L2) exists in `ai/embeddings/service.py` but only tests use it | Wrap the query-side embedding service with it, key `emb:q:{profile_version}:{sha256(query)}`, TTL 24 h | Removes ~100–300 ms and one API call from every repeated search/chat question | S |
| B3.3 | **JSON-mode + repair loops.** Groq is called with `json_object` (`groq_provider.py` L256); Gemini gets no schema (only `responseMimeType`). `OutputValidator` then repairs malformed JSON with up to 2 extra LLM calls (`ai/pipeline.py` header) | Use Groq strict `json_schema` (supported for `openai/gpt-oss-120b`) and Gemini `responseSchema` | Fewer repair calls; lower latency and token cost; fewer failed runs | M |
| B3.4 | **One model for everything.** Every feature uses the primary chat model; `gemini-flash-lite-latest` is silently upgraded to `gemini-flash-latest` (§A6) | Route by task: a cheap/fast model for query rewrite, triage, the "should this hunk get a comment?" filter and titles; the stronger model for explanations, plans and repairs. Make it a per-feature config map in `LLMGateway` | Lower cost and latency for high-volume calls | S |
| B3.5 | **Reranker cost.** Cross-encoder `ms-marco-MiniLM-L-6-v2` via sentence-transformers/PyTorch on up to 30 pairs per query, on the API's CPU | Export to ONNX and run with `onnxruntime` (no PyTorch); limit torch/ORT threads to avoid oversubscription with multiple workers; skip reranking when the RRF top-k is already confident (score gap heuristic) or for short identifier queries | Smaller image (PyTorch is the heaviest dependency); lower CPU per query | M |
| B3.6 | **Prompt shape for provider-side caching.** Prompts are built per request by `PromptBuilder` | Keep the **static system prompt and instructions first** and the variable repository data last, with byte-identical prefixes across calls. Gemini applies implicit context caching to repeated prefixes on supported models **[verify current model support]** | Lower input-token cost on repeated calls | S |
| B3.7 | **Context size.** Token budgets use `tiktoken` (OpenAI vocabulary) for Gemini (`ai/context/token_budget.py` L33). Chat retrieval returns top-8 chunks plus memory plus history | Calibrate the budget with real `input_tokens` from responses (already logged). Trim history to the last N turns plus a running summary. Order the best chunks first and last | Fewer tokens per call at equal quality | S |
| B3.8 | **Embedding batch concurrency.** `EmbeddingService` uses a semaphore and batches of 100; retries rotate keys | Rate-limit at the queue level (requests per minute per key) instead of discovering limits via 429s; add jitter to retries | Fewer 429s; smoother syncs | S |
| B3.9 | **Token/time budgets not enforced** (§A4): only step attempts and file counts are recorded | Record `LLMResponse.input_tokens + output_tokens` per task step in `ExecutionBudgetManager` and stop at the ceiling | Caps runaway agent cost | S |
| B3.10 | **Graph fan-out** (B2.4c) also pollutes retrieval context with wrong "callers" | Fix edge resolution; only expand high-confidence edges into context | Better context precision | M |

## B4. Database (PostgreSQL + pgvector)

### B4.1 Missing indexes for real query patterns

| Table | Query pattern (where) | Existing index | Add |
|---|---|---|---|
| `symbol_edges` | `WHERE source_symbol_id = :id OR target_symbol_id = :id` (`explanation_orchestrator.py` L317); joins on `source_symbol_id` (`bug_graph_context_service.py` L318) | only `repository_id` | `ix_symbol_edges_source (source_symbol_id)`, `ix_symbol_edges_target (target_symbol_id)`; rewrite the `OR` as `UNION ALL` so both indexes are used |
| `code_symbols` | Lookup by name within a repo (target resolution, graph build) | `repository_id`; `(file_id, start_line)` | `(repository_id, name)` |
| `repository_files` | Lookup by `(repository_id, path)` everywhere (sync, `files/by-path`, explain) | only `repository_id` (model/migration drift, §A1.5) | `UNIQUE (repository_id, path)` |
| `code_chunks` | Fetch chunks by symbol; reconstruct a file ordered by line | `file_id`; `repository_id`; `(repository_id, content_hash)` | `(file_id, start_line)`; `(symbol_id)` partial `WHERE symbol_id IS NOT NULL` |
| `analysis_runs` | History lists: `WHERE repository_id = ? [AND feature_type = ?] ORDER BY created_at DESC LIMIT n` | single-column indexes | Composite `(repository_id, feature_type, created_at DESC)` |
| `task_events` | Timeline: `WHERE task_id = ? ORDER BY created_at` | `task_id` | `(task_id, created_at)` |
| `tool_invocations`, `test_runs`, `repair_attempts` | Per-task ordered lists | `task_id` | `(task_id, created_at)` |
| `tasks` | Repo dashboard: `WHERE repository_id = ? [AND status = ?] ORDER BY created_at DESC` (`task_repository.list_tasks`) | separate `repository_id`, `status` | `(repository_id, status, created_at DESC)` |

Verify each with `EXPLAIN (ANALYZE, BUFFERS)` on a seeded DB (the `scripts/seed_database.py` script exists) and drop single-column indexes the composites make redundant. Postgres MCP Pro's `analyze_workload_indexes`, mentioned in the research guide, can automate this.

### B4.2 Model ↔ migration drift

- `repository_files`: unique constraint, composite index and `ON DELETE CASCADE` are missing in migrations (§A1.5).
- The content tables (`repository_files`, `code_symbols`, `symbol_edges`, `code_chunks`, `memory_entries`) reference `repositories` **without** `ON DELETE CASCADE` in their migrations, while the newer task and analysis tables have it. To compensate, `RepositoryRepository.delete` (`app/repositories/repository_repository.py` L131+) deletes about 12 tables by hand inside the HTTP request. It also loads every `Task` into the ORM and deletes them one by one, which cascades through ORM-loaded events, executions and so on. For a large repo this is slow and holds locks for a long time.
  - **Change:** add `ON DELETE CASCADE` to those FKs (and `symbol_edges → code_symbols`, `code_chunks → repository_files/code_symbols`), reduce `delete()` to a single `DELETE FROM repositories WHERE id = :id`, and run it as a background job that also cleans workspaces and Redis keys.

**Action:** add `alembic check` (or `alembic revision --autogenerate` in dry-run) to CI with a Postgres service container. CI currently runs tests on SQLite, which hides all of this.

### B4.3 Write path during indexing

**Evidence.** `indexer/incremental.py` inserts chunks **one row at a time** in a Python loop (`for i, chunk in enumerate(chunks): await self._execute(INSERT …)`, around L385–420), with the vector serialised as a text literal (`CAST(:embedding AS vector)`).

**Change.**
- Batch with `executemany` / `insert().values([...])` in groups of 500.
- Or use `COPY … FROM STDIN (FORMAT BINARY)` via psycopg 3. pgvector's Python package supports binary vector adaptation, which avoids text formatting of 768 floats per row **[EXT-KNOWN]**.
- Commit once per file batch.

**Gain:** usually 5–20× faster bulk indexing **[estimate; measure]**. **Effort:** S–M.

### B4.4 Read path

- Ownership checks: use the light `get_task_for_user` (§A1.2). Load relationships only on detail endpoints, and paginate `events`.
- Analysis-run payloads: `analysis_runs.result_payload` holds full results (JSONB). List endpoints should select summary columns only (`load_only`/explicit columns), not the whole JSONB.
- File reconstruction from chunks (`reconstruct_file_from_chunks`) runs on every explain call. Cache the reconstructed file in Redis keyed by `repo:file:content_hash` (§B5.4), or store raw redacted file content once per file instead of rebuilding from overlapping chunks.

### B4.5 pgvector tuning

- Upgrade to pgvector ≥0.8. Use `SET LOCAL hnsw.ef_search = 64–100` and `hnsw.iterative_scan = relaxed_order` for queries filtered by `repository_id`; without iterative scans, filtered HNSW queries can return fewer rows than requested.
- If index size or RAM becomes an issue, switch to a `halfvec(768)` expression index (half the memory) with L2-normalised vectors.
- Run `VACUUM (ANALYZE)` after large re-indexes. HNSW builds are faster with a higher `maintenance_work_mem`.

### B4.6 Things in the wrong store

| Data | Today | Better |
|---|---|---|
| Repository intelligence snapshots | JSON files on local disk under `.workspaces/repository-intelligence` (`snapshot_manager.py` L37), read per request | Postgres JSONB table `repository_intelligence(repo_id, commit_sha, snapshot)` + in-process LRU. Works with multiple instances and survives redeploys |
| Analysis history | DB **and** an in-memory dict on `app.state` (§A6) | DB only |
| Rate-limit counters, JWT blocklist, caches, pub/sub | Redis | Keep in Redis |

### B4.7 Retention

`task_events`, `tool_invocations`, `analysis_findings` and `sync_jobs` grow without bound. Add a scheduled cleanup job, e.g. events older than 90 days for completed tasks and completed `sync_jobs` older than 30 days, or monthly partitioning for `task_events` once it is large.

## B5. Redis

| # | Evidence | Change | Gain | Effort |
|---|---|---|---|---|
| B5.1 | **Sync Redis client used from async code:** `app/core/auth.py` L40 (blocklist check), `app/api/v1/events.py` L41, `app/api/v1/github.py` L459 (webhook dedupe), `integrations/github/source_service.py` L95 (cache), `app/core/rate_limit.py` (via `asyncio.to_thread` on every request) | Use `get_redis_async()` everywhere in async paths; keep the sync client only for sync workers/scripts | No thread hop per request; no event-loop blocking | S |
| B5.2 | **SSE fan-out design:** every SSE connection opens its **own** pub/sub subscription to one global channel `platform_events`, receives **all** users' events, parses each in Python, and filters (`events.py`). The loop also does `get_message(timeout=1.0)` plus `asyncio.sleep(0.5)`, adding up to ~1.5 s latency. `owned_repo_ids` is computed once at connect time, so a repo connected later never streams | **Per-scope channels**: publish to `events:user:{user_id}` and `events:repo:{repo_id}`; each connection subscribes only to its own channels (re-subscribe on `repo.connected`). Or use **one subscriber per process** that dispatches to in-memory `asyncio.Queue`s per connection. Replace `get_message` polling with `async for msg in pubsub.listen()` | CPU and Redis connections scale with users, not users × events; near-instant delivery; fixes A1.4 by construction | M |
| B5.3 | **Reliable queue command:** `sync_worker.py` uses `BRPOPLPUSH` (deprecated since Redis 6.2) | `BLMOVE sync_jobs sync_jobs:processing RIGHT LEFT <timeout>`; add a dead-letter list after N attempts and a reaper for stuck `processing` items. Or move all jobs to a durable workflow engine (research guide) and stop using Redis as a queue | Future-proof; no lost or stuck jobs | S |
| B5.4 | **Caching opportunities:** GitHub source cache keys by revision with a 1 h TTL (`github/cache.py` L52) even for immutable, SHA-addressed content | Immutable keys (`sha`-addressed blobs/trees/diffs): TTL 7–30 days with `maxmemory-policy allkeys-lru`. Mutable keys (branch heads, PR lists): 60–300 s. New caches: query embeddings (B3.2), reconstructed files (B4.4), context bundles (shared across workers instead of in-process) | Fewer GitHub API and DB calls; caches shared across workers | S |
| B5.5 | **Rate limiter:** fixed-window `INCR` + `EXPIRE` pipeline, called via `to_thread`; the JWT blocklist `EXISTS` is a separate round-trip on the same request | Async client, plus one Lua script (or pipeline) that does both the blocklist check and the counter increment in one round-trip. Consider a sliding window (sorted set or two-window weighted) for AI endpoints to avoid boundary bursts | 1 round-trip instead of 2; fairer limits | S |
| B5.6 | **Payload size:** events and cache entries are JSON strings, and large cached file/diff payloads are stored uncompressed | Compress values > 8 KB (zlib/zstd); keep events small (IDs + status, and let the UI fetch details) | Lower Redis memory (matters on Upstash free/small tiers) | S |
| B5.7 | **Key hygiene:** keys like `auth:blocklist:{jti}`, `sync_jobs`, `platform_events` have no environment prefix | Prefix with `{env}:{app}:` (e.g. `prod:adp:…`) so staging and production can share an instance safely; document every key family with its TTL | Safety; easier debugging | S |
| B5.8 | **Upstash specifics:** `health_check_interval=30` for Upstash (`core/redis.py`) and long-lived pub/sub connections per SSE client | With per-scope channels or a single subscriber per process (B5.2), the connection count drops to ~1 per worker. Check your Upstash plan's limits on concurrent connections and commands per day **[verify]** | Stays within free/small-tier limits | — |

---

# PART C — Plan and measurement

## C.1 Prioritised action list

| Pri | Action | Section | Effort | Impact |
|---|---|---|---|---|
| P0 | Fix `json` NameError, duplicate `get_task_for_user`, SSE fail-open, `repository_files` constraint | A1 | S | Correctness / security |
| P0 | Wire `StaticReviewer` (or remove the claim) | A1.3 | S | Feature actually works |
| P0 | Stop blocking the event loop in 42 async handlers | B2.1 | M | Latency under load |
| P0 | Long task operations → 202 + background job + SSE | B2.2, B1.1 | M–L | No timeouts |
| P1 | Remove Stack B + unreachable aliases | A2 | M | −1.8k LOC, single security surface |
| P1 | Ruff autofix (348 imports, 17 vars) + Ruff in CI | A5 | S | Hygiene |
| P1 | Embedding reuse by `content_hash` + batched inserts | B3.1, B4.3 | S–M | Faster/cheaper sync |
| P1 | Missing indexes + `alembic check` in Postgres CI | B4.1, B4.2 | S | Query speed, drift prevention |
| P1 | Async Redis everywhere + SSE per-scope channels | B5.1, B5.2 | M | Scalability |
| P1 | Multi-worker server, separate sync worker, migrations out of startup | B2.3 | S | Throughput, safe deploys |
| P2 | Delete test-only modules and dead functions (with tests) | A3, A4 | M | −3–5k LOC |
| P2 | Strict structured outputs + model routing | B3.3, B3.4 | M | Cost, latency |
| P2 | Query-embedding cache, Redis caches, compression | B3.2, B5.4, B5.6 | S | Latency |
| P2 | Task events over SSE instead of 3 s polling | B1.2 | M | API load |
| P2 | Frontend cleanup, MSW dedupe, virtualised viewer, global staleTime | A7, B1.4–B1.7 | M | Bundle, UX |
| P3 | Reranker on ONNX; drop PyTorch | B3.5 | M | Image size, CPU |
| P3 | Graph edge resolution with confidence | B2.4c, B3.10 | M | Graph quality, sync speed |
| P3 | Snapshots to Postgres; retention jobs | B4.6, B4.7 | M | Multi-instance correctness, storage |
| P3 | Docs/tests reorganisation; binaries out of git | A9 | S | Repo hygiene |

## C.2 How to measure the gains

| Metric | How | Baseline to record before changes |
|---|---|---|
| API p50/p95 under concurrency | `locust` or `k6` (both OSS): 20 virtual users mixing chat, explain, task detail and SSE connections | p95 per endpoint; SSE event delay |
| Event-loop blocking | `PYTHONASYNCIODEBUG=1` with `loop.slow_callback_duration = 0.1` in staging; count warnings | Number of slow callbacks per minute |
| Sync throughput | Time and Gemini calls to (re)index a fixture repo after a one-line change | Seconds; embedding API calls |
| DB | `pg_stat_statements` top queries by total time; `EXPLAIN ANALYZE` for the queries in B4.1 | Top 10 statements |
| Redis | `INFO commandstats`, `INFO clients` (connected clients), memory | Commands/min, connections, used memory |
| LLM cost | Sum `input_tokens`/`output_tokens` from `llm_call` logs per feature per day | Tokens per request per feature |
| Frontend | `vite build` chunk sizes (+ visualizer), Lighthouse on `/app/repositories/:id/tasks`, React Profiler on CodeViewer with a 10k-line file | KB per chunk, LCP, render ms |
| Codebase size | `cloc backend frontend/src` | LOC before and after each cleanup PR |

## C.3 Guardrails while cleaning up

- Do not delete anything listed as a false positive (§A4) or marked **WIRE**.
- Delete code **and** its tests in the same PR, and keep coverage stable or rising on the remaining modules.
- Keep the public REST contract for endpoints the UI uses (the list in §A2.1). Diff `/openapi.json` per PR.
- Prefer one mechanism per concern: one task API, one test runner, one repair loop, one blast-radius engine, one history path, one MSW, one JWT library, one dependency manifest.

---

# Appendix 1 — All unreferenced backend functions/classes (raw scan output)

Generated by an AST scan of `backend/` (excluding `tests/` and `migrations/`). A definition is listed when its name has **zero** references (Name, Attribute, import alias or identifier string) anywhere in non-test backend code. `[tests:N]` means N references exist only in tests; `[unused]` means none at all. Paths are relative to `backend/`. Check §A4 for known false positives before deleting.

| LOC | Location | Definition / usage |
|---|---|---|
| 171 | `review/static_reviewer.py:23` | class StaticReviewer [tests:6] |
| 139 | `ai/services/bug_investigator.py:42` | class BugInvestigator [tests:3] |
| 134 | `scanner/source_location.py:215` | resolve_target [tests:16] |
| 129 | `app/services/task_execution_report.py:51` | build_report [tests:3] |
| 122 | `ai/services/test_requirement_service.py:55` | class TestRequirementService [tests:5] |
| 118 | `indexer/embedding_queue.py:21` | class EmbeddingQueue [tests:9] |
| 101 | `app/integrations/github/service.py:611` | push_branch [tests:3] |
| 98 | `scanner/task_impact_analyzer.py:61` | analyze_impact [tests:2] |
| 95 | `ai/services/bug_investigator.py:86` | investigate_and_verify [tests:1] |
| 87 | `indexer/embedding_queue.py:40` | process_batch [tests:6] |
| 83 | `app/core/rate_limit.py:205` | dispatch [unused] |
| 81 | `scanner/workspace_preflight.py:77` | validate_preflight [tests:5] |
| 78 | `ai/services/issue_task_adapter.py:315` | from_finding [unused] |
| 78 | `scanner/task_acceptance_mapper.py:66` | map_requirements_to_scenarios [unused] |
| 77 | `ai/intelligence/impact.py:42` | analyze_impact [tests:2] |
| 73 | `ai/services/execution_recovery.py:44` | handle_step_failure [tests:2] |
| 71 | `app/services/review_history_service.py:47` | save_review [tests:3] |
| 69 | `ai/services/test_requirement_service.py:108` | plan_tests_with_ai [unused] |
| 66 | `ai/embeddings/service.py:281` | class CachedEmbeddingService [tests:2] |
| 66 | `app/services/test_generation_orchestrator.py:755` | detect_test_framework_and_conventions [unused] |
| 63 | `app/services/analysis_run_history_service.py:172` | find_duplicate [tests:4] |
| 61 | `review/blast_radius.py:12` | class BlastRadiusEngine [tests:4] |
| 58 | `ai/services/ai_quality_evaluator.py:328` | generate_quality_report [tests:1] |
| 58 | `app/services/test_generation_history_service.py:45` | save_test_generation [tests:2] |
| 54 | `ai/context/service.py:425` | get_test_context [tests:5] |
| 54 | `ai/context/service.py:483` | get_review_context [tests:8] |
| 52 | `ai/context/service.py:315` | get_explanation_context [tests:28] |
| 50 | `ai/context/service.py:371` | get_bug_context [tests:5] |
| 47 | `ai/context/intelligence_context.py:172` | build_test_intelligence_context [tests:3] |
| 45 | `scanner/task_test_planner.py:305` | create_test_plan [tests:1] |
| 44 | `app/services/code_review_orchestrator.py:1136` | run_static_review_checks [unused] |
| 44 | `scanner/source_mapper.py:210` | to_source_references [tests:3] |
| 43 | `app/services/git_branch.py:724` | collect_pr_metadata_from_workspace [tests:1] |
| 42 | `ai/services/retrieval_optimizer.py:265` | get_latency_percentiles [tests:1] |
| 41 | `app/core/auth.py:65` | dispatch [unused] |
| 38 | `ai/schemas/prompt_builder.py:141` | build_summary_prompt [tests:1] |
| 38 | `app/services/explanation_history_service.py:41` | save_explanation [tests:2] |
| 37 | `app/repositories/analysis_run_repository.py:2123` | update_status [tests:3] |
| 37 | `scanner/test_coverage_analyzer.py:76` | parse_coverage_output [tests:2] |
| 36 | `sandbox/diff_verifier.py:333` | assert_revision_integrity [unused] |
| 36 | `app/integrations/github/service.py:833` | create_task_branch [tests:1] |
| 35 | `ai/schemas/prompt_builder.py:180` | build_grounding_prompt [tests:1] |
| 35 | `review/blast_radius.py:15` | compute [tests:2] |
| 35 | `scanner/source_mapper.py:935` | map_line_to_symbol [tests:1] |
| 34 | `app/services/git_branch.py:204` | create_isolated_task_workspace [tests:5] |
| 34 | `app/services/explanation_history_service.py:80` | record_failure [tests:5] |
| 34 | `app/services/review_history_service.py:119` | record_failure [tests:5] |
| 34 | `scanner/symbol_blast_radius.py:322` | analyze_task_diff_ranges [tests:1] |
| 33 | `scanner/test_coverage_analyzer.py:114` | estimate_symbol_coverage [unused] |
| 32 | `ai/services/ai_quality_evaluator.py:291` | evaluate_schema_conformance [tests:2] |
| 32 | `ai/context/service.py:206` | audit_context_budget [tests:1] |
| 31 | `ai/schemas/grounding.py:90` | validate_answer [tests:8] |
| 31 | `ai/context/review_context.py:76` | parse_diff_hunks [tests:1] |
| 31 | `app/services/bug_scan_history_service.py:129` | list_history [tests:4] |
| 30 | `app/services/test_generation_history_service.py:104` | record_failure [tests:5] |
| 30 | `app/services/bug_scan_history_service.py:94` | record_failure [tests:5] |
| 30 | `scanner/source_mapper.py:255` | to_modified_files [tests:1] |
| 29 | `ai/schemas/prompt_builder.py:216` | build_repair_prompt [tests:1] |
| 29 | `ai/context/service.py:114` | invalidate_cache_for_repository [tests:2] |
| 29 | `app/services/code_review_orchestrator.py:1105` | parse_unified_diff_changed_lines [tests:4] |
| 29 | `app/services/test_generation_history_service.py:139` | list_history [tests:4] |
| 29 | `app/services/review_history_service.py:293` | get_review_summary [tests:1] |
| 29 | `scanner/ast_rules.py:1339` | analyze_target_selection [unused] |
| 28 | `ai/services/bug_investigator.py:57` | build_investigation_packet [tests:1] |
| 26 | `app/services/explanation_history_service.py:119` | list_history [tests:4] |
| 24 | `ai/services/retrieval_optimizer.py:106` | consume [tests:6] |
| 24 | `ai/services/retrieval_optimizer.py:212` | execute_optimized_retrieval [tests:2] |
| 24 | `ai/services/retrieval_optimizer.py:237` | execute_concurrent_search [tests:1] |
| 24 | `app/services/test_generation_orchestrator.py:838` | sanitize_and_ground_test_result [unused] |
| 24 | `app/services/bug_scan_history_service.py:239` | find_existing_scan [tests:1] |
| 23 | `ai/embeddings/service.py:110` | validate_query_profile [tests:3] |
| 23 | `app/repositories/task_repository.py:2064` | get_task_for_user [tests:2] |
| 23 | `scanner/target_selector.py:98` | to_target_snippet [tests:3] |
| 22 | `app/services/test_generation_history_service.py:216` | find_duplicate_run [unused] |
| 22 | `app/services/review_history_service.py:211` | list_history [tests:4] |
| 22 | `app/integrations/github/service.py:797` | create_issue_from_finding [tests:1] |
| 22 | `app/integrations/github/source_service.py:724` | setup_task_branch [tests:1] |
| 22 | `review/blast_radius.py:51` | compute_symbols [unused] |
| 22 | `scanner/static_bug_scanner.py:67` | scan_file [tests:1] |
| 21 | `ai/services/ai_quality_evaluator.py:156` | enforce_provider_policy [tests:2] |
| 21 | `ai/schemas/grounding.py:68` | validate_citation [tests:2] |
| 21 | `app/repositories/task_repository.py:2359` | _append_event [unused] |
| 20 | `sandbox/workspace_manager.py:1795` | assert_not_stale [tests:2] |
| 20 | `ai/services/bug_finding_validator.py:68` | filter_hallucinated_findings [tests:1] |
| 20 | `app/services/bug_scan_history_service.py:186` | get_latest_scan [tests:1] |
| 20 | `app/core/logging.py:89` | dispatch [unused] |
| 19 | `ai/context/service.py:185` | assert_revision_consistency [tests:2] |
| 19 | `app/repositories/analysis_run_repository.py:2161` | add_findings [tests:1] |
| 18 | `app/repositories/pull_request_repository.py:80` | update_status [tests:3] |
| 17 | `ai/services/execution_checkpoint_manager.py:112` | rollback_to_checkpoint [tests:1] |
| 17 | `ai/schemas/validator.py:119` | validate_or_raise [tests:1] |
| 17 | `ai/intelligence/snapshot_manager.py:173` | load_snapshot_for_commit [tests:1] |
| 17 | `ai/context/service.py:240` | estimate_context_tokens [tests:1] |
| 17 | `app/integrations/github/service.py:274` | get_installation [unused] |
| 16 | `app/models/code_chunk.py:39` | validate_embedding [unused] |
| 16 | `app/core/input_security.py:67` | resolve_within_root [tests:2] |
| 16 | `scanner/rule_registry.py:69` | list_rules [tests:6] |
| 15 | `sandbox/workspace_manager.py:568` | fail_execution [tests:2] |
| 15 | `app/integrations/github/service.py:346` | list_branches [unused] |
| 15 | `scanner/import_tracker.py:486` | track_repository_imports [unused] |
| 14 | `app/services/explanation_orchestrator.py:730` | enforce_gateway_provider_policy [tests:10] |
| 14 | `app/repositories/repository_repository.py:116` | get_stale_sync_jobs [unused] |
| 14 | `app/integrations/github/source_service.py:211` | invalidate_cache [unused] |
| 13 | `ai/retrieval/fusion.py:153` | fuse_adaptive [tests:1] |
| 13 | `app/services/test_generation_orchestrator.py:823` | validate_generated_test_code [tests:3] |
| 12 | `ai/llm/schemas.py:156` | parse_schema [tests:2] |
| 12 | `app/integrations/github/service.py:784` | get_pull_request_detail [unused] |
| 12 | `app/integrations/github/service.py:820` | compare_branches [unused] |
| 11 | `indexer/embedding_queue.py:128` | recover_stale_processing [unused] |
| 11 | `app/services/task_history_service.py:718` | get_active_tasks [unused] |
| 11 | `app/repositories/task_repository.py:2347` | list_tool_invocations [unused] |
| 11 | `app/repositories/chunk_repository.py:15` | get_chunks [unused] |
| 11 | `app/repositories/chunk_repository.py:27` | get_by_content_hash [unused] |
| 11 | `app/repositories/chunk_repository.py:39` | delete_by_file_id [unused] |
| 10 | `ai/pipeline.py:59` | class RetrieverProtocol [unused] |
| 10 | `ai/services/execution_budget_manager.py:83` | record_token_usage [unused] |
| 10 | `ai/services/execution_budget_manager.py:94` | record_elapsed_time [unused] |
| 10 | `ai/services/retrieval_optimizer.py:131` | truncate_to_budget [tests:1] |
| 10 | `app/services/test_generation_history_service.py:169` | get_run_by_id [tests:2] |
| 10 | `app/services/git_branch.py:420` | create_agent_branch [tests:2] |
| 10 | `app/services/explanation_history_service.py:146` | get_explanation [tests:1] |
| 10 | `app/services/review_history_service.py:282` | delete_review [unused] |
| 10 | `app/services/bug_scan_history_service.py:161` | get_scan [tests:1] |
| 10 | `app/schemas/repair.py:259` | record_attempt [tests:3] |
| 10 | `app/integrations/github/cache.py:30` | class RevisionMismatchError [unused] |
| 10 | `scanner/task_test_planner.py:290` | build_test_manifest_batches [tests:1] |
| 9 | `ai/services/execution_budget_manager.py:121` | get_remaining_budget [unused] |
| 9 | `app/schemas/plan.py:799` | validate_against_constraints [tests:2] |
| 9 | `app/repositories/memory_repository.py:24` | get_active_memory_entries [unused] |
| 9 | `app/api/v1/events.py:98` | _is_event_authorized_for_user [unused] |
| 9 | `app/models/code_chunk.py:28` | validate_and_redact_content [unused] |
| 9 | `app/core/database.py:151` | get_db_async [tests:2] |
| 9 | `app/core/rate_limit.py:127` | class InMemoryRateLimitStore [tests:5] |
| 8 | `sandbox/workspace_manager.py:1526` | sanitize_log [tests:2] |
| 8 | `indexer/incremental.py:44` | should_reindex [tests:4] |
| 8 | `app/services/git_branch.py:318` | get_default_branch [tests:2] |
| 8 | `app/schemas/plan.py:809` | approve [tests:10] |
| 8 | `app/repositories/pull_request_repository.py:99` | delete_by_task_id [tests:1] |
| 8 | `app/repositories/memory_repository.py:15` | get_memory_entries [unused] |
| 7 | `ai/services/retrieval_optimizer.py:94` | estimate_tokens [tests:1] |
| 7 | `app/repositories/task_repository.py:351` | get_task_for_user [tests:2] |
| 7 | `app/repositories/symbol_edge_repository.py:15` | get_edges_for_source_symbol [unused] |
| 7 | `app/repositories/symbol_edge_repository.py:23` | get_edges_for_target_symbol [unused] |
| 7 | `app/repositories/code_symbol_repository.py:24` | get_symbols_for_file [unused] |
| 7 | `app/core/database.py:124` | init_async_db [unused] |
| 6 | `ai/services/execution_checkpoint_manager.py:97` | get_checkpoint [unused] |
| 6 | `ai/schemas/prompt_builder.py:34` | _load_prompt [unused] |
| 6 | `ai/context/explanation.py:73` | generate_source_references [tests:1] |
| 6 | `ai/context/builder.py:195` | _fit_items [tests:4] |
| 6 | `app/services/code_review_orchestrator.py:1182` | compute_category_counts [tests:1] |
| 6 | `app/integrations/github/schemas.py:214` | class CommitListRequest [unused] |
| 5 | `ai/context/service.py:108` | clear_cache [unused] |
| 5 | `ai/context/builder.py:188` | _fit_history [tests:4] |
| 5 | `app/integrations/github/schemas.py:273` | class PullRequestListRequest [unused] |
| 4 | `sandbox/workspace_manager.py:2132` | reap_expired_workspaces [tests:1] |
| 4 | `ai/pipeline.py:72` | class LLMGatewayProtocol [unused] |
| 4 | `app/schemas/plan.py:543` | topological_sort [tests:1] |
| 4 | `app/integrations/github/service.py:362` | get_default_branch [tests:2] |
| 4 | `app/integrations/github/schemas.py:25` | class FileTargetType [unused] |
| 4 | `app/core/telemetry.py:126` | set_model_info [tests:1] |
| 3 | `sandbox/workspace_manager.py:796` | get_execution_timeline [tests:19] |
| 3 | `sandbox/resource_monitor.py:71` | check_output_limit [tests:2] |
| 3 | `ai/services/execution_budget_manager.py:105` | record_omitted_context [unused] |
| 3 | `ai/services/retrieval_optimizer.py:102` | check_headroom [unused] |
| 3 | `ai/services/retrieval_optimizer.py:308` | reset_stats [unused] |
| 3 | `ai/services/execution_checkpoint_manager.py:108` | can_resume [tests:1] |
| 3 | `app/repositories/task_repository.py:2496` | delete_event [tests:1] |
| 3 | `app/repositories/task_repository.py:2500` | update_event [tests:1] |
| 3 | `app/repositories/task_repository.py:2504` | update_approval [tests:1] |
| 3 | `app/core/telemetry.py:104` | record_stage [unused] |
| 3 | `scanner/parser.py:47` | get_supported_languages [unused] |
| 3 | `scanner/ast_rules.py:1104` | register_rule [unused] |
| 2 | `ai/services/bounded_repair_loop.py:56` | class RepairBudgetExhaustedError [unused] |
| 2 | `ai/services/retrieval_optimizer.py:142` | get_history [unused] |
| 2 | `ai/context/builder.py:184` | _dedup_memory [tests:5] |
| 2 | `scripts/seed_database.py:17` | _compile_jsonb_sqlite [unused] |
| 2 | `scripts/seed_database.py:23` | _compile_vector_sqlite [unused] |

# Appendix 2 — Unused imports per file (Ruff F401, excluding `__init__.py`)

| Count | File |
|---|---|
| 28 | `backend/sandbox/workspace_manager.py` |
| 21 | `backend/app/services/bug_detection_orchestrator.py` |
| 15 | `backend/app/services/explanation_orchestrator.py` |
| 13 | `backend/app/services/test_generation_orchestrator.py` |
| 10 | `backend/app/services/code_review_orchestrator.py` |
| 9 | `backend/app/services/task_history_service.py` |
| 9 | `backend/app/services/task_execution_orchestrator.py` |
| 9 | `backend/ai/context/task_context.py` |
| 9 | `backend/ai/context/service.py` |
| 7 | `backend/scripts/benchmark_quality_suite.py` |
| 7 | `backend/app/repositories/task_repository.py` |
| 7 | `backend/ai/services/test_requirement_service.py` |
| 6 | `backend/app/services/independent_verifier.py` |
| 6 | `backend/app/services/explanation_history_service.py` |
| 6 | `backend/app/integrations/github/service.py` |
| 6 | `backend/ai/services/task_planner.py` |
| 4 | `backend/scanner/test_requirement_discovery.py` |
| 4 | `backend/scanner/test_gap_analyzer.py` |
| 4 | `backend/scanner/target_selector.py` |
| 4 | `backend/scanner/source_mapper.py` |
| 4 | `backend/scanner/ast_rules.py` |
| 4 | `backend/sandbox/diff_verifier.py` |
| 4 | `backend/app/services/test_runner.py` |
| 4 | `backend/app/services/test_generation_report.py` |
| 4 | `backend/app/services/test_generation_history_service.py` |
| 4 | `backend/app/services/review_history_service.py` |
| 4 | `backend/app/services/git_branch.py` |
| 4 | `backend/app/services/bug_scan_history_service.py` |
| 4 | `backend/ai/services/requirement_verifier.py` |
| 3 | `backend/sandbox/test_runner.py` |
| 3 | `backend/sandbox/command_runner.py` |
| 3 | `backend/app/services/test_requirement_orchestrator.py` |
| 3 | `backend/app/services/task_recovery.py` |
| 3 | `backend/app/services/repair_loop.py` |
| 3 | `backend/app/services/bug_candidate_discovery.py` |
| 3 | `backend/app/services/analysis_run_history_service.py` |
| 3 | `backend/app/schemas/repair.py` |
| 3 | `backend/app/api/v1/repositories.py` |
| 3 | `backend/ai/services/execution_verifier.py` |
| 3 | `backend/ai/services/execution_recovery.py` |
| 3 | `backend/ai/services/ai_quality_evaluator.py` |
| 3 | `backend/ai/embeddings/gemini_provider.py` |
| 2 | `backend/scanner/workspace_preflight.py` |
| 2 | `backend/scanner/test_mapper.py` |
| 2 | `backend/scanner/test_coverage_analyzer.py` |
| 2 | `backend/scanner/task_impact_analyzer.py` |
| 2 | `backend/scanner/framework_detector.py` |
| 2 | `backend/sandbox/tool_policy_bridge.py` |
| 2 | `backend/app/services/task_orchestrator.py` |
| 2 | `backend/app/services/task_execution_report.py` |
| 2 | `backend/app/services/bug_graph_context_service.py` |
| 2 | `backend/app/schemas/workspace.py` |
| 2 | `backend/app/models/task.py` |
| 2 | `backend/app/api/v1/tasks.py` |
| 2 | `backend/app/api/v1/events.py` |
| 2 | `backend/app/api/v1/analysis/bugs.py` |
| 2 | `backend/ai/services/task_requirement_discovery.py` |
| 2 | `backend/ai/services/retrieval_optimizer.py` |
| 2 | `backend/ai/services/plan_replanner.py` |
| 2 | `backend/ai/services/execution_checkpoint_manager.py` |
| 2 | `backend/ai/services/bug_investigator.py` |
| 2 | `backend/ai/services/bug_detection_engine.py` |
| 2 | `backend/ai/intelligence/related_files.py` |
| 2 | `backend/ai/intelligence/impact.py` |
| 2 | `backend/ai/context/bug_context.py` |
| 1 | `backend/scripts/test_context_real.py` |
| 1 | `backend/scripts/seed_database.py` |
| 1 | `backend/scripts/benchmark_rag.py` |
| 1 | `backend/scanner/test_quality_analyzer.py` |
| 1 | `backend/scanner/taint_analyzer.py` |
| 1 | `backend/scanner/symbol_blast_radius.py` |
| 1 | `backend/scanner/source_location.py` |
| 1 | `backend/scanner/rule_registry.py` |
| 1 | `backend/scanner/import_tracker.py` |
| 1 | `backend/sandbox/path_guard.py` |
| 1 | `backend/sandbox/constants.py` |
| 1 | `backend/migrations/versions/24498ac67b3e_add_pgvector_extension.py` |
| 1 | `backend/migrations/env.py` |
| 1 | `backend/app/services/repository_metadata_service.py` |
| 1 | `backend/app/services/repair_service.py` |
| 1 | `backend/app/services/bug_validation_service.py` |
| 1 | `backend/app/schemas/ai_quality.py` |
| 1 | `backend/app/models/github_installation.py` |
| 1 | `backend/app/models/base.py` |
| 1 | `backend/app/models/analysis_run.py` |
| 1 | `backend/app/integrations/github/client.py` |
| 1 | `backend/app/core/telemetry.py` |
| 1 | `backend/app/core/logging.py` |
| 1 | `backend/app/core/lifespan.py` |
| 1 | `backend/app/api/v1/github.py` |
| 1 | `backend/app/api/v1/chat.py` |
| 1 | `backend/app/api/v1/analysis/common.py` |
| 1 | `backend/ai/services/test_generation_service.py` |
| 1 | `backend/ai/services/task_completeness_checker.py` |
| 1 | `backend/ai/services/explanation_service.py` |
| 1 | `backend/ai/services/code_review_engine.py` |
| 1 | `backend/ai/services/bug_finding_validator.py` |
| 1 | `backend/ai/services/bounded_repair_loop.py` |
| 1 | `backend/ai/services/agent_execution_loop.py` |
| 1 | `backend/ai/llm/gemini_provider.py` |
| 1 | `backend/ai/llm/client.py` |
| 1 | `backend/ai/intelligence/snapshot_manager.py` |
| 1 | `backend/ai/intelligence/models.py` |
| 1 | `backend/ai/embeddings/client.py` |
| 1 | `backend/ai/context/test_context.py` |
| 1 | `backend/ai/context/explanation.py` |

# Appendix 3 — Commands used

```bash
ruff check backend --exclude backend/tests --select F401,F811,F841,F821 --isolated
ruff check backend --exclude backend/tests --select ASYNC,PERF,SIM,B --isolated
# module reachability + unreferenced definitions: custom AST scripts (import graph from app.main, app.workers.sync_worker, scripts/*)
# frontend: custom TS import graph from src/main.tsx; recommended permanent tool: npx knip
# frontend↔backend route cross-check: grep of API path literals in frontend/src vs @router decorators
```

*End of audit. No project file was modified.*
