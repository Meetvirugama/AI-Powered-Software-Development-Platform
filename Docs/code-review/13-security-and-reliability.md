# Security and Reliability — AI-Powered Code Review Intelligence (F14)

## 1. Security Defenses

### 1.1 Path Traversal Defenses
- All incoming and reported file paths are normalized and strictly validated using `validate_repo_relative_path`.
- Path traversal sequences (`../`, absolute paths `/`, Windows drive specifiers `C:\`) trigger `UnsafePathError` and are rejected before execution.

### 1.2 Subprocess Command Injection Defense
- Dynamic tool execution for ESLint and Biome linters adheres strictly to static execution arguments:
  ```python
  cmd = ["npx", "eslint", "--format", "json", "--no-color", "--", safe_path]
  ```
- The `--` delimiter prevents target file paths from being interpreted as CLI flags.
- Subprocesses run with safe default timeouts (`timeout=30.0`), output size truncation (5MB limit), and isolated environment variables.

### 1.3 Secret Redaction & Token Masking
- The review pipeline integrates regex-based and heuristic secret scrubbers.
- In-flight evidence strings are sanitized before being sent to LLMs or published to GitHub reviews.
- Bearer tokens, GitHub App private keys, AWS access keys, and connection strings are masked with `[REDACTED_SECRET]`.

### 1.4 Tenant Isolation & Authorization
- Every API endpoint validates that `repository_id` belongs to `request.state.user_id` using `get_owned_repository`.
- Analysis runs and findings verify repository ownership before updating feedback or publishing comments.

---

## 2. Reliability & Resilience

### 2.1 Stale Commit Head Defense
- Before publishing comments to a pull request, `ReviewPublicationService` verifies that the analyzed commit SHA matches the PR's current `head.sha`.
- If the PR HEAD has advanced due to a new commit push, publication is gracefully skipped (`review_publication_stale_commit`), avoiding outdated comments on obsolete code.

### 2.2 Network Timeout Reconciliation
- If the GitHub API times out during `create_pull_request_review`, the service queries existing PR reviews (`list_pull_request_reviews`) to reconcile whether GitHub processed the request before failing or retrying.
- Prevents duplicate review spam caused by retry storms.

### 2.3 Fail-Closed Production Webhooks
- Webhook endpoints require cryptographic HMAC-SHA256 signature verification (`X-Hub-Signature-256`).
- Unsigned or invalid webhook deliveries are rejected with `401 Unauthorized` in production.
- Delivery IDs are deduplicated in Redis to prevent replay attacks.
