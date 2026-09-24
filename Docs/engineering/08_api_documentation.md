# 08. API Documentation
> **Version:** 1.0 | **Created:** 2026-09-24 | **Last Updated:** 2026-09-24 | **Status:** Draft

---

## API Overview

- **Base URL (local):** `http://127.0.0.1:8000`
- **API Prefix:** `/api/v1`
- **Interactive Docs:** `http://127.0.0.1:8000/docs`
- **OpenAPI JSON:** `http://127.0.0.1:8000/openapi.json`
- **ReDoc:** `http://127.0.0.1:8000/redoc`

---

## API Inventory

| Method | Endpoint | Feature | Auth Required | Status |
|---|---|---|---|---|
| GET | `/api/v1/health` | Health Check | No | 🟢 Done |
| GET | `/api/v1/auth/github/login` | GitHub OAuth | No | ⚪ Stub |
| GET | `/api/v1/auth/github/callback` | OAuth Callback | No | ⚪ Stub |
| GET | `/api/v1/auth/me` | Current User | Yes | ⚪ Stub |
| POST | `/api/v1/auth/logout` | Logout | Yes | ⚪ Stub |
| POST | `/api/v1/auth/github/installation` | GitHub App Install | Yes | ⚪ Stub |
| GET | `/api/v1/repositories` | List Repositories | Yes | ⚪ Stub |
| GET | `/api/v1/repositories/{id}` | Repository Detail | Yes | ⚪ Stub |
| POST | `/api/v1/repositories/{id}/sync` | Trigger Sync | Yes | ⚪ Todo |
| POST | `/api/v1/chat` | Repository Chat | Yes | ⚪ Todo |

---

## Endpoint Specifications

---

### GET `/api/v1/health`

**Purpose:** Check API availability. Used by Docker healthchecks, CI, and monitoring.

**Authentication:** Not required

**Request:** None

**Response:**
```json
{
  "status": "ok",
  "version": "1.0.0"
}
```

