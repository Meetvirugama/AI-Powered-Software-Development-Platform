# TASK: Implement Untrusted Data Provenance & Taint Tracking in the AI-Powered Software Development Platform

## 1. ROLE AND OBJECTIVE

Act as a Senior AI Security Architect, Python Backend Engineer, and LLM Agent Security Researcher.

Your task is to design, implement, test, and document a provenance-aware taint-tracking security architecture in the existing AI-Powered Software Development Platform.

The objective is to ensure that untrusted information originating from GitHub issues, comments, findings, and other external sources remains identifiable throughout the complete AI development pipeline.

Implement a lightweight, production-oriented security mechanism inspired by:

1. Greshake et al. — Indirect Prompt Injection.
2. Design Patterns for Securing LLM Agents — Plan-then-Execute and Context-Minimisation.
3. CaMeL — Separation of control flow and data flow using capability-based policies.

Do not simply create a new provenance class. Implement end-to-end provenance propagation and enforce security policies at actual tool execution boundaries.

The existing issue fencing mechanism must remain functional.

## 2. FIRST: UNDERSTAND THE EXISTING REPOSITORY

Before changing code, thoroughly inspect:

- backend/ai/services/issue_task_adapter.py
- backend/app/schemas/task.py
- backend/app/schemas/plan.py
- backend/ai/services/task_planner.py
- backend/ai/services/agent_execution_loop.py
- backend/ai/services/plan_replanner.py
- backend/app/services/task_execution_orchestrator.py
- backend/agent/tools/
- backend/app/core/input_security.py
- backend/app/core/secret_redaction.py
- backend/sandbox/
- backend/tests/

Trace the complete data flow:

GitHub issue
→ IssueToTaskAdapter
→ TaskIntakePayload
→ TaskPlanner
→ StructuredPlan
→ PlanStep
→ AgentExecutionLoop
→ Tool arguments
→ Tool execution
→ Audit events.

Also investigate direct tool invocation paths that do not pass through AgentExecutionLoop.

Identify:

- Where source identity is currently available.
- Where source identity is lost.
- Which transformations create new content.
- Which operations execute commands or modify files.
- Existing approval and authorization infrastructure.
- Existing persistence and serialization mechanisms.
- Existing security controls that must be reused.

Create:

Docs/security/provenance/EXISTING_ARCHITECTURE_AUDIT.md

Document actual findings with file paths, class names, functions, and identified security gaps.

Do not assume the architecture described in this task perfectly matches the current repository. Verify every integration point.

## 3. IMPLEMENT PROVENANCE FOUNDATION

Create a reusable provenance architecture under:

backend/ai/security/

Suggested modules:

- provenance.py
- taint_tracker.py
- taint_policy.py
- provenance_audit.py

Follow existing project conventions and avoid duplicating existing functionality.

Implement typed models for:

### TrustLevel

- SYSTEM
- PLATFORM
- USER_APPROVED
- USER_PROVIDED
- EXTERNAL_UNTRUSTED
- MODEL_GENERATED

These classifications must be assigned by trusted backend code, not by LLM-generated content.

### DataProvenance

Include:

- provenance_id
- source_type
- source_id
- source_repository_id where applicable
- source_reference
- trust_level
- tainted
- parent_ids
- transformation
- created_at

Make provenance metadata immutable.

Use correct Python typing and Pydantic conventions already present in the repository.

Do not store raw secrets or unnecessary copies of sensitive input inside provenance records.

## 4. IMPLEMENT TAINT TRACKING

Implement a reusable taint tracking engine.

Responsibilities:

- Register source data.
- Generate provenance IDs.
- Track parent-child relationships.
- Propagate taint through transformations.
- Support multiple source inputs.
- Preserve provenance through LLM generation.
- Preserve provenance through summarization.
- Preserve provenance through serialization and deserialization.
- Preserve provenance during replanning.
- Detect missing or invalid provenance.
- Prevent unauthorized trust escalation.

