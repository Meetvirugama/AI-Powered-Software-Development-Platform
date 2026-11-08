# Deployment and Configuration — AI-Powered Code Review Intelligence (F14)

## 1. Environment Variables & Platform Configuration

The code review intelligence subsystem respects the following configuration parameters:

| Variable | Type | Default | Description |
|:---|:---:|:---:|:---|
| `REVIEW_PR_AUTOMATION_ENABLED` | `bool` | `true` | Global switch for automatic code reviews on PR webhook events. |
| `REVIEW_MAX_INLINE_COMMENTS` | `int` | `15` | Default ceiling on inline GitHub comments per review to prevent spam. |
| `REVIEW_MIN_CONFIDENCE` | `str` | `"medium"` | Minimum finding confidence required for inline publication (`"high"`, `"medium"`). |
| `REVIEW_CHANGED_LINES_ONLY` | `bool` | `true` | Restrict inline review comments strictly to modified or added diff lines. |
| `GITHUB_APP_ID` | `str` | - | GitHub App identifier for repository installations. |
| `GITHUB_APP_PRIVATE_KEY` | `str` | - | PEM-encoded RSA private key for GitHub App authentication. |
| `GITHUB_WEBHOOK_SECRET` | `str` | - | HMAC secret for verifying incoming webhook deliveries. |
| `REDIS_URL` | `str` | `"redis://localhost:6379/0"` | Redis cache for webhook idempotency and token blocklists. |

---

## 2. Per-Repository Settings

Repository administrators can adjust settings dynamically via the API (`PATCH /api/v1/repositories/{id}/review/settings`) or the repository settings UI:

```json
{
  "pr_review_enabled": true,
  "pr_review_drafts": false,
  "max_comments": 20,
  "min_confidence": "high",
  "changed_lines_only": true
}
```

- **`pr_review_enabled`**: Master opt-in toggle per repository. Default is `false` until explicitly enabled.
- **`pr_review_drafts`**: If `false`, PRs marked as Draft are ignored by automated review runners until marked "Ready for review".
- **`max_comments`**: Custom limit for maximum comments in a single PR review.
- **`changed_lines_only`**: When `true`, enforces that only lines within the PR diff are commented on.

---

## 3. Toolchain Prerequisites

For multi-language static analysis support:
- **Python**: `ruff` and `bandit` installed in the execution environment.
- **Node.js / TypeScript**: `npx` available on PATH. `eslint` and `@biomejs/biome` are invoked via `npx` dynamically or read from repository dependencies. If neither tool is installed or configured in the target repo, static JS/TS analysis is skipped without failing the AI review.
