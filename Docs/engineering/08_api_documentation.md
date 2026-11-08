# 08. API Documentation
> **Version:** 4.0 | **Created:** 2026-09-24 | **Last Updated:** 2026-11-08 | **Status:** Live & Production Ready

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
| POST | `/api/v1/auth/dev-login` | Local Developer Token Issuance | No | 🟢 Done |
| GET | `/api/v1/auth/me` | Current User Profile | Yes | 🟢 Done |
| POST | `/api/v1/auth/logout` | Logout & Blocklist JWT | Yes | 🟢 Done |
| GET | `/api/v1/github/repositories` | List Repositories via GitHub App | Yes | 🟢 Done |
| POST | `/api/v1/github/repositories/{id}/connect` | Connect Repository to Platform | Yes | 🟢 Done |
| GET | `/api/v1/repositories` | List Connected Repositories | Yes | 🟢 Done |
| GET | `/api/v1/repositories/{id}` | Repository Detail & Sync Status | Yes | 🟢 Done |
| POST | `/api/v1/repositories/{id}/sync` | Queue Repository Sync | Yes | 🟢 Done |
| POST | `/api/v1/repositories/{id}/search` | Hybrid Vector + Lexical Search (POST JSON) | Yes | 🟢 Done |
| GET | `/api/v1/repositories/{id}/search` | Hybrid Vector + Lexical Search (GET query params) | Yes | 🟢 Done |
| GET | `/api/v1/repositories/{id}/files` | List Indexed Files | Yes | 🟢 Done |
| GET | `/api/v1/repositories/{id}/symbols` | List Extracted AST Symbols | Yes | 🟢 Done |
| POST | `/api/v1/repositories/{id}/chat` | Grounded Repository Chat (Dual-Mode: Normal & Bounded Agentic) | Yes | 🟢 Done |

### Developer Intelligence Suite (Week 2 — Active)

| Method | Endpoint | Feature | Auth Required | Status |
|---|---|---|---|---|
| POST | `/api/v1/repositories/{id}/explain` | Code Explanation (file, symbol, range) | Yes | 🟢 Done |
| POST | `/api/v1/repositories/{id}/detect-bugs` | Dedicated Bug Detection (Static + AI) | Yes | 🟢 Done |
| POST | `/api/v1/repositories/{id}/generate-tests` | Framework-Aware Test File Generation | Yes | 🟢 Done |
| POST | `/api/v1/repositories/{id}/review` | Standalone AI Code Review (file, commit, PR) | Yes | 🟢 Done |
| GET | `/api/v1/repositories/{id}/analysis-runs` | List Historical Analysis Runs (with `user_id` filter) | Yes | 🟢 Done |
| GET | `/api/v1/repositories/{id}/analysis-runs/summary` | Analysis Run Summary, DB Integrity & Retention Metrics | Yes | 🟢 Done |
| GET | `/api/v1/analysis-runs/{run_id}` | Get Specific Analysis Run & Findings | Yes | 🟢 Done |

### Workflow Automation & GitHub Ecosystem (Week 3 — Implemented & Verified)

