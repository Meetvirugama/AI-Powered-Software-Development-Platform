# 08. API Documentation
> **Version:** 2.0 | **Created:** 2026-09-24 | **Last Updated:** 2026-09-28 | **Status:** Live

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
| GET | `/health` | Health Check | No | 🟢 Done |
| GET | `/api/v1/auth/github/login` | GitHub OAuth Login | No | 🟢 Done |
| GET | `/api/v1/auth/github/callback` | OAuth Callback | No | 🟢 Done |
| GET | `/api/v1/auth/me` | Current User | Yes | 🟢 Done |
| POST | `/api/v1/auth/logout` | Logout | Yes | 🟢 Done |
| GET | `/api/v1/repositories` | List Repositories | Yes | 🟢 Done |
| GET | `/api/v1/repositories/{id}` | Repository Detail | Yes | 🟢 Done |
| POST | `/api/v1/repositories/{id}/sync` | Queue Sync | Yes | 🟢 Done |
| POST | `/api/v1/repositories/{id}/search` | Hybrid Code Search | Yes | 🟢 Done |
| GET | `/api/v1/repositories/{id}/files` | List Indexed Files | Yes | 🟢 Done |
| GET | `/api/v1/repositories/{id}/symbols` | List Extracted Symbols | Yes | 🟢 Done |
| POST | `/api/v1/repositories/{id}/chat` | Repository Chat | Yes | 🟢 Done |

---

## Endpoint Specifications

---

### GET `/health`

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

**Status Codes:**
| Code | Meaning |
|---|---|
| 200 | API is available |

**Notes:** Does NOT require database connectivity. Intentional — allows health checking even if DB is down.

**Implementation:** `backend/app/api/v1/health.py`

---

### GET `/api/v1/auth/github/login`

**Purpose:** Initiate GitHub OAuth login. Generates CSRF state token and redirects browser to GitHub OAuth page.

**Authentication:** Not required

**Request:** None

**Response:** HTTP 307 redirect to `https://github.com/login/oauth/authorize?...`

Side effect: Sets `oauth_state` httpOnly cookie (TTL 600s) for CSRF validation.

**Status Codes:**
| Code | Meaning |
|---|---|
| 307 | Redirect to GitHub OAuth |
| 500 | GitHub OAuth not configured (missing `GITHUB_CLIENT_ID`) |

**Implementation:** `backend/app/api/v1/auth.py` — `github_login()`

---

### GET `/api/v1/auth/github/callback`

**Purpose:** Handle GitHub OAuth callback. Exchange authorization code for access token, upsert user record, issue JWT cookie.

**Authentication:** Not required

**Query Parameters:**
| Param | Type | Required | Description |
|---|---|---|---|
| `code` | string | Yes | OAuth authorization code from GitHub |
| `state` | string | Yes | CSRF state parameter |

**Response:**
```json
{
  "access_token": "eyJ...",
  "expires_in": 3600,
  "user": {
    "id": "uuid",
    "login": "github-username",
    "email": "user@example.com",
    "avatar_url": "https://avatars.githubusercontent.com/..."
  }
}
```

Side effect: Sets JWT as httpOnly `session` cookie. Clears `oauth_state` cookie.

**Status Codes:**
| Code | Meaning |
|---|---|
| 200 | JWT issued, user upserted |
| 400 | CSRF state invalid or expired |
| 401 | GitHub rejected the authorization code |
| 502 | GitHub returned incomplete user profile |
| 503 | GitHub OAuth unavailable |

**Implementation:** `backend/app/api/v1/auth.py` — `github_callback()`

---

### GET `/api/v1/auth/me`

**Purpose:** Return the currently authenticated user.

**Authentication:** Required (httpOnly JWT cookie)

**Request:** None (auth via cookie)

**Response:**
```json
{
  "id": "uuid",
  "login": "github-username",
  "email": "user@example.com",
  "avatar_url": "https://avatars.githubusercontent.com/..."
}
```

**Status Codes:**
| Code | Meaning |
|---|---|
| 200 | User object returned |
| 401 | Not authenticated or user no longer exists |

**Implementation:** `backend/app/api/v1/auth.py` — `get_current_user()`

---

### POST `/api/v1/auth/logout`

**Purpose:** Invalidate the current session. Adds JWT ID to Redis blocklist with TTL equal to remaining token lifetime.

**Authentication:** Required

**Request:** None

**Response:** 204 No Content (cookie cleared)

**Status Codes:**
| Code | Meaning |
|---|---|
| 204 | Session invalidated, cookie cleared |
| 401 | Not authenticated |
| 503 | Redis unavailable |

