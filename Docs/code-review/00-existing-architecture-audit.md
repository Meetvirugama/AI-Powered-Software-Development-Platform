# 00 — Existing Architecture Audit: AI-Powered Code Review

**Document**: `Docs/code-review/00-existing-architecture-audit.md`  
**Feature**: F14 — AI-Powered Code Review Intelligence  
**Author**: Antigravity Senior Architecture & QA Team  
**Status**: AUDITED & VERIFIED  

---

## 1. Existing Architecture Overview

The platform currently possesses a functional foundation for standalone AI code review established during Week 2 Day 5. It handles multi-target analysis (`file`, `commit`, `pr`, `diff`), runs static AST/linter checks (Ruff, Bandit), computes blast-radius context from repository indexing, invokes an LLM with fenced context, grounds findings to line coordinates, and returns structured findings to the frontend Studio view.

However, the existing system is largely **read-only and platform-confined**:
1. Findings are **not published as inline comments** to GitHub pull requests via the GitHub REST API (`/repos/{owner}/{repo}/pulls/{number}/reviews`).
2. Only Python linters (Ruff, Bandit) are executed; JavaScript/TypeScript ecosystems lack static scanners despite claims in user documentation.
3. There is no developer feedback mechanism (thumbs up/down or false positive flags).
4. Findings lack persistent lifecycle tracking (`NEW`, `ACTIVE`, `FIXED`, `REOPENED`, `DISMISSED`).
5. PR `synchronize` webhook events only post a top-level summary without diff-anchored comments or incremental commit diffing.

---

## 2. File-by-File Responsibilities

| File Path | LOC | Existing Responsibility | Classification |
|---|---|---|---|
| `backend/app/services/code_review_orchestrator.py` | 1,241 | Target resolution (`file`, `commit`, `pr`, `diff`), context extraction, AST mapping, AI prompt construction, static check aggregation, grounding & ranking. | **PARTIALLY IMPLEMENTED** |
| `backend/app/integrations/github/client.py` | 543 | Low-level GitHub REST API wrapper. Implements `create_pull_request_review(owner, repo, pr_number, body, event, comments)` but does not accept `commit_id` or handle diff anchor reconciliation. | **PARTIALLY IMPLEMENTED** |
| `backend/app/integrations/github/service.py` | 1,045 | High-level GitHub service. Delegates to `GitHubClient.create_pull_request_review` with token resolution from GitHub App installation. | **PARTIALLY IMPLEMENTED** |
| `backend/review/static_reviewer.py` | 193 | Host subprocess execution of Ruff and Bandit on modified files. Missing ESLint, Biome, and sandboxed execution boundaries. | **PARTIALLY IMPLEMENTED** |
| `backend/ai/context/review_context.py` | 237 | `ReviewContextBuilder` computes symbol dependencies and blast radius for changed files. | **IMPLEMENTED** |
| `backend/scanner/source_mapper.py` | 382 | Maps diff hunks to enclosing AST symbols, scopes, and modified line ranges. | **IMPLEMENTED** |
| `backend/app/models/analysis_run.py` | 120 | Persists review run metadata, status, target, and JSONB `result_payload`. | **IMPLEMENTED** |
| `backend/app/models/analysis_finding.py` | 134 | Persists individual review findings with severity, confidence, evidence, and JSONB `metadata`. | **IMPLEMENTED** |
| `backend/app/models/repository.py` | 36 | Database model holding repository settings, including boolean flags `pr_review_enabled` and `pr_review_drafts`. | **IMPLEMENTED** |
| `backend/app/api/v1/analysis/review.py` | 311 | `POST /api/v1/repositories/{id}/review` endpoint orchestrating target resolution, LLM review, static checks, and persistence. | **PARTIALLY IMPLEMENTED** |
| `backend/app/services/webhook_handlers.py` | 749 | `PullRequestEventHandler` handles `pull_request` webhooks. Currently only formats top-level body text and posts single review body with no inline comments. | **PARTIALLY IMPLEMENTED** |
| `frontend/src/pages/RepositoryReviewStudio.tsx` | 232 | Studio page for code review with file selection, target configuration, and history drawer. | **IMPLEMENTED** |
| `frontend/src/components/explorer/CodeReviewView.tsx` | 1,058 | Renders review report, category breakdown, risk pill, finding cards, and issue creation. Missing inline feedback buttons and GitHub publication badges. | **PARTIALLY IMPLEMENTED** |

---

## 3. Existing Execution Sequence

