# Security Hardening & Defense-in-Depth Specification
**Target:** AI-Powered Software Development Platform — Secure Sandbox Execution Architecture (Issue #200 / F20)  
**Date:** November 2026  
**Status:** Approved Hardening Baseline  

---

## 1. Multi-Layered Defense-in-Depth Model

Security is never entrusted to a single defense mechanism. The architecture enforces four concentric rings of defensive controls:

```
[ LAYER 1: Application-Level Input & Policy Guardrails ]
    ├── WorkspacePathGuard: Absolute path, UNC, and '..' climbing rejection
    ├── Command Allowlist: Permitted executables only (pytest, python, npm, git)
    ├── Argument Tokenizer: Blocks shell injection characters (;, |, &, >, <, `)
    ├── Output Capping: Terminal buffers bounded to 100 KB
    └── Secret Redaction: Regex masking of keys, tokens, and credentials

[ LAYER 2: Host Network & Secret Boundary ]
    ├── Zero Secret Injection: Runner and containers receive no cloud API keys
    ├── Private VNet: Runner service isolated behind internal NSG rules
    └── Mutual Bearer Token: Authenticated API with constant-time verification

[ LAYER 3: OCI Container Boundary (Linux Kernel) ]
    ├── Network Isolation: --network=none in offline execution phase
    ├── Filesystem Immutability: --read-only rootfs + tmpfs on /tmp (noexec, nosuid)
    ├── Capability Stripping: --cap-drop=ALL and --security-opt=no-new-privileges
    ├── Non-Root User: UID 10001 unprivileged execution
    └── Resource Limits (cgroups v2): 2 vCPU, 4GB RAM, 512 PIDs

[ LAYER 4: Userspace Kernel Boundary (gVisor) ]
    ├── Sentry Syscall Interception: Emulates 300+ Linux syscalls in Go
    └── Gofer Filesystem Proxy: Mediates host filesystem access without raw syscalls
```

---

## 2. Platform Secret Isolation Policy

The platform handles numerous sensitive credentials:
- LLM Provider Keys: `GEMINI_API_KEY`, `GROQ_API_KEY`.
- Storage & DB: Supabase PostgreSQL credentials, Upstash Redis password.
- Application Security: `JWT_SECRET`, GitHub OAuth Client Secret.
- Cloud Hosting: Azure service credentials.

### Isolation Rules:
1. **Never Forward Secrets to Runner:** The Runner Service request payload accepts only task parameters, command strings, arguments, and workspace-relative paths. It has no configuration for AI keys or database credentials.
2. **Never Forward Secrets to Containers:** Environment variables passed via `-e` in `docker run` are sanitized by `WorkspaceCommandRunner.sanitize_environment`. All host environment variables are stripped except standard non-sensitive keys (`PATH`, `LANG`, `TMP`).
3. **Secret Redaction in Output:** If a test script echoes a leaked secret or reflects environment variables, the runner passes standard output and standard error through `app.core.secret_redaction.redact(...)` before persisting or returning the result.

---

## 3. Storage Quotas & Disk Confinement

1. **Workspace Root Validation:** `WorkspacePathGuard.validate_workspace_root` ensures all workspaces reside strictly under designated directories (`.workspaces/<task_id>`). UNC shares, root filesystems (`/`), and platform repos are rejected.
2. **Path Traversal Protection:** Every file read/write operation resolves paths with `validate_repo_relative_path` and `is_within`.
3. **Disk Quota Enforcement:** `WorkspaceResourceMonitor` calculates recursive disk usage across the task directory, enforcing:
   - Maximum workspace disk budget: **500 MB** (`DEFAULT_MAX_DISK_BYTES`).
   - Maximum individual file size: **5 MB** (`DEFAULT_MAX_FILE_SIZE_BYTES`).
   - Maximum modified files per task: **50 files** (`DEFAULT_MAX_FILES_MODIFIED`).
