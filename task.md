# Week 3 — Workflow Automation, GitHub Ecosystem & Production Hardening

**Project:** AI-Powered Software Development Platform  
**Duration:** 7 working days  
**Team:** Meet, Dev, Dhramraj, Yug, Om, Parth, Prit, Sukun, Keval, Devu  
**Prerequisite:** Week 2 Developer Intelligence Suite is integrated and its acceptance tests pass.

---

## 1. Week 3 Objective

Transform the developer-intelligence platform into an integrated AI development workflow that can take a task from an identified problem to a verified code change and a human-reviewable GitHub Draft PR.

### Final workflow

```text
Connect GitHub Repository
          |
          v
Explore Code / Explain / Detect Bugs / Review
          |
          v
Create GitHub Issue or Submit a Task
          |
          v
Task Planner + Repository Context (RAG)
          |
          v
Validate Structured Implementation Plan
          |
          v
Human Approves Plan
          |
          v
Create Isolated Git Branch + Workspace
          |
          v
Apply Changes Using Approved Agent Tools
          |
          v
Generate or Update Tests
          |
          v
Run Tests in Restricted Sandbox
          |
          +------ Tests Fail ------+
          |                         |
          v                         |
Diagnose Failure                    |
          |                         |
          v                         |
Apply Bounded Repair ---------------+
          |
          v
Independent Verification
          |
          v
AI Code Review + Static Analysis
          |
          v
Generate PR Summary + Test Evidence
          |
          v
Push Task Branch
          |
          v
Create GitHub Draft Pull Request
          |
          v
Human Reviews and Decides Next Steps
```

The agent must not automatically merge a pull request, modify protected branches, bypass approval gates or deploy code.

## 2. Week 3 Feature Ownership

| Feature | Lead | Collaborators |
|---|---|---|
| F31 — GitHub Issue Creation | Parth | Yug, Dhramraj, Sukun, Keval |
| F32 — Task Planner and Approval | Meet | Dev, Yug, Dhramraj, Om |
| F33 — Isolated Workspace and File Execution | Prit | Devu, Parth, Sukun |
| F34 — Tool Routing and Policy Enforcement | Devu | Prit, Sukun, Yug |
| F35 — Test Runner and Bounded Repair | Meet | Dev, Prit, Devu, Keval |
| F36 — Independent Verification and PR Summary | Dev | Meet, Keval, Om |
| F37 — GitHub Branch Push and Draft PR | Parth | Yug, Dhramraj, Sukun |
| F38 — Task Timeline and Workflow UI | Dhramraj | Yug, Om, Keval |
| F39 — Persistence, Checkpoints and Traceability | Om | Yug, Meet, Parth |
| F40 — Security, Acceptance and Release Gate | Sukun | Keval and all feature leads |

Every feature lead is responsible for its design, integration, tests, documentation and acceptance criteria. The collaborators own their assigned deliverables.

## 3. Existing Week 2 Components to Reuse

Do not rebuild existing capabilities.

| Week 2 component | Week 3 use |
|---|---|
| Code Explanation | Understand implementation details and affected symbols |
| Bug Detection | Supply defects and remediation context to task planning |
| Test Generation | Generate or update tests for proposed changes |
| AI Code Review | Review the final diff and produce findings |
| Repository context and RAG | Retrieve relevant source files, symbols and dependencies |
| Analysis schemas | Reuse structured findings and verification metadata |
| Repository Explorer | Launch issues, tasks, reviews and execution workflows |
| GitHub repository integration | Fetch authorized source content and PR information |
| Task/analysis persistence | Extend history with execution runs, checkpoints and PR references |
| Existing LLM gateway | Use only the approved Gemini and Groq providers |

Before adding a new service, inspect the existing code, confirm the contract and reuse or extend the current implementation.

---

# DAY 1 — GitHub Issue Creation and Task Intake

**Goal:** A developer can turn an existing bug or review finding into a GitHub issue and start a development task from a supported issue or natural-language request.

## Parth — GitHub Issue Integration

