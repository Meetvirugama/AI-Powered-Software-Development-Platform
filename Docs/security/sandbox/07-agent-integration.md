# AI Agent Integration & CommandRunner Migration
**Target:** AI-Powered Software Development Platform — Secure Sandbox Execution Architecture (Issue #200 / F20)  
**Date:** November 2026  
**Status:** Integrated Architecture  

---

## 1. Unified Execution Flow

Prior to this architecture, automated agents invoked `WorkspaceCommandRunner.run_command(...)`, which directly spawned `subprocess.Popen` on the host API server.

With the secure execution architecture, all agents continue using the familiar `WorkspaceCommandRunner`, `WorkspaceTestRunner`, and `WorkspaceManager` interfaces, but execution is dynamically routed through `SandboxFactory`:

```
   +-------------------------------------------------------------+
   |                       AI AGENT LAYER                        |
   |                                                             |
   |   +-----------------------+     +-----------------------+   |
   |   |   Bug Detection Agent |     | Test Generation Agent |   |
   |   +-----------------------+     +-----------------------+   |
   |               │                             │               |
   |               ▼                             ▼               |
   |   +-----------------------+     +-----------------------+   |
   |   |   Static Reviewer     |     | Execution Verifier    |   |
   |   +-----------------------+     +-----------------------+   |
   |               │                             │               |
   |               +--------------+--------------+               |
   |                              │                              |
   |                              ▼                              |
   |               +-----------------------------+               |
   |               |   WorkspaceCommandRunner    |               |
   |               +-----------------------------+               |
   +------------------------------│------------------------------+
                                  │
                                  ▼
                     +--------------------------+
                     |      SandboxFactory      |
                     +--------------------------+
                       /                      \
      (Development)   /                        \  (Production)
                     ▼                          ▼
        +--------------------------+  +--------------------------+
        |  LocalSubprocessBackend  |  |       RunnerClient       |
        +--------------------------+  +--------------------------+
                                                    │
                                                    ▼
                                      +--------------------------+
                                      |      Runner Service      |
                                      +--------------------------+
                                                    │
                                                    ▼
                                      +--------------------------+
                                      | Docker / gVisor Sandbox  |
                                      +--------------------------+
```

---

## 2. Integrated Platform Agents

### 2.1 Test Generation Agent & Execution Verifier
- **Location:** `backend/app/services/test_execution_verifier.py`, `backend/app/services/test_stability_service.py`
- **Role:** Generates unit tests and validates their pass rate and flake resistance across repeated executions.
- **Integration:** Calls `self._workspace_manager.test_runner.run_tests(...)`. Because `WorkspaceCommandRunner` delegates to `SandboxBackend`, the test execution verifier automatically runs generated tests inside the hardened container with `--network=none`.

### 2.2 Bug Detection & Code Review Agents
- **Location:** `backend/review/static_reviewer.py`, `backend/app/services/bug_detection_orchestrator.py`
- **Role:** Executes static analysis tools (`ruff`, `eslint`, `biome`) and inspects AST structures.
- **Integration:** Static linters that execute JavaScript plugins or custom rules run inside the sandbox container (`node:20-slim`), preventing rogue npm packages or malicious ESLint plugins from reading host API secrets.

### 2.3 Task Execution Orchestrator
- **Location:** `backend/app/services/task_execution_orchestrator.py`
- **Role:** Provisions task workspaces, applies file patches, validates diffs, and coordinates repair loops.
- **Integration:** The orchestrator binds `WorkspaceManager(backend=...)`, ensuring all file modifications, invariant checks, and tool invocations operate against the secured sandbox.

---

## 3. Git Operations Security

Git commands process untrusted repository content (e.g. `.git/config`, hooks, smudge filters, submodules).

Security Policies for Git Operations:
1. **Disabled Git Hooks:** All host-side git operations (such as worktree creation, diff calculation, and branch checkout) are executed with:
   ```bash
   git -c core.hooksPath=/dev/null <command>
   ```
   This prevents malicious repository-controlled `.git/hooks/` (e.g. `pre-commit`, `post-checkout`) from executing on the host.
2. **Untrusted Git Commands in Sandbox:** Any git operation run by an AI agent tool or test suite runs strictly inside the sandbox container.
3. **No Credential Exposure:** Git clone credentials (GitHub App installation tokens) are scoped, injected only during initial clone operations, and never stored in workspace `.git/config` files.
