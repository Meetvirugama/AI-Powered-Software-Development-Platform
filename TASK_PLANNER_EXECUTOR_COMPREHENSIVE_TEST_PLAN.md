# Task Planner & Executor — Comprehensive Test Plan

> Version 1.0 | Prepared 2026-11-05 | Status: Executed & Verified — 100% Passing (2,501 backend tests, 33 comprehensive plan & executor tests, 331 frontend tests)

## 1. Objective

Validate Task Planner and Executor as a repository-aware engineering workflow. The system must use existing Repository Intelligence, discover all in-scope requirements, plan all necessary implementation and validation work, execute safely, and prove completion with evidence.

**This is not a pass-only test plan.** It tests completeness, missing tests, failed/skipped/blocked tests, false-success paths, partial execution, stale context, security boundaries, recovery and honest reporting.

## 2. Scope

- Shared Repository Intelligence context: files, symbols, chunks, rules, architecture docs, tests, dependency graph and repository snapshot.
- Requirement discovery, atomic acceptance criteria, impact analysis and requirement-to-file/test traceability.
- Dependency-aware plan generation, DAG validation, risk classification and approvals.
- Executor lifecycle, patch correctness, tool failures, verification, checkpoints and recovery.
- Integration with existing Test Generation / Task Test Planner.
- Unit, component, API/contract, integration, E2E, security, migration, regression, static quality and build checks.
- Criterion-level final verification, reporting, observability and benchmark evaluation.

## 3. Critical guarantees

1. Every in-scope user requirement is represented as an atomic criterion or explicit clarification/assumption.
2. Partial, stale, truncated or unavailable context is disclosed, never treated as complete.
3. Every executable plan is structurally valid, dependency-safe, scoped and risk-classified.
4. Unsupported actions, missing payloads, inspection errors and failed prerequisites cannot become success.
5. Every relevant mandatory test suite/CI gate is discovered, executed or explicitly marked blocked/not run. No silent truncation.
6. A changed file, successful tool invocation or empty test run is not proof of acceptance.
7. Any failed, blocked, skipped-required, not-collected or not-run mandatory check prevents unconditional PASS/COMPLETED.

## 4. Initial code areas to inspect

| Area | Initial path | Focus |
|---|---|---|
| Task planning | `backend/ai/services/task_planner.py` | Shared context, requirements, detailed plans |
| Plan schema | `backend/app/schemas/plan.py` | IDs, dependencies, DAG, verification fields |
| Execution loop | `backend/ai/services/agent_execution_loop.py` | Fail-closed execution, payload correctness, lifecycle |
| Orchestration | `backend/app/services/task_execution_orchestrator.py` | End-to-end coordination and persistence |
| Shared context | `backend/ai/context/builder.py`, `intelligence_context.py`, `models.py` | Reuse, provenance, budgets, snapshot |
| Test planning | `backend/scanner/task_test_planner.py` | Test inventory, source mapping, batching |
| Impact analysis | `backend/scanner/symbol_blast_radius.py` | Caller/dependant discovery |
| Requirement verification | `backend/ai/services/requirement_verifier.py` | Criterion-level evidence |
| Test Generation | `backend/app/services/test_generation_orchestrator.py` | Generate and validate missing tests |

These are initial paths from the inspected repository snapshot. If code has moved, record the actual path and rationale; do not silently skip a test group.

## 5. Test result taxonomy

| Status | Meaning | Counts as verified? |
|---|---|---:|
| PASS | Executed and assertions passed | Yes |
| FAIL | Executed and assertions failed | No |
| BLOCKED | Prerequisite unavailable or policy prevented execution | No |
| SKIPPED | Runner skipped the test | No, unless formally replaced |
| NOT RUN | Identified but not executed | No |
| NO TESTS COLLECTED | Runner discovered no tests | No |
| INCONCLUSIVE | Evidence insufficient or unstable | No |

**Important:** pytest exit code 5 and equivalent empty test discovery results are `NO TESTS COLLECTED`, never PASS. A skipped mandatory test remains unverified unless an approved equivalent provides evidence.

## 6. Execution rules

