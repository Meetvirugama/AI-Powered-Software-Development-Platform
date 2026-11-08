# MASTER IMPLEMENTATION PROMPT — Secure Sandbox Execution Architecture
## Project: AI-Powered Software Development Platform
### Target Agent: Antigravity 3.8 Flash

---

# 0. YOUR ROLE

Act as a Senior Backend Engineer, Application Security Engineer, DevSecOps Architect, and Software Infrastructure Engineer.

You are working on my existing project:

**AI-Powered Software Development Platform**

Your responsibility is to research, audit, design, implement, test, and document a production-grade secure execution architecture for untrusted GitHub repositories.

This is an existing project. Do not create a separate demonstration application or replace the existing architecture unnecessarily.

You must understand the current codebase before making modifications.

## Primary objective

Currently, our platform can execute commands, run tests, install dependencies, and perform AI-assisted code modifications.

However, repository code is currently executed directly on the API host.

We need to replace this unsafe execution architecture with an isolated sandbox architecture using:

- SandboxBackend abstraction.
- Docker-based execution.
- gVisor runtime support.
- Dedicated Runner Service.
- CPU, RAM, PID, disk and execution-time restrictions.
- Network isolation.
- Filesystem isolation.
- Secure workspace lifecycle management.
- Dependency installation and offline execution phases.

The API server must never directly execute untrusted repository code in production.

**This is a P0 security task. Prioritize security and correctness over implementation speed.**

---

# 1. IMPORTANT DEVELOPMENT RULES

Follow these rules throughout the task.

## 1.1 Audit before implementation

Before modifying anything:

1. Explore the entire repository.
2. Understand the existing backend architecture.
3. Locate all command execution entry points.
4. Find every place that executes Python, Node.js, pytest, npm, npx, git or shell commands.
5. Identify every component that interacts with workspaces.
6. Identify all agents that use CommandRunner.
7. Identify existing security controls.
8. Understand how task IDs, repository IDs and user IDs are managed.
9. Understand existing authentication and authorization.
10. Identify deployment architecture.

Do not assume the architecture described in this prompt perfectly matches the current source code.

The actual repository is the source of truth.

If a component already exists, extend it instead of creating a duplicate.

## 1.2 Preserve existing functionality

Do not break:

- GitHub repository integration.
- Repository cloning.
- Git worktrees.
- WorkspaceManager.
- Code review agent.
- Bug detection agent.
- Test generation agent.
- AI orchestrator.
- Code modification workflows.
- Diff generation.
- File reading and writing.
- Existing task lifecycle.
- Existing authentication.
- Existing API contracts unless changes are necessary.

All existing agents should continue working through the new secure execution architecture.

## 1.3 No fake implementation

Never:

- Create a Docker backend that internally uses host subprocess.
- Claim gVisor support without actually verifying the runtime.
- Claim network isolation based only on environment variables.
- Claim CPU/RAM protection based only on application monitoring.
- Silently fall back to local subprocess in production.
- Hardcode Docker credentials.
- Expose the Docker socket through an unrestricted API.
- Use unverified container image digests.
- Mark security tests as passed without running them.
- Create documentation describing features that do not exist.

If infrastructure is unavailable, implement the code that can safely be implemented, document the infrastructure dependency, and clearly mark the relevant functionality as unverified or blocked.

## 1.4 Documentation is mandatory

Every major implementation decision must be documented.

I want to maintain long-term technical documentation for this project.

Do not put all documentation into one short README.

Create a structured documentation system with architecture diagrams, sequence diagrams, component responsibilities, security decisions, APIs, configuration, testing, deployment and troubleshooting.

## 1.5 Work in manageable stages

Do not attempt a blind large-scale rewrite.

Work in the following order:

Audit → Research → Architecture → Design → Implementation → Testing → Documentation → Final Verification.

Maintain a progress document so that work can continue without losing decisions.

---

# 2. PHASE 1 — COMPLETE EXISTING CODEBASE AUDIT

First, analyze the actual source code.

## 2.1 Components to investigate

Find and inspect the actual implementations of:

### A. WorkspaceManager

Reported existing responsibility:

- Creates task-specific workspaces.
- Uses Git worktrees.
- Creates task branches.
- Has directory-copy fallback.
- Manages workspace paths.
- Handles workspace cleanup.

Investigate:

- How task workspaces are created.
- Whether different users can access each other's workspaces.
- Whether worktrees share Git metadata.
- How fallback copying works.
- Whether symbolic links can escape the workspace.
- How workspace deletion works.
- Whether concurrent tasks create race conditions.
- Whether workspaces are persisted or recreated.

### B. WorkspacePathGuard

Investigate:

- Path traversal protection.
- Absolute path handling.
- Symbolic links.
- Hard links where applicable.
- `.git` restrictions.
- `.env` restrictions.
- Private key restrictions.
- File read/write operations.
- Whether every file access passes through the guard.

Identify bypass opportunities.

### C. WorkspaceResourceMonitor

Reported existing limits:

- Disk: 500 MB.
- Individual file: 5 MB.
- Files modified: 50.

Investigate:

- How these limits are enforced.
- Whether limits are checked before or after writes.
- Whether directory copies bypass them.
- Whether temporary files count toward disk usage.
- Whether symlinks affect calculations.
- Whether concurrent writes can bypass limits.

Identify which limits are application-level and which can be enforced by the OS.

### D. CommandRunner

Investigate:

- Command allowlist.
- Argument validation.
- Shell injection protection.
- Dangerous flags.
- Environment sanitization.
- Timeout handling.
- Process-group handling.
- Output limits.
- Python execution.
- Pytest execution.
- npm execution.
- Node.js execution.
- Git operations.

Specifically identify:

- Every direct subprocess call.
- Every use of `sys.executable`.
- Every command that executes repository-controlled code.
- Every package installation path.
- Every indirect execution path.

### E. Other execution entry points

Search the entire backend for:

- subprocess.Popen
- subprocess.run
- subprocess.call
- os.system
- os.popen
- asyncio.create_subprocess_exec
- asyncio.create_subprocess_shell
- shell=True
- exec
- eval
- pytest invocation
- npm install
- npm test
- pip install
- setup.py
- build backend execution

Do not assume that all execution happens through CommandRunner.

Find every entry point.

## 2.2 Existing security risk analysis

For every identified issue, document:

1. Vulnerability.
2. Root cause.
3. Exploitation scenario.
4. Potential impact.
5. Existing mitigation.
6. Missing mitigation.
7. Required solution.
8. Priority.
9. Files affected.
10. Acceptance criteria.

Classify issues as:

- Critical
- High
- Medium
- Low

## 2.3 Audit output

Create:

Docs/security/sandbox/01-existing-architecture-audit.md

Include:

- Existing architecture.
- Existing components.
- Actual file paths.
- Actual class and function names.
- Existing execution flow.
- Security gaps.
- Vulnerability scenarios.
- Existing protections.
- Limitations.
- Recommended changes.
- Implementation dependencies.

Also create a complete execution-entry-point inventory.

Do not start major implementation until this audit is completed.

---

# 3. PHASE 2 — RESEARCH AND TECHNICAL DECISIONS

Research the technologies that are relevant to secure execution.

The objective is not to integrate every available technology.

The objective is to select the safest practical architecture for our project.

## 3.1 Docker

Research:

- Docker Engine architecture.
- Container lifecycle.
- Linux namespaces.
- cgroups.
- seccomp.
- Linux capabilities.
- Read-only root filesystem.
- Bind mounts.
- tmpfs.
- Non-root execution.
- Network isolation.
- Container resource limits.
- Container cleanup.
- Image security.
- Container escape risks.

Official documentation:

https://docs.docker.com/

https://docs.docker.com/engine/security/

https://docs.docker.com/engine/containers/resource_constraints/

https://docs.docker.com/engine/security/seccomp/

## 3.2 gVisor

Research:

- gVisor architecture.
- Sentry.
- Gofer.
- runsc runtime.
- Docker integration.
- Filesystem behavior.
- Network behavior.
- Supported system calls.
- Performance overhead.
- Compatibility limitations.
- Deployment requirements.
- Security boundaries.

Official resources:

https://gvisor.dev/

https://gvisor.dev/docs/

https://gvisor.dev/docs/user_guide/containerd/quick_start/docker/

We prefer gVisor because it adds a userspace-kernel isolation layer without requiring KVM.

Do not claim that gVisor eliminates all container escape risks.

## 3.3 Firecracker

Research:

- MicroVM architecture.
- KVM requirements.
- Snapshotting.
- Isolation boundaries.
- Performance.
- Resource overhead.
- Operational complexity.

Official resources:

https://firecracker-microvm.github.io/

https://github.com/firecracker-microvm/firecracker

Evaluate Firecracker as a future alternative, not an immediate mandatory implementation.

## 3.4 Other projects

Study:

- E2B: https://github.com/e2b-dev
- OpenHands: https://github.com/All-Hands-AI/OpenHands
- Daytona: https://github.com/daytonaio/daytona
- nsjail: https://github.com/google/nsjail
- bubblewrap: https://github.com/containers/bubblewrap
- Docker MCP Gateway: https://github.com/docker/mcp-gateway

For each project document:

- Architecture.
- Main functionality.
- Isolation technology.
- Integration approach.
- Strengths.
- Weaknesses.
- Dependencies.
- Licensing.
- Whether it is suitable for our platform.
- What we can learn or reuse.
- What we should not copy.

Verify current licences and versions from authoritative sources.

Do not assume the entire product and its SDK have the same licence.

## 3.5 Research deliverable

Create:

Docs/security/sandbox/02-technology-research.md

Include a detailed comparison table.

Final expected decision:

- Docker: primary container management.
- gVisor: additional production isolation.
- Firecracker: future microVM option.
- E2B: optional managed alternative.
- Daytona: architecture reference; evaluate AGPL implications.
- OpenHands: runtime architecture reference.

Do not introduce unnecessary dependencies.

---

# 4. PHASE 3 — DESIGN THE NEW ARCHITECTURE

Introduce a pluggable sandbox architecture.