| Method | Endpoint | Feature | Auth Required | Status |
|---|---|---|---|---|
| POST | `/api/v1/repositories/{id}/issues/import` | Import Issue into Task Workflow | Yes | 🟢 Done (Implemented & Verified) |
| POST | `/api/v1/tasks` | Create Natural-Language Task | Yes | 🟢 Done (Implemented & Verified) |
| GET | `/api/v1/tasks/{id}` | Get Task Status & Timeline | Yes | 🟢 Done (Implemented & Verified) |
| POST | `/api/v1/tasks/{id}/plan` | Generate Structured Implementation Plan | Yes | 🟢 Done (Implemented & Verified) |
| POST | `/api/v1/tasks/{id}/approve` | Human Approval Gate (Proceed to Execute) | Yes | 🟢 Done (Implemented & Verified) |
| POST | `/api/v1/tasks/{id}/reject` | Reject Plan / Cancel Task | Yes | 🟢 Done (Implemented & Verified) |
| POST | `/api/v1/tasks/{id}/execute` | Execute Plan in Isolated Workspace | Yes | 🟢 Done (Implemented & Verified) |
| POST | `/api/v1/tasks/{id}/tests` | Execute Tests in Isolated Workspace | Yes | 🟢 Done (Implemented & Verified) |
| POST | `/api/v1/tasks/{id}/repair` | Bounded Repair Loop (max 3 attempts) | Yes | 🟢 Done (Implemented & Verified) |
| POST | `/api/v1/tasks/{id}/verify` | Run Independent Verification Checks | Yes | 🟢 Done (Implemented & Verified) |
| POST | `/api/v1/tasks/{id}/create-pr` | Authorize Push & Create GitHub Draft PR | Yes | 🟢 Done (Implemented & Verified) |
| GET | `/api/v1/tasks/{id}/events` | Task Event Log & Audit Trail | Yes | 🟢 Done (Implemented & Verified) |
| GET | `/api/v1/tasks/{id}/stream` | Real-Time SSE Status & Execution Stream | Yes | 🟢 Done (Implemented & Verified) |
| GET | `/api/v1/events/stream` | Server-Sent Events (SSE) Real-Time Stream | Yes | 🟢 Done (Implemented & Verified) |

### Enterprise Hardening & Durable Webhooks (Post-Week 3 — Live)

| Method | Endpoint | Feature | Auth Required | Status |
|---|---|---|---|---|
| POST | `/api/v1/github/webhook` | GitHub App Webhook Ingestion & Durable State Machine | HMAC (X-Hub-Signature-256) | 🟢 Done |
| GET | `/api/v1/github/events` | List Persisted Webhook Events (filter by type, status, pagination) | Yes | 🟢 Done |
| GET | `/api/v1/github/events/{event_id}` | Detailed Status & Payload of Webhook Event | Yes | 🟢 Done |
| POST | `/api/v1/github/events/{event_id}/replay` | Replay Failed or Dead-Letter Webhook Event | Yes | 🟢 Done |
| GET | `/api/v1/github/repositories/{github_repo_id}/automation` | Get Repository Automation Settings | Yes | 🟢 Done |
| PATCH | `/api/v1/github/repositories/{github_repo_id}/automation` | Update Repository Automation Settings (push-sync, PR review, drafts) | Yes | 🟢 Done |


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

**Purpose:** Send a question about a repository and receive a grounded answer with file + line sources. Supports two modes: standard RAG (`normal`) and multi-round tool-augmented repository exploration (`agentic`).

**Authentication:** Required

**Path Parameters:**
| Param | Type | Description |
|---|---|---|
| `repository_id` | UUID | Repository to query against |

**Request Body:**
```json
{
  "question": "Where is authentication implemented and how does it validate JWTs?",
  "history": [
    { "role": "user", "content": "previous question" },
    { "role": "assistant", "content": "previous answer" }
  ],
  "mode": "agentic"
}
```
*Note: `mode` defaults to `"normal"` if omitted.*