- Audit the existing GitHub integration and authentication model.
- Implement or extend `GitHubService.create_issue(owner, repo, title, body, labels)`.
- Use the existing GitHub App installation-token mechanism where configured.
- Validate repository permissions and required issue fields.
- Format issues with:
  - Problem summary.
  - Evidence and source references.
  - Severity and category.
  - Reproduction steps or relevant context.
  - Suggested remediation, when available.
  - Link to the originating platform finding.
- Handle missing permissions, invalid labels, API errors and rate limits.
- Ensure duplicate requests do not create unintended duplicate issues.

**Deliverable:** Tested GitHub issue service with structured errors.

## Yug — Issue Creation API

Implement or extend:

```text
POST /api/v1/repositories/{id}/issues
```

- Accept a validated bug finding or review finding reference.
- Verify that the finding belongs to the authorized repository.
- Retrieve the stored finding server-side rather than trusting arbitrary client-provided content.
- Call the GitHub service.
- Return the GitHub issue number, URL and creation status.
- Add authorization, validation and failure tests.

**Deliverable:** Working issue-creation endpoint.

## Dhramraj — Create Issue UI

- Add a Create GitHub Issue action to bug and review findings.
- Display a confirmation or preview of the issue title and body.
- Show loading, success, duplicate and error states.
- Display a link to the created GitHub issue.
- Prevent repeated submissions while the request is running.

**Deliverable:** Integrated issue-creation experience.

## Meet — Issue-to-Task Context

- Define how an issue becomes a structured development task.
- Retrieve the issue title, body, labels and authorized repository context.
- Normalize the problem into an implementation objective.
- Preserve the original issue reference and its requirements.

**Deliverable:** Issue intake contract for the task planner.

## Dev — Planning Input Validation

- Define the validated task input schema.
- Distinguish requirements, assumptions, constraints and expected behavior.
- Detect insufficient or contradictory task descriptions.
- Prevent unsupported assumptions from silently becoming implementation requirements.

**Deliverable:** Validated task-intake schema.

## Om — Issue and Task Persistence

- Define the relationship between GitHub issues and platform tasks.
- Store the issue number, URL, repository and source finding reference.
- Prevent accidental cross-repository associations.
- Preserve the external issue identifier for later traceability.

**Deliverable:** Issue/task persistence support and migration if required.

## Prit — Workspace Prerequisites

- Verify repository checkout and workspace preparation interfaces.
- Confirm the workspace can be associated with the originating task.
- Define the source revision metadata required for safe execution.

**Deliverable:** Workspace preparation contract.

## Devu — Tool and Policy Integration

- Confirm that GitHub write operations go through explicitly authorized service methods.
- Ensure agent tools cannot call issue creation without the appropriate permission.
- Return normalized tool errors for unauthorized or failed operations.

**Deliverable:** GitHub write-operation policy integration.

## Sukun — GitHub Security

- Validate repository authorization before creating an issue.
- Prevent arbitrary repository-owner or repository-name substitution.
- Ensure GitHub tokens remain server-side.
- Add tests for unauthorized repositories and malicious issue content.

**Deliverable:** GitHub issue security tests.

## Keval — Issue Acceptance Tests

- Test issue creation from a bug finding.
- Test issue creation from a review finding.
- Test missing permissions, invalid input, rate limits and duplicate submissions.
- Verify that a failed request does not appear successful in the UI.

**Day 1 exit gate:** A supported finding can be converted into a real GitHub issue in an authorized test repository, and the issue can be traced back to its originating finding.

---

# DAY 2 — Development Task Planner and Human Approval

**Goal:** The platform converts a natural-language task or GitHub issue into a validated, reviewable implementation plan.

## Meet — TaskPlanner

Implement the task-planning service.

Responsibilities:

- Accept a natural-language request or a supported GitHub issue.
- Retrieve relevant code using the existing RAG pipeline.
- Identify likely affected files, functions and dependencies.
- Produce ordered implementation steps.
- Define test and verification strategies.
- Identify assumptions, missing information and risk.
- Keep the plan within configured context and model-call budgets.
- Avoid claiming that nonexistent files or functions were inspected.

**Deliverable:** Repository-aware TaskPlanner.

## Dev — Planner Schema and Validation

- Define `PlannerSchema` and implementation-step schemas.
- Validate affected file paths and required fields.
- Check that dependencies between steps are coherent.
- Validate the proposed test strategy.
- Reject malformed or unsupported plans.
- Ensure a regenerated plan receives a new version identifier.
- Prevent stale approval from authorizing a different plan.

