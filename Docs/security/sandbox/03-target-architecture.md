# Target Sandbox Execution Architecture Specification
**Target:** AI-Powered Software Development Platform — Secure Sandbox Execution Architecture (Issue #200 / F20)  
**Date:** November 2026  
**Status:** Approved Architecture  

---

## 1. High-Level Architecture Overview

The secure sandbox execution architecture introduces a physical and logical separation between the **API / Orchestration Tier** and the **Untrusted Execution Tier**.

```
+-----------------------------------------------------------------------------------------+
|                                    API CONTROL PLANE                                    |
|                                (Azure App Service / Host)                               |
|                                                                                         |
|   +-------------------+    +----------------------+    +----------------------------+   |
|   |  AI Orchestrator  | -> |   WorkspaceManager   | -> |   WorkspaceCommandRunner   |   |
|   +-------------------+    +----------------------+    +----------------------------+   |
|                                                                       |                 |
|                                                                       v                 |
|                                                           +---------------------+       |
|                                                           |   SandboxFactory    |       |
|                                                           +---------------------+       |
|                                                              /               \          |
|                 (APP_ENV=development)                      /                 \ (Prod)   |
|                                                          v                     v        |
|                                            +--------------------+    +---------------+  |
|                                            |   LocalSubprocess  |    | RunnerClient  |  |
|                                            |       Backend      |    +---------------+  |
|                                            +--------------------+            |          |
+------------------------------------------------------------------------------|----------+
                                                                               |
                                                        Private Network (TLS)  |
                                                        Token: RUNNER_AUTH     |
                                                                               v
+-----------------------------------------------------------------------------------------+
|                                  DEDICATED RUNNER HOST                                  |
|                                    (Linux Runner VM)                                    |
|                                                                                         |
|   +---------------------------------------------------------------------------------+   |
|   |                       Runner Service (FastAPI / Uvicorn)                        |   |
|   |   - Workspace Provisioning & Retention Policy                                   |   |
|   |   - Command Whitelisting & Argument Validation                                  |   |
|   |   - Container Lifecycle & Orphan Sweeper                                        |   |
|   +---------------------------------------------------------------------------------+   |
|                                           |                                             |
|                                           v                                             |
|   +---------------------------------------------------------------------------------+   |
|   |                                  Docker Engine                                  |   |
|   |   --memory=4g --cpus=2 --pids-limit=512 --read-only --user=10001:10001          |   |
|   +---------------------------------------------------------------------------------+   |
|                                           |                                             |
|                                           v                                             |
|   +---------------------------------------------------------------------------------+   |
|   |                             gVisor Runtime (runsc)                              |   |
|   |   Userspace Syscall Interception (Sentry + Gofer)                               |   |
|   +---------------------------------------------------------------------------------+   |
|                     |                                     |                             |
|                     v                                     v                             |
|      +------------------------------+      +------------------------------+             |
|      |  Phase A: Dependency Install |      |   Phase B: Offline Testing   |             |
|      |    Restricted Egress Network |      |       --network=none         |             |
|      |    Registry Whitelist Caching|      |      pytest / npm test       |             |
|      +------------------------------+      +------------------------------+             |
|                                                                                         |
+-----------------------------------------------------------------------------------------+
```

---

## 2. Component Responsibilities

### 2.1 SandboxBackend Interface (`backend/sandbox/backend.py`)
Abstract Base Class defining the contract for executing commands and managing workspaces:
- `create_workspace(task_id: str, base_repo_path: Path | None) -> Path`: Provisions workspace directory.
- `execute_command(task_id: str, command: str, args: list[str], cwd: Path, env: dict[str, str], timeout_seconds: int, network: bool) -> WorkspaceCommandResult`: Executes command inside the sandbox.
- `read_file(task_id: str, relative_path: str) -> str`: Confined file read.
- `write_file(task_id: str, relative_path: str, content: str) -> None`: Confined file write.
- `get_diff(task_id: str) -> str`: Computes git diff of changes.
- `destroy_workspace(task_id: str) -> None`: Cleans up container and workspace resources.
- `get_status(task_id: str) -> dict[str, Any]`: Telemetry and resource monitoring.

### 2.2 LocalSubprocessBackend (`backend/sandbox/local_backend.py`)
- Executes commands locally on the host using `WorkspaceCommandRunner`'s process group isolation.
- **Fail-Closed Rule:** Validates `settings.app_env`. If `settings.is_production`, instantiation or execution raises `SecurityConfigurationError`. Never used as an automatic fallback in production.

### 2.3 ContainerBackend (`backend/sandbox/container_backend.py`)
- Manages per-task Docker containers directly (on hosts with Docker Engine available, e.g., Runner VM or local developer container).
- Applies all kernel-level security flags: `--cpus=2`, `--memory=4g`, `--pids-limit=512`, `--read-only`, tmpfs on `/tmp`, `--cap-drop=ALL`, `--security-opt=no-new-privileges`, `--user=10001:10001`.
- Configures `--runtime=runsc` when gVisor is installed and enabled.

### 2.4 RunnerClient (`backend/sandbox/runner_client.py`)
- Implements `SandboxBackend` for the API server when calling the dedicated remote Runner Service over HTTP/TLS.
- Uses mutual bearer token authentication (`RUNNER_AUTH_SECRET`), handles retries, connection timeouts, and translates runner responses into `WorkspaceCommandResult`.

### 2.5 Runner Service (`backend/runner/main.py`)
- Dedicated FastAPI microservice running on the Linux Runner VM.
- Exposes narrow authenticated endpoints:
  - `POST /internal/v1/workspaces`: Provision workspace.
  - `POST /internal/v1/workspaces/{task_id}/exec`: Execute allowlisted command.
  - `GET /internal/v1/workspaces/{task_id}/files`: Confined file read.
  - `PUT /internal/v1/workspaces/{task_id}/files`: Confined file write.
  - `GET /internal/v1/workspaces/{task_id}/diff`: Git diff.
  - `GET /internal/v1/workspaces/{task_id}/status`: Container telemetry.
  - `DELETE /internal/v1/workspaces/{task_id}`: Teardown & cleanup.
- Validates all requests independently, enforcing command allowlists and path confinement even if called by the API.

---

## 3. Trust Boundaries & Security Boundaries

```
[ FRONTEND ] 
     | (Untrusted User Input)
     v
[ API SERVER ] (Trusted for Task Management; Contains DB / LLM Secrets)
     |
     | === SECURITY BOUNDARY 1: Mutual Auth (RUNNER_AUTH_SECRET), Private VNet ===
     | (No LLM keys, DB passwords, or cloud credentials passed)
     v
[ RUNNER SERVICE ] (Trusted Execution Manager; Zero Cloud Secrets)
     |
     | === SECURITY BOUNDARY 2: Container Namespace & cgroups ===
     |
     | === SECURITY BOUNDARY 3: gVisor Userspace Kernel (Sentry Syscall Interceptor) ===
     v
[ UNTRUSTED REPOSITORY CODE ] (Strictly Confined; Non-root; No Network in Test Phase)
```

1. **Zero Secret Leakage:** The Runner Service and Sandbox Containers never receive Gemini API keys, Groq API keys, Supabase DB credentials, JWT secrets, or Azure credentials.
2. **Strict Network Partitioning:** The test execution phase runs with `--network=none`. Outbound socket calls fail at the kernel level.
3. **Strict Filesystem Isolation:** The container root filesystem is `--read-only`. Only `/workspace` (bind-mounted task directory) and `/tmp` (tmpfs 512m) are writable.

---

## 4. Execution Lifecycle & State Machine

The container and workspace transition through explicit, validated states:

```
[NOT_CREATED]
      |
      v
  (create_workspace)
      |
      v
  [CREATED] --------> [INITIALIZING]
                             |
                             v
                          [READY]
                             |
                +------------+------------+
                |                         |
                v                         v
     [INSTALLING_DEPENDENCIES]       [EXECUTING]
         (Phase A: Network)      (Phase B: Offline)
                |                         |
                v                         v
       [DEPENDENCIES_READY]        [COLLECTING_RESULTS]
                |                         |
                +------------+------------+
                             |
                             v
                        [COMPLETED]
                             |
                             v
                        [DESTROYED]
```

Terminal states: `COMPLETED`, `FAILED`, `TIMED_OUT`, `CANCELLED`, `EXPIRED`, `DESTROYED`.
Every state transition is tracked with timestamps, exit codes, and resource metrics.
