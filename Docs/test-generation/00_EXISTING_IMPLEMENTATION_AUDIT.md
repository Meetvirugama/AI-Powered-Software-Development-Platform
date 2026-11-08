# 00. Existing Implementation Audit & Gap Analysis

> **Date:** 2026-11-08  
> **Feature:** F13 — Framework-Aware Test Generation & Verification  
> **Status:** Phase 0 Baseline Audit Complete  
> **Reference:** `task.md §3`, Issue #193  

---

## 1. Existing Architecture Overview

The platform's current Test Generation subsystem was created during Week 2 (`Docs/week2.md §8`) to provide framework-aware test file synthesis via LLM.

Currently, the pipeline operates as a **single-shot, generation-and-static-validation engine**:
```
User Request (Target File/Symbol)
  ├── 1. Database-backed Target Resolution (files, code chunks, AST symbols)
  ├── 2. Framework & Convention Detection (manifests in DB chunks)
  ├── 3. Test Context Assembly (TestContextBuilder + fixtures + examples)
  ├── 4. LLM Generation (Gemini / Groq with JSON repair loop)
  ├── 5. Static Validation (ast.parse for Python, delimiter/keyword regex for JS)
  ├── 6. Security Sanitization (secret redaction, path traversal checks)
  └── 7. Persistence & Response (AnalysisRun recorded in PostgreSQL)
```

Generated tests are returned to the user as pure text code without ever being executed in an isolated runtime.

---

## 2. Existing File Responsibilities

| File Path | Component | Responsibility | Current Classification |
|---|---|---|---|
| `backend/app/services/test_generation_orchestrator.py` | Orchestration | Coordinates DB retrieval, framework detection, context assembly, static validation, secret redaction, and persistence. | **PARTIALLY IMPLEMENTED** (Never executes generated tests; blocks Vitest at L264). |
| `backend/ai/services/test_generation_service.py` | AI Generation Service | Formulates LLM prompts with boundary fences (`<<<REPO_DATA_...>>>`), parses JSON, validates AST syntax, triggers repair loop. | **PARTIALLY IMPLEMENTED** (Single-shot only; no iteration or coverage feedback). |
| `backend/scanner/framework_detector.py` | Scanner / Detector | Inspects repository files for test runners. Declares `pytest`, `unittest`, `jest`, `vitest`. | **FULLY IMPLEMENTED BUT MISMATCHED** (`vitest` declared in detector but rejected in orchestrator & schemas). |
| `backend/app/schemas/analysis.py` | Pydantic Schemas | Data contracts for test requests, responses, quality scorecards, requirements. | **IMPLEMENTED BUT RESTRICTIVE** (`SupportedTestFramework` lacks `"vitest"`; lacks execution/stability/coverage fields). |
| `backend/sandbox/workspace_manager.py` | Sandbox Workspaces | Disposable workspace provisioning (`.workspaces/task-<id>`), Git worktree isolation, file read/write/patch guards. | **FULLY IMPLEMENTED** (Week 3 production-ready, can be leveraged directly). |
| `backend/sandbox/test_runner.py` | Sandbox Test Execution | `WorkspaceTestRunner`: executes `pytest`, `unittest`, `jest`, `vitest` in sandboxed cwd, parses exit codes, outputs, failure classes. | **IMPLEMENTED BUT NOT INTEGRATED** into test generation service. |
| `backend/scanner/test_requirement_discovery.py` | Requirement Discovery | Discovers 14 categories of test requirements from AST symbols, parameters, and models. | **FULLY IMPLEMENTED**. |
| `backend/app/services/test_generation_report.py` | Markdown Reporter | Formats markdown report of generated test suite. | **PARTIALLY IMPLEMENTED** (Reports static metrics; lacks coverage & stability data). |
| `backend/scripts/benchmark_quality_suite.py` | Benchmark Harness | Regression test suite and quality evaluator across RAG, bug detection, review, and test generation. | **IMPLEMENTED BUT INCORRECT** (Hardcoded `✅ PASS` for assertion presence rate despite falling below threshold). |
| `frontend/src/components/explorer/TestGenerationView.tsx` | React UI | Workbench view displaying generated test code, scenarios, warnings, and copy/download controls. | **PARTIALLY IMPLEMENTED** (Static display; lacks verification badges, stability metrics, coverage comparisons). |

