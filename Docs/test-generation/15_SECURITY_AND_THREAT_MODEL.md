# Security Threat Model (STRIDE) & Hardening

---

## 1. STRIDE Analysis of Generated Code Execution

| STRIDE Threat Category | Potential Attack Scenario | Mitigating Control |
| :--- | :--- | :--- |
| **Spoofing** | Test code attempts to impersonate authenticated backend service or user | Subprocess executed with unprivileged UID, isolated environment variables, and no token forwarding. |
| **Tampering** | Test code attempts to modify repository source code or `conftest.py` | Workspaces provisioned under `.workspaces/`; source files are disposable copies. Path guard blocks write escapes. |
| **Repudiation** | Test execution crashes host process without leaving an audit trail | `WorkspaceExecutionEvent` timeline records events. Terminal stdout/stderr captured in bounded logs. |
| **Information Disclosure** | Test prints `os.environ` or leaks API keys in assertions | `redact_secrets_in_text` sanitizes raw stdout, covered scenarios, warnings, and error messages before response. |
| **Denial of Service** | Test enters `while True:` loop or exhausts heap memory | Process group hard timeout (default 45s, max 60s) sends `SIGKILL`. Resource monitor caps memory. |
| **Elevation of Privilege** | Test executes `sudo`, installs kernel modules, or escapes sandbox | Subprocess commands restricted to allowlist (`pytest`, `python`, `npm`). Package installations rejected. |

---

## 2. Hard Security Boundaries

1. **Host Isolation**: Generated tests never execute directly within the main FastAPI backend process.
2. **Read-Only Original Workspace**: Code is executed solely within a disposable clone in `.workspaces/`.
3. **Fail-Closed Policy**: Any policy violation immediately marks the test `REJECTED` or `UNVERIFIED`.