**Deliverable:** Validated plan contract and tests.

## Yug — Task APIs and Lifecycle

Implement or extend:

```text
POST /api/v1/tasks
GET  /api/v1/tasks/{task_id}
POST /api/v1/tasks/{task_id}/approve
POST /api/v1/tasks/{task_id}/reject
```

- Connect task creation to the planner.
- Persist the task and plan.
- Enforce task ownership and repository authorization.
- Implement valid state transitions.
- Require the correct plan version for approval.
- Make repeated approval requests idempotent.

**Deliverable:** Working task-planning and approval APIs.

## Dhramraj — New Task and Plan Approval UI

- Build the New Task page.
- Support natural-language task input and available GitHub issue selection.
- Display the plan summary, affected files, ordered steps, risks and tests.
- Add approve and reject actions.
- Display validation failures and missing information.
- Disable approval when the plan is invalid or outdated.

**Deliverable:** Complete task-intake and approval interface.

## Om — Task and Plan History

- Persist tasks, plan versions and approval decisions.
- Store the approving user and timestamp.
- Associate tasks with repository and originating issue.
- Preserve previous plan versions for auditability.

**Deliverable:** Durable plan history.

## Parth — Issue Data Retrieval

- Retrieve authorized GitHub issue metadata.
- Handle closed issues, inaccessible issues and missing content.
- Preserve the original issue reference.
- Prevent cross-repository issue selection.

**Deliverable:** Validated issue retrieval for task intake.

## Prit — Workspace Readiness

- Validate that the repository revision identified by the task exists.
- Ensure workspace creation uses the correct repository.
- Prepare the interfaces required by Day 3 execution.

**Deliverable:** Verified workspace setup integration.

## Devu — Planning Tool Contracts

- Expose repository search, file reading and symbol lookup through validated tool interfaces.
- Ensure all tool calls respect repository scope and access policies.
- Prevent the model from inventing tool results.

**Deliverable:** TaskPlanner tool integration.

## Sukun — Approval Gate

- Enforce approval on the server, not only in the frontend.
- Reject write and execution operations for unapproved plans.
- Verify that users can approve only tasks they are authorized to control.
- Test attempts to reuse an old approval after the plan changes.

**Deliverable:** Approval-gate security tests.

## Keval — Planner Acceptance

- Test natural-language and issue-based task creation.
- Test invalid and contradictory requests.
- Test stale plans, unauthorized approvals and repeated requests.
- Verify that no workspace write occurs before approval.

**Day 2 exit gate:** A user can create a task, review its validated plan and approve or reject it. No unapproved task can modify repository files.

---

# DAY 3 — Isolated Workspace, Tool Routing and Code Execution

**Goal:** An approved task can apply changes in an isolated workspace through validated tools.

## Prit — WorkspaceManager

Implement or extend the workspace manager.

Responsibilities:

- Create an isolated workspace for each task.
- Check out the correct repository and base revision.
- Scope all file operations to the workspace root.
- Implement `read_file`, `write_file`, `apply_patch` and `get_diff`.
- Reject path traversal, symlink escapes and unauthorized writes.
- Preserve file integrity when a patch fails.
- Record changed files and operation results.
- Define cleanup behavior for successful, failed and cancelled tasks.

**Deliverable:** Tested WorkspaceManager.

## Devu — ToolRouter

- Register available agent tools with stable schemas.
- Validate tool arguments before dispatch.
- Enforce policy checks before every action.
- Route file operations to the WorkspaceManager.
- Return structured tool results and errors.
- Apply execution timeouts and output limits.
- Prevent tools from bypassing repository and workspace authorization.

**Deliverable:** Working tool registry and execution router.

## Parth — Git Branch Management

Implement or extend the Git service for:

- Creating a task branch from the approved base revision.
- Checking out the intended branch in the isolated workspace.
- Verifying repository identity and branch ownership.
- Detecting unexpected changes to the base branch.
- Preparing change metadata for later push and PR creation.

Use a stable naming convention such as:

```text
agent/task-<task-id>
```