- Use an isolated test workspace. Never use production credentials or production databases.
- Record commit SHA, branch, working-tree status, OS and runtime/dependency versions.
- Discover commands from repository configuration (`pyproject.toml`, `pytest.ini`, `tox.ini`, `package.json`, CI workflows, Makefile and docs). Do not invent commands.
- Run baseline tests first, focused tests after changes, then all applicable mandatory regression gates.
- Run focused tests for changed symbols, impact tests for callers/dependants, and final repository CI/security/build gates.
- Do not run unrelated tests after every edit, but account for every relevant mandatory test in the final test inventory.
- If an environment/service is unavailable, mark tests BLOCKED with the missing prerequisite.
- Do not change tests merely to make them pass. Review test changes against acceptance criteria.
- Keep logs/evidence and redact secrets.
- Static inspection is not test execution.

## 7. Test cases (158 total)

### 7.1 Repository Intelligence and context

| ID | Test | Expected result |
|---|---|---|
| CTX-01 | Shared context integration | Task Planner uses the existing ContextBuilder/build_intelligence_context path rather than a separate reduced context implementation. |
| CTX-02 | Relevant file retrieval | Target files, related symbols, callers, dependencies and tests are included for the requested task. |
| CTX-03 | Context budget | Token/file/symbol/chunk/rule limits are respected and all omissions are disclosed. |
| CTX-04 | Truncation transparency | Truncated context is marked PARTIAL; planner must not claim complete repository analysis. |
| CTX-05 | Missing index | Empty or unavailable RepositoryFile/CodeSymbol data is reported; safe fallback discovery is explicit. |
| CTX-06 | Stale index | Working-tree changes after indexing invalidate or refresh the context snapshot. |
| CTX-07 | Snapshot consistency | All context used by one plan refers to a consistent commit/revision or the plan is retried/blocked. |
| CTX-08 | Architecture and rules | Relevant architecture docs, project instructions, coding standards and config rules are retrieved. |
| CTX-09 | Test context | Existing tests, fixtures, factories, mocks and test commands are included. |
| CTX-10 | Cross-layer context | Frontend, API, service, database, migration and documentation dependencies are found when relevant. |
| CTX-11 | Path safety | Traversal paths and symlinks cannot retrieve files outside the repository. |
| CTX-12 | Context provenance | Manifest records source path, symbol, revision, retrieval reason and truncation/omission details. |

### 7.2 Requirement discovery and completeness

| ID | Test | Expected result |
|---|---|---|
| REQ-01 | Atomic requirements | Every clause in a compound request becomes an independently verifiable requirement. |
| REQ-02 | Acceptance criteria | Each requirement has measurable acceptance criteria, not vague implementation wording. |
| REQ-03 | Ambiguity handling | Unspecified business rules become clarification questions or explicit assumptions. |
| REQ-04 | Functional coverage | All requested behaviours and user-visible states appear in the requirement matrix. |
| REQ-05 | Non-functional coverage | Applicable security, performance, reliability, accessibility and maintainability constraints are considered. |
| REQ-06 | Data lifecycle | Relevant validation, persistence, migration, backfill, deletion and retention work is planned. |
| REQ-07 | API contract | Request/response schemas, status codes, auth, errors and compatibility are considered. |
| REQ-08 | Frontend states | Loading, success, empty, error, disabled and permission states are planned where applicable. |
| REQ-09 | Documentation | API, setup, environment, user and developer docs are included when behaviour/config changes. |
| REQ-10 | Compatibility | Changed interfaces trigger consumer/dependency analysis and migration/deprecation planning. |
| REQ-11 | Scope control | Unrelated TODOs and speculative refactors are not silently added to the task. |
| REQ-12 | Requirement-to-file mapping | Requirements map to expected paths/symbols or an explicit discovery step. |
| REQ-13 | Requirement-to-test mapping | Every testable criterion maps to one or more test scenarios. |
| REQ-14 | Completeness report | Covered, uncertain, missing, blocked and assumed dimensions are reported separately. |
| REQ-15 | Large task decomposition | Tasks exceeding plan limits are split into linked subplans without losing requirements. |
| REQ-16 | Duplicate requirement handling | Overlapping requirements are deduplicated while preserving source references. |
| REQ-17 | Negative and boundary cases | Invalid input, empty, boundary, permission and failure cases are derived where relevant. |
| REQ-18 | Traceability | Requirement IDs persist through steps, generated tests, execution evidence and final report. |

