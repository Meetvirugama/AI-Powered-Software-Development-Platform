# Coverage-Guided Iterative Test Generation (CoverUp Feedback Loop)

---

## 1. Feedback Loop Workflow

Inspired by CoverUp (Goffi et al., 2024), `TestIterationOrchestrator` (`backend/app/services/test_iteration_service.py`) conducts up to `MAX_GENERATION_ROUNDS = 3` refinement rounds:

1. **Round 1**: Initial generation covering normal, edge-case, and failure-path scenarios.
2. **Execute & Analyze**: Collect runtime coverage. Identify uncovered executable lines.
3. **Snippet Extraction**: `extract_uncovered_context` extracts a $\pm 2$ line code window around uncovered statements.
4. **Targeted Prompting**: LLM is supplied only the uncovered context and missing requirements, asking for targeted tests only.
5. **Smart Merge**: `merge_generated_tests` merges new test functions and new imports into the existing test file without duplicating test names.
6. **Re-evaluate**: Executes the combined suite and checks if coverage increased.

---

## 2. Deterministic Stopping Conditions

The iteration loop terminates immediately when any of the following conditions is met:
1. **100% Coverage Reached**: No uncovered lines remain in the target file.
2. **Coverage Plateau**: Line coverage did not improve between consecutive rounds (`new_coverage <= prev_coverage`).
3. **Round Budget Reached**: Current round equals `MAX_GENERATION_ROUNDS = 3`.
4. **Execution Failure**: Newly generated test fails execution or crashes the sandbox.
