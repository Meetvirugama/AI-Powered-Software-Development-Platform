# Execution-Verified, Coverage-Guided Automated Test Generation

Welcome to the comprehensive documentation suite for the upgraded **Test Generation Feature (F13 / Issue #193)** of the AI-Powered Software Development Platform.

---

## 1. Feature Purpose & Value
The test generation engine transforms from a static, unverified syntax generator into an **execution-verified, coverage-guided, iterative, and security-hardened testing system**.

Every candidate test file undergoes a strict 5-stage verification pipeline inside an isolated sandbox (`.workspaces/`), verifying:
1. **Static Syntax & Path Policy**: No reserved-file overwrites (`conftest.py`, `pytest.ini`), no traversal escapes, valid AST/parser trees.
2. **Sandbox Execution**: Code runs in a clean, disposable workspace with resource limits and secret redaction.
3. **Stability & Flakiness Filter**: Executes 3 consecutive runs (`MAX_STABILITY_RUNS = 3`). Flaky tests (2/3) or failing tests (<=1/3) are explicitly classified as `UNVERIFIED`.
4. **Coverage Measurement & Attribution**: Measures baseline coverage vs. post-generation coverage, attributing newly exercised source lines specifically to the generated test.
5. **Iterative Feedback Loop**: Guided by uncovered line numbers (CoverUp P-11 inspiration) for up to 3 generation rounds (`MAX_GENERATION_ROUNDS = 3`).
6. **Offline Mutation Testing**: AST mutation engine (MuTAP P-12 inspiration) calculates mutation kill scores for offline benchmarking.

---

## 2. Verification Status Hierarchy

```
[ Synthesized Test ]
         │
         ▼
[ Stage 1: Static Validation ] ───(Fail)───► UNVERIFIED / REJECTED
         │ (Pass)
         ▼
[ Stage 2: Sandbox Provisioning ] ──(Crash)──► EXECUTION_ERROR
         │ (Success)
         ▼
[ Stage 3: Stability Validation (3 Runs) ] ─(2/3 or <=1/3)─► UNVERIFIED (Flaky / Failed)
         │ (3/3 Pass)
         ▼
[ Stage 4: Coverage Attribution ] ──(0% Gain)──► UNVERIFIED (No coverage delta)
         │ (Gain > 0%)
         ▼
    VERIFIED ✅
```

---

## 3. Documentation Sitemap

| Document | Title | Description |
| :--- | :--- | :--- |
| [00_EXISTING_IMPLEMENTATION_AUDIT.md](00_EXISTING_IMPLEMENTATION_AUDIT.md) | Existing Implementation Audit | Baseline audit of files, schemas, and sandbox capabilities before upgrade. |
| [01_REQUIREMENTS_AND_SCOPE.md](01_REQUIREMENTS_AND_SCOPE.md) | Requirements and Scope | Functional, non-functional requirements, and acceptance criteria. |
| [02_EXISTING_VS_PROPOSED_ARCHITECTURE.md](02_EXISTING_VS_PROPOSED_ARCHITECTURE.md) | Architecture Comparison | Side-by-side comparison of pre-existing vs upgraded architecture. |
| [03_SYSTEM_ARCHITECTURE.md](03_SYSTEM_ARCHITECTURE.md) | System Architecture | Component boundaries, responsibilities, and data contracts. |
| [04_EXECUTION_AND_VERIFICATION_FLOW.md](04_EXECUTION_AND_VERIFICATION_FLOW.md) | Execution & Verification Flow | Detailed explanation of Stages 1 through 5. |
| [05_SANDBOX_SECURITY_DESIGN.md](05_SANDBOX_SECURITY_DESIGN.md) | Sandbox Security Design | Process isolation, path guards, env stripping, and quotas. |
| [06_FRAMEWORK_ADAPTERS.md](06_FRAMEWORK_ADAPTERS.md) | Framework Adapters | pytest, unittest, jest, and vitest command & parser logic. |
| [07_COVERAGE_MEASUREMENT.md](07_COVERAGE_MEASUREMENT.md) | Coverage Measurement | Baseline, post-generation, delta calculation, and line attribution. |
| [08_COVERAGE_GUIDED_ITERATION.md](08_COVERAGE_GUIDED_ITERATION.md) | Coverage-Guided Iteration | Iterative feedback loop (CoverUp P-11), prompts, and merge logic. |
| [09_MUTATION_TESTING.md](09_MUTATION_TESTING.md) | Mutation Testing Engine | AST mutators, offline evaluation, score formula, and limitations. |
| [10_BENCHMARK_AND_EVALUATION.md](10_BENCHMARK_AND_EVALUATION.md) | Benchmark & Quality Gates | Corrected threshold evaluator (`evaluate_metric`) and quality gates. |
| [11_API_AND_DATABASE_CHANGES.md](11_API_AND_DATABASE_CHANGES.md) | API & Database Changes | Schema extensions in `analysis.py` and backward compatibility. |
| [12_FRONTEND_INTEGRATION.md](12_FRONTEND_INTEGRATION.md) | Frontend Integration | UI updates to `TestGenerationView.tsx` with verification badges. |
| [13_IMPLEMENTATION_PLAN.md](13_IMPLEMENTATION_PLAN.md) | Implementation Plan | 10-phase execution plan and architectural decisions. |
| [14_TESTING_STRATEGY.md](14_TESTING_STRATEGY.md) | Testing Strategy | Unit, integration (Scenarios A–V), regression, and security tests. |
| [15_SECURITY_AND_THREAT_MODEL.md](15_SECURITY_AND_THREAT_MODEL.md) | Security & Threat Model | STRIDE threat model, sandboxing, secret redaction, and attack vectors. |
| [16_PERFORMANCE_AND_COST_CONTROL.md](16_PERFORMANCE_AND_COST_CONTROL.md) | Performance & Cost Control | LLM token caps, execution timeouts, and prompt compression. |
| [17_DEPLOYMENT_AND_CONFIGURATION.md](17_DEPLOYMENT_AND_CONFIGURATION.md) | Deployment & Configuration | Environment variables, dependencies, and sandbox settings. |
| [18_TROUBLESHOOTING.md](18_TROUBLESHOOTING.md) | Troubleshooting Guide | Remediation for flakiness, coverage failures, and sandbox timeouts. |
| [19_IMPLEMENTATION_CHANGELOG.md](19_IMPLEMENTATION_CHANGELOG.md) | Implementation Changelog | Exact phase-by-phase modifications and newly created files. |
| [20_IMPLEMENTATION_TEST_REPORT.md](20_IMPLEMENTATION_TEST_REPORT.md) | Implementation Test Report | Executed test logs, pass counts (127/127 backend, 329/329 frontend). |
| [21_KNOWN_LIMITATIONS.md](21_KNOWN_LIMITATIONS.md) | Known Limitations | Technical constraints, edge cases, and future roadmap items. |

---

## 4. Architecture Diagrams
Mermaid diagrams reside in `Docs/test-generation/diagrams/`:
- [`existing_architecture.mmd`](diagrams/existing_architecture.mmd): Pre-upgrade single-shot pipeline.
- [`proposed_architecture.mmd`](diagrams/proposed_architecture.mmd): Upgraded 5-stage verified pipeline.
- [`execution_sequence.mmd`](diagrams/execution_sequence.mmd): Sequence flow between API, LLM, Verifier, and Sandbox.
- [`coverage_iteration.mmd`](diagrams/coverage_iteration.mmd): CoverUp-inspired feedback loop.
- [`sandbox_security.mmd`](diagrams/sandbox_security.mmd): Sandbox security boundaries and isolation.
- [`verification_state_machine.mmd`](diagrams/verification_state_machine.mmd): State machine transitions.

---

## 5. Research References
Research evaluations reside in `Docs/test-generation/research/`:
- [P10_TESTGEN_LLM.md](research/P10_TESTGEN_LLM.md): Meta's TestGen-LLM industrial pipeline.
- [P11_COVERUP.md](research/P11_COVERUP.md): UMass CoverUp high-coverage test synthesis.
- [P12_MUTAP.md](research/P12_MUTAP.md): MuTAP mutation testing for LLMs.
- [P13_TESTPILOT.md](research/P13_TESTPILOT.md): TestPilot JavaScript/TypeScript testing.
- [TOOLS_AND_LICENSES.md](research/TOOLS_AND_LICENSES.md): Tool licenses and version compatibilities.
