# Week 3 Release Checklist: Security Sign-off

**Release:** Week 3 Workflow Automation (F31–F39)
**Prepared by:** Sukun (Security) · **QA owner:** Keval · **Day:** W3 Day 7 · **Date:** 2026-11-02
**Based on:** `Docs/week3.md` §10 (Release safety, Data integrity, Testing) and §11 (Acceptance scenarios)
**Details:** [`week3_threat_model.md`](week3_threat_model.md) · [`week3_security_report.md`](week3_security_report.md)

Status key: ✅ Done (with evidence) · ⚠️ Done with a known limitation · ❌ Not done

---

## 1. Release safety (`week3.md` §10)

| # | Requirement | Status | Evidence |
|---|---|---|---|
| 1 | No direct protected-branch push | ✅ | Blocked in tool bridge, orchestrator `/branch` `/commit` `/push` `/create-pr`, and `GitHubService.push_branch` (any case, `refs/heads/…`). Tests: `test_security_w3_publish.py::test_push_to_protected_branch_is_refused`, `test_security_w3_regression.py::test_protected_branch_still_reported_as_policy_violation` |
| 2 | No automatic merge or deployment | ✅ | Platform has no merge entry point; PRs are Draft only. Tests: `test_github_service_has_no_merge_entry_point`, `test_pull_requests_are_always_drafts_and_redacted` |
| 3 | No execution before required approval | ✅ | `verify_execution_approval_gate` (plan version + plan hash + base revision). Tests: `test_security_w3_approval.py` (execute, tools, stale plan, tampered plan) |
| 4 | No arbitrary shell execution outside the policy system | ✅ | Tool API policy (templates, argv rules, blocked tools, trusted-only args), git name validation. Tests: `test_security_w3_tools.py`, `test_security_w3_regression.py` |
| 5 | No unlimited repair loop | ✅ | 3-attempt budget stored in the database, survives restart, identical patches rejected. Tests: `test_security_w3_runner.py::test_repair_budget_*`, `test_api_repair_budget_cannot_be_exceeded_or_reset_by_restart` |
| 6 | No fake verification success | ⚠️ | Publication requires a passed verification. **But:** a failed `git push` is recorded as successful unless `strict_remote=true` (B13), and the Draft PR URL is built locally instead of by GitHub (B14). See §4 |
| 7 | No unreviewed security bypass | ✅ | All Week 3 security PRs reviewed: #166, #168, #169, #170, #171 |

## 2. Data integrity (security-relevant items)

| # | Requirement | Status | Evidence |
|---|---|---|---|
| 8 | Approvals refer to the correct plan version | ✅ | Plan revision cancels approval; stale version 409; tampered hash 409. Tests: `test_security_w3_approval.py` |
| 9 | Test and verification results refer to the correct revision | ⚠️ | Checked while the server runs; the post-verification diff hash is in memory only, so the check is skipped after a restart (B16) |
| 10 | External GitHub operations can be reconciled after uncertain outcomes | ⚠️ | Draft PR creation is idempotent per task; push failure handling see B13 |
| 11 | Sensitive data excluded from stored logs and checkpoints | ✅ | Secret redaction on logs, tool output, test output, events, checkpoints, PR title/body. Tests in all five `test_security_w3_*` files. Open: `code_chunks` still store raw file content (B6, Divu) |

## 3. Security testing

| # | Requirement | Status | Evidence |
|---|---|---|---|
| 12 | Security tests cover applicable failure paths | ✅ | 79 security test functions in 5 files (see report §4) |
| 13 | Week 1–2 security regression still passes | ⬜ | Pending QA test run (§6) |
| 14 | Acceptance scenario B (plan rejected) | ✅ | `test_execute_blocked_after_rejection` |
| 15 | Acceptance scenario C (plan changed after approval) | ✅ | `test_new_plan_version_cancels_previous_approval`, `test_tampered_plan_*` |
| 16 | Acceptance scenario D (repair exhaustion) | ✅ | `test_repair_budget_stops_at_three_attempts`, API budget test |
| 17 | Acceptance scenario E (malicious tool request) | ✅ | `test_api_blocks_*`, `test_api_tool_policy_refuses_dangerous_calls`, blocked calls are audited and redacted |
| 18 | Acceptance scenario H (worker restart) | ⚠️ | Repair budget and approval survive restart; see B16 for the verification hash |
| 19 | Acceptance scenario I (permission revoked) | ✅ | Other users get 404 on every task route, including Day 5–7 routes |

## 4. Known limitations accepted for this release

These must be listed in the demo and do **not** block the course release, provided they are disclosed.
They **do** block running the platform for untrusted users on a shared server.

| ID | Limitation | Owner | Severity |
|---|---|---|---|
| B3 | No network, CPU or memory limits for test commands | Prit | 🟠 |
| B8 | Child processes survive a command timeout | Prit | 🟠 |
| B4 | `/push` and `/create-pr` do not require a prior `/authorize-publication` for the current head SHA | Yug | 🟠 |
| B13 | Failed push recorded as success unless `strict_remote=true` | Yug | 🟠 |
| B14 | Draft PR URL built locally; owner fallback `Meetvirugama` | Yug / Parth | 🟡 |
| B16 | Verification diff hash not persisted across restart | Prit / Yug | 🟠 |
| B6 | Raw content in `code_chunks` | Divu | 🟡 |
| B15 | Workspace-level push/fetch do not validate their own inputs (API callers are validated) | Prit | 🟡 |

## 5. Conditions before sign-off

- [ ] #170 merged (B2: token out of git argv and errors)
- [ ] #171 merged (B11: git option injection, B12: recovery limits)
- [ ] Security tests pass locally (§6)
- [ ] Full test suite passes locally, or failures are listed with owners (§6)
- [ ] Owners of §4 items have acknowledged them

## 6. Test evidence

The security tests were written and syntax-checked but **not run by Security before sign-off**.
Keval (QA) runs them as part of the Day 7 acceptance run and records the result here.

Run from `backend/` on the latest `main` (after #170 and #171 are merged), Python 3.11:

```bash
python -m pytest tests/test_security_w3_approval.py tests/test_security_w3_tools.py tests/test_security_w3_runner.py tests/test_security_w3_publish.py tests/test_security_w3_regression.py -q --no-cov
python -m pytest -q --no-cov
```

| Run | Commit | Run by | Result |
|---|---|---|---|
| Week 3 security tests | | Keval | Not run yet |
| Full suite | | Keval | Not run yet |

Expected: 1 `xfailed` (`test_timeout_also_stops_child_processes`, known limitation B8). Any other failure
must be listed here with an owner before the QA sign-off.

## 7. Sign-off

| Role | Name | Decision | Date |
|---|---|---|---|
| Security | Sukun | **Approved with §4 limitations**, on condition that #170 and #171 are merged and the §6 test run passes | 2026-11-02 |
| QA | Keval | ☐ Approved · ☐ Approved with §4 limitations · ☐ Not approved (after the §6 test run) | |
