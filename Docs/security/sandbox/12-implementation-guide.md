# Developer Implementation Guide & Module Reference
**Target:** AI-Powered Software Development Platform — Secure Sandbox Execution Architecture (Issue #200 / F20)  
**Date:** November 2026  
**Status:** Implementation Reference  

---

## 1. Subsystem File Map

```
backend/
├── runner/                              # Dedicated Internal Runner Microservice
│   ├── __init__.py                      # Package exports (app, create_runner_app)
│   ├── main.py                          # FastAPI application & authenticated endpoints
│   └── schemas.py                       # Pydantic request & response contracts
│
├── sandbox/                             # Sandbox Execution Core Subsystem
│   ├── __init__.py                      # Clean top-level exports
│   ├── backend.py                       # SandboxBackend Abstract Base Class (ABC)
│   ├── command_runner.py                # WorkspaceCommandRunner with policy validation
│   ├── constants.py                     # Security thresholds, timeouts, and allowlists
│   ├── container_backend.py             # ContainerBackend (Docker + gVisor runsc)
│   ├── diff_verifier.py                 # WorkspaceDiffVerifier & blast radius check
│   ├── exceptions.py                    # Typed exception hierarchy
│   ├── factory.py                       # SandboxFactory with fail-closed production checks
│   ├── local_backend.py                 # LocalSubprocessBackend (Development only)
│   ├── path_guard.py                    # WorkspacePathGuard (traversal & boundary defense)
│   ├── resource_monitor.py              # WorkspaceResourceMonitor (quotas & ceilings)
│   ├── runner_client.py                 # RunnerClient (HTTP client for Runner Service)
│   ├── test_runner.py                   # WorkspaceTestRunner (pytest/npm test parsing)
│   ├── tool_policy_bridge.py            # WorkspaceToolPolicyBridge
│   ├── two_phase_pipeline.py            # TwoPhaseExecutionService (Phase A/B pipeline)
│   └── workspace_manager.py             # WorkspaceManager (worktrees & lifecycle state)
│
└── tests/                               # Comprehensive Automated Test Suite
    ├── test_runner_service.py           # Integration tests for Runner Service endpoints
    ├── test_sandbox_backend.py          # Unit tests for factory & backends
    └── test_sandbox_security_scenarios.py # Automated tests for the 12 attack scenarios
```

---

## 2. Core Class Reference

### 2.1 `SandboxBackend` (`backend/sandbox/backend.py`)
- **Type:** Abstract Base Class (`abc.ABC`).
- **Methods:**
  - `create_workspace(task_id: str, base_repo_path: Path | None) -> Path`
  - `execute(task_id: str, command: str, arguments: Sequence[str] | None, cwd: Path | None, timeout_seconds: int | None, custom_env: Mapping[str, str] | None, network_enabled: bool) -> WorkspaceCommandResult`
  - `read_file(task_id: str, relative_path: str) -> str`
  - `write_file(task_id: str, relative_path: str, content: str) -> None`
  - `get_diff(task_id: str) -> str`
  - `destroy_workspace(task_id: str) -> None`
  - `get_status(task_id: str) -> dict[str, Any]`
  - `get_resource_usage(task_id: str) -> dict[str, Any]`

### 2.2 `SandboxFactory` (`backend/sandbox/factory.py`)
- **Key Method:** `get_backend(backend_type: str | None = None, **kwargs) -> SandboxBackend`
- **Security Check:** Inspects `settings.is_production` and `settings.app_env`. Rejects `local` in production with `SandboxSecurityError`. Resolves `container`, `runner`, or `local`.

### 2.3 `ContainerBackend` (`backend/sandbox/container_backend.py`)
- **Key Capability:** Builds hardened OCI container run commands with `--network=none`, `--read-only`, tmpfs on `/tmp`, `--cap-drop=ALL`, `--security-opt=no-new-privileges`, `--cpus=2`, `--memory=4g`, `--pids-limit=512`. Detects and activates gVisor `--runtime=runsc`.

### 2.4 `RunnerClient` (`backend/sandbox/runner_client.py`)
- **Key Capability:** Delegates all sandbox operations over HTTP/TLS to the dedicated Runner Service with bearer token authentication (`X-Runner-Token`). Raises `RunnerUnavailableError` on connection drops; fails closed without falling back to local subprocess.

### 2.5 `TwoPhaseExecutionService` (`backend/sandbox/two_phase_pipeline.py`)
- **Key Capability:** Inspects workspace manifests. Coordinates Phase A dependency install (with network access) followed by Phase B offline test execution (with `--network=none`).
