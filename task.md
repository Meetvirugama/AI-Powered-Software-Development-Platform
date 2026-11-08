# TASK: Upgrade Test Generation into an Execution-Verified, Coverage-Guided Automated Testing System

## 1. YOUR ROLE

Act as a Senior Software Architect, Senior Python Backend Engineer, AI/LLM Engineer, Test Automation Engineer, Application Security Engineer and QA Engineer.

You are working on my existing project:

**AI-Powered Software Development Platform**

Your task is to upgrade the existing Test Generation feature into a reliable, execution-verified, coverage-guided automated testing system.

You must work directly inside the existing repository.

Do not create a separate demo project.
Do not create duplicate implementations.
Do not unnecessarily rewrite existing architecture.
Do not remove existing working functionality.
Do not assume that features are missing without inspecting the actual implementation.

I am using Antigravity 3.8 Flash. Therefore:

- Work in small, clearly defined phases.
- Inspect the code before modifying it.
- Keep changes modular.
- Avoid unnecessary token consumption.
- Reuse existing utilities and infrastructure.
- Run targeted tests after each implementation phase.
- Document all architectural and implementation decisions.
- Never report a feature as completed without testing it.

Your goal is production-quality implementation, not just a prototype.

---

# 2. PRIMARY OBJECTIVE

Currently, our Test Generation system performs:

1. Framework detection.
2. Test requirement discovery.
3. Test scenario planning.
4. LLM-based test generation.
5. Syntax validation.
6. Reserved-file and safety checks.

However, generated tests are not sufficiently verified.

We want to introduce:

1. Actual test execution in an isolated sandbox.
2. Three-consecutive-run stability validation.
3. Baseline and post-generation coverage measurement.
4. Coverage-guided iterative test generation.
5. Mutation testing for offline quality evaluation.
6. Complete Vitest support.
7. Correct benchmark gates.
8. Detailed test verification reports.
9. Comprehensive documentation inside the existing Docs directory.

The final workflow should be:

Repository Analysis
→ Framework Detection
→ Requirement Discovery
→ Test Generation
→ Static Validation
→ Sandbox Execution
→ Stability Validation
→ Coverage Analysis
→ Coverage-Guided Iteration
→ Final Verification
→ Quality Report

Mutation testing should be an additional offline evaluation workflow, not a mandatory step for every user request.

---

# 3. MANDATORY FIRST STEP: COMPLETE EXISTING CODEBASE AUDIT

Before implementing anything, inspect the actual repository.

Do not immediately start writing code.

## 3.1 Inspect these existing files

### Test generation

- backend/app/services/test_generation_orchestrator.py
- backend/ai/services/test_generation_service.py
- backend/app/services/test_generation_report.py
- backend/app/services/test_requirement_orchestrator.py
- backend/scanner/test_requirement_discovery.py
- backend/scanner/framework_detector.py
- backend/ai/prompts/test_generation_system.txt

### Sandbox infrastructure

- backend/sandbox/__init__.py
- backend/sandbox/workspace_manager.py
- backend/sandbox/test_runner.py
- backend/sandbox/command_runner.py
- backend/sandbox/path_guard.py
- backend/sandbox/resource_monitor.py
- backend/sandbox/constants.py
- backend/sandbox/exceptions.py
- backend/sandbox/tool_policy_bridge.py
- backend/sandbox/diff_verifier.py

### Existing tests

Inspect all relevant tests, especially:

- backend/tests/test_framework_detector.py
- backend/tests/test_test_generation_comprehensive.py
- backend/tests/test_test_generation_day4.py
- backend/tests/test_test_generation_plan_matrix.py
- backend/tests/test_feature_quality_benchmarks.py
- backend/tests/test_adversarial_sandbox.py

### Frontend

Inspect:

- frontend/src/components/explorer/TestGenerationView.tsx
- Related API clients.
- Test generation response schemas.
- Existing report and history components.

### Documentation

Inspect:

- Docs/quality_benchmark_report.md
- Docs/testing/test_generation_feature_testing_result.md
- Docs/workspace_sandbox_architecture_audit.md
- Docs/engineering/11_testing_qa.md
- Docs/engineering/05_system_architecture.md
- Docs/README.md

## 3.2 Verify existing implementation

There are potentially outdated assumptions in earlier audits.

For example:

- framework_detector.py already declares Vitest as a supported framework.
- backend/sandbox/ already contains a substantial execution and workspace infrastructure.
- The existing quality report has a benchmark-gate inconsistency.

Verify these facts against the actual code.

For each capability, classify it as:

- FULLY IMPLEMENTED
- PARTIALLY IMPLEMENTED
- IMPLEMENTED BUT NOT INTEGRATED
- MISSING
- IMPLEMENTED BUT INCORRECT
- NEEDS SECURITY IMPROVEMENT

