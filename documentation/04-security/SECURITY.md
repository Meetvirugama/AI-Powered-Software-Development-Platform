# Security

## Threat model summary

| Asset | Main threats | Primary controls |
|---|---|---|
| User sessions | Token theft, CSRF, replay | httpOnly cookies, short-lived HS256 JWT with `iss/aud/jti`, refresh rotation, Redis blocklist, Origin/Referer checks on writes, SameSite policy, fail-closed on Redis outage |
| GitHub credentials | Leakage via logs, argv, sandbox | Installation tokens cached in Redis, git auth via `GIT_CONFIG_*` env (never argv), push from API host only, secret redaction in logs/responses/checkpoints |
| Tenant data | Cross-tenant access | Ownership checks on every repository/task route, repository-scoped SQL, per-user SSE channels |
| LLM | Prompt injection from repository/issue content | System/data separation, delimited untrusted sections, provenance + taint policy, grounding validation |
| Host | Untrusted code execution | Sandbox backends (local refused in production), container hardening, gVisor, runner isolation, path guard, command allowlist, resource budgets |
| Supply chain | Vulnerable dependencies, committed secrets | pip-audit, Gitleaks, bandit, ruff in CI; pinned base image digest |

## Authentication and authorisation

- GitHub OAuth with PKCE (S256); state stored in Redis and consumed atomically (`GETDEL`), bound to the browser by cookie; redirect URLs validated against configured origins.
- Platform tokens: HS256, algorithm allow-list, mandatory claims (`sub, jti, iss, aud, token_type, iat, exp`), 15-minute access tokens, 7-day refresh tokens.
- GitHub App tokens use RS256 with the App private key — a separate trust domain from platform tokens.
- Roles: `viewer < developer < admin` (`require_min_role`, `require_role`). MCP registry mutations require `admin`.
- Dev login (`POST /auth/dev-login`): returns `404` unless `ENABLE_DEV_LOGIN=true`, `403` in production or from non-loopback clients; production startup fails if enabled.

## HTTP hardening

- `SecurityHeadersMiddleware`: `X-Frame-Options: DENY`, `X-Content-Type-Options`, CSP (relaxed only for the docs UI), HSTS on HTTPS.
- Vercel adds CSP and security headers for the SPA.
- CORS: explicit origins; regex must be anchored in production; no wildcards.
- Rate limiting per route via Redis.
- Webhooks: 5 MB size guard before reading the body, HMAC-SHA256 verification, delivery-id deduplication.
- `FORWARDED_ALLOW_IPS` restricted to loopback/private ranges when proxy headers are trusted.

## Agent and execution safety

| Control | Where |
|---|---|
| Mandatory plan approval bound to plan hash and base revision | `app/repositories/task/approvals.py` |
| Tool risk tiers, JSON-Schema validation, rate limits, audit | `agent/tools/*` |
| Tool approval gate (argument hash, expiry, single use) and MCP elicitation | `app/services/tool_approval_gate.py`, `app/services/mcp_elicitation_service.py` |
| Provenance and taint tracking (untrusted issue/repository content cannot drive command tools without re-approval) | `ai/security/*` |
| Path guard (traversal, symlinks, workspace confinement), forbidden files (`.env`, `.git`, credentials) | `sandbox/path_guard.py`, `ai/services/edit_synthesizer.py` |
| Command allowlist and argument validation; runner arguments validated before the approval gate | `sandbox/command_runner.py`, `app/api/v1/tasks.py` |
| Git hooks disabled (`core.hooksPath=/dev/null`) | sandbox backends |
| Container: no network in test phase, read-only root, non-root UID 10001, dropped capabilities, `no-new-privileges`, CPU/memory/PID limits, output cap, process-tree kill on timeout | `sandbox/container_backend.py` |
| Bounded repair (3 attempts); no test-file edits unless planned (anti reward-hacking) | `ai/services/bounded_repair_loop.py` |
| Independent verification incl. secret scan (regex + Gitleaks) before publication | `app/services/independent_verifier.py`, `sandbox/gitleaks_scanner.py` |
| Publication requires persisted, SHA-bound authorisation; protected branches refused; draft PR only | `app/repositories/task/publication.py`, `app/services/git_branch.py` |

## Data protection

- `app/core/secret_redaction.py` redacts keys, tokens, private-key blocks and credential assignments in API responses, analysis payloads, logs (handler-level filter), checkpoints and tool outputs.
- Observability never captures prompts/responses unless `OBSERVABILITY_CAPTURE_PROMPTS/RESPONSES` are explicitly enabled.
- The seed script refuses non-local databases without explicit flags.
- SSRF protection for MCP URLs: DNS resolution, private, loopback and metadata ranges blocked.

## CI security pipeline

| Job | Tooling |
|---|---|
| Secret scan | Gitleaks (`.gitleaks.toml`) |
| Static analysis | Ruff (syntax/error rules), Bandit (fails on HIGH) |
| Dependencies | pip-audit on production requirements |
| Gate | `backend/scripts/security_gate.py` (7 checks) and security/RBAC test suites |
| Pre-commit | `.pre-commit-config.yaml`, `.secrets.baseline` |

## Reporting

Report vulnerabilities privately to the maintainers rather than opening a public issue.

## Known gaps

See [Known limitations](../08-reference/KNOWN_LIMITATIONS.md): in-memory MCP registry, thread-based workflows, scanner binaries absent from the production image, runner host provisioning required for isolated execution in production.
