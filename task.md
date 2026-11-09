# MASTER IMPLEMENTATION TASK
# Autonomous Code Synthesis, Plan-Bound Editing & Durable Workflow Execution

**Project:** AI-Powered Software Development Platform  
**Coding Agent:** Antigravity 3.8 Flash  
**Implementation Level:** Production-oriented backend architecture  
**Priority:** P0 + P1  
**Primary Objective:** Enable end-to-end autonomous code generation and execution after human approval.

---

# 0. YOUR ROLE

Act as a Senior AI Agent Architect, Python Backend Engineer, LLM Systems Engineer, Distributed Workflow Engineer, and Application Security Engineer.

You are working on an existing AI-powered software development platform.

Your task is to solve two major architectural problems:

1. The agent cannot autonomously synthesize code for approved plan steps when the HTTP caller does not provide file content.
2. The entire autonomous execution workflow runs synchronously inside HTTP requests, making it vulnerable to timeouts, connection drops, and process failures.

You must implement:

- EditSynthesizer.
- Plan-bound code modifications.
- Validated search/replace patches.
- LLM-based code synthesis.
- Syntax and lint validation.
- Bounded iterative self-correction.
- Durable workflow execution using the existing DBOS infrastructure where technically appropriate.
- HTTP 202 Accepted execution initiation.
- Workflow progress tracking.
- Recovery and checkpoint integration.
- Comprehensive documentation.

IMPORTANT:

Do not rewrite the existing agent execution architecture from scratch.

Inspect and reuse:

- AgentExecutionLoop.
- LoopDetector.
- WorkspaceManager.
- WorkspacePathGuard.
- WorkspaceDiffVerifier.
- ExecutionVerifier.
- ExecutionCheckpointManager.
- ExecutionRecovery.
- ExecutionBudgetManager.
- TaskExecutionOrchestrator.
- Existing LLM providers.
- Existing retrieval and code localization infrastructure.
- Existing SSE/event infrastructure.

Preserve all existing security controls and human approval requirements.

Do not stop after producing a plan. Implement, test, document, and provide a final report.

---

# 1. PHASE 0 — COMPLETE EXISTING CODEBASE AUDIT

Before changing any code, inspect the following files.

## 1.1 Core execution

- backend/ai/services/agent_execution_loop.py
- backend/ai/services/execution_verifier.py
- backend/ai/services/execution_checkpoint_manager.py
- backend/ai/services/execution_recovery.py
- backend/ai/services/execution_budget_manager.py
- backend/ai/services/bounded_repair_loop.py
- backend/ai/services/plan_replanner.py

## 1.2 Task orchestration

- backend/app/services/task_execution_orchestrator.py
- backend/app/api/v1/tasks.py
- backend/app/api/v1/events.py
- backend/app/models/task.py
- backend/app/repositories/task_repository.py
- backend/app/schemas/task.py
- backend/app/schemas/plan.py

## 1.3 Workspace and security

- backend/sandbox/workspace_manager.py
- backend/sandbox/diff_verifier.py
- backend/sandbox/path_guard.py
- backend/sandbox/workspace_tool_policy_bridge.py
- backend/app/core/input_security.py

Verify the actual file locations. Do not assume every listed path exists.

## 1.4 Frontend

Inspect:

- frontend/src/pages/RepositoryTaskStudio.tsx
- frontend/src/services/tasks.ts
- Existing task execution hooks.
- Existing task event streaming.
- Existing execution progress UI.

Find the actual implementation of:

```typescript
executeTask()
```

Inspect the automatic execution call:

```typescript
await executeTask(created.task_id, {
    run_steps: true,
    run_tests_after: true,
    auto_repair: true
});
```

Understand why it does not provide content for modification steps.

## 1.5 Existing DBOS infrastructure

Inspect:

- backend/requirements.txt
- backend/poc/dbos/__init__.py
- backend/poc/dbos/workflow.py
- backend/tests/test_reliable_worker_architecture.py

Also inspect:

- DBOS initialization.
- Application lifespan.
- Database configuration.
- SQLAlchemy session factory.
- Existing checkpoint storage.
- Existing worker infrastructure.
- Existing workflow persistence.

DBOS is already listed in the backend requirements.

Do not install another workflow engine without demonstrating a technical reason.

Do not assume the existing DBOS proof of concept is production-ready. Verify its initialization, persistence, retry, and recovery behavior.

## 1.6 Documentation

Inspect:

- Docs/agentic-chat/
- Docs/engineering/13_architecture_decisions.md
- Docs/engineering/14_changelog.md
- Docs/week3.md
- Docs/README.md

Pay particular attention to:

**ADR-010: Mandatory Human Approval Gate & Bounded Repair Loop**

This ADR must remain enforced.

---

# 2. EXISTING IMPLEMENTATION AND PROBLEMS

Document the actual implementation before changing it.

## 2.1 AgentExecutionLoop

File:

backend/ai/services/agent_execution_loop.py

Current responsibilities:

- Dependency-aware plan execution.
- Topological ordering.
- Action dispatch.
- Workspace operations.
- Loop detection.
- Iteration limits.
- Step execution records.
- Timeline events.

Existing action mapping:

| Action | Current behavior |
|---|---|
| patch | Calls patch_file |
| edit | Calls write_file |
| create | Calls write_file |
| write | Calls write_file |
| modify | Calls write_file |
| refactor | Calls write_file |
| delete | Calls delete_file |
| inspect | Calls read_file |
| read | Calls read_file |

Current problem:

For modification steps, content must be provided through step_payloads.

Without content, the execution fails with:

"No content payload provided. Placeholder synthetic writes are prohibited."

We must preserve the prohibition against placeholder content.

Instead of fabricating content, introduce an actual LLM-powered code synthesis service.

## 2.2 Important payload mapping bug

Inspect this logic:

```python
if "content" not in step_input:
    for other_input in payload_map.values():
        if isinstance(other_input, dict) and "content" in other_input:
            step_input["content"] = other_input["content"]
            break
```

This can reuse content belonging to another plan step.

Remove this cross-step fallback.

Each step must receive only its own explicitly associated payload.

Correct behavior:

```text
Step 1 -> payloads["step_1"]
Step 2 -> payloads["step_2"]
Step 3 -> payloads["step_3"]
```

Never copy content from another step.

## 2.3 Existing loop detection

The LoopDetector fingerprints actions and detects repeated cycles.

Preserve:

- Action fingerprinting.
- Cycle detection.
- Maximum iteration limit.
- Safe failure behavior.

