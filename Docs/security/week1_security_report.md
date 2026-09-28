# Week 1 Security Report

**Owner:** Sukun (Security + Observability) · **Date:** 2026-09-28 · **Commit reviewed:** `ac3f926` (main)
**Scope:** Week 1 codebase: backend API, GitHub integration, repository engine, indexer, RAG pipeline, frontend.

---

## 1. Gate result

> **Status: NOT PASSED YET.** 1 gate item passes, 3 need a test or DB run, and 2 are blocked by findings.
> The main blocker is **F-1**: secrets from synced repositories are stored in `code_chunks` without redaction.

| # | Gate item | Result | Evidence |
|---|---|---|---|
| 1 | No secrets in `.git` history | ✅ **PASS** | All 163 commits on all 48 remote branches scanned. `git log --all -S "SECRET"` → 11 commits, all variable names or docs. Pattern scan found 0 real secrets. 5 matches were test fixtures or doc examples, reviewed and allowlisted (§4). `.env` is gitignored and was never committed. |
| 2 | No secrets in `code_chunks` | ⚠️ **AT RISK** (run DB scan) | The indexer stores **raw file content** with no redaction (F-1). Any synced repo containing a key puts that key in this table. Run `security_gate.py` against the DB to get the actual count. |
| 3 | No secrets in `memory_entries` | ⏳ **PENDING** (run DB scan) | No Week 1 code writes memory entries (read-only repository), so the table is expected to be empty or seed data only. Confirm with the DB scan. |
| 4 | Repository isolation | ⏳ **PENDING** (run tests) · code review OK | Every repository route checks ownership (`user_id`) before any work. Retrieval SQL filters by `repository_id`. The previous isolation test **never actually ran** (F-5) and has been rewritten to cover all 6 endpoints. |
| 5 | Prompt injection | ✅ **PASS by design** · tests pending | Repo content goes only in the user message, inside a random per-call boundary (Day 5). The LLM has no tools and no DB access, and output is schema-validated JSON. Covered by `test_security_day5.py::TestPromptInjection`. |
| 6 | Path traversal / workspace confinement | ❌ **FAIL** (2 findings) | API path validator and walker symlink/traversal guards are in place (Day 5). But the clone workspace check can be bypassed (F-3), and the indexer/detector read files relative to the process's working directory instead of the clone (F-4). |
| + | API security (Day 6) | ⏳ **PENDING** (run tests) | Rate limits, security headers and CORS implemented; `test_security_day6.py`. |

---

## 2. Findings

| ID | Severity | Finding | Owner | Fix |
|---|---|---|---|---|
| **F-1** | 🔴 High | **No secret redaction before indexing.** The Day 4 secret scanner doesn't exist in the codebase. `indexer/incremental.py` inserts whole files into `code_chunks.content`, which flows into the LLM context and search results. | Sukun / Divu | Implement the Day 4 scanner (redact → `[REDACTED]`, log file + line + pattern, never the value) and call it before the `INSERT`. Then re-sync or purge existing chunks. |
| **F-2** | 🟠 Medium | **GitHub installation token saved to disk and possibly logged.** `clone_repository` puts the token in the clone URL (`https://x-access-token:<token>@github.com/...`). Git writes that URL into the clone's `.git/config`, and a failed clone logs `stderr` at ERROR, which can echo the URL. | Parth | Pass the token via `git -c http.extraHeader="Authorization: Basic …"` (or run `git remote set-url` right after cloning), and mask the token in logged `stderr`. |
| **F-3** | 🟠 Medium | **Workspace check can be bypassed.** `str(target).startswith(str(workspace_root))` also accepts sibling directories: `/tmp/ai_platform_workspaces_evil/x` passes for root `/tmp/ai_platform_workspaces`. | Parth | Use `target.is_relative_to(workspace_root)` or `is_within()` from `app/core/input_security.py`. |
| **F-4** | 🟠 Medium | **Files read relative to the wrong directory.** `FileWalker` returns repo-relative paths, but `IncrementalIndexer.sync` and `LanguageDetector.detect` call `open(file_info.path)` directly, so they resolve against the worker's current directory, not the clone. They index the wrong files, or files outside the workspace. | Divu / Prit | Pass the clone root and open via `resolve_within_root(root, file_info.path)`. |
| **F-5** | 🟡 Low | **Isolation was untested.** The old `test_repository_isolation.py` used fixtures that don't exist, the wrong cookie name (`auth_token` instead of `access_token`) and no `/api/v1` prefix, so it errored and was never executed. | Sukun | Replaced (see §3). |
| **F-6** | 🟡 Low | **Inconsistent denial codes.** GET/search/files/symbols return **403** for another user's repo, while sync/chat return **404**. Both deny access; 404 also hides that the repo exists. | Yug | Choose one (recommended: 404 everywhere) and update Docs/week1.md Day 3. |
| **F-7** | ⚪ Info | No endpoint reads file content by path yet. When one is added it must call `require_safe_repo_path()`. | Yug | Note in API docs. |
| **F-8** | ⚪ Info | Day 6 spec lists `POST /auth/github/callback`; the implementation is `GET` (OAuth redirect). The rate limit covers both. | Sukun | Update the doc. |