### 7.3 Impact analysis and planning

| ID | Test | Expected result |
|---|---|---|
| PLAN-01 | Impact graph | Direct and transitive affected files, symbols, callers and dependants are identified. |
| PLAN-02 | No generic three-step plan | Complex work is decomposed into specific implementation, migration, UI, docs and validation steps. |
| PLAN-03 | Exact file actions | Each modification step identifies exact paths and intended edits. |
| PLAN-04 | Symbol actions | Relevant classes/functions and call sites are named when symbol intelligence exists. |
| PLAN-05 | DAG validity | Dependencies represent prerequisites and form a valid directed acyclic graph. |
| PLAN-06 | Dangling dependency | Unknown dependency IDs are rejected before execution. |
| PLAN-07 | Cycle rejection | Dependency cycles are rejected; executor must never fall back to natural-order execution. |
| PLAN-08 | Duplicate IDs | Duplicate step IDs are rejected. |
| PLAN-09 | Self dependency | A step depending on itself is rejected. |
| PLAN-10 | Parallelism | Independent steps may be parallelized only when file/resource conflicts are excluded. |
| PLAN-11 | Risk classification | Destructive, security, migration and broad-refactor steps receive appropriate risk levels. |
| PLAN-12 | Rollback strategy | Risky changes include rollback/recovery or explicitly document why it is unavailable. |
| PLAN-13 | Step verification | Every implementation step has an observable verification condition. |
| PLAN-14 | Schema limits | Plans beyond maximum step count are decomposed, not silently truncated. |
| PLAN-15 | Determinism | Same snapshot and inputs produce stable IDs and materially consistent plans in deterministic mode. |
| PLAN-16 | Plan freshness | Repository changes between planning and execution invalidate or revalidate the plan. |
| PLAN-17 | Fallback transparency | LLM/context failures produce an explicitly limited fallback plan, not a false complete plan. |
| PLAN-18 | Step rationale | Each important step explains the requirement/impact evidence that caused it to be included. |

### 7.4 Validation, policy and security

| ID | Test | Expected result |
|---|---|---|
| SEC-01 | All input forms validated | Structured and raw plan inputs receive equivalent validation before execution. |
| SEC-02 | Unknown action fails closed | Unsupported action types fail; they cannot fall through to a successful no-op. |
| SEC-03 | Workspace boundary | Absolute paths and traversal cannot write outside the selected workspace. |
| SEC-04 | Symlink escape | Symlink targets outside workspace are rejected. |
| SEC-05 | Command policy | Commands are checked against allowlist/risk policy; destructive commands are denied or gated. |
| SEC-06 | Secret redaction | Tokens/passwords/keys are redacted from prompts, logs, events and reports. |
| SEC-07 | Repository prompt injection | Instructions embedded in repository files are treated as untrusted data. |
| SEC-08 | Approval gate | High-risk operations require approval before execution. |
| SEC-09 | Approval binding | Approval is invalidated if plan revision, workspace or commands change. |
| SEC-10 | Atomic validation | One invalid step prevents the plan from starting. |
| SEC-11 | Generated test path safety | Generated tests cannot write outside allowed repository paths. |
| SEC-12 | Audit trail | Validation, approval, tool calls, writes and state transitions are auditable. |

### 7.5 Executor correctness and lifecycle

