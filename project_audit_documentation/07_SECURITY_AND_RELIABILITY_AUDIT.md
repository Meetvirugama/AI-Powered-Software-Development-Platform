# 07 — Security and Reliability Audit

Severity scale: **Critical** (exploitable for full compromise in a supported configuration) · **High** · **Medium** · **Low** · **Info**. Issue details (evidence, fix, acceptance) are in 01; this document ranks them, covers every checklist area of the task specification, and defines remediation and security tests.

No dynamic testing (DAST), dependency vulnerability scan (`pip-audit`, `npm audit`) or secret scan was executed in this audit (no network / tools unavailable). The repository already contains CI jobs for Gitleaks, Bandit, Ruff and `pip-audit` (in `requirements-dev.txt`) — their latest results were **not verified**.

---

## 1. Security findings (ranked)

| Rank | Issue | Severity | Area | Exploit precondition | Remediation (summary) | Validation |
|---|---|---|---|---|---|---|
| 1 | ISS-001 | **Critical** | Secret management / JWT | Compose deployment without `JWT_SECRET`, or copying `.env.production.example` | Fail-closed compose (`${JWT_SECRET:?}`), validator rejects known/placeholder secrets, entropy check | TST-01; `docker compose config` fails without secret |
| 2 | ISS-002 | **Critical** (config-dependent) | Authentication | `APP_ENV` unset/`development` on an internet-reachable instance | Explicit `ENABLE_DEV_LOGIN` + loopback + no "first user" fallback; 404 when disabled | TST-02 |
| 3 | ISS-003 | **High** | Authorization (RBAC) | Any authenticated account | Admin-only mutations, persistence, real status | TST-04 |
| 4 | ISS-004 | **High** | Workflow authorization / audit | Developer account or replayed request | Mandatory persisted, SHA-bound publication authorization | TST-20, TST-E3 |
| 5 | ISS-021 | **Medium** | CSRF / CORS | Operator configures an unanchored `CORS_ORIGIN_REGEX`; cookies `SameSite=None` | `re.fullmatch`, anchored-regex validation, `SameSite=Lax` behind the Vercel rewrite | TST-05 |
| 6 | ISS-019 | **Medium** | Secret exposure | Local process access on the API/worker host (incl. `local` sandbox code) | Pass git auth via env (`GIT_CONFIG_*`) or askpass | TST-06 |
| 7 | ISS-023 | **Medium** | Data integrity / future prompt injection | Developer account | Remove public automated-memory routes; separate system vs user memories | TST-07 |
| 8 | ISS-012 | **Medium** (availability/UX; encourages long-lived tokens as a workaround) | Session management | — | Rotating refresh tokens with reuse detection | TST-03 |
| 9 | ISS-018 | **Medium** | Integrity of task state | Misconfigured remote in prod | No simulated success outside explicit dev flag | TST-E3 (+ unit test on push failure path) |
| 10 | ISS-029 | **Medium** (operational) | Data destruction | Running seed script with prod `DATABASE_URL` | Environment guard, Alembic-based seeding | TST-08 |
| 11 | ISS-022 | **Low** (latent) | SSRF | Future outbound MCP calls | Resolve-and-pin with private-range blocking | TST-09 |
| 12 | ISS-031 | **Low** | DoS | Large webhook bodies before HMAC | Content-Length check; proxy limit | TST-10 |
| 13 | ISS-037 | **Low** | Hard-coded identity | — | Remove defaults | code review |

---

## 2. Checklist coverage (task spec §8)

