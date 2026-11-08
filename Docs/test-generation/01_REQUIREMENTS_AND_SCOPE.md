# Requirements and Scope: Execution-Verified Test Generation

---

## 1. Functional Requirements

1. **Sandbox Execution (FR-01)**: Every generated test suite must be placed in an isolated temporary workspace provisioned under `.workspaces/` and executed using the detected runner (`pytest`, `python -m unittest`, `npm test`, or `npm test -- --run`).
2. **Stability Validation (FR-02)**: Generated tests must execute across `MAX_STABILITY_RUNS = 3` consecutive runs. Only 3/3 passed runs are classified as `STABLE`. Tests passing 2/3 runs are marked `UNSTABLE` (flaky) and never verified.
3. **Runtime Coverage Measurement (FR-03)**: The system must collect baseline coverage prior to test injection and post-generation coverage with the test included.
4. **Coverage Attribution (FR-04)**: Newly covered lines and branches must be attributed specifically to the generated test suite. Zero-gain tests remain `UNVERIFIED`.
5. **Coverage-Guided Iterative Refinement (FR-05)**: The system must support up to `MAX_GENERATION_ROUNDS = 3` iterative refinement loops, feeding uncovered lines back to the LLM.
6. **Complete Vitest Support (FR-06)**: Complete end-to-end integration for Vitest (`vitest.config.ts`, `vite.config.ts`, `package.json`, `npm test -- --run`, `vi.fn()`, `vi.mock()`).
7. **Offline Mutation Testing (FR-07)**: An offline mutation testing service (`MutationTestingService`) evaluating test suites against synthesized AST mutants.
8. **Correct Quality Gates (FR-08)**: Benchmark evaluator must fail strictly when measured metrics fall below target thresholds or when data is missing.
9. **Transparent Frontend Display (FR-09)**: `TestGenerationView.tsx` must clearly display verification status badges, stability breakdowns, coverage comparisons, iteration counts, and collapsible logs.

---

## 2. Non-Functional Requirements

1. **Security & Sandboxing (NFR-01)**: Generated code is treated as untrusted. Subprocesses run with stripped credentials, strict path guards, and no access to host secrets or databases.
2. **Performance & Latency (NFR-02)**: Sandboxed execution is bounded by a 45s hard timeout.
3. **Cost Control (NFR-03)**: Iterations are capped at 3 rounds; prompt context is pruned to uncovered slices only (no whole-repository re-sending).
4. **Zero Host Side-Effects (NFR-04)**: Original repository files are never modified or overwritten automatically.

---

## 3. Out-of-Scope Items

- Automatic code deployment or automatic PR merging.
- Running mutation testing synchronously on every live user request (reserved for offline quality benchmarking).
- Compiling C/C++ or non-standard languages (system scopes to Python and JavaScript/TypeScript).
