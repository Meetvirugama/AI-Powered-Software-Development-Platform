# Sandbox Configuration Reference
**Target:** AI-Powered Software Development Platform — Secure Sandbox Execution Architecture (Issue #200 / F20)  
**Date:** November 2026  
**Status:** Approved Reference  

---

## 1. Environment Variables Overview

All sandbox execution settings are centralized in `app.core.config.Settings`.

| Variable | Type | Default | Production Default / Requirement | Description |
|---|---|---|---|---|
| `APP_ENV` | `str` | `"development"` | `"production"` | Runtime environment (`development`, `staging`, `production`). |
| `SANDBOX_BACKEND` | `str` | `"local"` | `"runner"` or `"container"` | Execution backend. **`local` is strictly forbidden in production.** |
| `RUNNER_BASE_URL` | `str` | `None` | `https://runner.internal:8080` | Base URL of internal Runner Service when `SANDBOX_BACKEND=runner`. |
| `RUNNER_AUTH_SECRET` | `str` | `None` | *Mandatory* (>= 16 chars) | Shared bearer secret for authenticating API-to-Runner requests. |
| `RUNNER_REQUEST_TIMEOUT` | `float` | `60.0` | `60.0` | HTTP client timeout in seconds for runner API calls. |
| `SANDBOX_CPU_LIMIT` | `float` | `2.0` | `2.0` | Hard CPU limit allocated per container (Docker `--cpus`). |
| `SANDBOX_MEMORY_LIMIT` | `str` | `"4g"` | `"4g"` | Hard RAM limit allocated per container (Docker `--memory`). |
| `SANDBOX_PID_LIMIT` | `int` | `512` | `512` | Maximum process/thread count per container (`--pids-limit`). |
| `SANDBOX_DISK_LIMIT_MB` | `int` | `500` | `500` | Workspace storage quota ceiling in megabytes. |
| `SANDBOX_FILE_LIMIT_MB` | `int` | `5` | `5` | Maximum permissible size for a single file in megabytes. |
| `SANDBOX_OUTPUT_LIMIT_BYTES` | `int` | `102400` | `102400` (100 KB) | Maximum captured stdout and stderr bytes before truncation. |
| `SANDBOX_DEFAULT_TIMEOUT` | `int` | `30` | `30` | Default timeout budget in seconds for untrusted command execution. |
| `SANDBOX_MAX_LIFETIME` | `int` | `3600` | `3600` (1 hr) | Maximum permissible active sandbox lifetime before automated cleanup. |
| `SANDBOX_IDLE_TIMEOUT` | `int` | `600` | `600` (10 min) | Inactivity timeout threshold for unaccessed workspaces. |
| `SANDBOX_MAX_CONCURRENT_TASKS` | `int` | `5` | `5` | Maximum active tasks allowed on a single runner host. |
| `SANDBOX_RUNTIME` | `str` | `"runc"` | `"runsc"` (gVisor) | Container OCI runtime engine. |
| `SANDBOX_USE_GVISOR` | `bool` | `True` | `True` | Whether to inspect and engage gVisor `runsc` if verified. |
| `SANDBOX_PYTHON_IMAGE` | `str` | `"python:3.12-slim"` | `"python:3.12-slim"` | Pinned container image for Python test execution. |
| `SANDBOX_NODE_IMAGE` | `str` | `"node:20-slim"` | `"node:20-slim"` | Pinned container image for Node.js / JavaScript execution. |

---

## 2. Production Fail-Closed Validation Rules

The `Settings.validate_production_security` validator enforces hard boundaries at application startup:
1. **Forbidden Local Execution:** If `APP_ENV=production` and `SANDBOX_BACKEND` is set to `"local"`, `"subprocess"`, or `"localsubprocess"`, startup raises `ValueError`:
   ```
   Production configuration error: LocalSubprocessBackend is strictly forbidden in production.
   SANDBOX_BACKEND must be 'container' or 'runner'.
   ```
2. **Mandatory Runner Credentials:** If `SANDBOX_BACKEND=runner` in production:
   - `RUNNER_BASE_URL` cannot be empty.
   - `RUNNER_AUTH_SECRET` must be configured with at least 16 characters.
3. **No Automatic Insecure Fallback:** If the remote runner service cannot be reached during production execution, `RunnerClient` raises `RunnerUnavailableError`. Host subprocess execution is never used as an emergency fallback.