Integrate synthesis attempts with execution budgets so that repeated LLM generation cannot create uncontrolled loops.

## 2.4 Existing workflow

File:

backend/app/services/task_execution_orchestrator.py

The existing autonomous workflow performs:

1. Execute approved steps.
2. Save checkpoint.
3. Run tests.
4. Attempt bounded repair.
5. Save checkpoint.
6. Run independent verification.
7. Save verification checkpoint.
8. Create Draft PR if publication is authorized.

Preserve this progression.

Do not introduce automatic merging or deployment.

## 2.5 Existing synchronous execution

Inspect:

```python
def execute_approved_task(...)
```

in:

backend/app/api/v1/tasks.py

The current endpoint calls the orchestrator synchronously and returns after execution.

This is unsuitable for long-running autonomous tasks.

Move execution into durable background workflow execution.

The API should initiate the workflow and return:

HTTP 202 Accepted

with a workflow identifier and task identifier.

---

# 3. TARGET ARCHITECTURE

Implement the following architecture.

                    HUMAN APPROVAL
                          |
                          v
                   APPROVED PLAN
                          |
                          v
                  DURABLE WORKFLOW
                          |
                          v
                  AGENT EXECUTION LOOP
                          |
              +-----------+-----------+
              |                       |
              v                       v
        USER PAYLOAD             EDIT SYNTHESIZER
              |                       |
              |                 Repository Context
              |                       |
              |                 File Localization
              |                       |
              |                 Current File Content
              |                       |
              |                 LLM Code Generation
              |                       |
              |                 Search/Replace Blocks
              |                       |
              |                 Validation Pipeline
              |                       |
              |                 Bounded Self-Refinement
              |                       |
              +-----------+-----------+
                          |
                          v
                 PLAN-BOUND PATCHES
                          |
                          v
                  WORKSPACE EDITING
                          |
                          v
                 DIFF SCOPE VALIDATION
                          |
                          v
                     TEST RUNNER
                          |
                          v
                   BOUNDED REPAIR
                          |
                          v
                INDEPENDENT VERIFICATION
                          |
                          v
                   HUMAN PUBLICATION
                          |
                          v
                     DRAFT PR

Every major workflow stage must be durable, observable, and recoverable.

---

# 4. PHASE 1 — IMPLEMENT EditSynthesizer

Priority: P0

Create:

backend/ai/services/edit_synthesizer.py

This service is responsible for generating actual code modifications using the existing LLM infrastructure.

Do not make AgentExecutionLoop directly responsible for LLM prompts, repository retrieval, syntax checking, or patch generation.

Keep those responsibilities inside EditSynthesizer and its supporting components.

## 4.1 Input contract

The synthesizer should receive:

- Approved PlanStep.
- Task ID.
- Repository ID.
- Workspace path or trusted workspace context.
- Current file content.
- Expected files.
- Plan version.
- Approved base revision.
- Relevant code context.
- Previous validation feedback, if retrying.
- Execution budget.
- Existing task constraints.

Conceptual interface:

```python
class EditSynthesizer:

    def synthesize(
        self,
        task_id: str,
        step: PlanStep,
        workspace_context,
        previous_feedback=None,
    ) -> EditSynthesisResult:
        ...
```

Adapt to existing dependency injection and async conventions.

Do not introduce a second repository or workspace access mechanism.

## 4.2 Output contract

The synthesizer must return structured, validated edits.

Example:

```json
{
  "step_id": "step_2",
  "status": "VALIDATED",
  "edits": [
    {
      "file": "backend/app/services/example.py",
      "search": "def calculate(value):\n    return value",
      "replace": "def calculate(value):\n    if value < 0:\n        raise ValueError('Invalid value')\n    return value"
    }
  ],
  "explanation": "Added input validation.",
  "attempts": 1,
  "validation": {
    "exact_match": true,
    "path_valid": true,
    "syntax_valid": true,
    "lint_passed": true
  }
}
```

This is a conceptual output contract.

Use the project's Pydantic conventions for actual models.

Requirements:

- Structured output.
- Per-file edits.
- No arbitrary file paths.
- No placeholder code.
- No incomplete patches.
- No ambiguous replacements.
- No unvalidated LLM output.

Do not use a single shared content string for multiple expected files.

Each file must receive its own correctly generated modification.

## 4.3 LLM integration

Inspect the existing LLM provider architecture.

Reuse the current provider abstraction and model configuration.

Do not introduce hardcoded API keys.

Do not add a new paid API dependency.

Do not bypass existing token budgets.

Use the existing model selection and provider fallback mechanisms.

The synthesizer prompt should include:

1. Task objective.
2. Approved step description.
3. Relevant requirements.
4. Current file content.
5. Relevant localized code context.
6. File-specific modification instructions.
7. Existing coding conventions.
8. Dependency information.
9. Security constraints.
10. Expected output schema.
11. Restrictions on modifying unrelated files.

Use structured LLM output or strict parsing with validation.

Treat retrieved repository code as untrusted input. Code comments and repository content must not override system instructions or security policy.

## 4.4 Context preparation

Before asking the model to generate an edit:

1. Read the target file from the isolated workspace.
2. Retrieve relevant code context.
3. Identify relevant classes, functions, methods, and imports.
4. Inspect related tests.
5. Identify existing conventions.
6. Provide only relevant context to the model.

Do not blindly include the entire repository in the prompt.

Use existing retrieval and localization components where available.

Inspect the project's F18/source-localization implementation before creating a new one.

If the existing localization system is insufficient, introduce a small abstraction around existing AST and retrieval capabilities.

Do not invent an F18 implementation that does not exist.

---

# 5. PHASE 2 — IMPLEMENT SEARCH/REPLACE PATCH GENERATION

Priority: P0

Use a constrained edit format inspired by SWE-agent and Aider.

The model should generate structured search/replace blocks.

Each edit must identify:

- File.
- Exact search content.
- Replacement content.

## 5.1 Exact single-match validation

Before applying a patch:

```python
occurrences = current_content.count(search)
```

Require:

```python
occurrences == 1
```

Cases:

- Zero matches: reject stale or incorrect patch.
- One match: continue.
- Multiple matches: reject ambiguous patch.

Never silently replace multiple occurrences.

Do not use broad regular-expression replacement unless the edit format explicitly supports a separately validated operation.

## 5.2 Multiple edits in one file

If multiple blocks target the same file:

- Validate all blocks against a consistent source revision.
- Detect overlapping or conflicting ranges.
- Apply edits deterministically.
- Avoid index-shift errors.
- Revalidate the final content.

