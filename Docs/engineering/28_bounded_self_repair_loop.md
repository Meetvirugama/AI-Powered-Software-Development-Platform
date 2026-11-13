# Bounded Self-Repair Loop & Anti-Reward Hacking Architecture (Issue #205 / F24)

## 1. Executive Summary

This document specifies the technical architecture, fault localization, Reflexion verbal memory, and anti-reward hacking enforcement for **F24 — Bounded self-repair loop**, resolving **Issue #205**.

### Core Objectives & Deliverables
1. **Replacement of Placeholder Stubs with `LLMRepairSynthesizer`:**
   - Deprecate and remove the legacy hard-coded placeholder diff (`def handler(): pass -> return True`) from `BoundedRepairLoop._synthesize_patch`.
   - Implement `LLMRepairSynthesizer` reusing the existing `EditSynthesizer` service (F22) for structured SEARCH/REPLACE edits, syntax AST validation, and unified diff synthesis.
2. **Structured Diagnosis & Reflexion Memory:**
   - Ingest normalized test failure diagnostic context: failing test case name, parsed traceback, target `file:line`, error classification, and sanitized snippets.
   - Maintain verbal reinforcement history across retry attempts (**Reflexion P-19 & Self-Refine P-20**), passing lessons and failure feedback to prevent cyclic repeating mistakes.
3. **Anti-Reward Hacking Defense (P0):**
   - Classify all diagnosed failures into three distinct tiers: `infra` / `test-bug` / `code-bug`.
   - Strictly forbid modifying or "repairing" test files (`tests/**`, `test_*.py`, `*_test.py`, `*.spec.*`) to force a test pass during code repair cycles, unless the approved plan explicitly specifies test files in its scope (`allow_test_edits=True`).
4. **Hard 3-Attempt Budget Ceiling & Anti-Cycling Deduplication:**
   - Enforce the task-level budget ceiling of at most 3 repair attempts (`MAX_TASK_REPAIR_ATTEMPTS = 3`).
   - Block identical repeated patches using normalized SHA-256 content hashes (`compute_normalized_patch_hash`).
   - Abort immediately on infrastructure faults (`TIMEOUT`, `ENVIRONMENT_ERROR`, missing binaries, permission denied) without burning code repair attempts.

---

## 2. System Architecture & Control Flow

```mermaid
flowchart TD
    subgraph Test Execution & Diagnostic Intake
        TestRunner["WorkspaceTestRunner (pytest / jest)"]
        RawOutput["Stdout / Stderr Raw Output"]
        TracebackAnalyzer["FailureTracebackAnalyzer"]
        Diagnosis["TracebackDiagnosisResult"]
    end

    subgraph Failure Classification
        Classify["classify_diagnosis() / classify_failure()"]
        InfraGate{"Classification == 'infra'?"}
        HaltInfra["Halt Immediately (success=False, budget preserved)"]
    end

    subgraph Bounded Repair Loop (Max 3 Attempts)
        BudgetCheck{"attempt <= 3?"}
        Reflexion["Format Reflexion Memory (P-19)"]
        Synthesizer["LLMRepairSynthesizer (EditSynthesizer F22)"]
        PatchPayload["RepairPatchPayload (Unified Diff)"]
    end

    subgraph Validation Gates
        Validator["RepairPatchValidator"]
        Gate1["Gate 1: Budget Ceiling (<= 3)"]
        Gate2["Gate 7: Anti-Cycling Hash Deduplication"]
        Gate3["Gate 8: Anti-Reward Hacking (No Test Edits)"]
    end

    subgraph Workspace Execution
        Apply["Apply Patch to Workspace"]
        Retest["Re-run Test Suite"]
        OutcomePass["Tests PASSED (Repair Success)"]
        OutcomeFail["Tests FAILED (Re-diagnose & Increment Attempt)"]
        Exhausted["Budget Exhausted (Fails Closed)"]
    end

    TestRunner --> RawOutput
    RawOutput --> TracebackAnalyzer
    TracebackAnalyzer --> Diagnosis
    Diagnosis --> Classify
    Classify --> InfraGate

    InfraGate -- Yes --> HaltInfra
    InfraGate -- No --> BudgetCheck

    BudgetCheck -- Attempt > 3 --> Exhausted
    BudgetCheck -- Attempt <= 3 --> Reflexion
    Reflexion --> Synthesizer
    Synthesizer --> PatchPayload
    PatchPayload --> Validator

    Validator --> Gate1
    Gate1 --> Gate2
    Gate2 --> Gate3

    Gate3 -- Valid --> Apply
    Gate3 -- Invalid/Cheat --> OutcomeFail
    Apply --> Retest

    Retest -- Pass --> OutcomePass
    Retest -- Fail --> OutcomeFail
    OutcomeFail --> BudgetCheck
```

---

## 3. Sequence of Self-Repair Operations

