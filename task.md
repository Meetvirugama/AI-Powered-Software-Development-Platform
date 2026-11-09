# TASK: Implement Unified Tool Registry Architecture
## AI-Powered Software Development Platform
### Target coding agent: Antigravity 3.8 Flash

---

# 0. YOUR ROLE AND OBJECTIVE

Act as a Senior Backend Architect, Python Engineer, AI Agent Infrastructure Engineer, and Application Security Engineer.

You are working on my existing project:

**AI-Powered Software Development Platform**

Your task is to evolve the existing ToolRouter into a production-oriented Unified Tool Registry that can eventually support:

1. Built-in workspace tools.
2. Model Context Protocol (MCP) server tools.
3. External plugin tools.
4. Standardized JSON Schema validation.
5. Tool version management.
6. Tool-level security and risk classification.
7. Execution timeouts.
8. Rate limiting.
9. Output validation.
10. Centralized execution auditing.

IMPORTANT:

This is an existing production-oriented codebase. Do not build a new tool execution system from scratch.

Preserve the existing implementation wherever possible and extend it through controlled architectural refactoring.

Your implementation must be backward compatible with existing workspace tool functionality.

Do not sacrifice existing security controls for architectural simplicity.

You must perform actual implementation, testing, and documentation. Do not stop after producing an implementation plan.

---

# 1. FIRST UNDERSTAND THE EXISTING PROJECT

Before modifying anything, inspect the complete relevant backend implementation.

Start with these files:

- backend/agent/tools/router.py
- backend/sandbox/tool_policy_bridge.py
- backend/app/core/tool_api_policy.py
- backend/app/services/task_execution_orchestrator.py
- backend/app/models/task.py
- backend/app/repositories/task_repository.py
- backend/app/schemas/task.py
- backend/requirements.txt
- backend/requirements-dev.txt

Also inspect:

- WorkspaceManager
- WorkspacePathGuard
- PolicyEngine
- ToolDefinition
- ToolRequest
- ToolResult
- ToolInvocation
- Tool registration functions
- Existing tool handlers
- Redis integration
- Existing database migrations
- Existing authorization and approval logic
- Existing test fixtures and mocks

Search the entire repository for:

- ToolRouter
- ToolDefinition
- register_workspace_tools
- execute_tool
- _is_policy_guarded
- _validate_arguments
- _validate_value
- ToolInvocation
- tool_invocations
- policy_engine
- WorkspaceToolPolicyBridge

Do not assume the previous architectural assessment is completely accurate.

Verify every observation against the actual source code.

If an assumption is incorrect, document the actual implementation and adjust the design accordingly.

## 1.1 Existing architecture that must be preserved

The current system already provides:

- Tool registration.
- Argument validation.
- Command allowlisting.
- Dangerous command flag restrictions.
- Shell metacharacter checks.
- Path restrictions.
- Policy-engine authorization.
- Workspace lifecycle enforcement.
- Task approval checks.
- Protected branch restrictions.
- Secret redaction.
- Output size restrictions.
- Tool invocation auditing.

The WorkspaceToolPolicyBridge defines approximately 19 canonical workspace tools.

Examples:

- read_file
- write_file
- patch_file
- execute_command
- run_tests
- commit_task_changes
- push_task_branch
- create_draft_pr

Verify the actual complete list before implementation.

Preserve these tools and their existing functionality.

---

# 2. UNDERSTAND THE PROBLEMS WE ARE SOLVING

Document the existing implementation and explain these architectural problems.

## Problem 1: Limited ToolDefinition metadata

Current ToolDefinition primarily contains:

- name
- description
- parameters

It does not provide a standardized contract for:

- output_schema
- annotations
- risk_tier
- version
- source
- timeout_s
- rate_limit

We need a richer tool definition.

## Problem 2: Hand-written JSON Schema validation

The current router uses custom validation logic.

It does not provide complete standardized support for:

- $ref
- $defs
- oneOf
- anyOf
- allOf
- not
- pattern
- format
- uniqueItems
- multipleOf
- dependentRequired
- minProperties
- maxProperties

Replace custom validation with the Python jsonschema library.

Target JSON Schema Draft 2020-12.

Do not implement a second custom JSON Schema engine.

## Problem 3: Missing output validation

The current implementation does not consistently validate tool outputs against formal output schemas.

Introduce optional output_schema validation.

Maintain compatibility with existing handlers that return different output structures.

Do not invent output schemas without inspecting actual handler responses.

## Problem 4: No explicit tool versioning

The registry currently identifies tools primarily by their names.

Introduce explicit semantic versions.

Examples:

- workspace.read_file@1.0.0
- workspace.write_file@1.0.0
- github.create_pull_request@1.0.0

Support controlled schema evolution.

Prevent accidental version conflicts.

## Problem 5: Missing execution deadlines

Introduce per-tool timeout configuration.

Support:

- Async handlers.
- Blocking handlers.
- Subprocess handlers.
- External provider adapters in the future.

A timeout must not automatically cause a second execution.