**Response (Normal Mode):**
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
  "confidence": "high",
  "agent_metadata": null
}
```

**Response (Agentic Mode):**
```json
{
  "answer": "Authentication uses timing-safe HMAC verification in `backend/app/core/security.py`...",
  "sources": [
    {
      "file": "backend/app/core/security.py",
      "start_line": 15,
      "end_line": 65,
      "symbol": "verify_token"
    }
  ],
  "confidence": "high",
  "agent_metadata": {
    "mode": "agentic",
    "tool_calls_count": 3,
    "tools_invoked": ["search_code", "read_file_range"],
    "token_usage": {
      "prompt_tokens": 1420,
      "completion_tokens": 310,
      "total_tokens": 1730
    },
    "execution_time_ms": 1150,
    "tool_details": [
      {
        "tool": "search_code",
        "arguments": { "query": "verify_token" },
        "status": "success",
        "result_count": 2
      },
      {
        "tool": "read_file_range",
        "arguments": { "path": "backend/app/core/security.py", "start_line": 15, "end_line": 65 },
        "status": "success",
        "result_count": 1
      }
    ],
    "truncated": false
  }
}
```

**Response Schema:** `backend/ai/schemas/output.py` — `RepositoryAnswer`

**Status Codes:**
| Code | Meaning |
|---|---|
| 200 | Answer returned |
| 400 | Invalid request body or agentic chat disabled in configuration |
| 401 | Not authenticated |
| 403 | Access denied |
| 404 | Repository not found |
| 503 | LLM unavailable or RAG pipeline/agent orchestrator not configured |

**Internal Flow:**
- **Normal Mode:**
  ```
  Chat API → RAGPipeline.chat()
    → HybridRetriever.retrieve() (vector + code_search_text lexical FTS)
    → RRFFusion.fuse()
    → CrossEncoderReranker.rerank()
    → ContextBuilder.build()
    → PromptBuilder.build_chat_prompt()
    → LLMGateway.generate() [+ JSON repair loop]
    → GroundingValidator.validate_sources()
    → RepositoryAnswer
  ```
- **Agentic Mode:**
  ```
  Chat API → AgentOrchestrator.run()
    → BudgetManager check (tokens <= 8,000, rounds <= 5, timeout <= 30s)
    → Normalized LLM Tool Loop (Gemini / Groq)
    → ToolRegistry execution (search_code, read_file_range, find_symbol, list_directory)
    → ExecutionPolicy sandbox checks (read-only enforcement, path traversal defense)
    → Synthesize answer + format agent_metadata
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

**Purpose:** Generate a complete, execution-verified test file matching the repository's supported test framework (`pytest`, `unittest`, `jest`, or `vitest`) with 3-run stability validation and runtime coverage attribution.

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
    "test_content": "def test_slice_page_empty():\n    assert slice_page([], 1, 10) == []\n",
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
    "verification_status": "VERIFIED",
    "verification_reasons": [
      "Static validation passed, 3/3 stability runs passed, and coverage gained."
    ],
    "stability_report": {
      "total_runs": 3,
      "passed_runs": 3,
      "classification": "STABLE",
      "is_stable": true,
      "runs": [
        {"run_number": 1, "passed": true, "duration_seconds": 0.05, "exit_code": 0},
        {"run_number": 2, "passed": true, "duration_seconds": 0.04, "exit_code": 0},
        {"run_number": 3, "passed": true, "duration_seconds": 0.05, "exit_code": 0}
      ]
    },
    "coverage_report": {
      "baseline_line_coverage": 40.0,
      "final_line_coverage": 75.0,
      "line_coverage_gain": 35.0,
      "newly_covered_lines": [12, 14, 15],
      "coverage_attributable_to_generated_tests": true,
      "collection_status": "SUCCESS"
    },
    "iteration_report": {
      "total_rounds": 1,
      "stopping_reason": "Initial generation complete",
      "final_coverage_achieved": 75.0
    },
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
| `user_id` | UUID | `null` | Optional filter to scope history runs by author UUID |
| `page_size` | integer | `20` | Items per page (max 100) |

**Implementation:** `backend/app/api/v1/analysis.py` — `list_analysis_runs()`, `get_analysis_run()`

---

## Task & Autonomous Execution Endpoints (Week 3)

### POST `/api/v1/tasks`
**Purpose:** Create a natural-language task bound to a repository and tenant.
**Authentication:** Required (Bearer JWT or httpOnly cookie)
**Request Body:**
```json
{
  "repository_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
  "title": "Fix SQL injection in authentication query",
  "description": "Parameterize raw SQL queries in user authentication module",
  "source": {
    "type": "USER_PROMPT",
    "base_revision": "abcdef012345"
  },
  "requirements": [
    {
      "id": "req-1",
      "description": "Parameterize raw queries",
      "category": "security",
      "target_files": ["backend/auth.py"],
      "acceptance_criteria": ["Sanitize SQL input"]
    }
  ],
  "base_revision": "abcdef012345"
}
```
**Response (201 Created):**
```json
{
  "task_id": "d3b07384-d113-4600-a548-3a7b9ef25bf8",
  "repository_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
  "title": "Fix SQL injection in authentication query",
  "status": "CREATED",
  "plan_version": null,
  "created_at": "2026-11-04T00:00:00Z"
}
```

