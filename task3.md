# Implementation Plan: AI Quality Evaluation, Benchmark Gating & Agent Evaluation Framework

## 1. Project Objective

Improve the existing AI quality evaluation infrastructure to ensure that:

1. Benchmark results accurately reflect actual model quality.
2. Below-threshold metrics always fail the quality gate.
3. False-positive and defect-detection evaluation becomes more reliable.
4. Quality evaluation runs automatically through CI.
5. Recorded fixtures provide reproducible evaluation without requiring live LLM API calls.
6. An end-to-end agent evaluation harness measures the software development agent against real-world coding issues.
7. Evaluation results are documented, measurable and comparable across model and agent versions.

The long-term objective is to establish a reliable evaluation framework that measures not only LLM response quality but also the actual ability of the autonomous software development platform to solve software engineering problems.

**Core principle:**

A benchmark must never report PASS when any mandatory metric is below its configured threshold.

Do not replace the existing evaluator unnecessarily. Improve and extend the current evaluation architecture.

---

# 2. Existing Implementation

Before modifying anything, inspect the existing evaluation system.

## 2.1 AI Quality Evaluator

Existing file:

`ai_quality_evaluator.py`

Size: Approximately 388 LOC.

Current responsibilities:

### A. Provider Allowlist Validation

- Validates supported providers.
- Currently permits Gemini and Groq.
- Rejects unsupported providers.

Preserve this security and configuration boundary.

### B. False-Positive Evaluator

Evaluates clean code to determine whether the AI incorrectly reports defects.

Purpose:

- Detect unnecessary warnings.
- Measure false-positive behaviour.
- Ensure clean code is not incorrectly flagged.

### C. Defect Fixture Evaluator

Evaluates known defective code fixtures.

Existing metrics:

- Precision.
- Recall.
- F1 score.

Purpose:

- Measure defect detection accuracy.
- Determine whether the evaluator identifies actual defects.
- Detect incorrect or irrelevant findings.

### D. Schema Conformance Checker

Checks whether evaluator outputs conform to the expected response schema.

Preserve this functionality.

## 2.2 Benchmark Infrastructure

Existing scripts:

- `benchmark_quality_suite.py` — approximately 745 LOC.
- `benchmark_rag.py`

Inspect both scripts and identify shared functionality, duplicated logic and existing benchmark conventions.

Do not duplicate existing evaluation functionality when extending the system.

---

# 3. Problems and Technical Gaps

## Problem 1: Insufficient Evaluation Fixtures

### Existing problem

The current fixture suite is small.

It does not provide sufficient diversity to establish confidence in evaluation results.

### Impact

- Evaluation results may depend heavily on a small number of examples.
- Edge cases may remain undetected.
- Precision and recall estimates may not represent real-world performance.
- Changes in prompts or models may appear successful without meaningful improvements.

### Required improvement

Build a larger, categorized and reproducible fixture dataset.

Include:

1. Clean code.
2. Actual defects.
3. Security vulnerabilities.
4. Performance issues.
5. Incorrect error handling.
6. Concurrency problems.
7. Resource leaks.
8. Edge-case defects.
9. False-positive traps.
10. Complex multi-file defects.

Every fixture must have an expected evaluation result.

---

## Problem 2: Critical Benchmark Gating Bug

Priority: P0.

### Existing problem

The benchmark gate contains incorrect comparison logic.

A metric below its configured threshold can incorrectly receive PASS.

### Impact

This is a critical reliability problem.

The evaluation system may approve an AI model or agent version that does not satisfy the required quality standards.

Consequences:

- Incorrect CI success.
- Unreliable model comparisons.
- Poor-quality changes can pass evaluation.
- Regression detection becomes unreliable.
- Quality reports become misleading.

### Required improvement

Implement strict threshold enforcement.

A metric below its minimum threshold must always fail.

Example:

```python
threshold = 0.80
actual_score = 0.72

passed = actual_score >= threshold

assert passed is False
```

The comparison must be explicit and mathematically correct.