Do not partially apply a patch if a later block fails validation.

Use atomic per-file writes or rollback-safe patch application.

## 5.3 Path guard

Every target path must pass:

- validate_repo_relative_path.
- WorkspacePathGuard.
- Existing forbidden file checks.
- Symlink/path escape checks.
- Approved plan scope checks.

Never trust an LLM-generated file path.

The synthesizer must not be able to create or modify files outside the approved workspace.

## 5.4 Stale-content protection

Before applying a generated patch, ensure the source file has not changed since it was read.

Use a content hash or revision fingerprint.

If the source changed:

- Reject the stale patch.
- Re-read the file.
- Re-synthesize using the updated content.
- Record the stale-context event.

Do not apply a patch against an outdated file snapshot.

---

# 6. PHASE 3 — VALIDATION FILTER CHAIN

Priority: P0

Every synthesized patch must pass the following validation pipeline.

## Stage A: Structured output validation

Validate the LLM response.

Reject:

- Invalid JSON.
- Missing fields.
- Unexpected fields.
- Empty search strings.
- Empty replacements where prohibited.
- Unsupported edit operations.
- Excessively large output.
- Duplicate or conflicting edits.

## Stage B: Exact match validation

Verify the search block occurs exactly once.

## Stage C: Path validation

Validate all paths against the approved plan and workspace security boundary.

## Stage D: Patch application validation

Apply patches to an in-memory representation first.

Only persist the edit after every block passes validation.

## Stage E: Syntax validation

Choose validators based on file type.

For Python:

- Python ast.parse.
- Ruff where configured.

For JavaScript and TypeScript:

- Existing ESLint configuration.
- TypeScript compiler checks where appropriate.

For JSON:

- Standard JSON parsing.

For YAML:

- Existing YAML parser if available.

For unsupported formats:

- Apply structural and patch validation.
- Do not claim syntax validation was performed.

Consider tree-sitter only if it is already available or clearly justified by the supported languages.

Do not install unnecessary parsers.

## Stage F: Sandbox lint validation

Use the existing workspace command execution infrastructure.

Python:

- Ruff.

JavaScript/TypeScript:

- Existing ESLint scripts.
- Existing project-specific checks.

Do not assume every repository contains Ruff or ESLint.

Detect supported project tooling.

Run focused validation on changed files rather than executing an unnecessarily expensive full repository pipeline after every generation attempt.

## Stage G: Final edit acceptance

Only after all required checks pass:

- Apply the patch to the workspace.
- Record the accepted patch hash.
- Record changed files.
- Record validation results.
- Emit timeline events.

If validation fails, proceed to bounded self-refinement.

---

# 7. PHASE 4 — ITERATIVE SELF-REFINEMENT

Priority: P0

Implement a bounded correction loop inspired by Reflexion and Self-Refine.

Maximum synthesizer correction retries:

2 retries after the initial attempt.

Therefore:

- Attempt 1: Initial generation.
- Attempt 2: First correction.
- Attempt 3: Final correction.

Total maximum generation attempts: 3.

This is a separate limit from the task-level repair budget.

Do not accidentally reset the global task execution budget.

## 7.1 Feedback loop

```text
LLM GENERATION
      |
      v
STRUCTURED OUTPUT VALIDATION
      |
      v
PATCH VALIDATION
      |
      v
SYNTAX CHECK
      |
      v
LINT CHECK
      |
      +---- PASS ---> ACCEPT PATCH
      |
      +---- FAIL
              |
              v
       COLLECT VALIDATION ERRORS
              |
              v
       BUILD CORRECTION CONTEXT
              |
              v
       LLM REGENERATION
              |
              v
       RETRY BUDGET CHECK
              |
              +---- AVAILABLE ---> REPEAT
              |
              +---- EXHAUSTED ---> FAIL SAFELY
```

## 7.2 Feedback content

Send the model:

- Previous generated patch.
- Exact validation error.
- File and line information where available.
- Relevant current file content.
- Previous failed attempt summary.
- Original approved task objective.

Do not send entire logs unnecessarily.

Do not expose secrets in feedback.

## 7.3 Attempt persistence

Record every generation attempt.

Use existing tool invocation auditing.

Possible tool name:

```text
edit_synthesizer.generate_patch
```

Record:

- Task ID.
- Step ID.
- Attempt number.
- Model/provider.
- Sanitized input summary.
- Patch fingerprint.
- Validation outcome.
- Error category.
- Duration.
- Token usage if available.

Never store raw API credentials or unredacted sensitive prompts.

Emit timeline events for:

- SYNTHESIS_STARTED.
- SYNTHESIS_ATTEMPT_COMPLETED.
- PATCH_VALIDATION_FAILED.
- SYNTHESIS_RETRY_STARTED.
- SYNTHESIS_ACCEPTED.
- SYNTHESIS_EXHAUSTED.

Adapt event names to existing event conventions.

---

# 8. PHASE 5 — INTEGRATE SYNTHESIZER INTO AgentExecutionLoop

Priority: P0

File:

backend/ai/services/agent_execution_loop.py

The loop must support both:

1. Caller-supplied payloads.
2. Automatically synthesized edits.

## 8.1 Payload priority

Use this exact priority:

```text
STEP EXECUTION
      |
      v
Does this exact step have caller payload?
      |
      +---- YES ---> Validate payload ---> Execute
      |
      +---- NO ----> Is action a modification?
                            |
                            +---- NO ---> Existing dispatch
                            |
                            +---- YES
                                  |
                                  v
                           EditSynthesizer
                                  |
                                  v
                           Validate edits
                                  |
                                  v
                           Apply patches
```

Caller-supplied content has priority.

However, caller-supplied payloads must still pass:

- Plan scope validation.
- Path validation.
- Patch validation.
- Existing workspace authorization.

Never bypass validation because content came from an HTTP caller.

## 8.2 Action-specific behavior

For:

- edit
- create
- write
- modify
- refactor

If a valid exact-step payload is present, preserve its behavior where safe.

If no payload exists, call EditSynthesizer.

For patch:

- Preserve structured search/replace behavior.
- Synthesize a patch if no valid caller payload exists and the step requires an edit.

For inspect/read:

- Preserve read-only behavior.
- Never call EditSynthesizer.

For delete:

- Preserve existing authorization and approval restrictions.
- Do not synthesize deletion instructions.
- Never automatically delete an unexpected file.

For command/test:

- Preserve the existing command policy and test runner.

