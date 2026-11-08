# Operations & Troubleshooting Runbook
**Target:** AI-Powered Software Development Platform — Secure Sandbox Execution Architecture (Issue #200 / F20)  
**Date:** November 2026  
**Status:** Operations Guide  

---

## 1. Starting and Inspecting the Runner Service

### 1.1 Local Development / Staging Runner Startup
To run the internal Runner Service locally or on a test runner VM:
```bash
cd backend
export PYTHONPATH=.
export APP_ENV=development
export RUNNER_AUTH_SECRET="dev-secret-token-12345"
export SANDBOX_BACKEND=container
uvicorn runner.main:app --host 0.0.0.0 --port 8080 --reload
```

### 1.2 Verifying Service Health
```bash
curl -s http://localhost:8080/health | jq .
```
Expected output:
```json
{
  "status": "healthy",
  "service": "secure-runner-service",
  "backend": "container",
  "gvisor_verified": true,
  "environment": "development"
}
```

---

## 2. Docker & gVisor Diagnostic Checks

### 2.1 Verify Docker Daemon
```bash
docker info --format '{{.ServerVersion}}'
```

### 2.2 Verify gVisor `runsc` Installation
```bash
# Check if runsc binary is on PATH
which runsc

# Check if Docker recognizes runsc runtime
docker info --format '{{json .Runtimes}}' | grep runsc
```

### 2.3 Test Container Execution under gVisor
```bash
docker run --rm --runtime=runsc python:3.12-slim python -c "import platform; print(platform.uname())"
```
Under gVisor, `uname` displays the Linux version reported by Google's Sentry userspace kernel.

---

## 3. Orphan Container Sweeper & Resource Cleanup

If containers hang or fail to terminate normally:
```bash
# List all active sandbox containers
docker ps --filter "name=sandbox-*"

# Terminate all lingering sandbox containers
docker rm -f $(docker ps -aq --filter "name=sandbox-*")

# Remove dangling images and build cache
docker system prune -f --volumes
```

---

## 4. Troubleshooting Common Issues

### Issue 1: `RunnerUnavailableError: Runner service is unreachable`
- **Cause:** Network security group rules blocking port 8080, runner VM powered off, or uvicorn crashed.
- **Diagnostic:** Check `systemctl status runner-service` on the runner host. Test connectivity from App Service using `tcpping runner.internal:8080`.
- **Resolution:** Restart service via `sudo systemctl restart runner-service`.

### Issue 2: `RunnerAuthenticationError: Runner authentication failed (401)`
- **Cause:** Mismatched `RUNNER_AUTH_SECRET` between App Service and Runner Service.
- **Resolution:** Verify both environment configurations match. Tokens must be at least 16 characters in production.

### Issue 3: `WorkspacePolicyViolationError: Argument contains forbidden shell operator`
- **Cause:** AI agent tool passed command arguments containing unescaped semicolons (`;`), pipes (`|`), or redirects (`>`).
- **Resolution:** Shell metacharacters are strictly forbidden. Use clean argument arrays or write multi-line scripts to files before executing.

### Issue 4: `SocketError: Network is unreachable` during Tests
- **Cause:** Normal behavior during Phase B offline test execution.
- **Resolution:** Tests requiring network access must be refactored to mock network dependencies or execute dependency installation during Phase A.