The API server should manage tasks, while a separate runner executes untrusted code.

## 4.1 Target architecture

Implement the following logical architecture:

USER
 |
 v
FRONTEND
 |
 v
API SERVER
 |
 +---- Authentication
 |
 +---- Repository Management
 |
 +---- AI Orchestrator
 |
 +---- WorkspaceManager
 |
 +---- CommandRunner
          |
          v
     SandboxBackend
          |
          +-----------------------+
          |                       |
          v                       v
   LocalSubprocessBackend   RunnerClient
   Development only              |
                                 v
                          RUNNER SERVICE
                                 |
                                 v
                            Docker Engine
                                 |
                                 v
                              gVisor
                                 |
                    +------------+------------+
                    |            |            |
                    v            v            v
                 Task 123     Task 124     Task 125
                 Container    Container    Container

Production API server must not execute untrusted repository code locally.

## 4.2 SandboxBackend interface

Create an abstraction based on the existing project architecture.

Suggested location:

backend/execution/sandbox/base.py

Expected logical operations:

- create_workspace()
- execute()
- read_file()
- write_file()
- get_diff()
- destroy_workspace()
- get_status()
- get_resource_usage()

Use typed interfaces and structured request/response models.

Do not implement empty methods or fake responses.

Each operation must have clear error handling.

Support asynchronous execution if the existing backend uses async architecture.

Do not introduce unnecessary synchronous blocking operations into an async API.

## 4.3 LocalSubprocessBackend

Move the existing subprocess behavior into a dedicated backend.

Rules:

- Allowed only when APP_ENV=development.
- Must reject production execution.
- Must not be used as an automatic fallback.
- Must preserve current development workflows.
- Must continue enforcing existing command and path guards.

Production initialization must fail closed if the secure runner is unavailable or misconfigured.

Do not infer development mode from missing environment variables.

Require an explicit, validated environment configuration.

## 4.4 ContainerBackend

Implement the production backend.

It should communicate with the Runner Service.

Do not allow arbitrary API requests to construct unrestricted Docker commands.

Use validated configuration and a narrow operation interface.

## 4.5 SandboxFactory

Implement backend selection.

Expected behavior:

APP_ENV=development:
    LocalSubprocessBackend may be selected explicitly.

APP_ENV=production:
    ContainerBackend / RunnerClient required.

Unknown APP_ENV:
    Fail closed.

Missing production runner configuration:
    Fail closed.

Runner unavailable:
    Return a controlled execution error.

Never fall back to host execution.

## 4.6 Architecture deliverables

Create:

Docs/security/sandbox/03-target-architecture.md

Include:

- Architecture diagram.
- Component responsibilities.
- Data flow.
- Trust boundaries.
- Execution lifecycle.
- Workspace lifecycle.
- Backend selection.
- Authentication.
- Failure handling.
- Deployment architecture.
- Security boundaries.

Create:

Docs/security/sandbox/diagrams/

Include:

- architecture.mmd
- execution-sequence.mmd
- workspace-lifecycle.mmd
- dependency-installation-flow.mmd
- security-boundary.mmd

Use Mermaid diagrams.

Keep diagrams synchronized with the actual implementation.

---

# 5. PHASE 4 — IMPLEMENT THE RUNNER SERVICE

This is a critical infrastructure component.

Our existing API is deployed on Azure App Service.

Do not assume that Azure App Service can run arbitrary sibling Docker containers.

We need a dedicated Linux runner host.

## 5.1 Runner Service responsibilities

The runner service should handle:

- Sandbox creation.
- Workspace management.
- Container creation.
- Command execution.
- Resource enforcement.
- Network policies.
- File operations.
- Diff generation.
- Container termination.
- Cleanup.
- Resource monitoring.

The runner should be independent of the AI orchestration logic.

It must not require access to LLM API keys.

## 5.2 Runner API

Create a narrow authenticated API.

Suggested operations:

POST /internal/v1/workspaces

Create a workspace and sandbox.

POST /internal/v1/workspaces/{task_id}/exec

Execute an approved command.

GET /internal/v1/workspaces/{task_id}/files

Read a file.

PUT /internal/v1/workspaces/{task_id}/files

Write a file.

GET /internal/v1/workspaces/{task_id}/diff

Get Git diff.

GET /internal/v1/workspaces/{task_id}/status

Get sandbox status.

DELETE /internal/v1/workspaces/{task_id}

Destroy the sandbox and workspace resources according to retention policy.

Adapt exact paths to existing API conventions.

## 5.3 Authentication and authorization

Implement strong runner authentication.

Requirements:

- Runner is not publicly accessible.
- Private network access where feasible.
- Service-to-service authentication.
- TLS.
- Short-lived credentials or signed requests.
- Replay protection where applicable.
- Task ownership validation.
- User authorization.
- Request validation.
- Rate limits.
- Audit logs.

Do not trust task_id supplied by the frontend.

The API server must verify ownership before requesting runner operations.

Do not expose:

- Docker socket.
- Arbitrary Docker API.
- Unrestricted host filesystem access.
- Arbitrary host command execution.

The runner must independently validate all requests.

## 5.4 Runner security