```mermaid
sequenceDiagram
    autonumber
    participant Loop as BoundedRepairLoop
    participant Diag as FailureTracebackAnalyzer
    participant Synth as LLMRepairSynthesizer
    participant Edit as EditSynthesizer (F22)
    participant Valid as RepairPatchValidator
    participant WS as WorkspaceManager
    participant Run as WorkspaceTestRunner

    Loop->>Run: run_tests(initial)
    Run-->>Loop: WorkspaceTestExecutionResult (FAILED)
    Loop->>Diag: diagnose(raw_output)
    Diag-->>Loop: TracebackDiagnosisResult (category, file:line, classification)

    alt Infrastructure Failure
        Loop-->>Loop: Halt immediately (0 attempts used, budget preserved)
    else Repairable Failure
        loop Attempt 1 to 3
            Loop->>Synth: synthesize_repair(diagnosis, repair_history, allowed_files)
            Synth->>Synth: identify_target_file_and_line() [AgentFL]
            Synth->>Synth: format_reflexion_memory() [Reflexion P-19]
            Synth->>Edit: generate SEARCH/REPLACE edits & validate AST syntax
            Edit-->>Synth: EditBlocks validated
            Synth->>Synth: generate_unified_diff(difflib)
            Synth-->>Loop: RepairPatchPayload (diff, target_files, previous_hashes)

            Loop->>Valid: validate_patch(payload, allowed_files, allow_test_edits)
            alt Anti-Reward Hacking Violation (Modifying test files)
                Valid-->>Loop: PatchValidationResult (is_valid=False, VIOLATION)
                Loop->>Loop: Record rejected attempt to Reflexion memory
            else Patch Valid
                Valid-->>Loop: PatchValidationResult (is_valid=True)
                Loop->>WS: apply_patch_files(patch_payload)
                Loop->>Run: run_tests(retest)
                alt Retest Passed
                    Run-->>Loop: status = PASSED
                    Loop-->>Loop: Return BoundedRepairOutcome(success=True)
                else Retest Failed
                    Run-->>Loop: status = FAILED
                    Loop->>Diag: diagnose(retest_output)
                end
            end
        end
    end
```

---

## 4. Key Architectural Mechanisms

### 4.1 Reflexion Verbal Reinforcement Memory (P-19 & P-20)
Autonomous recovery requires that the repair synthesizer does not repeat the exact same failed edits. `LLMRepairSynthesizer.format_reflexion_memory` formats structured attempt records into verbal reflections:
```text
### REFLEXION MEMORY (PREVIOUS FAILED REPAIR ATTEMPTS):
The following repair attempts were executed earlier in this session and FAILED:
- Attempt 1:
  * Patch Summary: Added null check to billing.py
  * Patch Hash: 7b3d4f128e0a4c21
  * Test Status Before: FAILED -> Test Status After: FAILED
  * Reflection: This candidate fix did NOT resolve the test failure or was rejected.
    Take an alternative approach; do NOT generate the same changes.
```

### 4.2 Spectrum-Based Fault Localization (AgentFL / AutoCodeRover)
When a test fails, `pytest` summaries report the test location (e.g. `tests/test_calc.py::test_add`). Blindly targeting `tests/test_calc.py` would cause the synthesizer to edit the test rather than the production code.
`LLMRepairSynthesizer.identify_target_file_and_line` resolves root-cause locations:
1. Priority 1: Non-test files in approved plan scope (`allowed_files`).
2. Priority 2: Deepest application stack frame in the traceback (`extract_application_frames_from_traceback`) pointing to workspace code.
3. Priority 3: Non-test candidate heuristics derived from the test name (e.g., `tests/test_calc.py` -> `src/calc.py`).

### 4.3 Anti-Reward Hacking Gate (Rule Gate 8)
A critical failure mode of automated coding agents is **reward hacking**: deleting tests, relaxing assertions (e.g., `assert 1 == 1`), or commenting out test cases to make the test suite pass without fixing the defect.
- `RepairPatchValidator.validate_patch` enforces Gate 8:
  ```python
  if not allow_test_edits:
      for f in [*validated_files, *validated_targets]:
          if is_test_file(f) and f not in allowed_test_files:
              violations.append(
                  f"Anti-reward hacking violation: Modifying test file '{f}' is forbidden during repair unless explicitly permitted in plan scope."
              )
  ```
- If an agent generates a patch modifying any test file without explicit plan approval, the patch is rejected immediately, recorded in Reflexion memory, and forbidden from workspace application.

### 4.4 Failure Classification Tiers
Failures are classified into three distinct categories:
- `infra`: Timeouts, command not found, missing binaries, permission denied, out of memory. Halts the loop immediately without consuming the 3-attempt code repair budget.
- `test-bug`: The defect exists solely in test code (e.g. invalid test assertion without calling app code, fixture error). Test modifications are permitted only if explicitly in plan scope.
- `code-bug`: The defect originates in application source code. Repair edits must modify the application code under test.

---

## 5. Telemetry & Verification Matrix

| Component | Responsibility | Test File | Status |
| :--- | :--- | :--- | :--- |
| `LLMRepairSynthesizer` | Targeted patch synthesis via `EditSynthesizer` | `test_bounded_repair_loop_f24.py` | Verified (14/14) |
| `Reflexion Memory` | History accumulation & verbal lessons | `test_bounded_repair_loop_f24.py` | Verified |
| `Anti-Reward Hacking` | Test modification prevention | `test_bounded_repair_loop_f24.py` | Verified |
| `Anti-Cycling` | SHA-256 hash deduplication | `test_dev_w3_day4_repair.py` | Verified (19/19) |
| `Budget Ceiling` | Hard ceiling of 3 attempts | `test_meet_w3_all_days.py` | Verified (38/38) |
| `Full Workflow` | E2E test-repair-retest cycle | `test_om_w3_d3_d4_execution_persistence.py` | Verified (19/19) |
