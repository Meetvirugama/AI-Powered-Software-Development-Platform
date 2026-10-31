# Week 3 Day 3 — Workspace Execution Start, Tool Policy Bridge & Sandbox Security Audit Report

**Owner:** Prit Zania (Repository Engine & Workspace Lead)  
**Collaborators:** Devu (Tool Router), Sukun (Security Architecture), Yug (API Orchestration), Parth (Git Branch)  
**Milestone:** Week 3 — Workflow Automation, GitHub Ecosystem & Production Hardening  
**Task:** W3-Day3 — WorkspaceManager Execution Start, Tool Policy Bridge, Sandboxed Command Runner & Execution Timeline  
**Status:** 🟢 Complete & Fully Verified (16/16 New Tests Passing — 91/91 Week 3 Tests Passing — 100% Pass Rate)  
**Date:** Week 3 Day 3  
**Branch:** `feat/prit-week3-day3-workspace-execution`  

---

## 1. Executive Summary

During Week 3 Day 3, Prit Zania executed the mandatory **Workspace Execution Start & Tool Policy Integration** deliverables specified in [`Docs/week3.md`](week3.md) (§5, §6 F33 & F34, §8 Day 3, §9, §11 Scenarios A–C) and [`Docs/daily_tasks.md`](daily_tasks.md):