## 8.3 Remove unsafe cross-step content fallback

Delete the logic that searches every other payload for content.

Every payload must be associated with its own step ID.

## 8.4 Multiple expected files

The existing write_file path can write the same content to every expected file.

This is unsuitable for autonomous synthesis.

Change modification handling to use per-file edit results.

For example:

```text
Step:
  expected_files:
    - src/auth.py
    - tests/test_auth.py

Synthesized edits:
  src/auth.py -> implementation patch
  tests/test_auth.py -> test patch
```

Do not write identical content into both files.

## 8.5 Execution result

Extend StepExecutionRecord if necessary to include:

- synthesis_attempts
- patch_hashes
- validation_status
- changed_files
- failure_category

Maintain compatibility with existing response serialization.

---

# 9. PHASE 6 — PLAN-BOUND EDIT ENFORCEMENT

Priority: P0

This is a mandatory security requirement.

A task must never modify files outside its approved plan without explicit human re-approval.

Relevant existing architecture:

- PlanStep.expected_files.
- StructuredPlan.expected_files.
- WorkspaceDiffVerifier.
- ADR-010.
- Existing independent verification.

## 9.1 Allowed file scope

Build an immutable approved file scope from the approved plan version.

Use:

- PlanStep.expected_files.
- StructuredPlan.expected_files.
- Approved task requirements where appropriate.

But distinguish:

- Files allowed to inspect.
- Files allowed to modify.
- Files allowed to delete.
- Files allowed only for testing.

Do not assume every expected file is automatically modifiable.

Inspect the plan schema and existing planning semantics.

## 9.2 Enforce at three levels

Enforce file scope at:

LEVEL 1 — EditSynthesizer

The LLM can only generate edits for approved modification targets.

LEVEL 2 — Workspace modification

Before write_file, patch_file or delete_file:

- Verify exact approved scope.
- Verify current plan version.
- Verify approval is still valid.
- Verify path safety.

LEVEL 3 — Independent diff verification

After execution:

- Extract actual workspace diff.
- Compare every changed file with approved modification scope.
- Reject unauthorized additions, deletions, renames and modifications.
- Record blocking findings.

Do not rely only on the synthesizer prompt.

The server must enforce the boundary independently.

## 9.3 Human re-approval

If an operation needs a file outside the approved modification scope:

1. Do not modify the file.
2. Generate an additional scope request.
3. Explain why the file is required.
4. Show the requested file and reason.
5. Require explicit human approval.
6. Update the approved plan/version or approved scope through the existing approval workflow.
7. Invalidate previous approval if the plan version changes.
8. Resume execution only after authorization.

Never silently expand approved scope.

## 9.4 WorkspaceDiffVerifier integration

Actual class:

```python
WorkspaceDiffVerifier
```

File:

backend/sandbox/diff_verifier.py

Inspect its existing allowed_files logic.

The current implementation has optional scope validation.

Also inspect the independent verifier's current handling of test files and Markdown files.

Do not automatically allow every changed test or Markdown file merely because of its extension.

A test file should be included in approved scope or explicitly approved through the appropriate process.

Preserve:

- Forbidden file checks.
- Critical manifest deletion restrictions.
- Secret scanning.
- Path traversal checks.
- Diff immutability checks.

Ensure unauthorized files cause a blocking verification result.

---

# 10. PHASE 7 — IMPLEMENT DURABLE WORKFLOW EXECUTION

Priority: P1

This is the second major objective.

The current execution flow must not run entirely inside the HTTP request lifecycle.

Use the existing DBOS infrastructure after validating that it is properly configured.

Do not replace DBOS with Temporal or another engine.

Do not use FastAPI BackgroundTasks as the production durable execution mechanism.

## 10.1 Existing components to reuse

Inspect and reuse:

- DBOS dependency.
- Existing DBOS proof of concept.
- TaskExecutionOrchestrator.
- ExecutionCheckpointManager.
- ExecutionRecovery.
- ExecutionBudgetManager.
- save_task_checkpoint.
- Existing task status transitions.
- Existing event/timeline infrastructure.

## 10.2 Target workflow

Implement a durable workflow with these logical steps:

```text
1. VALIDATE_APPROVAL
2. INITIALIZE_WORKSPACE
3. EXECUTE_APPROVED_PLAN
4. SYNTHESIZE_MISSING_EDITS
5. VALIDATE_PLAN_BOUND_DIFF
6. SAVE_EXECUTION_CHECKPOINT
7. RUN_TESTS
8. RUN_BOUNDED_REPAIR_IF_NEEDED
9. SAVE_TEST_REPAIR_CHECKPOINT
10. RUN_INDEPENDENT_VERIFICATION
11. SAVE_VERIFICATION_CHECKPOINT
12. WAIT_FOR_PUBLICATION_AUTHORIZATION_IF_REQUIRED
13. CREATE_DRAFT_PR_IF_AUTHORIZED
14. COMPLETE_WORKFLOW
```

Keep workflow boundaries aligned with actual business operations.

Do not create a separate DBOS step for every trivial Python function.

## 10.3 DBOS workflow design

Create an appropriate module, for example:

```text
backend/ai/workflows/
    __init__.py
    autonomous_task_workflow.py
    workflow_steps.py
    workflow_models.py
```

Adapt this structure to existing project conventions.

Requirements:

- Use proper DBOS workflow decorators.
- Use DBOS step decorators for durable boundaries.
- Use stable workflow IDs.
- Persist workflow status.
- Support restart and recovery.
- Support idempotent execution.
- Handle failures safely.
- Preserve task ownership.
- Preserve human approval.
- Prevent duplicate workflow submission.
- Avoid executing completed durable steps twice.

Do not treat an in-memory workflow dictionary as durable persistence.

## 10.4 Workflow input

Do not pass SQLAlchemy ORM sessions or live request objects into durable workflow arguments.

Persist or pass serializable identifiers:

- task_id
- actor_id
- approved_plan_version
- approved_base_revision
- run_tests
- auto_repair
- publication authorization state
- safe workflow options

Each durable step should acquire its own database session through the application's session factory and reload the task and repository records.

Revalidate task ownership and approval before sensitive operations.

## 10.5 Idempotency

Every durable step must be designed for possible replay.

Examples:

Workspace initialization:

- Detect an existing valid workspace.
- Do not create duplicate workspaces.

Plan execution:

- Use step-level checkpoints.
- Do not repeat completed modifications blindly.
- Verify workspace revision and patch fingerprints.

Test execution:

- Associate runs with workflow and execution attempt IDs.

