# Secure Sandbox Execution Architecture
**AI-Powered Software Development Platform — Production Sandbox System (F20 / Issue #200)**

---

## 1. What is Sandbox Execution & Why is it Critical?

Our platform enables autonomous AI agents to analyze, modify, build, and test software across untrusted external GitHub repositories. 

Executing arbitrary repository code directly on an API server poses an existential security risk:
- Repository test fixtures (`conftest.py`, `unittest`), build backends (`setup.py`), or npm lifecycle scripts can execute arbitrary Python, JavaScript, and shell commands.
- On a shared host, malicious code could inspect environment variables containing AI API keys (`GEMINI_API_KEY`, `GROQ_API_KEY`), database passwords, or Azure credentials.
- Untrusted code could launch fork-bombs, exhaust host memory, read other users' workspaces, or exfiltrate private source code over the network.

**The Secure Sandbox Execution Architecture completely isolates untrusted repository code from the host API server.** In production, untrusted code runs exclusively inside containerized environments backed by Docker and gVisor, with no network access during test runs, read-only root filesystems, non-root users, and strict CPU/RAM/PID bounds.

---

## 2. System Architecture & Component Interaction

```
[ FRONTEND ] (Vercel)
     │
     ▼ (HTTPS / JWT)
[ API SERVER ] (Azure App Service)
     │
     ├── AI Orchestrator & Agents (Code Review, Bug Scanner, Test Generator)
     ├── WorkspaceManager & PathGuard
     ├── CommandRunner
     └── SandboxFactory
              │
              ├── (APP_ENV=development) ────────► LocalSubprocessBackend
              │
              └── (APP_ENV=production)  ────────► RunnerClient
                                                        │
                                                        ▼ (Bearer Auth over TLS)
                                              [ DEDICATED RUNNER SERVICE ]
                                              (Linux Runner Host / Azure VM)
                                                        │
                                                        ▼
                                              [ DOCKER ENGINE + gVisor runsc ]
                                              --network=none
                                              --read-only
                                              --user=10001:10001
                                              --cpus=2 --memory=4g --pids-limit=512
```

---

## 3. Documentation Structure

This documentation suite provides a complete, production-grade reference for developers, security engineers, and DevOps operators:

| Document | Title | Description |
|---|---|---|
| [01-existing-architecture-audit.md](01-existing-architecture-audit.md) | Existing Architecture Audit | Codebase audit of execution entry points, security gaps, and vulnerability scenarios. |
| [02-technology-research.md](02-technology-research.md) | Technology Research | Deep-dive evaluation of Docker, gVisor (`runsc`), Firecracker, E2B, Daytona, and nsjail. |
| [03-target-architecture.md](03-target-architecture.md) | Target Architecture | Comprehensive architecture specification, trust boundaries, lifecycle, and interfaces. |
| [04-runner-service-design.md](04-runner-service-design.md) | Runner Service Design | Internal REST API contracts, bearer authentication over TLS, schemas, and lifecycle management. |
| [05-container-isolation.md](05-container-isolation.md) | Container & gVisor Isolation | Kernel flags, cgroups limits, read-only rootfs, tmpfs, capabilities, and runtime setup. |
| [06-dependency-installation.md](06-dependency-installation.md) | Two-Phase Execution | Phase A (controlled dependency install) vs Phase B (offline execution without network). |
| [07-agent-integration.md](07-agent-integration.md) | Agent & Tool Integration | Integration with CommandRunner, WorkspaceManager, test generators, and review agents. |
| [08-security-hardening.md](08-security-hardening.md) | Security Hardening | Multi-layered defense-in-depth, secret scrubbing, path confinement, and quota enforcement. |
| [09-security-testing.md](09-security-testing.md) | Security Testing & Scenarios | Verification report for the 12 security attack scenarios tested against the sandbox. |
| [10-azure-deployment.md](10-azure-deployment.md) | Azure Deployment Guide | VM setup, Docker + gVisor installation script, systemd service, and cost optimization. |
| [11-configuration-reference.md](11-configuration-reference.md) | Configuration Reference | Environment variables, security defaults, and production fail-closed rules. |
| [12-implementation-guide.md](12-implementation-guide.md) | Implementation Guide | Codebase file map, class responsibilities, and key method signatures. |
| [13-operations-and-troubleshooting.md](13-operations-and-troubleshooting.md) | Operations & Troubleshooting | Runbooks for starting runner, orphan cleanup, diagnosing timeouts, and logs inspection. |
| [14-risk-register.md](14-risk-register.md) | Risk Register | Matrix of residual risks, likelihood, impact, mitigations, and tracking status. |
| [15-implementation-status.md](15-implementation-status.md) | Implementation Status | Living checklist of completed components, test coverage, and verification results. |

Diagrams are maintained in the [diagrams/](diagrams/) directory in Mermaid (`.mmd`) format:
- `architecture.mmd`
- `execution-sequence.mmd`
- `workspace-lifecycle.mmd`
- `dependency-installation-flow.mmd`
- `security-boundary.mmd`
- `deployment-architecture.mmd`