Do not implement an already-working capability again.

## 3.3 Create the initial audit document

Create:

Docs/test-generation/00_EXISTING_IMPLEMENTATION_AUDIT.md

Include:

1. Existing architecture.
2. Existing file responsibilities.
3. Current execution flow.
4. Existing sandbox capabilities.
5. Existing framework support.
6. Existing coverage capabilities.
7. Existing benchmark logic.
8. Existing frontend behavior.
9. Missing capabilities.
10. Security gaps.
11. Integration dependencies.
12. Exact files requiring modifications.
13. New files required.
14. Risks and compatibility concerns.
15. Implementation roadmap.

For every identified issue, include the actual file path and relevant function/class.

Do not fabricate implementation details.

After creating the audit, use it as the implementation reference.

---

# 4. FEATURE 1: EXECUTION-VERIFIED TEST GENERATION

Priority: HIGH

This is the most important improvement.

## 4.1 Existing problem

Currently, generated test files can pass syntax validation without actually working.

Examples of undetected problems:

- Incorrect imports.
- Invalid module paths.
- Incorrect fixtures.
- Wrong assertions.
- Missing dependencies.
- Runtime exceptions.
- Tests that do not exercise intended functionality.

Syntax validation is not sufficient.

## 4.2 Required implementation

Implement an execution-and-filter pipeline.

Every generated test must go through:

Stage 1: Static validation.
Stage 2: Sandbox execution.
Stage 3: Stability validation.
Stage 4: Coverage validation.
Stage 5: Final classification.

Only tests satisfying all mandatory verification conditions should be labelled VERIFIED.

## 4.3 Stage 1: Static validation

Preserve existing validations.

Python:
- AST parsing.
- Import and syntax checks where practical.
- Existing reserved-file checks.
- Existing dangerous-pattern checks.

JavaScript/TypeScript:
- Actual parser/compiler validation.
- TypeScript compatibility where configured.
- Framework-specific validation.

Do not rely only on bracket or delimiter balance for JavaScript.

Never generate or overwrite:

- conftest.py
- pytest.ini
- Existing framework configuration.
- Startup files.
- Existing test configuration.
- Other protected files.

Preserve existing safety policies and extend them when necessary.

## 4.4 Stage 2: Sandbox execution

Reuse the existing backend/sandbox infrastructure.

Do not create another sandbox manager if the current one can safely support this workflow.

Inspect whether the current test_runner.py and command_runner.py can execute generated tests safely.

If changes are necessary, extend existing components.

Requirements:

- Execute only inside an isolated temporary workspace.
- Never execute generated tests directly on the main backend server.
- Never modify the original repository.
- Capture stdout and stderr.
- Capture exit codes.
- Capture execution duration.
- Capture passed, failed, skipped and errored test counts.
- Capture timeout information.
- Preserve execution logs for reporting.
- Clean temporary workspaces after execution.
- Handle cleanup failures safely.

Use the repository's existing workspace lifecycle and path validation mechanisms.

## 4.5 Sandbox security requirements

Generated test code is untrusted executable code.

Implement or verify the following:

1. No access to production secrets.
2. No access to backend environment variables containing credentials.
3. Network disabled by default.
4. CPU limits.
5. Memory limits.
6. Disk limits.
7. Execution timeouts.
8. Process count limits where supported.
9. Filesystem isolation.
10. Path traversal protection.
11. Symlink escape protection.
12. Safe temporary file handling.
13. No privileged container execution.
14. Safe cleanup.
15. Dependency installation restrictions.

Do not allow generated tests to access:

- Production databases.
- Production Redis.
- Cloud credentials.
- GitHub tokens.
- API keys.
- SSH credentials.
- Host filesystem secrets.

Do not automatically install arbitrary packages requested by generated tests.

Prefer already-installed and locked repository dependencies.

If installation is required, use a controlled dependency policy.

Do not enable unrestricted network access to make a failing test pass.

Evaluate whether existing Docker isolation is sufficient for the threat model. Consider gVisor or Firecracker if stronger isolation is necessary.

Document the actual security guarantees and limitations.

## 4.6 Stage 3: Stability validation

Run the generated test suite three consecutive times.

Configuration:

MAX_STABILITY_RUNS = 3

Expected classification:

3/3 PASS:
- Stable candidate.

2/3 PASS:
- Unstable candidate.

1/3 or 0/3 PASS:
- Failed candidate.

Capture:

- Each run's result.
- Duration.
- Failure information.
- Error messages.
- Timeout information.

Do not silently retry failures and then mark the test verified.

Do not confuse stability retries with LLM generation iterations.

Keep these as separate configurations.

Example:

MAX_STABILITY_RUNS = 3
MAX_GENERATION_ROUNDS = 3

Generation rounds mean initial generation plus two additional rounds.

Stability runs mean repeated execution of the same generated test set.

Where practical, control randomness, environment state and test ordering to improve reproducibility.

Do not claim that three successful runs mathematically prove non-flakiness.

## 4.7 Stage 4: Final classification

Implement clear result categories:

VERIFIED:
- Static validation passed.
- Execution passed.
- All three stability runs passed.
- Coverage requirement satisfied.

UNVERIFIED:
- Test generated successfully.
- But one or more verification conditions were not satisfied.

REJECTED:
- Unsafe test.
- Protected file modification.
- Invalid or prohibited execution behavior.

EXECUTION_ERROR:
- Infrastructure failure prevented reliable verification.

Important:

Do not classify an infrastructure error as a failed test assertion.

Differentiate between:
- Actual test failure.
- Sandbox failure.
- Dependency failure.
- Execution timeout.
- Infrastructure error.

Do not silently discard unverified tests. Preserve them in a separate result section with reasons and warnings.

---

# 5. FEATURE 2: COVERAGE MEASUREMENT

Priority: HIGH

## 5.1 Problem

A passing test does not necessarily test meaningful functionality.

We need to know whether generated tests increase coverage.

## 5.2 Required implementation

Implement a dedicated coverage service.

Suggested file:

backend/app/services/test_coverage_service.py

Modify this name if an existing architecture convention is better.

The service should support:

Python:
- coverage.py
- pytest-cov where compatible.

JavaScript:
- Jest coverage.
- Vitest coverage.

Support:
- Line coverage.
- Branch coverage.
- Function coverage where available.
- Targeted source-file coverage.

Do not assume every repository has the same coverage configuration.

Respect existing coverage settings and source exclusions.

## 5.3 Baseline measurement

Before adding generated tests:

1. Create an isolated repository workspace.
2. Execute the appropriate existing baseline test suite.
3. Collect coverage.
4. Record the baseline.
5. Record pre-existing test failures separately.

Then add generated tests in the isolated workspace.

Execute the combined suite.

Collect post-generation coverage.

Calculate:

Coverage Gain = Post-generation Coverage - Baseline Coverage

Example:

Baseline line coverage: 40%
Post-generation line coverage: 65%

Coverage gain: +25 percentage points.

## 5.4 Critical correctness requirement

Coverage must be attributable to generated tests.

Do not allow existing tests to make generated tests appear more useful than they actually are.

Where possible, implement coverage comparison using:

- Baseline execution.
- Generated-test-only execution.
- Combined execution.

Track which new lines and branches were exercised by generated tests.

Account for existing test failures and coverage collection errors.

A generated test that does not increase coverage should not automatically be called useless.

For example, it may add a valuable assertion to already-covered code.

However, under the initial strict verification policy, it must remain UNVERIFIED if the mandatory coverage-gain condition is not met.

Expose the reason in the report.

## 5.5 Coverage reporting

Return structured metrics:

- Baseline line coverage.
- Final line coverage.
- Line coverage gain.
- Baseline branch coverage.
- Final branch coverage.
- Branch coverage gain.
- Newly covered lines.
- Newly covered branches.
- Coverage collection status.
- Unsupported coverage capabilities.

Never invent coverage values.

Never treat missing coverage data as 0% without distinguishing collection failure.

---

# 6. FEATURE 3: COVERAGE-GUIDED ITERATIVE GENERATION

Priority: MEDIUM-HIGH

Research inspiration: CoverUp (P-11).

## 6.1 Problem

The current system generates tests in a single attempt.

This can miss important branches and edge cases.

## 6.2 Required implementation

Introduce a feedback loop.

Flow:

1. Generate initial tests.
2. Execute generated tests.
3. Collect coverage.
4. Identify uncovered executable lines and branches.
5. Map uncovered code to source functions/classes.
6. Convert uncovered code into missing test requirements.
7. Send only relevant uncovered context to the LLM.
8. Generate additional targeted tests.
9. Execute and verify the additional tests.
10. Merge valid results.
11. Produce final report.

## 6.3 Iteration limits

Use:

MAX_GENERATION_ROUNDS = 3

This means:

- Round 1: Initial generation.
- Round 2: First improvement.
- Round 3: Second improvement.

Do not exceed this limit.

## 6.4 LLM prompt improvements

The LLM must receive:

- Relevant source code.
- Existing generated tests.
- Existing repository tests when relevant.
- Uncovered lines.
- Uncovered branches.
- Existing fixtures.
- Detected framework.
- Existing imports.
- Previously failed test information.
- Already-covered scenarios.

The LLM must generate only missing tests.

Do not regenerate the entire test suite unnecessarily.

