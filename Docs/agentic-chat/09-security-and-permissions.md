# 09 — Security and Permissions

## 1. Authentication & Tenant Authorization

All agentic chat requests enter via `POST /api/v1/repositories/{repository_id}/chat`.

1. **Authentication:**
   - The user must provide a valid session via `httpOnly` JWT cookie or Bearer token.
   - `get_current_user` dependency rejects unauthorized requests with HTTP 401.

2. **Repository Authorization:**
   - The router loads the repository via `RepositoryRepository.get(db, repository_id)`.
   - The repository must belong to the user's organization or authenticated account.
   - Unauthorized attempts return HTTP 404 or 403.
   - In all subsequent tool calls, `context.repository_id` is passed immutably to enforce tenant isolation in SQL queries.

---

## 2. Policy-Level Protections (`backend/ai/agent/policy.py`)

### 2.1 Path Traversal Prevention (`sanitize_relative_path`)
Tool inputs requesting file paths are sanitized against traversal attacks:
- Null bytes (`\0`) are rejected.
- Backslashes are normalized to forward slashes.
- Leading slashes (e.g. `/etc/passwd`) are rejected.
- Directory traversal tokens (`..`) are strictly rejected.
- Path length is capped at 500 characters.

### 2.2 Line-Range Clamping (`validate_line_range`)
- Negative lines or 0-indexed values are clamped or rejected.
- `start_line` must be $\le end_line$.
- Maximum line span is capped at 150 lines.

### 2.3 Secret Redaction (`sanitize_and_redact`)
Before any tool output or error message is returned to the model, regex-based secret filters mask:
- GitHub Tokens: `ghp_[a-zA-Z0-9]{36,}`
- AWS Access Keys: `AKIA[0-9A-Z]{16}`
- RSA / OpenSSH Private Keys: `-----BEGIN [A-Z ]*PRIVATE KEY-----...`
- Database URIs: `postgres://...`, `mysql://...`
- Authorization Headers: `Bearer eyJ...`

---

## 3. Database Isolation

- Queries executed by tools use read-only SQL statements (`SELECT`).
- Tools never perform `INSERT`, `UPDATE`, `DELETE`, or schema migrations.
- `run_db_query` supports asynchronous database execution safely without cross-request session leakage.