---

## 3. Controls delivered in Week 1 (Sukun)

| Day | Control | Where |
|---|---|---|
| 1 | `.env` gitignored, `.env.example` has placeholders only | `.gitignore`, `.env.example` |
| 3 | Isolation test matrix, all 6 repo endpoints (rewritten Day 7) | `backend/tests/test_repository_isolation.py` |
| 5 | Path validator, symlink/traversal-safe walker, prompt data boundary, XSS guard test | `app/core/input_security.py`, `scanner/walker.py`, `ai/schemas/prompt_builder.py`, `tests/test_security_day5.py` |
| 6 | Rate limits, security headers, CORS allowlist | `app/core/rate_limit.py`, `app/core/security_headers.py`, `app/main.py`, `tests/test_security_day6.py` |
| 7 | Automated gate + reviewed allowlist | `backend/scripts/security_gate.py`, `backend/scripts/security_gate_allowlist.txt` |

---

## 4. Git history review (gate item 1)

- **Command from spec:** `git log --all -S "SECRET"` → 11 commits. All add variable **names** (`JWT_SECRET`, `GITHUB_WEBHOOK_SECRET`), doc tables or test env values. None contain real secret values.
- **Pattern scan** over every added line in every commit: OpenAI `sk-…`, GitHub `ghp_/ghs_/github_pat_`, AWS `AKIA…`, `-----BEGIN … PRIVATE KEY-----`, and quoted or `.env`-style credential assignments.
- **Result:** 0 real secrets. 9 placeholders were skipped automatically (`<secret>`, `sk-test-key`, `-----BEGIN RSA PRIVATE KEY-----\n...\n`). 5 matches were reviewed and allowlisted:

| Fingerprint | Value type | Location | Why it's safe |
|---|---|---|---|
| `56ae5d01bc` | fake `ghs_` token | `backend/tests/test_github_mocks.py` | test fixture |
| `371d66138c` | fake `ghs_` token | `tests/mocks/github.py` | test fixture |
| `1311f8fc80` | `my-secret-key` | `Docs/project_idea.md`, `Docs/week3.md` | example text in docs |
| `fcf730b6d9` | `secret123` | Week 3 security test table | example text in docs |

---

## 5. How to reproduce

```bash
git fetch --all --unshallow            # full history, all branches
docker compose up -d postgres redis    # DB needed for items 2–3
python backend/scripts/security_gate.py --out Docs/security/week1_gate_results.md
```
The script exits `1` if any item fails, so it can run in CI. Secret values are never printed; findings show location, pattern and a hash fingerprint only.

## 6. Sign-off checklist
- [ ] F-1 fixed, existing chunks re-indexed, gate item 2 PASS
- [ ] F-3, F-4 fixed, gate item 6 PASS
- [ ] F-2 fixed (token not on disk or in logs)
- [ ] `security_gate.py` run on a DB with at least one synced repo, results attached
- [ ] All security test files green: isolation, Day 5, Day 6