Do not use reversed comparisons, truthiness checks or permissive default values.

---

## Problem 3: No Automatic CI Execution

### Existing problem

The quality evaluation suite is not automatically executed in CI.

### Impact

- Quality regressions may enter the main branch.
- Developers must manually execute benchmarks.
- Evaluation results are inconsistent.
- Changes to prompts and evaluator logic may go untested.

### Required improvement

Introduce a nightly CI workflow.

Run recorded-fixture evaluations automatically without making live LLM API calls.

---

## Problem 4: No End-to-End Agent Benchmark

### Existing problem

The current evaluator focuses primarily on AI quality and defect detection.

It does not adequately measure the autonomous software development platform's ability to solve complete software engineering tasks.

### Impact

The platform may generate technically plausible responses while failing to:

- Understand real issues.
- Modify the correct files.
- Implement working fixes.
- Preserve existing functionality.
- Pass regression tests.
- Produce maintainable changes.

### Required improvement

Develop a Mini SWE-bench evaluation harness containing 20–30 real-world software engineering tasks.

Measure the complete agent execution lifecycle.

---

# 4. Proposed Architecture

Implement an evaluation architecture with three layers.

```text
                Evaluation Infrastructure
                          |
             +------------+-------------+
             |            |             |
             v            v             v
       Quality Suite   RAG Benchmark   Agent Benchmark
             |            |             |
             v            v             v
       Fixture Data   RAG Datasets   Mini SWE-bench
             |            |             |
             +------------+-------------+
                          |
                          v
                  Evaluation Engine
                          |
                          v
                  Metrics Calculator
                          |
                          v
                   Quality Gate
                          |
                  +-------+-------+
                  |               |
                  v               v
                 PASS            FAIL
                  |               |
                  v               v
              CI Success      CI Failure
                          |
                          v
                 Evaluation Reports
```

## Architectural requirements

1. Maintain the existing AI quality evaluator.
2. Keep benchmark execution separate from metric calculation.
3. Centralize threshold configuration.
4. Make evaluation deterministic wherever possible.
5. Separate fixture-based testing from live model evaluation.
6. Make CI results reproducible.
7. Keep the agent benchmark isolated from production environments.
8. Store benchmark results in a structured format.

---

# 5. Solution 1: Fix Strict Benchmark Gating

Priority: P0.

Estimated size: Small.

This is the first task and must be completed before other major enhancements.

## 5.1 Audit Existing Gate Logic

Inspect:

- `ai_quality_evaluator.py`
- `benchmark_quality_suite.py`
- Any shared threshold or metrics utility.
- Existing test files.
- CI configuration.

Find every location where benchmark results are marked PASS or FAIL.

Search for:

- Threshold comparisons.
- Metric aggregation.
- Default metric values.
- Missing metric handling.
- Exception handling.
- Boolean pass/fail calculations.

Document the exact location of the bug.

## 5.2 Implement Correct Threshold Comparison

Expected behaviour:

```python
def evaluate_threshold(
    actual: float,
    minimum: float
) -> bool:
    return actual >= minimum
```

Examples:

| Actual | Threshold | Result |
|---:|---:|---|
| 0.95 | 0.80 | PASS |
| 0.80 | 0.80 | PASS |
| 0.79 | 0.80 | FAIL |
| 0.50 | 0.80 | FAIL |
| 0.00 | 0.80 | FAIL |

The threshold is inclusive: equality passes.

## 5.3 Centralized Threshold Configuration

Avoid scattering threshold values throughout benchmark scripts.

Introduce or extend a centralized configuration.

Example:

```yaml
quality_gates:
  precision:
    minimum: 0.80

  recall:
    minimum: 0.75

  f1_score:
    minimum: 0.80

  false_positive_rate:
    maximum: 0.10

  schema_conformance:
    minimum: 1.00
```

These are illustrative starting values. Inspect existing project requirements and preserve established thresholds unless a documented decision authorizes changing them.

Important:

- Precision, recall and F1 use minimum thresholds.
- False-positive rate uses a maximum threshold.
- Schema conformance uses the configured minimum.
- Each metric must declare its comparison direction.

## 5.4 Generic Gate Evaluator

Introduce a reusable gate evaluator.

Suggested interface:

```python
class QualityGate:
    def evaluate(
        self,
        metric_name: str,
        actual: float,
        threshold: float,
        comparison: str
    ) -> bool:
        ...
```

Supported comparisons:

- `gte`
- `gt`
- `lte`
- `lt`
- `eq`

Requirements:

1. Validate metric values.
2. Reject NaN and infinite values.
3. Handle missing metrics explicitly.
4. Reject invalid thresholds.
5. Include actual and expected values in the result.
6. Record the reason for failure.
7. Never default missing metrics to PASS.

## 5.5 Aggregate Gate Behaviour

Example:

```text
Precision:           PASS
Recall:              FAIL
F1:                  PASS
False Positive Rate: PASS
Schema Conformance:  PASS

Overall Result: FAIL
```

If a mandatory metric fails, the overall gate must fail.

Do not allow an average score to override a mandatory metric failure.

## 5.6 Regression Tests

Add tests for:

- Score greater than threshold.
- Score equal to threshold.
- Score below threshold.
- Zero score.
- Missing score.
- NaN.
- Positive infinity.
- Negative infinity.
- Invalid comparison operator.
- Multiple metrics with one failure.
- Multiple metrics with all passing.
- Maximum-threshold metrics.
- Empty evaluation results.

**Deliverable:** A verified benchmark gate that cannot report PASS when a mandatory metric is below its threshold.

---

# 6. Solution 2: Expand Fixture Evaluation

Priority: P1.

Estimated size: Medium.

## 6.1 Fixture Dataset Design

Create a structured fixture dataset.

Suggested directory:

```text
tests/
  evaluation/
    fixtures/
      clean_code/
      defect_detection/
      security/
      performance/
      error_handling/
      concurrency/
      resource_management/
      false_positives/
```

Each fixture should include:

- Unique fixture ID.
- Category.
- Description.
- Source code.
- Expected findings.
- Expected severity.
- Expected affected file or location.
- Expected behaviour.
- Reproduction instructions.
- Regression test where applicable.

Example:

```json
{
  "fixture_id": "SEC-001",
  "category": "security",
  "description": "SQL injection through string concatenation",
  "expected_findings": [
    {
      "type": "sql_injection",
      "severity": "high"
    }
  ]
}
```

Adapt this structure to the existing fixture schema rather than creating a conflicting format.

## 6.2 Fixture Categories

Develop fixtures for the following scenarios.

### Clean Code

- Valid input handling.
- Correct database queries.
- Proper exception handling.
- Safe resource cleanup.
- Correct authorization checks.

Purpose: Measure false-positive behaviour.

### Functional Defects

- Incorrect conditions.
- Off-by-one errors.
- Incorrect return values.
- Null handling problems.
- Incorrect state transitions.

### Security Defects

- SQL injection.
- Command injection.
- Path traversal.
- Insecure deserialization.
- Missing authorization.
- Hardcoded secrets.
- Unsafe file handling.

### Performance Defects

- N+1 queries.
- Unnecessary nested loops.
- Memory inefficiency.
- Repeated expensive operations.

### Concurrency Defects

- Race conditions.
- Shared-state mutation.
- Incorrect locking.
- Deadlocks.

### Error Handling

- Swallowed exceptions.
- Incorrect exception types.
- Missing cleanup.
- Improper retry logic.

## 6.3 Fixture Quality Requirements

Every fixture must be:

1. Reproducible.
2. Independently identifiable.
3. Categorized.
4. Validated against its expected outcome.
5. Version-controlled.
6. Licensed appropriately if sourced externally.

Do not artificially inflate benchmark scores using duplicate fixtures.

---

# 7. Solution 3: Improve Evaluation Metrics

Priority: P1.

Extend the existing precision, recall and F1 evaluation.

## 7.1 Existing Metrics

Preserve:

- Precision.
- Recall.
- F1 score.

Definitions:

```text
Precision = TP / (TP + FP)

Recall = TP / (TP + FN)

F1 = 2 * Precision * Recall / (Precision + Recall)
```

Handle zero denominators explicitly and document the selected convention.

## 7.2 Additional Metrics

Consider introducing:

### False Positive Rate

Measures incorrect findings relative to clean negative cases.

### Detection Rate

Measures the proportion of known defects successfully detected.

### Severity Accuracy

Checks whether predicted severity matches expected severity.

### Localization Accuracy

Measures whether the evaluator identifies the correct affected file or code location.

### Schema Conformance Rate

Measures valid structured responses.

### Evaluation Reliability

Tracks:

- Evaluator execution failures.
- Invalid responses.
- Timeout rate.
- Retry rate.

Keep primary quality metrics separate from operational reliability metrics.

Do not combine all metrics into one score without documenting the aggregation methodology.

---

# 8. Solution 4: Nightly CI Quality Suite

Priority: P1.

Estimated size: Medium.

Introduce automated nightly quality evaluation.

## 8.1 CI Workflow

Use the repository's existing CI platform.

If GitHub Actions is already used, create:

`.github/workflows/nightly-quality-evaluation.yml`

Example workflow structure:

```yaml
name: Nightly AI Quality Evaluation

on:
  schedule:
    - cron: "30 18 * * *"

  workflow_dispatch:

permissions:
  contents: read

jobs:
  quality-evaluation:
    runs-on: ubuntu-latest

    steps:
      - name: Checkout
        uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.11"

      - name: Install dependencies
        run: |
          pip install -r requirements.txt

      - name: Run quality suite
        run: |
          python benchmark_quality_suite.py \
            --fixtures-only \
            --fail-on-threshold

      - name: Upload evaluation report
        if: always()
        uses: actions/upload-artifact@v4
        with:
          name: quality-evaluation-report
          path: reports/
```

Adapt commands and dependency installation to the actual repository.

The schedule above uses UTC. Select the appropriate schedule based on project requirements.

## 8.2 CI Execution Rules

Nightly workflow:

- Runs recorded fixture evaluations.
- Runs schema conformance checks.
- Runs false-positive checks.
- Calculates precision, recall and F1.
- Evaluates all configured quality gates.
- Generates a machine-readable report.
- Uploads reports even when evaluation fails.

Pull request workflow:

- Run lightweight unit tests.
- Run gate logic tests.
- Run fixture validation tests.
- Avoid live LLM calls.
- Avoid expensive benchmark execution.

Optional live provider evaluation:

- Must be separately configured.
- Must be opt-in.
- Must use protected secrets.
- Must have usage limits.
- Must never be required for ordinary pull request validation.

## 8.3 CI Failure Behaviour

If a mandatory threshold fails:

- Exit code must be non-zero.
- Workflow must report failure.
- Evaluation report must still be generated.
- Failed metrics must be clearly identified.

Never allow report generation failure to hide an earlier benchmark failure.

---

# 9. Solution 5: Mini SWE-bench Evaluation Harness

Priority: P3.

Estimated size: Large.

This is a separate but highly valuable enhancement.

The objective is to evaluate the complete autonomous software development platform using real-world coding tasks.

## 9.1 Objective

Build a benchmark containing 20–30 small real-world software engineering issues.

Each task should represent a reproducible software development problem.

The agent must:

1. Understand the issue.
2. Inspect the repository.
3. Identify relevant files.
4. Develop a solution.
5. Modify code.
6. Execute tests.
7. Validate the fix.
8. Produce a final result.

The benchmark must evaluate actual task completion, not just LLM response quality.

## 9.2 Task Dataset Structure

Suggested directory:

```text
evaluation/
  mini_swebench/
    dataset/
      manifest.json

      tasks/
        TASK-001/
          metadata.json
          issue.md
          reproduction_test.py
          regression_test.py

        TASK-002/
          metadata.json
          issue.md
          reproduction_test.py
          regression_test.py

    harness/
      runner.py
      task_loader.py
      workspace_manager.py
      test_executor.py
      result_collector.py
      metrics.py

    reports/
```

