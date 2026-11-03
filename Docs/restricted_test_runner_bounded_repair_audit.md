# Restricted Test Runner, Failure Classification & Bounded Repair Loop Audit Report

> **Author:** Prit Zania (Repository Engine & Workspace Lead)  
> **Date:** 2026-10-29  
> **Target Milestone:** Week 3 — Day 4 (`Docs/week3.md` §6 F35, §8 Day 4, `Docs/daily_tasks.md` line 638)  
> **Status:** ✅ COMPLETED & VERIFIED (18/18 Day 4 Acceptance Tests Passed, 107/107 Week 3 Sandbox Tests Passed)  
> **Relevant Specifications:** `Docs/week3.md` §6 (F35), §8 (Day 4), §11 (Scenario D); ADR-007; ADR-010

---

## 1. Executive Summary

In Week 3 Day 4, the repository engine was extended with the **Restricted Test Runner**, **Structured Output Parser**, **Failure Classifier**, and **Bounded Auto-Repair Budget Enforcer** (`WorkspaceTestRunner`), integrated seamlessly with `WorkspaceManager` and Devu's `ToolRouter` / `PolicyEngine`.

Per **ADR-010** (Mandatory Human Approval Gate & Bounded Repair Loop), **Docs/week3.md §6 (F35)**, and **Docs/week3.md §11 (Scenario D)**, automated agent self-repair must never loop indefinitely. The agent is permitted at most **3 task-level repair attempts**. If tests still fail after the 3rd attempt, the repair budget is exhausted, a `REPAIR_BUDGET_EXHAUSTED` execution event is emitted to the timeline, and human developer intervention is alerted. Furthermore, duplicate patch proposals matching previously failed repair signatures are immediately rejected with `WorkspaceDuplicateRepairPatchError`.

All test executions run strictly inside the task's isolated sandbox directory (`cwd=workspace_path`), strictly bounded by command allowlists (disallowing `npm install`, `pip install`, and shell metacharacters), strict timeouts (default 60s, max 300s), output log capping (100 KB max), and automated secret redaction.

---

## 2. Key Capabilities & Technical Specifications

### 2.1 Framework Detection & Command Synthesis
The test runner detects or accepts explicit test framework configurations:
- **Pytest:** Detects `pytest.ini`, `pyproject.toml`, or `tests/` directory -> synthesizes `pytest -v`.
- **Python Unittest:** Detects `test_*.py` pattern or explicit declaration -> synthesizes `python -m unittest -v`.
- **Jest / NPM:** Detects `package.json` -> synthesizes `npm test --`.
- **Unsupported Frameworks:** Gracefully identifies frameworks outside the current runtime support matrix (`vitest`, `go test`, `cargo test`) and returns `TestOutcomeStatus.UNSUPPORTED_FRAMEWORK` with `is_repair_eligible=False` without crashing.
- **No Config Found:** When no recognizable test configuration exists, returns `TestOutcomeStatus.NO_TESTS_FOUND` cleanly.

### 2.2 Security & Isolation Policies
1. **Command Allowlist:** Only `pytest`, `python`, `python3`, `npm`, `npx`, and `node` are authorized test runner executables.
2. **Dependency Install Prevention (F35):** Disallows arbitrary package installations inside the test runner (`npm install`, `npm add`, `pip install`). Violations raise `WorkspacePolicyViolationError`.
3. **Shell Metacharacter Blocking:** Disallows command chaining operators (`;`, `&&`, `||`, `|`, `&`), redirection (`>`, `<`), and null bytes (`\x00`).
4. **Path Traversal Containment:** Target test paths are validated against `WorkspacePathGuard.resolve_within_workspace()`. Path escapes raise `WorkspacePathEscapeError`.
5. **Output Bounding & Secret Redaction:** Test stdout and stderr are capped at 100 KB (`MAX_COMMAND_OUTPUT_BYTES`). Outputs exceeding the ceiling are truncated with clear notice and automatically scanned by `redact()` to sanitize tokens and API keys.

### 2.3 Failure Classification & Repair Eligibility Matrix

Test outcomes are classified into four mutually exclusive failure classes to determine whether the agent may invoke an automated self-repair loop:

| Outcome Status | Classification | Repair Eligible? | Criteria & Description |
|---|---|---|---|
| `PASSED` | `NONE` | ❌ No | Exit code 0, all tests passed. |
| `FAILED` | `TEST_FAILURE` | ✅ **Yes** | Exit code 1, assertion errors, failing test cases. Agent is permitted a bounded repair attempt. |
| `ERROR` | `INFRASTRUCTURE_ERROR` | ❌ No | Missing modules, syntax errors, runner crashes, unhandled exceptions outside test cases. |
| `TIMEOUT` | `TIMEOUT` | ❌ No | Execution exceeded timeout budget (default 60s, max 300s). Process terminated. |
| `ERROR` | `SECURITY_VIOLATION` | ❌ No | Attempted path traversal, shell injection, or prohibited install command. |
| `UNSUPPORTED_FRAMEWORK` | `INFRASTRUCTURE_ERROR` | ❌ No | Framework unsupported by workspace environment. |
| `NO_TESTS_FOUND` | `INFRASTRUCTURE_ERROR` | ❌ No | No tests discovered or collected (pytest exit code 5). |