Do not push changes or create a PR until the required verification gates pass.

**Deliverable:** Isolated branch lifecycle.

## Meet — Agent Execution Loop

- Execute only approved plan steps.
- Retrieve context before modifying code.
- Select tools based on validated objectives and available tool contracts.
- Track step completion and remaining execution budget.
- Stop on ambiguity, unsafe actions or exhausted limits.
- Require actual tool evidence before marking an operation complete.

**Deliverable:** Bounded agent execution loop.

## Dev — Execution Validation

- Validate execution-step results.
- Compare completed work against the approved plan.
- Detect missing steps and unsupported completion claims.
- Define structured execution outcomes.
- Ensure errors and incomplete operations remain visible.

**Deliverable:** Execution-result validation.

## Yug — Execution APIs

Implement or extend:

```text
POST /api/v1/tasks/{task_id}/execute
POST /api/v1/tasks/{task_id}/pause
POST /api/v1/tasks/{task_id}/resume
POST /api/v1/tasks/{task_id}/cancel
GET  /api/v1/tasks/{task_id}/events
```

- Enforce valid state transitions.
- Prevent duplicate concurrent execution of a task.
- Persist execution status.
- Verify task ownership for all operations.
- Handle interrupted workers and invalid requests.

**Deliverable:** Task execution lifecycle APIs.

## Dhramraj — Execution Timeline UI

Display task progress through stages such as:

```text
Planning → Approved → Editing → Testing → Verifying
```

- Show current step and completed steps.
- Display tool activity and meaningful errors.
- Add pause, resume and cancel controls where supported.
- Clearly distinguish a running task from a successful one.
- Show human-intervention and failure states.

**Deliverable:** Execution timeline connected to real task events.

## Om — Checkpoints and Execution History

- Persist execution runs and step results.
- Record checkpoint references and source revisions.
- Store changed-file metadata.
- Preserve failed-run information.
- Ensure task state and execution history remain consistent.

**Deliverable:** Persistent execution history.

## Sukun — Execution Security

- Enforce read/write permissions at the tool boundary.
- Block unsafe filesystem paths and unauthorized repository access.
- Define command-execution permissions.
- Ensure untrusted repository content cannot grant new permissions.
- Verify cancellation and timeout behavior.

**Deliverable:** Workspace and tool-security tests.

## Keval — Execution Acceptance Tests

- Test approved and unapproved tasks.
- Test branch isolation and patch application.
- Test path traversal and invalid tool arguments.
- Test duplicate execution, cancellation and partial failure.
- Verify the correct task and revision appear in history.

**Day 3 exit gate:** An approved task can modify files through validated tools in an isolated branch and workspace. Every operation is traceable to its task.

---

# DAY 4 — Restricted Test Execution and Bounded Auto-Fix

**Goal:** Execute permitted tests, diagnose failures and perform a limited number of repair attempts.

## Prit — Restricted Test Runner

Implement a test runner that executes only permitted test commands in an isolated environment.

- Support the project's approved test commands, including `pytest` or `npm test` when configured.
- Use an isolated container or equivalent restricted execution environment.
- Enforce timeouts, output-size limits and resource restrictions.
- Restrict filesystem access and network access according to policy.
- Terminate processes on cancellation or timeout.
- Return structured results with exit code, duration and sanitized output.

Do not execute arbitrary model-generated shell commands without validation.

**Deliverable:** Restricted test runner.

## Devu — Command and Tool Policies

- Implement command allowlists.
- Validate working directories and arguments.
- Block unauthorized shell commands and dangerous command patterns.
- Enforce workspace boundaries.
- Normalize timeout, execution and infrastructure errors.
- Prevent the agent from bypassing restrictions by calling a different tool.

**Deliverable:** Enforced command-policy layer.

## Meet — Bounded Repair Loop

Implement the failure-diagnosis and repair workflow.

1. Run the permitted tests.
2. Collect actual failure output.
3. Identify the relevant code and failure context.
4. Generate a targeted repair plan.
5. Validate the proposed patch.
6. Apply the patch through the approved tool interface.
7. Re-run the appropriate tests.
8. Stop when tests pass, the repair budget is exhausted or human intervention is required.

Set a configurable default maximum of **three repair attempts**. A retry must not silently reset the budget.

