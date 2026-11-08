# 01 — Requirements and Scope: AI Code Review System

**Document**: `Docs/code-review/01-requirements-and-scope.md`  
**Feature**: F14 — AI-Powered Code Review Intelligence  
**Author**: Antigravity Senior Architecture & QA Team  
**Status**: APPROVED  

---

## 1. Problem Statement

While our current AI code review feature produces structured findings across 5 review dimensions (`correctness`, `security`, `performance`, `reliability`, `maintainability`), findings are currently locked inside the platform web interface. Developers reviewing code on GitHub do not receive actionable feedback where they actually work—directly inside pull request reviews.

Furthermore:
- Unanchored or context-line issues risk polluting pull requests with noisy comments if not gated by changed-line policies.
- Linters are limited to Python (Ruff/Bandit); modern TypeScript/JavaScript web applications cannot run ESLint or Biome.
- Developers cannot mark findings as false positives or upvote useful advice, preventing systematic evaluation and precision tuning.
- Consecutive reviews do not recognize which findings were already resolved or introduced in incremental commits.

---

## 2. Functional Requirements

### FR-01: GitHub PR Review Publication
- Publish qualified code review findings as inline GitHub review comments using `POST /repos/{owner}/{repo}/pulls/{pr_number}/reviews`.
- Group all inline comments into **one single GitHub review submission** with `event="COMMENT"` to minimize notification spam.
- Explicitly pin the review to the target `commit_id` (HEAD commit SHA analyzed).
- Format each inline comment with clear markdown: Finding title, category, severity, technical explanation, concrete failure scenario, and suggested remediation.
- Generate an executive review summary markdown block at the review top-level.
- Support both **automated webhook publication** (opt-in on PR `opened` / `synchronize`) and **manual publication** via API (`POST /repositories/{id}/review/publish`).

### FR-02: Quality Gate & Precision Filtering
- Implement two distinct finding collections:
  1. **Platform Findings**: All technically valid findings across modified and context files.
  2. **GitHub Publishable Findings**: Only findings meeting strict publication criteria.
- Publication criteria:
  - Evidence level must be `STRONG` or `PROVEN` (reject `SUSPECTED` or `NEEDS_CONTEXT`).
  - Confidence must be $\ge$ repository threshold (default `high` or `medium`).
  - Line coordinate must exist on an **added or modified line** in the PR diff (`side="RIGHT"`).
  - File path must be valid and verified within the repository.
  - Finding must not be a duplicate of an existing review comment.
- Configurable maximum comments per review (default: 10, configurable up to 25) to avoid overwhelming PR authors.

### FR-03: Deduplication & Comment Reconciliation
- Compute a deterministic SHA-256 fingerprint for each finding: `hash(repo_id, normalized_file_path, category, normalized_title_or_rule, symbol_name)`.
- Reconcile against previous reviews posted by the bot on the same PR to prevent repeating identical findings.
- Inspect existing human reviewer comments retrieved via `GitHubClient.list_pull_request_comments()` to avoid redundant observations.

### FR-04: Static Analysis Expansion (JavaScript & TypeScript)
- Support **ESLint** and **Biome** alongside Ruff and Bandit.
- Auto-detect scanner compatibility based on repository configuration files (`package.json`, `.eslintrc.*`, `eslint.config.*`, `biome.json`).
- Execute linters within an isolated sandbox boundary (`backend/sandbox/`) with strict execution timeouts (60s), output truncation, and zero network access.
- Normalize scanner diagnostics into the standard `ReviewFinding` structure.

### FR-05: Developer Feedback Loop
- Provide an API endpoint (`POST /analysis-runs/{run_id}/findings/{finding_id}/feedback`) allowing developers to vote:
  - `useful`: Finding helped identify or fix a real issue.
  - `not_useful`: Finding was not helpful.
  - `false_positive`: Finding was factually incorrect or inappropriate.
  - `already_fixed`: Issue was addressed.
- Persist feedback with user attribution and optional explanatory text.
- Compute aggregate acceptance and false-positive rates.

### FR-06: Finding Lifecycle Tracking
- Track finding states across consecutive PR commits:
  - `NEW`: Detected for the first time.
  - `ACTIVE`: Still present in the latest analysed commit.
  - `FIXED`: Code modification removed the defect.
  - `REOPENED`: Defect returned in a later revision.
  - `DISMISSED`: Dismissed by developer feedback.
  - `SUPPRESSED`: Suppressed by repository rule.
- Do not mark a finding `FIXED` if an analysis was incomplete or failed.

### FR-07: Incremental Review on Synchronize
- When a PR is updated with new commits (`synchronize` webhook event):
  - Retrieve the previous reviewed commit SHA and current HEAD commit SHA.
  - Compute the git diff between previous and current commit.
  - Re-evaluate modified files and their blast-radius dependents.
  - Check whether previous findings are resolved or persist.
  - Publish inline comments only for newly introduced issues.

### FR-08: Frontend Studio Enhancements
- Provide inline feedback buttons (👍 / 👎 / 🚩 False Positive) on finding cards.
- Display GitHub publication badge with direct link to the GitHub PR review.
- Indicate whether a finding is on a changed line (inline comment eligible) or platform-only.
- Provide repository review settings panel.

---

## 3. Non-Functional Requirements

1. **Security**:
   - Zero execution of arbitrary npm or pip scripts on the host machine.
   - Enforce path traversal protection (`require_safe_repo_path`).
   - Redact all secrets and credentials in review bodies and comments.
   - GitHub publishing disabled by default (opt-in requirement).
2. **Performance & Latency**:
   - Deterministic static analysis runs first.
   - PR review publication timeout bounded at 30 seconds.
   - Static linters timeout bounded at 60 seconds.
3. **Inference Efficiency**:
   - Limit prompt token consumption by bounding diff hunks and context tokens.
   - Avoid calling LLM for duplicate candidate comparison; use fingerprint matching first.
4. **Reliability & Idempotency**:
   - Durable publication tracking to handle network drops and prevent duplicate GitHub reviews.
   - Never auto-approve or auto-request changes on a PR (`event="COMMENT"` strictly enforced).

---

## 4. Scope & Boundaries

### In-Scope:
- GitHub PR inline comments publication.
- Quality gate filtering (changed lines, evidence levels, confidence thresholds).
- Multi-stage deduplication.
- ESLint and Biome integration with safe execution.
- Developer feedback API and UI.
- Finding lifecycle state tracking.
- Incremental PR review on `synchronize`.
- Complete documentation under `Docs/code-review/`.

### Out-of-Scope:
- Auto-merging pull requests or submitting `APPROVE` / `REQUEST_CHANGES` events.
- Installing third-party plugins from npm registry during static analysis.
- Live chat / back-and-forth thread discussion on GitHub comments (comments will include a link to discuss in platform chat).