### 2.4 Bounded Auto-Repair Budget Enforcement (ADR-010, Scenario D)

To eliminate runaway agent costs and infinite loops:
1. **Task-Level Budget Ceiling:** Each task is allocated exactly **3 repair attempts** (`MAX_REPAIR_ATTEMPTS = 3`).
2. **Attempt Recording:** Each repair attempt is recorded via `record_repair_attempt(task_id, patch_summary, patch_content, success, revision_id)`.
3. **Budget Exhaustion:** Attempting a 4th repair raises `WorkspaceRepairBudgetExhaustedError` and emits `WorkspaceExecutionEventType.REPAIR_BUDGET_EXHAUSTED` to the workspace timeline.
4. **Duplicate Patch Detection:** SHA-256 hash signatures of applied patch content are tracked per task. Proposing an identical failed patch raises `WorkspaceDuplicateRepairPatchError`.

---

## 3. Schemas & Data Contracts

### 3.1 Pydantic Models in `backend/app/schemas/workspace.py`
- `TestOutcomeStatus`: Enum (`PASSED`, `FAILED`, `ERROR`, `TIMEOUT`, `UNSUPPORTED_FRAMEWORK`, `AMBIGUOUS`, `NO_TESTS_FOUND`).
- `TestFailureClassification`: Enum (`NONE`, `TEST_FAILURE`, `INFRASTRUCTURE_ERROR`, `TIMEOUT`, `SECURITY_VIOLATION`).
- `WorkspaceTestExecutionRequest`: Task ID, explicit framework, optional test path, additional CLI args, timeout, environment overrides.
- `WorkspaceTestExecutionResult`: Full execution result with counts (`passed_count`, `failed_count`, `skipped_count`, `error_count`, `total_count`), `failed_test_names`, `failure_details`, duration, stdout/stderr, outcome status, classification, and `is_repair_eligible` flag.
- `RepairAttemptRecord`: Record of attempt number (1-indexed), timestamp, patch summary, patch SHA-256 hash, success flag, and workspace revision.
- `WorkspaceRepairBudgetStatus`: Live status with `max_repair_attempts`, `repair_attempts_used`, `remaining_repair_attempts`, and boolean `is_budget_exhausted`.

### 3.2 Timeline Events
Added to `WorkspaceExecutionEventType`:
- `TESTS_STARTED`: Test execution triggered.
- `TESTS_PASSED`: All tests passed.
- `TESTS_FAILED`: Test failures detected.
- `TEST_INFRASTRUCTURE_FAILURE`: Non-test crash or configuration failure.
- `TEST_TIMEOUT`: Test execution exceeded timeout.
- `REPAIR_ATTEMPT_STARTED`: Agent commenced self-repair attempt.
- `REPAIR_ATTEMPT_COMPLETED`: Repair attempt finished and recorded.
- `REPAIR_BUDGET_EXHAUSTED`: 3-attempt ceiling reached, requiring human intervention.

---

## 4. ToolRouter & Policy Bridge Integration

In `backend/sandbox/tool_policy_bridge.py`:
- Registered `TOOL_RUN_TESTS` (`run_tests`): Executes workspace test suite with full policy validation.
- Registered `TOOL_RECORD_REPAIR` (`record_repair_attempt`): Records self-repair attempts and enforces budget ceilings.

Both tools require an active `IN_USE` workspace state and enforce strict parameter schemas through `WorkspaceToolPolicyBridge`.

---

## 5. Verification & Acceptance Testing

The Day 4 test suite in `backend/tests/test_prit_w3_d4_restricted_test_runner.py` verifies all deliverables:

1. `test_framework_detection_pytest_and_explicit`: Tests pytest autodetection and explicit framework overrides (unittest, jest).
2. `test_unsupported_framework_reported_explicitly`: Verifies `vitest` returns `UNSUPPORTED_FRAMEWORK` cleanly.
3. `test_no_config_found_reporting`: Verifies empty directory returns `NO_TESTS_FOUND`.
4. `test_command_allowlist_and_install_prevention`: Verifies rejection of non-allowlisted commands and `npm install` / `pip install`.
5. `test_disallowed_shell_tokens_and_path_traversal`: Verifies blocking of `;`, `&&`, and `../` traversal.
6. `test_output_parsing_pytest_success`: Verifies extraction of 5 passed tests in 0.35s.
7. `test_output_parsing_pytest_failure_and_repair_eligibility`: Verifies 1 failed, 3 passed parsing, failing name extraction, and `is_repair_eligible=True`.
8. `test_output_parsing_jest_format`: Verifies Jest test summary parsing.
9. `test_infrastructure_failure_classification`: Verifies `ModuleNotFoundError` is classified as `INFRASTRUCTURE_ERROR` (`is_repair_eligible=False`).
10. `test_timeout_classification`: Verifies execution timeout classification (`is_repair_eligible=False`).
11. `test_test_output_truncation_and_secret_redaction`: Verifies 100 KB output truncation and `[REDACTED]` secret masking.
12. `test_bounded_repair_attempts_tracking_and_max_ceiling`: Verifies attempts 1-3 tracking and 4th attempt rejection with `WorkspaceRepairBudgetExhaustedError`.
13. `test_duplicate_failed_patch_rejected`: Verifies duplicate patch hash rejection with `WorkspaceDuplicateRepairPatchError`.
14. `test_workspace_manager_run_tests_integration`: Verifies end-to-end `WorkspaceManager.run_tests()` and timeline event emission.
15. `test_workspace_manager_record_repair_attempt_exhaustion`: Verifies `REPAIR_BUDGET_EXHAUSTED` timeline event emission.
16. `test_unapproved_workspace_blocks_test_execution`: Verifies tests cannot run in unapproved `READY` state.
17. `test_tool_router_run_tests_dispatch`: Verifies `run_tests` dispatch through `ToolRouter` with `policy_engine`.
18. `test_tool_router_record_repair_dispatch`: Verifies `record_repair_attempt` dispatch through `ToolRouter`.

### Test Results
```
backend/tests/test_prit_w3_d4_restricted_test_runner.py::test_framework_detection_pytest_and_explicit PASSED
backend/tests/test_prit_w3_d4_restricted_test_runner.py::test_unsupported_framework_reported_explicitly PASSED
backend/tests/test_prit_w3_d4_restricted_test_runner.py::test_no_config_found_reporting PASSED
backend/tests/test_prit_w3_d4_restricted_test_runner.py::test_command_allowlist_and_install_prevention PASSED
backend/tests/test_prit_w3_d4_restricted_test_runner.py::test_disallowed_shell_tokens_and_path_traversal PASSED
backend/tests/test_prit_w3_d4_restricted_test_runner.py::test_output_parsing_pytest_success PASSED
backend/tests/test_prit_w3_d4_restricted_test_runner.py::test_output_parsing_pytest_failure_and_repair_eligibility PASSED
backend/tests/test_prit_w3_d4_restricted_test_runner.py::test_output_parsing_jest_format PASSED
backend/tests/test_prit_w3_d4_restricted_test_runner.py::test_infrastructure_failure_classification PASSED
backend/tests/test_prit_w3_d4_restricted_test_runner.py::test_timeout_classification PASSED
backend/tests/test_prit_w3_d4_restricted_test_runner.py::test_test_output_truncation_and_secret_redaction PASSED
backend/tests/test_prit_w3_d4_restricted_test_runner.py::test_bounded_repair_attempts_tracking_and_max_ceiling PASSED
backend/tests/test_prit_w3_d4_restricted_test_runner.py::test_duplicate_failed_patch_rejected PASSED
backend/tests/test_prit_w3_d4_restricted_test_runner.py::test_workspace_manager_run_tests_integration PASSED
backend/tests/test_prit_w3_d4_restricted_test_runner.py::test_workspace_manager_record_repair_attempt_exhaustion PASSED
backend/tests/test_prit_w3_d4_restricted_test_runner.py::test_unapproved_workspace_blocks_test_execution PASSED
backend/tests/test_prit_w3_d4_restricted_test_runner.py::test_tool_router_run_tests_dispatch PASSED
backend/tests/test_prit_w3_d4_restricted_test_runner.py::test_tool_router_record_repair_dispatch PASSED
======================= 18 passed in 0.25s =======================

Cumulative Prit Week 3 Test Suite (Day 1 - Day 4):
======================= 107 passed in 1.20s =======================
```

---

## 6. Downstream Team Interfaces

- **Meet (Agent Execution & Self-Repair Loop):** Uses `WorkspaceTestRunner.run_tests()` and `get_repair_budget_status()` to drive the bounded repair loop.
- **Dev (Traceback Diagnosis):** Uses `WorkspaceTestExecutionResult.failed_test_names` and `failure_details` to formulate targeted AST-level patches.
- **Yug (Execution & Repair APIs):** Surfaces test outcomes, failure classifications, and remaining repair attempts to client endpoints.
- **Dhramraj (Workbench & Timeline UI):** Listens to `TESTS_STARTED`, `TESTS_PASSED`, `TESTS_FAILED`, `REPAIR_ATTEMPT_COMPLETED`, and `REPAIR_BUDGET_EXHAUSTED` timeline events to display live execution counters and human alert modals.
- **Keval (Acceptance & Integration Tests):** Integrates end-to-end scenarios validating repair success vs 3-attempt ceiling exhaustion.
