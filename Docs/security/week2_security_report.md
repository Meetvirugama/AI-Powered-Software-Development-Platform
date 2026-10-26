# Week 2 Security Report — Developer Intelligence Suite

**Owner:** Sukun (Security and trust boundaries) · **Day:** W2 Day 6 (Security Audit) · **Date:** 2026-10-24
**Scope:** Explain Code, Find Bugs, Generate Tests, AI Code Review, analysis history, plus repository chat (Week 1) where it shares the same prompt path.
**Code audited:** `main` at `2236213` + open security PRs #114 (Day 4) and #115 (Day 5) + this PR.

---

## 1. Summary

> **Status: no open Critical or High issue once #114, #115 and this PR are merged.**
> Two Medium items remain open with owners (GitHub token in clone URL, Gemini key in request URL — both already masked in logs).

| Area (Docs/week2.md Day 6) | Result | Evidence |
|---|---|---|
| Prompt injection in code and docs | ✅ Pass | All 4 services + chat wrap repository data in a random `<<<REPO_DATA_…>>>` boundary; system prompts forbid following embedded instructions. Fixtures `CANARY-PI-001…008` never leave the boundary. Injected "report zero findings" cannot hide static findings. |
| Unauthorized repository access | ✅ Pass | Every analysis route resolves the repo with `_owned_repository` (user + repo) before any work → 404; services are never called. History list and `GET /analysis-runs/{id}` re-check ownership. |
| Path traversal | ✅ Pass | Targets, diff file paths and model citations go through `require_safe_repo_path` / `validate_repo_relative_path`. Proposed test paths also pass a test-file policy (#114). |
| Secret exposure | ✅ Pass (after merges) | Secrets redacted before the LLM call, in results, in saved history, in error messages and in logs. See §3. |
| Malformed model output | ✅ Pass | Invalid output → `500 ANALYSIS_FAILED`; failed runs are saved as `FAILED`, never as a zero-finding success. |
| Oversized input / bounded processing | ✅ Pass | 1 MB file limit (413), diff ≤ 200,000 chars, context 500–100,000 tokens, history `page_size` ≤ 100, 2 LLM attempts max, static scanners `timeout=60`. |
| Cross-repository analysis access | ✅ Pass | Retrieval filters by `repository_id`; another user's run id returns 404; commit/PR lookups only run for an owned repo. |
| Rate limiting | ✅ Pass | `explain`, `detect-bugs`, `generate-tests`, `review`: 20 req/min per user; chat 30; sync 5. |

---

## 2. Findings

| ID | Severity | Finding | Owner | Status |
|---|---|---|---|---|
| W2-S1 | 🔴 High | No secret redaction anywhere (carried over from W1 F-1). | Sukun | ✅ **Fixed** — `app/core/secret_redaction.py` + log filter (#107); explain (#108); bug scanner (#111); test generation (#114); code review (#115); shared prompt fence (this PR). |
| W2-S2 | 🟠 Medium | Error logs could include raw model output / exception text. | Sukun | ✅ **Fixed** (#107) — handler-level `SecretRedactingFilter`. |
| W2-S5 | 🟠 Medium | Test generation accepted any traversal-free path from the model, incl. `conftest.py`, `.github/workflows/…`, `setup.py` or the source file itself — exporting it would create auto-executed code. | Sukun / Yug | ✅ **Fixed in #114** — `check_generated_test_path`; falls back to the convention path with a warning. |
| W2-S6 | 🟠 Medium | Code review only checked line numbers for single-file targets; commit / PR / diff findings could cite lines that do not exist. | Sukun / Yug | ✅ **Fixed in #115** — `_max_known_line` bounds every target by indexed length and diff hunk ranges. |
| W2-S7 | 🟡 Low | Repository chat, summary and verifier prompts (Week 1 `PromptBuilder`) sent repository text to the LLM unredacted. | Sukun / Dev | ✅ **Fixed in this PR** — `_fence()` now redacts, so every prompt using it is covered. |
| W1-F2 | 🟠 Medium | GitHub installation token is placed in the clone URL (`https://x-access-token:<token>@…`) and stored in each clone's `.git/config`; failed clones log git's stderr. | Parth | ⏳ **Open** — use `git -c http.extraHeader=…` or `git remote set-url` after clone. Log output is already masked by the redaction filter (`url_credentials`). |
| W2-S8 | 🟠 Medium | Gemini API key is sent as `?key=` in the request URL, so it appears in httpx request logs and exception messages. | Meet | ⏳ **Open** — send it in the `x-goog-api-key` header. Mitigated: the log filter redacts `AIza…` keys. |
| W1-F1 | 🟡 Low (was High) | `code_chunks` still store raw file content; `/search` returns chunk text to the repository owner. Secrets no longer reach the LLM, results, history or logs. | Divu / Sukun | ⏳ **Open** — call `redact()` in the indexer before insert, then re-index. |
| W2-S3 | 🟡 Low | `static_reviewer.py` passes the target path right after scanner flags; a file name starting with `-` could be read as an option (paths are already validated). | Devu | ⏳ **Open** — add `"--"` before the path. |
| W1-F4 | 🟡 Low | `scanner/detector.py` opens `file_info.path` relative to the worker's working directory (indexer already fixed). | Prit | ⏳ **Open** |
| W1-F3 | 🟠 Medium | Workspace check used `str.startswith`. | Parth | ✅ **Fixed** — now `is_within()`. |
| W1-F6 | 🟡 Low | 403 vs 404 inconsistency for other users' repos. | Yug | ✅ **Fixed** — consistently 404. |

---

## 3. Where secrets are removed

| Point | Explain | Find Bugs | Generate Tests | Code Review | Chat |
|---|---|---|---|---|---|
| Before the LLM call | ✅ | ✅ | ✅ (#114) | ✅ (#115) | ✅ (this PR) |
| In the API result | ✅ | ✅ | ✅ | ✅ | — |
| In saved history (`record_analysis_run`) | ✅ | ✅ | ✅ | ✅ | — |
| In error messages / validation errors | ✅ | ✅ | ✅ | ✅ | — |
| In logs (handler filter) | ✅ | ✅ | ✅ | ✅ | ✅ |

Patterns: OpenAI `sk-…`, GitHub `ghp_/ghs_/github_pat_`, AWS `AKIA…`, Google `AIza…`, Groq `gsk_…`, Slack `xox…`, JWTs, private-key blocks, `user:pass@` in URLs, `Bearer` tokens, quoted `*KEY/SECRET/PASSWORD/TOKEN = "…"` and `.env`-style `KEY=value`.

---

## 4. Test evidence

| Test file | Covers |
|---|---|
| `tests/test_security_week2_baseline.py` | Redaction module, log filter, prompt fence, unsafe paths |
| `tests/test_security_explain.py` | Day 2 — Explain Code |
| `tests/test_security_bugs.py` | Day 3 — Find Bugs |
| `tests/test_security_testgen.py` | Day 4 — Generate Tests (#114) |
| `tests/test_security_review.py` | Day 5 — Code Review (#115) |
| `tests/test_security_week2_audit.py` | Day 6 — all 4 features: access, traversal, oversize, malformed output, cross-user history, chat redaction, rate-limit coverage |

```bash
python -m pytest backend/tests/test_security_week2_baseline.py backend/tests/test_security_explain.py \
  backend/tests/test_security_bugs.py backend/tests/test_security_testgen.py \
  backend/tests/test_security_review.py backend/tests/test_security_week2_audit.py -v --no-cov
```

> Tests for Days 3–6 were added through the GitHub website and have not yet been run locally; run the command above (or CI) before the Day 7 sign-off.

---

## 5. Day 7 sign-off checklist
- [ ] #114 (Generate Tests security) merged
- [ ] #115 (Code Review security) merged
- [ ] This PR (Day 6 audit) merged
- [ ] All security test files above pass
- [ ] Owners acknowledge open items W1-F2 (Parth), W2-S8 (Meet), W1-F1 (Divu), W2-S3 (Devu), W1-F4 (Prit)
- [ ] No Critical/High item open
