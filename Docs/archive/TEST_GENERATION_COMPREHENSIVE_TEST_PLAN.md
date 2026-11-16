# Repository Intelligence–Powered Test Generation
## Comprehensive Feature Testing Plan

**Project:** AI-Powered Software Development Platform  
**Primary repository:** https://github.com/Meetvirugama/AI-Powered-Software-Development-Platform  
**Feature under test:** Test Generation using existing Repository Intelligence  
**Document type:** Functional, integration, quality, security, regression and acceptance test plan  
**Execution rule:** Test the current implementation first. Do not silently fix code while testing.

---

# 1. Objective

Verify that Test Generation reuses the existing Repository Intelligence feature to discover the important test requirements of a repository, identify existing coverage and gaps, generate useful tests, execute them safely, and report what remains untested.

This feature must **not** be considered successful merely because it generates test files or produces tests that pass. It must demonstrate that it can:

1. Understand the repository structure and supported languages/frameworks.
2. Reuse the repository's indexed files, symbols, relationships, chunks, summaries and snapshot metadata.
3. Discover important testable behaviours and risks across the repository.
4. Inventory existing tests, fixtures, mocks and coverage evidence.
5. Build a traceable Test Requirement Matrix.
6. Identify missing and partially covered requirements.
7. Generate a diverse, prioritised test suite for important gaps.
8. Validate generated test code and execute it in a restricted environment.
9. Measure coverage and test quality without confusing metrics.
10. Report unsupported, blocked, untested and unverified areas honestly.

## 1.1 Required test-generation modes

Test all three modes:

- **Full Repository Test Generation:** discover requirements across the complete supported repository.
- **Targeted Test Generation:** generate tests for a selected file, class, function, method or API endpoint, including relevant dependencies.
- **Change-Based Test Generation:** analyse a commit/branch/change set and discover affected requirements and regression tests.

## 1.2 Non-goals and safety boundaries

- Do not push commits, create pull requests, open issues or modify the remote repository.
- Do not execute arbitrary repository scripts on the host.
- Do not run destructive tests against production databases, live services or real user data.
- Do not overwrite or delete existing tests without explicit approval.
- Do not claim a test passed unless it was actually executed and its result was captured.
- Do not claim complete repository coverage when some languages, folders, generated code or runtime paths were unsupported.
- Do not invent coverage, mutation scores, requirement coverage or execution results.

---

# 2. Mandatory instructions for the testing agent

Use this document as the execution specification.

1. Inspect the actual repository and identify the current implementation before testing.
2. Record the exact repository commit SHA and Repository Intelligence snapshot/version used for each run.
3. Identify actual API routes, schemas, services, models, database tables, workers, frontend components and test-runner capabilities from the code. Do not assume a proposed file or feature already exists.
4. Separate **implemented**, **partially implemented**, **not implemented**, **unsupported** and **not verified** capabilities.
5. Run baseline tests before generating tests. Preserve baseline output.
6. Use isolated temporary fixtures and disposable databases for destructive or security-oriented cases.
7. Do not modify application code to make a test pass during baseline testing.
8. Generated tests must be saved only to the designated test output location or an isolated worktree. Never silently overwrite existing tests.
9. For each test, record whether it was generated, statically validated, executed, passed, failed, skipped, timed out or blocked.
10. After each test group, update the results file specified below.
11. If a test cannot be run, record the reason and evidence. Do not mark it as passed.
12. Re-run relevant baseline tests after generated tests are added to detect regressions.
13. Do not treat test names, imports or generated scenario descriptions as proof of execution coverage.
14. Record token usage, generation attempts, execution duration and relevant resource usage where instrumentation exists.
15. Do not expose secrets, environment variables, private repository contents or credentials in reports.

## 2.1 Required result file

Create or update:

`Docs/testing/test_generation_feature_testing_result.md`

If the repository uses a different existing documentation-folder casing, preserve that convention but retain the exact filename:

`test_generation_feature_testing_result.md`

After each major test group:

- Save the current results.
- Verify the file exists and is non-empty.
- Include executed test IDs, status, evidence, defects and blocked cases.
- Preserve previous results; do not replace detailed history with only a final summary.

If the repository is read-only or the agent cannot save to it, create a downloadable local result file and explicitly state that it was not saved to GitHub.

---

# 3. Test result status definitions

Use only these statuses:

| Status | Meaning |
|---|---|
| PASS | Expected behaviour was observed and supported by evidence |
| FAIL | Actual behaviour differs from expected behaviour |
| PARTIAL | Some expected behaviour works, but a material requirement is missing |
| BLOCKED | Test could not run because a required dependency, permission or environment was unavailable |
| NOT_IMPLEMENTED | Required capability is absent from the current implementation |
| UNSUPPORTED | Capability is outside the declared language/framework/scope |
| NOT_RUN | Test has not been executed |
| NOT_APPLICABLE | Requirement genuinely does not apply; include a reason |

Do not use PASS for a generated-but-unexecuted test.

---

# 4. Repository baseline and implementation audit

| ID | Test | Expected result |
|---|---|---|
| TG-BASE-001 | Record repository URL, branch and commit SHA | Exact revision is recorded |
| TG-BASE-002 | Record Repository Intelligence snapshot ID/version | Snapshot identity is recorded |
| TG-BASE-003 | Inspect Test Generation frontend entry points | Actual pages, hooks, services and components are listed |
| TG-BASE-004 | Inspect Test Generation API routes | Actual endpoints, methods, schemas and auth requirements are listed |
| TG-BASE-005 | Inspect test-generation orchestrator | Actual orchestration stages and error paths are documented |
| TG-BASE-006 | Inspect test-generation service and prompts | Actual model calls, structured output and repair logic are documented |
| TG-BASE-007 | Inspect existing test context builder | Inputs, retrieval strategy, token budget and limitations are documented |
| TG-BASE-008 | Inspect Repository Intelligence context interfaces | Reusable snapshot, symbols, graph and chunk interfaces are identified |
| TG-BASE-009 | Inspect test mapper and task test planner | Existing mapping and planning limitations are recorded |
| TG-BASE-010 | Inspect test runner | Supported commands, isolation, timeout and output handling are documented |
| TG-BASE-011 | Inspect database models and migrations | Test history, run metadata and persistence are understood |
| TG-BASE-012 | Inspect supported languages/frameworks | Only actually implemented adapters are listed |
| TG-BASE-013 | Inspect current tests for Test Generation | Existing baseline tests are identified |
| TG-BASE-014 | Run existing backend test suite | Baseline result and failures are recorded |
| TG-BASE-015 | Run existing frontend test suite | Baseline result and failures are recorded |
| TG-BASE-016 | Record known failures before feature testing | Pre-existing failures are distinguished from new defects |
| TG-BASE-017 | Identify feature flags and configuration | Defaults and required settings are recorded |
| TG-BASE-018 | Identify logging and observability | Request IDs, run IDs and error traces are traceable |
| TG-BASE-019 | Check migrations on a clean test database | Schema initializes without data loss |
| TG-BASE-020 | Verify result-file location and write permission | Result file can be created and updated, or limitation is recorded |

---

# 5. Repository Intelligence reuse tests

**Objective:** prove that Test Generation uses the existing repository intelligence snapshot instead of creating a duplicate or incomplete repository context.