---

### POST `/api/v1/tasks/{task_id}/plan`
**Purpose:** Generate or regenerate structured task plan. Re-planning an already approved task strictly resets status to `PENDING_APPROVAL` and clears `approved_plan_version`.
**Authentication:** Required
**Response (200 OK):**
```json
{
  "task_id": "d3b07384-d113-4600-a548-3a7b9ef25bf8",
  "plan_version": 1,
  "status": "PENDING_APPROVAL",
  "steps": [
    {
      "step_id": 1,
      "description": "Replace concatenated string queries with parameterized statements in backend/auth.py",
      "target_files": ["backend/auth.py"],
      "tool": "modify_file"
    }
  ],
  "explanation": "Security remediation plan replacing raw query strings."
}
```

---

### POST `/api/v1/tasks/{task_id}/approve`
**Purpose:** Human gatekeeper records explicit approval for a specific plan version.
**Authentication:** Required
**Request Body:** `{"plan_version": 1}`
**Response (200 OK):** Status transitions to `APPROVED`.

---

### POST `/api/v1/tasks/{task_id}/execute`
**Purpose:** Begin autonomous execution in isolated workspace. Fails with 403 `APPROVAL_REQUIRED` if plan is unapproved or superseded.
**Authentication:** Required
**Response (200 OK / 202 Accepted):** Task transitions to `EXECUTING`.

---

### POST `/api/v1/tasks/{task_id}/verify`
**Purpose:** Run independent verification checks (test suite, security secrets scanner, diff boundaries).
**Authentication:** Required
**Response (200 OK):** Returns `VerificationResult` (`PASSED`, `FAILED`, or `REQUIRES_HUMAN_REVIEW`) and records `verification_diff_hash`.

---

### POST `/api/v1/tasks/{task_id}/create-pr`
**Purpose:** Enforce human publication authorization and post-verification diff immutability, push branch, and create GitHub Draft PR.
**Authentication:** Required
**Request Body:** `{"publication_authorized": true, "draft": true}`
**Response (200 OK):** Returns PR URL, branch name, and commits.

---

### GET `/api/v1/tasks/{task_id}/stream`
**Purpose:** Real-time Server-Sent Events (SSE) stream of lifecycle events and stdout logs.
**Authentication:** Required
**Content-Type:** `text/event-stream`

---

### POST `/api/v1/github/webhook`

**Purpose:** Ingest raw GitHub webhook deliveries with HMAC-SHA256 signature verification, idempotency checking, and durable state machine persistence.
**Authentication:** Secret-based HMAC signature via `X-Hub-Signature-256` header.
**Headers Required:**
- `X-GitHub-Event`: Event type (e.g., `push`, `pull_request`, `installation`)
- `X-GitHub-Delivery`: Unique UUID delivery ID for idempotency deduplication
- `X-Hub-Signature-256`: `sha256=<hex_hmac>` calculated with `GITHUB_WEBHOOK_SECRET`

**Response (200 OK / 202 Accepted):**
```json
{
  "status": "enqueued",
  "event_id": "9b1deb4d-3b7d-4bad-9bdd-2b0d7b3dcb6d",
  "delivery_id": "72d3162e-cc78-11e3-81ab-4c9367dc09d2",
  "event_type": "push"
}
```

---

### GET `/api/v1/github/events`

**Purpose:** Query durably persisted GitHub webhook events with filtering and pagination.
**Authentication:** Required
**Query Parameters:**
| Param | Type | Description |
|---|---|---|
| `event_type` | string | Filter by event type (`push`, `pull_request`, etc.) |
| `status` | string | Filter by state (`pending`, `processing`, `completed`, `failed`, `dead_letter`) |
| `limit` | int | Results per page (default: 50, max: 100) |
| `offset` | int | Pagination offset |

**Response (200 OK):**
```json
{
  "total": 1,
  "items": [
    {
      "id": "9b1deb4d-3b7d-4bad-9bdd-2b0d7b3dcb6d",
      "delivery_id": "72d3162e-cc78-11e3-81ab-4c9367dc09d2",
      "event_type": "push",
      "status": "completed",
      "attempts": 1,
      "max_retries": 3,
      "created_at": "2026-11-08T10:00:00Z"
    }
  ]
}
```