Adapt the structure to the current workspace and repository conventions.

## 9.3 Task Metadata

Example:

```json
{
  "task_id": "TASK-001",
  "repository": "example-project",
  "base_commit": "COMMIT_SHA",
  "issue_title": "Fix incorrect null handling",
  "issue_description": "The application crashes when optional input is null.",
  "category": "bug_fix",
  "difficulty": "easy",
  "language": "python",
  "reproduction_test": "reproduction_test.py",
  "regression_test": "regression_test.py",
  "expected_files": [
    "src/handler.py"
  ]
}
```

Every task must use a pinned base commit.

Do not use a moving branch as the benchmark baseline.

## 9.4 Task Selection

Select 20–30 tasks from permissively licensed repositories.

Suggested categories:

- Bug fixes.
- Incorrect API behaviour.
- Validation errors.
- Exception handling.
- Data processing defects.
- Performance improvements.
- Small refactoring tasks.
- Test-related defects.

Prefer tasks that:

1. Have clear issue descriptions.
2. Have reproducible failures.
3. Have deterministic expected outcomes.
4. Can be evaluated automatically.
5. Have manageable execution requirements.

Record repository license, source attribution, commit SHA and task provenance.

Do not copy entire repositories unnecessarily.

## 9.5 Evaluation Lifecycle

```text
          Load Benchmark Task
                   |
                   v
           Prepare Workspace
                   |
                   v
           Read Issue Description
                   |
                   v
          Agent Executes Task
                   |
                   v
           Collect Code Changes
                   |
                   v
           Run Reproduction Test
                   |
                   v
           Run Regression Tests
                   |
                   v
          Evaluate Patch Quality
                   |
                   v
            Store Results
```

## 9.6 Workspace Isolation

Every task must execute in an isolated environment.

Requirements:

- Separate workspace per task.
- Pinned repository commit.
- No access to unrelated tasks.
- No access to production credentials.
- Restricted network access.
- CPU and memory limits.
- Execution timeout.
- Cleanup after completion.

Reuse existing secure workspace and sandbox components where appropriate.

Do not execute benchmark-generated code directly on the API host.

## 9.7 Test Execution Strategy

Each task must have two major test stages.

### Stage A: Reproduction Test

Purpose:

Verify that the original issue exists.

Expected behaviour:

- Test fails on the unmodified baseline.
- Test passes after a correct fix.

### Stage B: Regression Test

Purpose:

Verify that the fix does not break existing functionality.

Expected behaviour:

- Existing tests pass after the agent's changes.
- New functionality behaves correctly.

Do not accept a task as solved merely because the agent claims it fixed the issue.

## 9.8 Benchmark Metrics

Measure:

### Primary Metric: Pass@1

Percentage of tasks solved successfully in one attempt.

```text
Pass@1 =
Successfully Solved Tasks / Total Valid Tasks
```

### Additional Metrics

- Reproduction test success.
- Regression test success.
- Patch acceptance rate.
- Task completion rate.
- Average execution time.
- Average LLM token consumption.
- Tool-call count.
- Retry count.
- Test failure rate.
- Security policy violations.

Track infrastructure failures separately from agent failures.

Do not count an infrastructure failure as a normal agent failure without reporting the distinction.

## 9.9 Benchmark Report

Generate a report containing:

- Benchmark version.
- Agent version.
- Model configuration.
- Task count.
- Successfully solved tasks.
- Failed tasks.
- Pass@1.
- Average execution time.
- Token consumption.
- Failure categories.
- Test execution results.
- Patch information.

Allow comparison between different agent versions and configurations.

---

# 10. Research and External Framework Evaluation

Evaluate external frameworks before introducing dependencies.

## 10.1 RAGAS

Purpose:

Evaluate retrieval-augmented generation quality.

Potential metrics:

- Faithfulness.
- Answer relevancy.
- Context precision.
- Context recall.

