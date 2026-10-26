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

### Core & Repository APIs (Week 1 — Live)

| Method | Endpoint | Feature | Auth Required | Status |
|---|---|---|---|---|
| GET | `/health` | Health Check | No | 🟢 Done |
| GET | `/api/v1/auth/github/login` | GitHub OAuth Login | No | 🟢 Done |
| GET | `/api/v1/auth/github/callback` | OAuth Callback | No | 🟢 Done |
| GET | `/api/v1/auth/me` | Current User Profile | Yes | 🟢 Done |
| POST | `/api/v1/auth/logout` | Logout & Blocklist JWT | Yes | 🟢 Done |
| GET | `/api/v1/github/repositories` | List Repositories via GitHub App | Yes | 🟢 Done |
| POST | `/api/v1/github/repositories/{id}/connect` | Connect Repository to Platform | Yes | 🟢 Done |
| GET | `/api/v1/repositories` | List Connected Repositories | Yes | 🟢 Done |
| GET | `/api/v1/repositories/{id}` | Repository Detail & Sync Status | Yes | 🟢 Done |
| POST | `/api/v1/repositories/{id}/sync` | Queue Repository Sync | Yes | 🟢 Done |
| POST | `/api/v1/repositories/{id}/search` | Hybrid Vector + Lexical Search | Yes | 🟢 Done |
| GET | `/api/v1/repositories/{id}/files` | List Indexed Files | Yes | 🟢 Done |
| GET | `/api/v1/repositories/{id}/symbols` | List Extracted AST Symbols | Yes | 🟢 Done |
| POST | `/api/v1/repositories/{id}/chat` | Grounded Repository Chat | Yes | 🟢 Done |

### Developer Intelligence Suite (Week 2 — Active)

| Method | Endpoint | Feature | Auth Required | Status |
|---|---|---|---|---|
| POST | `/api/v1/repositories/{id}/explain` | Code Explanation (file, symbol, range) | Yes | 🟢 Done (API Contract) |
| POST | `/api/v1/repositories/{id}/detect-bugs` | Dedicated Bug Detection (Static + AI) | Yes | 🟢 Done (API Contract) |
| POST | `/api/v1/repositories/{id}/generate-tests` | Framework-Aware Test File Generation | Yes | 🟢 Done (API Contract) |
| POST | `/api/v1/repositories/{id}/review` | Standalone AI Code Review (file, commit, PR) | Yes | 🟢 Done (API Contract) |
| GET | `/api/v1/repositories/{id}/analysis-runs` | List Historical Analysis Runs | Yes | 🟢 Done (API Contract) |
| GET | `/api/v1/analysis-runs/{run_id}` | Get Specific Analysis Run & Findings | Yes | 🟢 Done (API Contract) |

### Workflow Automation & GitHub Ecosystem (Week 3 — Upcoming)

| Method | Endpoint | Feature | Auth Required | Status |
|---|---|---|---|---|
| POST | `/api/v1/repositories/{id}/issues/import` | Import Issue into Task Workflow | Yes | ⚪ Todo |
| POST | `/api/v1/tasks` | Create Natural-Language Task | Yes | ⚪ Todo |
| GET | `/api/v1/tasks/{id}` | Get Task Status & Timeline | Yes | ⚪ Todo |
| POST | `/api/v1/tasks/{id}/plan` | Generate Structured Implementation Plan | Yes | ⚪ Todo |
| POST | `/api/v1/tasks/{id}/approve` | Human Approval Gate (Proceed to Execute) | Yes | ⚪ Todo |
| POST | `/api/v1/tasks/{id}/reject` | Reject Plan / Cancel Task | Yes | ⚪ Todo |
| POST | `/api/v1/tasks/{id}/execute` | Execute Plan in Isolated Workspace | Yes | ⚪ Todo |
| POST | `/api/v1/tasks/{id}/verify` | Run Independent Verification Checks | Yes | ⚪ Todo |
| POST | `/api/v1/tasks/{id}/create-pr` | Authorize Push & Create GitHub Draft PR | Yes | ⚪ Todo |


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

### POST `/api/v1/repositories/{repository_id}/explain`

**Purpose:** Explain a selected file, symbol, or 1-indexed inclusive line range using grounded repository context.

**Authentication:** Required

**Request Body (`ExplainCodeRequest`):**
```json
{
  "target": {
    "type": "range",
    "path": "backend/app/core/input_security.py",
    "start_line": 36,
    "end_line": 64,
    "symbol": "validate_repo_relative_path"
  },
  "options": {
    "include_context": true,
    "max_context_tokens": 10000,
    "persist_run": true
  }
}
```