---

## 3. Current Execution Flow & Gaps

1. **Target Identification:** Developer selects a target file, symbol, or line range in the UI or API (`POST /api/v1/repositories/{id}/generate-tests`).
2. **Framework Detection:** `detect_repository_test_framework()` queries `RepositoryFile` and `CodeChunk` records. While `framework_detector.py` recognizes `vitest`, line 264 in `test_generation_orchestrator.py` explicitly rejects it with `400 UNSUPPORTED_TARGET`.
3. **Context Construction:** `TestContextBuilder` gathers target code, imports, fixtures (`conftest.py`), and mockable calls.
4. **LLM Generation:** LLM generates a JSON payload with `test_content`, `proposed_test_path`, and `covered_scenarios`.
5. **Static Validation Only:** `validate_generated_test_syntax()` performs `ast.parse` for Python and regex brace balancing for JS.
6. **No Execution:** The system stops here. The generated code is never executed, leading to unobserved errors:
   - Non-existent imports or circular imports.
   - Broken fixtures or incorrect mock setup.
   - Faulty assertions that immediately fail or error out.
   - Zero verification of whether any code is actually executed.

---

## 4. Existing Sandbox Capabilities Assessment

The `backend/sandbox/` subsystem was thoroughly hardened during Week 3 and is production-ready:
- **Isolation:** `WorkspaceManager` creates isolated worktrees under `.workspaces/task-<id>` or temporary directories.
- **Process Guarding:** `WorkspaceCommandRunner` isolates execution with strict environment variable stripping (`PATH`, minimal defaults; removes `AWS_*`, `GITHUB_*`, `DATABASE_URL`, `JWT_SECRET`).
- **Resource Limits:** `ResourceMonitor` tracks CPU, memory, and timeout limits (default 60s, max 300s). Output capped at 100 KB to avoid log exhaustion.
- **Filesystem Security:** `WorkspacePathGuard` defends against directory traversal (`../`) and symlink escapes.
- **Test Runner:** `WorkspaceTestRunner` parses test execution output for `pytest`, `unittest`, `jest`, and `vitest`.
- **Readiness:** The sandbox infrastructure is **100% ready** to run generated tests. We do NOT need to reinvent or duplicate sandbox components; we only need to bridge test generation to `WorkspaceManager` and `WorkspaceTestRunner`.

---

## 5. Existing Framework Support

| Framework | `framework_detector.py` | `test_generation_orchestrator.py` | `SupportedTestFramework` Schema | `WorkspaceTestRunner` | Frontend UI |
|---|---|---|---|---|---|
| `pytest` | Supported | Supported | Supported | Supported | Supported |
| `unittest` | Supported | Supported | Supported | Supported | Supported |
| `jest` | Supported | Supported | Supported | Supported | Supported |
| `vitest` | Declared & Detected | **Blocked (L264)** | **Missing** | Supported | **Missing** |

**Gap:** Vitest is supported by the scanner and the sandbox test runner, but blocked at the orchestration layer, schema layer, and frontend client.

---

## 6. Existing Coverage Capabilities

- `scanner/test_coverage_analyzer.py` exists as a static coverage estimator based on AST symbol mappings.
- **Runtime coverage measurement is currently missing:**
  - Neither `coverage.py` nor `pytest --cov` is invoked at runtime.
  - No baseline test execution is performed before test generation.
  - No post-generation delta coverage is calculated.
  - No attribution of newly covered lines to generated tests exists.

---