Treat API-server requests as untrusted at the runner boundary.

Enforce:

- Command allowlists.
- Argument validation.
- Workspace containment.
- Maximum request sizes.
- Execution timeout.
- Resource limits.
- Container lifecycle restrictions.
- Output caps.
- Authentication.
- Authorization.

The runner must not accept arbitrary image names, mount paths, Docker flags or runtime options from the API client.

Only server-controlled configuration may define those values.

## 5.5 Runner deliverable

Create:

Docs/security/sandbox/04-runner-service-design.md

Document:

- API contracts.
- Request schemas.
- Response schemas.
- Authentication.
- Authorization.
- Error handling.
- Lifecycle.
- Security controls.
- Deployment requirements.

---

# 6. PHASE 5 — IMPLEMENT DOCKER + GV​​ISOR ISOLATION

This is the most important implementation phase.

Use Docker with gVisor for production sandbox execution.

## 6.1 Container configuration

Initial proposed limits:

CPU: 2 vCPU

Memory: 4 GB

PID limit: 512

Workspace disk: 500 MB

Temporary storage: 512 MB

Individual file size: 5 MB

Output limit: 100 KB

Command timeout: configurable.

These values are starting defaults. Make them configurable through validated server-side settings.

Do not allow normal users to override security-critical limits.

## 6.2 Required security settings

Implement the equivalent of:

--network=none

--pids-limit=512

--memory=4g

--cpus=2

--read-only

--tmpfs /tmp

--cap-drop=ALL

--security-opt=no-new-privileges

--user=10001:10001

--runtime=runsc

Use:

- Non-root execution.
- Read-only root filesystem.
- Restricted writable mounts.
- Secure temporary storage.
- Default-deny networking.
- Runtime-enforced resource limits.
- Appropriate seccomp configuration.
- No privileged containers.
- No host PID namespace.
- No host network.
- No Docker socket mount.
- No unnecessary Linux capabilities.

Do not disable seccomp without a documented and justified compatibility requirement.

Do not use --privileged.

## 6.3 Workspace mounting

Each task must have its own workspace.

Example:

Host:

/sandbox/workspaces/task-123

Container:

/workspace

Mount only the assigned task workspace.

Ensure:

- No cross-task workspace access.
- No host secrets.
- No application source access.
- No unrelated host mounts.
- Correct non-root ownership.
- Controlled writable directories.
- No symlink-based escape.
- Disk quota enforcement.

Remember that a read-only container root does not automatically impose a quota on a writable host bind mount.

Use filesystem quotas or a suitable isolated storage mechanism.

## 6.4 Image management

Create approved language images.

Examples:

- Python.
- Node.js.
- Python + Node.js if genuinely required.

Use minimal base images.

Pin exact versions and verified image digests.

Example:

FROM python:3.12-slim@sha256:<verified-digest>

Never invent image digests.

Never use unverified floating tags in production.

Implement:

- Image allowlist.
- Digest verification.
- Image scanning.
- Image update policy.
- Image caching.
- Image pull failure handling.

Repository-controlled files must never decide which privileged image or runtime the host executes.

## 6.5 Container lifecycle

Implement:

CREATED
   |
   v
INITIALIZING
   |
   v
READY
   |
   v
INSTALLING_DEPENDENCIES
   |
   v
EXECUTING
   |
   v
COLLECTING_RESULTS
   |
   v
COMPLETED
   |
   v
DESTROYED

Also support:

FAILED

TIMED_OUT

CANCELLED

EXPIRED

Every state transition should be validated.

Implement:

- Maximum lifetime.
- Idle timeout.
- Explicit cancellation.
- Cleanup after failures.
- Cleanup after API disconnects where appropriate.
- Periodic orphan-container cleanup.
- Restart recovery.
- Resource usage tracking.

Do not depend solely on the API process remaining alive to clean up containers.

## 6.6 Deliverable

Create:

Docs/security/sandbox/05-container-isolation.md

Include all Docker configurations, gVisor setup, resource limits, image policies, mount policies, lifecycle and failure handling.

---

# 7. PHASE 6 — TWO-PHASE DEPENDENCY INSTALLATION

We need separate dependency installation from untrusted test execution.

Do not disable network permanently without considering dependency installation.

## 7.1 Phase A: Dependency installation

Flow:

Repository
   |
   v
Manifest Detection
   |
   v
Python / Node Dependency Detection
   |
   v
Restricted Installation Environment
   |
   v
Dependency Installation
   |
   v
Dependency Artifacts

Support relevant manifests, including:

Python:
- requirements.txt
- pyproject.toml
- poetry.lock
- Pipfile.lock

Node.js:
- package.json
- package-lock.json
- npm lockfiles.

Only support the package managers that the existing project actually needs.

During installation:

- Run inside a sandbox.
- Use non-root.
- Do not expose application secrets.
- Restrict outbound networking.
- Prefer approved package registries.
- Apply download-size limits.
- Apply timeouts.
- Record installation logs.
- Prevent access to host filesystem.
- Protect against malicious install scripts.

Important:

npm lifecycle scripts and Python build backends can execute arbitrary code.