**Deliverable:** Bounded self-fix loop.

## Dev — Failure Diagnosis and Repair Validation

- Define structured test results and repair diagnoses.
- Distinguish test failures, timeouts and infrastructure failures.
- Require evidence from actual test output.
- Validate that proposed fixes relate to the original task.
- Prevent identical failed patches from being repeatedly applied.
- Ensure passing tests do not automatically imply that the original requirements are satisfied.

**Deliverable:** Failure diagnosis and repair-validation logic.

## Yug — Test and Repair APIs

- Expose execution status and test results through the task API.
- Persist repair-attempt metadata.
- Validate task state before starting a test run.
- Ensure cancelled or completed tasks cannot accidentally restart.
- Return structured failure information.

**Deliverable:** Integrated test/repair API workflow.

## Dhramraj — Test and Repair Timeline

- Show test commands, exit codes, durations and results.
- Display repair attempts and their outcomes.
- Distinguish test failures from infrastructure failures.
- Display when the agent has exhausted its repair budget.
- Show the required human-intervention state.

**Deliverable:** Integrated testing and repair UI.

## Om — Test Run Persistence

- Persist test runs and repair attempts.
- Associate each run with the correct task step and code revision.
- Preserve previous failed attempts.
- Record whether the final result is passed, failed or inconclusive.

**Deliverable:** Test and repair history.

## Parth — Branch Integrity

- Verify that the workspace remains on the intended task branch.
- Associate test results with the correct working-tree state.
- Ensure changes are not pushed prematurely.
- Record branch and base-revision metadata.

**Deliverable:** Branch-integrity checks.

## Sukun — Sandbox Security

- Test command allowlists and denied commands.
- Test process termination and resource limits.
- Prevent access to host secrets and unauthorized filesystem paths.
- Restrict network access according to policy.
- Ensure malicious repository code cannot disable the sandbox.

**Deliverable:** Sandbox security test report.

## Keval — Test and Repair QA

- Test successful runs and failing tests.
- Test repair success, repair failure and exhausted retries.
- Test timeouts and invalid commands.
- Verify that the retry limit is enforced across task recovery.
- Verify that failed tests cannot be reported as passed.

**Day 4 exit gate:** Tests execute within the approved restricted environment. Failures can trigger bounded repairs, and every attempt is recorded accurately.

---

# DAY 5 — Independent Verification, Code Review and Draft PR Creation

**Goal:** Produce a verified change set and create a GitHub Draft PR for human review.

## Dev — IndependentVerifier and PR Summary

Implement an independent verifier that checks:

- The original task requirements.
- The approved plan and completed steps.
- The actual final diff.
- Test results and relevant evidence.
- Findings from the Week 2 AI Code Review engine.
- Remaining risks and incomplete requirements.

Verification must return one of:

```text
PASS
FAIL
INCONCLUSIVE
```

Generate a structured PR summary containing:

- Problem and task objective.
- Implementation summary.
- Changed files.
- Tests executed and their actual outcomes.
- Verification result and evidence.
- Known limitations and remaining risks.

The verifier must not trust the agent's own completion claim as sufficient evidence.

**Deliverable:** Independent verification service and PR-summary generator.

## Meet — Requirement-to-Code Verification

- Compare the final implementation with the original request.
- Verify that all required plan steps have evidence.
- Identify missing or out-of-scope changes.
- Use repository context and test evidence to diagnose incomplete work.
- Escalate ambiguous requirements instead of declaring unsupported success.

**Deliverable:** Requirement-level verification integration.

## Parth — GitHub Push and Draft PR

Implement or extend:

```text
GitHubService.push_branch(...)
GitHubService.create_pull_request(..., draft=True)
```

Responsibilities:

- Verify the task branch and base branch.
- Ensure the task branch contains the expected changes.
- Push only the authorized task branch.
- Create a GitHub Draft PR against the intended base branch.
- Include the task summary, changed files, test results and verification status.
- Link the originating issue when applicable.
- Store the resulting PR number and URL.
- Handle permission errors, branch conflicts, rate limits and duplicate requests.

Do not merge the PR automatically.

**Deliverable:** Draft PR creation service with tests.

## Yug — PR Creation API

