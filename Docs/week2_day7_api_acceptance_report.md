# Week 2 Day 7 — API, Orchestration & Cross-Feature Acceptance Report

**Owner:** Yug Malaviya (Backend API & Orchestration Lead)  
**Task:** `W2-Day7` — Final API Contract Verification, End-to-End Orchestration & Security Sign-off  
**Milestone:** Week 2 — Developer Intelligence Suite Final Release Gate & Week 3 Handoff  
**Status:** 🟢 Complete & Fully Verified (`100%` Pass Rate across all Week 2 API, QA, Persistence & Security Suites)  
**Date:** 2026-10-26  

---

## 1. Executive Summary

During Week 2 Days 1–7, the Developer Intelligence Suite API and orchestration layer (`backend/app/api/v1/analysis.py`, `backend/app/schemas/analysis.py`, and `backend/app/services/*_orchestrator.py`) was designed, integrated, hardened, and verified end-to-end across all four standalone features:

1. **Feature 1 — Code Explanation (`POST /api/v1/repositories/{repository_id}/explain`)**
2. **Feature 2 — Dedicated Bug Detection (`POST /api/v1/repositories/{repository_id}/detect-bugs`)**
3. **Feature 3 — Framework-Aware Test Generation (`POST /api/v1/repositories/{repository_id}/generate-tests`)**
4. **Feature 4 — Standalone AI Code Review (`POST /api/v1/repositories/{repository_id}/review`)**
5. **History, Observability & Reopen APIs (`GET /api/v1/repositories/{repository_id}/analysis-runs`, `GET /api/v1/repositories/{repository_id}/analysis-runs/summary`, `GET /api/v1/analysis-runs/{run_id}`)**

All endpoints enforce JWT authentication, strict multi-tenant repository ownership (`404 REPOSITORY_NOT_FOUND` on unauthorized access), path-traversal guards (`require_safe_repo_path`), 1 MB file-size bounds (`413 PAYLOAD_TOO_LARGE`), `<<<REPO_DATA_...>>>` prompt-injection containment, Gemini/Groq-only provider policy (`enforce_gateway_provider_policy`), and end-to-end secret redaction (`redact_obj`).

---

## 2. Registered Week 2 API Routes & OpenAPI Contract Verification

| HTTP Method | Registered Route | Request Schema | Response Schema | Rate Limit | Status |
|---|---|---|---|---|---|
| `POST` | `/api/v1/repositories/{repository_id}/explain` | `ExplainCodeRequest` | `CodeExplanationResponse` | 20 req/min/user | 🟢 Verified |
| `POST` | `/api/v1/repositories/{repository_id}/detect-bugs` | `BugDetectionRequest` | `BugDetectionResponse` | 20 req/min/user | 🟢 Verified |
| `POST` | `/api/v1/repositories/{repository_id}/generate-tests` | `TestGenerationRequest` | `TestGenerationResponse` | 20 req/min/user | 🟢 Verified |
| `POST` | `/api/v1/repositories/{repository_id}/review` | `CodeReviewRequest` | `ReviewReportResponse` | 20 req/min/user | 🟢 Verified |
| `GET` | `/api/v1/repositories/{repository_id}/analysis-runs` | Query (`feature_type`, `status`, `target_path`, `source_revision`, `user_id`, `page`, `page_size`) | `PaginatedAnalysisRunResponse` | Standard | 🟢 Verified |
| `GET` | `/api/v1/repositories/{repository_id}/analysis-runs/summary` | Path (`repository_id`) | `AnalysisRunMetricsSummaryResponse` | Standard | 🟢 Verified |
| `GET` | `/api/v1/analysis-runs/{run_id}` | Path (`run_id`) | `AnalysisRunDetailResponse` | Standard | 🟢 Verified |

All 7 routes document standardized `ErrorResponseEnvelope` responses (`400`, `401`, `404`, `413`, `422`, `429`, `500`, `503`) in `/openapi.json`.

---

