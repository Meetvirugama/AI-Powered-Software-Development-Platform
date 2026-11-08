# 04. User Roles & Permissions
> **Version:** 4.0 | **Created:** 2026-09-24 | **Last Updated:** 2026-11-08 | **Status:** 100% Implemented & Synchronized

---

## Defined Roles

| Role | Description |
|---|---|
| **Anonymous** | Unauthenticated user — limited to `/login` and `/api/v1/health` |
| **Developer** | Authenticated GitHub user — primary user with access to connected repositories, intelligence features, and workflows |
| **Team Lead / Admin** | Enhanced administrative oversight, policy review, and audit trail inspection |

---

## Permission Matrix

### 1. Authentication & Profile

| Feature | Anonymous | Developer | Lead / Admin |
|---|---|---|---|
| View login page | ✓ | ✓ | ✓ |
| GitHub OAuth login | ✓ | ✓ | ✓ |
| View own profile (`/api/v1/auth/me`) | — | ✓ | ✓ |
| Logout & invalidate session (`/api/v1/auth/logout`) | — | ✓ | ✓ |

### 2. Repository & Discovery

| Feature | Anonymous | Developer | Lead / Admin |
|---|---|---|---|
| Discover repositories via GitHub App (`/github/repositories`) | — | ✓ | ✓ |
| Connect repository (`/github/repositories/:id/connect`) | — | ✓ | ✓ |
| List connected repositories (`/repositories`) | — | ✓ | ✓ |
| View repository details (`/repositories/:id`) | — | ✓ | ✓ |
| Trigger repository sync (`/repositories/:id/sync`) | — | ✓ | ✓ |
| List indexed files & symbols | — | ✓ | ✓ |
| Grounded repository chat (`/repositories/:id/chat`) | — | ✓ | ✓ |
| Bounded Agentic Chat mode & tool inspection | — | ✓ | ✓ |

### 3. Developer Intelligence Suite (Week 2 — Active)

| Feature | Anonymous | Developer | Lead / Admin |
|---|---|---|---|
| Request Code Explanation (`/explain`) | — | ✓ | ✓ |
| Run Dedicated Bug Detection (`/detect-bugs`) | — | ✓ | ✓ |
| Request Framework-Aware Test Generation (`/generate-tests`) | — | ✓ | ✓ |
| Run Standalone AI Code Review (`/review`) | — | ✓ | ✓ |
| View historical analysis runs & findings | — | ✓ | ✓ |

### 4. Workflow Automation & GitHub Ecosystem (Week 3 — Complete)

| Feature | Anonymous | Developer | Lead / Admin |
|---|---|---|---|
| Import GitHub Issue as task | — | ✓ | ✓ |
| Create GitHub Issue from approved finding | — | ✓ | ✓ |
| Request structured task plan (`/plan`) | — | ✓ | ✓ |
| **Approve / Reject Implementation Plan** | — | ✓ | ✓ |
| Trigger isolated workspace execution | — | ✓ | ✓ |
| View live execution timeline & terminal logs | — | ✓ | ✓ |
| Review test runner & self-repair attempts | — | ✓ | ✓ |
| Inspect independent verification report | — | ✓ | ✓ |
| **Authorize Git Push & Draft PR creation** | — | ✓ | ✓ |
| Merge Pull Request | — | Manual on GitHub | Manual on GitHub |

### 5. Enterprise Hardening & Durable Webhooks (Post-Week 3 — Complete)

| Feature | Anonymous | Developer | Lead / Admin |
|---|---|---|---|
| Ingest GitHub webhook deliveries (`/github/webhook`) | ✓ (HMAC) | ✓ (HMAC) | ✓ (HMAC) |
| View durably persisted webhook events (`/github/events`) | — | ✓ | ✓ |
| Inspect webhook event details & payload (`/github/events/:id`) | — | ✓ | ✓ |
| Replay failed/dead-letter webhook event (`/github/events/:id/replay`) | — | ✓ | ✓ |
| View repository automation settings (`/github/repositories/:id/automation`) | — | ✓ | ✓ |
| Update repository automation settings (`/github/repositories/:id/automation`) | — | ✓ | ✓ |

---

## Agent / Workflow Internal Permission Tiers

Enforced server-side by the Policy Engine (Devu / Sukun), not solely by UI button states:

| Workflow Action | Permission Rule | Enforcement Point |
|---|---|---|
| Read repository files | Always allowed within authorized repository | `FileWalker` / `GitHubService` |
| Execute AI analysis | Read-only; cannot modify repository files | Analysis Engines |
| Modify workspace files | **DENIED** until explicit Human Plan Approval | Task Orchestrator & Approval Gate |
| Run test commands | Allowed only for permitted command templates | Tool Router (`allowlist`) |
| Network egress from sandbox | Denied by default; allowed only if explicitly whitelisted | Sandbox Policy Engine |
| Commit to task branch | Allowed only inside `.workspaces/task-<id>` | Git Workspace Manager |
| Push to remote GitHub | **DENIED** without explicit publication authorization | Publication Gate |
| Push to protected branches (`main`/`master`) | **STRICTLY FORBIDDEN (NEVER ALLOWED)** | Git Security Policy |
| Merge Pull Request | **STRICTLY FORBIDDEN (NEVER ALLOWED)** | GitHub Policy (Human Only) |
| Agentic chat write operations | **STRICTLY FORBIDDEN (READ-ONLY ONLY)** | `ExecutionPolicy` directory jail & tool registry |

---

## Authentication Implementation Details

- **Protocol:** GitHub OAuth 2.0 with atomic Redis CSRF state nonces (`oauth_state:{state}` with `GETDEL`).
- **Session Token:** JSON Web Token (JWT, HS256) stored in `httpOnly`, `secure`, `SameSite=Lax` cookie.
- **Timing Safety:** Cryptographic signatures verified via `hmac.compare_digest` to prevent timing side-channels.
- **Secret Entropy:** Startup validation strictly rejects keys shorter than 32 bytes (256 bits).
- **Frontend State:** Derived from `GET /api/v1/auth/me` via Zustand `useAuthStore`.
- **Session Revocation:** Logout adds the JWT identifier (`jti`) to Redis blocklist (`jwt_blocklist:{jti}`) with remaining TTL.