Repair:

- Preserve the existing task-level maximum of three repair attempts.
- Do not reset the repair budget after workflow restart.

Draft PR:

- Check whether the corresponding draft PR already exists.
- Avoid creating duplicates after recovery.

Never automatically retry an operation with uncertain completion unless it is protected by an idempotency mechanism.

## 10.6 Recovery

If the process crashes:

1. Recover the workflow.
2. Load the last completed durable step.
3. Load task checkpoints.
4. Verify workspace state.
5. Verify current approved plan version.
6. Verify current workspace revision.
7. Resume only safe incomplete work.

If the workspace no longer matches the expected revision, stop and require reconciliation.

Do not blindly replay patches.

---

# 11. PHASE 8 — HTTP 202 ACCEPTED API

Priority: P1

Refactor the execution endpoints.

Inspect:

backend/app/api/v1/tasks.py

Current endpoints include:

- execute_approved_task.
- run_autonomous_workflow_endpoint.

Both currently invoke synchronous orchestration paths.

Change the long-running execution path to enqueue a durable workflow.

## 11.1 New API response

Return:

HTTP 202 Accepted

Example:

```json
{
  "task_id": "task-uuid",
  "workflow_id": "workflow-uuid",
  "status": "QUEUED",
  "message": "Autonomous execution has been accepted.",
  "status_url": "/api/v1/tasks/task-uuid/workflow-status"
}
```

Create an appropriate Pydantic response schema.

Do not return a fake workflow ID.

## 11.2 Endpoint behavior

The endpoint should:

1. Authenticate the user.
2. Verify task ownership.
3. Verify approved plan.
4. Verify approval is still valid.
5. Verify workspace prerequisites.
6. Create or retrieve the idempotent workflow.
7. Persist execution metadata.
8. Submit the workflow.
9. Return HTTP 202.

Do not perform code generation, test execution, repair or verification before returning the response.

Keep dry-run behavior compatible with the existing API.

## 11.3 Workflow status endpoint

Add:

```text
GET /tasks/{task_id}/workflow-status
```

Return:

- workflow_id
- task_id
- status
- current_step
- completed_steps
- failed_step
- progress information
- last_checkpoint
- started_at
- updated_at
- completed_at
- safe error summary

Enforce task ownership.

Do not expose internal credentials, raw prompts or stack traces.

## 11.4 Idempotent submission

If the same approved task workflow is submitted multiple times:

- Detect the existing active workflow.
- Return its workflow ID.
- Do not start another workflow.
- Require a new authorized execution attempt if a previous workflow is terminally failed.

Use appropriate database uniqueness or durable workflow identity rules.

---

# 12. PHASE 9 — PROGRESS STREAMING

Priority: P1

Inspect the actual existing event infrastructure.

Do not assume that an endpoint is SSE merely because its name contains events.

The project has existing task event and event-stream functionality.

Verify its actual route, response type and frontend integration.

Reuse the existing SSE infrastructure where appropriate.

Target progress events:

```text
WORKFLOW_QUEUED
WORKFLOW_STARTED
APPROVAL_VALIDATED
WORKSPACE_INITIALIZED
STEP_STARTED
SYNTHESIS_STARTED
SYNTHESIS_RETRY
PATCH_VALIDATED
PATCH_APPLIED
STEP_COMPLETED
TESTS_STARTED
TESTS_COMPLETED
REPAIR_STARTED
REPAIR_COMPLETED
VERIFICATION_STARTED
VERIFICATION_COMPLETED
DRAFT_PR_CREATED
WORKFLOW_COMPLETED
WORKFLOW_FAILED
```

Every event should include:

- task_id
- workflow_id
- event_type
- timestamp
- safe message
- relevant step ID
- sanitized payload

Events must be persisted or otherwise recoverable.

SSE reconnection must not lose historical progress.

Support:

- Last-Event-ID where applicable.
- Reconnection.
- Event ordering.
- Keep-alive.
- Authorization.
- Task ownership.
- Safe error handling.

Do not emit secrets or raw LLM reasoning.

---

# 13. PHASE 10 — FRONTEND INTEGRATION

Priority: P1

Inspect:

frontend/src/pages/RepositoryTaskStudio.tsx

frontend/src/services/tasks.ts

Update the execution flow.

## 13.1 Current problem

The frontend submits:

```typescript
executeTask(taskId, {
    run_steps: true,
    run_tests_after: true,
    auto_repair: true
});
```

The frontend should no longer wait for the entire autonomous workflow to finish.

## 13.2 New behavior

When a user approves and starts autonomous execution:

1. Send execution request.
2. Receive HTTP 202.
3. Store workflow_id.
4. Display queued/running status.
5. Connect to task progress stream.
6. Update UI from persisted events.
7. Show synthesis attempts.
8. Show current plan step.
9. Show test and repair progress.
10. Show verification result.
11. Show final Draft PR result if authorized.

Do not create a completely new dashboard if the existing RepositoryTaskStudio can support this.

Reuse existing components and design conventions.

## 13.3 Progress states

Support:

- QUEUED
- RUNNING
- SYNTHESIZING
- VALIDATING
- TESTING
- REPAIRING
- VERIFYING
- WAITING_FOR_APPROVAL
- COMPLETED
- FAILED
- CANCELLED

Map these states to the existing task status system carefully.

Do not introduce contradictory task and workflow statuses.

## 13.4 Connection recovery

If the browser refreshes:

- Retrieve active workflow status.
- Reconnect to progress events.
- Restore current progress.
- Avoid starting a duplicate workflow.

If SSE disconnects, reconnect without losing prior progress.

---

# 14. PHASE 11 — CANDIDATE PATCH GENERATION

Priority: P3 — FUTURE WORK

Document this as a future extension.

Do not implement it in the initial P0/P1 milestone unless the foundational implementation is complete and tested.

Future design:

- Generate 2–3 repair patch candidates.
- Validate candidate structure.
- Apply candidates in isolated workspace snapshots or isolated worktrees.
- Run relevant tests.
- Compare test outcomes.
- Compare lint outcomes.
- Compare regression results.
- Select the best valid candidate.
- Require human approval for scope expansion.

Never apply multiple candidate patches to the same live workspace concurrently.

Do not violate the existing three-attempt repair budget.

Candidate generation must not multiply the task's token budget without an explicit budget allocation.

Document:

- Candidate isolation.
- Resource limits.
- Test comparison.
- Selection criteria.
- Failure behavior.
- Cost considerations.

---