| ID | Test | Expected result |
|---|---|---|
| TG-RI-001 | Run Repository Intelligence before test generation | Test Generation can retrieve the completed snapshot |
| TG-RI-002 | Inspect retrieved snapshot ID | All context records refer to the same snapshot |
| TG-RI-003 | Retrieve target symbol context | Correct symbol, path, signature and source revision are supplied |
| TG-RI-004 | Retrieve callers of target symbol | Relevant callers are included when available |
| TG-RI-005 | Retrieve callees/dependencies | Relevant called functions and modules are included |
| TG-RI-006 | Retrieve imported types and constructors | Required object construction context is included |
| TG-RI-007 | Retrieve related models and schemas | Relevant validation and data contracts are included |
| TG-RI-008 | Retrieve API route and service relationships | Endpoint-to-service-to-model chain is discoverable |
| TG-RI-009 | Retrieve relevant repository chunks | Chunks are relevant, ranked and source-grounded |
| TG-RI-010 | Retrieve existing test files | Relevant tests and fixtures are included |
| TG-RI-011 | Retrieve project testing conventions | Framework, naming, fixture and mock patterns are followed |
| TG-RI-012 | Retrieve project documentation | Relevant requirements and expected behaviour are included |
| TG-RI-013 | Retrieve configuration dependencies | Relevant environment/configuration behaviour is considered without exposing secrets |
| TG-RI-014 | Compare selected file with automatically discovered dependencies | Both are included and their provenance is distinguishable |
| TG-RI-015 | Select an explicit related file | Explicit user selection receives priority |
| TG-RI-016 | Exceed context token budget | Context is ranked and trimmed without dropping essential target evidence silently |
| TG-RI-017 | Inspect context manifest | Included and excluded files/symbols and reasons are reported |
| TG-RI-018 | Request a missing symbol | System reports unavailable context instead of fabricating it |
| TG-RI-019 | Use an incomplete Repository Intelligence snapshot | Generation is blocked or clearly marked partial according to policy |
| TG-RI-020 | Use stale snapshot after source changes | Staleness is detected and refresh is requested or performed |
| TG-RI-021 | Change a dependency without changing target file | Dependency invalidation updates affected test context |
| TG-RI-022 | Compare targeted and full-repository context | Targeted context is bounded; full mode discovers broader repository requirements |
| TG-RI-023 | Verify no duplicate repository index is created | Existing indexing/graph infrastructure is reused |
| TG-RI-024 | Force graph-edge persistence failure | Snapshot is not falsely represented as complete |
| TG-RI-025 | Verify source and context commit consistency | No mixed-commit evidence is used |

---

# 6. Full repository inventory tests

| ID | Test | Expected result |
|---|---|---|
| TG-INV-001 | Scan a small supported repository | Source inventory is complete within declared scope |
| TG-INV-002 | Scan nested source directories | Nested modules are discovered |
| TG-INV-003 | Scan a monorepo with multiple packages | Packages are separated and inventoried |
| TG-INV-004 | Identify application entry points | Entrypoints are listed |
| TG-INV-005 | Identify functions and methods | Symbols and source locations are indexed |
| TG-INV-006 | Identify classes and constructors | Classes, constructors and initialization paths are discovered |
| TG-INV-007 | Identify API routes | Route methods, paths, handlers and dependencies are listed |
| TG-INV-008 | Identify database models and repositories | Persistence boundaries are identified |
| TG-INV-009 | Identify background jobs and workers | Scheduled and asynchronous paths are included |
| TG-INV-010 | Identify external service clients | Integration boundaries are included |
| TG-INV-011 | Identify frontend routes and components | User-facing workflows are discoverable for supported frontend stacks |
| TG-INV-012 | Identify configuration and environment access | Configuration-dependent behaviour is identified |
| TG-INV-013 | Identify queues, events and message handlers | Event-driven paths are included where supported |
| TG-INV-014 | Identify shared utilities | Shared high-impact utilities are identified |
| TG-INV-015 | Exclude dependency/vendor folders | Third-party code is not treated as project-owned code unless explicitly requested |
| TG-INV-016 | Exclude build outputs and generated files | Generated artifacts are excluded or separately classified |
| TG-INV-017 | Handle ignored files and ignore rules | Exclusions are visible and explainable |
| TG-INV-018 | Handle symlinks | No path escape or infinite traversal occurs |
| TG-INV-019 | Handle binary and unsupported files | They are safely skipped and reported |
| TG-INV-020 | Handle a repository with no source files | Clear empty-project result is returned |
| TG-INV-021 | Handle duplicate filenames in different directories | Files remain uniquely identified by normalized path |
| TG-INV-022 | Handle case-sensitive paths | Correct paths are preserved |
| TG-INV-023 | Handle large repository inventory | Pagination/limits and omissions are explicit |
| TG-INV-024 | Compare inventory with repository tree | In-scope files are accounted for |
| TG-INV-025 | Re-run inventory without changes | Stable inventory is reused where appropriate |

---

# 7. Test Requirement Matrix tests

This is the most important test group. The engine must discover what should be tested before generating test code.

| ID | Test | Expected result |
|---|---|---|
| TG-REQ-001 | Generate requirements for a pure utility function | Input classes, output behaviour and edge cases are identified |
| TG-REQ-002 | Generate requirements for a stateful service | State transitions and side effects are identified |
| TG-REQ-003 | Generate requirements for an API endpoint | Request, response, auth, validation and error contracts are identified |
| TG-REQ-004 | Generate requirements for a database repository | CRUD, constraints, transactions and failure behaviour are identified |
| TG-REQ-005 | Generate requirements for an external API client | Success, error, timeout, retry and malformed response cases are identified |
| TG-REQ-006 | Generate requirements for a background worker | Retry, duplicate delivery, idempotency and failure handling are considered |
| TG-REQ-007 | Generate requirements for a frontend form | Validation, submission, loading, success and error states are identified |
| TG-REQ-008 | Generate requirements for a multi-step workflow | Important state transitions and failure points are identified |
| TG-REQ-009 | Include documented business rules | Relevant requirements are extracted and source-linked |
| TG-REQ-010 | Include API schema constraints | Required fields, types, bounds and formats are considered |
| TG-REQ-011 | Include authorization rules | Allowed and denied access scenarios are identified |
| TG-REQ-012 | Include tenant/user isolation rules | Cross-user and cross-tenant access scenarios are considered |
| TG-REQ-013 | Include exception handling branches | Each meaningful exception path has a requirement |
| TG-REQ-014 | Include retry and timeout behaviour | Retry exhaustion and timeout outcomes are considered |
| TG-REQ-015 | Include transaction and rollback behaviour | Partial writes and rollback expectations are considered |
| TG-REQ-016 | Include concurrency-sensitive behaviour | Race and duplicate-operation scenarios are considered where relevant |
| TG-REQ-017 | Include configuration-dependent behaviour | Missing and invalid configuration scenarios are considered |
| TG-REQ-018 | Include security boundaries | Relevant threat scenarios are included |
| TG-REQ-019 | Include regression requirements | Known defects and changed behaviour become explicit requirements |
| TG-REQ-020 | Include performance requirements | Only documented or justified performance expectations are included |
| TG-REQ-021 | Mark irrelevant categories | NOT_APPLICABLE includes a reason |
| TG-REQ-022 | Identify unsupported requirements | Unsupported language/runtime analysis is explicitly labelled |
| TG-REQ-023 | Assign stable requirement IDs | IDs remain stable across unchanged snapshots where feasible |
| TG-REQ-024 | Attach source evidence | Each requirement has paths, symbols, lines or documentation references |
| TG-REQ-025 | Attach expected outcomes | Requirements define observable outcomes, not vague test titles |
| TG-REQ-026 | Detect conflicting documentation and code | Conflict is surfaced; the model does not silently choose an unsupported interpretation |
| TG-REQ-027 | Detect missing specification | Assumptions and uncertainty are recorded |
| TG-REQ-028 | Detect duplicated requirements | Equivalent requirements are merged or linked |
| TG-REQ-029 | Detect requirement dependencies | Preconditions and related requirements are represented |
| TG-REQ-030 | Verify complete requirement status accounting | Every discovered requirement has a status |

---

# 8. Required scenario-category coverage

Run these against representative components in the repository. Categories should be applied when relevant, not forced onto every symbol.