Do not assume that cancelling an asyncio task terminates an underlying blocking operation.

Use subprocess termination and appropriate client-level timeouts where applicable.

## Problem 6: Missing rate limiting

Introduce configurable per-tool invocation limits.

Support scopes:

- user
- task
- provider
- global

Use the existing Redis infrastructure if available.

Use atomic Redis operations for distributed deployments.

Do not add another Redis instance.

## Problem 7: Missing semantic annotations and risk classification

Introduce MCP-compatible semantic annotations:

- readOnlyHint
- destructiveHint
- idempotentHint
- openWorldHint

Introduce separate internal risk tiers:

- low
- medium
- high
- critical

Never treat annotations supplied by an external MCP server as proof of safety.

Risk classification must be controlled by trusted platform configuration.

## Problem 8: Missing provider abstraction

The current implementation is mainly designed around built-in workspace tools.

Introduce execution adapter boundaries so that future MCP and plugin integrations do not require rewriting ToolRouter.

## Problem 9: Incomplete execution audit information

The existing tool_invocations table must be preserved.

Extend it where appropriate to support:

- tool version
- source
- provider
- risk tier
- schema fingerprint
- timeout status
- rate-limit status
- normalized error category

Avoid duplicate audit tables and duplicate data.

## Problem 10: Handler execution convention

Inspect the existing handler dispatch logic.

If the current implementation uses TypeError-based fallback to guess handler calling conventions, replace it with an explicit handler interface.

A TypeError raised inside a handler must never result in the same operation being executed a second time.

---

# 3. TARGET ARCHITECTURE

Implement the following logical architecture.

AI AGENT
    |
    v
UNIFIED TOOL REGISTRY
    |
    +-------------------------------+
    |               |               |
    v               v               v
BUILT-IN TOOLS    MCP TOOLS      PLUGIN TOOLS
    |               |               |
    v               v               v
Builtin Adapter  MCP Adapter    Plugin Adapter
    |               |               |
    v               v               v
Workspace       MCP Client     Plugin Provider
Bridge          (Future)        (Future)
    |               |               |
    +---------------+---------------+
                    |
                    v
           COMMON EXECUTION PIPELINE
                    |
          +---------+---------+
          |         |         |
          v         v         v
       SCHEMA    POLICY    EXECUTION
      VALIDATION ENGINE    LIMITS
          |         |         |
          +---------+---------+
                    |
                    v
            OUTPUT VALIDATION
                    |
                    v
             SECRET REDACTION
                    |
                    v
               AUDITING
                    |
                    v
                AI AGENT

Important architectural separation:

1. Unified Tool Registry manages metadata and tool resolution.
2. SchemaValidator manages standardized schema validation.
3. ExecutionPolicy manages common execution restrictions.
4. PolicyEngine remains responsible for authorization decisions.
5. WorkspaceToolPolicyBridge retains workspace-specific security.
6. BuiltinWorkspaceAdapter connects existing workspace handlers.
7. MCP and Plugin adapters are future integration boundaries.

Do not move workspace-specific authorization logic into the generic registry.

Do not bypass PolicyEngine.

---

# 4. IMPLEMENT THE NEW TOOL DEFINITION MODEL

Create or refactor the ToolDefinition model.

Suggested design:

```python
from dataclasses import dataclass, field
from typing import Any, Literal


@dataclass(frozen=True)
class ToolAnnotations:
    read_only_hint: bool = False
    destructive_hint: bool = False
    idempotent_hint: bool = False
    open_world_hint: bool = False


@dataclass(frozen=True)
class ToolRateLimit:
    requests: int
    window_seconds: int

    scope: Literal[
        "user",
        "task",
        "provider",
        "global"
    ] = "task"


@dataclass(frozen=True)
class ToolDefinition:
    name: str
    description: str

    input_schema: dict[str, Any]
    output_schema: dict[str, Any] | None = None

    annotations: ToolAnnotations = field(
        default_factory=ToolAnnotations
    )

    risk_tier: Literal[
        "low",
        "medium",
        "high",
        "critical"
    ] = "medium"

    version: str = "1.0.0"

    source: str = "builtin"

    timeout_s: float = 30.0

    rate_limit: ToolRateLimit | None = None
```

This is the target conceptual model.

Adapt it to the project's actual Pydantic/dataclass conventions.

Do not introduce conflicting models.

## 4.1 Requirements

- Maintain compatibility with existing parameters if required.
- Introduce input_schema as the standardized name.
- Provide a migration strategy for existing parameters.
- Avoid duplicate representations of the same schema.
- Validate tool names.
- Validate semantic versions.
- Validate risk tiers.
- Validate timeout values.
- Validate rate-limit configuration.
- Prevent invalid source metadata.
- Make tool definitions immutable after registration.
- Store validated schemas safely.

If a backwards-compatible parameters property is necessary, implement it as a controlled compatibility property rather than storing two independent schemas.

## 4.2 Tool identity

Design a collision-safe tool identity.

External servers can expose identical names.

For example:

- github.read_file
- filesystem.read_file
- workspace.read_file

Do not allow an untrusted provider to impersonate a built-in tool.

Use structured provider identity and namespace resolution.

Keep existing workspace tool names working during migration.

---

# 5. IMPLEMENT STANDARD JSON SCHEMA VALIDATION

Install:

```bash
pip install "jsonschema>=4.23,<5"
```

Update the correct backend dependency file.

Use Draft202012Validator.

Create:

backend/agent/tools/schema_validator.py

The validator must support:

- type
- required
- properties
- additionalProperties
- enum
- const
- $ref
- $defs
- oneOf
- anyOf
- allOf
- not
- pattern
- format
- uniqueItems
- minItems
- maxItems
- minimum
- maximum
- exclusiveMinimum
- exclusiveMaximum
- multipleOf
- minLength
- maxLength
- minProperties
- maxProperties
- dependentRequired
- conditional schemas

Requirements:

1. Validate the schema at registration time.
2. Validate arguments before execution.
3. Validate outputs when output_schema exists.
4. Produce deterministic validation errors.
5. Do not expose sensitive information in error messages.
6. Restrict schema size and nesting depth.
7. Reuse compiled validator instances where practical.
8. Avoid unnecessary repeated schema compilation.
9. Support locally registered $ref definitions.
10. Prevent uncontrolled remote $ref resolution.
11. Never allow untrusted schemas to trigger arbitrary network requests.

Use FormatChecker for supported formats.

Do not assume that format validation automatically guarantees security.

Add unit tests for valid and invalid schemas.

---

# 6. IMPLEMENT TOOL REGISTRY

Create:

backend/agent/tools/registry.py

Responsibilities:

- Register tools.
- Resolve tools.
- Unregister tools when permitted.
- Enable and disable tools.
- List available tools.
- Filter tools by source.
- Filter tools by permissions.
- Resolve versions.
- Detect duplicates.
- Detect conflicting registrations.
- Validate schemas during registration.
- Calculate schema fingerprints.
- Maintain provider identity.

The registry should become the single source of truth for tool definitions.

Avoid unnecessary global mutable state.

Use dependency injection consistent with the current architecture.

## 6.1 Registration requirements

Registration must reject:

- Empty names.
- Invalid schemas.
- Invalid versions.
- Unsupported source types.
- Invalid risk tiers.
- Invalid timeout values.
- Invalid rate-limit configurations.
- Duplicate conflicting identities.
- Untrusted attempts to register built-in tools.

Tool discovery must never automatically grant execution permission.

Separate:

DISCOVERED
    |
    v
VALIDATED
    |
    v
APPROVED
    |
    v
REGISTERED
    |
    v
ENABLED
    |
    v
EXECUTABLE

The initial implementation can retain an in-memory registry for built-in tools.

Do not introduce unnecessary database persistence if the current architecture does not require it.

---

# 7. IMPLEMENT TOOL EXECUTION ADAPTERS

Create a common adapter interface.

Suggested location:

backend/agent/tools/adapters/base.py

Use an explicit execution contract.

Conceptually:

```python
from typing import Protocol, Any


class ToolExecutionAdapter(Protocol):

    def execute(
        self,
        tool,
        arguments: dict[str, Any],
        context,
    ) -> Any:
        ...
```

Adapt the contract to support asynchronous execution where needed.

Implement:

## 7.1 BuiltinWorkspaceAdapter

File:

backend/agent/tools/adapters/builtin.py

Responsibilities:

- Integrate with existing WorkspaceToolPolicyBridge.
- Preserve all workspace operations.
- Preserve WorkspaceManager behavior.
- Preserve WorkspacePathGuard.
- Preserve task ownership checks.
- Preserve workspace lifecycle checks.
- Preserve protected branch restrictions.
- Preserve publication approval.
- Preserve command allowlists.

Do not duplicate the workspace bridge's security logic.

The adapter should call the existing trusted implementation.

All 19 existing workspace tools must continue functioning.

## 7.2 MCP adapter boundary

File:

backend/agent/tools/adapters/mcp.py

For this milestone, implement only the interface and necessary extension points.

Do not connect real MCP servers yet.

Define how future MCP tools will:

- Register metadata.
- Import input schemas.
- Import output schemas where available.
- Resolve server identity.
- Invoke tools.
- Handle remote errors.
- Apply timeouts.
- Validate responses.

Do not install an MCP SDK unless an actual requirement exists in this milestone.

## 7.3 Plugin adapter boundary

File:

backend/agent/tools/adapters/plugin.py

For this milestone, implement only the architecture boundary.

Do not implement external plugin integrations yet.

Define provider resolution, authentication boundary, invocation and error normalization responsibilities.

---

# 8. IMPLEMENT THE COMMON EXECUTION PIPELINE

Refactor ToolRouter so all execution adapters follow the same common lifecycle.

Required sequence:

1. Receive ToolRequest.
2. Resolve tool identity.
3. Confirm tool is registered.
4. Confirm tool is enabled.
5. Resolve approved tool version.
6. Validate input arguments.
7. Resolve trusted execution adapter.
8. Build execution context.
9. Check user authorization.
10. Check task authorization.
11. Check provider authorization where applicable.
12. Apply internal risk policy.
13. Check human approval requirements.
14. Apply rate limits.
15. Apply concurrency limits.
16. Execute with configured timeout.
17. Normalize execution result.
18. Validate output schema if configured.
19. Redact secrets.
20. Apply output size limits.
21. Persist audit information.
22. Return ToolResult.

Use the project's existing ToolRequest and ToolResult conventions.

Do not create incompatible response structures.

## 8.1 Important: policy-guarded handlers

Inspect:

```python
_is_policy_guarded
```

The current workspace bridge uses a special guarded execution path.

Do not allow arbitrary MCP or plugin handlers to set this marker.

Replace implicit trust based on a handler attribute with explicit trusted adapter configuration.

Only the built-in workspace adapter may use the special workspace policy contract.

Even then, the common execution pipeline must apply the required result sanitization and audit operations.

Never let an external adapter skip:

- Registry validation.
- Provider authorization.
- Rate limiting.
- Execution deadlines.
- Output sanitization.
- Audit logging.

Preserve all existing workspace authorization guarantees.

## 8.2 Important: prevent double execution

Remove TypeError-based execution signature fallback.

Never implement:

```python
try:
    output = handler(**arguments)
except TypeError:
    output = handler(request, agent_state)
```

Use explicit handler protocols or adapters.

A handler's internal TypeError must become an execution failure, not a second execution attempt.

Do not retry destructive operations automatically.

---

# 9. IMPLEMENT RISK-BASED POLICIES

Introduce internal risk classification.

Suggested initial configuration:

| Tool | Risk |
|---|---|
| read_file | low |
| list_files | low |
| inspect_git_diff | low |
| write_file | medium |
| patch_file | medium |
| run_tests | medium |
| execute_command | high |
| delete_file | high |
| push_task_branch | critical |
| create_draft_pr | critical |

These are starting classifications.

Inspect the actual behavior of each tool before assigning its final risk.

The system must distinguish between:

1. Semantic annotations.
2. Internal risk classification.
3. Authorization.
4. Human approval.

They are different concepts.

For example:

A tool can declare readOnlyHint=true, but the platform must still check whether the user can read the requested resource.

A tool can declare destructiveHint=false, but the platform must not automatically trust it.

MCP and plugin metadata must never be allowed to lower internally configured risk.

---

# 10. IMPLEMENT EXECUTION TIMEOUTS

Introduce per-tool timeout enforcement.

Example:

```python
timeout_s = tool.timeout_s
```

Support appropriate execution strategies.

For async operations:

- Use async deadlines.
- Handle cancellation.
- Normalize timeout errors.

For subprocess operations:

- Enforce subprocess timeout.
- Terminate the process.
- Kill it if graceful termination fails.
- Capture safe diagnostic information.

For blocking operations:

- Use suitable worker isolation.
- Do not assume thread cancellation terminates the operation.

For future remote providers:

- Use provider-level connect/read timeouts.
- Support request cancellation where available.

Record:

- Configured timeout.
- Actual duration.
- Timeout status.
- Execution outcome.

Do not automatically retry an operation after a timeout if the operation may already have completed.

---

# 11. IMPLEMENT RATE LIMITING

Inspect existing Redis utilities first.

Reuse the existing Redis connection and configuration.

Do not introduce a new Redis server.

Create:

backend/agent/tools/rate_limiter.py

Support:

- Per-user limits.
- Per-task limits.
- Per-provider limits.
- Global limits.
- Per-tool limits.

Use atomic Redis operations.

Do not use an in-memory counter as the production distributed rate limiter.

Provide a safe fallback only if the existing architecture explicitly supports one.

Rate limits must be configurable.

Do not hardcode arbitrary limits throughout handlers.

Example initial configurations:

read_file:
60 requests / minute / task

execute_command:
10 requests / minute / task

create_draft_pr:
3 requests / hour / user

These are examples. Adjust based on the existing execution workload.

Also implement configurable maximum concurrent executions per tool and provider if compatible with the current worker architecture.

Important:

A rate-limited operation must never reach its handler.

---

# 12. OUTPUT VALIDATION AND SANITIZATION

This is a critical part of the task.

Currently, generic handlers and policy-guarded workspace handlers can take different execution paths.

Ensure every adapter passes through a common post-execution boundary.

The order must be:

Tool execution
    |
    v
Normalize result
    |
    v
Validate output schema
    |
    v
Redact secrets
    |
    v
Enforce output limits
    |
    v
Record audit event
    |
    v
Return ToolResult

Preserve existing secret redaction patterns.

Inspect all existing output sanitization logic.

Do not duplicate sanitization implementations.

Avoid logging raw credentials or sensitive output.

Treat MCP and plugin outputs as untrusted external data.

External tool responses must never modify authorization policies or trusted registry metadata.

For tools without a defined output schema, preserve their existing response format and document the missing contract.