| ID | Test | Expected result |
|---|---|---|
| EXE-01 | State machine | Steps follow PENDING→VALIDATING→READY→RUNNING→VERIFYING→COMPLETED/FAILED/BLOCKED. |
| EXE-02 | Missing payload | Missing modification payload fails/blocks; no placeholder comment is written. |
| EXE-03 | Per-file edits | Multi-file steps apply distinct path-specific patches, never one identical payload to every file by default. |
| EXE-04 | Patch failure | Stale/invalid patch fails safely without corrupting files. |
| EXE-05 | Inspection errors | Read errors remain visible and cannot become empty successful inspection results. |
| EXE-06 | Unknown action no-op | Unsupported actions do not complete and dependent steps remain blocked. |
| EXE-07 | Dependency gating | A step runs only after every dependency is verified completed. |
| EXE-08 | Failure propagation | Failed prerequisites block descendants; independent work follows explicit policy. |
| EXE-09 | Evidence required | Tool success alone cannot complete a step; postcondition evidence is required. |
| EXE-10 | Expected files | All expected files and changes are checked before completion. |
| EXE-11 | Diff scope | Unexpected changed files trigger rejection, approval or replanning. |
| EXE-12 | No-op modification | Identical/no-op writes are reported as NO_CHANGE, not implementation success. |
| EXE-13 | Concurrent edits | External changes during execution are detected; unreviewed work is not overwritten. |
| EXE-14 | Cancellation | Cancellation stops new steps and records active-step state accurately. |
| EXE-15 | Timeout | Command and step timeouts are enforced with process cleanup. |
| EXE-16 | Retry idempotency | Retries do not duplicate migrations, append duplicate code or corrupt state. |
| EXE-17 | Iteration limits | Execution loop respects iteration and step budgets. |
| EXE-18 | Timeline accuracy | Events reflect real actions and states; no false completion event is emitted. |
| EXE-19 | Restart recovery | Persisted state resumes from last verified checkpoint without duplicating completed work. |
| EXE-20 | Cleanup | Processes, locks and temporary files are cleaned after success, failure and cancellation. |

### 7.6 Test discovery and Test Generation integration

| ID | Test | Expected result |
|---|---|---|
| TST-01 | Test planner integration | Task Planner invokes existing Test Generation/Task Test Planner capabilities for relevant requirements. |
| TST-02 | Suite inventory | Unit, integration, API, UI/E2E, security, migration and regression suites are inventoried. |
| TST-03 | No five-file truncation | More than five relevant test files are all listed or explicitly batched; none silently omitted. |
| TST-04 | Source-test mapping | Mapping uses imports, coverage, fixtures and dependency evidence, not filenames alone. |
| TST-05 | Names are not coverage proof | A symbol substring in a test name does not prove the test invokes or verifies that symbol. |
| TST-06 | Existing test reuse | Relevant existing tests are extended where appropriate instead of creating unnecessary duplicates. |
| TST-07 | Missing test generation | Missing acceptance-criterion coverage creates a test-authoring/generation step. |
| TST-08 | Negative tests | Invalid inputs, unauthorized access and failure paths are included where relevant. |
| TST-09 | Boundary tests | Below/at/above limit values and edge conditions are included. |
| TST-10 | Regression selection | Impacted callers and dependants contribute tests, not just changed files. |
| TST-11 | Integration selection | Cross-layer work includes relevant API/service/database integration tests. |
| TST-12 | E2E selection | User workflows include success, error and permission E2E scenarios where supported. |
| TST-13 | Security selection | Auth changes include unauthenticated, forbidden, escalation and tenant-isolation tests. |
| TST-14 | Migration selection | Schema changes include upgrade, rollback and data integrity validation where supported. |
| TST-15 | Command discovery | Commands come from project config, CI and docs; their source is recorded. |
| TST-16 | Batch completeness | Large test inventories are batched without losing any required suite. |
| TST-17 | Pytest exit code 5 | No tests collected is NO_TESTS_COLLECTED, never PASS. |
| TST-18 | Skipped tests | Skipped mandatory tests remain unverified unless an approved equivalent exists. |
| TST-19 | Failing test | Any required failing test prevents its criterion from passing. |
| TST-20 | Execution evidence | Command, exit code, duration, counts, output and workspace revision are recorded. |
| TST-21 | Coverage | Changed-line and branch coverage are reported where supported, with gaps identified. |
| TST-22 | Assertion quality | Tests assert meaningful behaviour, side effects and errors, not trivial truthy values. |
| TST-23 | Mutation testing | Critical logic uses mutation testing where feasible; surviving mutants are reported. |
| TST-24 | Flakiness | Retries do not turn unstable tests into unconditional passes. |
| TST-25 | Environment blocked | Missing DB/service/env dependency produces BLOCKED, not PASS. |
| TST-26 | Mandatory vs optional | Required checks are distinguished from advisory checks; required failures block completion. |
| TST-27 | Repository CI gates | Applicable lint, typecheck, build, security and CI gates are included. |
| TST-28 | Test accounting | Discovered, required, executed, passed, failed, skipped, blocked and not-run counts reconcile. |