| ID | Scenario category | Expected result |
|---|---|---|
| TG-CAT-001 | Happy path | Normal successful behaviour is covered |
| TG-CAT-002 | Invalid input | Invalid input is rejected safely |
| TG-CAT-003 | Missing input | Missing required fields/arguments are handled |
| TG-CAT-004 | Null/None values | Null-like values are handled according to contract |
| TG-CAT-005 | Empty values | Empty strings, arrays and collections are considered |
| TG-CAT-006 | Minimum boundary | Minimum accepted boundary is tested |
| TG-CAT-007 | Maximum boundary | Maximum accepted boundary is tested |
| TG-CAT-008 | Just below/above boundaries | Off-by-one behaviour is tested |
| TG-CAT-009 | Numeric special values | NaN, positive/negative infinity and precision cases are considered where applicable |
| TG-CAT-010 | Unicode and encoding | Unicode, emoji and non-ASCII input are handled |
| TG-CAT-011 | Large payload | Size limits and resource handling are tested |
| TG-CAT-012 | Malformed serialization | Invalid JSON/XML/etc. is handled where applicable |
| TG-CAT-013 | Exception path | Expected exceptions and error translation are checked |
| TG-CAT-014 | Dependency unavailable | Controlled failure behaviour is tested |
| TG-CAT-015 | Timeout | Timeout handling and cleanup are tested |
| TG-CAT-016 | Retry exhaustion | Final failure after retries is tested |
| TG-CAT-017 | Duplicate request | Idempotency or duplicate handling is verified |
| TG-CAT-018 | Concurrent requests | Shared-state safety is considered |
| TG-CAT-019 | Unauthorized request | Authentication boundary is checked |
| TG-CAT-020 | Forbidden request | Authorization boundary is checked |
| TG-CAT-021 | Cross-user access | User data isolation is checked |
| TG-CAT-022 | Cross-tenant access | Tenant isolation is checked where applicable |
| TG-CAT-023 | State transition | Valid and invalid transitions are tested |
| TG-CAT-024 | Rollback | Partial operation failure does not leave invalid state |
| TG-CAT-025 | Recovery | System can recover from supported transient failures |
| TG-CAT-026 | Resource cleanup | Connections, temporary files and locks are released |
| TG-CAT-027 | Configuration missing | Missing settings produce safe, actionable errors |
| TG-CAT-028 | Configuration invalid | Invalid settings are rejected or safely defaulted |
| TG-CAT-029 | Regression | Previously fixed defect remains fixed |
| TG-CAT-030 | Observability | Important failures produce useful logs without leaking secrets |

---

# 9. Existing test inventory and mapping

| ID | Test | Expected result |
|---|---|---|
| TG-MAP-001 | Discover existing unit tests | Test files and cases are inventoried |
| TG-MAP-002 | Discover integration tests | Integration suites are inventoried |
| TG-MAP-003 | Discover end-to-end tests | E2E suites and workflows are inventoried |
| TG-MAP-004 | Discover fixtures and factories | Reusable test setup is identified |
| TG-MAP-005 | Discover mocks and stubs | Existing mocking conventions are identified |
| TG-MAP-006 | Discover parameterized tests | Parameter sets and scenario coverage are understood |
| TG-MAP-007 | Map test imports to source modules | Candidate relationship is recorded |
| TG-MAP-008 | Map executed tests to source lines | Runtime evidence is recorded when available |
| TG-MAP-009 | Map tests to source symbols | Symbol mapping is evidence-based |
| TG-MAP-010 | Map tests to requirements | Requirement coverage links are created |
| TG-MAP-011 | Handle tests with different names from symbols | Mapping does not rely only on test names |
| TG-MAP-012 | Handle indirect testing through services | Indirect dependency evidence is represented |
| TG-MAP-013 | Handle shared fixtures | Fixture dependencies are tracked |
| TG-MAP-014 | Handle tests that only import but never call target | Import alone is not treated as adequate coverage |
| TG-MAP-015 | Handle tests with no meaningful assertions | Weak test evidence is flagged |
| TG-MAP-016 | Handle skipped tests | Skipped tests do not count as executed coverage |
| TG-MAP-017 | Handle xfail/expected failures | Their special status is preserved |
| TG-MAP-018 | Handle flaky tests | Flaky evidence is not treated as reliable pass evidence |
| TG-MAP-019 | Handle obsolete tests | Stale test mappings are flagged |
| TG-MAP-020 | Rebuild mappings after source changes | Stale mappings are invalidated |

---

# 10. Coverage and gap analysis

| ID | Test | Expected result |
|---|---|---|
| TG-GAP-001 | Analyse repository with no tests | Major requirements are reported missing |
| TG-GAP-002 | Analyse repository with only happy-path tests | Negative and edge-case gaps are identified |
| TG-GAP-003 | Analyse partially covered function | Missing behaviours are identified |
| TG-GAP-004 | Analyse branch coverage | Uncovered branch outcomes are identified |
| TG-GAP-005 | Analyse exception branches | Uncovered exception paths are identified |
| TG-GAP-006 | Analyse endpoint coverage | Route/method/contract gaps are identified |
| TG-GAP-007 | Analyse service integration coverage | Untested service boundaries are identified |
| TG-GAP-008 | Analyse database transaction coverage | Transaction and rollback gaps are identified |
| TG-GAP-009 | Analyse security requirement coverage | Critical security gaps are highlighted |
| TG-GAP-010 | Analyse frontend workflow coverage | Important UI states and user journeys are identified |
| TG-GAP-011 | Compare requirement coverage and line coverage | Metrics remain distinct |
| TG-GAP-012 | Compare requirement coverage and branch coverage | Metrics remain distinct |
| TG-GAP-013 | Analyse tests that execute code but assert nothing meaningful | Requirement is not marked adequately covered |
| TG-GAP-014 | Analyse duplicated tests | Duplicate scenarios are identified |
| TG-GAP-015 | Analyse tests with excessive mocking | Behavioural integration gaps are surfaced |
| TG-GAP-016 | Analyse unsupported code | Unsupported areas are reported, not counted as covered |
| TG-GAP-017 | Analyse unexecuted generated tests | They do not count as executed coverage |
| TG-GAP-018 | Analyse timed-out tests | They are not marked as passing |
| TG-GAP-019 | Analyse skipped tests | They remain uncovered unless separate evidence exists |
| TG-GAP-020 | Produce complete gap report | Every requirement has covered/partial/missing/blocked/unsupported/N/A status |

---

# 11. Prioritisation tests

Prioritisation must not be based only on model intuition.

| ID | Test | Expected result |
|---|---|---|
| TG-PRI-001 | Critical authentication requirement | High priority |
| TG-PRI-002 | Authorization/tenant-isolation requirement | High priority |
| TG-PRI-003 | Payment or irreversible operation (if present) | High priority |
| TG-PRI-004 | Data-loss or corruption risk | High priority |
| TG-PRI-005 | Public API contract requirement | Priority reflects exposure and impact |
| TG-PRI-006 | Frequently changed high-centrality module | Change and dependency risk influence priority |
| TG-PRI-007 | Low-risk formatting helper | Lower priority than critical business/security paths |
| TG-PRI-008 | Requirement with no evidence | Uncertainty is visible |
| TG-PRI-009 | Requirement with existing reliable coverage | Not unnecessarily regenerated |
| TG-PRI-010 | Requirement with weak existing test | Prioritised for improvement |
| TG-PRI-011 | Priority explanation | Factors and evidence are visible |
| TG-PRI-012 | Priority stability | Equivalent inputs produce reasonably stable ranking |
| TG-PRI-013 | User changes priority settings | User configuration is respected |
| TG-PRI-014 | Limited generation budget | Highest-risk missing requirements are selected first |
| TG-PRI-015 | Full repository run | Lower-priority requirements remain visible even if deferred |

Suggested priority factors:

- Business criticality.
- Security and privacy impact.
- Data integrity impact.
- Dependency centrality and blast radius.
- Change frequency.
- Existing coverage quality.
- Failure likelihood when evidence exists.
- User-defined priority.
- Cost and feasibility of testing.