Prevent duplicate test cases.

Preserve traceability between:

Requirement → Generated Test → Source Function → Coverage Result.

## 6.5 Stop conditions

Stop iterative generation when:

- No meaningful uncovered target remains.
- Coverage stops improving.
- Maximum rounds are reached.
- Generation budget is exhausted.
- Sandbox execution fails due infrastructure issues.
- The framework cannot provide reliable coverage data.

Do not continue spending LLM tokens without a clear improvement opportunity.

---

# 7. FEATURE 4: MUTATION TESTING

Priority: MEDIUM / OPTIONAL FOR USER REQUESTS

Research inspiration: MuTAP (P-12).

Mutation testing should initially be implemented as an offline evaluation and benchmarking capability.

Do not run mutation testing on every user request.

## 7.1 Purpose

Coverage tells us whether code was executed.

Mutation testing helps evaluate whether tests detect intentional code changes.

Example:

Original:

def is_adult(age):
    return age >= 18

Mutation:

def is_adult(age):
    return age > 18

A test that only checks age 20 will not detect this mutation.

A test checking age 18 should detect it.

## 7.2 Python

Investigate and integrate mutmut.

## 7.3 JavaScript/TypeScript

Investigate and integrate Stryker.

## 7.4 Required metrics

Track:

- Total mutants.
- Killed mutants.
- Survived mutants.
- Equivalent mutants where identified.
- Timeout mutants.
- Mutation score.
- Execution duration.

Formula:

Mutation Score =
Killed Mutants / Valid Non-Equivalent Mutants × 100

Do not count equivalent or invalid mutants in the denominator.

Document limitations.

## 7.5 Evaluation strategy

Use a controlled benchmark repository or fixture suite.

Compare:

- Existing tests.
- Generated tests.
- Combined tests.

This will help determine whether generated tests improve defect detection.

Keep mutation execution separate from the normal user workflow.

---

# 8. FEATURE 5: COMPLETE VITEST SUPPORT

Priority: HIGH

Important: The existing framework detector already declares Vitest in its supported framework set.

Do not blindly add Vitest again.

Audit the entire end-to-end implementation.

Verify:

1. Framework detection.
2. Manifest parsing.
3. Config-file discovery.
4. Test command selection.
5. Test file naming.
6. Test requirement discovery.
7. LLM generation prompts.
8. Imports and mocking APIs.
9. Test execution.
10. Coverage collection.
11. Frontend response rendering.

Vitest support is complete only when all these stages work.

## 8.1 Detection

Inspect:

- package.json
- vitest.config.js
- vitest.config.ts
- vitest.config.mjs
- Existing Vitest imports.
- Existing test files.
- Relevant workspace configuration.

Handle ambiguous configurations carefully.

Do not incorrectly identify Jest and Vitest when both are installed.

Use actual project scripts and configurations where appropriate.

## 8.2 Generation

Generate framework-appropriate code using:

- describe()
- it()
- test()
- expect()
- vi.fn()
- vi.mock()
- beforeEach()
- afterEach()

Use the repository's existing conventions.

Do not blindly reuse Jest-specific mocking APIs.

## 8.3 Execution

Support the configured Vitest command.

Typical example:

npx vitest run

But prefer the repository's actual package-manager and script configuration.

Support:

- npm.
- pnpm.
- yarn.
- Existing lockfiles.

Do not arbitrarily change package managers.

## 8.4 Coverage

Use the repository's configured Vitest coverage provider.

Support V8 or Istanbul where compatible.

Do not overwrite the user's existing coverage configuration.

---

# 9. FEATURE 6: BENCHMARK GATE CORRECTION

Priority: P0

Inspect:

Docs/quality_benchmark_report.md

backend/tests/test_feature_quality_benchmarks.py

Existing benchmark implementation.

The existing report shows:

Syntax validity: 75%
Target: >=66%

Assertion presence: 50%
Target: >=66%

Yet both are marked PASS.

This is inconsistent.

## 9.1 Required correction

Implement a reliable threshold evaluator.

Example:

def evaluate_metric(value, threshold):
    return {
        "value": value,
        "threshold": threshold,
        "status": "PASS" if value >= threshold else "FAIL"
    }

Overall mandatory quality gate:

overall_pass = all(
    mandatory_metric.status == "PASS"
    for mandatory_metric in mandatory_metrics
)

## 9.2 Requirements

- Below target must FAIL.
- At target must PASS.
- Above target must PASS.
- Missing measurements must not silently PASS.
- Invalid benchmark data must be reported.
- Optional metrics must not accidentally become mandatory.
- Report generation must use actual evaluation results.

Distinguish:

HARD GATES:
Mandatory requirements.

QUALITY METRICS:
Measurements used to compare improvements.