Dependency installation must be treated as untrusted execution.

Never install dependencies on the API host.

## 7.2 Phase B: Offline testing

After dependency installation:

- Ensure the execution environment has all required dependencies.
- Start the test phase without external network access.
- Use --network=none.
- Execute pytest or npm test.
- Execute approved static analysis tools.
- Capture output.
- Collect exit codes.
- Collect execution metrics.
- Preserve relevant logs.

Do not assume Docker networking can be changed in-place between phases.

Design the transition using separate containers or another explicitly verified isolation strategy.

The dependency artifacts shared between phases must be carefully controlled.

Do not introduce shared writable directories between unrelated tasks.

## 7.3 Deliverable

Create:

Docs/security/sandbox/06-dependency-installation.md

Document:

- Manifest detection.
- Package manager selection.
- Installation environment.
- Network policy.
- Dependency caching.
- Artifact transfer.
- Offline execution.
- Failure cases.
- Security risks.

---

# 8. PHASE 7 — INTEGRATE WITH EXISTING AGENTS

This project has multiple AI-assisted workflows.

Do not make the sandbox an isolated feature that existing agents cannot use.

Find every agent that invokes CommandRunner or performs repository execution.

Expected integration targets may include:

- Code Review Agent.
- Bug Detection Agent.
- Test Generation Agent.
- AI Orchestrator.
- Repository Analysis.
- Automated Code Modification.
- Validation workflows.

Actual component names must be discovered from the repository.

## 8.1 Integration requirements

All repository-controlled code execution must go through the new execution abstraction.

Example:

AI Agent
   |
   v
CommandRunner
   |
   v
SandboxBackend
   |
   v
Runner Service
   |
   v
Container

Agents should not need to know whether the implementation uses Docker or gVisor.

They should receive a structured result:

- Exit code.
- Standard output.
- Standard error.
- Timeout status.
- Execution duration.
- Resource usage.
- Sandbox status.

Preserve existing agent contracts where possible.

## 8.2 Git operations

Review which Git operations need to execute on the API host and which need to execute inside the runner.

Do not unnecessarily move trusted repository-management operations into the sandbox.

However, any Git operation that processes untrusted repository-controlled content must be reviewed for security.

Treat Git configuration, hooks, filters and submodules as potential execution or network attack surfaces.

Do not allow repository-controlled Git hooks to execute on the API host.

Use controlled Git configuration.

## 8.3 Integration deliverable

Create:

Docs/security/sandbox/07-agent-integration.md

Include:

- Existing agent execution paths.
- New execution flow.
- Files changed.
- Interface changes.
- Compatibility.
- Error propagation.
- Task cancellation.
- Integration tests.

---

# 9. PHASE 8 — SECURITY HARDENING

Preserve all existing application-level protections.

Sandboxing is an additional layer, not a replacement.

## 9.1 Retain existing protections

Keep:

- WorkspacePathGuard.
- Command allowlist.
- Argument validation.
- Environment sanitization.
- Secret redaction.
- Output caps.
- Timeout handling.
- WorkspaceResourceMonitor.
- File modification limits.

Extend them where required.

## 9.2 Additional controls

Implement or document:

- Container-level filesystem isolation.
- Network isolation.
- CPU restrictions.
- Memory restrictions.
- PID restrictions.
- Disk quotas.
- File descriptor limits.
- Process termination.
- Task ownership.
- Runner authentication.
- Container image verification.
- Audit logging.
- Concurrency limits.
- Container cleanup.
- Secret isolation.
- Secure error handling.

## 9.3 Secret protection

The runner and sandbox must never receive:

- Gemini API keys.
- Groq API keys.
- Database passwords.
- JWT signing secrets.
- Azure credentials.
- GitHub personal access tokens.
- Application `.env` contents.

If private repository access is required, use a separate trusted cloning operation with narrowly scoped credentials.

Never expose cloning credentials to repository tests or installation scripts.

## 9.4 Security deliverable

Create:

Docs/security/sandbox/08-security-hardening.md

---

# 10. PHASE 9 — TESTING AND SECURITY VALIDATION

Do not consider implementation complete without testing.

Create automated unit, integration and security tests.

## 10.1 Unit tests

Test:

- SandboxFactory.
- Backend selection.
- Environment validation.
- Production fail-closed behavior.
- Local backend restrictions.
- Command validation.
- Workspace path validation.
- Request validation.
- Lifecycle transitions.
- Error mapping.
- Resource configuration.

## 10.2 Integration tests

Test:

- Runner authentication.
- Workspace creation.
- Container creation.
- File writing.
- File reading.
- Git diff.
- Command execution.
- Timeout handling.
- Container termination.
- Cleanup.
- Runner failure.
- API-runner communication.

## 10.3 Security tests

Create controlled malicious test repositories.

Test the following:

### Test 1: Host secret access

Try reading a known test secret placed outside the workspace.

Expected:

The secret must not be accessible.

### Test 2: Cross-task access

Task A attempts to read Task B's workspace.

Expected:

Access denied.

### Test 3: Network exfiltration

Try opening an external TCP connection during the offline execution phase.