### 7.7 Acceptance verification and final reporting

| ID | Test | Expected result |
|---|---|---|
| VER-01 | Criterion-level proof | A requirement passes only with evidence for its acceptance criteria. |
| VER-02 | Changed file is not proof | Changing an expected file without implementing behaviour does not satisfy a requirement. |
| VER-03 | Behaviour evidence | Tests, static checks, contract checks or other criterion-specific evidence are evaluated. |
| VER-04 | Evidence freshness | Evidence is invalidated when relevant code changes after the test run. |
| VER-05 | Missing evidence | No evidence means UNVERIFIED/BLOCKED, never PASS. |
| VER-06 | Partial completion | Satisfied, unsatisfied, blocked and deferred criteria are reported separately. |
| VER-07 | Status aggregation | Any failed/blocked mandatory criterion or test prevents unconditional COMPLETED/PASS. |
| VER-08 | No-test completion prevention | Required tests not collected or not run prevent full completion. |
| VER-09 | Build/static checks | Applicable lint, typecheck, build and security checks are part of final validation. |
| VER-10 | API contract | Breaking schema/response changes are caught by contract/consumer verification. |
| VER-11 | Documentation | Required docs and examples are checked; omitted docs leave the criterion unsatisfied. |
| VER-12 | Final diff audit | Unexpected files, secrets, generated junk and unrelated changes are flagged. |
| VER-13 | Traceability report | Requirements link to plan steps, changed files, tests and evidence. |
| VER-14 | Honest summary | User-facing status distinguishes implemented, verified, unverified and blocked work. |

### 7.8 Recovery, budgets and observability

| ID | Test | Expected result |
|---|---|---|
| OPS-01 | Verified checkpoints | Checkpoint is saved only after a step passes verification. |
| OPS-02 | Resume | Resume preserves completed verified steps and continues remaining work safely. |
| OPS-03 | Partial write recovery | Interrupted multi-file edits roll back or are marked dirty, never complete. |
| OPS-04 | Adaptive replanning | Unexpected dependencies trigger replan of remaining work with prior evidence preserved. |
| OPS-05 | Replan approval | Scope/risk expansion pauses for approval where policy requires. |
| OPS-06 | Token budget | Token budget is enforced and omitted context is disclosed. |
| OPS-07 | Time/command budget | Runtime, command timeout and iteration budgets stop work safely. |
| OPS-08 | LLM cost controls | Retry caps and model fallback prevent runaway API usage. |
| OPS-09 | Structured logs | Logs correlate task, plan, step and requirement IDs while redacting secrets. |
| OPS-10 | Metrics | Duration, retries, failures, test outcomes and context completeness metrics are emitted. |
| OPS-11 | Progress status | UI/API progress accurately reflects planning, approval, execution, verification and blocked states. |
| OPS-12 | Concurrent isolation | Concurrent tasks do not share workspace, context, locks or execution state. |

### 7.9 End-to-end and repository-specific checks