1. **Mandatory Approval Gate & Execution Start:** Implemented `WorkspaceManager.start_execution()` enforcing server-side approval verification per ADR-010. Any attempt by unapproved tasks (`PENDING_APPROVAL`, `REJECTED`, `CREATED`, `CANCELLED`) to enter an isolated workspace is blocked with `WorkspaceAuthorizationError`. Stale approvals where base revision shifted since plan generation are detected and invalidated with `WorkspaceStaleApprovalError` (Docs/week3.md §11 Scenarios B & C).
2. **Controlled Execution Lifecycle:** Implemented pause (`IN_USE -> STOPPED`), resume (`STOPPED -> IN_USE`), graceful stop, and failure handling (`FAILED`), preserving diagnostics and state without deleting user files or active task evidence.
3. **Restricted Sandboxed Command Runner:** Created `WorkspaceCommandRunner` enforcing an explicit allowlist of permitted commands (`ALLOWED_COMMAND_TEMPLATES`: `git`, `python`, `python3`, `pytest`, `npm`, `npx`, `node`, `ls`, `dir`, `cat`, `echo`). Rejects shell injections, logical operators, and metacharacters (`;`, `&&`, `||`, `|`, `` ` ``, `$`, `\n`, `\r`, null bytes). Enforces execution timeouts and output-size limits (100 KB max capture) with secret scrubbing.
4. **Environment Isolation & Secret Purging:** Purges sensitive credentials and host tokens (`GITHUB_TOKEN`, `AWS_SECRET_ACCESS_KEY`, `DATABASE_URL`, `POSTGRES_PASSWORD`, `SECRET_KEY`, `JWT_SECRET`, AI keys) before subprocess spawning, preventing sandbox escape or credential exposure.
5. **Tool Policy Bridge & Router Integration:** Built `WorkspaceToolPolicyBridge` and `register_workspace_tools()` connecting Devu's `ToolRouter` ([`backend/agent/tools/router.py`](../backend/agent/tools/router.py)) to `WorkspaceManager`. Registers 6 canonical workspace tools (`read_file`, `write_file`, `patch_file`, `delete_file`, `list_files`, `execute_command`) with strict JSON parameter schemas, `WorkspacePathGuard` boundary confinement, and fail-closed policy enforcement.
6. **Execution Timeline & Observability:** Implemented `WorkspaceExecutionEvent` timeline tracking every lifecycle transition (`WORKSPACE_CREATED`, `BRANCH_SETUP`, `EXECUTION_STARTED`, `TOOL_INVOCATION`, `EXECUTION_PAUSED`, `EXECUTION_RESUMED`, `EXECUTION_STOPPED`, `EXECUTION_FAILED`, `CLEANUP_COMPLETED`), supporting Dhramraj's live progress dashboard and Yug's timeline APIs.
7. **Canonical Pydantic Schemas:** Exported all Day 3 schemas (`WorkspaceExecutionEvent`, `WorkspaceExecutionEventType`, `WorkspaceStartExecutionRequest`, `WorkspaceStartExecutionResult`, `WorkspaceCommandRequest`, `WorkspaceCommandResult`, `WorkspaceToolPolicyRequest`, `WorkspaceToolPolicyResult`) from [`backend/app/schemas/workspace.py`](../backend/app/schemas/workspace.py) and [`app.schemas`](../backend/app/schemas/__init__.py).
8. **Automated Verification:** Created [`backend/tests/test_prit_w3_d3_workspace_execution.py`](../backend/tests/test_prit_w3_d3_workspace_execution.py) with 16 comprehensive tests passing synchronously with 100% success rate, bringing total Week 3 passing tests to 91.

---

## 2. Architectural Pipeline & Inter-Team Integration

The Week 3 Day 3 implementation establishes the operational boundary where an approved plan transitions into actual workspace execution:

```text
┌─────────────────────────────────────────┐
│  Meet / Yug / Dhramraj (Day 2)          │
│  Human Approval Gate (ADR-010)          │
└────────────────────┬────────────────────┘
                     │ WorkspaceStartExecutionRequest (status="APPROVED", base_sha)
                     ▼
┌─────────────────────────────────────────────────────────────────────────┐
│  Prit: WorkspaceManager Execution Gate (backend/sandbox/workspace_manager.py)
│                                                                         │
│  1. Check task_status == "APPROVED" (reject if unapproved)             │
│  2. Validate base revision == approved revision (reject if stale)       │
│  3. Transition workspace: READY -> IN_USE                              │
│  4. Emit timeline event: EXECUTION_STARTED                             │
└────────────────────┬────────────────────────────────────────────────────┘
                     │ Workspace in IN_USE state
                     ▼
┌─────────────────────────────────────────────────────────────────────────┐
│  Devu: ToolRouter (backend/agent/tools/router.py)                       │
│  Prit: WorkspaceToolPolicyBridge (backend/sandbox/tool_policy_bridge.py) │
│                                                                         │
│  1. Validate tool name against registered CANONICAL_WORKSPACE_TOOLS     │
│  2. Verify workspace status == IN_USE                                   │
│  3. Parameter schema validation & WorkspacePathGuard boundary check     │
│  4. Command allowlist validation (ALLOWED_COMMAND_TEMPLATES)            │
└────────────────────┬────────────────────────────────────────────────────┘
                     │ Permitted & Sanitized Tool Invocation
         ┌───────────┴──────────────────────────────┐
         ▼                                          ▼
┌───────────────────────────────────┐  ┌───────────────────────────────────┐
│ File Operations (Prit)            │  │ Sandboxed Command Runner (Prit)   │
│ - read_file (size cap checked)    │  │ - WorkspaceCommandRunner          │
│ - write_file (disk quota checked) │  │ - Strip sensitive host env vars   │
│ - patch_file (atomic replace)     │  │ - Cwd = .workspaces/task-<id>     │
│ - delete_file / list_files        │  │ - Timeout & 100KB output bounds   │
└─────────────────┬─────────────────┘  └─────────────────┬─────────────────┘
                  │                                      │
                  └──────────────────┬───────────────────┘
                                     │
                                     ▼
┌─────────────────────────────────────────────────────────────────────────┐
│  Prit: Execution Timeline & Event Bus                                  │
│  - WorkspaceExecutionEvent logged in chronological order                │
│  - Secret scrubbing applied on all output payloads                      │
│  - Ready for Yug's GET /tasks/{id}/events & Dhramraj's Progress UI      │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## 3. Human Approval Gate & Anti-Bypass Enforcement

### 3.1 Strict Approval Invariant (Docs/week3.md §8 Day 3, ADR-010)

No task is permitted to enter `IN_USE` or execute tools without server-verified approval:
- If `task_status` is not `"APPROVED"` (e.g. `PENDING_APPROVAL`, `REJECTED`, `CREATED`, `CANCELLED`), `start_execution()` rejects the request immediately with `WorkspaceAuthorizationError`.
- Neither the LLM nor direct API requests can modify workspace files before this check passes.

### 3.2 Stale Approval Detection (Docs/week3.md §11 Scenario C)

If the repository's base revision shifts or a plan is revised after human approval:
$$\text{request.approved\_base\_revision} \ne \text{workspace.base\_revision}$$
The system rejects execution with `WorkspaceStaleApprovalError`. The workspace remains in `READY` state, forcing the orchestrator to re-plan and obtain fresh human approval.

---

## 4. Sandboxed Command Runner & Threat Surface Mitigation

### 4.1 Command Allowlist Policy

Arbitrary shell execution is forbidden. Only explicit pre-approved CLI executables are permitted:
- `git`: Branch, status, worktree, and diff operations.
- `python`, `python3`: Interpreter invocation.
- `pytest`: Python test execution.
- `npm`, `npx`, `node`: JavaScript/TypeScript dependency and test execution.
- `ls`, `dir`, `cat`, `echo`: Bounded inspect utilities.

### 4.2 Shell Injection Prevention

All invocations use argument arrays (`[command, *arguments]`) without `shell=True`. Furthermore, both executable names and argument strings are scanned for dangerous shell metacharacters:
`";"`, `"&&"`, `"||"`, `"|"`, `` "`" ``, `"$"`, `">"`, `"<"`, `"\n"`, `"\r"`, and `\x00`.
Any matching token triggers an immediate `WorkspacePolicyViolationError`.

### 4.3 Environment Sanitization

To prevent accidental leakage of platform credentials to untrusted task processes:
- `SENSITIVE_ENV_VARS` (`GITHUB_TOKEN`, `GH_TOKEN`, `AWS_SECRET_ACCESS_KEY`, `DATABASE_URL`, `POSTGRES_PASSWORD`, `SECRET_KEY`, `JWT_SECRET`, AI API keys) are purged.
- Any variable key containing substrings `SECRET`, `TOKEN`, `PASSWORD`, `PRIVATE_KEY`, or `CREDENTIAL` is purged.
- Subprocesses run strictly in `cwd=workspace_path`.

### 4.4 Resource & Output Bounds

- **Execution Timeout:** Enforced via `subprocess.run(timeout=...)`, capped at `MAX_TIMEOUT_SECONDS` (300s). On timeout, returns structured `WorkspaceCommandResult(timed_out=True, exit_code=-1)`.
- **Output Truncation:** Captured stdout and stderr are capped at `MAX_COMMAND_OUTPUT_BYTES` (100 KB) with explicit truncation notices.
- **Redaction:** `redact()` scrubs any leaked access keys or secrets from stdout and stderr.

---

## 5. Tool Policy Bridge & Agent Tool Registration

### 5.1 Canonical Tool Schemas

`WorkspaceToolPolicyBridge` registers 6 tools with Devu's `ToolRouter`:

| Tool Name | Parameters | Validation / Safety Guard |
|---|---|---|
| `read_file` | `file_path: str` | `WorkspacePathGuard`, file size quota check |
| `write_file` | `file_path: str`, `content: str`, `create_parents: bool` | `WorkspacePathGuard`, disk quota, modified file limit |
| `patch_file` | `file_path: str`, `target_content: str`, `replacement_content: str` | Exact match verification, atomic write |
| `delete_file` | `file_path: str` | `WorkspacePathGuard`, workspace confinement |
| `list_files` | `subpath: str` | Excludes `.git`, `__pycache__`, `venv` |
| `execute_command` | `command: str`, `arguments: list[str]`, `timeout_seconds: int` | Allowlist enforcement, shell token rejection, timeout cap |

### 5.2 Status-Guarded Invocation

All tool handlers verify that the workspace is currently in `WorkspaceStatus.IN_USE`. If an agent attempts to call a tool while the workspace is `NOT_CREATED`, `READY`, `STOPPED`, `FAILED`, or `CLEANUP_PENDING`, the policy bridge denies the request with a descriptive error.

---

## 6. Verification & Test Suite Matrix

The Day 3 test suite [`backend/tests/test_prit_w3_d3_workspace_execution.py`](../backend/tests/test_prit_w3_d3_workspace_execution.py) contains 16 automated tests passing synchronously with 100% success rate:

| Test Case | Capability Under Test | Result |
|---|---|---|
| `test_workspace_provisioning_metadata` | Metadata retention, base revision, branch name, initial timeline | 🟢 Pass |
| `test_unapproved_task_cannot_start_execution` | Anti-bypass check for `PENDING_APPROVAL` and `REJECTED` tasks | 🟢 Pass |
| `test_approved_task_enters_in_use_state` | Approved task transitions `READY -> IN_USE`, records start time | 🟢 Pass |
| `test_stale_approval_revision_mismatch_blocks_execution` | Stale approval invalidation when base revision shifts | 🟢 Pass |
| `test_execution_pause_and_resume_cycle` | Pause (`IN_USE -> STOPPED`) and resume (`STOPPED -> IN_USE`) | 🟢 Pass |
| `test_execution_stop_and_fail` | Graceful stop and failure diagnostics recording | 🟢 Pass |
| `test_sandboxed_command_execution_success` | Allowlisted command execution (`python -V`), output capture | 🟢 Pass |
| `test_command_blocked_when_workspace_not_in_use` | Command blocked when workspace is not in `IN_USE` state | 🟢 Pass |
| `test_disallowed_command_rejected_by_policy` | Rejection of non-allowlisted commands (`curl`) | 🟢 Pass |
| `test_shell_injection_tokens_rejected` | Rejection of shell operators (`;`, `&&`, `\|`) | 🟢 Pass |
| `test_command_environment_strips_sensitive_keys` | Host credential purging from subprocess environment | 🟢 Pass |
| `test_tool_router_registration_and_policy_dispatch` | Registration with `ToolRouter` and execution of read/write/list | 🟢 Pass |
| `test_tool_policy_blocks_path_traversal` | Blocking directory climbing (`../`), UNC paths, and system files | 🟢 Pass |
| `test_tool_policy_blocks_unapproved_or_paused_workspace` | Blocking tool calls on unapproved or stopped workspaces | 🟢 Pass |
| `test_safe_file_patching_and_deletion` | Exact string replacement patch and guarded deletion | 🟢 Pass |
| `test_concurrent_tasks_isolated_working_directories` | Concurrency isolation across multiple tasks | 🟢 Pass |

### Total Test Suite Health (Week 3 Prit Components)

```text
======================== 91 passed, 1 warning in 3.38s ========================
- backend/tests/test_prit_w3_d1_workspace.py                    (38 passed)
- backend/tests/test_prit_w3_d2_blast_radius_and_test_planner.py (35 passed)
- backend/tests/test_prit_w3_d3_workspace_execution.py           (16 passed)
- backend/tests/test_tool_router.py                             (2 passed)
```

---

## 7. Definition of Done Sign-Off (Docs/week3.md §10)

- [x] **Functional Correctness:** Approved tasks enter isolated workspaces and execute allowlisted commands; unapproved tasks and unsafe tool operations are blocked.
- [x] **Data Integrity:** Base revision, branch name, execution state, and chronological timeline events are preserved.
- [x] **Inter-Team Integration:** Prit & Devu tool policy interfaces connected; Yug & Dhramraj execution start/timeline contracts fulfilled.
- [x] **Security Hardening:** Host credentials stripped, path traversal prevented, shell injection tokens rejected, output secrets redacted.
- [x] **Acceptance Scenarios:** Scenario A (isolated workspace creation), Scenario B (unapproved execution blocked), and Scenario C (stale approval invalidation) fully verified.
- [x] **Documentation & Changelog:** Architecture report published, `Docs/daily_tasks.md`, `10_development_tasks.md`, and `14_changelog.md` updated.
