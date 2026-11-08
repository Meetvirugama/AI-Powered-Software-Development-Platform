# 5-Stage Execution and Verification Flow

This document details the exact execution and verification stages traversed by every generated test.

---

## Stage 1: Static Validation
- **Python Targets**:
  - Validates code structure using `ast.parse(clean_content)`.
  - Scans for dangerous tokens (`eval`, `exec`, `os.system`, `subprocess`, raw network calls).
  - Verifies presence of at least one `test_` function or `Test` class with assertions (`assert `).
- **JavaScript/TypeScript Targets**:
  - Validates balanced delimiters (`{`, `}`, `[`, `]`, `(`, `)`).
  - Verifies presence of framework constructs (`describe(`, `it(`, `test(`, `expect(`).
  - Accepts Vitest mocking primitives (`vi.fn()`, `vi.mock()`).
- **Path & Security Policy**:
  - `check_generated_test_path`: Rejects reserved filenames (`conftest.py`, `pytest.ini`, `package.json`, `.github/workflows/*`).
  - `validate_repo_relative_path`: Blocks path traversal (`../`) and absolute paths.

---

## Stage 2: Sandbox Provisioning
- Managed by `WorkspaceManager.create_workspace`.
- Allocates a disposable directory under `.workspaces/task-xxx-hash`.
- Copies target source file and essential manifest dependencies.
- Enforces filesystem isolation: the original repository is never modified.

---

## Stage 3: Stability Validation (3 Consecutive Runs)
- Configuration: `MAX_STABILITY_RUNS = 3`.
- The suite is executed three times in succession inside the sandbox.
- Classification logic:
  - **3/3 PASS** $\implies$ `STABLE` (`is_stable=True`).
  - **2/3 PASS** $\implies$ `UNSTABLE` (`is_stable=False`). Flaky candidate.
  - **1/3 or 0/3 PASS** $\implies$ `FAILED` (`is_stable=False`). Persistent failure.
- Captures run-level duration, exit codes, and failure logs.
- Flaky tests are **never** marked verified.

---

## Stage 4: Coverage Measurement & Attribution
- **Stage 4a (Baseline)**: Measures coverage of target source code prior to adding generated tests.
- **Stage 4b (Post-Gen)**: Writes generated test file to `proposed_test_path` and measures combined coverage.
- **Gain Formula**:
  $$\text{Gain}_{\text{line}} = \text{Cov}_{\text{post}} - \text{Cov}_{\text{baseline}}$$
  $$\text{Gain}_{\text{branch}} = \text{Branch}_{\text{post}} - \text{Branch}_{\text{baseline}}$$
- **Attribution**:
  $$\text{Newly Covered Lines} = \text{Covered}_{\text{post}} \setminus \text{Covered}_{\text{baseline}}$$
- Tests producing 0% gain and 0 newly covered lines remain `UNVERIFIED`.

---

## Stage 5: Final Classification
- `VERIFIED`: Static OK + Sandbox Execution OK + 3/3 Stability OK + Attributed Coverage Gain.
- `UNVERIFIED`: Syntactically valid, but execution failed, was flaky (2/3), or yielded zero coverage gain.
- `REJECTED`: Path policy violation, protected file modification attempt, or prohibited tokens.
- `EXECUTION_ERROR`: Sandbox failure, execution timeout, or missing test runner environment.
- **Cleanup Guarantee**: Sandbox workspace is cleaned unconditionally in the `finally:` block.