Do not fabricate failure probabilities or claim an empirically calibrated risk score without data.

---

# 12. Test planning and generation tests

| ID | Test | Expected result |
|---|---|---|
| TG-PLAN-001 | Plan tests for a pure function | Input partitions and expected outputs are defined |
| TG-PLAN-002 | Plan tests for a complex service | Dependencies and setup requirements are identified |
| TG-PLAN-003 | Plan tests for an API endpoint | Request/response and access-control cases are defined |
| TG-PLAN-004 | Plan tests for database operations | Disposable database/transaction strategy is defined |
| TG-PLAN-005 | Plan tests for external integrations | Appropriate mocks/fakes or sandbox dependencies are selected |
| TG-PLAN-006 | Plan tests for async functions | Async test conventions are followed |
| TG-PLAN-007 | Plan tests for background jobs | Retry, duplicate delivery and idempotency are considered |
| TG-PLAN-008 | Plan tests for frontend components | User interactions and visible outcomes are specified |
| TG-PLAN-009 | Plan tests for a multi-module workflow | Cross-module requirements are linked |
| TG-PLAN-010 | Plan tests with existing fixtures | Existing reusable fixtures are preferred |
| TG-PLAN-011 | Plan tests with unavailable dependencies | Blocked dependencies are reported |
| TG-PLAN-012 | Plan tests for unsupported language | No fake test code is produced |
| TG-PLAN-013 | Generate scenario matrix before code | Plan is inspectable independently of generated code |
| TG-PLAN-014 | Verify scenario-to-requirement mapping | Every planned scenario references requirement IDs |
| TG-PLAN-015 | Verify expected outcomes | Scenarios define observable assertions |
| TG-PLAN-016 | Verify setup/teardown | Resource lifecycle is planned |
| TG-PLAN-017 | Verify scenario diversity | Duplicate scenarios are minimised |
| TG-PLAN-018 | Verify plan completeness | All selected requirements have a plan or explicit reason for exclusion |

---

# 13. Generated test correctness and quality

| ID | Test | Expected result |
|---|---|---|
| TG-GEN-001 | Generate test for normal behaviour | Test asserts correct expected result |
| TG-GEN-002 | Generate invalid-input test | Rejection/error behaviour is asserted |
| TG-GEN-003 | Generate boundary tests | Boundary values and outcomes are correct |
| TG-GEN-004 | Generate null/empty-value tests | Contract-specific behaviour is checked |
| TG-GEN-005 | Generate exception tests | Correct exception/error contract is asserted |
| TG-GEN-006 | Generate authorization tests | Allowed and denied cases are distinct |
| TG-GEN-007 | Generate database tests | Isolated test data and cleanup are used |
| TG-GEN-008 | Generate integration tests | Correct integration boundary is exercised |
| TG-GEN-009 | Generate async tests | Correct async runner and await behaviour are used |
| TG-GEN-010 | Generate parameterized tests | Parameters cover distinct partitions |
| TG-GEN-011 | Generate tests using repository fixtures | Existing fixture conventions are followed |
| TG-GEN-012 | Generate tests with mocks | Mocks verify meaningful interactions and are not excessive |
| TG-GEN-013 | Generate test for indirect dependency | Required dependency setup is included |
| TG-GEN-014 | Generate test for branch condition | Test input reaches intended branch |
| TG-GEN-015 | Generate test for regression requirement | Test reproduces the defect condition and asserts corrected behaviour |
| TG-GEN-016 | Generate test for idempotency | Repeated operation outcome is asserted |
| TG-GEN-017 | Generate test for transaction rollback | Persistent state is checked after failure |
| TG-GEN-018 | Generate test for timeout/retry | Timing and retry assertions are deterministic |
| TG-GEN-019 | Generate test for concurrency | Synchronisation is deterministic; no arbitrary sleeps |
| TG-GEN-020 | Generate test for security boundary | Test verifies the actual security property |
| TG-GEN-021 | Generate test for frontend state | Visible/user-observable behaviour is asserted |
| TG-GEN-022 | Generate test for API contract | Schema, status and response semantics are asserted |
| TG-GEN-023 | Inspect assertions | Tests do not merely call the target without checking outcomes |
| TG-GEN-024 | Inspect test independence | Tests do not depend on execution order |
| TG-GEN-025 | Inspect random data | Randomness is seeded or controlled |
| TG-GEN-026 | Inspect time-dependent tests | Clock is controlled or assertions are robust |
| TG-GEN-027 | Inspect test names | Names describe behaviour and scenario |
| TG-GEN-028 | Inspect duplicate tests | Redundant tests are flagged |
| TG-GEN-029 | Inspect generated code provenance | Source and requirement references are available |
| TG-GEN-030 | Inspect generated test readability | Setup, action and assertion are understandable |

---

# 14. Coverage-guided generation and refinement

This group verifies the feedback loop inspired by coverage-guided test generation research.

| ID | Test | Expected result |
|---|---|---|
| TG-COV-001 | Run baseline coverage before generation | Baseline coverage is stored |
| TG-COV-002 | Run coverage after generation | New coverage is measured from actual execution |
| TG-COV-003 | Compare baseline and final line coverage | Delta is calculated correctly |
| TG-COV-004 | Compare branch coverage | Branch delta is calculated when supported |
| TG-COV-005 | Generate for uncovered branch | New test reaches the intended branch |
| TG-COV-006 | Generate test that does not improve coverage | It is flagged and not counted as improvement |
| TG-COV-007 | Generate test with no meaningful assertion | Coverage gain does not automatically imply quality |
| TG-COV-008 | Generate duplicate tests | Diversity analysis identifies redundancy |
| TG-COV-009 | Run refinement after test failure | Repair is bounded and failure cause is recorded |
| TG-COV-010 | Run refinement after no coverage gain | Planner selects a different input/strategy or stops |
| TG-COV-011 | Reach generation attempt limit | Run ends with explicit unresolved gaps |
| TG-COV-012 | Reach token/time budget | Run ends safely and reports deferred requirements |
| TG-COV-013 | Re-measure after repair | Metrics reflect final executed test version |
| TG-COV-014 | Compare coverage by file/symbol | Local coverage is traceable |
| TG-COV-015 | Verify generated tests are included in measurement | Correct test set is measured |
| TG-COV-016 | Verify pre-existing tests remain included | Baseline suite is not accidentally excluded |
| TG-COV-017 | Verify exclusions and coverage configuration | Excluded files are visible |
| TG-COV-018 | Handle coverage tool unavailable | Coverage is unknown, not fabricated |
| TG-COV-019 | Handle partial coverage data | Partial state and missing scope are reported |
| TG-COV-020 | Verify no infinite refinement loop | Bounded stopping conditions work |

---

# 15. Mutation testing and assertion-strength tests

Mutation testing is optional when the language/tooling does not support it, but the platform must report that limitation.

| ID | Test | Expected result |
|---|---|---|
| TG-MUT-001 | Run mutation analysis on supported fixture | Mutants are generated and results recorded |
| TG-MUT-002 | Verify a strong assertion kills a relevant mutant | Mutant is detected |
| TG-MUT-003 | Verify a weak assertion allows mutant to survive | Weakness is surfaced |
| TG-MUT-004 | Distinguish killed mutants | Correctly detected mutants are counted |
| TG-MUT-005 | Distinguish survived mutants | Surviving mutants are reported |
| TG-MUT-006 | Distinguish timed-out mutants | Timeout is not counted as killed |
| TG-MUT-007 | Distinguish equivalent/unviable mutants | Tool classifications are preserved |
| TG-MUT-008 | Generate tests for surviving mutants | New test candidates target the changed behaviour |
| TG-MUT-009 | Re-run mutation analysis after generation | Updated score is measured |
| TG-MUT-010 | Mutation tool unsupported | Score is null/unavailable, not zero or fabricated |
| TG-MUT-011 | Mutation budget exhausted | Partial result is labelled |
| TG-MUT-012 | Verify mutation score denominator | Excluded/equivalent mutants are treated according to tool semantics |