Decision:

Consider RAGAS for a future extension of `benchmark_rag.py`.

Do not replace existing deterministic tests with LLM-based evaluation.

## 10.2 promptfoo

Purpose:

- Prompt evaluation.
- Regression testing.
- Model comparison.
- Adversarial testing.

Decision:

Evaluate whether it can complement existing fixture-based tests.

Avoid duplicating the existing evaluator unnecessarily.

## 10.3 DeepEval

Purpose:

- LLM evaluation.
- Test-driven evaluation.
- Custom metrics.
- Regression evaluation.

Decision:

Assess whether selected evaluation metrics provide meaningful additional value.

## 10.4 Langfuse

Purpose:

- Dataset management.
- Experiment tracking.
- Evaluation history.
- Model comparison.

Decision:

Consider it as an optional future integration.

Do not make the existing benchmark system dependent on an external observability platform.

## 10.5 SWE-bench

Purpose:

Evaluate autonomous software engineering agents against real repository issues.

Decision:

Use SWE-bench as a reference for the Mini SWE-bench architecture.

Start with 20–30 manageable tasks rather than attempting the complete SWE-bench dataset.

## Research Constraints

For every framework:

1. Inspect its current documentation.
2. Verify license.
3. Identify maintenance status.
4. Inspect integration complexity.
5. Identify dependency requirements.
6. Evaluate overlap with existing functionality.
7. Document adopt/reject/defer decision.

Do not install every framework simply because it is available.

---

# 11. Testing Strategy

Testing must be implemented alongside every phase.

## 11.1 Gate Tests

Mandatory:

- Above threshold.
- Equal to threshold.
- Below threshold.
- Missing metric.
- Invalid metric.
- NaN and infinity.
- Minimum comparison.
- Maximum comparison.
- Invalid operator.
- Multiple mandatory metrics.
- Empty results.

## 11.2 Fixture Tests

Test:

- Fixture loading.
- Fixture schema validation.
- Duplicate fixture detection.
- Missing expected results.
- Category filtering.
- False-positive evaluation.
- Defect detection.
- Precision and recall calculations.

## 11.3 CI Tests

Verify:

- Workflow syntax.
- Fixture-only execution.
- No API calls in PR jobs.
- Correct non-zero exit code.
- Report generation after failure.
- Artifact upload.
- Reproducibility.

## 11.4 Mini SWE-bench Tests

Test:

- Task loading.
- Commit checkout.
- Workspace isolation.
- Reproduction test.
- Regression test.
- Timeout handling.
- Agent crash handling.
- Result collection.
- Cleanup.
- Benchmark aggregation.

---

# 12. Documentation Requirements

All important implementation decisions must be documented.

Create or update documentation following existing repository conventions.

### Document 1: Existing Evaluation Architecture

File:

`AI_QUALITY_EVALUATION_ARCHITECTURE.md`

Include:

- Existing evaluator design.
- Existing benchmark scripts.
- Metric calculations.
- Fixture architecture.
- Current limitations.

### Document 2: Benchmark Gate Design

File:

`BENCHMARK_GATING_DESIGN.md`

Include:

- Previous comparison bug.
- Root cause.
- Correct comparison logic.
- Threshold configuration.
- Missing metric behaviour.
- Aggregate gate behaviour.
- Test cases.

### Document 3: CI Quality Evaluation

File:

`NIGHTLY_QUALITY_EVALUATION.md`

Include:

- Workflow design.
- Execution schedule.
- PR vs nightly responsibilities.
- Fixture-only execution.
- Failure behaviour.
- Artifact storage.

### Document 4: Mini SWE-bench Architecture

File:

`MINI_SWE_BENCH_DESIGN.md`

Include:

- Task selection.
- Dataset structure.
- Task metadata.
- Workspace isolation.
- Agent execution lifecycle.
- Test execution.
- Metrics.
- Reporting.

### Document 5: Framework Research

File:

`EVALUATION_FRAMEWORK_RESEARCH.md`

Include:

- RAGAS.
- promptfoo.
- DeepEval.
- Langfuse.
- SWE-bench.
- License verification.
- Integration assessment.
- Adopt/reject/defer decisions.

### Document 6: Implementation and Testing Report

File:

`AI_EVALUATION_IMPLEMENTATION_REPORT.md`

Include:

- Files created.
- Files modified.
- Bugs fixed.
- Tests added.
- Tests executed.
- Results.
- Known limitations.
- Future improvements.

Do not overwrite unrelated documentation.

---

# 13. Implementation Phases

## Phase 0: Repository Audit

Priority: P0.

Tasks:

1. Inspect `ai_quality_evaluator.py`.
2. Inspect `benchmark_quality_suite.py`.
3. Inspect `benchmark_rag.py`.
4. Locate every threshold comparison.
5. Locate PASS/FAIL calculation.
6. Inspect existing fixtures.
7. Inspect CI workflows.
8. Identify existing test coverage.
9. Identify duplicated evaluation logic.

Deliverable:

`AI_QUALITY_EVALUATION_ARCHITECTURE.md`

Complete this phase before making structural changes.

## Phase 1: Fix Benchmark Gate

Priority: P0.

Tasks:

1. Identify the exact comparison bug.
2. Implement correct comparison direction.
3. Centralize threshold definitions.
4. Implement mandatory metric enforcement.
5. Handle missing and invalid values.
6. Add regression tests.
7. Run existing evaluation tests.

Deliverable:

Verified strict quality gate.

This phase must be completed before proceeding.

## Phase 2: Expand Fixtures

Priority: P1.

Tasks:

1. Audit current fixtures.
2. Define fixture schema.
3. Add categorized clean-code fixtures.
4. Add defect fixtures.
5. Add security fixtures.
6. Add performance fixtures.
7. Add false-positive traps.
8. Validate fixture quality.
9. Update evaluation reports.

Deliverable:

Expanded reproducible fixture suite.

## Phase 3: Nightly CI

Priority: P1.

Tasks:

1. Inspect existing CI architecture.
2. Implement nightly workflow.
3. Add fixture-only execution.
4. Configure strict benchmark failure.
5. Generate machine-readable reports.
6. Upload reports as artifacts.
7. Test manual workflow dispatch.
8. Verify failure propagation.

Deliverable:

Automated nightly quality evaluation.

## Phase 4: Mini SWE-bench Research and Design

Priority: P3.

Tasks:

1. Research SWE-bench architecture.
2. Identify suitable permissively licensed repositories.
3. Select initial candidate issues.
4. Verify reproduction steps.
5. Define task metadata.
6. Define workspace isolation.
7. Design test execution.
8. Define benchmark metrics.

Deliverable:

`MINI_SWE_BENCH_DESIGN.md`

## Phase 5: Mini SWE-bench Implementation

Priority: P3.

Tasks:

1. Implement task loader.
2. Implement dataset validation.
3. Implement workspace preparation.
4. Integrate existing autonomous agent execution.
5. Implement test executor.
6. Implement result collector.
7. Implement metrics calculator.
8. Generate benchmark reports.
9. Add initial 20–30 tasks.
10. Validate benchmark reproducibility.

Deliverable:

Working end-to-end agent evaluation harness.

## Phase 6: Framework Assessment

Priority: P2/P3.

Tasks:

1. Evaluate RAGAS.
2. Evaluate promptfoo.
3. Evaluate DeepEval.
4. Evaluate Langfuse.
5. Evaluate SWE-bench integration options.
6. Document license and dependency implications.
7. Select only genuinely useful additions.

Deliverable:

Framework adoption recommendations.

## Phase 7: Final Audit and Documentation

Tasks:

1. Run complete test suite.
2. Verify gate behaviour.
3. Verify CI execution.
4. Verify fixture reproducibility.
5. Verify Mini SWE-bench execution if implemented.
6. Review security boundaries.
7. Update documentation.
8. Produce final implementation report.

Deliverable:

Complete AI quality evaluation infrastructure.

