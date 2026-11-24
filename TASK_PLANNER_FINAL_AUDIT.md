# Task Planner audit

Baseline: `69b6bb3` on `parth`. Historical audits were used to locate code and test suites. This audit traces the checked-out implementation.

## Execution path

| Stage | Entry point and data flow | Observed gap |
| --- | --- | --- |
| Intake and access | `RepositoryTaskStudio` and `CreateTask` call the tasks API. FastAPI auth middleware establishes the actor. Task routes check ownership and RBAC. | Studio uses structured task creation and supplies generic requirements. The freeform endpoint calls the ownership helper with an unsupported keyword. Existing intake tests replace that helper. |
| Context and planning | `TaskPlanner` uses `TaskContextBuilder`, repository files and symbols, requirement discovery, the localizer and the configured LLM gateway. `TaskPlanMixin` persists plan versions and their hashes. | DB queries and prompt inputs still use fixed limits. The critic is advisory on prompt intake. The other plan route also accepts custom plans. Relevance-ranked GitHub history and discussion retrieval remain unverified in this flow. |
| Human approval | Approval records store actor, plan version, base revision and plan hash. Execution recomputes the hash and checks the approval record. | Studio's Auto-Pilot action submits an approval itself from the pending state. |
| Execution and workspace | Tasks routes call `TaskExecutionOrchestrator` or submit to the workflow registry. The orchestrator provisions a workspace and invokes the `AgentExecutionLoop`, `EditSynthesizer`, `ToolRouter`, `CodeEditor` and workspace policy bridge. | Native workflow coordination is process-local. Backend selection and runner isolation need end-to-end validation. The historical test results do not establish that a live model can edit an arbitrary repository. |
| Tests and repair | Workspace test runner detects frameworks and records command output. The orchestrator persists test and bounded repair records. | `NO_TESTS_FOUND` was persisted as passed. The verifier also accepted zero-count and absent results. This let verification proceed without test evidence. |
| Independent verification | Diff scope, secret scan, static analysis and requirement checks feed the verification record. Workspace diff and Git HEAD are sampled separately. | A dirty worktree can be assigned the base HEAD as its verified revision. Some checks are only represented in the PR summary. |
| Git and GitHub | Sandbox workspace manager handles Git. `GitBranchService` resolves GitHub App clients. Task APIs manage publication state and traceability. | Synchronous workflow can authorize whatever revision is produced. The separate push path can proceed without a persisted SHA-bound authorization. Task Draft PR creation can persist a locally generated PR number and URL and does not issue a GitHub create call on that path. |
| Persistence and monitoring | Task, plan, approvals, execution, tools, test runs, repairs, verification, checkpoints, events and task PRs have SQLAlchemy records and Alembic migrations. Studio queries these endpoints. Redis supports event distribution and background workers. | Redis events do not make task workflows durable. Task-specific and generic PR records can diverge. Persisted state does not establish restart recovery across hosts. |
| Deployment | `startup.sh` selects API, migration, sync, webhook or isolated runner roles. Docker builds the application image. GitHub workflows exercise dependencies and deploy the Azure API and sync worker. | The deployed runner, PostgreSQL, Redis and App Service settings were not exercised. Local Alembic reported one head, `o3c4d5e6f7a8`. Docker's local socket had no running daemon. |

## Severity-ranked baseline defects

- **P0** Publication flags can stand in for a human authorizing a specific commit. Fake success can record a GitHub PR that does not exist.
- **P1** `POST /tasks/prompt-to-plan` raises `TypeError` before repository ownership lookup. The Studio bypasses this route.
- **P1** Required verification can pass after missing tests, empty collection or failures with zero recorded counts.
- **P1** A verification record can identify the base commit while publication later changes HEAD.
- **P1** The background workflow can report completion after a failed execution or verification stage.
- **P2** Plan criticism, repository grounding, clarification and persisted requirement coverage do not form a single enforced approval contract.
- **P2** Native workflow registry and local workspaces limit cross-process duplicate handling, recovery and scalability.
- **P3** Some progress text is generic, and a fixed workflow step count can misrepresent optional stages.

The local frontend baseline passed 369 tests in 35 files. See the test report for backend results and regression coverage.
