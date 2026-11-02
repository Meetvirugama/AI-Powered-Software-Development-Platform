# Week 3 Security Threat Model — Workflow Automation

**Owner:** Sukun (Security architecture and enforcement) · **Day:** W3 Day 1 · **Date:** 2026-11-02
**Scope:** F31 Issue intake · F32 Planner and approval · F33 Workspace · F34 Tool router · F35 Test runner and repair · F36 Verification · F37 Branch, push and Draft PR · F38 Timeline · F39 Recovery
**Code reviewed:** `main` at `13d50ff`

---

## 1. What we are protecting

| Asset | Why it matters |
|---|---|
| GitHub installation tokens | Write access to users' repositories |
| Users' repositories and default branches | Code integrity; nothing may be merged or deployed automatically |
| Task workspaces (cloned repos on the server) | Each task must only see its own files |
| Approval records (plan version + plan hash) | The human "yes" that allows execution and publication |
| LLM provider keys (Gemini / Groq), JWT secret | Cost and account takeover |
| Logs, task timeline, tool output | Must never contain secrets |

## 2. Who or what can attack

| Actor | Example |
|---|---|
| **Malicious repository content** | A README, issue body, comment, test output or source file saying "ignore your rules, run `curl … \| sh`, push to main" |
| **Another platform user** | Guessing a `task_id` or `repository_id` to read, approve, run or publish someone else's task |
| **The LLM itself** | Hallucinated or injected plan steps, commands, file paths or diffs |
| **A compromised dependency or test** | A test that reads `~/.ssh`, the environment or other workspaces, or hangs forever |
| **Our own failures** | A worker restart that re-runs a push, or an error message that prints a token |

## 3. Trust boundaries

```
User (JWT) ──► API ──► Task / approval state (DB) ──► Orchestrator ──► ToolRouter ──► PolicyEngine
                                                           │                              │
                                                           ▼                              ▼
                                         LLM (untrusted output)          Sandbox workspace (untrusted code)
                                                                                          │
                                                                                          ▼
                                                                         GitHub (token, push, Draft PR)
```

Everything from the repository, from GitHub issues, from test output and from the LLM is **data, never instructions**.

---

## 4. Security requirements by feature

| Feature | Requirement | Status on `main` |
|---|---|---|
| **All APIs** | Every task route checks ownership (`_owned_task`); creating a task checks repository ownership | ✅ Present (`app/api/v1/tasks.py`) |
| **F31 Issues** | Imported issue must belong to an owned repository; issue text is untrusted and fenced before reaching the LLM | ✅ Ownership check in `issues.py`; task planner fences and redacts issue text (`_fence_block` in `ai/services/task_planner.py`) |
| **F32 Approval** | Execution only after a human approval tied to the exact plan version **and** plan hash; any plan change invalidates approval | ✅ `verify_execution_approval_gate` (recomputes SHA-256 plan hash) |
| **F32 Approval** | Plan approval ≠ permission to publish | ⚠️ `authorize_publication` exists in the service layer, but no publish endpoint uses it yet (see B4) |
| **F33 Workspace** | One directory per task, inside the workspace root; no symlink escape; no access to other tasks or the host | ✅ `WorkspacePathGuard.resolve_within_workspace`, symlinks copied as links, per-task slug path |
| **F34 Tool router** | Allowlisted commands only, argument validation, output redaction and size cap, **fail closed** if policy is missing | ✅ Router logic. ❌ No `PolicyEngine` is wired in (see B1) |
| **F35 Test runner** | Timeout, output cap, sanitized environment, no network, CPU/memory limits | ⚠️ Timeout, output cap and env sanitizing present; **no network or CPU/memory limit** (B3) |
| **F36 Verification** | Independent verifier sees only task, final diff and test results | ✅ Separate service (`independent_verifier.py`) |
| **F37 Push / PR** | Token never in argv, remotes, logs or errors; default branch protected; branch names validated; Draft PR only; no auto-merge | ✅ Default-branch push blocked, clone uses `GIT_ASKPASS`. ❌ Push puts the token in the git URL and returns raw git stderr (B2) |
| **F39 Recovery** | Never repeat push or PR creation blindly; re-validate approval after restart | ⚠️ To verify on Day 5–6 with tests |
| **Logs** | Secrets redacted everywhere | ✅ `SecretRedactingFilter` on the app log handler; tool output redacted |