| Area | Status | Evidence / notes | Action |
|---|---|---|---|
| Authentication | Partially strong | HS256 JWT with `iss`/`aud`/`jti`, 15-min expiry, Redis blocklist with local cache (`core/auth.py`), OAuth state in Redis with TTL 600 s, redirect validation against CORS origins (`auth.py` `_resolve_trusted_frontend_url`) | ISS-001, ISS-002, ISS-012 |
| Authorization | Mostly strong | Tenant isolation via `get_owned_repository`/`get_owned_task`/user-filtered queries in every router except MCP; RBAC hierarchy `viewer<developer<admin` (`api/v1/dependencies.py`); role is taken from the JWT claim at issue time — role changes apply only after re-login (acceptable with 15-min tokens; document it) | ISS-003, ISS-004 |
| Session management | Weak | No refresh; logout blocklists `jti` (good) | ISS-012 |
| JWT handling | Good, with secret risk | `create_access_token` refuses missing secret/iss/aud; algorithm pinned in decode (`core/security.py` L83–88: `algorithms=[algorithm]`, `issuer`, `audience` verified) | ISS-001 |
| CSRF | Present | Origin/Referer check for cookie-authenticated writes in production | ISS-021 |
| XSS | Low risk | React escaping; no `dangerouslySetInnerHTML`/`innerHTML` in `frontend/src` (scan); chat markdown rendered by a custom component (`RepositoryChat.tsx` `MessageContent`) — keep it free of raw HTML; security headers set by backend and `vercel.json` (`nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy`) — **no Content-Security-Policy** on the Vercel-served SPA | Add CSP (`default-src 'self'; connect-src 'self'; img-src 'self' https://avatars.githubusercontent.com data:; frame-ancestors 'none'`) to `vercel.json` (OPT-12) |
| SQL injection | Low risk | ORM / bound parameters; f-string SQL only with integer casts or allow-listed values (`ai/retrieval/vector.py` L96–99) and constant identifiers in migrations/`scripts/security_gate.py` | Keep; add Ruff `S608` |
| Command injection | Mitigated | `sandbox/command_runner.py` allow-list (`ALLOWED_COMMAND_TEMPLATES`), list-form `subprocess` everywhere (no `shell=True` in production code), forbidden git sub-commands in sandbox, MCP stdio registration rejects shell metacharacters (`mcp_registry.py` L83) | Keep; TST-11 fuzz allow-list |
| Path traversal | Mitigated | `sandbox/path_guard.py` resolves real paths and checks workspace containment; GitHub source service enforces path checks and size limits | TST-12 (symlink escape cases) |
| SSRF | Latent | ISS-022 | — |
| File upload security | N/A | No file-upload endpoints found | — |
| Secret management | Mixed | `.gitleaks.toml`, `.secrets.baseline`, pre-commit hooks; `secret_redaction.py` applied to responses (`chat.py`) and push errors; example secrets in `.env.example` (`RUNNER_AUTH_SECRET=dev-runner-secret-key-12345`) and compose default JWT | ISS-001; make all example secrets empty |
| Environment variables | Mixed | Strong production validator; but `APP_ENV` defaults to development, unused vars (ISS-027), missing setting for webhook worker (ISS-014) | 08 §3 |
| API rate limiting | Present | `core/rate_limit.py` Redis store with in-memory fallback, per user/IP; AI endpoints need cost-aware quotas | OPT-15 |
| Input validation | Good | Pydantic models with lengths/limits (e.g., chat question ≤ 4,000, history ≤ 50); webhook delivery-ID regex; `core/input_security.py` | — |
| Output encoding | Good | JSON responses; redaction of secrets in AI outputs | — |
| CORS | Good, one gap | Explicit origins; `*` filtered; dev localhost regex only outside production; production rejects localhost origins and wildcard regex | ISS-021 (anchoring) |
| Dependency vulnerabilities | **Not verified** | `pip-audit` present in dev requirements; Dependabot/Renovate config not found | DEP-15 |
| Insecure deserialization | Low risk | No `pickle`/`yaml.load`/`marshal` in production code; Redis cache serialization is JSON, explicitly not pickle (`ai/retrieval/cache_serialization.py` L5) | — |
| AI prompt injection | Partially mitigated | `ai/security/{provenance,taint_tracker,taint_policy}.py` track untrusted content into tool calls; repository content and issue text flow into prompts by design; agent tools are read-only; task tools gated by approvals | Wire memory with provenance labels (ISS-036/023); add red-team fixtures (exists: `tests/fixtures/security/prompt_injection`) to CI (TST-17) |
| Tool execution permissions | Present | `agent/tools/router.py` schema validation + rate limits + approval gate (`tool_approval_gate.py`, `core/tool_api_policy.py`); MCP policy edits not enforced (ISS-003) | — |
| Agent sandbox isolation | Depends on backend | `local` backend = host subprocess (dev only; production validator forbids it when explicitly set); `container` uses Docker with gVisor option but is unavailable in the image (ISS-006); `runner` service with Bearer auth; env scrubbing in `command_runner.py` (allow-listed env keys; `PIP_NO_INDEX`, `NPM_CONFIG_OFFLINE`) — **network egress is not blocked** for `local`; `container` applies `--network=none` for the offline test phase (`container_backend.py` L263–265) | Use `runner` with gVisor + no network in production; TST-13 |
| Database access controls | App-level only | Single DB role; no row-level security. Acceptable for this architecture; ensure the DB user is not superuser in production | Ops checklist 12 |
| Sensitive data exposure | Good | Prompt/response capture off by default in observability; DB URL redacted in logs; token never returned to the browser except dev-login/JSON callback bodies (`TokenResponse.access_token`) — consider removing token from JSON responses since cookies are used | Low |
| Logging of secrets | Mostly mitigated | `secret_redaction.redact`; risk via silent exception strings is low | Add a log-redaction filter at the logging handler level (TST-14) |
| Background worker security | OK | Workers use same settings validator; lease/locks in Redis; webhook HMAC with `compare_digest` and fail-closed when secret missing | ISS-014 topology |

---

## 3. Reliability findings

