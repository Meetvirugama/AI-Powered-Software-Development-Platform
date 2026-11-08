# Existing vs. Proposed Architecture Comparison

---

## 1. Architectural Evolution

| Architectural Dimension | Pre-Existing System (Day 4 Baseline) | Upgraded System (Issue #193) |
| :--- | :--- | :--- |
| **Verification Gate** | Static syntax check only (`ast.parse` for Python, balanced delimiters for JS). | 5-stage pipeline: Static $\to$ Sandbox $\to$ Stability $\to$ Coverage $\to$ Classification. |
| **Sandbox Execution** | None. Tests were previewed without runtime validation. | Isolated temporary workspace (`.workspaces/task-xxx`) executing real runners. |
| **Flakiness Detection** | None. Single run or no run. | Deterministic 3-consecutive-run stability validator (`MAX_STABILITY_RUNS = 3`). |
| **Coverage Analysis** | None or static heuristic guesses. | Runtime coverage delta measurement via `coverage.py` & Istanbul/V8. |
| **Coverage Attribution** | None. | Direct line-by-line attribution of newly covered lines to generated tests. |
| **Feedback Loop** | Single-shot generation. | Coverage-guided iterative refinement (up to 3 rounds) targeting uncovered lines. |
| **Defect Detection Evaluation** | None. | Offline AST-based mutation testing service (`MutationTestingService`). |
| **Vitest Support** | Declared in detector enum but rejected in orchestrator with 400. | Full end-to-end support (`vitest.config.*`, `npm test -- --run`, `vi.mock`). |
| **Benchmark Threshold Gate** | Hardcoded `✅ PASS` in markdown template even when metrics fell below target. | Dynamic threshold evaluator (`evaluate_metric`) that strictly fails on below-target metrics. |
| **Frontend UI** | Static preview only. | Verification status badges, 3-run breakdown, coverage delta stats, and terminal output. |

---

## 2. Key Architectural Decisions

1. **Reuse Existing Sandbox Infrastructure**: Rather than building a parallel execution engine, we leveraged `WorkspaceManager` and `WorkspaceTestRunner`, extending them with coverage arguments and multi-run stability validation.
2. **Separation of Services**:
   - `TestStabilityValidator`: Handles run-level flakiness detection.
   - `TestCoverageService`: Handles baseline, post-gen, and attribution metrics.
   - `TestIterationOrchestrator`: Handles uncovered slice extraction and prompt feedback.
   - `MutationTestingService`: Handles offline AST mutation testing.
   - `TestExecutionVerifier`: Coordinates the end-to-end verification pipeline.
