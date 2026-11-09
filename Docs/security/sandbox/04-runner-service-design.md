# Runner Service Design & API Specification
**Target:** AI-Powered Software Development Platform — Secure Sandbox Execution Architecture (Issue #200 / F20)  
**Date:** November 2026  
**Status:** Approved Design  

---

## 1. Executive Purpose

The **Runner Service** is a dedicated internal execution microservice designed to decouple untrusted code execution from the main API control plane. The API server (running on Azure App Service) handles user authentication, LLM prompt engineering, and database transactions, while the Runner Service (running on a dedicated Linux host) executes commands, tests, and builds inside container sandboxes.

The Runner Service:
- Has zero access to LLM API keys (`GEMINI_API_KEY`, `GROQ_API_KEY`), Supabase DB passwords, or user credentials.
- Exposes a narrow, strictly validated REST interface protected by constant-time client bearer token authentication over TLS.
- Independently validates command executables, argument tokens, and workspace paths, enforcing security policies even if an API server request was compromised.

---

## 2. API Endpoints & Request / Response Contracts

Base Path: `/internal/v1`

### 2.1 Provision Workspace
- **Route:** `POST /internal/v1/workspaces`
- **Description:** Prepares the host directory and initializes the container workspace.
- **Request Body:**
  ```json
  {
    "task_id": "task-7890",
    "base_repo_path": "/path/to/seed/repo"
  }
  ```
- **Response (`200 OK`):**
  ```json
  {
    "success": true,
    "task_id": "task-7890",
    "workspace_path": "/sandbox/workspaces/task-7890",
    "backend": "container"
  }
  ```

### 2.2 Execute Command
- **Route:** `POST /internal/v1/workspaces/{task_id}/exec`
- **Description:** Runs an allowlisted command inside the sandbox container.
- **Request Body:**
  ```json
  {
    "command": "pytest",
    "arguments": ["tests/test_feature.py", "-v"],
    "cwd": null,
    "timeout_seconds": 30,
    "custom_env": {
      "NODE_ENV": "test"
    },
    "network_enabled": false
  }
  ```
- **Response (`200 OK`):**
  ```json
  {
    "success": true,
    "command": "pytest",
    "exit_code": 0,
    "stdout": "================ 1 passed in 0.12s ================",
    "stderr": "",
    "duration_ms": 420.5,
    "timed_out": false,
    "error": null,
    "sandbox_status": "CONTAINER_GVISOR",
    "resource_metrics": {
      "duration_ms": 420.5,
      "timed_out": false,
      "image": "python:3.12-slim",
      "network_isolated": true,
      "runtime": "runsc"
    }
  }
  ```

### 2.3 Read File
- **Route:** `GET /internal/v1/workspaces/{task_id}/files?path={relative_path}`
- **Description:** Reads file contents from within the task's isolated workspace.
- **Response (`200 OK`):**
  ```json
  {
    "success": true,
    "path": "src/app.py",
    "content": "def main(): pass\n"
  }
  ```

### 2.4 Write File
- **Route:** `PUT /internal/v1/workspaces/{task_id}/files`
- **Description:** Confined file write subject to file size and workspace disk quotas.
- **Request Body:**
  ```json
  {
    "path": "src/app.py",
    "content": "def main(): print('updated')\n"
  }
  ```
- **Response (`200 OK`):**
  ```json
  {
    "success": true,
    "path": "src/app.py",
    "bytes_written": 29
  }
  ```

### 2.5 Extract Git Diff
- **Route:** `GET /internal/v1/workspaces/{task_id}/diff`
- **Description:** Extracts unified git diff of all modifications made inside the task workspace.
- **Response (`200 OK`):**
  ```json
  {
    "success": true,
    "task_id": "task-7890",
    "diff": "diff --git a/src/app.py b/src/app.py\n..."
  }
  ```

### 2.6 Query Status & Telemetry
- **Route:** `GET /internal/v1/workspaces/{task_id}/status`
- **Description:** Retrieves container execution status, active containers, and gVisor verification.
- **Response (`200 OK`):**
  ```json
  {
    "success": true,
    "task_id": "task-7890",
    "backend": "container",
    "status": "READY",
    "gvisor_verified": true,
    "details": {
      "disk_bytes": 1048576,
      "modified_files": 2
    }
  }
  ```

### 2.7 Destroy Workspace & Sandboxes
- **Route:** `DELETE /internal/v1/workspaces/{task_id}`
- **Description:** Forcefully terminates all active containers (`docker rm -f`) and purges directory.
- **Response (`200 OK`):**
  ```json
  {
    "success": true,
    "task_id": "task-7890",
    "status": "DESTROYED"
  }
  ```

---

## 3. Client Bearer Authentication & TLS Transport Security

1. **Authentication Token (`RUNNER_AUTH_SECRET`):**
   - Every request from `RunnerClient` to the Runner Service must provide an authentication header:
     - `X-Runner-Token: <RUNNER_AUTH_SECRET>`
     - OR `Authorization: Bearer <RUNNER_AUTH_SECRET>`
   - The token authenticates the client caller and is verified using Python `secrets.compare_digest` to prevent timing attacks.
   - Any missing or incorrect token immediately terminates with `HTTP 401 Unauthorized`.
   - Missing secret configuration causes the runner service to fail closed (`HTTP 500`).
2. **Mandatory Authenticated TLS Encryption:**
   - Client bearer tokens authenticate the caller but do not encrypt traffic. Therefore, **every network hop carrying the token must use authenticated TLS (HTTPS)** to protect against eavesdropping and token interception.
   - In production, TLS is terminated via a reverse proxy (e.g. Nginx or Caddy on port 8443) or an Application Gateway in front of Uvicorn.
3. **Private Network Containment:**
   - The Runner Service is deployed inside a private Azure Virtual Network subnet.
   - Ingress is restricted via Azure Network Security Group (NSG) rules allowing traffic strictly from the App Service Subnet over TLS.
4. **No Docker Socket Exposure:**
   - The Docker socket `/var/run/docker.sock` is accessible only to the Runner Service daemon, never exposed over the network, and never bind-mounted into untrusted task containers.
