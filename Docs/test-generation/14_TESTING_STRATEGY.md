# Comprehensive Testing & QA Strategy

---

## 1. Testing Pyramid

Our verification strategy validates the test generation upgrade across four distinct tiers:

1. **Unit Testing Tier**:
   - `test_test_stability_service.py`: 7 tests verifying 3/3 PASS, 2/3 UNSTABLE, $\le 1/3$ FAILED, crashes, and runner adapters.
   - `test_test_coverage_service.py`: 6 tests verifying JSON parsing, delta gain calculations, attribution, and unconfigured fallbacks.
   - `test_test_mutation_service.py`: 4 tests verifying comparison, arithmetic, and constant AST mutant generation and score calculations.
   - `test_test_iteration_service.py`: 5 tests verifying context window slicing, stopping conditions, AST/regex test merging, and scenario deduplication.
   - `test_benchmark_gate_evaluator.py`: 8 tests verifying dynamic threshold evaluations.

2. **Integration Testing Tier (Scenarios A through V)**:
   - `test_test_generation_execution_verified.py`: 22 end-to-end integration tests implementing Scenarios A through V from `task.md` §11.2.
   - `test_test_generation_vitest.py`: 6 tests validating Vitest manifests, disambiguation, command construction, and syntax compatibility.

3. **Regression Testing Tier**:
   - `test_generate_tests_day4.py`: 9 tests verifying framework detection, conftest guards, secret redaction, and endpoint execution.
   - `test_test_generation_comprehensive.py`: 7 tests verifying requirement discovery, multi-level evidence, and gap matrix.
   - `test_framework_detector.py`: 48 tests verifying multi-language repository detection.

4. **Frontend Testing Tier**:
   - 329 Vitest tests across 27 suites (`npm --prefix frontend test -- --run`).
   - Production bundle build verified with `npm --prefix frontend run build`.