Expected:

Connection blocked.

### Test 4: CPU exhaustion

Run an infinite CPU loop.

Expected:

CPU usage remains within configured limits.

### Test 5: Memory exhaustion

Attempt to allocate excessive memory.

Expected:

Container memory limit enforced.

### Test 6: Process exhaustion

Attempt to create excessive processes.

Expected:

PID limit enforced.

### Test 7: Filesystem writes

Try writing to:

/workspace/test.txt

Expected:

Allowed within quota.

Try writing to:

/usr/test.txt

Expected:

Denied.

### Test 8: Docker socket access

Try accessing:

/var/run/docker.sock

Expected:

Not mounted and inaccessible.

### Test 9: Symbolic link escape

Create a symlink pointing outside the workspace and attempt to access it through file operations.

Expected:

Workspace boundary preserved.

### Test 10: Malicious repository hooks

Test malicious:

- conftest.py
- setup.py
- npm lifecycle scripts
- build backend scripts
- Git hooks.

Expected:

All untrusted execution occurs inside the sandbox, never on the API host.

### Test 11: Timeout

Start a long-running process and terminate it.

Expected:

The container and its child processes are stopped.

### Test 12: Runner outage

Make the runner unavailable.

Expected:

Production execution fails safely.

No local subprocess fallback.

## 10.4 Test reporting

For each test, record:

- Test ID.
- Objective.
- Attack scenario.
- Execution procedure.
- Expected result.
- Actual result.
- Pass/fail.
- Evidence.
- Related source files.

Do not mark an infrastructure-dependent security test as passed if the runner host or gVisor runtime is unavailable.

Use:

PASS
FAIL
NOT RUN
BLOCKED

## 10.5 Testing deliverable

Create:

Docs/security/sandbox/09-security-testing.md

Also create an automated security test suite in the appropriate existing test directory.

---

# 11. PHASE 10 — AZURE DEPLOYMENT ARCHITECTURE

Our current architecture uses:

- Frontend: Vercel.
- API backend: Azure App Service.
- Database: Supabase.
- Redis: Upstash.

We want to retain the existing deployment architecture wherever possible.

## 11.1 Proposed architecture

VERCEL
  |
  v
AZURE APP SERVICE
  |
  | Authenticated internal communication
  |
  v
DEDICATED LINUX RUNNER VM
  |
  v
DOCKER ENGINE
  |
  v
GVISOR RUNTIME
  |
  v
ISOLATED TASK CONTAINERS

The existing App Service must not execute repository tests locally.

## 11.2 Hosting research

Evaluate:

1. Dedicated Azure Linux VM.
2. Azure Container Apps dynamic sessions.
3. E2B managed cloud sandboxes.

For each, compare:

- Infrastructure requirements.
- Isolation.
- Operational complexity.
- Security.
- Pricing.
- Networking.
- Scaling.
- Compatibility with Docker/gVisor.
- Deployment complexity.
- Limitations.

Do not assume that a service supports gVisor or arbitrary Docker runtime configuration without verifying it.

## 11.3 Budget awareness

We have previously used Azure for Students credits.

Keep infrastructure cost under control.

Research:

- VM pricing.
- Disk pricing.
- Network pricing.
- Idle costs.
- Container overhead.
- Concurrent task capacity.

Recommend a minimal practical configuration.

Implement:

- Maximum concurrency.
- Idle shutdown where practical.
- Container cleanup.
- Disk cleanup.
- Resource monitoring.
- Cost alerts.

Do not deploy expensive infrastructure automatically.

Do not create cloud resources or spend credits without explicit approval.

## 11.4 Deployment deliverable

Create:

Docs/security/sandbox/10-azure-deployment.md

Include:

- Architecture.
- Infrastructure requirements.
- Linux setup.
- Docker installation.
- gVisor installation.
- Runner deployment.
- Network configuration.
- TLS and authentication.
- Environment variables.
- Monitoring.
- Scaling.
- Cost considerations.
- Rollback procedure.

Also create deployment scripts or configuration files where appropriate.

---

# 12. PHASE 11 — CONFIGURATION AND ENVIRONMENT VARIABLES

Create a central validated configuration.

Suggested settings:

APP_ENV

SANDBOX_BACKEND

RUNNER_BASE_URL

RUNNER_AUTH_SECRET or the selected secure credential configuration

RUNNER_REQUEST_TIMEOUT

SANDBOX_CPU_LIMIT

SANDBOX_MEMORY_LIMIT

SANDBOX_PID_LIMIT

SANDBOX_DISK_LIMIT_MB

SANDBOX_FILE_LIMIT_MB

SANDBOX_OUTPUT_LIMIT_BYTES

SANDBOX_DEFAULT_TIMEOUT

SANDBOX_MAX_LIFETIME

SANDBOX_IDLE_TIMEOUT

SANDBOX_MAX_CONCURRENT_TASKS

SANDBOX_RUNTIME

SANDBOX_PYTHON_IMAGE

SANDBOX_NODE_IMAGE

Use actual project configuration conventions.

Requirements:

- Validate settings at startup.
- Reject invalid configurations.
- Do not use insecure production defaults.
- Never expose secrets in API responses.
- Never log secret values.
- Update .env.example.
- Document each setting.
- Ensure development and production configurations are separate.

Create:

Docs/security/sandbox/11-configuration-reference.md

---

# 13. PHASE 12 — DOCUMENTATION SYSTEM

Documentation is one of the primary deliverables.

I want enough documentation that another developer can understand the entire architecture and continue development without asking me how it works.

Create the following structure, adapting it to the existing Docs folder:

Docs/
└── security/
    └── sandbox/
        │
        ├── README.md
        │
        ├── 01-existing-architecture-audit.md
        ├── 02-technology-research.md
        ├── 03-target-architecture.md
        ├── 04-runner-service-design.md
        ├── 05-container-isolation.md
        ├── 06-dependency-installation.md
        ├── 07-agent-integration.md
        ├── 08-security-hardening.md
        ├── 09-security-testing.md
        ├── 10-azure-deployment.md
        ├── 11-configuration-reference.md
        ├── 12-implementation-guide.md
        ├── 13-operations-and-troubleshooting.md
        ├── 14-risk-register.md
        ├── 15-implementation-status.md
        │
        └── diagrams/
            ├── architecture.mmd
            ├── execution-sequence.mmd
            ├── workspace-lifecycle.mmd
            ├── dependency-installation-flow.mmd
            ├── security-boundary.mmd
            └── deployment-architecture.mmd

## 13.1 README.md

This should be the starting point.

Explain:

- What sandbox execution means.
- Why we need it.
- Existing security problems.
- New architecture.
- How components communicate.
- How to navigate the documentation.
- Current implementation status.

## 13.2 Technology research

Explain:

- Why Docker.
- Why gVisor.
- Why not ordinary subprocess.
- Why not Docker alone.
- When Firecracker is useful.
- E2B alternatives.
- Open-source project comparisons.
- Licence considerations.
- Research sources.

Include authoritative source links.

Clearly distinguish verified facts from engineering assumptions.

## 13.3 Architecture documentation

Include:

- Component diagrams.
- Class diagrams.
- Sequence diagrams.
- Data flow.
- Trust boundaries.
- API communication.
- Error handling.
- Lifecycle.
- Network boundaries.

## 13.4 Implementation documentation

For every new module explain:

1. Purpose.
2. Responsibilities.
3. Important classes.
4. Important methods.
5. Inputs.
6. Outputs.
7. Dependencies.
8. Error handling.
9. Security considerations.
10. Integration with other modules.

## 13.5 Operations documentation

Explain:

- How to start the runner.
- How to check Docker.
- How to check gVisor.
- How to create a sandbox.
- How to inspect logs.
- How to diagnose failed commands.
- How to terminate containers.
- How to clean up orphan containers.
- How to rotate credentials.
- How to troubleshoot network restrictions.
- How to investigate resource exhaustion.

## 13.6 Risk register

Create a table with:

| ID | Risk | Severity | Likelihood | Mitigation | Status |
|---|---|---|---|---|---|

Include remaining risks and unresolved infrastructure dependencies.

## 13.7 Implementation status

Maintain a checklist of:

- Completed tasks.
- Partially implemented tasks.
- Pending tasks.
- Blocked tasks.
- Tests executed.
- Security tests passed.
- Security tests failed.
- Infrastructure dependencies.
- Remaining production blockers.

Update this document whenever implementation status changes.

---

# 14. IMPLEMENTATION ORDER

Follow this exact dependency-aware order.

WEEK / STAGE 1:
- Repository audit.
- Execution entry-point inventory.
- Security gap analysis.
- Technology research.
- Architecture documentation.

STAGE 2:
- SandboxBackend interface.
- SandboxFactory.
- LocalSubprocessBackend.
- Production fail-closed configuration.
- Unit tests.

STAGE 3:
- Runner Service.
- Authentication.
- Authorization.
- API contracts.
- RunnerClient.

STAGE 4:
- Docker ContainerBackend.
- Container lifecycle.
- Workspace mounting.
- Resource enforcement.
- gVisor integration.

STAGE 5:
- Dependency installation.
- Restricted network phase.
- Offline execution phase.
- Python and Node.js support.

STAGE 6:
- Existing agent integration.
- CommandRunner migration.
- Git integration review.
- Workspace integration.

STAGE 7:
- Security testing.
- Failure handling.
- Cleanup.
- Performance testing.

STAGE 8:
- Azure deployment documentation.
- Infrastructure setup.
- Production verification.
- Final documentation.

Do not move to production deployment before the security tests and infrastructure prerequisites are satisfied.

---

# 15. ACCEPTANCE CRITERIA

The task is complete only when the following criteria are addressed.

## Architecture

[ ] SandboxBackend abstraction implemented.

[ ] SandboxFactory implemented.

[ ] LocalSubprocessBackend restricted to explicit development mode.

[ ] Production execution fails closed.

[ ] ContainerBackend implemented.

[ ] RunnerClient implemented.

[ ] Separate Runner Service implemented.

## Security

[ ] No untrusted repository execution on API host in production.

