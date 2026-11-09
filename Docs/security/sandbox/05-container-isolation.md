# Container & gVisor Isolation Specification
**Target:** AI-Powered Software Development Platform — Secure Sandbox Execution Architecture (Issue #200 / F20)  
**Date:** November 2026  
**Status:** Production Standard  

---

## 1. Container Security Hardening Profile

Every untrusted command executed inside `ContainerBackend` is launched with a hardened OCI security profile.

```bash
docker run \
  --name "sandbox-<task_id>-<timestamp>" \
  --rm \
  --cpus=2.0 \
  --memory=4g \
  --pids-limit=512 \
  --read-only \
  --tmpfs /tmp:rw,noexec,nosuid,size=512m \
  -v /sandbox/workspaces/<task_id>:/workspace:rw \
  -w /workspace \
  --cap-drop=ALL \
  --security-opt=no-new-privileges \
  --user=10001:10001 \
  --network=none \
  --runtime=runsc \
  python:3.12-slim \
  python -m pytest tests/
```

### 1.1 Flag-by-Flag Security Breakdown

| Flag | Category | Purpose & Security Enforcement |
|---|---|---|
| `--network=none` | Network Isolation | Disables all external network interfaces. Blocks outbound data exfiltration, socket connections, and reverse shells during test execution. |
| `--read-only` | Filesystem Integrity | Mounts the container root filesystem (`/`) as immutable. Untrusted scripts cannot modify `/usr`, `/bin`, `/lib`, or system binaries. |
| `--tmpfs /tmp:rw,noexec,nosuid,size=512m` | Temporary Storage | Mounts a 512 MB memory-backed tmpfs for `/tmp` with `noexec` (prohibiting execution of newly dropped binaries) and `nosuid`. |
| `-v <ws>:/workspace:rw` | Workspace Confinement | Bind-mounts only the assigned task directory to `/workspace`. Untrusted scripts have zero visibility into other task directories. |
| `--user=10001:10001` | Non-Root Execution | Runs the process as an unprivileged user (UID/GID 10001), preventing container-level root privileges. |
| `--cap-drop=ALL` | Capability Stripping | Drops all Linux capabilities (`CAP_NET_RAW`, `CAP_SYS_ADMIN`, `CAP_DAC_OVERRIDE`, etc.). The process cannot alter kernel parameters or mount devices. |
| `--security-opt=no-new-privileges` | Privilege Escalation Block | Prevents child processes from gaining additional privileges via `setuid` or `setgid` binaries. |
| `--cpus=2.0` | Resource Boundary | Enforces a hard cgroup ceiling of 2 vCPUs, preventing CPU exhaustion loops from starving sibling containers or the runner host. |
| `--memory=4g` | Resource Boundary | Enforces a hard cgroup ceiling of 4 GB RAM. Processes exceeding this limit trigger container OOM without impacting host memory. |
| `--pids-limit=512` | Resource Boundary | Restricts maximum concurrent processes and threads to 512, completely neutralizing fork-bombs (`:(){ :|:& };:` or `[os.fork() ...]`). |
| `--runtime=runsc` | Userspace Kernel | Routes system calls through Google's gVisor userspace Sentry, insulating the host Linux kernel from potential kernel exploits. |

---

## 2. gVisor (`runsc`) Architecture & Verification

1. **How gVisor Operates:**
   - Instead of translating container syscalls directly to the host Linux kernel, `runsc` runs a virtual userspace kernel (the Sentry) in Go.
   - Filesystem operations pass through Gofer, a proxy process that mediates access to the `/workspace` bind mount.
2. **Runtime Verification:**
   - The platform verifies gVisor support via:
     ```python
     def _verify_gvisor_runtime(self) -> bool:
         proc = subprocess.run(["docker", "info", "--format", "{{json .Runtimes}}"], capture_output=True, text=True)
         return "runsc" in proc.stdout or shutil.which("runsc") is not None
     ```
   - When verified, `--runtime=runsc` is engaged automatically.
   - If `runsc` is not installed (e.g. on macOS developer workstations), standard hardened Docker isolation (`runc`) is maintained and the verification status is transparently reported in telemetry as `gvisor_verified: false`.

---

## 3. Pinned Language Images Policy

Untrusted repository code must never specify arbitrary container images or supply custom Dockerfiles to the host.

Approved Language Images:
- **Python Workloads:** `python:3.12-slim`
- **Node.js / TypeScript Workloads:** `node:20-slim`
- Floating `latest` tags are prohibited in production. Images are pulled and pinned to verified base tags or digests.

---

## 4. Lifecycle Management & Orphan Cleanup

Sandboxes are governed by an automated lifecycle manager:
1. **Hard Command Timeout:** Default 30s, configurable up to 300s. Exceeding budget triggers immediate `docker kill <container_name>` and process group termination.
2. **Max Sandbox Lifetime:** Idle or hanging workspaces are subject to a 1-hour maximum lifetime ceiling (`SANDBOX_MAX_LIFETIME=3600`).
3. **Orphan Sweeper:** A periodic background worker inspects Docker containers matching the `sandbox-*` naming pattern. Any container older than its timeout budget is forcefully pruned (`docker rm -f`).
