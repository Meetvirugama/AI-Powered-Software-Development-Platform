# Secure Execution Technology Research & Evaluation
**Target:** AI-Powered Software Development Platform — Secure Sandbox Execution Architecture (Issue #200 / F20)  
**Date:** November 2026  
**Author:** Senior Backend & Security Infrastructure Architecture Team  

---

## 1. Executive Overview

Executing untrusted code from arbitrary GitHub repositories requires multi-layered defense-in-depth. Application-level safeguards (such as Python string checks or command allowlists) are insufficient on their own because Python scripts, pytest fixtures, setup hooks, and npm install scripts can invoke arbitrary system calls (`syscall`), read memory, open network sockets, and manipulate the underlying operating system.

This research document evaluates containerization, sandboxing, and virtualization technologies to select the optimal production architecture for the AI-Powered Software Development Platform.

---

## 2. Technology Evaluations

### 2.1 Docker (Moby / OCI Containers)
- **Architecture:** Linux kernel cgroups (v1/v2), kernel namespaces (PID, Mount, Net, IPC, UTS, User), seccomp-bpf system call filters, and Linux capabilities.
- **Key Capabilities for Sandboxing:**
  - **Network Isolation:** `--network=none` tears down all network interfaces except the loopback (`lo`), preventing any egress exfiltration or ingress command-and-control.
  - **Filesystem Protection:** `--read-only` mounts the root filesystem as read-only. Writable state is restricted to explicit temporary storage (`--tmpfs /tmp:rw,noexec,nosuid,size=512m`) and the specific workspace bind-mount (`-v /sandbox/workspaces/<task_id>:/workspace:rw`).
  - **Resource Capping:** `--cpus=2`, `--memory=4g`, `--pids-limit=512` enforced by Linux cgroups at the kernel level.
  - **Privilege Dropping:** `--cap-drop=ALL`, `--security-opt=no-new-privileges`, and non-root execution (`--user=10001:10001`).
- **Container Escape Risks:**
  - Containers share the host Linux kernel. Any Linux kernel privilege escalation zero-day (e.g., Dirty COW, CVE-2022-0847 Dirty Pipe, io_uring vulnerabilities) could potentially compromise the host if not mitigated by userspace syscall interception.
- **Licence:** Apache-2.0 (Moby Engine / Docker CE components).

### 2.2 gVisor (`runsc` OCI Runtime)
- **Architecture:**
  - Developed by Google, gVisor is an application kernel written in Go that implements substantial portions of the Linux system call interface in userspace.
  - **Sentry:** Intercepts system calls made by untrusted applications. Rather than passing syscalls directly to the host Linux kernel, the Sentry handles them internally in userspace.
  - **Gofer:** A mediator process that provides secure, mediated filesystem access using the 9P or direct host filesystem protocol.
- **Docker Integration:**
  - gVisor integrates directly into Docker via the `runsc` OCI runtime (`docker run --runtime=runsc ...`).
  - Does **not** require hardware virtualization (`/dev/kvm`), making it deployable on standard cloud virtual machines without nested virtualization support.
- **Performance & Compatibility:**
  - **Overhead:** ~10–25% CPU overhead on heavy system call workloads (e.g. rapid filesystem access or fork-heavy operations). Pure compute workloads run with near-zero overhead.
  - **Compatibility:** Implements over 300 Linux system calls. Standard Python test suites (`pytest`, `unittest`), Node.js (`npm`, `jest`), Git operations, and standard linters (`ruff`, `eslint`) run with 100% compatibility.
- **Security Posture:**
  - Provides a critical defense-in-depth layer: even if a malicious payload attempts a kernel exploit, the exploit targets the Go-based userspace Sentry rather than the host Linux kernel.
- **Licence:** Apache-2.0.

### 2.3 Firecracker (MicroVMs)
- **Architecture:**
  - Developed by AWS, Firecracker runs minimalist virtual machines (MicroVMs) on top of the Linux Kernel-based Virtual Machine (`/dev/kvm`).
  - Strips legacy devices, providing sub-second boot times (~5ms) and minimal memory footprint (~5 MB per VM).
- **Evaluation:**
  - Hardware-level virtualization isolation guarantees that even kernel exploits cannot breach the host VM.
  - **Operational Complexity:** Requires `/dev/kvm`, which demands Bare Metal or nested-virtualization-capable cloud instances (e.g. Azure Dv3 / Ev3 series). Requires building custom Linux guest kernels, rootfs ext4 images, and managing tap networking devices.
- **Conclusion:** Firecracker provides the highest theoretical isolation but carries substantial operational and infrastructure cost overhead. Suitable as a future phase architecture when scaling to multi-tenant multi-cluster workloads.
- **Licence:** Apache-2.0.

### 2.4 E2B (Managed Sandboxes)
- **Architecture:** Managed cloud infrastructure providing Firecracker-based sandboxes for AI agents via an open-source SDK.
- **Evaluation:**
  - Fast time-to-market; eliminates need to manage runner infrastructure.
  - **Drawbacks:** Introduces external third-party SaaS dependency, ongoing usage-based pricing, external data transit for proprietary code, and potential rate limits.
- **Licence:** Apache-2.0 (SDK & infrastructure).

### 2.5 Daytona & OpenHands
- **Daytona:** Dev environment orchestrator. Features robust workspace management, but is licensed under **AGPL-3.0**. Copying or bundling Daytona code into our proprietary platform would impose copyleft obligations. Therefore, Daytona is used as an architectural reference only, with zero direct code reuse.
- **OpenHands (formerly OpenDevin):** Open-source AI software development agent with a Docker action execution runtime. Validates the Docker container action pattern with non-root users. Licensed under MIT.

---

## 3. Technology Comparison Matrix

| Technology | Isolation Layer | Requires KVM? | Performance Overhead | Startup Latency | Licence | Deployment on Azure App Service? | Recommended Role |
|---|---|---|---|---|---|---|---|
| **Host Subprocess (Current)** | None (Same host, user, network) | No | 0% | ~10ms | Internal | Yes (Existing) | **Development only (`APP_ENV=development`)** |
| **Docker (runc)** | Linux Namespaces + cgroups + seccomp | No | < 2% | ~500ms | Apache-2.0 | No (needs dedicated VM) | **Baseline Container Engine** |
| **Docker + gVisor (`runsc`)** | Userspace Kernel (Sentry + Gofer) | No | 10–20% | ~800ms | Apache-2.0 | No (needs dedicated Linux VM) | **Target Production Sandbox Architecture** |
| **Firecracker MicroVM** | Hardware Hypervisor (KVM) | Yes | ~5% | ~50ms | Apache-2.0 | No (requires nested virt VM) | Future Scale-out Evolution |
| **E2B Cloud** | Managed Firecracker | No (SaaS) | Network bound | ~200ms | Apache-2.0 | Yes (via API) | Optional SaaS Alternative |
| **Daytona** | Container Workspaces | No | < 5% | ~1s | AGPL-3.0 | No | Architectural Reference Only (Do Not Copy Code) |

---

## 4. Final Technology Decisions & Rationale

1. **Primary Container Engine:** Docker (Moby) Engine.  
   *Rationale:* Industry standard, proven stability, native support for cgroups v2, read-only root filesystems, `--network=none`, and seamless OCI runtime integration.

2. **Production Userspace Isolation:** gVisor (`runsc`).  
   *Rationale:* Intercepts system calls in userspace without requiring KVM hardware virtualization. Runs cleanly on standard Azure Linux Virtual Machines (e.g., Standard_B2s or Standard_D2s_v5). When `runsc` is available on the runner host, `--runtime=runsc` is engaged.

3. **Pluggable Architecture:** `SandboxBackend` abstraction with `LocalSubprocessBackend`, `ContainerBackend`, and `RunnerClient`.  
   *Rationale:* Decouples AI orchestrator agents from execution mechanics, enables fast development on developer workstations, and guarantees hard fail-closed enforcement in production.

4. **Dedicated Runner Host:** Linux VM with authenticated REST API.  
   *Rationale:* Azure App Service (where the main API is deployed) does not support running sibling Docker containers. A dedicated Runner VM provides strict boundary isolation and prevents host secret leakage.