---

# 16. Test execution and isolation

| ID | Test | Expected result |
|---|---|---|
| TG-RUN-001 | Execute one generated unit test | Actual result is captured |
| TG-RUN-002 | Execute complete generated test suite | Suite summary is captured |
| TG-RUN-003 | Execute existing and generated tests together | Regression impact is visible |
| TG-RUN-004 | Execute with timeout | Process is terminated safely |
| TG-RUN-005 | Execute code that attempts filesystem escape | Access is blocked |
| TG-RUN-006 | Execute code that attempts network access | Network policy is enforced |
| TG-RUN-007 | Execute code that attempts to read host secrets | Secrets are unavailable |
| TG-RUN-008 | Execute code that attempts subprocess abuse | Process restrictions are enforced |
| TG-RUN-009 | Execute destructive database test | Only disposable test database is affected |
| TG-RUN-010 | Execute test that creates temporary files | Files are confined and cleaned |
| TG-RUN-011 | Execute test that leaves background process | Process is terminated/cleaned |
| TG-RUN-012 | Execute test with infinite loop | Timeout and resource limits stop it |
| TG-RUN-013 | Execute test with excessive memory use | Resource limit is enforced |
| TG-RUN-014 | Execute test with excessive output | Output is bounded |
| TG-RUN-015 | Execute tests concurrently | Isolation prevents cross-run contamination |
| TG-RUN-016 | Cancel active run | Child processes and resources are cleaned |
| TG-RUN-017 | Runner unavailable | Run is BLOCKED, not PASSED |
| TG-RUN-018 | Dependency installation fails | Failure and safe recovery are reported |
| TG-RUN-019 | Test process crashes | Exit code and diagnostics are recorded |
| TG-RUN-020 | Runner restarts during execution | Run state is reconciled; no false success |
| TG-RUN-021 | Execute tests with environment variables | Only explicitly allowed variables are passed |
| TG-RUN-022 | Execute tests with credentials in repository | Secrets are masked and not transmitted to the LLM |
| TG-RUN-023 | Execute tests against external service | Only an explicitly configured sandbox is used |
| TG-RUN-024 | Verify cleanup after failure | Temporary resources are removed |
| TG-RUN-025 | Verify test output parsing | Passed/failed/skipped/error counts match runner output |

---

# 17. Test Generation API and persistence tests

Adapt endpoint names to the actual routes found in the repository.

| ID | Test | Expected result |
|---|---|---|
| TG-API-001 | Submit valid full-repository request | Request is accepted and run ID returned |
| TG-API-002 | Submit valid targeted request | Target and dependencies are resolved |
| TG-API-003 | Submit valid change-based request | Changed files/commit are resolved |
| TG-API-004 | Submit nonexistent repository ID | Safe not-found response |
| TG-API-005 | Submit nonexistent target path | Validation error |
| TG-API-006 | Submit invalid symbol ID | Validation error |
| TG-API-007 | Submit unsupported framework | Explicit unsupported result |
| TG-API-008 | Submit invalid mode | Schema validation error |
| TG-API-009 | Submit malformed payload | Safe client error |
| TG-API-010 | Submit unauthenticated request | Authentication enforced |
| TG-API-011 | Submit unauthorized repository request | Access denied |
| TG-API-012 | Request another user's run | Access denied |
| TG-API-013 | Fetch run history | Only authorised records returned |
| TG-API-014 | Fetch run detail | Correct requirements, tests and status returned |
| TG-API-015 | Cancel a run | Cancellation state is persisted |
| TG-API-016 | Retry failed generation | New attempt is linked to prior run |
| TG-API-017 | Submit duplicate request | Idempotency/deduplication policy is followed |
| TG-API-018 | Persist requirement matrix | Records are linked to repository and snapshot |
| TG-API-019 | Persist generated test metadata | Paths, IDs, status and provenance are stored |
| TG-API-020 | Persist execution result | Exit status and timestamps are stored |
| TG-API-021 | Persist quality metrics | Unknown metrics remain null/unavailable |
| TG-API-022 | Database unavailable during persistence | Failure is surfaced; no false completed state |
| TG-API-023 | Partial persistence failure | Run is recoverable or marked partial |
| TG-API-024 | Query stale run | Snapshot mismatch is visible |
| TG-API-025 | Delete/retention policy applies | Only eligible data is removed |
| TG-API-026 | Verify tenant/user ownership | No cross-user data leakage |
| TG-API-027 | Verify pagination | Large history is paginated |
| TG-API-028 | Verify API response schema | Frontend and backend contract agree |

---

# 18. LLM planning, generation and review tests

| ID | Test | Expected result |
|---|---|---|
| TG-LLM-001 | Planner receives complete context | Structured requirements are returned |
| TG-LLM-002 | Planner receives incomplete context | Uncertainty and missing evidence are returned |
| TG-LLM-003 | Planner invents source path | Grounding validator rejects it |
| TG-LLM-004 | Planner invents function | Grounding validator rejects it |
| TG-LLM-005 | Generator produces malformed JSON | Bounded repair or safe failure |
| TG-LLM-006 | Generator produces invalid test code | Static validation catches it |
| TG-LLM-007 | Generator imports nonexistent dependency | Import/static validation catches it |
| TG-LLM-008 | Generator references nonexistent fixture | Validation catches it |
| TG-LLM-009 | Generator creates a test with no assertion | Quality reviewer flags it |
| TG-LLM-010 | Generator repeats an existing test | Duplicate detection flags it |
| TG-LLM-011 | Generator ignores a high-priority requirement | Completeness review flags it |
| TG-LLM-012 | Reviewer identifies unsupported assumptions | Assumptions are surfaced |
| TG-LLM-013 | Reviewer rejects unsafe test code | Test is blocked |
| TG-LLM-014 | LLM provider times out | Controlled retry/failure |
| TG-LLM-015 | LLM rate limit reached | Backoff and clear status |
| TG-LLM-016 | LLM returns empty output | Safe failure |
| TG-LLM-017 | LLM returns oversized output | Output is bounded |
| TG-LLM-018 | LLM response exceeds token budget | Truncation/repair does not silently remove critical requirements |
| TG-LLM-019 | LLM provider unavailable | Run is blocked or fallback follows configured policy |
| TG-LLM-020 | Retry budget exhausted | Run ends with clear error |
| TG-LLM-021 | Prompt contains repository text | Repository content is treated as untrusted data |
| TG-LLM-022 | Repository file contains prompt injection | Instructions inside repository content are not followed |
| TG-LLM-023 | Test fixture contains secret-looking values | Secrets are not copied into prompts or reports |
| TG-LLM-024 | Review stage receives generated tests | It independently checks correctness and completeness |
| TG-LLM-025 | Same input is submitted twice | Duplicate generation is controlled or explained |
| TG-LLM-026 | Model output has unsupported claims | Claims are rejected or marked uncertain |
| TG-LLM-027 | Structured schema validation fails | Invalid result is not persisted as successful |
| TG-LLM-028 | Generation result has missing requirement links | Traceability validation fails |
| TG-LLM-029 | Model proposes a test for irrelevant category | Planner/reviewer rejects or marks N/A with reason |
| TG-LLM-030 | Token usage instrumentation exists | Prompt/completion usage is recorded accurately |

---

# 19. Security and privacy tests

Use isolated fixtures and non-production accounts. Never exploit a live third-party service.