Implement:

```text
POST /api/v1/tasks/{task_id}/create-pr
```

- Validate task ownership and repository access.
- Require the appropriate task state and verification evidence.
- Reject tasks that have failed required verification.
- Make repeated requests idempotent.
- Return the PR URL, number and creation status.
- Handle failures without falsely marking the task as PR-created.

**Deliverable:** PR orchestration endpoint.

## Dhramraj — PR Status UI

- Display the final diff and verification report.
- Show test outcomes and review findings.
- Display the Draft PR URL and status.
- Provide a clear indication when PR creation fails.
- Link the task, originating issue and PR together.

**Deliverable:** PR status card and final review screen.

## Om — Traceability and PR Persistence

- Store the PR number, URL, branch, base revision and head revision.
- Link the PR to its task and originating issue.
- Preserve verification and test evidence.
- Record the final state transition.
- Prevent inconsistent or duplicate PR records.

**Deliverable:** Persistent task-to-PR traceability.

## Prit — Final Workspace Integrity

- Confirm the diff matches the actual working tree.
- Reject unexpected changes outside the approved scope.
- Ensure the final revision is stable before verification.
- Preserve failed-task workspaces when required for diagnosis.

**Deliverable:** Final workspace-integrity checks.

## Devu — Final Tool and Policy Gate

- Ensure push and PR operations require explicit authorization.
- Enforce tool policies before each GitHub write operation.
- Prevent unapproved tasks from pushing branches.
- Ensure no tool can merge into a protected branch.

**Deliverable:** Final Git operation policy tests.

## Sukun — PR Security

- Verify repository permissions before pushing or opening a PR.
- Scan changed files for newly introduced secrets.
- Ensure credentials are not exposed in PR descriptions or logs.
- Verify that required security checks block PR creation when they fail.
- Prevent duplicate or unauthorized PR creation.

**Deliverable:** PR security checks.

## Keval — PR Acceptance Tests

- Test successful Draft PR creation.
- Test failed verification blocking PR creation.
- Test duplicate requests and GitHub API errors.
- Verify that PR metadata matches the correct branch and task.
- Test issue-to-task-to-PR traceability.

**Day 5 exit gate:** A verified task can produce a Draft PR with an accurate summary and traceable test evidence. Failed or inconclusive required verification blocks the normal successful completion path.

---

# DAY 6 — Security, Reliability and Performance Hardening

**Goal:** Validate the integrated platform against abuse cases, interrupted execution and measurable performance requirements.

## Sukun — Security Red Team

Run tests for:

- Path traversal and symlink escapes.
- Prompt injection in README files, source code and comments.
- Unauthorized repository access.
- Unapproved file modifications and Git operations.
- Malicious test commands.
- Secret leakage through logs, generated code, review findings and PR descriptions.
- Repeated or replayed approval requests.
- Unauthorized task resume, cancellation and PR creation.
- Resource exhaustion and process termination failures.

Record the severity, reproduction steps, fix and regression test for every confirmed issue.

**Deliverable:** Security report with no unresolved critical issues.

## Meet — Retrieval and Agent Performance

- Measure repository-context retrieval latency.
- Verify bounded agent execution and model-call budgets.
- Test behavior under provider rate limits and timeouts.
- Ensure context retrieval does not repeatedly fetch the same unnecessary files.
- Measure the execution path with representative repositories.

**Deliverable:** Retrieval and execution performance report.

## Dev — AI Quality and Verification

- Evaluate bug detection and code-review findings against the Week 2 fixtures.
- Measure false positives and missing findings.
- Verify that the independent verifier rejects unsupported completion claims.
- Test repair-loop quality and malformed model output.
- Confirm only the approved Gemini and Groq providers are used.

**Deliverable:** AI quality and verification report.

## Dhramraj — UX and Workflow Polish

- Verify all loading, error, empty and recovery states.
- Ensure the task timeline reflects real backend state.
- Fix broken navigation and duplicated UI controls.
- Ensure the final diff, verification report and PR link are accessible.
- Test common desktop/laptop layouts.

**Deliverable:** Polished, integrated workflow UI.

## Yug — API Reliability