**Implementation:** `backend/app/api/v1/auth.py` — `logout()`

---

### GET `/api/v1/repositories`

**Purpose:** List all repositories owned by the authenticated user.

**Authentication:** Required

**Response:**
```json
[
  {
    "id": "uuid",
    "github_repo_id": "123456789",
    "owner": "github-username",
    "name": "my-repo",
    "full_name": "github-username/my-repo",
    "default_branch": "main",
    "language": "Python",
    "sync_status": "SYNCED",
    "last_synced_at": "2026-09-28T12:00:00Z"
  }
]
```

**Status Codes:**
| Code | Meaning |
|---|---|
| 200 | List returned (empty list if none) |
| 401 | Not authenticated |

**Implementation:** `backend/app/api/v1/repositories.py` — `list_repositories()`

---

### GET `/api/v1/repositories/{repository_id}`

**Purpose:** Get detailed metadata and sync status for a specific repository.

**Authentication:** Required

**Path Parameters:**
| Param | Type | Description |
|---|---|---|
| `repository_id` | UUID | Repository internal ID |

**Response:**
```json
{
  "id": "uuid",
  "github_repo_id": "123456789",
  "owner": "github-username",
  "name": "my-repo",
  "full_name": "github-username/my-repo",
  "default_branch": "main",
  "language": "Python",
  "sync_status": "SYNCED",
  "last_synced_at": "2026-09-28T12:00:00Z"
}
```

**Status Codes:**
| Code | Meaning |
|---|---|
| 200 | Repository returned |
| 401 | Not authenticated |
| 403 | Repository exists but belongs to another user |
| 404 | Repository not found |

**Implementation:** `backend/app/api/v1/repositories.py` — `get_repository()`

---

### POST `/api/v1/repositories/{repository_id}/sync`

**Purpose:** Queue a repository synchronization job.

**Authentication:** Required

**Response:**
```json
{
  "job_id": "uuid"
}
```

**Status Codes:**
| Code | Meaning |
|---|---|
| 202 | Sync job queued |
| 401 | Not authenticated |
| 403 | Access denied |
| 404 | Repository not found |

**Implementation:** `backend/app/api/v1/repositories.py` — `sync_repository()`

---

### POST `/api/v1/repositories/{repository_id}/search`

**Purpose:** Hybrid code search (vector + lexical) via the RAG retrieval pipeline.

**Authentication:** Required

**Request Body:**
```json
{
  "query": "where is authentication implemented?",
  "top_k": 10
}
```

**Response:**
```json
{
  "query": "where is authentication implemented?",
  "results": [
    {
      "id": "uuid",
      "file_path": "backend/app/core/auth.py",
      "start_line": 1,
      "end_line": 50,
      "content": "class JWTMiddleware...",
      "score": 0.94
    }
  ]
}
```

**Status Codes:**
| Code | Meaning |
|---|---|
| 200 | Search results returned |
| 401 | Not authenticated |
| 403 | Access denied |
| 404 | Repository not found |
| 503 | RAG pipeline not configured |

**Implementation:** `backend/app/api/v1/repositories.py` — `search_repository()`

---

### GET `/api/v1/repositories/{repository_id}/files`

**Purpose:** List all indexed files in a repository (paginated).

**Authentication:** Required

**Query Parameters:**
| Param | Type | Default | Description |
|---|---|---|---|
| `page` | integer | 1 | Page number (1-indexed) |
| `page_size` | integer | 50 | Items per page (max 100) |

**Response:**
```json
{
  "page": 1,
  "page_size": 50,
  "total": 142,
  "items": [
    {
      "id": "uuid",
      "path": "backend/app/core/auth.py",
      "language": "Python",
      "size_bytes": 6944,
      "line_count": 171,
      "content_hash": "sha256...",
      "last_indexed_at": "2026-09-28T12:00:00Z"
    }
  ]
}
```

**Status Codes:**
| Code | Meaning |
|---|---|
| 200 | File list returned |
| 401 | Not authenticated |
| 403 | Access denied |
| 404 | Repository not found |

**Implementation:** `backend/app/api/v1/repositories.py` — `list_files()`

---

### GET `/api/v1/repositories/{repository_id}/symbols`

**Purpose:** List all extracted code symbols (functions, classes, etc.) in a repository (paginated).

**Authentication:** Required

**Query Parameters:**
| Param | Type | Default | Description |
|---|---|---|---|
| `page` | integer | 1 | Page number (1-indexed) |
| `page_size` | integer | 50 | Items per page (max 100) |