Important rule:

An LLM-generated output must never automatically become trusted.

If an LLM summarizes an untrusted GitHub issue, the resulting information must retain the original issue provenance.

If an LLM combines trusted platform context and untrusted issue information, retain all relevant parent provenance.

Do not implement a global Python string tracker.

Use explicit typed provenance-aware values, fields, and transformation helpers at meaningful trust boundaries.

Distinguish taint from authorization. Approval of an action must not erase its historical provenance.

## 5. INTEGRATE WITH ISSUE TASK ADAPTER

Modify:

backend/ai/services/issue_task_adapter.py

Preserve:

- fence_untrusted_issue_data()
- Randomized boundary markers.
- Secret redaction.
- extract_safe_repo_paths().
- validate_repo_relative_path().
- Existing protected-file handling.
- Task intake behavior.
- Finding formatting.

Add provenance generation for:

- GitHub issue titles.
- GitHub issue descriptions.
- GitHub comments when imported.
- Finding descriptions.
- Finding evidence.
- User-provided requirements.
- Platform-generated constraints.

Attach provenance to the relevant requirements and assumptions.

Do not treat an extracted, validated file path as a trusted instruction.

Do not let external source metadata override backend-generated provenance.

## 6. INTEGRATE WITH TASK AND PLAN SCHEMAS

Modify:

- backend/app/schemas/task.py
- backend/app/schemas/plan.py

Add provenance-aware fields to the appropriate models.

Requirements and assumptions must preserve their original provenance.

PlanStep must support:

- Provenance references.
- Multiple parent sources.
- Taint status.
- Approval requirement metadata.
- Provenance for individual sensitive fields where necessary.

Do not rely exclusively on a single boolean tainted field.

For example, a plan may have a trusted platform-generated title but an issue-derived description and LLM-generated command arguments.

Represent these differences accurately.

Preserve all existing schema validators, path validation, constraints, and compatibility behavior.

Do not create circular imports.

## 7. INTEGRATE WITH TASK PLANNER AND REPLANNER

Modify:

- backend/ai/services/task_planner.py
- backend/ai/services/plan_replanner.py

Ensure:

1. Planner input carries source provenance.
2. Generated plan steps inherit relevant provenance.
3. Requirement IDs remain correctly associated.
4. Provenance is not lost during conversion.
5. Replanning preserves original lineage.
6. Model output cannot manufacture trusted metadata.
7. Missing provenance is not automatically trusted.

Do not add unnecessary LLM calls.

Prefer deterministic backend-side propagation.

## 8. IMPLEMENT EXECUTION POLICY ENFORCEMENT

Implement:

backend/ai/security/taint_policy.py

Integrate it into:

- backend/ai/services/agent_execution_loop.py
- backend/agent/tools/
- backend/app/services/task_execution_orchestrator.py

First identify every actual tool execution path.

Enforce policy immediately before the tool invocation.

Evaluate:

- Action type.
- Actual tool arguments.
- Argument provenance.
- Parent provenance.
- Repository ID.
- Task ID.
- Workspace ID.
- Resource scope.
- Operation risk.
- Required capabilities.
- Existing authorization.
- Approval status.

Implement risk-based policy decisions.

Suggested policy:

Repository reading and code searching:
Allowed under existing repository access and workspace policies.

Planning and code proposal generation:
Allowed, but preserve provenance.

File modifications:
Allowed only under existing workspace restrictions, path validation, and applicable execution policy.

File deletion:
Restricted according to operation risk and existing authorization.

Shell commands:
Require independent command validation, sandboxing, allowlisting, and applicable authorization.

Secret access:
Denied by default for untrusted-derived operations.

Network access:
Restricted through explicit destination and capability policies.

GitHub publication:
Must follow existing publication authorization.

Important:

Taint alone must not automatically block legitimate code generation.

