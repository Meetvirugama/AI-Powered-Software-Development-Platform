# 01 — Requirements & Scope

## 1. Problem Statements

1. **Autonomous Code Synthesis Failure:**
   The agent execution loop cannot autonomously generate code for approved plan steps. If the HTTP caller does not provide pre-crafted code payloads, modification steps fail. Furthermore, a legacy fallback bug accidentally borrows payloads from other steps, causing unintended file mutations.
2. **Synchronous HTTP Execution Bottleneck:**
   Long-running post-approval workflows (step execution $\rightarrow$ test runs $\rightarrow$ bounded repairs $\rightarrow$ verification $\rightarrow$ draft PR) execute synchronously within the client request lifecycle. Any connection interruption, browser refresh, proxy timeout, or server restart terminates execution unpredictably.

---

## 2. Functional Requirements

- **FR-1: EditSynthesizer Service:** Implement `EditSynthesizer` in `backend/ai/services/edit_synthesizer.py` to autonomously generate code changes using existing LLM infrastructure.
- **FR-2: Search/Replace Patch Format:** Edits must be generated as structured search/replace blocks (`file`, `search`, `replace`).
- **FR-3: Exact Single-Match Enforcement:** Edits are accepted only if the `search` block occurs exactly once in the target file (`current_content.count(search) == 1`). Ambiguous or zero-match patches must be rejected.
- **FR-4: Validation Pipeline:** Every synthesized edit must pass:
  1. Structured output schema validation.
  2. Exact single-match validation.
  3. Path guard and workspace boundary validation.
  4. In-memory patch dry-run application.
  5. Language-specific syntax validation (Python `ast.parse`, JSON `json.loads`).
  6. Sandbox lint validation (Ruff where available).
- **FR-5: Bounded Self-Refinement (Self-Refine / Reflexion):** If validation fails, provide structured failure feedback back to the LLM for up to 2 correction retries (maximum 3 total generation attempts).
- **FR-6: Payload Priority in AgentExecutionLoop:**
  - Caller-supplied payloads take precedence.
  - Missing payloads trigger `EditSynthesizer`.
  - Unsafe cross-step fallback logic is completely removed.
- **FR-7: Plan-Bound Modification Scope:** Workspace modifications (`write_file`, `patch_file`, `delete_file`) must strictly target files listed in the approved plan. Modifications outside approved scope are rejected.
- **FR-8: Durable Workflow Execution:** Wrap the post-approval pipeline in a durable workflow (`ai/workflows/autonomous_task_workflow.py`) with stable workflow IDs, checkpointing, idempotency, and crash recovery.
- **FR-9: HTTP 202 Accepted Execution Initiation:** `POST /api/v1/tasks/{task_id}/run-workflow` (and async execute) returns `HTTP 202 Accepted` with `workflow_id` and `status_url`.
- **FR-10: Workflow Status & Progress Streaming:** Add `GET /api/v1/tasks/{task_id}/workflow-status` and stream workflow lifecycle events over Redis pubsub and SSE.

---

## 3. Non-Functional & Security Requirements

- **NFR-1 (Performance & Cost):** Limit synthesizer retries to 2. Send localized code context instead of whole repositories.
- **NFR-2 (Observability):** Audit every synthesis attempt with duration, model, patch fingerprint, and validation status.
- **NFR-3 (Idempotency):** Completed steps must not re-execute upon workflow retry or replay.
- **SR-1 (Preserve ADR-010):** No execution or synthesis occurs without an explicit human plan approval.
- **SR-2 (Path Traversal Defense):** All file paths must pass `validate_repo_relative_path` and `WorkspacePathGuard`.
- **SR-3 (Untrusted Model Output):** LLM outputs are treated as untrusted data and strictly validated prior to workspace application.
- **SR-4 (Secret Redaction):** All error messages, diffs, and logs must have high-entropy tokens and credentials redacted.

---

## 4. Scope Categorization

| Phase / Tier | Component | Priority | Status |
| :--- | :--- | :--- | :--- |
| **Phase 1** | `EditSynthesizer` service & prompt construction | **P0** | In Scope |
| **Phase 2** | Search/replace patch generation & validation pipeline | **P0** | In Scope |
| **Phase 3** | Bounded self-refinement (3 attempts max) | **P0** | In Scope |
| **Phase 4** | `AgentExecutionLoop` integration & payload fix | **P0** | In Scope |
| **Phase 5** | Plan-bound file scope enforcement | **P0** | In Scope |
| **Phase 6** | Durable workflow execution (DBOS / fallback) | **P1** | In Scope |
| **Phase 7** | HTTP 202 Accepted API & workflow status endpoint | **P1** | In Scope |
| **Phase 8** | Progress streaming (SSE) & frontend integration | **P1** | In Scope |
| **Phase 9** | Database models, audit logging & migrations | **P1** | In Scope |
| **Phase 10** | Comprehensive testing & documentation | **P0/P1** | In Scope |
| **Phase 11** | Candidate patch evaluation (Agentless pattern) | **P3** | Deferred to Future Work |