**Response:**
```json
{
  "page": 1,
  "page_size": 50,
  "total": 1024,
  "items": [
    {
      "id": "uuid",
      "file_id": "uuid",
      "name": "JWTMiddleware",
      "kind": "class",
      "start_line": 1,
      "end_line": 50,
      "signature": "class JWTMiddleware:",
      "parent_id": null
    }
  ]
}
```

**Status Codes:**
| Code | Meaning |
|---|---|
| 200 | Symbol list returned |
| 401 | Not authenticated |
| 403 | Access denied |
| 404 | Repository not found |

**Implementation:** `backend/app/api/v1/repositories.py` — `list_symbols()`

---

### POST `/api/v1/repositories/{repository_id}/chat`

**Purpose:** Send a question about a repository and receive a grounded answer with file + line sources.

**Authentication:** Required

**Path Parameters:**
| Param | Type | Description |
|---|---|---|
| `repository_id` | UUID | Repository to query against |

**Request Body:**
```json
{
  "question": "Where is authentication implemented?",
  "history": [
    { "role": "user", "content": "previous question" },
    { "role": "assistant", "content": "previous answer" }
  ]
}
```

**Response:**
```json
{
  "answer": "Authentication is handled in backend/app/core/auth.py via the JWTMiddleware class...",
  "sources": [
    {
      "file": "backend/app/core/auth.py",
      "start_line": 1,
      "end_line": 50,
      "symbol": "JWTMiddleware"
    }
  ],
  "confidence": "high"
}
```

**Response Schema:** `backend/ai/schemas/output.py` — `RepositoryAnswer`

**Status Codes:**
| Code | Meaning |
|---|---|
| 200 | Answer returned |
| 400 | Invalid request body |
| 401 | Not authenticated |
| 403 | Access denied |
| 404 | Repository not found |
| 503 | LLM unavailable or RAG pipeline not configured |

**Internal Flow:**
```
Chat API → RAGPipeline.chat()
  → HybridRetriever.retrieve() (vector + lexical)
  → RRFFusion.fuse()
  → CrossEncoderReranker.rerank()
  → ContextBuilder.build()
  → PromptBuilder.build_chat_prompt()
  → LLMGateway.generate() [+ JSON repair loop]
  → GroundingValidator.validate_sources()
  → RepositoryAnswer
```

**Error Codes:**
| Code | Description | Retryable |
|---|---|---|
| `SERVICE_UNAVAILABLE` | LLM timeout or RAG pipeline not configured | Yes |
| `INTERNAL_SERVER_ERROR` | JSON repair loop exhausted | No |
| `REPOSITORY_NOT_FOUND` | Repository not found or not owned by caller | No |

**Implementation:** `backend/app/api/v1/chat.py` — `chat_with_repository()`

---

## Standard Error Format

All error responses follow this envelope:

```json
{
  "error": {
    "code": "MACHINE_READABLE_CODE",
    "message": "Human-readable description.",
    "retryable": false
  }
}
```

**Error Codes:**
| Code | HTTP | Description |
|---|---|---|
| `UNAUTHORIZED` | 401 | Not authenticated or token invalid |
| `FORBIDDEN` | 403 | Authenticated but lacks permission |
| `REPOSITORY_NOT_FOUND` | 404 | Repository does not exist |
| `OAUTH_STATE_INVALID` | 400 | CSRF state mismatch or expired |
| `OAUTH_EXCHANGE_FAILED` | 401/502 | GitHub rejected authorization code |
| `GITHUB_PROFILE_FAILED` | 502 | GitHub returned incomplete user profile |
| `SERVICE_UNAVAILABLE` | 503 | LLM, Redis, or external service down |
| `INTERNAL_SERVER_ERROR` | 500 | Unrecoverable server error |

---

## Authentication Strategy

| Aspect | Implementation |
|---|---|
| Method | GitHub OAuth 2.0 → JWT |
| JWT Algorithm | Configured via `JWT_ALGORITHM` env var |
| JWT Secret | `JWT_SECRET` env var (required, never committed) |
| Token storage | httpOnly cookie (set by backend on callback) |
| Frontend access | Cookie sent automatically via `withCredentials: true` |
| Session invalidation | JWT JTI added to Redis blocklist on logout with remaining TTL |
| Route protection | `JWTMiddleware` validates all non-auth routes |
| CSRF protection | `oauth_state` cookie + `secrets.compare_digest` during OAuth callback |

---

## Frontend API Client

**Location:** `frontend/src/services/` (planned by Dhramraj)

**Config:**
- Base URL from environment variable
- Auth token injection (cookie-based, `withCredentials: true`)
- Error parsing into standard `ApiError` type
- Using Axios