Do not consider assertion presence sufficient proof of assertion correctness.

Update the benchmark report only using newly measured results.

Do not change historical results to make them appear successful.

---

# 10. FEATURE 7: TEST QUALITY REPORTING

Priority: HIGH

Improve the backend report and frontend TestGenerationView.tsx.

The user should clearly understand what happened to each generated test.

## 10.1 Required report information

### Summary

- Total generated tests.
- Verified tests.
- Unverified tests.
- Rejected tests.
- Execution errors.

### Framework

- Detected language.
- Detected framework.
- Package manager.
- Execution command.

### Static validation

- Syntax result.
- Import validation.
- Safety validation.

### Execution

- Total execution count.
- Passed.
- Failed.
- Skipped.
- Errors.
- Execution time.

### Stability

- Run 1.
- Run 2.
- Run 3.
- Final stability classification.

### Coverage

- Baseline line coverage.
- Final line coverage.
- Coverage improvement.
- Branch coverage.
- Newly covered lines and branches.

### Iterative generation

- Generation round count.
- Additional tests generated.
- Uncovered branches addressed.
- Stopping reason.

### Failure details

For every failed or unverified test:

- Test name.
- File path.
- Failure reason.
- Relevant error output.
- Suggested remediation.

## 10.2 Frontend requirements

Improve the existing TestGenerationView.tsx.

Do not redesign the entire platform.

Maintain the existing design system.

Add:

- Verification status.
- Execution summary.
- Stability indicator.
- Coverage comparison.
- Generation-round information.
- Expandable failure details.
- Separate VERIFIED and UNVERIFIED sections.

Never show an unverified test as verified.

Do not expose secrets or internal sensitive paths in user-visible logs.

Maintain compatibility with existing API consumers where possible.

---

# 11. FEATURE 8: EVALUATION AND TESTING

Priority: CRITICAL

Do not consider implementation complete just because the code compiles.

Build a comprehensive testing strategy.

## 11.1 Unit tests

Test:

- Framework detection.
- Vitest configuration detection.
- Static validation.
- Execution service.
- Stability validation.
- Coverage calculation.
- Coverage comparison.
- Iteration stopping conditions.
- Mutation metric calculation.
- Benchmark threshold evaluation.
- Final classification.

## 11.2 Integration tests

Test complete workflows:

Scenario A:
Valid Python pytest repository.

Scenario B:
Python unittest repository.

Scenario C:
JavaScript Jest repository.

Scenario D:
TypeScript Vitest repository.

Scenario E:
Repository with both Jest and Vitest dependencies.

Scenario F:
Repository with no existing test framework.

Scenario G:
Invalid generated syntax.

Scenario H:
Incorrect imports.

Scenario I:
Test with failing assertion.

Scenario J:
Flaky generated test.

Scenario K:
Passing test with no coverage improvement.

Scenario L:
Passing test with additional coverage.

Scenario M:
Sandbox timeout.

Scenario N:
Memory limit exceeded.

Scenario O:
Unsafe file access attempt.

Scenario P:
Path traversal attempt.

Scenario Q:
Attempt to access environment secrets.

Scenario R:
Existing baseline test failures.

Scenario S:
Coverage collection failure.

Scenario T:
Generation budget exhausted.

Scenario U:
Maximum iteration limit reached.

Scenario V:
Temporary workspace cleanup failure.

## 11.3 Regression tests

Run all relevant existing tests.

Do not delete existing tests just because they fail after your modifications.

Investigate whether the failure is:

- A regression.
- An existing failure.
- An environment issue.
- An outdated expectation.

Document the actual outcome.

## 11.4 Adversarial security tests

Specifically verify:

- ../ path traversal.
- Symlink escapes.
- Unauthorized file modifications.
- Secret access.
- Network access.
- Resource exhaustion.
- Command injection.
- Unsafe dependency installation.
- Background process persistence.
- Sandbox cleanup.

Never execute an adversarial test outside the isolated environment.

---

# 12. LLM COST AND PERFORMANCE CONTROL

We use limited/free LLM inference resources.

Do not introduce unnecessary API calls.

Implement:

1. Initial generation only once.
2. Maximum two additional generation rounds.
3. Targeted uncovered-code context.
4. Avoid duplicate generation.
5. Avoid resending the entire repository.
6. Reuse existing repository context.
7. Reuse existing cached analysis when valid.
8. Limit prompt size.
9. Track token usage.
10. Stop when no meaningful coverage improvement occurs.

Use the existing LLM provider architecture.

Do not introduce a new paid inference provider.

Do not hardcode Gemini API keys or model names in business logic.

Use the existing configuration and provider abstraction.

Track:

- Input tokens.
- Output tokens.
- Generation rounds.
- Estimated generation cost when provider data permits.
- Execution time separately from LLM time.