| ID | Test | Expected result |
|---|---|---|
| TG-SEC-001 | Repository path traversal attempt | Access outside repository is blocked |
| TG-SEC-002 | Symlink points outside repository | External target is not read |
| TG-SEC-003 | Generated test attempts arbitrary file read | Runner sandbox blocks access |
| TG-SEC-004 | Generated test attempts arbitrary file write | Runner sandbox blocks access |
| TG-SEC-005 | Generated test attempts network exfiltration | Network restriction blocks it |
| TG-SEC-006 | Generated test attempts command execution | Process policy blocks unauthorised commands |
| TG-SEC-007 | Malicious filename | Path handling remains safe |
| TG-SEC-008 | Malicious test output | Output is escaped in UI |
| TG-SEC-009 | HTML/script in test names or logs | No frontend script execution |
| TG-SEC-010 | Prompt injection in source comments | Treated as untrusted repository data |
| TG-SEC-011 | Prompt injection in README/docs | Does not override system instructions |
| TG-SEC-012 | Secret in source fixture | Redacted or excluded from LLM context |
| TG-SEC-013 | Secret in exception traceback | Redacted from user-visible logs |
| TG-SEC-014 | Cross-user run access | Denied |
| TG-SEC-015 | Cross-repository access | Denied |
| TG-SEC-016 | Unauthorized test-run cancellation | Denied |
| TG-SEC-017 | Unauthorized generated-file retrieval | Denied |
| TG-SEC-018 | Dependency install from untrusted source | Policy-controlled; no silent arbitrary install |
| TG-SEC-019 | Malicious package lifecycle script | Isolated installation policy prevents host compromise |
| TG-SEC-020 | Resource exhaustion attempt | CPU, memory, disk, process and time limits apply |
| TG-SEC-021 | Concurrent run isolation | One run cannot inspect another run's files |
| TG-SEC-022 | Log injection | Logs remain structured and safe |
| TG-SEC-023 | Sensitive repository metadata | Access follows repository permissions |
| TG-SEC-024 | User-provided test command | Allowlist/approval policy is enforced |
| TG-SEC-025 | Verify audit trail | Run creator, snapshot, actions and result are recorded |

---

# 20. Snapshot, revision and incremental update tests

| ID | Test | Expected result |
|---|---|---|
| TG-REV-001 | Generate tests at commit A | Run references commit A |
| TG-REV-002 | Change target file to commit B | New run uses commit B |
| TG-REV-003 | Change dependency only | Related requirements are invalidated |
| TG-REV-004 | Change test file only | Test inventory/mapping is refreshed |
| TG-REV-005 | Rename source symbol | Old mapping is invalidated and new mapping created |
| TG-REV-006 | Delete source file | Related requirements are marked stale/removed appropriately |
| TG-REV-007 | Switch branch | Context and test mappings follow selected branch |
| TG-REV-008 | Rebase branch | Commit identity is refreshed |
| TG-REV-009 | Generate during repository update | Run uses one consistent snapshot |
| TG-REV-010 | Snapshot build fails | Last good snapshot remains available but is marked stale |
| TG-REV-011 | Partial index update | No false complete snapshot |
| TG-REV-012 | Re-run unchanged repository | Reusable evidence is reused |
| TG-REV-013 | Compare two snapshots | Added/removed/changed requirements are identified |
| TG-REV-014 | Retrieve old run after new commit | Historical run remains tied to old commit |
| TG-REV-015 | Verify cached generated plan | Cache key includes relevant revision/context inputs |
| TG-REV-016 | Verify cache invalidation | Changed dependencies invalidate affected plans |
| TG-REV-017 | Verify requirement ID stability | Unchanged requirements retain identity where feasible |
| TG-REV-018 | Verify no cross-branch cache leakage | Branch-specific context remains isolated |

---

# 21. Frontend and user experience tests

Adapt component paths to the actual frontend implementation.

| ID | Test | Expected result |
|---|---|---|
| TG-UI-001 | Open Test Generation Studio | Page loads without runtime errors |
| TG-UI-002 | Choose full repository mode | Correct controls and description appear |
| TG-UI-003 | Choose targeted mode | Target selection is available |
| TG-UI-004 | Choose change-based mode | Commit/branch/change selection is available |
| TG-UI-005 | Start repository analysis | Progress state is shown |
| TG-UI-006 | Display requirement dashboard | Counts and statuses match backend |
| TG-UI-007 | Filter by requirement category | Results filter correctly |
| TG-UI-008 | Filter by priority | Critical/high/medium/low filters work |
| TG-UI-009 | Inspect requirement details | Evidence, expected behaviour and related symbols appear |
| TG-UI-010 | Inspect existing coverage | Evidence level is visible |
| TG-UI-011 | Select missing requirements | Selection state is accurate |
| TG-UI-012 | Generate selected tests | Correct requirements are submitted |
| TG-UI-013 | Generate all eligible tests | All selected eligible requirements are included |
| TG-UI-014 | Display generation progress | Planning, generation, validation and execution states are distinguishable |
| TG-UI-015 | Display generated files | File paths and contents are accessible |
| TG-UI-016 | Display test execution result | Passed/failed/skipped/blocked states are distinct |
| TG-UI-017 | Display coverage changes | Before/after values are accurate |
| TG-UI-018 | Display requirement coverage | Not confused with line coverage |
| TG-UI-019 | Display mutation score | Hidden or unavailable when not measured |
| TG-UI-020 | Display missing requirements | Critical gaps are prominent |
| TG-UI-021 | Display unsupported areas | Unsupported scope is explicit |
| TG-UI-022 | Cancel generation | UI and backend cancellation state agree |
| TG-UI-023 | Recover after refresh | Run state is restored |
| TG-UI-024 | Handle API error | Useful error state and retry action appear |
| TG-UI-025 | Handle empty repository | Empty-state explanation appears |
| TG-UI-026 | Handle large requirement matrix | Pagination/virtualisation keeps UI responsive |
| TG-UI-027 | Handle narrow desktop/laptop viewport | Layout remains usable |
| TG-UI-028 | Handle keyboard navigation | Controls are accessible |
| TG-UI-029 | Handle long paths and symbol names | Text does not break layout |
| TG-UI-030 | Export/download test report | Export matches displayed data |
| TG-UI-031 | Approve generated files | Only explicitly selected files are approved |
| TG-UI-032 | Reject generated files | Rejected files are not saved to project |
| TG-UI-033 | Display stale snapshot warning | User sees which revision was analysed |
| TG-UI-034 | Display partial run | Partial result is not represented as complete |
| TG-UI-035 | Verify status labels | Generated, validated, executed and passed are distinct |

---

# 22. Performance, scalability and resilience tests

Use representative repository sizes and record actual measurements. Do not invent universal timing thresholds; establish targets from measured baselines.

| ID | Test | Expected result |
|---|---|---|
| TG-PERF-001 | Small repository | Analysis completes within configured budget |
| TG-PERF-002 | Medium repository | Memory and latency remain within configured limits |
| TG-PERF-003 | Large repository | Bounded traversal and pagination work |
| TG-PERF-004 | Monorepo | Package-level planning avoids uncontrolled context expansion |
| TG-PERF-005 | Repository with many tests | Test inventory remains responsive |
| TG-PERF-006 | Repository with many symbols | Graph retrieval remains bounded |
| TG-PERF-007 | Repository with deep dependency chain | Traversal depth limit is respected |
| TG-PERF-008 | Highly connected graph | Ranking prevents context explosion |
| TG-PERF-009 | Concurrent generation runs | Runs remain isolated and within capacity |
| TG-PERF-010 | Concurrent runner executions | Resource quotas are enforced |
| TG-PERF-011 | LLM slow response | Timeout and cancellation work |
| TG-PERF-012 | LLM provider outage | Graceful failure and recovery |
| TG-PERF-013 | Database outage | No false completed run |
| TG-PERF-014 | Redis/cache outage | Safe fallback or explicit blocked state |
| TG-PERF-015 | Runner outage | Generation and execution statuses remain separate |
| TG-PERF-016 | Worker restart | Job recovery is safe and idempotent |
| TG-PERF-017 | User cancels long run | Work stops within configured cancellation policy |
| TG-PERF-018 | Token budget exhausted | Run ends with prioritised deferred requirements |
| TG-PERF-019 | Disk/output limit reached | Safe failure and cleanup |
| TG-PERF-020 | Repeated identical request | Cache/deduplication policy reduces unnecessary work |
| TG-PERF-021 | Incremental repository update | Only affected test intelligence is refreshed |
| TG-PERF-022 | Record token usage | Input/output token accounting is accurate |
| TG-PERF-023 | Record model calls | Calls, retries and failures are traceable |
| TG-PERF-024 | Record execution duration | Runner time is separated from generation time |
| TG-PERF-025 | Record context retrieval duration | Retrieval bottlenecks are visible |