# 15. PHASE 12 — SECURITY REQUIREMENTS

These are mandatory.

## 15.1 Human approval

Preserve ADR-010.

No execution without valid approval.

If the plan changes:

- Invalidate previous approval.
- Require new approval.
- Prevent old workflows from continuing against the new plan.

## 15.2 File scope

No edit outside approved scope.

No silent scope expansion.

No LLM-generated path can override server-side path guards.

## 15.3 Workspace isolation

Preserve:

- WorkspaceManager.
- WorkspacePathGuard.
- Task workspace isolation.
- Workspace lifecycle checks.
- Protected branch restrictions.

## 15.4 LLM output safety

Treat model output as untrusted.

Validate all:

- Paths.
- Patch blocks.
- Search matches.
- Replacement content.
- Syntax.
- Lint results.
- Final diffs.

## 15.5 Resource limits

Enforce:

- Maximum synthesis attempts.
- Maximum task iterations.
- Existing execution budgets.
- Existing repair attempt ceiling.
- Maximum input size.
- Maximum output size.
- LLM timeout.
- Tool timeout.
- Workflow concurrency.

## 15.6 Workflow security

- Validate actor ownership.
- Validate approval at execution time.
- Validate plan version at every sensitive boundary.
- Prevent duplicate execution.
- Prevent unauthorized workflow resume.
- Do not trust frontend status.
- Do not expose raw internal errors.

## 15.7 Publication

Preserve the existing publication authorization requirement.

The workflow may create a Draft PR only when the required authorization is present.

Never merge automatically.

---

# 16. PHASE 13 — DATABASE AND PERSISTENCE

Inspect existing models before adding new ones.

Potential workflow metadata:

- workflow_id
- task_id
- workflow_status
- current_step
- approved_plan_version
- approved_base_revision
- started_at
- updated_at
- completed_at
- last_checkpoint
- safe_error_summary

Potential synthesis audit metadata:

- synthesis_attempt_id
- workflow_id
- task_id
- step_id
- attempt_number
- model/provider
- patch_hash
- validation_status
- duration_ms
- error_category

Do not create redundant tables if DBOS and existing task execution records already provide the necessary persistence.

Determine which system owns:

1. Workflow execution state.
2. Task business state.
3. Step checkpoint state.
4. Synthesis audit history.
5. User-visible timeline events.

These must have clearly defined responsibilities.

Use Alembic migrations where database changes are required.

Test migration upgrades and downgrades.

---

# 17. DOCUMENTATION — MANDATORY DELIVERABLE

I want every research decision, architectural change, implementation detail and testing result documented.

Documentation must be updated alongside code.

First inspect existing Docs structure and avoid duplicating existing documentation.

Create or update:

Docs/autonomous-execution/

## 00-existing-architecture-audit.md

Document:

- AgentExecutionLoop.
- LoopDetector.
- Existing action dispatch.
- Existing payload handling.
- Current synchronous execution.
- Existing workflow chain.
- Existing checkpoints.
- Existing recovery.
- Existing execution budgets.
- Existing diff verification.
- Frontend execution behavior.
- DBOS proof of concept.
- Existing SSE/event infrastructure.
- Actual limitations.

Include exact file and class references.

## 01-requirements-and-scope.md

Document:

- Problem statement.
- Functional requirements.
- Non-functional requirements.
- Security requirements.
- Compatibility requirements.
- P0/P1/P3 scope.
- Acceptance criteria.

## 02-research-and-technical-decisions.md

Research and document:

### SWE-agent

- Constrained edit interfaces.
- Search/replace editing.
- Immediate validation feedback.
- Why structured editing is preferable to unrestricted file generation.

### Aider

- Search/replace edit blocks.
- Unified diff approaches.
- File-specific edit contracts.
- Patch validation.

### Agentless

- Multiple patch candidates.
- Candidate evaluation.
- Test-based selection.
- Why this is deferred to P3.

### Reflexion

- Feedback-based improvement.
- Failure feedback.
- Iterative correction.

### Self-Refine

- Initial generation.
- Validation feedback.
- Bounded correction.
- Stopping criteria.

### Durable Execution

- DBOS.
- Temporal comparison.
- Existing DBOS integration.
- Durable workflow steps.
- Checkpointing.
- Idempotency.
- Recovery.
- Replay behavior.

For each technology explain:

- What it does.
- Why it is relevant.
- What we are adopting.
- What we are not adopting.
- Tradeoffs.
- Security implications.
- Cost implications.

Verify technical claims against official documentation and actual dependency versions.

Do not fabricate research citations.

## 03-edit-synthesizer-architecture.md

Document:

- Service responsibilities.
- Input contract.
- Output contract.
- LLM integration.
- Repository context.
- File localization.
- Patch generation.
- Structured output.
- Validation.
- Error handling.

Include Mermaid diagrams.

## 04-patch-validation-and-application.md

Document:

- Search/replace format.
- Exact-match validation.
- Multiple-block handling.
- Path validation.
- Stale-content detection.
- Atomic patch application.
- Syntax validation.
- Lint validation.
- Rollback behavior.

## 05-plan-bound-edit-security.md

Document:

- Approved plan scope.
- Expected files.
- Inspect versus modify permissions.
- Server-side scope enforcement.
- WorkspaceDiffVerifier integration.
- Human re-approval.
- ADR-010 compliance.
- Threat model.

## 06-self-refinement-and-budget.md

Document:

- Maximum three synthesis attempts.
- Initial attempt and two retries.
- Feedback generation.
- Error classification.
- Token budget.
- Loop detection.
- Tool invocation auditing.
- Failure behavior.

## 07-durable-workflow-architecture.md

Document:

- DBOS integration.
- Workflow definition.
- Workflow steps.
- Durable execution.
- Stable workflow IDs.
- Idempotency.
- Retry behavior.
- Crash recovery.
- Database sessions.
- Checkpoint integration.
- Task status synchronization.

## 08-api-and-frontend-integration.md

Document:

- HTTP 202.
- Workflow submission.
- Workflow status API.
- SSE events.
- Reconnection.
- Frontend progress states.
- Browser refresh recovery.
- Duplicate submission protection.

## 09-database-and-audit.md

Document:

- Existing models.
- New fields.
- New tables if any.
- Migrations.
- Synthesis attempt audit.
- Workflow audit.
- Timeline events.
- Sensitive data handling.

## 10-testing-and-validation.md

Document:

- Unit tests.
- Integration tests.
- Security tests.
- Durable workflow tests.
- Recovery tests.
- Frontend tests.
- Migration tests.
- Performance tests.
- Actual commands and results.

