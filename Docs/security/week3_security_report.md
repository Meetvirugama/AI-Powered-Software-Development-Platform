# Week 3 Security Report: Workflow Automation

**Owner:** Sukun (Security architecture and enforcement) · **Day:** W3 Day 6 · **Date:** 2026-11-02
**Scope:** F31–F39 (issue intake → planning and approval → workspace → tools → tests and repair → verification → branch, push and Draft PR → timeline → recovery)
**Code reviewed:** `main` after merging #164, #165, #166, #168 and #169, plus open PR #170 (Day 5)
**Threat model:** [`week3_threat_model.md`](week3_threat_model.md)

---

## 1. Summary

Week 3 lets the platform change code and publish Draft PRs, so the main risks were:
another user touching a task, code running before a human approves, untrusted text or tools
escaping the sandbox, and GitHub tokens leaking or being used to push where they should not.

| Area | Result |
|---|---|
| Task ownership (every task route) | ✅ Other users get 404 on all routes, including the Day 5–7 routes |
| Human approval gate | ✅ Nothing executes before approval of the exact plan version and hash |
| Tool API | ✅ Fixed this week: publication and admin tools blocked, trusted-only arguments refused, commands limited to approved templates |
| Test runner and repair | ✅ Fixed this week: unsafe runner arguments and repair writes to protected files are blocked; budget of 3 is enforced |
| Git push and Draft PR | ✅ Token kept out of argv and errors, branch names validated, Draft only (**#170 must be merged**) |
| Git argument injection in Day 5–7 endpoints | ✅ Fixed in this PR (Day 6) |
| Recovery | ✅ Fixed in this PR: recovery can no longer skip ahead to verification or publication |
| Sandbox resource limits | ⚠️ Still open (no network, CPU or memory limits; child processes survive timeouts) |

**Release recommendation:** OK for the course demo and internal testing once #170 and this PR are merged.
Before letting untrusted users run code on a shared server, B3 and B8 (sandbox limits) must be fixed.

---

## 2. Work delivered

| Day | Deliverable | PR | Status |
|---|---|---|---|
| 1 | Threat model and PR review checklist | (commit `deb883d`) | ✅ In main |
| 2 | Approval gate and issue intake tests (`test_security_w3_approval.py`) | #166 | ✅ Merged |
| 3 | API tool policy (`app/core/tool_api_policy.py`) and tool tests (`test_security_w3_tools.py`) | #168 | ✅ Merged |
| 4 | Repair validator fix (`repair_service.py`), runner tests (`test_security_w3_runner.py`) | #169 | ✅ Merged |
| 5 | Secure `git push` and Draft PR (`integrations/github/service.py`), publish tests (`test_security_w3_publish.py`) | #170 | ⏳ Waiting for review |
| 6 | Git name validation and recovery limits (orchestrator and tool policy), regression tests (`test_security_w3_regression.py`), this report | this PR | ⏳ |

---

## 3. Findings and status

Severity: 🔴 High · 🟠 Medium · 🟡 Low

| ID | Sev | Finding | Owner | Status |
|---|---|---|---|---|
| B1 | 🔴 | Tool router had no policy engine, so all tools were denied | Prit / Devu | ✅ Resolved: `WorkspaceToolPolicyBridge` |
| B2 | 🔴 | `push_branch` put the token in the git URL (visible in the process list) and returned raw git errors | Parth / Sukun | ✅ Fixed in #170 (pending merge) |
| B3 | 🟠 | Test commands have no network, CPU or memory limits | Prit | ⚠️ Open |
| B4 | 🟠 | Publication must need explicit human authorization | Yug | ⚠️ Partly done: `/push` and `/create-pr` require `publication_authorized=true` **and** passed verification, but do not check that `/authorize-publication` was called for the current head SHA |
| B5 | 🟠 | Gemini API key sent in the URL | Meet | ✅ Resolved: `x-goog-api-key` header |
| B6 | 🟡 | `code_chunks` store raw file content (may include secrets) | Divu | ⚠️ Open (not re-checked this week) |
| B7 | 🔴 | Tool API trusted caller values: `publication_authorized`, `remote_url` (`--receive-pack=` → command execution), `task_id`, admin tools, any allowlisted binary with any arguments | Sukun | ✅ Fixed in #168 |
| B8 | 🟠 | On timeout only the main process is killed; child processes keep running | Prit | ⚠️ Open (xfail test documents it) |
| B9 | 🟠 | `/tests` passed caller arguments to pytest unchecked (`../other-task`, `/etc`, `--rootdir`) | Sukun | ✅ Fixed in #168 |
| B10 | 🟠 | Repair could write a protected file by naming it in `target_files`; forbidden check was case-sensitive | Sukun | ✅ Fixed in #169 |
| B11 | 🔴 | **Git option injection in Day 5–7 endpoints:** `/push` sent `remote_name` and `branch_name` straight to `git push` (`--receive-pack=<cmd>` runs a command on the server); `/branch`, `/commit`, `/create-pr` and the `check_stale_revision` tool (`base_branch` → `git fetch`) had the same issue; `/commit` `files` could be git options | Sukun | ✅ Fixed in this PR |
| B12 | 🟠 | `/recover` accepted any `target_status`, so a task could jump to `VERIFYING` or `READY_FOR_PUBLICATION` | Sukun | ✅ Fixed in this PR: only `PLANNING`, `APPROVED` or `CANCELLED` |
| B13 | 🟠 | `push_verified_branch` records a **successful** push when the real push fails (unless `strict_remote=true`) | Yug | ⚠️ Open: should be strict by default in production |
| B14 | 🟡 | `WorkspaceManager.create_draft_pr` builds the PR URL locally instead of calling GitHub; Draft PR owner falls back to `Meetvirugama` when the task has no repository | Yug / Parth | ⚠️ Open: wire to `GitHubService.create_pull_request` (now Draft-only and validated) and remove the fallback |
| B15 | 🟡 | `WorkspaceManager.push_task_branch` and `detect_stale_base_revision` do not validate `remote_url` / `remote_name` / branch themselves (all API paths are now validated before them) | Prit | ⚠️ Open (defense in depth) |
| B16 | 🟠 | The post-verification diff hash is kept only in memory; after a restart the "no edits after verification" check is skipped | Prit / Yug | ⚠️ Open: store it with the verification result |

---

## 4. Security tests

All tests run with SQLite in memory and need no network.

| File | Tests | What it covers |
|---|---|---|
| `test_security_w3_approval.py` | 17 | Ownership on all task routes, issue import into another user's repository, execute and tools blocked before approval, stale and tampered plans, secret redaction, planner fencing |
| `test_security_w3_tools.py` | 20 | Path traversal and symlink escape, task isolation, command allowlist, host secrets removed from the environment, router fails closed, API tool policy end to end, unsafe test-runner arguments |
| `test_security_w3_runner.py` | 20 | Timeout and cap, output truncation, secrets in test output redacted, host environment hidden, test runner validation, repair budget (3, per task, survives restart), repair cannot write protected or outside files |
| `test_security_w3_publish.py` | 10 | Token never in git argv, URL or errors, protected branches, branch, owner and repo injection, no hooks or force push, Draft-only PRs with redacted text, no merge entry point |
| `test_security_w3_regression.py` | 12 | Day 5–7 routes: ownership, publication needs authorization and verification, git name injection, safe commit paths, recovery limits, tool policy for git names |

(Counts are test functions; parametrized cases make the actual number of test runs larger.)

Run locally from `backend/` with the Python 3.11 virtual environment:

```bash
python -m pytest tests/test_security_w3_approval.py tests/test_security_w3_tools.py \
  tests/test_security_w3_runner.py tests/test_security_w3_publish.py \
  tests/test_security_w3_regression.py -q --no-cov
```

Then the full suite (Week 1–3 regression):

```bash
python -m pytest -q --no-cov
```

---

## 5. Review checklist status (from the threat model)

| Rule | Status |
|---|---|
| 1. Every route checks ownership first | ✅ Tested on all task routes |
| 2. Nothing executes, writes or publishes without the approval gate | ✅ Execute, tools, branch, commit and run-workflow check it; publication also needs verification and authorization |
| 3. Repository, issue, test and LLM text is fenced and treated as data | ✅ Planner fencing and redaction tested |
| 4. Allowlisted commands only, no `shell=True`, no commands built from model text | ✅ Tool API enforces templates; runner uses an argument list |
| 5. Paths go through `WorkspacePathGuard` / `validate_repo_relative_path` | ✅ File tools, repair targets, commit files and runner arguments |
| 6. Tokens never in argv, remotes, logs, errors or the frontend | ✅ After #170 (`push_branch`); clone already used `GIT_ASKPASS` |
| 7. External operations are idempotent and never repeated blindly | ⚠️ Draft PR is idempotent per task; see B13 for the push |
| 8. Security-sensitive PRs reviewed by Sukun | ✅ |

---

## 6. Before release sign-off (Day 7)

- [ ] Merge #170 (B2) and this PR (B11, B12)
- [ ] Full test suite passes locally
- [ ] Owners acknowledge open items: B3, B8 (Prit) · B4, B13, B14 (Yug, Parth) · B6 (Divu) · B15, B16 (Prit, Yug)
- [ ] Release checklist signed by Keval and Sukun