---

# 13. AUDITING AND DATABASE CHANGES

Inspect the existing ToolInvocation model and tool_invocations table.

Do not replace them.

Extend the existing invocation auditing system.

Potential fields:

- tool_version
- tool_source
- provider_id
- risk_tier
- schema_fingerprint
- execution_timeout_s
- execution_timed_out
- rate_limit_status
- error_category

Choose fields based on actual project conventions.

Create separate provider or registry tables only if necessary.

Possible future tables:

tool_providers
tool_registry

An immutable version history table can be considered if required.

Requirements:

1. Use existing SQLAlchemy conventions.
2. Create proper Alembic migrations.
3. Ensure migration rollback works.
4. Maintain backward compatibility.
5. Update repository methods.
6. Update API schemas if exposed.
7. Avoid storing secrets.
8. Preserve sanitized_arguments behavior.
9. Ensure audit failures do not silently create security bypasses.

Classify execution outcomes properly.

At minimum, distinguish:

- SUCCESS
- DENIED
- FAILED
- TIMEOUT
- RATE_LIMITED

Preserve existing status conventions where API compatibility requires them.

Do not silently change API response semantics.

---

# 14. TASK EXECUTION ORCHESTRATOR INTEGRATION

Inspect:

backend/app/services/task_execution_orchestrator.py

Currently, ToolRouter is instantiated inside task orchestration.

Refactor this carefully.

The orchestrator should depend on the unified registry and execution interfaces.

Requirements:

- Do not duplicate registry initialization.
- Do not register the same workspace tools multiple times.
- Preserve dependency injection.
- Preserve existing agent state.
- Preserve execution context creation.
- Preserve task lifecycle behavior.
- Preserve workspace ownership checks.
- Preserve approval flow.
- Preserve existing agent/tool calling behavior.

Keep the refactor small and testable.

Do not rewrite the entire orchestrator.

---

# 15. DOCUMENTATION REQUIREMENTS — MANDATORY

I want every architectural decision, research finding, implementation detail, and testing result documented.

Documentation is a core deliverable, not an optional final step.

First inspect:

Docs/agentic-chat/
Docs/agentic-chat/07-tool-registry-and-tool-reference.md
Docs/agentic-chat/09-security-and-permissions.md
Docs/agentic-chat/13-testing-strategy.md
Docs/agentic-chat/17-future-enhancements.md

Also inspect the main Docs/README.md.

Update existing documents where appropriate.

Do not create duplicate documentation for topics already documented.

Create or update the following documentation structure, adapting names to the existing convention:

Docs/tool-registry/

00-existing-architecture-audit.md

Include:

- Current ToolRouter implementation.
- Existing ToolDefinition.
- Existing handler architecture.
- WorkspaceToolPolicyBridge.
- Existing policy integration.
- Current invocation auditing.
- Current security mechanisms.
- Existing tests.
- Exact architectural limitations.
- Actual file references.

01-requirements-and-scope.md

Include:

- Problem statement.
- Functional requirements.
- Non-functional requirements.
- Security requirements.
- Compatibility requirements.
- Scope of this milestone.
- Out-of-scope features.
- Acceptance criteria.

02-research-and-design-decisions.md

Document detailed technical research.

Include:

A. JSON Schema Draft 2020-12.

- Why standardized validation is needed.
- Custom validation limitations.
- Draft 2020-12 capabilities.
- jsonschema library selection.
- FormatChecker.
- Local $ref handling.
- External reference security.
- Performance considerations.

B. MCP tool architecture.

- MCP tool definition concepts.
- inputSchema.
- outputSchema.
- annotations.
- Tool discovery.
- Provider identity.
- Trust boundaries.
- Why MCP server metadata cannot determine authorization.

C. Versioning.

- Semantic versioning.
- Schema fingerprints.
- Compatibility.
- Breaking changes.
- Version retirement.

D. Risk classification.

- readOnlyHint.
- destructiveHint.
- idempotentHint.
- openWorldHint.
- Internal risk tiers.
- Human approval.
- Policy integration.

E. Execution controls.

- Timeout mechanisms.
- Cancellation.
- Subprocess termination.
- Rate limiting.
- Redis atomic operations.
- Concurrency control.

F. Auditing.

- Existing audit architecture.
- Required additional metadata.
- Secret redaction.
- Error classification.

G. Alternatives considered.

For every major design decision explain:

- What problem it solves.
- Alternatives considered.
- Why the selected approach is preferable.
- Tradeoffs.
- Security implications.
- Performance implications.

03-system-architecture.md

Include:

- Target architecture.
- Component responsibilities.
- Module structure.
- Registry design.
- Adapter design.
- Execution lifecycle.
- Data flow.
- Security boundaries.
- Error flow.

Use Mermaid diagrams.

04-tool-definition-and-registry.md

Include:

- Final ToolDefinition.
- ToolAnnotations.
- ToolRateLimit.
- Registration.
- Tool identity.
- Version resolution.
- Source identification.
- Schema fingerprinting.
- Enable/disable lifecycle.

