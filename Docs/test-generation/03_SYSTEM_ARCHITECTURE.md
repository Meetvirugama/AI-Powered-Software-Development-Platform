# System Architecture: Execution-Verified Test Generation

---

## 1. Component Boundaries & Responsibilities

```
                                    ┌────────────────────────────────────────────────────────┐
                                    │               TestGenerationResponse                   │
                                    └──────────────────────────▲─────────────────────────────┘
                                                               │
┌────────────────────────┐      ┌──────────────────────────────┴─────────────────────────────┐
│  Analysis API Route    ├─────►│                  TestExecutionVerifier                     │
│ (api/v1/analysis/      │      │       (app/services/test_execution_verifier.py)            │
│  tests.py)             │      └──────────────┬───────────────┬───────────────┬─────────────┘
└──────────┬─────────────┘                     │               │               │
           │                                   ▼               │               ▼
           ▼                            ┌──────────────┐       │       ┌──────────────┐
┌────────────────────────┐              │ TestCoverage │       │       │ TestStability│
│  TestGenerationService │              │   Service    │       │       │  Validator   │
│  (ai/services/)        │              └──────┬───────┘       │       └──────┬───────┘
└──────────┬─────────────┘                     │               ▼              │
           │                                   │        ┌──────────────┐      │
           ▼                                   └───────►│  Workspace   │◄─────┘
┌────────────────────────┐                              │   Manager    │
│ TestIterationOrchestr. │                              │ (sandbox/)   │
│ (app/services/)        │                              └──────┬───────┘
└────────────────────────┘                                     │
                                                               ▼
                                                        ┌──────────────┐
                                                        │ Isolated OS  │
                                                        │ Subprocess   │
                                                        └──────────────┘
```

### 1.1 `TestExecutionVerifier` (`backend/app/services/test_execution_verifier.py`)
- Acts as the central pipeline coordinator.
- Manages temporary sandbox workspace lifecycle (`create_workspace` $\to$ `cleanup_workspace` in `finally:` block).
- Executes Stage 1 (Static validation check), Stage 2 (Sandbox setup), Stage 3 (Stability validation), Stage 4 (Coverage delta), and Stage 5 (Classification).

### 1.2 `TestStabilityValidator` (`backend/app/services/test_stability_service.py`)
- Executes the test suite exactly `MAX_STABILITY_RUNS = 3` consecutive times.
- Detects transient failures and race conditions without retrying indefinitely.
- Generates a structured `StabilityReport`.

### 1.3 `TestCoverageService` (`backend/app/services/test_coverage_service.py`)
- Dispatches framework coverage adapters (`coverage.py` for Python, Istanbul/V8 for Node).
- Gathers baseline target coverage before test injection.
- Gathers post-generation target coverage with generated tests.
- Computes coverage gains and newly exercised line numbers.

### 1.4 `TestIterationOrchestrator` (`backend/app/services/test_iteration_service.py`)
- Extracts code snippets around uncovered lines.
- Enforces loop termination rules (plateau, 100% coverage, max 3 rounds).
- Deduplicates test methods and covered scenarios.

### 1.5 `MutationTestingService` (`backend/app/services/test_mutation_service.py`)
- Offline evaluation engine synthesizing AST mutants (comparison, arithmetic, constants).
- Computes mutation kill scores to benchmark test suite quality.