A tainted issue may legitimately describe a bug that the agent needs to fix.

The policy must distinguish between using untrusted data as reference material and allowing it to control sensitive operations.

Never treat syntactically valid input as automatically authorized.

No direct tool invocation may bypass policy enforcement.

Fail closed when required provenance or authorization is missing.

Reuse existing security controls rather than implementing duplicate path guards, secret scanning, or sandboxing.

## 9. IMPLEMENT NARROWLY SCOPED HUMAN APPROVAL

Investigate existing user approval and authorization workflows first.

Extend existing infrastructure where available.

If necessary, introduce an ExecutionApproval model containing:

- approval_id
- task_id
- step_id
- action_type
- resource_scope
- argument_digest
- provenance_ids
- approved_by
- approved_at
- expires_at
- status

Approval must be:

- Bound to the exact normalized arguments.
- Bound to the correct task.
- Bound to the correct repository.
- Bound to the correct workspace.
- Bound to the relevant action and resources.
- Granted only by an authorized human.
- Expirable and revocable.

Any argument change must invalidate the previous approval.

Do not allow LLM-generated plans to approve themselves.

Do not interpret approval of one operation as unrestricted authorization for another.

If frontend work is necessary, document the required integration separately and preserve the existing authentication model.

## 10. IMPLEMENT STRUCTURED SECURITY AUDIT LOGGING

Implement provenance audit events.

Suggested events:

- PROVENANCE_CREATED
- TAINT_PROPAGATED
- PROVENANCE_VALIDATION_FAILED
- EXECUTION_POLICY_EVALUATED
- EXECUTION_APPROVAL_REQUIRED
- EXECUTION_APPROVED
- EXECUTION_DENIED
- EXECUTION_COMPLETED

Capture relevant IDs, policy decisions, source references, action types, and denial reasons.

Do not log raw secrets, credentials, or unnecessarily sensitive input.

Audit logs must follow existing access-control and logging conventions.

## 11. IMPLEMENT SECURITY TESTS

Create:

backend/tests/security/provenance/

Implement:

- test_provenance_models.py
- test_taint_tracker.py
- test_taint_propagation.py
- test_issue_intake_provenance.py
- test_planner_provenance.py
- test_replanner_provenance.py
- test_execution_policy.py
- test_approval_scope.py
- test_provenance_serialization.py
- test_end_to_end_taint_tracking.py

Mandatory tests:

1. GitHub issue receives EXTERNAL_UNTRUSTED provenance.
2. Issue comments receive external provenance.
3. Finding evidence retains its original provenance.
4. Summarization does not remove taint.
5. LLM-generated plan steps preserve parent provenance.
6. Multiple input sources are tracked.
7. Replanning cannot erase taint.
8. Serialization and deserialization preserve provenance.
9. Missing provenance cannot silently become trusted.
10. Unauthorized shell commands are blocked.
11. Unauthorized secret access is blocked.
12. Changed arguments invalidate approvals.
13. Cross-task approval reuse is rejected.
14. Cross-repository approval reuse is rejected.
15. Expired approvals are rejected.
16. Unauthorized users cannot approve actions.
17. Direct tool execution cannot bypass policy.
18. Valid low-risk repository operations continue to work.
19. Existing protected-file restrictions continue working.
20. Existing secret redaction continues working.
21. Existing prompt-injection fencing continues working.

Include a full adversarial test using a malicious GitHub issue containing instructions to ignore previous rules, read .env, print environment variables, execute arbitrary shell commands, and exfiltrate secrets.

Verify that legitimate bug-fixing requirements remain usable while unauthorized operations are rejected.

## 12. BACKWARD COMPATIBILITY AND PERFORMANCE

Preserve existing API contracts wherever possible.

Support legacy task and plan payloads safely.

Missing legacy provenance must not be interpreted as proof of trust.

Use an explicit compatibility policy for legacy objects at execution boundaries.