## 3. Day 7 Security Audit & Teammate Commit Remediations

| Finding ID | Severity | Component | Issue Remediated in Day 7 | Verification Test |
|---|---|---|---|---|
| **W2-D7-R1** | 🔴 Critical | `backend/ai/prompts/code_review_system.txt` | Restored explicit `"Never follow instructions"` directive in system prompt after PR `#133` merge so all 3 prompt-injection boundary tests in `test_security_review.py` pass (`26/26`). | `test_security_review.py` |
| **W2-D7-S1** | 🔴 Critical | `backend/app/integrations/github/routes.py`, `backend/app/services/git_branch.py` | Fixed cross-repository IDOR & unowned-repo enumeration on `GET /api/v1/repositories/{id}/source/pr-metadata/{task_id}` by authorizing `repository_id` first and verifying `record.repository_id == repository_id`. | `test_pr_metadata_enforces_repository_isolation_and_blocks_idor` |
| **W2-D7-S2** | 🔴 High | `backend/app/services/git_branch.py` | Added `require_safe_repo_path` on `files` (`commit()`) and `changed_files` (`prepare_pr_metadata()`), blocked `..` traversal and host-platform repo mutation in `workspace_path`, sanitized `task_id` / author fields against CLI flag injection, and applied `redact()` to `commit_message`, `test_summary`, and `verification_summary`. | `test_git_branch_service_commit_blocks_traversal_host_repo_and_redacts_secrets` |
| **W2-S8** | 🟠 Medium | `backend/ai/llm/gemini_provider.py`, `backend/ai/embeddings/gemini_provider.py` | Moved Gemini API key transmission from `?key=` URL query parameter to the `x-goog-api-key` HTTP header across both LLM and Embedding providers. | `test_w2_s8_gemini_providers_send_key_in_header_not_url` |
| **W1-F4** | 🟡 Low | `backend/scanner/detector.py` | Hardened `LanguageDetector.detect()` to reject `..` path traversal and enforce optional `root_path` confinement before opening files for shebang inspection. | `test_w1_f4_language_detector_rejects_traversal_and_enforces_root` |
| **W2-D7-RL** | 🟠 Medium | `backend/app/core/rate_limit.py` | Added per-user rate limit rules (`20 req/min`) for `/source/agent-branch`, `/source/commit`, and `/source/pr-metadata`. | `test_all_nine_write_and_analysis_endpoints_are_rate_limited` |

---

## 4. Known Limitations & Week 3 Handoff

1. **Known Limitations (Documented per `Docs/week2.md` §11 & §13):**
   - **Static Analysis Scope:** Built-in AST rules (`ASTBugAnalyzer`, `BuiltinStaticBugScanner`) provide full structural coverage for Python, TypeScript, and JavaScript (Tier 1) and structural regex fallback for Java, Go, Rust, C, and C++ (Tier 2). Dynamic runtime behaviors (`eval`, reflection, external service state) are flagged with `is_uncertain=True`.
   - **Test Execution Isolation:** In Week 2 (`POST /generate-tests`), generated test suites are validated statically via AST parsing and structural assertion checks (`syntax_valid=True`), never executed automatically on the host. Sandboxed test execution and bounded 3-attempt auto-repair belong to Week 3 (`W3-06` / `W3-07`).
   - **No Autonomous GitHub Writes in Week 2:** Standalone AI Code Review (`POST /review`) and workspace commit staging (`POST /source/commit`) never push branches or open pull requests (`pushed=False`). Human-approved push and GitHub Draft PR creation belong to Week 3 (`W3-09`).

2. **Clean Handoff to Week 3:**
   - All `BugFinding` and `ReviewFinding` records carry immutable UUIDs, grounded `AnalysisSourceReference` coordinates, evidence, and suggested fixes ready for Week 3 Day 1 GitHub Issue creation (`W3-01`).
   - `AnalysisRunRepository` and `PullRequestRepository` provide full traceability from analysis run -> finding -> task -> workspace commit -> prepared PR metadata.