05-schema-validation.md

Include:

- JSON Schema implementation.
- Supported schema features.
- Registration validation.
- Input validation.
- Output validation.
- $ref policy.
- Validation errors.
- Test cases.

06-execution-pipeline.md

Include detailed step-by-step execution logic.

Explain each stage:

- Registry resolution.
- Input validation.
- Context construction.
- Authorization.
- Risk evaluation.
- Human approval.
- Rate limiting.
- Concurrency limiting.
- Timeout enforcement.
- Adapter execution.
- Output validation.
- Redaction.
- Auditing.

07-security-and-permissions.md

Include:

- Existing security controls.
- New security controls.
- Trusted adapter model.
- Workspace authorization.
- MCP trust boundary.
- Plugin trust boundary.
- SSRF prevention.
- External reference restrictions.
- Command restrictions.
- Path restrictions.
- Secret management.
- Failure handling.
- Threat model.

08-database-and-auditing.md

Include:

- Existing ToolInvocation model.
- Database changes.
- Migration details.
- New audit fields.
- Provider persistence.
- Error categories.
- Retention considerations.
- Sensitive-data handling.

09-testing-and-validation.md

Include:

- Unit tests.
- Integration tests.
- Security tests.
- Regression tests.
- Performance tests.
- Test commands.
- Test results.
- Known limitations.

10-implementation-changelog.md

Maintain a chronological record of:

- Date.
- Phase.
- Files changed.
- Features implemented.
- Decisions.
- Tests executed.
- Failures encountered.
- Fixes.
- Remaining work.

11-future-mcp-and-plugin-integration.md

Document:

- Future MCP integration plan.
- MCP client architecture.
- Provider configuration.
- Tool discovery.
- Approval workflow.
- External authentication.
- Plugin architecture.
- Provider monitoring.
- Future implementation sequence.

12-operations-and-troubleshooting.md

Include:

- Common validation failures.
- Registration errors.
- Provider errors.
- Timeout behavior.
- Redis rate-limit errors.
- Audit failures.
- Debugging instructions.
- Operational configuration.

README.md

Create an index explaining:

- Purpose.
- Architecture.
- Document navigation.
- Implementation status.
- Current supported capabilities.
- Future capabilities.

Documentation rules:

1. Use accurate file paths and class names.
2. Include actual code examples from the implemented system.
3. Include Mermaid diagrams.
4. Explain why every major change exists.
5. Document all configuration variables.
6. Document all database migrations.
7. Document all tests and their results.
8. Clearly distinguish implemented features from planned features.
9. Never claim a feature is implemented when it is only an interface or proposal.
10. Update documentation as implementation progresses, not only at the end.

---

# 16. TESTING REQUIREMENTS

Testing is mandatory.

Inspect the existing tests first.

Preserve and run relevant existing tests, especially:

- backend/tests/test_tool_router.py
- backend/tests/test_security_w3_tools.py
- backend/tests/test_prit_w3_d3_workspace_execution.py
- backend/tests/test_prit_w3_d4_restricted_test_runner.py
- backend/tests/test_prit_w3_d5_verification_and_draft_pr.py
- backend/tests/test_prit_w3_d7_acceptance.py
- backend/tests/test_week3_day3_day4_and_fixes.py

Verify these exact paths exist before running them.

Do not delete existing tests to make the suite pass.

## 16.1 Registry tests

Test:

- Successful registration.
- Duplicate registration.
- Conflicting version registration.
- Unknown tool.
- Disabled tool.
- Invalid source.
- Invalid risk tier.
- Invalid timeout.
- Invalid rate limit.
- Schema fingerprint.
- Version resolution.
- Provider namespace collision.

## 16.2 Schema validation tests

Test:

- Valid object.
- Invalid property type.
- Missing required field.
- Invalid enum.
- Invalid pattern.
- Valid $defs.
- Valid local $ref.
- Invalid $ref.
- oneOf.
- anyOf.
- allOf.
- uniqueItems.
- multipleOf.
- minProperties.
- maxProperties.
- Format validation.
- Malformed schema.
- External reference rejection.
- Excessive schema nesting.

## 16.3 Execution tests

Test:

- Built-in adapter execution.
- Input validation before handler execution.
- Authorization denial.
- Successful execution.
- Invalid output.
- Secret redaction.
- Output size restriction.
- Handler exception.
- Internal TypeError.
- No double execution.
- Timeout.
- Rate-limit rejection.
- Concurrency-limit rejection.
- Audit persistence.

## 16.4 Security regression tests

Specifically verify:

1. External tools cannot claim trusted built-in identity.
2. External tools cannot self-assign lower risk.
3. MCP annotations do not bypass authorization.
4. External adapters cannot bypass common validation.
5. External adapters cannot bypass output sanitization.
6. Invalid input never reaches handlers.
7. Rate-limited requests never reach handlers.
8. A failed authorization check always denies execution.
9. Workspace paths remain restricted.
10. Protected branch restrictions remain intact.
11. Task ownership restrictions remain intact.
12. Human publication approval remains mandatory.
13. Secrets are not written into audit records.
14. Timeouts do not cause duplicate execution.
15. Provider name collisions cannot cause tool impersonation.