**Response (`CodeExplanationResponse`):**
```json
{
  "run_id": "uuid",
  "repository_id": "uuid",
  "status": "COMPLETED",
  "target": {
    "type": "range",
    "path": "backend/app/core/input_security.py",
    "start_line": 36,
    "end_line": 64,
    "symbol": "validate_repo_relative_path",
    "revision": null
  },
  "revision": "main",
  "explanation": {
    "purpose": "Validates untrusted repository-relative file paths and blocks path traversal.",
    "logic_flow": [
      "Rejects empty, overly long, or control-character strings.",
      "Normalizes POSIX path segments and rejects '..' segments."
    ],
    "key_symbols": [
      {
        "name": "validate_repo_relative_path",
        "kind": "function",
        "role": "Primary path sanitizer",
        "start_line": 36,
        "end_line": 64
      }
    ],
    "inputs_and_outputs": "Takes `path: str`, returns normalized path string or raises `UnsafePathError`.",
    "dependencies": ["pathlib.PurePosixPath", "re"],
    "assumptions_and_limitations": ["Symlink escape checks require `resolve_within_root`."],
    "sources": [
      {
        "repository_id": null,
        "file_path": "backend/app/core/input_security.py",
        "start_line": 36,
        "end_line": 64,
        "revision": null,
        "symbol_name": "validate_repo_relative_path"
      }
    ],
    "confidence": "high",
    "missing_context": []
  },
  "created_at": "2026-10-17T12:00:00Z"
}
```

**Status Codes:**
| Code | Meaning |
|---|---|
| 200 | Structured explanation returned |
| 400 | Unsafe path or line range exceeds indexed file bounds (`INVALID_REQUEST`) |
| 401 | Not authenticated (`UNAUTHORIZED`) |
| 404 | Repository not owned/found (`REPOSITORY_NOT_FOUND`) or target file missing (`FILE_NOT_FOUND`) |
| 413 | Target file exceeds 1 MB limit (`PAYLOAD_TOO_LARGE`) |
| 422 | Request schema validation failed (`INVALID_REQUEST`) |
| 429 | Per-user rate limit exceeded (20 req/min, `RATE_LIMITED`) |
| 500 | AI output failed validation (`ANALYSIS_FAILED`) |
| 503 | Explanation service or LLM provider unavailable (`SERVICE_UNAVAILABLE`) |

**Implementation:** `backend/app/api/v1/analysis.py` — `explain_code()`

---

### POST `/api/v1/repositories/{repository_id}/detect-bugs`

**Purpose:** Identify potential defects using static analysis and AI reasoning with grounded source locations.

**Authentication:** Required

**Request Body (`BugDetectionRequest`):**
```json
{
  "target": {
    "type": "file",
    "path": "src/pagination.py"
  },
  "include_static": true,
  "include_ai": true,
  "min_severity": "LOW"
}
```

**Response (`BugDetectionResponse`):**
```json
{
  "run_id": "uuid",
  "repository_id": "uuid",
  "status": "COMPLETED",
  "target": {
    "type": "file",
    "path": "src/pagination.py",
    "start_line": null,
    "end_line": null,
    "symbol": null,
    "revision": null
  },
  "revision": "main",
  "findings": [
    {
      "id": "finding-1",
      "category": "off_by_one",
      "severity": "HIGH",
      "title": "Inclusive loop upper bound accesses index len(items)",
      "description": "Iterating up to len(items) inclusive causes IndexError on the final iteration.",
      "source_reference": {
        "repository_id": null,
        "file_path": "src/pagination.py",
        "start_line": 14,
        "end_line": 18,
        "revision": null,
        "symbol_name": "slice_page"
      },
      "evidence": "for idx in range(0, len(items) + 1): items[idx]",
      "suggested_fix": "Use range(0, len(items)) instead of len(items) + 1.",
      "confidence": "high",
      "is_uncertain": false,
      "source_type": "AI",
      "rule_id": null
    }
  ],
  "total_findings": 1,
  "static_findings_count": 0,
  "ai_findings_count": 1,
  "missing_context": [],
  "created_at": "2026-10-17T12:00:00Z"
}
```

**Implementation:** `backend/app/api/v1/analysis.py` — `detect_bugs()`

---

### POST `/api/v1/repositories/{repository_id}/generate-tests`

**Purpose:** Generate a complete, previewable test file matching the repository's supported test framework (`pytest`, `unittest`, or `jest`).

**Authentication:** Required

**Request Body (`TestGenerationRequest`):**
```json
{
  "target": {
    "type": "file",
    "path": "src/pagination.py"
  },
  "framework": "pytest"
}
```

