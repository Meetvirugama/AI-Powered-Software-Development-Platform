# Coverage Measurement, Delta Calculation & Line Attribution

---

## 1. Baseline and Post-Generation Strategy

To determine whether generated tests add genuine testing value, `TestCoverageService` (`backend/app/services/test_coverage_service.py`) follows a two-point delta measurement:

```
[ Isolated Workspace Root ]
           │
           ├─► 1. Run Baseline Test Suite ────────► Collect Baseline Target Coverage (%)
           │
           ├─► 2. Write Proposed Test File
           │
           └─► 3. Run Combined / Generated Test ──► Collect Post-Gen Target Coverage (%)
                                                               │
                                                               ▼
                                                  Calculate Coverage Gain:
                                                  Gain = PostGen% - Baseline%
```

---

## 2. Line Attribution Formula

A test is credited with improving code quality only if it exercises executable statements that were previously unexercised:

$$\text{Newly Covered Lines} = \text{CoveredLines}_{\text{post}} \setminus \text{CoveredLines}_{\text{baseline}}$$
$$\text{Newly Covered Branches} = \text{CoveredBranches}_{\text{post}} \setminus \text{CoveredBranches}_{\text{baseline}}$$

If $\text{Gain} \le 0\%$ and $\text{Newly Covered Lines} = \emptyset$, the test is marked `UNVERIFIED` under our strict verification policy, with the explicit reason:
`"Test executed cleanly across 3 runs, but produced 0% coverage gain on target file."`

---

## 3. Tool Fallbacks & Missing Tooling

If `coverage.py` or Node coverage tools are not installed in the execution environment:
- The service sets `collection_status = "NOT_CONFIGURED"`.
- It records a descriptive warning without crashing the pipeline.
- Coverage metrics are set to `None` rather than inventing synthetic 0.0% or 100.0% numbers.
