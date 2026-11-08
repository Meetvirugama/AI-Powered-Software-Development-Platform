# Sandbox Architecture Risk Register
**Target:** AI-Powered Software Development Platform — Secure Sandbox Execution Architecture (Issue #200 / F20)  
**Date:** November 2026  
**Status:** Active Security Risk Register  

---

## 1. Risk Register Matrix

| ID | Threat / Risk Scenario | Severity | Likelihood | Mitigation Strategy | Implementation Status |
|---|---|---|---|---|---|
| **RSK-01** | **Host Secret Exfiltration:** Malicious repository test fixtures or conftest read API server environment variables. | Critical | High | Hard fail-closed container isolation with `--network=none`; zero secrets passed to runner or containers. | **MITIGATED** (Verified via SEC-01 & SEC-03) |
| **RSK-02** | **Denial of Service via Fork-Bomb / OOM:** Untrusted repository code exhausts host CPU, RAM, or process table. | High | Medium | Linux cgroups limits: `--cpus=2.0`, `--memory=4g`, `--pids-limit=512`, process tree kill on timeout. | **MITIGATED** (Verified via SEC-04, SEC-05, SEC-06) |
| **RSK-03** | **Filesystem Tampering / Persistence:** Script writes persistent backdoors to system binaries or libraries. | High | Low | Root filesystem mounted `--read-only`; tmpfs `/tmp` mounted `noexec,nosuid`; only `/workspace` is writable. | **MITIGATED** (Verified via SEC-07) |
| **RSK-04** | **Cross-Tenant / Cross-Task Snooping:** One task workspace accesses or alters files in an adjacent task workspace. | High | Medium | Container mounts only the single task workspace (`-v /sandbox/workspaces/<id>:/workspace:rw`); path guards block traversal. | **MITIGATED** (Verified via SEC-02 & SEC-09) |
| **RSK-05** | **Docker Daemon Escape / Socket Compromise:** Container gains control of `/var/run/docker.sock` to take over host. | Critical | Low | Docker socket is never mounted into untrusted containers; `--user=10001:10001`, `--cap-drop=ALL`. | **MITIGATED** (Verified via SEC-08) |
| **RSK-06** | **Silent Fallback to Host Subprocess in Prod:** If runner host goes offline, system falls back to uncontained execution. | Critical | Low | Hard fail-closed rule in `SandboxFactory` and `Settings.validate_production_security`; raises `RunnerUnavailableError`. | **MITIGATED** (Verified via SEC-12) |
| **RSK-07** | **Malicious Dependency Build Script:** Python `setup.py` or npm lifecycle script runs arbitrary code during install. | High | Medium | Two-Phase Execution Pipeline: Phase A dependency installation executes strictly inside sandbox container. | **MITIGATED** (Verified via SEC-13) |
| **RSK-08** | **Zero-Day Linux Kernel Privilege Escalation:** Kernel exploit escapes standard Linux container namespaces. | Critical | Very Low | Production deployment incorporates gVisor `runsc` userspace syscall emulation; syscalls handled in userspace Go. | **MITIGATED on Linux; BLOCKED on macOS** (documented dependency) |

---

## 2. Infrastructure Dependencies & Operational Constraints

1. **gVisor (`runsc`) OS Dependency:**
   - gVisor runs on Linux hosts (Ubuntu 24.04 recommended).
   - On macOS developer machines, `runsc` is unavailable natively without a Linux virtual machine. In local macOS dev, standard Docker container isolation (`runc`) is active and verified, while `runsc` is verified on the dedicated Linux Runner VM.
2. **Dedicated Runner VM Provisioning:**
   - Azure App Service requires deployment of the dedicated Linux Runner VM (`Standard_B2s`) before production cutover to `SANDBOX_BACKEND=runner`.