Do not confuse test execution retries with LLM generation retries.

---

# 13. ARCHITECTURAL DESIGN REQUIREMENTS

Keep the implementation modular.

Do not put every responsibility inside test_generation_orchestrator.py.

Inspect existing architecture before deciding final file names.

Potential responsibilities:

Framework adapters:
- Detection.
- Framework-specific execution.
- Framework-specific coverage.

Validation:
- Static validation.
- Execution validation.
- Stability validation.
- Coverage validation.

Services:
- Test execution.
- Coverage collection.
- Coverage comparison.
- Iterative generation.
- Quality reporting.

Evaluation:
- Mutation testing.
- Benchmark evaluation.

The orchestrator should coordinate these services rather than implement all their internal logic.

Use:

- Existing Pydantic schemas.
- Existing API conventions.
- Existing dependency injection.
- Existing logging.
- Existing error handling.
- Existing workspace lifecycle.
- Existing security policies.

Use typed interfaces.

Avoid circular imports.

Avoid duplicated execution logic.

Ensure backward compatibility with existing test-generation APIs.

Introduce schema changes carefully and document them.

---

# 14. DOCUMENTATION REQUIREMENTS — VERY IMPORTANT

I want ALL implementation documentation inside the existing:

Docs/

Create a dedicated documentation directory:

Docs/test-generation/

Do not create another documentation folder elsewhere.

Do not put major documentation files in the project root.

Keep existing Docs content intact.

Create the following documentation structure:

Docs/
└── test-generation/
    ├── README.md
    ├── 00_EXISTING_IMPLEMENTATION_AUDIT.md
    ├── 01_REQUIREMENTS_AND_SCOPE.md
    ├── 02_EXISTING_VS_PROPOSED_ARCHITECTURE.md
    ├── 03_SYSTEM_ARCHITECTURE.md
    ├── 04_EXECUTION_AND_VERIFICATION_FLOW.md
    ├── 05_SANDBOX_SECURITY_DESIGN.md
    ├── 06_FRAMEWORK_ADAPTERS.md
    ├── 07_COVERAGE_MEASUREMENT.md
    ├── 08_COVERAGE_GUIDED_ITERATION.md
    ├── 09_MUTATION_TESTING.md
    ├── 10_BENCHMARK_AND_EVALUATION.md
    ├── 11_API_AND_DATABASE_CHANGES.md
    ├── 12_FRONTEND_INTEGRATION.md
    ├── 13_IMPLEMENTATION_PLAN.md
    ├── 14_TESTING_STRATEGY.md
    ├── 15_SECURITY_AND_THREAT_MODEL.md
    ├── 16_PERFORMANCE_AND_COST_CONTROL.md
    ├── 17_DEPLOYMENT_AND_CONFIGURATION.md
    ├── 18_TROUBLESHOOTING.md
    ├── 19_IMPLEMENTATION_CHANGELOG.md
    ├── 20_IMPLEMENTATION_TEST_REPORT.md
    ├── 21_KNOWN_LIMITATIONS.md
    ├── diagrams/
    │   ├── existing_architecture.mmd
    │   ├── proposed_architecture.mmd
    │   ├── execution_sequence.mmd
    │   ├── coverage_iteration.mmd
    │   ├── sandbox_security.mmd
    │   └── verification_state_machine.mmd
    └── research/
        ├── README.md
        ├── P10_TESTGEN_LLM.md
        ├── P11_COVERUP.md
        ├── P12_MUTAP.md
        ├── P13_TESTPILOT.md
        └── TOOLS_AND_LICENSES.md

Adjust this structure if some existing documentation already covers the same subject. Avoid duplicate or contradictory documents.

## 14.1 Documentation content

### README.md

Explain:

- Feature purpose.
- Architecture.
- Supported frameworks.
- Execution workflow.
- Verification statuses.
- Coverage measurement.
- Iterative generation.
- Mutation evaluation.
- Security boundaries.
- How to run tests.
- Links to all documentation.

### Existing implementation audit

Document what existed before modifications.

### Requirements and scope

Document:

- Functional requirements.
- Non-functional requirements.
- Acceptance criteria.
- Dependencies.
- Out-of-scope items.

### Architecture

Include:

- Existing architecture.
- Proposed architecture.
- Component responsibilities.
- Data flow.
- Service boundaries.
- Integration points.

### Execution and verification

Document every verification stage.

Include:
- Static validation.
- Sandbox execution.
- Stability checks.
- Coverage validation.
- Final classification.

### Sandbox security

Document:
- Threat model.
- Isolation model.
- Filesystem restrictions.
- Network restrictions.
- Resource limits.
- Secret protection.
- Dependency restrictions.
- Cleanup.
- Known limitations.