```
1. Client requests POST /api/v1/repositories/{repository_id}/review
2. resolve_review_target_and_build_context():
   - file: Reconstructs source from code_chunks
   - commit/pr: GitHubSourceService retrieves commit/PR diff
   - diff: Unified diff parser extracts modified hunks
3. ReviewContextBuilder: Assembles symbol blast radius
4. AI Review Engine: LLM invoked with fenced diff & context
5. StaticReviewer: Subprocess runs Ruff & Bandit
6. Source Grounding & Deduplication: Maps findings to line numbers
7. Persistence: record_analysis_run() writes AnalysisRun & AnalysisFinding
8. Returns ReviewReportResponse to caller
```

**Missing in sequence**:
- Verification whether finding is on a changed line versus unchanged context line.
- Pre-publication eligibility and evidence quality gating.
- GitHub review creation with multiple inline line-level comments.
- Deduplication against previous bot comments and human reviewer comments.
- Feedback collection and finding lifecycle updates.

---

## 4. Existing API Endpoints

- `POST /api/v1/repositories/{repository_id}/review`: Runs standalone review. Returns `ReviewReportResponse`.
- `GET /api/v1/repositories/{repository_id}/review/history`: Retrieves past review runs.
- `GET /api/v1/repositories/{repository_id}/analysis-runs/{run_id}`: Retrieves specific run with findings.
- `POST /api/v1/webhooks/github`: Receives GitHub webhook payloads (including PR events).

**Missing endpoints**:
- `POST /api/v1/repositories/{repository_id}/review/publish`: Explicit user-triggered publication of review findings to GitHub PR.
- `POST /api/v1/analysis-runs/{run_id}/findings/{finding_id}/feedback`: Submitting developer feedback (useful, not_useful, false_positive).
- `PATCH /api/v1/repositories/{repository_id}/review/settings`: Repository-level review configuration (enable/disable publication, changed-lines-only, minimum confidence, scanner selection).
- `GET /api/v1/repositories/{repository_id}/review/settings`: Retrieve current review settings.

---

## 5. Existing Database Structure

- `repositories`: Holds `pr_review_enabled` and `pr_review_drafts`.
- `analysis_runs`: Holds `result_payload` (JSONB), `target_path`, `source_revision`, `status`.
- `analysis_findings`: Holds `category`, `severity`, `confidence`, `evidence`, `suggested_fix`, `is_new_in_change`, and `finding_metadata` (JSONB).

**Assessment**:
The existing database schema is **sufficiently extensible**:
- `finding_metadata` (JSONB) on `AnalysisFinding` can natively store `fingerprint`, `lifecycle_status`, `first_detected_commit`, `last_detected_commit`, `is_changed_line`, `github_comment_id`, and `feedback`.
- `result_payload` (JSONB) on `AnalysisRun` can store `review_publication` details (`github_review_id`, `published_comments_count`, `commit_sha`).
- Repository settings can be augmented cleanly via model columns or repository settings extension without destructive table migrations.

---

## 6. Existing GitHub Integration

- `GitHubClient.create_pull_request_review()` takes `owner`, `repo`, `pr_number`, `body`, `event`, and `comments: list[dict]`.
- Existing implementation did NOT send `commit_id` in the review payload, risking comments being dropped if the PR HEAD moved.
- Webhook handler `PullRequestEventHandler` only called `create_pull_request_review(..., body=review_body)` without passing any `comments` list.
- No reconciliation logic: if a review creation timed out, there was no check to see if GitHub actually received and posted it before retrying.

---

## 7. Existing Static Scanners

- `StaticReviewer` in `backend/review/static_reviewer.py`:
  - Python: `ruff check --output-format json` and `bandit -f json -r`.
  - Directly invokes `subprocess.run([sys.executable, ...])` on the host machine.
  - JavaScript / TypeScript: **NOT IMPLEMENTED** (missing ESLint and Biome).
  - Sandbox isolation: Not using `backend/sandbox/` execution primitives.

---

## 8. Existing Frontend Integration

- `RepositoryReviewStudio.tsx` renders file picker and triggers `POST /repositories/{id}/review`.
- `CodeReviewView.tsx` renders findings with severity filters, category counts, risk badge, and copyable suggested fix.
- Lacks:
  - Thumbs up / thumbs down vote buttons for developer feedback.
  - Lifecycle badges (`NEW`, `ACTIVE`, `FIXED`, `REOPENED`, `DISMISSED`).
  - GitHub publication status and link to PR review.
  - Changed-line vs platform-only indicator.

---

## 9. Existing Tests