- Test invalid state transitions and concurrent requests.
- Verify idempotency for task approval, execution and PR creation.
- Standardize API error responses.
- Test authorization for every task lifecycle endpoint.
- Ensure failed background jobs do not leave tasks marked successful.

**Deliverable:** API reliability and authorization report.

## Om — Database and Traceability Performance

- Inspect slow task-history and analysis-history queries.
- Add indexes where supported by actual query patterns.
- Verify task, issue, branch and PR relationships.
- Test recovery after interrupted execution.
- Ensure audit events and checkpoints remain consistent.

**Deliverable:** Database and traceability report.

## Parth — GitHub Failure Recovery

- Test push failures, branch conflicts and PR-creation failures.
- Handle GitHub rate limits and permission changes.
- Verify that retries do not create duplicate PRs.
- Preserve enough metadata to recover safely from partial success.

**Deliverable:** GitHub integration recovery tests.

## Prit — Sandbox Reliability

- Test timeout and process-kill behavior.
- Verify workspace cleanup and preservation rules.
- Test restricted execution under resource limits.
- Ensure a failed cleanup cannot affect other workspaces.

**Deliverable:** Sandbox reliability report.

## Devu — Tool Reliability

- Verify consistent timeout and error handling across tools.
- Test invalid arguments and policy denials.
- Ensure every operation returns an accurate structured result.
- Check that tools cannot bypass sandbox or GitHub restrictions.

**Deliverable:** Tool reliability report.

## Keval — Full Regression

- Run backend unit and integration tests.
- Run frontend tests and production build.
- Run the complete end-to-end workflow.
- Verify security regression tests.
- Publish failures, skipped scenarios and blockers.

**Deliverable:** Consolidated regression report.

### Performance acceptance

Use measured baselines rather than claiming performance targets without evidence.

- Record retrieval latency and target the previously proposed P95 retrieval latency of less than 400 ms where the benchmark environment supports it.
- Record task planning, analysis, test execution and PR creation durations separately.
- Verify bounded memory, execution time and provider calls.
- Report any unmet target with measurements and a remediation plan.

**Day 6 exit gate:** Critical security and reliability issues are resolved, all important regressions are tracked, and performance is measured against defined targets.

---

# DAY 7 — Final Integration and Live Demonstration

**Goal:** Demonstrate the complete platform using a real authorized test repository and publish the final engineering report.

## Meet — End-to-End Agent Validation

- Verify issue/task intake, context retrieval and plan generation.
- Confirm execution follows the approved plan.
- Verify bounded repair and independent verification.
- Confirm model-provider restrictions are enforced.

## Dev — Final Intelligence and Verification

- Verify Week 2 analysis features remain functional.
- Confirm the final review and PR summary reflect actual changes and tests.
- Verify that incomplete or unsupported results are not reported as successful.

## Dhramraj — Final Product Demonstration

- Connect all feature screens.
- Verify issue, task, timeline, diff and PR navigation.
- Ensure the final workflow works through the UI without relying on mocked production responses.

## Yug — API and State Validation

- Verify all task and issue APIs.
- Confirm correct state transitions and authorization.
- Test duplicate requests and failure recovery.

## Om — Data and Traceability Validation

- Verify that the complete task history is persistent.
- Confirm issue, task, branch, test, verification and PR records are linked.
- Validate audit history and checkpoints.

## Parth — GitHub Demo Preparation

- Verify GitHub permissions and test-repository access.
- Ensure the branch and Draft PR are created from the correct source revision.
- Verify issue and PR links.

## Prit — Sandbox Demo Preparation

- Verify that test execution is isolated and bounded.
- Confirm cancellation, timeout and cleanup behavior.
- Ensure the demonstration uses a safe disposable workspace.

## Devu — Tool Integration

- Verify every required tool is connected to its actual implementation.
- Confirm policy enforcement, tool results and failure handling.
- Ensure no placeholder tool is used in the final acceptance path.

## Sukun — Final Security Gate

- Execute the critical security regression suite.
- Verify secret redaction and repository isolation.
- Block the release candidate if a critical security issue remains unresolved.

## Keval — Final Acceptance Report

- Run the complete acceptance scenario.
- Record test results and known limitations.
- Verify all acceptance criteria below.
- Publish the final regression and demo report.