### Coverage

Document:
- Baseline collection.
- Post-generation collection.
- Generated-test attribution.
- Line coverage.
- Branch coverage.
- Coverage limitations.

### Iteration

Document:
- Feedback loop.
- LLM context.
- Generation limits.
- Stopping conditions.
- Token control.

### Mutation testing

Document:
- Mutant generation.
- Mutant execution.
- Mutation score.
- Equivalent mutants.
- Evaluation strategy.

### Testing and implementation report

Document:
- Tests executed.
- Commands used.
- Pass/fail counts.
- Regression results.
- Security test results.
- Actual coverage measurements.
- Known issues.

Never fabricate test results.

If a test has not been executed, clearly label it NOT RUN.

## 14.2 Diagrams

Use Mermaid diagrams.

Create accurate diagrams based on the actual implementation.

Include:

1. Existing architecture.
2. Proposed architecture.
3. Full execution sequence.
4. Coverage-guided iteration.
5. Sandbox security boundaries.
6. Verification state machine.

Ensure the diagrams agree with the actual code.

## 14.3 Research documentation

Document:

P-10: Meta TestGen-LLM.
P-11: CoverUp.
P-12: MuTAP.
P-13: TestPilot.

For each, include:

- Research problem.
- Proposed approach.
- Relevant techniques.
- How it relates to our project.
- What we are adopting.
- What we are not adopting.
- Limitations.

Also document tools:

- coverage.py.
- pytest-cov.
- mutmut.
- Stryker.
- Hypothesis.
- Jest coverage.
- Vitest coverage.

Verify tool versions, compatibility and licenses before introducing dependencies.

Distinguish verified research facts from implementation decisions and unverified assumptions.

---

# 15. IMPLEMENTATION PHASES

Work in this order.

## PHASE 0 — AUDIT

- Inspect all relevant code.
- Inspect sandbox.
- Inspect framework support.
- Inspect benchmark logic.
- Inspect frontend.
- Write the existing implementation audit.
- Prepare exact change plan.

Do not modify production code before the audit is complete.

## PHASE 1 — BENCHMARK CORRECTION

- Correct threshold logic.
- Add unit tests.
- Update benchmark reporting.
- Document the changes.

This should be independently testable.

## PHASE 2 — SANDBOX READINESS

- Audit existing execution infrastructure.
- Verify isolation.
- Verify command restrictions.
- Verify resource limits.
- Verify secret protection.
- Verify cleanup.
- Extend only missing capabilities.

Do not duplicate existing sandbox components.

## PHASE 3 — EXECUTION VERIFICATION

- Implement or extend execution service.
- Capture execution results.
- Add stability validation.
- Add final test classification.
- Add unit and integration tests.

## PHASE 4 — COVERAGE

- Implement baseline coverage.
- Implement post-generation coverage.
- Add generated-test attribution.
- Add line and branch metrics.
- Add framework adapters.
- Test Python and JavaScript/TypeScript.

## PHASE 5 — VITEST

- Audit current support.
- Fix missing integration points.
- Add complete Vitest workflow tests.
- Validate coverage execution.

## PHASE 6 — ITERATIVE GENERATION

- Add coverage feedback.
- Add uncovered branch extraction.
- Add targeted LLM prompting.
- Add maximum round limit.
- Add stopping conditions.
- Add token tracking.

## PHASE 7 — MUTATION EVALUATION

- Integrate mutmut where appropriate.
- Integrate Stryker where appropriate.
- Add offline benchmark suite.
- Compare existing versus generated tests.
- Report mutation scores.

## PHASE 8 — FRONTEND AND REPORTING

- Integrate verification response.
- Display statuses.
- Display coverage.
- Display execution results.
- Display unverified reasons.
- Preserve existing UI functionality.

## PHASE 9 — COMPLETE TESTING

- Unit tests.
- Integration tests.
- Regression tests.
- Security tests.
- Framework compatibility tests.
- Benchmark evaluation.

## PHASE 10 — DOCUMENTATION AND FINAL AUDIT

- Complete all documentation.
- Validate Mermaid diagrams.
- Update Docs/README.md with the new documentation section.
- Update relevant engineering documentation.
- Update implementation changelog.
- Produce final testing report.
- Produce final known limitations report.

---

# 16. STRICT DEVELOPMENT RULES

Follow these rules throughout implementation.