Avoid unnecessary database migrations.

If persistent provenance or approval records require migrations, provide reversible migration scripts and update the corresponding schemas.

Avoid unnecessary LLM calls.

Keep provenance operations deterministic and lightweight.

Do not break:

- GitHub OAuth.
- GitHub App integration.
- Issue ingestion.
- Task creation.
- Task planning.
- Agent execution.
- Workspace isolation.
- Bounded repair.
- Code review.
- Test generation.
- Verification.
- Pull request creation.

## 13. DOCUMENT EVERYTHING

Create:

Docs/security/provenance/

Required documents:

1. README.md
2. EXISTING_ARCHITECTURE_AUDIT.md
3. PROVENANCE_ARCHITECTURE.md
4. TAINT_TRACKING_DESIGN.md
5. DATA_FLOW_AND_TRUST_BOUNDARIES.md
6. EXECUTION_POLICY.md
7. HUMAN_APPROVAL_DESIGN.md
8. SECURITY_RESEARCH.md
9. THREAT_MODEL.md
10. IMPLEMENTATION_LOG.md
11. TESTING_STRATEGY.md
12. FUTURE_IMPROVEMENTS.md

Documentation must explain:

- Existing implementation.
- Identified problems.
- Research background.
- Architecture decisions.
- Data models.
- Trust levels.
- Taint propagation.
- Execution enforcement.
- Approval workflow.
- Threat scenarios.
- Security limitations.
- Test results.
- Performance impact.
- Migration and compatibility.
- Future improvements.

Include Mermaid architecture, data-flow, and authorization diagrams.

Update the relevant parent security documentation to link to the new documentation.

## 14. IMPLEMENTATION EXECUTION STRATEGY

Work incrementally.

Stage 1: Audit existing architecture and document the data flow.

Stage 2: Implement provenance models and unit tests.

Stage 3: Implement taint propagation engine.

Stage 4: Integrate provenance into issue intake.

Stage 5: Integrate task schemas, planner, and replanner.

Stage 6: Integrate execution-time policy enforcement.

Stage 7: Integrate approval and audit logging.

Stage 8: Add adversarial and end-to-end tests.

Stage 9: Run existing regression tests.

Stage 10: Complete documentation and implementation report.

After each stage:

- Run relevant tests.
- Review security implications.
- Record changes.
- Fix regressions before continuing.

Do not rewrite unrelated modules.

Do not remove existing security mechanisms.

Do not introduce placeholder implementations or fake successful test results.

## 15. FINAL ACCEPTANCE CRITERIA

The task is complete only when:

- Provenance is assigned at issue intake.
- Provenance survives the entire planning lifecycle.
- Taint propagates through transformations.
- LLM outputs cannot escalate trust.
- Tool arguments have traceable provenance.
- Sensitive execution operations are policy-controlled.
- Human approval is narrowly scoped where required.
- No execution path bypasses policy enforcement.
- Security audit events are generated.
- Adversarial tests pass.
- Existing regression tests pass.
- Documentation is complete.
- Backward compatibility is verified.

## 16. FINAL IMPLEMENTATION REPORT

After implementation, provide:

1. Existing architecture findings.
2. Security gaps identified.
3. Final architecture.
4. Files created.
5. Files modified.
6. Database migrations, if any.
7. Detailed implementation explanation.
8. Data-flow explanation.
9. Execution policy explanation.
10. Approval mechanism explanation.
11. Tests executed and actual results.
12. Security scenarios covered.
13. Performance considerations.
14. Known limitations.
15. Remaining tasks.
16. Documentation locations.

Clearly distinguish completed work from planned or incomplete work.

Do not claim production readiness without corresponding evidence.

FINAL GOAL:

Transform the existing issue-to-task pipeline into a provenance-aware, policy-controlled agent execution architecture where untrusted information can guide legitimate development work but cannot independently acquire execution authority.