## 7. Existing Benchmark Logic & Gate Flaw

In `backend/scripts/benchmark_quality_suite.py` and `Docs/quality_benchmark_report.md`:
- `run_test_generation_quality_benchmark()` evaluates:
  - `syntax_validity_rate`: 75.0% (target $\ge 66.0\%$)
  - `assertion_presence_rate`: 50.0% (target $\ge 66.0\%$)
- In `generate_markdown_report()`, line 724:
  ```python
  | **Assertion Presence Rate** | **{test_gen['assertion_presence_rate']*100:.1f}%** | $\ge 66.0\%$ | ✅ PASS |
  ```
- **Flaw:** The template hardcoded `✅ PASS` instead of evaluating `status = "PASS" if value >= threshold else "FAIL"`. Furthermore, `all_quality_gates_passed` omitted checking assertion rate and syntax validity thresholds.

---

## 8. Existing Frontend Behavior

`frontend/src/components/explorer/TestGenerationView.tsx`:
- Renders `detected_framework`, `proposed_test_path`, `covered_scenarios` (Normal, Edge Case, Failure Path), and syntax status.
- Lacks indicators for test execution, stability across runs, coverage delta, or iterative generation rounds.
- Hardcodes frameworks to `pytest`, `unittest`, and `jest` without `vitest`.

---

## 9. Missing Capabilities

1. **Sandbox Test Execution:** Invoking the sandbox to actually run generated test suites against target code.
2. **Stability Validation:** Three consecutive execution runs (`MAX_STABILITY_RUNS = 3`) to classify flakiness.
3. **Runtime Coverage Engine:** Measuring baseline coverage, post-generation coverage, and computing coverage delta (lines and branches) using `coverage.py` and `vitest/jest --coverage`.
4. **Coverage-Guided Iterative Feedback Loop:** Feeding uncovered lines/branches back into targeted LLM rounds (`MAX_GENERATION_ROUNDS = 3`).
5. **Vitest End-to-End Support:** End-to-end integration across schemas, orchestrator, prompts, and UI.
6. **Benchmark Gate Enforcement:** Strict threshold logic where $< \text{threshold}$ produces `FAIL`.
7. **Mutation Testing Evaluation:** Offline evaluation module calculating mutation score ($Killed / Non-Equivalent$).
8. **Truthful Verification Statuses:** Explicit categorization into `VERIFIED`, `UNVERIFIED`, `REJECTED`, and `EXECUTION_ERROR`.

---

## 10. Security Gaps & Threat Model

1. **Untrusted Code Execution:** Generated tests are generated by an LLM and must be treated as untrusted code.
   - *Mitigation:* Execute strictly inside `WorkspaceManager` temporary directories with `cwd=workspace_path`.
   - *Environment:* Strip host credentials (`DATABASE_URL`, `JWT_SECRET`, `GITHUB_*`, `GEMINI_*`, `GROQ_*`).
   - *Network:* Disable outbound network access during test runs where feasible.
   - *Filesystem:* Enforce `WorkspacePathGuard` to prevent reading or writing outside the workspace.
2. **Protected File Collisions:** Prevent writing to `conftest.py`, `pytest.ini`, `vitest.config.*`, `package.json`, or root dotfiles.
3. **Resource Exhaustion:** Bound execution time (timeout $\le 60$s), memory, process spawn count, and output logs (max 100 KB).

---

## 11. Integration Dependencies

- `backend/sandbox/workspace_manager.py` (Workspace provisioning and isolated worktree management)
- `backend/sandbox/test_runner.py` (Command execution and output parsing)
- `backend/scanner/framework_detector.py` (Detection of frameworks and test commands)
- `backend/ai/llm/client.py` (LLM gateway for initial and iterative generation)
- `backend/app/models/` and `backend/app/repositories/` (Database persistence for runs)

---

## 12. Exact Files Requiring Modifications

