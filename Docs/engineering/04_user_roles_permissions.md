# 04. User Roles & Permissions
> **Version:** 1.0 | **Created:** 2026-09-24 | **Last Updated:** 2026-09-24 | **Status:** Draft

> [!NOTE]
> Role system is not yet implemented in the backend. Auth API is a stub. The roles below are derived from the project design documents (`project_idea.md`, `team_rules.md`).

---

## Defined Roles

| Role | Description |
|---|---|
| **Anonymous** | Unauthenticated user — no access beyond login page |
| **Developer** | Authenticated GitHub user — primary user of the platform |
| **Team Lead** | TBD — extends Developer with analytics/admin capabilities (not yet implemented) |
| **Platform Admin** | TBD — future scope only |

---

## Permission Matrix

### Authentication & Profile

| Feature | Anonymous | Developer | Team Lead | Admin |
|---|---|---|---|---|
| Access login page | ✓ | ✓ | ✓ | ✓ |
| GitHub OAuth login | ✓ | ✓ | ✓ | ✓ |
| View own profile (`/auth/me`) | — | ✓ | ✓ | ✓ |
| Logout | — | ✓ | ✓ | ✓ |

### Repository Management

| Feature | Anonymous | Developer | Team Lead | Admin |
|---|---|---|---|---|
| List own repositories | — | ✓ | ✓ | ✓ |
| View repository detail | — | ✓ | ✓ | ✓ |
| Trigger repository sync | — | ✓ | ✓ | ✓ |
| Install GitHub App on repo | — | ✓ | ✓ | ✓ |
| Manage other users' repos | — | — | TBD | ✓ |

### AI Chat

| Feature | Anonymous | Developer | Team Lead | Admin |
|---|---|---|---|---|
| Repository-aware chat | — | ✓ | ✓ | ✓ |
| View chat history | — | ✓ | ✓ | ✓ |

### Agentic Tasks

| Feature | Anonymous | Developer | Team Lead | Admin |
|---|---|---|---|---|
| Submit task (natural language) | — | ✓ | ✓ | ✓ |
| Approve agent plan | — | ✓ | ✓ | ✓ |
| Cancel / kill agent | — | ✓ | ✓ | ✓ |
| Approve GitHub push | — | ✓ | ✓ | ✓ |
| Merge PR | — | ✓ (via GitHub) | ✓ | ✓ |
| View agent activity timeline | — | ✓ | ✓ | ✓ |

### Agent Policy

| Feature | Anonymous | Developer | Team Lead | Admin |
|---|---|---|---|---|
| View project rules | — | ✓ | ✓ | ✓ |
| Modify project rules | — | — | TBD | ✓ |
| Override agent budget limits | — | — | TBD | ✓ |

### Memory & Analytics

| Feature | Anonymous | Developer | Team Lead | Admin |
|---|---|---|---|---|
| View project memory | — | ✓ | ✓ | ✓ |
| Edit memory entries | — | ✓ | ✓ | ✓ |
| Delete memory entries | — | ✓ | ✓ | ✓ |
| View agent analytics | — | — | ✓ | ✓ |
| View audit log | — | ✓ | ✓ | ✓ |

---

## Agent Permission Tiers (Internal)

The agent itself has permission tiers that vary by execution phase. These are enforced by the Policy Engine (Sukun), not by user roles.

| Agent Action | Permission Level |
|---|---|
| Read files, search code | Always allowed |
| Write files (in sandbox only) | Allowed during `EXECUTING` state |
| Run tests | Allowed during `TESTING` state |
| Git commit (in sandbox) | Allowed after tests pass |
| Git push to GitHub | Requires explicit human approval |
| Merge PR | Requires explicit human approval (done manually on GitHub) |
| Write to production | Always **DENIED** |

---

## Authentication Implementation Details

Based on [`backend/app/api/v1/auth.py`](file:///Users/meetvirugama/Desktop/AI-Powered-Software-Development-Platform/backend/app/api/v1/auth.py) and [`frontend/src/stores/useAuthStore.ts`](file:///Users/meetvirugama/Desktop/AI-Powered-Software-Development-Platform/frontend/src/stores/useAuthStore.ts):

- **Auth method:** GitHub OAuth 2.0 + JWT (HS256)
- **Token storage:** httpOnly cookie (set by backend, never read by frontend JS)
- **Frontend auth state:** Zustand `useAuthStore` — stores `user` object from `GET /auth/me`
- **`isAuthenticated`:** Derived from whether `user` is non-null (not from raw token)
- **Route protection:** `ProtectedRoute` component wraps all `/app/*` routes

> [!IMPORTANT]
> The auth API router exists as a stub only. GitHub OAuth endpoints are **not yet implemented**. The frontend has MSW mocks set up for development.