## 16.5 Run the wider backend test suite

Run:

- Focused unit tests.
- Existing security regression tests.
- Relevant integration tests.
- Database migration tests.
- Full backend test suite where the environment permits.

Record:

- Number of tests passed.
- Number of tests failed.
- Number skipped.
- Exact failure reasons.
- Existing failures versus newly introduced failures.

Never report tests as passing unless they were actually executed.

---

# 17. PERFORMANCE AND QUALITY REQUIREMENTS

This platform must remain efficient.

Avoid:

- Recompiling schemas unnecessarily.
- Recreating Redis clients for each call.
- Repeated registry initialization.
- Excessive database queries.
- Unnecessary database tables.
- Duplicate audit records.
- Excessive logging.
- Large tool outputs.
- Blocking asynchronous execution.
- Unbounded concurrent tool calls.

Measure performance before and after the refactor where possible.

Benchmark:

1. Tool registration.
2. Tool resolution.
3. Schema validation.
4. Execution overhead.
5. Audit persistence.

Document results.

Do not claim performance improvements without measurements.

---

# 18. IMPLEMENTATION ORDER

Follow this sequence.

Do not implement everything in one uncontrolled refactoring.

PHASE 0 — Existing code audit

- Inspect files.
- Map dependencies.
- Identify existing tests.
- Identify security boundaries.
- Document the current architecture.
- Record existing failures.

PHASE 1 — Registry foundation

- Expand ToolDefinition.
- Introduce ToolAnnotations.
- Introduce ToolRateLimit.
- Introduce source metadata.
- Introduce tool versioning.
- Implement UnifiedToolRegistry.
- Preserve compatibility.

PHASE 2 — JSON Schema

- Install jsonschema.
- Implement SchemaValidator.
- Validate schemas during registration.
- Validate arguments.
- Add output schema support.
- Add schema tests.

PHASE 3 — Execution architecture

- Introduce explicit adapter interface.
- Implement BuiltinWorkspaceAdapter.
- Add MCP adapter boundary.
- Add Plugin adapter boundary.
- Refactor ToolRouter dispatch.
- Remove TypeError-based fallback.
- Preserve workspace policies.

PHASE 4 — Security and execution limits

- Introduce internal risk policy.
- Introduce timeout manager.
- Introduce Redis rate limiter.
- Introduce concurrency controls.
- Unify output sanitization.
- Verify trusted adapter restrictions.

PHASE 5 — Audit and database

- Extend ToolInvocation where necessary.
- Add migrations.
- Update repository methods.
- Update response schemas.
- Verify audit correctness.

PHASE 6 — Orchestrator integration

- Inject registry.
- Remove unnecessary duplicate initialization.
- Preserve agent execution.
- Preserve existing task and workspace behavior.

PHASE 7 — Testing

- Run new tests.
- Run existing regression tests.
- Run security tests.
- Run migration tests.
- Run wider backend tests.
- Fix regressions.

PHASE 8 — Documentation and final review

- Complete all documentation.
- Update implementation changelog.
- Update documentation index.
- Verify diagrams.
- Verify implementation status.
- Produce final implementation report.

You may adjust the order if the actual dependencies require it, but document why.

---

# 19. STRICT SCOPE BOUNDARIES

Implement now:

- Unified Tool Registry.
- Rich tool metadata.
- JSON Schema Draft 2020-12 validation.
- Input schema validation.
- Optional output schema validation.
- Tool versioning.
- Source identification.
- MCP-compatible annotations.
- Internal risk classification.
- Execution adapter architecture.
- Built-in workspace adapter.
- MCP adapter interface.
- Plugin adapter interface.
- Execution timeouts.
- Rate limiting.
- Concurrency controls where supported.
- Common output sanitization.
- Improved audit logging.
- Regression testing.
- Complete documentation.

Do NOT implement in this milestone:

- Actual MCP server connections.
- Automatic MCP server discovery over the network.
- Arbitrary third-party plugin installation.
- Arbitrary remote code execution.
- New frontend MCP management screens.
- External plugin marketplaces.
- Unnecessary changes to the agent's LLM orchestration.
- A complete rewrite of WorkspaceManager.
- A replacement for PolicyEngine.

These belong to future milestones.

---

# 20. SECURITY RULES THAT MUST NEVER BE VIOLATED

1. Never weaken existing authorization.
2. Never remove WorkspacePathGuard.
3. Never remove command allowlists.
4. Never remove dangerous flag restrictions.
5. Never allow untrusted tools to become trusted built-in tools.
6. Never trust external semantic annotations for authorization.
7. Never allow MCP tools to bypass PolicyEngine.
8. Never allow plugin tools to bypass common execution controls.
9. Never expose credentials in logs.
10. Never execute invalid arguments.
11. Never retry destructive operations automatically.
12. Never treat a timeout as proof that a remote operation failed.
13. Never allow uncontrolled remote JSON Schema references.
14. Never allow one task to access another task's workspace.
15. Never bypass protected branch restrictions.
16. Never bypass human publication approval.
17. Never silently swallow security failures.
18. Never claim a test passed without running it.

