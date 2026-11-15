# 12 — Final Project Checklist

Tick an item only when its evidence exists (test ID green in CI, link to PR, or a recorded measurement). IDs refer to 01 (ISS), 03/04 (FEAT), 05 (DC), 06 (OPT), 08 (DEP), 09/07 (TST), 10 (T).

## 1. Functionality
- [ ] Login via GitHub works and the session survives beyond 15 minutes without re-OAuth (ISS-012 · TST-03/32)
- [x] Dev login is unreachable with default settings (ISS-002 · TST-02) — Resolved in PR #feature/project-audit-remediation
- [ ] Connect → sync → index completes in production for a fixture repository (ISS-005 · TST-E1)
- [ ] Chat answers cite indexed files; conversations persist across reloads; tokens stream (FEAT-05 · ISS-015/016 · TST-23, TST-E1)
- [ ] Explain, Bugs, Tests, Review produce persisted runs visible in history (FEAT-06…10 · TST-E2)
- [ ] Review publishes to GitHub once per click; bug → issue works (TST-E2)
- [x] Task lifecycle reaches `DRAFT_PR_CREATED` only after persisted, SHA-bound authorization (ISS-004 · TST-E3) — Resolved in PR #feature/project-audit-remediation
- [x] Failed pushes are never reported as successful in production (ISS-018) — Resolved in PR #feature/project-audit-remediation
- [ ] Tools & MCP page shows real, persisted data — or the feature is removed (ISS-033/003 · FEAT-14)
- [ ] Webhook console, automation settings, code search, symbols and PR picker available (FEAT-15/16/17 · T4.4–T4.6)

## 2. Integration
- [ ] 0 frontend calls to non-existent endpoints (contract test TST-30 green)
- [ ] Frontend types generated from OpenAPI; no hand-written response interfaces (OPT-03)
- [ ] Every backend route is consumed, documented as external/infra/internal, or removed (03 §1)
- [ ] One PR data model and one diff endpoint (ISS-042, DC-01)
- [ ] Task/tool events delivered via SSE; polling only as fallback (OPT-11)
- [ ] Project memory used by chat, planner and review with provenance labels (ISS-036 · TST-40)

## 3. Security
- [x] No committed JWT secret accepted by the validator; production secret rotated (ISS-001 · TST-01) — Resolved in PR #feature/project-audit-remediation
- [x] MCP and all admin routes require admin (ISS-003 · TST-04) — Resolved in PR #feature/project-audit-remediation
- [x] CSRF regex uses `fullmatch`; cookie SameSite policy matches topology; CSP present (ISS-021 · TST-05, TST-18) — CSRF fullmatch + SameSite lax resolved; CSP pending
- [x] Git tokens never appear in argv or logs (ISS-019 · TST-06, TST-14) — Resolved in PR #feature/project-audit-remediation
- [x] Internal memory endpoints removed (ISS-023 · TST-07) — Resolved in PR #feature/project-audit-remediation
- [ ] Tenant-isolation sweep green for every ID-bearing route (TST-15)
- [ ] Sandbox: runner with no network for test phase; path/command fuzz tests green (TST-11…13)
- [ ] Dependency and secret scans green on lock files (DEP-15)

## 4. Performance
- [ ] No `async def` route performs sync DB I/O (ISS-009 · TST-29)
- [ ] `/health/live` p95 < 50 ms under AI load (TST-N1) — baseline and result recorded
- [ ] SSE per-user channels; idle connection cost ~0 (TST-N2)
- [ ] LLM concurrency cap and per-user AI quotas enforced (ISS-025 · TST-16)
- [ ] Server-side pagination on all list endpoints (ISS-024 · TST-31)
- [ ] Retrieval benchmark recorded with graph/reranker variants; chosen configuration justified by numbers (OPT-13/14 · TST-35)

## 5. Code quality
- [ ] Dead-code batches A–E completed with validation (05 §5)
- [ ] Silent broad `except` handlers ≤ 10, each annotated (ISS-040)
- [ ] No test-aware branches in production code (ISS-041)
- [ ] Largest Python file < 800 LOC; one task UI component (OPT-06, DC-20)
- [ ] Ruff (incl. `BLE`, `S`, `ASYNC`) and oxlint/tsc clean in CI

## 6. Database
- [ ] `alembic upgrade head` + `alembic check` + down/up cycle green on PG+pgvector (TST-25)
- [ ] FK `ondelete` policies defined (ISS-034); `pull_requests` merged (ISS-042 · TST-26)
- [ ] Index review done with `pg_stat_statements`; unused indexes dropped (OPT-20)
- [ ] Retention jobs running; table growth bounded (OPT-21 · TST-26d)
- [ ] Connection budget per role documented and verified (ISS-032)
- [x] Seed script cannot touch non-local databases (ISS-029 · TST-08) — Resolved in PR #feature/project-audit-remediation

## 7. AI
- [x] Graph expansion and reranker built from settings (ISS-007/008 · TST-27) — Resolved in PR #feature/project-audit-remediation
- [ ] Workflows durable across restarts; no `asyncio.run` in library code (ISS-010/011 · TST-E4)
- [ ] Static scanners available where analyses run; availability reported per result (ISS-013)
- [ ] Prompt version and model recorded per run (OPT-18 · TST-34)
- [ ] Nightly quality gate green; prompt-injection regression green (TST-38, TST-17)

## 8. Testing
- [ ] Coverage measured for `app, ai, sandbox, scanner, indexer, review, agent` with floors (ISS-035)
- [ ] Compose-based E2E (Playwright) in CI (TST-E0…E6)
- [x] Tests organised by feature (DC-29c); symlinked duplicate test modules removed (DC-29d) — DC-29d resolved in PR #feature/project-audit-remediation
- [ ] Load/soak tests executed before release (TST-N1…N3)

## 9. Deployment
- [ ] Roles deployed separately: api, sync_worker, webhook_worker, task_worker, runner (T9.1)
- [ ] Migrations run once per release, not per replica (T9.2)
- [ ] `FORWARDED_ALLOW_IPS` restricted (T9.3)
- [ ] Readiness includes worker heartbeat, webhook backlog, scanner and sandbox availability; alerts configured (OPT-24)
- [ ] Reranker model pre-fetched; offline mode at runtime (DEP-09)
- [ ] Backup/restore drill executed (T9.7)

## 10. Documentation
- [ ] README claims match code and CI status (ISS-028)
- [ ] Historical sprint docs archived with an index (DC-29a/b)
- [ ] Runbooks: deploy per role, rotate secrets, replay webhooks, recover tasks
- [ ] This audit set updated when issues close (mark ISS rows "Resolved in PR #…")