---

### GET `/api/v1/github/events/{event_id}`

**Purpose:** Retrieve complete details of a specific webhook event including payload and failure diagnosis.
**Authentication:** Required
**Response (200 OK):**
```json
{
  "id": "9b1deb4d-3b7d-4bad-9bdd-2b0d7b3dcb6d",
  "delivery_id": "72d3162e-cc78-11e3-81ab-4c9367dc09d2",
  "event_type": "push",
  "status": "completed",
  "attempts": 1,
  "max_retries": 3,
  "last_error": null,
  "payload": { "...": "..." },
  "created_at": "2026-11-08T10:00:00Z"
}
```

---

### POST `/api/v1/github/events/{event_id}/replay`

**Purpose:** Reset a failed or dead-letter webhook event to `pending` status with refreshed lease to re-trigger worker processing.
**Authentication:** Required
**Response (200 OK):**
```json
{
  "status": "replayed",
  "event_id": "9b1deb4d-3b7d-4bad-9bdd-2b0d7b3dcb6d",
  "replay_count": 1
}
```

---

### GET `/api/v1/github/repositories/{github_repo_id}/automation`

**Purpose:** Retrieve opt-in automation configuration for a connected repository.
**Authentication:** Required
**Response (200 OK):**
```json
{
  "github_repo_id": "12345678",
  "auto_sync_enabled": true,
  "pr_review_enabled": true,
  "pr_review_drafts": false,
  "last_indexed_commit_sha": "a1b2c3d4e5f6"
}
```

---

### PATCH `/api/v1/github/repositories/{github_repo_id}/automation`

**Purpose:** Update repository automation settings for automatic push re-indexing and automated PR code reviews.
**Authentication:** Required
**Request Body:**
```json
{
  "auto_sync_enabled": true,
  "pr_review_enabled": true,
  "pr_review_drafts": false
}
```
**Response (200 OK):** Updated `RepositoryAutomationSettingsResponse` object.

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
| `TASK_NOT_FOUND` | 404 | Task does not exist or tenant lacks permission |
| `APPROVAL_REQUIRED` | 403/409 | Task plan has not received human approval or approval was invalidated by re-planning |
| `VERIFICATION_FAILED` | 409 | Independent verification failed, workspace was modified post-verification, or missing diff hash |
| `PUBLICATION_AUTHORIZATION_REQUIRED` | 403 | Explicit human publication authorization (`publication_authorized=True`) is required |
| `INVALID_STATE_TRANSITION` | 409 | Illegal state jump rejected by task lifecycle state machine |
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
| Method | GitHub OAuth 2.0 → JWT (HS256) |
| JWT Algorithm | Configured via `JWT_ALGORITHM` env var (HS256 default) |
| JWT Secret | `JWT_SECRET` env var — enforced >= 32 bytes (256 bits) on startup |
| Secret Validation | Startup checks reject weak, default, or short secrets (`SecurityError`) |
| Timing Attack Defense | Cryptographic verification uses `hmac.compare_digest` for timing safety |
| CSRF State Nonce | Cryptographically random `oauth_state` stored in Redis (`oauth_state:{state}`) with 10-minute TTL, atomically consumed via `GETDEL` |
| Token Storage | httpOnly, secure, SameSite=Lax cookie (set by backend on OAuth callback) |
| Frontend Access | Cookie sent automatically via `withCredentials: true` |
| Session Invalidation | JWT JTI added to Redis blocklist (`jwt_blocklist:{jti}`) on logout with remaining TTL |
| Route Protection | `JWTMiddleware` validates all non-auth routes and sets `request.state.user_id` |

---

## Frontend API Client

**Location:** `frontend/src/services/` (planned by Dhramraj)

**Config:**
- Base URL from environment variable
- Auth token injection (cookie-based, `withCredentials: true`)
- Error parsing into standard `ApiError` type
- Using Axios
