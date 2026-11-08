# Research Summary: CoverUp (High-Coverage Test Suite Synthesis)

**Citation**: Goffi, A., Gorla, A., & Mattavelli, A. (2024). *CoverUp: High-Coverage Python Unit Test Suite Generation with LLMs*. arXiv:2403.04785.

---

## 1. Problem Formulation
Single-shot prompt generation typically yields unit tests that only exercise obvious "happy paths" (normal behavior), leaving edge cases, error handlers, and branch conditions completely uncovered. Resending entire files to an LLM wastes context tokens and leads to duplicate test cases.

## 2. CoverUp's Approach
1. Execute an initial test pass to identify uncovered lines and missing branches.
2. For each uncovered segment, extract only the enclosing function/class slice (context window).
3. Query the LLM with focused, snippet-level test generation prompts targeting specific line numbers.
4. Filter out any generated tests that do not increase coverage or fail execution.
5. Merge non-duplicate test functions into the test suite until full coverage or a round limit is reached.

## 3. Applicability to Our Platform
We implemented `TestIterationOrchestrator` (`backend/app/services/test_iteration_service.py`) based on CoverUp's principles:
- **Targeted Context Extraction**: `extract_uncovered_context(source, uncovered_lines, window=2)` selects only code surrounding uncovered lines.
- **Bounded Feedback Loop**: Capped at `MAX_GENERATION_ROUNDS = 3` to control inference costs.
- **Stopping Conditions**: Terminate cleanly on 100% coverage, coverage plateaus, or round ceilings.
- **Smart Merge**: AST-level merging for Python and regex-level injection for JS/TS avoids duplicate test functions and imports.
