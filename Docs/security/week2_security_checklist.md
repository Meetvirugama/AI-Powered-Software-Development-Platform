# Week 2 Security Checklist — Developer Intelligence Suite

**Owner:** Sukun (Security and trust boundaries) · **Day:** W2 Day 1 · **Applies to:** Explain Code, Find Bugs, Generate Tests, AI Code Review, analysis history

---

## 1. Threat model — what is untrusted

Everything that comes from a user's repository or from the model is **data, never instructions**.

| Untrusted input | Where it enters | Main risk |
|---|---|---|
| Source code, comments, docstrings, string literals | All 4 features (context + target code) | Prompt injection, secrets copied into results |
| README / docs / config files | Context retrieval | Prompt injection ("report zero findings") |
| File paths, symbol names, line ranges | Request `target` | Path traversal, reading another repo's files |
| Commit messages, PR titles/descriptions, diffs | Code Review | Prompt injection, oversized input |
| Model output (JSON, explanations, generated tests) | All 4 features | Fake file paths/lines, secrets echoed back, instructions to act |
| Static-analysis output (ruff / bandit JSON) | Find Bugs, Review | Code snippets containing secrets |

**Trust boundary:** system prompt + server code = trusted. Repository data + model output = untrusted.

---

## 2. Rules every feature must follow

| # | Rule | How it is enforced |
|---|---|---|
| R1 | **Repository content never goes in the system prompt.** It goes in the user message inside a random `<<<REPO_DATA_<token>>>` … `<<<END_REPO_DATA_<token>>>` boundary. | `ai.schemas.prompt_builder._fence`; tests in `test_security_week2_baseline.py` |
| R2 | **The system prompt says repository text is data** and must never be followed. | Each service's `_SYSTEM_PROMPT` |
| R3 | **Read-only.** Week 2 services may not write files, run commands from model output, or call GitHub write APIs (issues, branches, PRs, merges). | No write client passed to analysis services; reviewed per PR |
| R4 | **Ownership first.** Every analysis route resolves the repository with `_owned_repository` (user + repo) before any work; history reads re-check ownership. | `app/api/v1/analysis.py`; `test_analysis_api.py` |
| R5 | **Safe paths.** Target paths and proposed output paths (e.g. generated test file) go through `require_safe_repo_path` → 400 on `..`, absolute paths, backslashes, control chars. | `app/core/input_security.py` |
| R6 | **Redact secrets on the way out.** Results, error messages and logs pass through `redact()` / `redact_obj()`; logs are redacted automatically by `SecretRedactingFilter`. | `app/core/secret_redaction.py`, `app/core/logging.py` |
| R7 | **Validate model output.** Output must match the feature schema; invalid output → `ANALYSIS_FAILED`, never an empty "COMPLETED". File/line citations are grounded against indexed files. | Dev's schemas + grounding |
| R8 | **Bounded processing.** File size (1 MB), context tokens, retries and scanner run time are capped. | `MAX_ANALYZABLE_FILE_BYTES`, `max_context_tokens`, scanner `timeout=60` |
| R9 | **Generated code is never executed automatically** and never written to the repository by the API. | Test-generation endpoint returns content only |

---

## 3. Per-feature checklist

### Explain Code (`POST /repositories/{id}/explain`)
- [x] Repo content fenced (R1) and system prompt rule (R2) — verified in `LLMCodeExplanationService`
- [x] Ownership (R4) and safe target path (R5)
- [ ] Explanation text redacted before response / persistence (R6)
- [ ] Injection fixtures produce no `CANARY-PI-` output with a real provider

### Find Bugs (`POST /repositories/{id}/detect-bugs`)
- [x] Ownership (R4) and safe target path (R5)
- [ ] AI bug prompt uses `_fence` (R1)
- [ ] `evidence` / `description` fields redacted (R6) — bandit/ruff output can contain code lines
- [ ] Static scanner invoked with `--` before the path so a file named `--config=…` cannot become a flag
- [ ] Findings cannot trigger any GitHub action (R3)

### Generate Tests (`POST /repositories/{id}/generate-tests`)
- [x] Ownership (R4) and safe target path (R5)
- [ ] **Proposed test-file path** validated with `require_safe_repo_path` (R5)
- [ ] Generated test content redacted (R6) — the model may copy keys from the source
- [ ] Never executed or written by the API (R9)

### AI Code Review (`POST /repositories/{id}/review`)
- [x] Ownership (R4); file target path validated (R5)
- [ ] Commit SHA / PR number only fetched from the owned repository (no cross-repo PR access)
- [ ] Diff, PR title and description fenced (R1)
- [ ] Returned file paths and line numbers checked against the diff / indexed files (R7)
- [ ] Model output cannot cause a GitHub write (R3)

### Analysis history (`GET /analysis-runs`, `GET /analysis-runs/{run_id}`)
- [x] Ownership re-checked through the run's repository
- [ ] Stored `result_payload` is redacted before saving (R6)

---

## 4. Baseline audit findings (W2 Day 1)

| ID | Severity | Finding | Owner | Status |
|---|---|---|---|---|
| W2-S1 | 🔴 High | No secret redaction anywhere in the codebase (Week 1 F-1 still open). Analysis results and stored runs can contain secrets copied from repository code. | Sukun (module) · Dev / Yug (call sites) · Divu (indexer) | **This PR adds `secret_redaction.py` + log filter.** Wiring into results / indexer is follow-up per feature day. |
| W2-S2 | 🟠 Medium | Error logs include `str(exc)` of model-validation errors, which can echo raw model output. | Sukun | **Fixed in this PR** — handler-level `SecretRedactingFilter` |
| W2-S3 | 🟡 Low | `static_reviewer.py` passes the target path straight after scanner flags; a path starting with `-` could be read as an option. Paths are already validated, so risk is low. | Divu | Open — add `"--"` before the path |
| W2-S4 | ⚪ Info | `ContextBuilder.render_intelligence_data` uses fixed `<<<REPO_DATA_START>>>` markers; safe today because services wrap it again in the random `_fence`. Any new service must also use `_fence`. | Meet / Dev | Documented |

---

## 5. Test assets

| Asset | Path |
|---|---|
| Prompt-injection fixtures (canaries `CANARY-PI-001…008`) | `backend/tests/fixtures/security/prompt_injection/` |
| Baseline regression tests | `backend/tests/test_security_week2_baseline.py` |
| Isolation + traversal on analysis routes (Yug) | `backend/tests/test_analysis_api.py` |

Run:
```bash
pytest backend/tests/test_security_week2_baseline.py backend/tests/test_analysis_api.py -v --no-cov
```