If a requested change conflicts with an existing security guarantee, stop and document the conflict before implementing that change.

---

# 21. DEFINITION OF DONE

The task is complete only when the following conditions are satisfied.

## Architecture

- [ ] Unified Tool Registry implemented.
- [ ] ToolDefinition expanded.
- [ ] Source and version management implemented.
- [ ] Execution adapters implemented.
- [ ] Existing workspace bridge integrated.
- [ ] MCP adapter boundary documented.
- [ ] Plugin adapter boundary documented.

## Validation

- [ ] Standard jsonschema validation implemented.
- [ ] Draft 2020-12 used.
- [ ] Registration-time schema validation implemented.
- [ ] Input validation implemented.
- [ ] Optional output validation implemented.
- [ ] Remote reference resolution restricted.

## Execution

- [ ] Timeouts implemented.
- [ ] Rate limits implemented.
- [ ] Concurrency limits implemented or documented as unsupported.
- [ ] Handler dispatch is explicit.
- [ ] Double-execution issue fixed.
- [ ] Common output sanitization implemented.

## Security

- [ ] Existing workspace security preserved.
- [ ] PolicyEngine integration preserved.
- [ ] Risk classification implemented.
- [ ] External provider trust boundary enforced.
- [ ] Secret redaction preserved.
- [ ] Approval checks preserved.

## Auditing

- [ ] Existing ToolInvocation preserved.
- [ ] Required audit metadata added.
- [ ] Database migrations tested.
- [ ] Error categories standardized.
- [ ] No credentials stored in audit records.

## Testing

- [ ] New unit tests pass.
- [ ] Existing tool router tests pass.
- [ ] Existing security tests pass.
- [ ] Workspace regression tests pass.
- [ ] Database migration tests pass.
- [ ] Wider backend test suite executed where possible.

## Documentation

- [ ] Existing documentation reviewed.
- [ ] Architecture audit updated.
- [ ] Research and design decisions documented.
- [ ] Implementation explained.
- [ ] Security explained.
- [ ] Database changes documented.
- [ ] Testing results documented.
- [ ] Changelog updated.
- [ ] Future MCP/plugin roadmap documented.

---

# 22. FINAL IMPLEMENTATION REPORT

At the end, provide a comprehensive report.

Use this structure:

## A. Executive Summary

Explain what changed and why.

## B. Existing vs New Architecture

Explain the previous architecture and final architecture.

## C. Files Created

List every new file and its responsibility.

## D. Files Modified

For each file explain:

- What changed.
- Why it changed.
- Which functionality was affected.

## E. Technical Implementation

Explain:

- Registry.
- ToolDefinition.
- Schema validation.
- Versioning.
- Annotations.
- Risk policies.
- Adapters.
- Timeouts.
- Rate limiting.
- Output validation.
- Auditing.

## F. Security Analysis

Explain existing security preservation and new protections.

## G. Database Changes

List migrations and model changes.

## H. Testing Results

Give actual test commands and results.

## I. Documentation Created/Updated

List every documentation file.

## J. Remaining Issues

Clearly identify anything incomplete.

## K. Future MCP and Plugin Integration

Explain how the architecture supports future integration and what remains to be implemented.

## L. Final Acceptance Checklist

Mark each requirement:

- COMPLETED
- PARTIALLY COMPLETED
- NOT COMPLETED
- BLOCKED

Do not mark an item completed without evidence.

---

# 23. EXECUTION INSTRUCTIONS FOR ANTIGRAVITY

Follow these working rules throughout the task.

1. Start by inspecting the actual repository.
2. Read all relevant source files before modifying them.
3. Read the existing documentation.
4. Create the implementation audit first.
5. Present the proposed file-level implementation plan.
6. Implement incrementally.
7. Keep changes focused on this feature.
8. Update documentation alongside implementation.
9. Run tests after each significant phase.
10. Fix regressions before proceeding.
11. Do not remove existing functionality to simplify implementation.
12. Do not create unnecessary abstractions.
13. Do not duplicate existing utilities.
14. Do not invent configuration or database structures without inspecting the project.
15. Do not silently skip failed tests.
16. Do not leave placeholder implementations while claiming features are complete.
17. Clearly document future-only adapter boundaries.
18. Keep the code readable, typed and maintainable.

If the implementation is too large for one working session, complete it in phases and maintain an accurate progress document so work can resume without repeating completed changes.

Do not stop after the planning phase. Continue with implementation unless a genuine blocker requires my decision.

**MOST IMPORTANT: Preserve the existing working platform. The goal is to improve the architecture, not break or replace the existing system.**

Begin with PHASE 0: inspect the repository, audit the existing ToolRouter architecture, and document the findings. Then proceed through the implementation phases in order.