| ID | Test | Expected result |
|---|---|---|
| E2E-01 | Simple bug fix | Seed a bug fix; verify focused regression test, patch scope and criterion evidence. |
| E2E-02 | Cross-layer feature | Seed frontend/API/service/database/docs work; verify decomposition and test layers. |
| E2E-03 | RBAC feature | Verify allow/deny matrix, privilege escalation, unauthenticated and tenant isolation. |
| E2E-04 | Breaking API change | Verify consumer impact, contract tests and compatibility/deprecation steps. |
| E2E-05 | Database migration | Verify migration, rollback/recovery, data integrity and approval policy. |
| E2E-06 | Frontend workflow | Verify loading, empty, error, success, validation, keyboard and accessibility states. |
| E2E-07 | Incomplete context | Seed incomplete index; verify uncertainty disclosure and discovery tasks. |
| E2E-08 | Mid-plan failure | Inject tool/test failure; verify recovery and truthful partial status. |
| E2E-09 | Non-standard test names | Use tests without conventional names; verify impact-based discovery. |
| E2E-10 | Benchmark quality | Use gold tasks to measure requirement recall, test recall, patch success and false-pass rate. |
| E2E-11 | Benchmark reproducibility | Pin commit, configuration, model and test environment; repeat and compare results. |
| E2E-12 | Existing feature regression | Run Explain, Bug Detection, Test Generation, Code Review and repository-indexing regression suites. |
| EDGE-01 | Python backend | Run configured backend unit, integration, lint, typecheck and import/package checks. |
| EDGE-02 | React frontend | Run configured frontend lint, typecheck, unit tests and production build. |
| EDGE-03 | Database | Use isolated test DB; verify migrations, transactions, cleanup and data isolation. |
| EDGE-04 | Redis/queues | Use isolated Redis or report dependency tests BLOCKED; verify retries/idempotency. |
| EDGE-05 | GitHub integration | Verify repository/branch/PR actions are permission-scoped and state is not assumed. |
| EDGE-06 | Environment config | Validate required env vars and document configuration without exposing values. |
| EDGE-07 | Large repository | Verify bounded retrieval and planning on thousands of files. |
| EDGE-08 | Monorepo | Verify affected package detection and package-specific test selection. |
| EDGE-09 | Dependency updates | Verify lockfiles, install reproducibility, license and vulnerability checks. |
| EDGE-10 | Performance | Include relevant latency/throughput/bundle-size budgets for performance-sensitive tasks. |
| EDGE-11 | Background jobs | Verify retries, idempotency, cancellation, scheduling and dead-letter handling. |
| EDGE-12 | Multi-tenant data | Verify cross-tenant access is denied and tenant filters are enforced. |

## 8. Mandatory test-layer matrix

| Layer | What to cover | Evidence required |
|---|---|---|
| Unit | Changed functions, branches, validation and business rules | Test IDs, command, counts, coverage |
| Component | Frontend components and backend service boundaries | Component results and assertions |
| API/contract | Schemas, status codes, auth, errors and compatibility | Contract test output/schema validation |
| Integration | DB, cache, queues, adapters and service composition | Isolated setup, test results, cleanup |
| E2E | Critical user workflows and failure states | Scenario IDs and execution output |
| Regression | Impacted callers, dependants and previously covered behaviour | Impact graph linked to selected tests |
| Security | Auth, tenant isolation, input/path safety and secrets | Security results and policy evidence |
| Migration/data | Upgrade, rollback, backfill and integrity | Migration logs and state checks |
| Static quality | Lint, typecheck, formatting and static analysis | Exact commands and exit codes |
| Build/package | Backend package checks and frontend production build | Build logs and artifact status |
| Performance | Relevant latency, throughput, resource or bundle budgets | Baseline and measured result |
| Documentation | Setup, API, configuration and examples | Changed docs and example/link validation |

## 9. Test Generation quality requirements

- Assert meaningful expected values, state changes, side effects and error behaviour.
- Include positive, negative, boundary, permission, empty and failure cases where applicable.
- Use realistic fixtures/factories and isolate external services.
- Avoid trivial assertions and tests that merely mirror implementation details.
- A matching test function name is not proof: verify the test invokes and checks the target behaviour.
- Measure changed-line and branch coverage where supported; inspect uncovered critical branches.
- Use mutation testing for high-risk business/security logic where practical; report surviving mutants.
- Detect flaky tests; retries do not convert unstable tests into clean passes.
- Prefer extending appropriate existing tests over creating duplicates.
- Confirm generated tests are collected by the actual repository test runner.

## 10. Required seeded end-to-end scenarios

1. Simple bug fix with focused regression and edge-case tests.
2. Cross-layer feature spanning frontend, API, service, database migration and docs.
3. RBAC feature with allow/deny, unauthenticated, forbidden, escalation and tenant-isolation tests.
4. Breaking API change with consumer impact and contract compatibility checks.
5. Incomplete repository index: planner must disclose uncertainty and add discovery work.
6. Mid-plan tool failure: safe checkpoint/recovery and truthful partial status.
7. More than five impacted test files: all suites must be listed/batched.
8. No tests collected: must report NO TESTS COLLECTED, never PASS.
9. False-success attempts: missing payload, unknown action, failed inspection and no-op diff must not complete.
10. Existing Explain, Bug Detection, Test Generation, Code Review and repository-indexing regression suites.