---

# 4. Final End-to-End Acceptance Scenario

Use a disposable GitHub test repository with a small application, a known defect and an existing test suite.

### Scenario A — Developer Intelligence to GitHub Issue

1. Connect an authorized GitHub repository.
2. Open the Repository Explorer.
3. Explain a selected function.
4. Run Bug Detection on the target file.
5. Inspect the finding, evidence and suggested fix.
6. Create a GitHub issue directly from the finding.
7. Verify the issue links back to the platform finding.

### Scenario B — Issue to Draft Pull Request

1. Select the created issue or enter an equivalent natural-language task.
2. Generate a repository-aware implementation plan.
3. Inspect affected files, proposed steps and test strategy.
4. Approve the plan as an authorized user.
5. Verify the task branch and isolated workspace are created.
6. Execute the approved plan using validated agent tools.
7. Generate or update relevant tests.
8. Run tests inside the restricted environment.
9. Introduce or reproduce a test failure in the fixture and verify bounded repair.
10. Verify that the repair limit is enforced.
11. Run independent verification against the original requirement.
12. Run AI Code Review and the configured static checks against the final diff.
13. Generate the PR summary with actual test and verification results.
14. Push the task branch.
15. Create a GitHub Draft PR.
16. Verify the PR links to the task and originating issue.
17. Inspect the final diff, test evidence and review findings.

### Scenario C — Failure and Security Cases

Verify that:

- An unapproved task cannot modify files.
- An unauthorized user cannot access or approve another user's task.
- A malicious repository instruction cannot bypass policy.
- An unsafe command is rejected.
- Path traversal and unauthorized filesystem access are blocked.
- Failed required tests prevent normal successful completion.
- Failed or inconclusive required verification blocks the normal PR-creation path.
- Repeated requests do not cause duplicate execution or duplicate PRs.
- GitHub API failures are accurately reported.
- Cancellation and recovery preserve task history.
- Credentials do not leak into logs, generated code, findings or PR descriptions.
- No automatic merge or protected-branch modification occurs.

---

# 5. Definition of Done

A Week 3 feature is complete only when:

- [ ] The actual implementation is connected to the application.
- [ ] Existing Week 2 services are reused where appropriate.
- [ ] API contracts and state transitions are documented.
- [ ] Authentication and repository authorization are enforced.
- [ ] Failure paths and retries are tested.
- [ ] Unit and integration tests pass.
- [ ] Relevant security tests pass.
- [ ] UI reflects actual backend state.
- [ ] Database records and audit history remain consistent.
- [ ] Logs and errors are sanitized.
- [ ] Code is reviewed and integrated through the agreed workflow.
- [ ] Acceptance evidence is recorded.

# 6. Week 3 Final Deliverables

By the end of the week, the repository should contain:

1. GitHub issue creation from bug and review findings.
2. TaskPlanner for natural-language tasks and supported GitHub issues.
3. Validated plans and human approval workflow.
4. Isolated workspace and safe file operations.
5. Task-scoped Git branch creation and change tracking.
6. Validated tool registry and policy enforcement.
7. Restricted test runner.
8. Bounded failure diagnosis and repair loop.
9. Independent verification with evidence.
10. Final AI review and PR-summary generation.
11. GitHub branch push and Draft PR creation.
12. Task timeline, history and issue-to-PR traceability.
13. Security, recovery, integration and performance test reports.
14. Final demonstration and known-issues documentation.

# 7. Explicitly Out of Scope

Do not silently expand Week 3 into unrestricted autonomous development.

The following remain outside the normal Week 3 completion path unless separately approved:

- Automatic merging of pull requests.
- Automatic deployment to production.
- Arbitrary shell execution without restrictions.
- Unrestricted internet access from the sandbox.
- Unbounded autonomous repair attempts.
- Automatic modification of protected branches.
- Claims of complete security or correctness based solely on AI review.

---

## Final Week 3 Milestone

A developer can identify a problem, create a GitHub issue, start a task, review and approve the implementation plan, execute changes in a restricted workspace, run and repair tests within defined limits, inspect independently verified changes, and receive a GitHub Draft PR ready for human review.

**The release gate is the complete working workflow—not merely the completion of individual files or modules.**