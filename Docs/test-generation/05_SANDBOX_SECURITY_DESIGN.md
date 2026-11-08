# Sandbox Security Design & Threat Mitigation

Generated tests represent untrusted executable code. This document details the defense-in-depth architecture protecting the host system, repositories, and secrets.

---

## 1. Security Threat Model & Protections

| Threat Vector | Potential Attack | Security Mitigation | Implementation File |
| :--- | :--- | :--- | :--- |
| **Path Traversal** | `../../etc/shadow` or overwriting `conftest.py` | `WorkspacePathGuard.resolve_within_workspace` + `check_generated_test_path` reject escapes and reserved files. | `backend/sandbox/path_guard.py`, `backend/app/services/test_generation_orchestrator.py` |
| **Credential Theft** | Inspecting environment variables for API keys | Environment whitelist strips all credentials; logs pass through `redact_secrets_in_text`. | `backend/sandbox/command_runner.py`, `backend/app/core/secret_redaction.py` |
| **Malicious Package Installs** | `npm install evil-pkg` or `pip install` inside test suite | Disallowed command tokens and forbidden subcommands (`install`, `add`, `update`, `upgrade`) raise `WorkspacePolicyViolationError`. | `backend/sandbox/test_runner.py` |
| **Resource Exhaustion** | Infinite loops / fork bombs | Hard timeouts (default 45s, max 60s) terminate runaway processes via process group `SIGKILL`. Memory caps monitored. | `backend/sandbox/command_runner.py`, `backend/sandbox/resource_monitor.py` |
| **Network Probing** | Phone-home telemetry or SSRF | Network sockets blocked by test runner policies; offline mock fixtures enforced. | `backend/ai/prompts/test_generation_system.txt`, `backend/sandbox/command_runner.py` |
| **Filesystem Pollution** | Leaving dirty files or orphan temp directories | Strict workspace lifecycle: every workspace provisioned has an idempotent cleanup call in a `finally:` block. | `backend/app/services/test_execution_verifier.py`, `backend/sandbox/workspace_manager.py` |

---

## 2. Environment Stripping Whitelist
Subprocesses executed via `WorkspaceCommandRunner` only inherit minimal non-sensitive variables:
- `PATH`: System binary lookup path.
- `HOME` / `USER`: Standard user identifiers for local temp operations.
- `LANG` / `LC_ALL`: UTF-8 locale variables.
- `PYTHONPATH`: Scoped strictly to the isolated workspace root.

All cloud credentials (`AWS_*`, `GITHUB_*`, `GEMINI_*`, `DATABASE_URL`, `JWT_SECRET`) are explicitly stripped.