## 11-implementation-changelog.md

Maintain chronological implementation history.

Include:

- Date.
- Phase.
- Changes.
- Files.
- Tests.
- Failures.
- Fixes.
- Decisions.
- Remaining work.

## 12-future-candidate-patch-selection.md

Document the P3 candidate patch architecture.

## 13-operations-and-troubleshooting.md

Document:

- Workflow stuck states.
- DBOS initialization errors.
- Recovery failures.
- Synthesis failures.
- Patch mismatch.
- Syntax failures.
- Lint failures.
- SSE disconnects.
- Duplicate workflow submission.
- Budget exhaustion.

## README.md

Create a complete documentation index.

Also update existing:

- Docs/agentic-chat/
- Docs/engineering/13_architecture_decisions.md
- Docs/engineering/14_changelog.md
- Docs/README.md

Only update the documents where relevant.

Do not duplicate the same content across unrelated documentation files.

---

# 18. TESTING REQUIREMENTS

Testing is mandatory.

Inspect the existing tests and add targeted coverage.

## 18.1 EditSynthesizer tests

Test:

1. Successful generation.
2. Invalid structured output.
3. Missing search block.
4. Missing replacement block.
5. Exact single-match success.
6. Zero-match rejection.
7. Multiple-match rejection.
8. Path traversal rejection.
9. Forbidden file rejection.
10. Stale content detection.
11. Syntax validation failure.
12. Ruff failure.
13. ESLint failure where supported.
14. Successful retry.
15. Retry exhaustion.
16. Token budget exhaustion.
17. Provider timeout.
18. Secret redaction.
19. Per-file patch isolation.
20. Atomic multi-block patch application.

Use mocked LLM responses for deterministic unit tests.

## 18.2 AgentExecutionLoop tests

Test:

- Caller payload takes priority.
- Missing payload triggers synthesizer.
- Payload from another step is never reused.
- Read steps do not invoke synthesizer.
- Delete steps do not invoke synthesizer.
- Each file gets its own patch.
- Plan-bound scope is enforced.
- Existing dependency ordering remains correct.
- Loop detection remains correct.
- Existing maximum iteration behavior remains correct.
- Synthesizer failures stop unsafe execution.

## 18.3 Plan-bound security tests

Test:

- Approved file can be edited.
- Unapproved file cannot be edited.
- Path traversal cannot be edited.
- Forbidden files cannot be edited.
- Unexpected file in final diff is blocked.
- Test files are not automatically exempt.
- Markdown files are not automatically exempt.
- Plan version changes invalidate approval.
- Re-approval allows only the newly approved scope.
- Delete operations remain restricted.

## 18.4 Durable workflow tests

Test:

1. Workflow submission.
2. HTTP 202 response.
3. Workflow ID persistence.
4. Duplicate submission.
5. Workflow execution.
6. Successful checkpoint.
7. Simulated crash.
8. Workflow recovery.
9. Resume from checkpoint.
10. No duplicate file modifications.
11. No duplicate repair attempts.
12. No duplicate Draft PR.
13. Approval revalidation.
14. Plan version invalidation.
15. Budget preservation.
16. Workflow failure reporting.
17. Workflow status endpoint.
18. Event persistence.
19. SSE reconnection.
20. Unauthorized workflow access.

Use the existing DBOS test infrastructure where appropriate.

A fake in-memory workflow is not sufficient proof of durability.

## 18.5 Existing regression tests

Preserve and run all relevant existing tests.

At minimum inspect and run:

- backend/tests/test_task_planner_and_executor_comprehensive.py
- backend/tests/test_meet_w3_all_days.py
- backend/tests/test_security_w3_tools.py
- backend/tests/test_prit_w3_d5_verification_and_draft_pr.py
- backend/tests/test_reliable_worker_architecture.py
- backend/tests/test_week3_day3_day4_and_fixes.py
- backend/tests/test_om_w3_d6_d7_performance_recovery_acceptance.py

Verify the paths before running them.

Do not remove existing tests.

Do not weaken assertions to make tests pass.

Run the wider backend suite where possible.

Record exact failures.

---

# 19. PERFORMANCE AND COST CONTROL

This platform must remain cost-efficient.

Reuse existing model providers.

Requirements:

- No unnecessary LLM calls.
- No full repository context in every prompt.
- Limit generation retries to two after the initial attempt.
- Cache or reuse relevant repository context only when revision-safe.
- Use token budgets.
- Use deterministic validation before requesting another LLM response.
- Use focused lint checks.
- Avoid unnecessary full test runs during synthesis.
- Avoid unbounded parallel generation.
- Do not run duplicate workflows.
- Record actual token usage when available.

Document:

- Average synthesis token consumption.
- Maximum synthesis token budget.
- Retry cost.
- Workflow execution overhead.
- Model/provider fallback behavior.

Do not invent cost estimates. Calculate them from actual provider pricing or clearly label assumptions.

---

# 20. IMPLEMENTATION ORDER

Follow the order below.

## PHASE 0 — Existing architecture audit

- Inspect source.
- Inspect DBOS.
- Inspect UI.
- Inspect tests.
- Inspect security boundaries.
- Document findings.

## PHASE 1 — EditSynthesizer foundation

- Create models.
- Create service.
- Integrate LLM provider.
- Integrate code context.
- Generate structured edits.
- Add unit tests.

## PHASE 2 — Patch validation

- Exact-match checks.
- Path guard.
- Stale-content protection.
- Atomic patch application.
- Syntax validation.
- Lint validation.

## PHASE 3 — Self-refinement

- Feedback loop.
- Maximum three attempts.
- Budget integration.
- Audit logging.
- Timeline events.

## PHASE 4 — AgentExecutionLoop integration

- Payload priority.
- Remove cross-step fallback.
- Integrate synthesizer.
- Per-file patches.
- Preserve loop detection.
- Regression tests.

## PHASE 5 — Plan-bound security

- Approved scope.
- Server-side edit checks.
- WorkspaceDiffVerifier integration.
- Human re-approval.
- Security tests.

## PHASE 6 — Durable workflow

- Inspect DBOS POC.
- Verify production initialization.
- Implement durable workflow.
- Integrate checkpoints.
- Integrate recovery.
- Implement idempotency.

## PHASE 7 — API changes

- HTTP 202.
- Workflow ID.
- Workflow status endpoint.
- Duplicate submission protection.

## PHASE 8 — SSE and frontend