1. Do not rewrite the entire project.
2. Do not replace existing sandbox infrastructure without a proven reason.
3. Do not duplicate existing services.
4. Do not remove working features.
5. Do not silently change API contracts.
6. Do not introduce unnecessary dependencies.
7. Do not introduce paid APIs.
8. Do not hardcode credentials.
9. Do not execute generated code on the host backend.
10. Do not weaken existing security restrictions.
11. Do not automatically modify the user's original repository.
12. Do not overwrite existing test files.
13. Do not generate tests inside protected configuration files.
14. Do not silently accept failing tests.
15. Do not mark tests VERIFIED without all mandatory checks.
16. Do not report coverage improvements without measurements.
17. Do not report mutation scores without execution.
18. Do not claim tests passed if they were not executed.
19. Do not hide infrastructure failures.
20. Do not create duplicate Docs directories.
21. Do not put major project documentation outside Docs/.
22. Update documentation whenever implementation changes.
23. Preserve existing user-facing functionality.
24. Prefer small, reviewable changes.
25. Maintain compatibility with existing deployment architecture.

---

# 17. ACCEPTANCE CRITERIA

The task is complete only when the following are satisfied.

### Execution

- [ ] Generated tests execute in an isolated sandbox.
- [ ] Original repository is protected.
- [ ] Execution output is captured.
- [ ] Execution failures are classified correctly.
- [ ] Three consecutive runs are supported.
- [ ] Flaky tests are not labelled verified.

### Coverage

- [ ] Baseline coverage is collected.
- [ ] Post-generation coverage is collected.
- [ ] Line coverage is supported.
- [ ] Branch coverage is supported where available.
- [ ] Generated-test contribution is measured.
- [ ] Missing coverage data is handled correctly.

### Iteration

- [ ] Maximum three generation rounds.
- [ ] Uncovered lines and branches are fed back to LLM.
- [ ] Duplicate tests are prevented.
- [ ] Token budgets are respected.
- [ ] Stopping conditions work.

### Frameworks

- [ ] pytest works.
- [ ] unittest works.
- [ ] Jest works.
- [ ] Vitest works end to end.

### Mutation testing

- [ ] Offline evaluation is supported.
- [ ] Mutation score is calculated correctly.
- [ ] Equivalent mutants are excluded where identified.
- [ ] Mutation testing is not mandatory for every request.

### Benchmark

- [ ] Threshold violations produce FAIL.
- [ ] Missing metrics cannot silently PASS.
- [ ] Actual results are reported.

### Frontend

- [ ] Verification statuses are visible.
- [ ] Coverage comparison is visible.
- [ ] Execution details are visible.
- [ ] Unverified tests are clearly separated.
- [ ] Existing functionality remains intact.

### Documentation

- [ ] All new documentation is in Docs/test-generation/.
- [ ] Docs/README.md is updated.
- [ ] Architecture diagrams are created.
- [ ] Research references are documented.
- [ ] Implementation changelog is maintained.
- [ ] Actual testing report is available.
- [ ] Known limitations are documented.

---

# 18. FINAL DELIVERABLES

At completion, provide:

1. Existing implementation audit.
2. Final architecture.
3. Complete implementation.
4. All new and modified file paths.
5. New dependencies and license details.
6. Database/API changes, if any.
7. Unit test results.
8. Integration test results.
9. Regression test results.
10. Security test results.
11. Framework compatibility results.
12. Coverage benchmark results.
13. Mutation evaluation results.
14. Performance and token usage observations.
15. Known limitations.
16. Complete documentation under Docs/test-generation/.
17. Final implementation summary.

Also provide a clear status for each phase:

- COMPLETED
- PARTIALLY COMPLETED
- BLOCKED
- NOT STARTED

Do not call the task complete if critical acceptance criteria remain unmet.

---

# 19. HOW TO WORK WITH ME

I want actual implementation, not only suggestions.

Start with PHASE 0.

First inspect the repository and produce:

- Existing architecture audit.
- Exact gaps.
- Existing sandbox readiness assessment.
- Exact files to modify.
- Exact new files required.
- Implementation dependency order.

Then proceed phase by phase.

For each phase:

1. Explain what you are changing.
2. Explain why it is necessary.
3. Modify the code.
4. Run relevant tests.
5. Fix failures.
6. Update documentation.
7. Record the result in the implementation changelog.

If a phase depends on missing infrastructure, implement or resolve that dependency first.

If a security issue is discovered, stop the affected execution workflow until it is resolved.

If an implementation decision could break existing APIs or deployment, inspect dependencies and document the migration before changing it.

Do not ask me to approve every small code change. Use engineering judgment within these requirements.

However, never make destructive changes, delete existing data, overwrite user files, expose credentials, or weaken security without explicit authorization.

**FINAL GOAL:**

Transform the existing Test Generation feature into an execution-verified, coverage-guided, iterative and security-conscious automated testing system.

Every generated test should have an honest, traceable verification status.

Every implementation decision should be documented.

Every claimed improvement should be supported by actual test results.

Keep all feature documentation organized inside the existing Docs/ directory.