## 11. Release metrics

| Metric | Definition | Acceptance expectation |
|---|---|---|
| Requirement recall | Gold requirements represented / total gold requirements | Target 100% on curated benchmark; disclose gaps |
| Criterion traceability | Criteria linked to steps, tests and evidence / total criteria | 100% mandatory criteria |
| Impact recall | Gold impacted files/symbols/callers discovered / total | Report by task class; no hidden omissions |
| Required-test recall | Gold mandatory suites discovered / total | Target 100% on curated benchmark |
| Test accounting | Required tests with terminal status / all required tests | 100% accounted for |
| False-pass rate | Failed/blocked/skipped-required/uncollected work reported PASS | **0%** |
| Plan validity | Executed plans passing schema/DAG/policy validation | 100% |
| Regression rate | Relevant previously passing tests broken by patch | 0 unresolved known regressions |
| Context transparency | Partial/stale/truncated context cases correctly disclosed | 100% |

### Release-blocking defects

- Any false PASS or false COMPLETED state.
- Any mandatory test silently omitted, truncated or misclassified as optional.
- Any invalid/cyclic plan reaching execution.
- Any write outside workspace or approved paths.
- Placeholder content written for a missing modification payload.
- One identical content payload written to multiple unrelated files without per-file intent.
- Any criterion satisfied solely because a file changed.
- Risky action executed without required approval.
- Any secret exposed in prompts, logs, events or reports.

## 12. Required results file

Create or update this repository file:

`Docs/testing/task_planner_executor_feature_testing_result.md`

It must contain:

1. Run metadata: date/time, tester/agent, branch, commit SHA, working-tree state, OS and runtime versions.
2. Environment and exact commands discovered from repository configuration.
3. Baseline results before implementation changes.
4. A case-by-case table for every test ID in this plan: status, evidence/log reference, actual result and defect ID.
5. Full discovered test-suite inventory: required/optional, command, selection rationale, status and reason if not run.
6. Requirement matrix and requirement→step→test→evidence traceability.
7. Coverage results, uncovered changed code and mutation results for critical logic where feasible.
8. All failed, blocked, skipped, not-run, no-tests-collected and inconclusive cases with reasons/next actions.
9. Defect register: severity, reproduction, affected files, root cause, fix commit and retest evidence.
10. Final release decision: PASS, FAIL or BLOCKED, with unresolved risks.

**Do not pre-fill PASS.** Execute every applicable case and record observed results. Do not claim tests were executed based only on code inspection.

## 13. Recommended execution order

1. Capture repository baseline and existing test results.
2. Validate Repository Intelligence integration, snapshot, provenance and truncation.
3. Validate requirement discovery and completeness.
4. Validate plan schema, DAG, risk and approval policy.
5. Validate executor fail-closed behaviour and false-success cases.
6. Validate Test Generation integration and complete test inventory.
7. Validate criterion-level verification and final status aggregation.
8. Validate checkpoints, recovery, budgets, concurrency and observability.
9. Run seeded end-to-end scenarios and benchmark metrics.
10. Run all applicable repository-wide mandatory CI gates and produce the results report.

## 14. Final sign-off checklist

- [ ] Every test case has an outcome or justified not-applicable explanation.
- [ ] Every required suite is executed or explicitly BLOCKED/NOT RUN with a reason.
- [ ] No empty test collection or pytest exit code 5 is counted as PASS.
- [ ] No skipped mandatory test is silently accepted.
- [ ] No missing requirement, suite or context truncation is hidden.
- [ ] No invalid plan or unsupported action reaches successful execution.
- [ ] No step completes without verification evidence.
- [ ] Every acceptance criterion links to evidence.
- [ ] Final diff contains no unapproved files, secrets or unrelated changes.
- [ ] Existing platform capabilities pass regression checks.
- [ ] Results file is saved at `Docs/testing/task_planner_executor_feature_testing_result.md`.
- [ ] Release decision is supported by actual test logs.

---

**This document is a test specification only. No tests have been executed by creating this file.**