# Week 2 Security Report — Developer Intelligence Suite

**Owner:** Sukun (Security and trust boundaries) & Yug (Day 7 Final Remediation) · **Day:** W2 Day 6–7 (Security Audit & Final Sign-off) · **Date:** 2026-10-26
**Scope:** Explain Code, Find Bugs, Generate Tests, AI Code Review, analysis history, GitHub source/commit/PR-metadata routes, plus repository chat (Week 1) where it shares the same prompt path.
**Code audited:** `main` at `d55f315` + Day 7 final security remediations.

---

## 1. Summary

> **Status: All Critical, High, Medium, and Low Week 2 security items are resolved and verified by automated tests.**

| Area (Docs/week2.md Day 6–7) | Result | Evidence |
|---|---|---|
| Prompt injection in code and docs | ✅ Pass | All 4 services + chat wrap repository data in a random `<<<REPO_DATA_…>>>` boundary; system prompts (`explanation_system.txt`, `bug_detection_system.txt`, `test_generation_system.txt`, `code_review_system.txt`) forbid following embedded instructions. Fixtures `CANARY-PI-001…008` never leave the boundary. Injected "report zero findings" cannot hide static findings. |
| Unauthorized repository access & IDOR | ✅ Pass | Every analysis route and GitHub source route (`/source/commit`, `/source/pr-metadata/{task_id}`, `/analysis-runs/summary`) resolves the repo with `_owned_repository` / `_get_repository` before any work → 404; services are never called. Cross-repository task ID lookups on `/source/pr-metadata/{task_id}` are blocked with 404. |
| Path traversal | ✅ Pass | Targets, diff file paths, commit staging `files`, PR `changed_files`, `LanguageDetector`, and model citations go through `require_safe_repo_path` / `validate_repo_relative_path`. Proposed test paths also pass a test-file policy (#114). |
| Secret exposure | ✅ Pass | Secrets redacted before the LLM call, in results, in saved history, in workspace commit messages, in PR metadata, in `code_chunks` indexing, in error messages, and in logs. Gemini API keys sent via `x-goog-api-key` header (`W2-S8`). |
| Malformed model output | ✅ Pass | Invalid output → `500 ANALYSIS_FAILED`; failed runs are saved as `FAILED`, never as a zero-finding success. |
| Oversized input / bounded processing | ✅ Pass | 1 MB file limit (413), diff ≤ 200,000 chars, context 500–100,000 tokens, history `page_size` ≤ 100, 2 LLM attempts max, static scanners `timeout=60` with `--` flag separator (`W2-S3`). |
| Cross-repository analysis access | ✅ Pass | Retrieval filters by `repository_id`; another user's run id returns 404; commit/PR lookups only run for an owned repo. |
| Rate limiting | ✅ Pass | `explain`, `detect-bugs`, `generate-tests`, `review`, `source/agent-branch`, `source/commit`, `source/pr-metadata`: 20 req/min per user; chat 30; sync 5. |

---

## 2. Findings & Final Remediation Status

| ID | Severity | Finding | Owner | Status |
|---|---|---|---|---|
| W2-S1 | 🔴 High | No secret redaction anywhere (carried over from W1 F-1). | Sukun / Yug | ✅ **Fixed** — `app/core/secret_redaction.py` + log filter (#107); explain (#108); bug scanner (#111); test generation (#114); code review (#115); shared prompt fence; `SymbolChunker` & `IncrementalIndexer`. |
| W2-S2 | 🟠 Medium | Error responses and logs could include raw model output / exception text. | Sukun / Yug | ✅ **Fixed** — `SecretRedactingFilter` on logs + `redact()` in `APIError.__init__` and `error_response()`. |
| W2-S5 | 🟠 Medium | Test generation accepted any traversal-free path from the model, incl. `conftest.py`, `.github/workflows/…`, `setup.py` or the source file itself. | Sukun / Yug | ✅ **Fixed in #114** — `check_generated_test_path`; falls back to the convention path with a warning. |
| W2-S6 | 🟠 Medium | Code review only checked line numbers for single-file targets; commit / PR / diff findings could cite lines that do not exist. | Sukun / Yug | ✅ **Fixed in #115** — `_max_known_line` bounds every target by indexed length and diff hunk ranges. |
| W2-S7 | 🟡 Low | Repository chat, summary and verifier prompts (Week 1 `PromptBuilder`) sent repository text to the LLM unredacted. | Sukun / Dev | ✅ **Fixed** — `_fence()` now redacts, so every prompt using it is covered. |
| W2-S8 | 🟠 Medium | Gemini API key was sent as `?key=` in the request URL. | Meet / Yug | ✅ **Fixed in Day 7** — `GeminiProvider` and `GeminiEmbeddingProvider` now send `x-goog-api-key` in request headers (`test_w2_s8_gemini_providers_send_key_in_header_not_url`). |
| W1-F1 | 🟡 Low | `code_chunks` stored raw file content before redaction. | Divu / Yug | ✅ **Fixed** — `SymbolChunker` and `IncrementalIndexer.sync()` call `redact()` before embedding and persistence. |
| W2-S3 | 🟡 Low | `static_reviewer.py` passed target path directly after scanner flags without `--`. | Devu / Yug | ✅ **Fixed** — `StaticReviewer.run_scanner()` rejects leading `-` paths and passes `"--"` before `target_path`. |
| W1-F4 | 🟡 Low | `scanner/detector.py` opened `file_info.path` without traversal/root checks. | Prit / Yug | ✅ **Fixed in Day 7** — `LanguageDetector.detect()` rejects `..` traversal and enforces optional `root_path` confinement. |
| W2-D7-S1 | 🔴 Critical | `GET /repositories/{id}/source/pr-metadata/{task_id}` ignored `repository_id` and allowed cross-repo IDOR. | Parth / Yug | ✅ **Fixed in Day 7** — Enforces `_get_repository(repository_id, user_id)` and `record.repository_id == repository_id`. |
| W2-D7-S2 | 🔴 High | `GitBranchService.commit()` & `prepare_pr_metadata()` lacked `require_safe_repo_path` on `files`/`changed_files`, host-repo guard, and secret redaction. | Parth / Yug | ✅ **Fixed in Day 7** — Validates file paths, blocks host/system dirs, sanitizes git refs/authors, and redacts secrets. |
| W1-F3 | 🟠 Medium | Workspace check used `str.startswith`. | Parth | ✅ **Fixed** — now `is_within()`. |
| W1-F6 | 🟡 Low | 403 vs 404 inconsistency for other users' repos. | Yug | ✅ **Fixed** — consistently 404. |

---

## 3. Where secrets are removed

| Point | Explain | Find Bugs | Generate Tests | Code Review | Chat | Commit / PR Metadata |
|---|---|---|---|---|---|---|
| Before the LLM call | ✅ | ✅ | ✅ | ✅ | ✅ | N/A |
| In the API result | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| In saved history / DB | ✅ | ✅ | ✅ | ✅ | — | ✅ |
| In error messages / validation errors | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| In logs (handler filter) | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |

---

## 4. Day 7 sign-off checklist
- [x] #114 (Generate Tests security) merged
- [x] #115 (Code Review security) merged
- [x] Day 6 & Day 7 security audits merged
- [x] All security test files (`test_security_week2_baseline.py`, `test_security_explain.py`, `test_security_bugs.py`, `test_security_testgen.py`, `test_security_review.py`, `test_security_week2_audit.py`, `test_day6_integration_and_security.py`, `test_yug_w2_day7_final_acceptance.py`) pass 100%
- [x] Open items `W2-S8`, `W1-F1`, `W2-S3`, `W1-F4`, `W2-D7-S1`, `W2-D7-S2` remediated and verified
- [x] Zero Critical or High security items open — **APPROVED FOR WEEK 3 HANDOFF**