[ ] Container isolation implemented.

[ ] gVisor integration implemented and verified on supported Linux infrastructure.

[ ] Network restrictions implemented.

[ ] Filesystem isolation implemented.

[ ] CPU restrictions implemented.

[ ] Memory restrictions implemented.

[ ] PID restrictions implemented.

[ ] Disk restrictions implemented.

[ ] Non-root execution.

[ ] No Docker socket exposed to repository code.

[ ] No application secrets exposed.

[ ] No cross-task workspace access.

[ ] Timeout and process termination verified.

[ ] Automatic cleanup implemented.

## Integration

[ ] Existing agents use the new execution interface.

[ ] Existing workspace functionality preserved.

[ ] Git diff functionality preserved.

[ ] Python execution works.

[ ] Node.js execution works where supported.

[ ] Dependency installation works in the restricted installation phase.

[ ] Tests execute offline.

[ ] Structured execution results returned.

## Testing

[ ] Unit tests.

[ ] Integration tests.

[ ] Security tests.

[ ] Failure tests.

[ ] Resource limit tests.

[ ] Production configuration tests.

[ ] Existing regression tests.

## Documentation

[ ] Existing architecture audit.

[ ] Technology research.

[ ] Target architecture.

[ ] Runner API documentation.

[ ] Docker/gVisor configuration.

[ ] Dependency installation design.

[ ] Agent integration documentation.

[ ] Security testing documentation.

[ ] Deployment documentation.

[ ] Configuration reference.

[ ] Troubleshooting guide.

[ ] Risk register.

[ ] Implementation status.

---

# 16. IMPORTANT ARCHITECTURAL DECISIONS

Use these decisions as the default unless actual codebase constraints require a documented alternative.

1. Docker + gVisor is the preferred production sandbox architecture.
2. A separate Linux runner host is the preferred deployment architecture.
3. Azure App Service remains responsible for API and AI orchestration.
4. The runner is responsible for untrusted repository execution.
5. Local subprocess is development-only.
6. Production execution must fail closed.
7. Dependency installation occurs inside an isolated environment.
8. Test execution happens without external network access.
9. Existing application-level security controls must be retained.
10. Container limits must be enforced by the runtime/operating system.
11. All runner operations must be authenticated and authorized.
12. Docker and host management interfaces must never be exposed to untrusted workloads.
13. Future Firecracker support should be possible through the abstraction without implementing it now.
14. MCP integration is optional and must not bypass runner authorization or security boundaries.

If you change any of these decisions, create an Architecture Decision Record explaining:

- Original decision.
- New decision.
- Reason.
- Advantages.
- Disadvantages.
- Security impact.
- Cost impact.
- Migration impact.

---

# 17. FINAL EXECUTION INSTRUCTIONS

Start with repository exploration and audit.

Do not immediately start creating Docker files.

First understand the existing code.

Then create the audit and research documents.

After that, implement the architecture incrementally.

For every implementation stage:

1. Explain what you found.
2. Explain what needs changing.
3. Identify exact files.
4. Explain the implementation.
5. Implement the changes.
6. Run relevant tests.
7. Record results.
8. Update documentation.
9. Update implementation status.

Keep changes minimal, modular, testable and maintainable.

Do not rewrite unrelated parts of the platform.

Do not delete existing functionality without proving that it is unnecessary.

If you discover additional vulnerabilities during implementation, document and address them when relevant to sandbox security.

If you encounter infrastructure limitations:

- Continue with safe code-level implementation.
- Document the limitation.
- Provide exact infrastructure setup instructions.
- Mark runtime verification as BLOCKED.
- Never pretend the security feature is production-ready.

## FINAL REPORT REQUIRED

At the end, provide a detailed report containing:

### A. Existing architecture
What was present before implementation.

### B. Security problems
What vulnerabilities were identified.

### C. Research
What technologies were evaluated and why the final choices were made.

### D. Implementation
Every new file and every modified file.

### E. Architecture
How the new execution flow works.

### F. Security
Which security boundaries are now enforced and how.

### G. Testing
Actual commands executed and test results.

### H. Documentation
All documentation files created or updated.

### I. Deployment
What is ready for Azure and what still requires infrastructure configuration.

### J. Remaining work
Incomplete features, blockers, known risks and future improvements.

### K. Production readiness

Give an honest status:

- NOT READY
- DEVELOPMENT READY
- STAGING READY
- PRODUCTION READY

Only select PRODUCTION READY if the actual infrastructure, runtime, isolation controls and required security tests have been verified.

---

# FINAL PRINCIPLE

We are building an AI-powered software development platform that executes code from external GitHub repositories.

Every external repository must be considered untrusted.

The AI agent may inspect, modify, install dependencies and execute tests, but it must never gain access to the API server's secrets, filesystem, other users' workspaces or unrestricted network.

**Security must be enforced at the infrastructure boundary, not merely through prompts, Python validation or command allowlists.**

Build this as a reusable, modular and production-oriented sandbox execution system that can support future AI coding agents, autonomous debugging, test generation, code modification and repository automation.

Prioritize correctness, isolation, maintainability, observability and complete technical documentation.