---

# 23. Framework and language adapter tests

The current implementation must be audited to determine which adapters really exist. Run only applicable tests and mark unsupported ones honestly.

| ID | Test | Expected result |
|---|---|---|
| TG-LANG-001 | Python pytest project | Correct pytest conventions |
| TG-LANG-002 | Python unittest project | Correct unittest conventions |
| TG-LANG-003 | JavaScript Jest project | Correct Jest conventions if implemented |
| TG-LANG-004 | TypeScript project | Type-aware imports and test syntax if supported |
| TG-LANG-005 | React component project | Correct component testing conventions if supported |
| TG-LANG-006 | FastAPI project | Route/dependency testing patterns if supported |
| TG-LANG-007 | Flask project | Application/client fixture patterns if supported |
| TG-LANG-008 | Django project | Django test/database conventions if supported |
| TG-LANG-009 | Node API project | API and async test patterns if supported |
| TG-LANG-010 | Mixed-language monorepo | Each package is classified independently |
| TG-LANG-011 | Missing test configuration | Safe detection and setup guidance |
| TG-LANG-012 | Conflicting test frameworks | Conflict is surfaced |
| TG-LANG-013 | Multiple test roots | Correct test root selection |
| TG-LANG-014 | Custom test command | Only approved command policy is used |
| TG-LANG-015 | Unsupported language | No misleading generated test |
| TG-LANG-016 | Framework version mismatch | Compatibility failure is reported |
| TG-LANG-017 | Type checker/linter unavailable | Static checks are marked unavailable |
| TG-LANG-018 | Adapter-specific fixtures | Existing project conventions are respected |

---

# 24. Full repository completeness tests

These tests specifically prevent the feature from generating only a few passing unit tests and declaring success.

| ID | Test | Expected result |
|---|---|---|
| TG-COMP-001 | Repository has multiple application modules | Requirements are discovered across all in-scope modules |
| TG-COMP-002 | Repository has API, service and database layers | All three layers are considered |
| TG-COMP-003 | Repository has frontend and backend | Both are included if supported |
| TG-COMP-004 | Repository has authentication and authorization | Relevant access-control requirements are included |
| TG-COMP-005 | Repository has external integrations | Integration failure and contract scenarios are included |
| TG-COMP-006 | Repository has asynchronous jobs | Worker lifecycle and retry scenarios are included |
| TG-COMP-007 | Repository has shared utilities | High-impact shared behaviour is considered |
| TG-COMP-008 | Repository has configuration-driven branches | Configuration variants are considered |
| TG-COMP-009 | Repository has multiple user roles | Role-based behaviour is considered |
| TG-COMP-010 | Repository has data ownership boundaries | Ownership/isolation tests are considered |
| TG-COMP-011 | Repository has state machines/workflows | Valid and invalid transitions are considered |
| TG-COMP-012 | Repository has transaction boundaries | Commit/rollback behaviour is considered |
| TG-COMP-013 | Repository has caching | Cache hit/miss/invalidation/stale data behaviour is considered |
| TG-COMP-014 | Repository has rate limiting | Threshold and bypass behaviour are considered |
| TG-COMP-015 | Repository has file uploads/downloads | Size, type, path, permission and failure cases are considered |
| TG-COMP-016 | Repository has search/retrieval | Empty, irrelevant, malformed and permission-filtered results are considered |
| TG-COMP-017 | Repository has LLM/provider integrations | Provider failure, malformed output, budget and prompt-injection cases are considered |
| TG-COMP-018 | Repository has background cleanup/retention | Expiry and deletion rules are considered |
| TG-COMP-019 | Repository has webhook/event handlers | Signature, duplicate delivery and ordering are considered |
| TG-COMP-020 | Repository has admin features | Admin-only access and audit behaviour are considered |
| TG-COMP-021 | Repository has no relevant feature category | It is marked N/A with evidence |
| TG-COMP-022 | Repository contains unsupported modules | Unsupported modules are counted and disclosed |
| TG-COMP-023 | Run full-repository generation with limited budget | Deferred requirements remain visible |
| TG-COMP-024 | Compare discovered requirements with repository inventory | In-scope testable components have accounted-for status |
| TG-COMP-025 | Final report claims completeness | Claim is supported by inventory, requirements and limitations evidence |

---

# 25. Change-based test generation

| ID | Test | Expected result |
|---|---|---|
| TG-CHG-001 | Change a pure function | Direct tests are recommended |
| TG-CHG-002 | Change a shared utility | Dependent modules are identified |
| TG-CHG-003 | Change a public API schema | Contract and downstream tests are recommended |
| TG-CHG-004 | Change a database model | Related repositories, services and migrations are considered |
| TG-CHG-005 | Change authentication logic | Security and regression tests are prioritised |
| TG-CHG-006 | Change an external client | Integration/error tests are recommended |
| TG-CHG-007 | Change a frontend component | Component and affected workflow tests are recommended |
| TG-CHG-008 | Change a function signature | Callers and dependent tests are invalidated |
| TG-CHG-009 | Rename a symbol | Old references are reconciled |
| TG-CHG-010 | Delete a module | Obsolete tests and broken dependants are identified |
| TG-CHG-011 | Change only documentation | Behavioural test requirements are not invented without evidence |
| TG-CHG-012 | Change only test files | Test inventory and quality analysis refresh |
| TG-CHG-013 | Change configuration | Configuration-dependent requirements are refreshed |
| TG-CHG-014 | Change dependency version | Compatibility tests are considered |
| TG-CHG-015 | Change multiple related files | One coherent change-based plan is created |
| TG-CHG-016 | Compare branches | Correct merge-base/diff semantics are used |
| TG-CHG-017 | Change-based run with stale graph | Run refreshes or blocks stale context |
| TG-CHG-018 | Change with no testable impact | Reasoned no-test recommendation is returned |

---

# 26. Three mandatory end-to-end scenarios

## E2E-001: Full repository first-time test generation

**Fixture:** a representative supported repository with source modules, API endpoints, database models, existing tests, documentation and at least one external integration.

Steps:

1. Connect the repository.
2. Build or load Repository Intelligence.
3. Record the snapshot and commit.
4. Run full repository inventory.
5. Discover test requirements.
6. Inventory existing tests and fixtures.
7. Run baseline tests and coverage.
8. Build the requirement matrix.
9. Review missing and partially covered requirements.
10. Generate tests for selected high-priority gaps.
11. Run static validation.
12. Execute in the isolated runner.
13. Measure coverage and quality.
14. Run bounded refinement for useful uncovered requirements.
15. Run the existing suite again.
16. Produce the final report.

Expected:

- All in-scope components have an accounted-for status.
- Requirements are evidence-linked.
- Existing coverage is not guessed.
- Generated tests are traceable.
- Executed and unexecuted tests are distinct.
- Missing critical requirements remain visible.
- No existing tests are silently overwritten.
- Final report identifies unsupported and blocked scope.

## E2E-002: Targeted generation with dependency context

Fixture: a selected service function that depends on a model, helper, database repository and external client.

Steps:

1. Select the target symbol.
2. Select one explicit related file.
3. Retrieve automatic dependency context.
4. Verify selected and automatic context provenance.
5. Retrieve existing tests and fixtures.
6. Build target-specific requirements.
7. Identify uncovered requirements.
8. Generate tests.
9. Validate and execute tests.
10. Inspect requirement-to-test traceability.