1. `backend/app/schemas/analysis.py`: Add `"vitest"` to `SupportedTestFramework`; extend `TestGenerationResult` with `verification_status`, `stability_report`, `coverage_report`, and `iteration_report`.
2. `backend/app/services/test_generation_orchestrator.py`: Add execution, stability validation (3 runs), coverage measurement, and iterative generation orchestration; enable Vitest.
3. `backend/ai/services/test_generation_service.py`: Support iterative prompting with uncovered lines/branches and feedback context; support Vitest syntax and fixtures.
4. `backend/app/services/test_generation_report.py`: Format execution outcomes, stability classifications, and coverage deltas in markdown reports.
5. `backend/scripts/benchmark_quality_suite.py`: Fix hardcoded gate evaluation logic to dynamically enforce thresholds.
6. `backend/tests/test_feature_quality_benchmarks.py`: Verify that below-threshold values produce `FAIL`.
7. `frontend/src/types/analysis.ts`: Add `'vitest'` to `SupportedTestFramework`; add verification and coverage fields.
8. `frontend/src/components/explorer/TestGenerationView.tsx`: Add Vitest commands, verification badges, stability and coverage tabs.

---

## 13. Exact New Files Required

1. `backend/app/services/test_coverage_service.py`: Dedicated runtime coverage engine for Python (`coverage.py` / `pytest-cov`) and JavaScript/TypeScript (`vitest` / `jest --coverage`).
2. `backend/app/services/test_stability_service.py`: 3-run stability validator classifying `STABLE`, `UNSTABLE`, and `FAILED`.
3. `backend/app/services/test_mutation_service.py`: Offline mutation testing evaluation harness and score calculator.
4. `backend/tests/test_test_generation_execution_verified.py`: Comprehensive test suite verifying execution, 3-run stability, coverage gain, and iterative feedback.
5. `backend/tests/test_test_coverage_service.py`: Tests for baseline, post-generation, and delta coverage attribution.
6. `backend/tests/test_test_generation_vitest.py`: End-to-end Vitest detection, generation, and execution tests.
7. `backend/tests/test_benchmark_gate_evaluator.py`: Unit tests verifying that benchmark thresholds strictly FAIL below targets.
8. `Docs/test-generation/*.md`: Full documentation suite (22 files, diagrams, research docs).

---

## 14. Risks and Compatibility Concerns

- **API Backward Compatibility:** Existing fields (`syntax_valid`, `covered_scenarios`, `test_content`, `proposed_test_path`) must remain intact so existing API consumers and UI code continue working without breakage.
- **Execution Overhead:** Running 3 stability runs and coverage measurement increases execution time. Timeouts must be bounded (e.g. 15s per run, total budget $\le 60$s).
- **Graceful Degradation:** If sandbox workspace creation fails or dependencies are missing, the system must classify as `UNVERIFIED` or `EXECUTION_ERROR` with human-readable diagnostic explanations rather than crashing.

---

## 15. Implementation Roadmap

- **Phase 0:** Audit & Baseline Documentation (This document).
- **Phase 1:** Benchmark Gate Correction & Evaluator Unit Tests.
- **Phase 2:** Sandbox Readiness Verification & Capability Extension.
- **Phase 3:** Execution-Verified Pipeline & 3-Run Stability Validator.
- **Phase 4:** Runtime Coverage Measurement Engine (`test_coverage_service.py`).
- **Phase 5:** Complete End-to-End Vitest Support across Schemas, Prompts, and Execution.
- **Phase 6:** Coverage-Guided Iterative Test Generation (CoverUp pattern, $\le 3$ rounds).
- **Phase 7:** Offline Mutation Testing Evaluation Harness (`test_mutation_service.py`).
- **Phase 8:** Frontend UI & Reporting Enhancements.
- **Phase 9:** Comprehensive Quality & Adversarial Security Test Suite.
- **Phase 10:** Complete Documentation Suite in `Docs/test-generation/`.