- `backend/tests/test_code_review_day5.py`: 13 tests (all passing).
- `backend/tests/test_dev_w2_day5_code_review.py`: 10 tests (all passing).
- `backend/tests/test_static_reviewer.py`: 11 tests (all passing).
- `backend/tests/test_security_review.py`: 26 tests (all passing).
- `backend/tests/test_keval_w2_day5_review_qa.py`: 6 tests (all passing).
- `backend/tests/test_meet_day5_review_context.py`: 8 tests (all passing).
- `backend/tests/test_om_w2_d5_review_history.py`: 14 tests (all passing).
- Total: 88 passing backend review tests.

---

## 10. Confirmed Implementation Gaps

1. **Gap 1: PR Inline Comments Publication**:
   - `create_pull_request_review` called only with text summary; line comments never constructed with `path`, `line`, `side`, and `body`.
2. **Gap 2: Changed-Line Policy**:
   - No filter separating changed-line findings (eligible for GitHub comments) from unchanged context findings (platform UI only).
3. **Gap 3: Deduplication**:
   - No comparison against prior bot comments or existing PR discussion comments.
4. **Gap 4: JavaScript/TypeScript Static Review**:
   - ESLint and Biome missing from `StaticReviewer`.
5. **Gap 5: Developer Feedback**:
   - No feedback model or API to collect 👍/👎 or reason strings.
6. **Gap 6: Finding Lifecycle**:
   - No tracking of `NEW`, `ACTIVE`, `FIXED`, `REOPENED`, `DISMISSED`.
7. **Gap 7: Incremental Review on Synchronize**:
   - PR `synchronize` webhook runs full scan without diffing previous commit against new commit.
8. **Gap 8: UI Feedback & Publication State**:
   - Frontend lacks feedback triggers and publication status displays.

---

## 11. Security & Reliability Risks

1. **Subprocess execution**: StaticReviewer running subprocesses on host without sandbox isolation or timeout controls on untrusted JS scripts.
2. **Commit SHA pinning**: Omitting `commit_id` when publishing reviews can cause comments to anchor on incorrect file versions.
3. **Publication idempotency**: Network failures during review publishing could trigger duplicate reviews without reconciliation.
4. **Untrusted repo content**: Malicious prompt injections inside PR diffs must remain contained in fences (`<<<REPO_DATA_...>>>`).

---

## 12. Component Modification & New Services Plan

### Reusable Components:
- `ReviewSourceMapper`: High-precision unified diff parser and line coordinate mapper.
- `ReviewContextBuilder`: Symbol dependency and blast-radius calculator.
- `GitHubClient` / `GitHubService`: Authentication and GitHub REST API integration.
- `WorkspaceManager` / `CommandRunner`: Isolated sandbox execution in `.workspaces/`.

### Modified Components:
- `backend/app/integrations/github/client.py`: Add `commit_id` support and comment anchor validation to `create_pull_request_review`.
- `backend/review/static_reviewer.py`: Add ESLint and Biome adapters, repository config detection, and sandbox runner.
- `backend/app/services/code_review_orchestrator.py`: Integrate quality gate and deduplication.
- `backend/app/services/webhook_handlers.py`: Upgrade `PullRequestEventHandler` for inline publication and incremental diffing.
- `backend/app/api/v1/analysis/review.py`: Add review publication, settings, and feedback routes.
- `frontend/src/components/explorer/CodeReviewView.tsx`: Add feedback buttons, lifecycle status, and publication badges.

### Proposed New Dedicated Services:
- `backend/app/services/review_publication_service.py`: Orchestrates GitHub PR review publication, diff anchor validation, idempotency, and reconciliation.
- `backend/app/services/review_validation_service.py`: Gating rules, evidence sufficiency, confidence threshold, and changed-line policy.
- `backend/app/services/review_deduplication_service.py`: Multi-stage deduplication (fingerprint, normalized text, overlapping region, prior PR comments).
- `backend/app/services/review_feedback_service.py`: Persistence and analytics for developer feedback.
- `backend/app/services/review_lifecycle_service.py`: Tracking finding status transitions across review runs.
- `backend/app/services/incremental_review_service.py`: Handles PR `synchronize` commit diffing and affected context selection.

---

## 13. Priority Order

1. **Phase 1**: GitHub Review Publication Foundation (`ReviewPublicationService`, diff anchor validation, commit pinning, idempotency).
2. **Phase 2**: Finding Quality Gate & Deduplication (`ReviewValidationService`, `ReviewDeduplicationService`).
3. **Phase 3**: Static Analysis Expansion (ESLint, Biome, repository config detection, safe sandbox).
4. **Phase 4**: Feedback & Finding Lifecycle (`ReviewFeedbackService`, `ReviewLifecycleService`, UI buttons).
5. **Phase 5**: Incremental Review on Synchronize (`IncrementalReviewService`, webhook integration).
6. **Phase 6**: Hardening, Quality Benchmark, Testing & Documentation.