Expected:

- Explicit selection is prioritised.
- Relevant dependencies are included.
- Unrelated repository files do not overwhelm context.
- Indirect behaviour is considered.
- Missing dependencies are not fabricated.

## E2E-003: Change-based regression generation

Fixture: a commit changes a shared utility used by multiple services.

Steps:

1. Select base and target revisions.
2. Resolve changed files and symbols.
3. Retrieve reverse dependency/blast-radius context.
4. Identify affected requirements and existing tests.
5. Compare baseline coverage.
6. Generate missing regression tests.
7. Execute generated and existing affected tests.
8. Compare results and coverage.
9. Save a report pinned to the target commit.

Expected:

- Direct and affected dependent behaviours are considered.
- Unaffected areas are not needlessly regenerated.
- Tests use one consistent revision.
- Regression failures are clearly reported.

---

# 27. Required test fixtures

Create small, controlled fixtures rather than relying only on the production repository.

| Fixture | Required characteristics |
|---|---|
| FIX-001 Simple utility | Pure functions, normal and boundary cases |
| FIX-002 Branch-heavy module | Nested conditions and uncovered branches |
| FIX-003 API service | Validation, auth, status codes and response schema |
| FIX-004 Database service | CRUD, constraints, transaction and rollback |
| FIX-005 External client | Timeout, retry, malformed response and provider failure |
| FIX-006 Async worker | Duplicate delivery, retry and idempotency |
| FIX-007 Security module | Role checks, ownership and tenant isolation |
| FIX-008 Frontend component | Form, loading, error and success states |
| FIX-009 Existing test suite | Good tests, weak tests, skipped tests and duplicate tests |
| FIX-010 Prompt-injection repository | Malicious instructions in comments/docs/fixtures |
| FIX-011 Large monorepo | Multiple packages and bounded context |
| FIX-012 Unsupported-language folder | Honest unsupported-scope reporting |
| FIX-013 Stale snapshot fixture | Source changes after indexing |
| FIX-014 Flaky test fixture | Controlled nondeterminism for detection |
| FIX-015 Mutation fixture | Simple mutants that should be detected by strong tests |

Possible external research/benchmark references:

- CoverUp: https://github.com/plasma-umass/coverup
- Pynguin: https://github.com/se2p/pynguin
- CODAMOSA: https://github.com/microsoft/codamosa
- EvoSuite: https://github.com/EvoSuite/evosuite
- CodeQL: https://github.com/github/codeql
- Semgrep rules: https://github.com/semgrep/semgrep-rules
- OWASP Juice Shop: https://github.com/juice-shop/juice-shop
- WebGoat: https://github.com/WebGoat/WebGoat

Use external repositories only as controlled fixtures or research references. Do not assume their licences, dependencies or security posture permit unrestricted integration into this product.

---

# 28. Acceptance gates

These are proposed engineering release gates. Adjust numeric thresholds after establishing a representative baseline.

## Gate A — Requirement discovery

- Every in-scope module has an accounted-for status.
- Every discovered requirement has a stable ID and evidence.
- Critical requirements are explicitly identified.
- Unsupported and not-applicable areas are visible.
- Requirement discovery is not limited to the selected function in full-repository mode.

## Gate B — Traceability

- Every generated test maps to at least one requirement.
- Every requirement has a coverage status.
- Test-to-source mapping uses evidence stronger than test names/imports alone.
- Snapshot and commit metadata are retained.

## Gate C — Correctness and execution

- Generated files pass static validation before execution.
- Execution happens only in the isolated runner.
- Actual runner outcomes are persisted.
- Existing tests are preserved.
- Baseline and post-generation test results are compared.

## Gate D — Quality

- Meaningful assertions are present.
- Duplicate scenarios are identified.
- Coverage deltas are measured.
- Branch coverage is reported when supported.
- Mutation score is reported only when mutation analysis actually runs.
- Weak, flaky and unsupported tests are identified.

## Gate E — Completeness and honesty

- No success claim is based only on test count or passing status.
- No critical missing requirement is hidden by aggregate coverage.
- Deferred requirements remain visible after budget exhaustion.
- Unsupported languages and modules are reported.
- A partial run is never represented as complete.

## Gate F — Security and reliability

- Generated code cannot access host secrets or arbitrary host files.
- Filesystem and network access follow sandbox policy.
- Resource and time limits are enforced.
- Cancellation and cleanup work.
- Cross-user/repository access is denied.

---

# 29. Required result report format

Create `Docs/testing/test_generation_feature_testing_result.md` with this structure.

## 29.1 Run metadata

- Repository:
- Branch:
- Commit SHA:
- Repository Intelligence snapshot ID:
- Test Generation version/build:
- Date:
- Tester/agent:
- Environment:
- Supported languages/frameworks:
- Runner configuration:

## 29.2 Summary

| Metric | Count |
|---|---:|
| Total test cases in this plan | |
| Executed | |
| PASS | |
| FAIL | |
| PARTIAL | |
| BLOCKED | |
| NOT_IMPLEMENTED | |
| UNSUPPORTED | |
| NOT_RUN | |
| NOT_APPLICABLE | |

## 29.3 Requirement completeness

| Metric | Count |
|---|---:|
| Requirements discovered | |
| Covered | |
| Partially covered | |
| Missing | |
| Blocked | |
| Unsupported | |
| Not applicable | |
| Critical missing | |

## 29.4 Coverage and quality

| Metric | Baseline | After generation | Delta | Tool/status |
|---|---:|---:|---:|---|
| Line coverage | | | | |
| Branch coverage | | | | |
| Requirement coverage | | | | |
| Mutation score | | | | |
| Duplicate tests | | | | |
| Weak assertions | | | | |
| Flaky tests | | | | |

Use `N/A` or `UNKNOWN` where evidence is unavailable. Never substitute zero for an unmeasured metric.

## 29.5 Detailed test execution

| Test ID | Status | Evidence/log | Defect ID | Notes |
|---|---|---|---|---|

## 29.6 Defect log

| Defect ID | Severity | Feature area | Reproduction | Expected | Actual | Evidence |
|---|---|---|---|---|---|---|

## 29.7 Missing requirements

For each missing critical/high-priority requirement include:

- Requirement ID.
- Description.
- Source file/symbol.
- Evidence.
- Why it is not covered.
- Recommended test scenario.
- Whether generation or execution was blocked.

## 29.8 Unsupported and blocked areas

List exact modules, languages, frameworks, tools, dependencies and reasons.

## 29.9 Final recommendation

Choose one:

- READY FOR CONTROLLED RELEASE
- READY WITH KNOWN LIMITATIONS
- NOT READY — CRITICAL DEFECTS
- NOT READY — REQUIREMENT DISCOVERY INCOMPLETE
- NOT READY — EXECUTION/ISOLATION UNSAFE
- INCONCLUSIVE — INSUFFICIENT TEST ENVIRONMENT

Explain the decision with evidence.

---

# 30. Final instructions to the implementation/testing agent

Do not simply run this plan as a collection of isolated unit tests. The main objective is to establish whether the product can discover and satisfy the important testing needs of a real repository.

The most important proof is the full-repository end-to-end test:

1. Inventory the repository.
2. Discover its important behaviours and risks.
3. Build a traceable requirement matrix.
4. Find existing test evidence.
5. Identify what is missing.
6. Generate tests for the missing requirements.
7. Execute them safely.
8. Measure coverage and quality.
9. Identify remaining gaps.
10. Produce an honest, snapshot-pinned report.

**A feature that generates 20 passing happy-path tests while missing authentication, authorization, error handling, database consistency, integration failures or important workflows has failed this test plan.**

The release decision must be based on requirement completeness, correctness, execution evidence, quality, safety and transparent limitations—not the number of generated tests.