- Progress events.
- Reconnection.
- Frontend workflow tracking.
- Refresh recovery.
- Execution status UI.

## PHASE 9 — Database and audit

- Models.
- Migrations.
- Repositories.
- Workflow audit.
- Synthesis audit.

## PHASE 10 — Full regression and documentation

- Run all relevant tests.
- Fix regressions.
- Validate migrations.
- Validate frontend.
- Complete documentation.
- Produce final report.

You may change the order only when actual technical dependencies require it. Document the reason.

---

# 21. STRICT IMPLEMENTATION RULES

1. Do not replace the existing AgentExecutionLoop.
2. Do not remove LoopDetector.
3. Do not remove execution budgets.
4. Do not remove checkpoints.
5. Do not remove recovery.
6. Do not weaken ADR-010.
7. Do not permit modifications outside approved scope.
8. Do not reuse content from another step.
9. Do not fabricate placeholder code.
10. Do not trust unvalidated LLM output.
11. Do not apply ambiguous search/replace blocks.
12. Do not silently apply multiple occurrences.
13. Do not apply stale patches.
14. Do not retry destructive operations automatically.
15. Do not pass live SQLAlchemy sessions to durable workflow arguments.
16. Do not claim in-memory background tasks are durable.
17. Do not duplicate DBOS initialization.
18. Do not introduce another workflow engine.
19. Do not duplicate existing SSE infrastructure.
20. Do not change unrelated authentication or deployment architecture.
21. Do not expose internal prompts or credentials.
22. Do not automatically merge pull requests.
23. Do not claim a feature is implemented until it is tested.
24. Do not create unnecessary database tables.
25. Do not skip documentation.

If a security-sensitive design decision is unclear, document the conflict and request clarification rather than silently choosing a weaker implementation.

---

# 22. DEFINITION OF DONE

## Autonomous code synthesis

- [ ] EditSynthesizer implemented.
- [ ] Existing LLM provider reused.
- [ ] Structured edit output implemented.
- [ ] Per-file patches implemented.
- [ ] Exact-match validation implemented.
- [ ] Path guard integrated.
- [ ] Stale-content validation implemented.
- [ ] Syntax validation implemented.
- [ ] Lint validation implemented.
- [ ] Two bounded correction retries implemented.
- [ ] Synthesis attempts audited.

## Agent integration

- [ ] Caller payload priority preserved.
- [ ] Cross-step content fallback removed.
- [ ] Missing payload triggers synthesis.
- [ ] Multiple files handled correctly.
- [ ] Existing loop detector preserved.
- [ ] Existing execution budgets preserved.

## Plan-bound editing

- [ ] Approved file scope enforced.
- [ ] Scope enforced before every modification.
- [ ] Diff scope independently verified.
- [ ] Unexpected files blocked.
- [ ] Explicit re-approval implemented.
- [ ] ADR-010 preserved.

## Durable workflow

- [ ] DBOS production integration verified.
- [ ] Durable workflow implemented.
- [ ] Stable workflow ID implemented.
- [ ] HTTP 202 implemented.
- [ ] Idempotent submission implemented.
- [ ] Workflow status API implemented.
- [ ] Checkpoints integrated.
- [ ] Recovery integrated.
- [ ] Database session lifecycle safe.
- [ ] No duplicate destructive execution.

## Progress and frontend

- [ ] Progress events implemented.
- [ ] SSE integration verified.
- [ ] Reconnection supported.
- [ ] Frontend updated.
- [ ] Browser refresh recovery supported.
- [ ] Duplicate workflow submissions prevented.

## Testing

- [ ] EditSynthesizer tests pass.
- [ ] Patch validation tests pass.
- [ ] Plan scope tests pass.
- [ ] Durable execution tests pass.
- [ ] Crash recovery tests pass.
- [ ] Existing regression tests pass.
- [ ] Migration tests pass.
- [ ] Frontend tests pass where available.

## Documentation

- [ ] Architecture audit.
- [ ] Research.
- [ ] Design decisions.
- [ ] Synthesizer implementation.
- [ ] Patch validation.
- [ ] Plan-bound security.
- [ ] Durable workflow.
- [ ] API and frontend.
- [ ] Database and audit.
- [ ] Testing results.
- [ ] Changelog.
- [ ] Future candidate patch architecture.

---

# 23. FINAL IMPLEMENTATION REPORT

At completion, provide:

## A. Executive summary

Explain what was implemented.

## B. Existing architecture versus final architecture

Explain the major differences.

## C. EditSynthesizer implementation

Explain:

- LLM integration.
- Context preparation.
- Localization.
- Structured output.
- Patch generation.
- Validation.
- Self-refinement.

## D. AgentExecutionLoop changes

Explain payload priority, synthesis integration, per-file edits, and loop detection.

## E. Plan-bound security

Explain how unauthorized file modifications are prevented and how re-approval works.

## F. Durable execution

Explain DBOS architecture, workflow IDs, durable steps, idempotency, checkpoints, and recovery.

## G. API and frontend

Explain 202 responses, status APIs, SSE and UI changes.

## H. Database changes

List all models, tables and migrations.

## I. Files created and modified

Give exact paths and responsibilities.

## J. Testing results

Give actual commands, passed/failed/skipped counts, and unresolved failures.

## K. Documentation

List every document created or updated.

## L. Remaining limitations

Clearly distinguish implemented capabilities from planned capabilities.

## M. Final acceptance checklist

Use:

- COMPLETED
- PARTIALLY COMPLETED
- NOT COMPLETED
- BLOCKED

Do not mark something completed without implementation and test evidence.

---

# 24. START EXECUTION

Start with PHASE 0.

First:

1. Inspect the complete relevant implementation.
2. Map the existing dependencies.
3. Verify DBOS readiness.
4. Identify the existing LLM provider and localization services.
5. Inspect the real API and SSE routes.
6. Inspect the current security boundaries.
7. Inspect the existing tests.
8. Write the architecture audit document.
9. Produce the file-by-file implementation plan.

Then continue with implementation.

Do not stop at the audit or planning stage.

If a phase is too large for one session, complete it incrementally and maintain an accurate implementation changelog and progress document.

MOST IMPORTANT:

The final system must be capable of taking a human-approved development plan, autonomously generating valid code changes, applying only authorized patches, executing tests, performing bounded repair, verifying the final diff, and surviving HTTP disconnections or backend restarts without losing workflow state.

**The goal is genuine end-to-end autonomous software development with strict human approval, workspace isolation, plan-bound edits, durable execution, and complete auditability.**