**Response Schema:** [`HealthResponse`](file:///Users/meetvirugama/Desktop/AI-Powered-Software-Development-Platform/backend/app/schemas/health.py)
```python
class HealthResponse(BaseModel):
    status: str = "ok"
    version: str = "1.0.0"
```

**Status Codes:**
| Code | Meaning |
|---|---|
| 200 | API is available |

**Notes:** Does NOT require database connectivity. Intentional — allows health checking even if DB is down.

**Implementation:** [`backend/app/api/v1/health.py`](file:///Users/meetvirugama/Desktop/AI-Powered-Software-Development-Platform/backend/app/api/v1/health.py)

---

### GET `/api/v1/auth/github/login`

**Purpose:** Initiate GitHub OAuth login. Redirects the browser to GitHub's OAuth page.

**Authentication:** Not required

**Request:** None

**Response:** HTTP 302 redirect to `https://github.com/login/oauth/authorize?...`

**Status Codes:**
| Code | Meaning |
|---|---|
| 302 | Redirect to GitHub OAuth |

**Status:** ⚪ Stub — router exists, handler not implemented (Yug Day 2)

**Implementation:** [`backend/app/api/v1/auth.py`](file:///Users/meetvirugama/Desktop/AI-Powered-Software-Development-Platform/backend/app/api/v1/auth.py)

---

### GET `/api/v1/auth/github/callback`

**Purpose:** Handle GitHub OAuth callback. Exchange code for access token, create/update user, set JWT cookie.

**Authentication:** Not required

**Query Parameters:**
| Param | Type | Required | Description |
|---|---|---|---|
| `code` | string | Yes | OAuth authorization code from GitHub |
| `state` | string | No | CSRF state parameter |

**Response:** HTTP 302 redirect to `/app/dashboard` with httpOnly JWT cookie set

**Status Codes:**
| Code | Meaning |
|---|---|
| 302 | Success — redirected to dashboard |
| 400 | Invalid or missing code |
| 500 | GitHub API error |

**Status:** ⚪ Stub

---

### GET `/api/v1/auth/me`

**Purpose:** Return the currently authenticated user.

**Authentication:** Required (httpOnly cookie with JWT)

**Request:** None (auth via cookie)

**Response:**
```json
{
  "id": "uuid",
  "github_id": "12345",
  "login": "username",
  "email": "user@example.com",
  "avatar_url": "https://avatars.githubusercontent.com/..."
}
```

**Status Codes:**
| Code | Meaning |
|---|---|
| 200 | User object returned |
| 401 | Not authenticated |

**Frontend Dependency:** Used by `useAuthStore` to populate `user` on app load.
**Status:** ⚪ Stub

---

### POST `/api/v1/auth/logout`

**Purpose:** Invalidate the current session. Adds JWT to Redis blocklist.

**Authentication:** Required

**Request:** None

**Response:**
```json
{ "status": "ok" }
```

**Status Codes:**
| Code | Meaning |
|---|---|
| 200 | Session invalidated |
| 401 | Not authenticated |

**Status:** ⚪ Stub

---

### POST `/api/v1/auth/github/installation`

**Purpose:** Store a GitHub App installation after the user installs the App on their GitHub account.

**Authentication:** Required

**Request Body:**
```json
{
  "installation_id": "12345678"
}
```

**Response:**
```json
{
  "id": "uuid",
  "installation_id": "12345678",
  "account_login": "username"
}
```

**Status Codes:**
| Code | Meaning |
|---|---|
| 201 | Installation stored |
| 400 | Invalid installation_id |
| 401 | Not authenticated |

**Status:** ⚪ Stub

---

### GET `/api/v1/repositories`

**Purpose:** List all repositories the authenticated user has installed the GitHub App on.

**Authentication:** Required

**Query Parameters:**
| Param | Type | Required | Description |
|---|---|---|---|
| `page` | integer | No | Pagination (TBD) |
| `per_page` | integer | No | Items per page (TBD) |

**Response:**
```json
[
  {
    "id": "uuid",
    "owner": "username",
    "name": "my-repo",
    "default_branch": "main",
    "language": "Python",
    "sync_status": "SYNCED",
    "last_synced_at": "2026-09-24T12:00:00Z"
  }
]
```

**Status Codes:**
| Code | Meaning |
|---|---|
| 200 | List returned |
| 401 | Not authenticated |

**Status:** ⚪ Stub — router exists

**Implementation:** [`backend/app/api/v1/repositories.py`](file:///Users/meetvirugama/Desktop/AI-Powered-Software-Development-Platform/backend/app/api/v1/repositories.py)

---

### GET `/api/v1/repositories/{id}`

**Purpose:** Get detailed metadata and sync status for a specific repository.

**Authentication:** Required

**Path Parameters:**
| Param | Type | Description |
|---|---|---|
| `id` | UUID | Repository internal ID |

**Response:**
```json
{
  "id": "uuid",
  "owner": "username",
  "name": "my-repo",
  "default_branch": "main",
  "language": "Python",
  "sync_status": "SYNCED",
  "last_synced_at": "2026-09-24T12:00:00Z",
  "file_count": 142,
  "symbol_count": 1024
}
```

**Status Codes:**
| Code | Meaning |
|---|---|
| 200 | Repository returned |
| 401 | Not authenticated |
| 403 | Access denied (not your repository) |
| 404 | Repository not found |

**Status:** ⚪ Stub

---

### POST `/api/v1/chat` *(Planned — Week 1 Day 7)*

**Purpose:** Send a question about a repository and receive a grounded answer with file + line sources.

**Authentication:** Required

**Request Body:**
```json
{
  "question": "Where is authentication implemented?",
  "repository_id": "uuid",
  "history": [
    { "role": "user", "content": "previous question" },
    { "role": "assistant", "content": "previous answer" }
  ]
}
```

**Response:**
```json
{
  "answer": "Authentication is handled in src/auth/service.py...",
  "sources": [
    {
      "file": "src/auth/service.py",
      "start_line": 20,
      "end_line": 48,
      "symbol": "AuthService"
    }
  ],
  "confidence": "high"
}
```

**Response Schema:** [`RepositoryAnswer`](file:///Users/meetvirugama/Desktop/AI-Powered-Software-Development-Platform/backend/ai/schemas/output.py)

**Status Codes:**
| Code | Meaning |
|---|---|
| 200 | Answer returned |
| 400 | Invalid request |
| 401 | Not authenticated |
| 404 | Repository not found or not indexed |
| 503 | LLM unavailable |

**Error Response Schema:** [`ErrorResponse`](file:///Users/meetvirugama/Desktop/AI-Powered-Software-Development-Platform/backend/ai/schemas/output.py)
```json
{
  "code": "LLM_TIMEOUT",
  "message": "The AI service timed out. Please try again.",
  "retryable": true
}
```

**Error Codes:**
| Code | Description | Retryable |
|---|---|---|
| `RETRIEVAL_EMPTY` | No chunks found for this repository | No |
| `LLM_TIMEOUT` | LLM request timed out | Yes |
| `LLM_RATE_LIMIT` | OpenAI rate limit reached | Yes |
| `LLM_UNAVAILABLE` | OpenAI API unreachable | Yes |
| `REPOSITORY_NOT_FOUND` | Repository not indexed | No |

**Internal Flow:** Chat API → EmbeddingService → VectorRetriever + LexicalRetriever → RRFFusion → CrossEncoderReranker → ContextBuilder → PromptBuilder → LLMGateway → OutputValidator → GroundingValidator → Response

**Status:** ⚪ Todo — router stub exists at [`backend/app/api/v1/chat.py`](file:///Users/meetvirugama/Desktop/AI-Powered-Software-Development-Platform/backend/app/api/v1/chat.py)

---

## Standard Error Format

All error responses follow this envelope (from `project_idea.md` and `ai/schemas/output.py`):

```json
{
  "error": {
    "code": "MACHINE_READABLE_CODE",
    "message": "Human-readable description.",
    "retryable": false
  }
}
```

> [!NOTE]
> The standard error handler is documented in the design but not yet implemented in `backend/app/core/`. Yug implements this on Day 2.

---

## Authentication Strategy

| Aspect | Implementation |
|---|---|
| Method | GitHub OAuth 2.0 → JWT |
| JWT Algorithm | HS256 (configurable via `JWT_ALGORITHM` env var) |
| JWT Secret | `JWT_SECRET` env var (required, never committed) |
| Token storage | httpOnly cookie (set by backend) |
| Frontend access | Cookie sent automatically via `withCredentials: true` |
| Session invalidation | JWT ID added to Redis blocklist on logout |
| Route protection | `JWTMiddleware` validates `Authorization: Bearer` on non-auth routes |

---

## Frontend API Client

**Location:** TBD — `frontend/src/services/` (planned by Dhramraj)

**Config:**
- Base URL from environment variable
- Auth token injection (cookie-based, `withCredentials: true`)
- Error parsing into standard `ApiError` type
- Using Axios
