# F25 — Independent Verification Architecture & Verification Report (Issue #206)

> **Version:** 1.0  
> **Date:** 2026-11-14  
> **Author:** Om (`OM202401238`)  
> **Status:** APPROVED & TESTED (19/19 Unit & Integration Tests Passing)  
> **Target Issue:** [#206 — F25: Independent Verification](https://github.com/Meetvirugama/AI-Powered-Software-Development-Platform/issues/206)

---

## 1. Executive Summary

This deliverable resolves **GitHub Issue #206 (F25 — Independent Verification)** by establishing a defense-in-depth verification pipeline across all automated code changes before publication or draft pull request creation.

Two major security and correctness pillars have been implemented:
1. **Secondary Secret Engine (Gitleaks Integration):** A dedicated `GitleaksDiffScanner` operates across staged diffs alongside the primary regex redaction engine. It leverages native `gitleaks` CLI execution when installed, and gracefully falls back to a high-speed built-in Gitleaks-standard rules engine covering AWS access keys, GitHub PAT/OAuth tokens, Slack webhooks, Private RSA/OpenSSH keys, OpenAI/Anthropic keys, Stripe API keys, and generic credential patterns. It honors `.gitleaks.toml` path/allowlist configurations and redacts all leaked token previews.
2. **P-28 LLM-as-Judge Requirement Verification:** Evaluates each task requirement and acceptance criterion against candidate workspace diff hunks. Every verified criterion is backed by structured evidence (`CriterionJudgeEvidence`) containing specific line-indexed diff hunk citations (`DiffHunkCitation` with `Lstart-Lend`, headers, and code snippets). This prevents reward hacking and hallucinated completions, ensuring code changes demonstrably satisfy human intent before a pull request can be prepared.

---

## 2. Architecture & Pipeline Overview

```
                      ┌────────────────────────────────────────┐
                      │    Workspace Unified Diff (git diff)   │
                      └──────────────────┬─────────────────────┘
                                         │
                 ┌───────────────────────┴───────────────────────┐
                 │                                               │
                 ▼                                               ▼
   ┌───────────────────────────┐                   ┌───────────────────────────┐
   │   Primary Secret Engine   │                   │  Secondary Secret Engine  │
   │  (Regex Redaction Engine) │                   │   (GitleaksDiffScanner)   │
   └─────────────┬─────────────┘                   └─────────────┬─────────────┘
                 │                                               │
                 └───────────────────────┬───────────────────────┘
                                         ▼
                 ┌───────────────────────────────────────────────┐
                 │       Dual-Engine Secret Gate (SEC-001)       │
                 │   - Blocks PR if either engine detects leak   │
                 │   - Deduplicates findings & logs telemetry    │
                 └───────────────────────┬───────────────────────┘
                                         │ Clean Diff
                                         ▼
                 ┌───────────────────────────────────────────────┐
                 │     Diff Hunk Extractor (1-indexed lines)     │
                 │   extract_diff_hunks_from_diff() -> Citations │
                 └───────────────────────┬───────────────────────┘
                                         │
                                         ▼
                 ┌───────────────────────────────────────────────┐
                 │      P-28 LLM-as-Judge Requirement Engine     │
                 │              (LLMRequirementJudge)            │
                 │  - Evaluates criteria against candidate hunks │
                 │  - Emits CriterionJudgeEvidence with citations│
                 └───────────────────────┬───────────────────────┘
                                         │
                                         ▼
                 ┌───────────────────────────────────────────────┐
                 │       IndependentVerifier Report Summary      │
                 │   - 12 Verification Gates + P-28 Judge Check  │
                 │   - PR Markdown with Diff Citations Table     │
                 └───────────────────────────────────────────────┘
```

---

## 3. Pillar 1: Secondary Secret Engine (`GitleaksDiffScanner`)

### 3.1 Design Principles
- **Dual-Engine Redundancy:** Diff verification does not rely on a single regex scanner. Both `redact_secrets` and `GitleaksDiffScanner` inspect diff additions independently.
- **Graceful Fallback:** If the native `gitleaks` CLI binary is not present on the host environment PATH, the scanner seamlessly switches to built-in rules without failing or halting the pipeline.
- **Accurate Line Tracking:** Correctly tracks unified diff headers (`@@ -old,len +new,len @@`) and context lines (` `) so that flagged secrets map to the exact file line numbers.
- **Benign Placeholder Allowlisting:** Respects `.gitleaks.toml` custom configurations and skips benign documentation examples (e.g. `[REDACTED]`, `<YOUR_API_KEY>`, `os.environ.get(...)`) to eliminate false positives in test fixtures and docs.

### 3.2 Canonical Rule Coverage
| Rule Identifier | Target Secret Category | Match Pattern Example |
|---|---|---|
| `gitleaks:aws-access-key-id` | AWS IAM & STS Credentials | `AKIAIOSFODNN7EXAMPLE` |
| `gitleaks:aws-secret-access-key` | AWS Secret Keys | `aws_secret_access_key = "..."` (40 chars) |
| `gitleaks:github-pat` | GitHub Personal Access Tokens | `ghp_...` (36 chars) / `github_pat_...` |
| `gitleaks:github-token` | GitHub OAuth / Refresh / Action tokens | `gho_...`, `ghu_...`, `ghs_...`, `ghr_...` |
| `gitleaks:openai-api-key` | OpenAI / Anthropic API Keys | `sk-proj-...`, `sk-ant-...` |
| `gitleaks:slack-webhook` | Slack Incoming Webhook URLs | `https://hooks.slack.com/services/T.../B.../...` |
| `gitleaks:private-key` | RSA / DSA / EC / OpenSSH Private Keys | `-----BEGIN RSA PRIVATE KEY-----` |
| `gitleaks:stripe-api-key` | Stripe Test & Live Secret Keys | `sk_live_...`, `sk_test_...` |
| `gitleaks:generic-api-key` | Generic high-entropy API tokens | `api_key = "..."`, `secret = "..."` |

---

## 4. Pillar 2: P-28 LLM-as-Judge Requirement Verification

### 4.1 Schema Definitions
In `backend/app/schemas/verification.py`:
- `DiffHunkCitation`: Captures file location, line bounds (`line_range="L10-L25"`), unified hunk headers (`@@ -10,5 +10,15 @@`), and representative diff snippets.
- `CriterionJudgeEvidence`: Structured evaluation containing:
  - `criterion_id`: Identifier of the acceptance criterion.
  - `requirement_id`: Parent task requirement identifier.
  - `verdict`: `"PASS"`, `"FAIL"`, `"PARTIAL"`, `"INCONCLUSIVE"`, or `"UNMET"`.
  - `confidence`: Calibrated score between `0.0` and `1.0`.
  - `reasoning`: Objective justification explaining how diff hunks substantiate the criterion.
  - `citations`: List of `DiffHunkCitation` objects.
  - `judge_model`: Model descriptor (`"llm-judge-p28"`).

### 4.2 Citation Extraction Algorithm
The function `extract_diff_hunks_from_diff` accepts:
- Raw unified git diff strings (`str`).
- `WorkspaceDiffResult` containing `FileDiffSummary` and `FileDiffHunk`.
- `TaskDiffRanges` with AST-compatible `LineRange` objects.
- Raw file dictionaries.

Each hunk is normalized to 1-indexed line spans (`Lstart-Lend`), allowing direct traceability from high-level user requirements to concrete code changes.

### 4.3 PR Summary Presentation
The Markdown PR summary automatically renders a dedicated audit table:

```markdown
### 📋 P-28 Acceptance Criteria Citations (LLM-as-Judge)
| Requirement | Criterion | Verdict | Confidence | Cited Diff Hunks |
| :--- | :--- | :--- | :--- | :--- |
| `req-auth` | Generate secure random token | `PASS` | 94.0% | `src/auth.py#L1-L15` |
| `req-auth` | Validate bearer header | `PASS` | 94.0% | `src/auth.py#L1-L15` |
```

---

## 5. Verification & Test Matrix

The complete test suite in `backend/tests/test_independent_verification_f25.py` executes **19 automated unit and integration tests**:

| Test Group | Test Case | Target Capability | Result |
|---|---|---|:---:|
| **Gitleaks Scanner** | `test_gitleaks_cli_availability_flag` | Detects host CLI availability without error | ✅ PASS |
| | `test_detects_aws_access_key` | Detects AWS Key ID in diff additions | ✅ PASS |
| | `test_detects_github_pat` | Detects GitHub PAT with accurate line number | ✅ PASS |
| | `test_detects_slack_webhook` | Detects Slack webhook URLs | ✅ PASS |
| | `test_detects_private_key` | Detects embedded PEM private keys | ✅ PASS |
| | `test_detects_openai_key` | Detects OpenAI `sk-proj` secret keys | ✅ PASS |
| | `test_ignores_allowlisted_placeholders` | Skips `[REDACTED]`, `<YOUR_KEY>`, and comments | ✅ PASS |
| | `test_ignores_deleted_lines_with_secrets` | Deleted lines do not trigger false alerts | ✅ PASS |
| **Diff Hunks** | `test_extract_hunks_from_unified_diff_string` | Parses multi-file unified git diff text | ✅ PASS |
| | `test_extract_hunks_from_workspace_diff_result` | Parses `WorkspaceDiffResult` & `FileDiffHunk` | ✅ PASS |
| | `test_extract_hunks_from_task_diff_ranges` | Parses `TaskDiffRanges` & `LineRange` | ✅ PASS |
| **LLM-as-Judge** | `test_judge_evaluates_criterion_matching_hunks` | `PASS` verdict with high confidence and citations | ✅ PASS |
| | `test_judge_evaluates_unmet_when_no_matching_diff` | `UNMET` verdict when target diff hunks missing | ✅ PASS |
| | `test_judge_fails_on_test_failure` | `FAIL` verdict on associated test run failures | ✅ PASS |
| **Verifier Integration** | `test_verifier_produces_criteria_evidence_and_markdown` | `RequirementToCodeVerifier` emits citations | ✅ PASS |
| | `test_secret_scan_dual_engine_detects_credentials` | `IndependentVerifier` dual-engine blocks secrets | ✅ PASS |
| | `test_secret_scan_dual_engine_passes_on_clean_diff` | `IndependentVerifier` passes clean diffs | ✅ PASS |
| | `test_p28_llm_judge_check_in_independent_verifier` | Check 13 runs and formats PR markdown table | ✅ PASS |
| **Diff Verifier** | `test_workspace_diff_verifier_detects_secrets_with_gitleaks` | `WorkspaceDiffVerifier` secondary engine check | ✅ PASS |

**Test Execution Time:** 0.15s (100% passing).  
**Regression Test Results:** `test_dev_w3_day5_verification.py` (14/14 passed), `test_meet_w3_all_days.py` (passed).