---

# 14. Important Engineering Constraints

Antigravity must follow these rules.

1. Do not replace the existing AI quality evaluator unnecessarily.
2. Do not introduce duplicate metric calculators.
3. Do not allow below-threshold metrics to PASS.
4. Do not let average scores override mandatory metric failures.
5. Do not treat missing metrics as successful results.
6. Do not use live LLM calls in ordinary PR fixture tests.
7. Do not create duplicate fixtures to inflate evaluation size.
8. Do not count infrastructure failures as successful agent executions.
9. Do not trust agent-generated success messages.
10. Do not accept a patch without running actual tests.
11. Do not execute untrusted benchmark code on the production API host.
12. Do not expose API credentials to benchmark workspaces.
13. Do not introduce external evaluation frameworks without assessing their value.
14. Do not change existing quality thresholds without documenting the decision.
15. Preserve existing benchmark and reporting compatibility.

---

# 15. Definition of Done

## P0 — Mandatory

- [ ] Root cause of benchmark gating bug identified.
- [ ] Correct threshold comparisons implemented.
- [ ] Equality boundary tested.
- [ ] Below-threshold values always FAIL.
- [ ] Missing and invalid metrics cannot PASS.
- [ ] Aggregate quality gate works correctly.
- [ ] Regression tests pass.

## P1 — Quality Infrastructure

- [ ] Fixture suite expanded.
- [ ] Fixture categories established.
- [ ] False-positive evaluation improved.
- [ ] Defect evaluation improved.
- [ ] CI nightly workflow implemented.
- [ ] PR runs avoid live LLM calls.
- [ ] Reports generated and uploaded.
- [ ] CI failure propagates correctly.

## P3 — Agent Evaluation

- [ ] Mini SWE-bench architecture documented.
- [ ] 20–30 tasks selected.
- [ ] Task commits pinned.
- [ ] Reproduction tests verified.
- [ ] Regression tests implemented.
- [ ] Isolated execution implemented.
- [ ] Agent integration completed.
- [ ] Pass@1 calculated.
- [ ] Benchmark reports generated.

## Documentation

- [ ] Existing architecture documented.
- [ ] Gate design documented.
- [ ] CI workflow documented.
- [ ] Mini SWE-bench documented.
- [ ] External framework research documented.
- [ ] Final implementation report completed.

---

# 16. Final Instructions to Antigravity 3.8 Flash

Act as a senior AI evaluation engineer, QA architect and autonomous-agent benchmarking researcher.

Do not start by rewriting the benchmark infrastructure.

First inspect the existing repository and understand how the current evaluation system works.

For every implementation phase, follow this process:

1. Explain what already exists.
2. Identify the exact problem.
3. Identify the affected files and functions.
4. Research the relevant evaluation methodology.
5. Explain the proposed solution.
6. Document the implementation design.
7. Implement incrementally.
8. Add automated tests.
9. Execute the tests.
10. Record actual results.
11. Update the technical documentation.

### Execution discipline

**First complete Phase 0 and Phase 1.**

The benchmark-gating bug is P0 and must be fixed immediately.

Do not begin Mini SWE-bench implementation before the existing quality gate is reliable.

After completing Phase 1, provide:

- Root cause analysis.
- Before/after comparison.
- Files modified.
- Tests added.
- Actual test results.
- Confirmation that below-threshold metrics fail.

Then continue with fixture expansion and CI automation.

Treat Mini SWE-bench as a separate research and implementation milestone.

### Final deliverable

The final output must contain:

1. Existing vs updated architecture.
2. Root cause of the benchmark gate bug.
3. All implemented fixes.
4. Fixture expansion summary.
5. CI workflow details.
6. Mini SWE-bench architecture and results.
7. Files created and modified.
8. Test execution report.
9. Framework research decisions.
10. Remaining technical debt.

**Final objective:**

Build a reliable, reproducible and automated evaluation system that measures AI code quality, prevents quality regressions and objectively determines whether the autonomous software development agent can solve real-world software engineering tasks.