| Topic | Current state | Issues | Recommendation |
|---|---|---|---|
| Failure recovery | Startup reconciliation of stale sync jobs (600 s) and interrupted tasks; workspace recovery | ISS-010 (thread workflows lost) | OPT-08 durable jobs |
| Retry policies | LLM provider retries + fallback; sync worker retries (3, exp. base 2 s); webhook attempts with `max_attempts`; GitHub client retries (verify per call) | No retry budget/jitter documentation | Document; add jitter where missing |
| Idempotency | Webhook delivery-ID dedupe (24 h); push-to-sync SHA dedupe; plan approval bound to `plan_hash` | Task creation and PR creation idempotency keys absent (double-click → duplicate task) — the PR path has a concurrency guard (`task_execution_orchestrator.py` L1927 conflict) | Accept `Idempotency-Key` header on `POST /tasks`, `/issues/import`, `/create-pr` |
| Transaction consistency | Per-request sessions; several multi-step operations commit in stages; persistence errors swallowed | ISS-038, ISS-040 | Unit-of-work per operation; explicit error surfacing |
| Graceful shutdown | Uvicorn graceful timeout (15 s); lifespan cancels worker tasks, closes LLM/embedding clients, Redis, engines | Workflow threads are not joined/cancelled (ISS-010) | OPT-08 |
| Monitoring | Structured logs, request IDs; OTel/Langfuse optional | No worker/backlog metrics | OPT-24 |
| Health checks | `/health/live`, `/health/ready` (DB, Redis, services) | Readiness ignores workers, scanners, sandbox (ISS-005, ISS-013, ISS-006) | Extend readiness |
| Logging | JSON logs with request IDs | 115 silent handlers (ISS-040) | OPT-09 |
| Observability | Spans for LLM calls (`gen_ai.*` attributes), stage metrics persisted per analysis run | OTel off by default | Enable with sampling |
| Data durability | Postgres for core state | In-memory: MCP registry, workflow registry, analysis-history fallback, chat history | ISS-003, ISS-010, ISS-038, ISS-016 |
| Concurrency safety | Repo-level Redis locks for sync; lease-based claims | No global LLM concurrency (ISS-025); unbounded workflow threads | OPT-15, OPT-08 |

---

## 4. Remediation strategy

1. **Immediately (P0, Phase 1):** ISS-001, ISS-002, ISS-003 (RBAC part), confirm ISS-005 in Azure; rotate any JWT secret that may have been the compose default; force logout (blocklist is per-jti, so rotation of the secret invalidates all tokens).
2. **Next (Phase 1–2):** ISS-004, ISS-021, ISS-019, ISS-023, ISS-018, ISS-029; add CSP.
3. **Hardening (Phase 5/9):** sandbox runner with gVisor and no network; scanners in runner (ISS-013); dependency scanning automation (DEP-15); prompt-injection regression suite in CI.

---

## 5. Security test plan (feeds 09)

| Test ID | What | How | Pass criteria |
|---|---|---|---|
| TST-01 | JWT secret validator | Parametrised unit tests with every committed placeholder + low-entropy strings | `ValueError` for each; compose without secret fails |
| TST-02 | Dev-login exposure | API tests in prod/dev settings, with/without flag, non-loopback client | 404 when disabled; no fallback impersonation |
| TST-03 | Refresh token rotation | Unit + API: rotate, reuse old → family revoked | As stated |
| TST-04 | MCP RBAC | viewer/developer/admin matrix on 5 routes | Mutations 403 except admin |
| TST-05 | CSRF regex | Origins `https://a.vercel.app` ✓, `https://a.vercel.app.evil.com` ✗ | As stated |
| TST-06 | Token not in argv | Unit test inspecting `push_task_branch` command construction (mock `subprocess.run`) | No token substring in `cmd` |
| TST-07 | Automated memory routes removed | OpenAPI contains no `/memories/automated/*` | — |
| TST-08 | Seed guard | Run script with a non-local URL | Exit ≠ 0, no DDL executed (mock engine) |
| TST-09 | SSRF validator | Stub resolver mapping host → 10.0.0.1 / 169.254.169.254 | Rejected |
| TST-10 | Webhook size | Content-Length 6 MB | 413 before body read |
| TST-11 | Command allow-list fuzz | Hypothesis-generated commands with metacharacters / path tricks | All rejected unless template-exact |
| TST-12 | Path traversal | `../`, absolute paths, symlink pointing outside workspace | Rejected |
| TST-13 | Sandbox egress | In runner/container, `python -c "import urllib.request; urllib.request.urlopen('https://example.com')"` | Fails (no network) |
| TST-14 | Log redaction | Log records containing GitHub/Gemini token patterns | Redacted in emitted JSON |
| TST-15 | Tenant isolation sweep | For every route with `{repository_id}`/`{task_id}`, call with another user's ID (auto-generated from OpenAPI) | 404/403 for all |
| TST-16 | Rate limiting | Exceed per-user AI quota | 429 + `Retry-After` |
| TST-17 | Prompt-injection regression | Fixtures in `backend/tests/fixtures/security/prompt_injection` run against planner/chat with mocked LLM capturing prompts | Untrusted content stays in delimited sections; no tool call triggered by injected text |
| TST-18 | Security headers & CSP | Request SPA and API | Headers present |