**Response (`TestGenerationResponse`):**
```json
{
  "run_id": "uuid",
  "repository_id": "uuid",
  "status": "COMPLETED",
  "target": {
    "type": "file",
    "path": "src/pagination.py",
    "start_line": null,
    "end_line": null,
    "symbol": null,
    "revision": null
  },
  "revision": "main",
  "result": {
    "detected_framework": "pytest",
    "proposed_test_path": "backend/tests/test_pagination.py",
    "test_content": "def test_slice_page_empty():\\n    assert slice_page([], 1, 10) == []\\n",
    "covered_scenarios": [
      {
        "name": "test_slice_page_empty",
        "category": "edge_case",
        "description": "Verifies empty list returns empty page."
      }
    ],
    "assumptions_and_warnings": [],
    "syntax_valid": true,
    "validation_errors": [],
    "sources": [
      {
        "repository_id": null,
        "file_path": "src/pagination.py",
        "start_line": 1,
        "end_line": 25,
        "revision": null,
        "symbol_name": null
      }
    ]
  },
  "created_at": "2026-10-17T12:00:00Z"
}
```

**Implementation:** `backend/app/api/v1/analysis.py` — `generate_tests()`

---

### POST `/api/v1/repositories/{repository_id}/review`

**Purpose:** Run a standalone AI and static code review on a single file, commit SHA, GitHub PR number, or unified diff without starting an autonomous task.

**Authentication:** Required

**Request Body (`CodeReviewRequest`):**
```json
{
  "target": {
    "type": "commit",
    "commit_sha": "a1b2c3d4"
  },
  "include_static": true
}
```

**Response (`ReviewReportResponse`):**
```json
{
  "run_id": "uuid",
  "repository_id": "uuid",
  "status": "COMPLETED",
  "target": {
    "type": "commit",
    "path": null,
    "commit_sha": "a1b2c3d4",
    "pr_number": null,
    "diff": null,
    "base_revision": null,
    "head_revision": null
  },
  "report": {
    "summary": "Reviewed commit a1b2c3d4: 1 high-severity security issue identified.",
    "risk_level": "HIGH",
    "findings": [
      {
        "id": "rev-1",
        "category": "security",
        "severity": "HIGH",
        "title": "Unparameterized SQL string interpolation",
        "description": "User input is formatted directly into SQL query text.",
        "source_reference": {
          "repository_id": null,
          "file_path": "src/db.py",
          "start_line": 42,
          "end_line": 45,
          "revision": "a1b2c3d4",
          "symbol_name": null
        },
        "evidence": "conn.execute(f\"SELECT * FROM users WHERE login = '{login}'\")",
        "suggested_fix": "Use bound parameters (:login) with SQLAlchemy text().",
        "confidence": "high",
        "is_uncertain": false,
        "is_new_in_change": true,
        "source_type": "COMBINED",
        "rule_id": "B608"
      }
    ],
    "total_findings": 1,
    "category_counts": {
      "security": 1
    },
    "missing_context": []
  },
  "created_at": "2026-10-17T12:00:00Z"
}
```

**Implementation:** `backend/app/api/v1/analysis.py` — `review_code()`

---

### GET `/api/v1/repositories/{repository_id}/analysis-runs` & GET `/api/v1/analysis-runs/{run_id}`

**Purpose:** List and inspect persisted analysis runs and findings for repositories owned by the authenticated user.

**Authentication:** Required

**Query Parameters (`GET /api/v1/repositories/{repository_id}/analysis-runs`):**
| Param | Type | Default | Description |
|---|---|---|---|
| `feature_type` | string | `null` | Optional filter: `explain`, `detect_bugs`, `generate_tests`, `review` |
| `status` | string | `null` | Optional filter: `PENDING`, `RUNNING`, `COMPLETED`, `FAILED`, `CANCELLED` |
| `page` | integer | `1` | 1-indexed page number |
| `page_size` | integer | `20` | Items per page (max 100) |

**Implementation:** `backend/app/api/v1/analysis.py` — `list_analysis_runs()`, `get_analysis_run()`

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
| `FILE_NOT_FOUND` | 404 | Target file does not exist in the indexed repository |
| `ANALYSIS_RUN_NOT_FOUND` | 404 | Requested analysis run ID does not exist or is not accessible |
| `INVALID_REQUEST` | 400/422 | Unsafe file path, invalid line range, or schema validation failure |
| `PAYLOAD_TOO_LARGE` | 413 | Target file exceeds the 1 MB analysis limit |
| `ANALYSIS_FAILED` | 500 | AI output failed schema validation or analysis execution failed |

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