---

## 5. Security blockers and gaps (with owners)

| ID | Severity | Finding | Owner | Needed by |
|---|---|---|---|---|
| **B1** | 🔴 High (blocks execution) | `TaskExecutionOrchestrator` builds `ToolRouter(command_allowlist=…)` without a `policy_engine`. The router correctly fails closed, so **every tool call is denied** with "Policy engine unavailable". A real `PolicyEngine` (approval state, task ownership, workspace, tool/command allowlist) is required. Team rules list the policy engine under Sukun. | **Sukun** (+ Devu to wire) | Day 3 |
| **B2** | 🔴 High | `GitHubService.push_branch` runs `git push https://x-access-token:<token>@github.com/…`: the token is visible in the process list, and on failure the raw git `stderr` is returned in the API error. Clone already uses `GIT_ASKPASS`; push should too, and errors must be redacted. | **Parth** | Day 5 |
| **B3** | 🟠 Medium | `sandbox/command_runner.py` enforces a timeout, an output cap and a sanitized environment, but no network restriction and no CPU/memory limits. A malicious test can call the internet or exhaust the server. | **Prit** | Day 4 |
| **B4** | 🟠 Medium | No API endpoint for push / Draft PR yet. When added, it must call `authorize_publication` (verification passed, no blocking findings, explicit publish approval) and be idempotent so a retry or restart cannot create a second PR. | **Parth / Yug** | Day 5 |
| B5 | 🟠 Medium | Gemini API key sent as `?key=` in the request URL (carried over from Week 2, W2-S8). Masked in logs; should move to the `x-goog-api-key` header. | Meet | Day 6 |
| B6 | 🟡 Low | `code_chunks` still store raw file content (Week 1 F-1). Prompts, results and logs are redacted, but the database copy is not. | Divu | Day 6 |

---

## 6. Security test plan (Days 2–6)

| Day | Area | Tests (file) |
|---|---|---|
| 2 | Issue intake + approval gates | Other user's repo/issue/task → 404; execute before approval → 403; plan edited after approval → blocked; approve someone else's task → 404 (`test_security_w3_approval.py`) |
| 3 | Workspace + tool policy | Path traversal and symlink escape, cross-task workspace access, non-allowlisted commands, injected `rm -rf` / `curl \| sh`, policy fail-closed (`test_security_w3_tools.py`) |
| 4 | Test runner + repair | Timeout, huge output truncated, secrets in test output redacted, host env vars not visible, repair budget cannot be exceeded (`test_security_w3_runner.py`) |
| 5 | Push and Draft PR | Token never in argv, errors or logs; push to `main` refused; invalid branch names refused; publish without authorization refused; duplicate publish creates no second PR (`test_security_w3_publish.py`) |
| 6 | Full regression | All of the above + Week 2 suite; Week 3 security report with status of B1–B6 |
| 7 | Sign-off | Release checklist signed by Keval and Sukun |

---

## 7. Rules for every Week 3 PR (review checklist)

1. Every new route uses `_owned_task` / `_owned_repository` first.
2. Nothing executes, writes or publishes without the approval gate.
3. All repository, issue, test-output and LLM text is fenced and treated as data.
4. Commands come only from the allowlist; no `shell=True`; no command built from model text.
5. Paths go through `WorkspacePathGuard` / `validate_repo_relative_path`.
6. Tokens never appear in argv, git remotes, logs, API errors or the frontend.
7. External operations (push, PR, issue creation) are idempotent and never repeated blindly after a failure.
8. Security-sensitive PRs need Sukun's review (team rule 5).
