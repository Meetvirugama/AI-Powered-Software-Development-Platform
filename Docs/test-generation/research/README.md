# Automated Testing & Test Generation Research Index

This directory documents the scientific literature and industrial tooling evaluated during the architectural design of the execution-verified, coverage-guided test generation system (Issue #193).

---

## 1. Surveyed Literature

| Document | Paper / System | Origin / Authors | Core Concept Adopted |
| :--- | :--- | :--- | :--- |
| [P10_TESTGEN_LLM.md](P10_TESTGEN_LLM.md) | **TestGen-LLM** | Meta Platforms (Alshahwan et al., 2024) | Filter-and-verify pipeline: only verified tests that pass execution & regression gates reach developers. |
| [P11_COVERUP.md](P11_COVERUP.md) | **CoverUp** | University of Massachusetts (Goffi et al., 2024) | High-coverage test suite synthesis via targeted iterative feedback on uncovered lines and branches. |
| [P12_MUTAP.md](P12_MUTAP.md) | **MuTAP** | Automated Mutation-Guided LLM Testing (Dakhel et al., 2024) | Offline evaluation of test quality by synthesizing code mutants and computing mutant kill ratios. |
| [P13_TESTPILOT.md](P13_TESTPILOT.md) | **TestPilot** | GitHub / Delft University (Schäfer et al., 2023) | Deterministic JavaScript/TypeScript unit test generation with mocking APIs and isolated runtime execution. |

---

## 2. Surveyed Tools & Ecosystem Libraries

See [TOOLS_AND_LICENSES.md](TOOLS_AND_LICENSES.md) for full license compatibility, dependency footprints, and version matrices covering:
- **Python**: `coverage.py`, `pytest`, `pytest-cov`, `mutmut`, `unittest`.
- **Node.js**: `jest`, `vitest`, `c8`, `istanbul`, `stryker`.
