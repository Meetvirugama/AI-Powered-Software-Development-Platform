# 01 — Complete Codebase Audit (Master Issue Register)

This is the single source of truth for issue IDs. Every other document refers to these `ISS-###` IDs.
Labels (Verified / Verified (static) / Suspected / Recommendation) are defined in 00 §1.1.
Complexity scale: **S** ≤ ½ day · **M** 1–3 days · **L** 3–8 days · **XL** > 8 days.

---

## 1. Summary register

| ID | Title | Status | Priority | Category | Primary location |
|---|---|---|---|---|---|
| ISS-001 | Publicly known fallback `JWT_SECRET` in compose passes the production validator | Verified | **P0** | Security / Config | `docker-compose.yml` L44, L66; `backend/app/core/config.py` L341–345 |
| ISS-002 | Dev-login impersonation is live whenever `APP_ENV` is not explicitly production | Verified | **P0** | Security / Auth | `backend/app/api/v1/auth.py` L367–410; `config.py` L30 |
| ISS-003 | MCP registry mutation endpoints have no role check and use global in-memory state | Verified | **P0** | Security / AuthZ | `backend/app/api/v1/mcp_registry.py` L49–154 |
| ISS-004 | Draft-PR "human authorization" is a request boolean; persisted authorization not enforced | Verified | P1 | Security / Workflow | `backend/app/api/v1/tasks.py` L203–223, L1680–1752; `task_execution_orchestrator.py` L1916 |
| ISS-005 | Production disables the embedded sync worker but CI/CD deploys no worker process | Suspected | **P0** | Deployment / Integration | `config.py` L335–336; `.github/workflows/main_…yml` deploy job; `startup.sh` |
| ISS-006 | Compose production forces `SANDBOX_BACKEND=container` but the image has no Docker CLI/socket | Suspected | P1 | Deployment / Sandbox | `config.py` L386–397; `Dockerfile`; `docker-compose.yml` |
| ISS-007 | Symbol-graph retrieval expansion is never enabled (wrong flag name and wrong module path) | Verified | P1 | AI / Integration | `backend/app/core/lifespan.py` L162–164 |
| ISS-008 | Reranker is hard-wired; `reranker_backend` / ONNX settings and `reranker_factory` are ignored | Verified | P2 | AI / Config | `lifespan.py` L145–146; `ai/retrieval/reranker_factory.py` |
| ISS-009 | 42 `async def` route handlers perform synchronous DB I/O on the event loop | Verified (static) | P1 | Performance / Async | see list in §3 |
| ISS-010 | "Durable" autonomous workflows run in raw threads with an in-memory registry; DBOS never launched | Verified | P1 | Reliability | `ai/workflows/autonomous_task_workflow.py` L45–91, L519–560 |
| ISS-011 | `asyncio.run` in worker threads to call async LLM code from sync code | Suspected | P2 | Async correctness | `ai/services/llm_repair_synthesizer.py` L320–350; `edit_synthesizer.py` L710–730; `ai_quality_evaluator.py` L555–575 |
| ISS-012 | No token renewal: 15-minute JWT, no refresh endpoint, forced re-login | Verified | P1 | Auth / UX | `config.py` L64; `auth.py`; `frontend/src/services/api.ts` L84–93 |
| ISS-013 | Static scanners (Ruff, Bandit, Semgrep, OSV, Gitleaks) not installed in production image | Verified | P1 | Integration / Deps | `backend/requirements.txt`; `review/static_reviewer.py` L135–141; `Dockerfile` |
| ISS-014 | Embedded webhook worker cannot be disabled; standalone webhook worker never deployed | Verified | P2 | Config / Workers | `lifespan.py` L520; `docker-compose.yml` |
| ISS-015 | Chat "token streaming" is simulated; `generate_stream` unused and would duplicate output on fallback | Verified | P2 | AI / Realtime | `app/api/v1/chat.py` L119–135; `ai/llm/client.py` L401–450 |
| ISS-016 | Chat conversations are not persisted; history is trusted from the client | Verified | P2 | Feature gap / DB | `chat.py`; `frontend/src/hooks/useRepositoryChat.ts`; no table |
| ISS-017 | Publish response contract mismatch and unsafe 404 fallback (`/publish` → `/create-pr`) | Verified | P2 | API contract | `frontend/src/services/tasks.ts` L598–620; `frontend/src/types/task.ts` L913–933; `app/schemas/task.py` L756–770 |
| ISS-018 | Failed `git push` is converted into a "successful" simulated push when no remote is configured | Verified | P1 | Logic / Workflow | `task_execution_orchestrator.py` L1775, L1853–1885 |
| ISS-019 | GitHub installation token passed on the git command line (`-c http.extraheader`) | Verified | P2 | Security / Secrets | `sandbox/workspace_manager.py` L1306–1316 |
| ISS-020 | SSE fan-out subscribes every connection to one global pub/sub channel and filters in Python | Verified | P2 | Scalability / Realtime | `app/api/v1/events.py` L195–250 |
| ISS-021 | CSRF Origin check uses prefix-anchored `re.match`; production cookies default to `SameSite=None` | Verified | P2 | Security / CSRF | `app/core/auth.py` L185; `config.py` L298–302; `.env.production.example` L47–49 |
| ISS-022 | MCP URL SSRF validator does not resolve DNS and allows `http://localhost` in production | Suspected (latent) | P3 | Security / SSRF | `app/services/mcp_elicitation_service.py` L54–140 |
| ISS-023 | Internal "automated memory" endpoints are exposed over HTTP (users can forge task outcome memories) | Verified | P2 | Security / Data integrity | `app/api/v1/memories.py` L139–186 |
| ISS-024 | `GET /repositories` has no server-side pagination; the UI paginates client-side while polling | Verified | P2 | Performance / API | `app/api/v1/repositories.py` L126; `frontend/src/services/repositories.ts` L39–57 |
| ISS-025 | `ai_max_concurrent_calls` is configured but never enforced (no global LLM concurrency limit) | Verified | P2 | AI / Cost control | `config.py` L94 (only reference) |
| ISS-026 | Conflicting Python dependency manifests (`pyproject.toml` vs `backend/requirements.txt`) | Verified | P1 | Dependencies | `pyproject.toml` L11–35; `backend/requirements.txt` |
| ISS-027 | `ASYNC_DATABASE_URL` (asyncpg) in compose is never read; asyncpg is not installed | Verified | P3 | Config | `docker-compose.yml` L41, L64; `app/core/database.py` L81–135 |
| ISS-028 | Documentation states capabilities/results that the code does not match | Verified | P3 | Documentation | `README.md`; `Docs/audits/CODEBASE_CLEANUP_CHANGELOG.md` |
| ISS-029 | `scripts/seed_database.py` drops all tables of whatever `DATABASE_URL` is set, without a guard | Verified | P2 | Operational safety | `backend/scripts/seed_database.py` L46–47 |
| ISS-030 | Health router mounted twice (root and `/api/v1`) | Verified | P3 | API hygiene | `backend/app/main.py` L82–83 |
| ISS-031 | Webhook body read fully before size enforcement | Verified | P3 | Robustness | `app/api/v1/github.py` L460–463 |
| ISS-032 | Per-process connection budget (sync 20+10, async 10+5) × processes may exceed managed Postgres limits | Suspected | P2 | Database / Ops | `app/core/database.py` L50–135; `config.py` L45–48 |
| ISS-033 | Tools & MCP admin page is entirely hard-coded client state | Verified | P1 | Feature parity | `frontend/src/pages/ToolsIntegrationsAdminPage.tsx` L25–89 |
| ISS-034 | FKs to `users.id` (and `github_installations.id`) have no `ondelete` policy; no account-deletion flow | Verified | P3 | Database | `app/models/repository.py` L22–23; `github_installation.py` L14; `sync_job.py` L24 |
| ISS-035 | CI coverage gate measures only the `app` package | Verified | P2 | Testing | `.github/workflows/main_…yml` L110–114; `pytest.ini` |
| ISS-036 | Project memory never reaches AI prompts (write-only from the AI's perspective) | Verified (static) | P1 | AI integration | `chat.py` L114; `ai/pipeline.py` L204–245 |
| ISS-037 | Hard-coded developer GitHub login (`Meetvirugama`) in frontend and backend | Verified | P3 | Code quality | `frontend/src/pages/Login.tsx` L30; `auth.py` L383 |
| ISS-038 | Analysis history silently falls back to a process-local in-memory store on DB errors | Verified | P2 | Data consistency | `app/api/v1/analysis/history.py` L133–158; `app/services/explanation_orchestrator.py` L878–895 |
| ISS-039 | Services instantiated on `app.state` but never read (dead DI wiring) | Verified (static) | P3 | Dead code | `lifespan.py` `init_history_services`, `init_context_service` |
| ISS-040 | 115 broad, silent `except Exception: pass/continue` handlers in non-test code | Verified (static) | P2 | Error handling | top: `sandbox/workspace_manager.py` (6), `command_runner.py` (5), `container_backend.py` (5) |
| ISS-041 | Test-aware branches in production code (`PYTEST_CURRENT_TEST`, `_is_mock_db`, monkeypatch detection) | Verified (static) | P2 | Testability / Correctness | 28 hits in 14 files (§3) |
| ISS-042 | Two pull-request tables (`pull_requests`, `task_pull_requests`); `pull_requests.task_id` has no FK | Verified | P2 | Database / Duplication | `app/models/pull_request.py` L22; `app/models/task.py` (`TaskPullRequest`); `app/services/git_branch.py` L612–700 |

**Totals:** P0 = 4 · P1 = 11 · P2 = 19 · P3 = 8 (42 issues).

Items from the earlier in-repo audit (`CODEBASE_CLEANUP_AND_OPTIMIZATION_AUDIT.md` §A1) were re-checked and are **resolved** in the current code: missing `import json` (now `task_execution_orchestrator.py` L19), duplicate `get_task_for_user` (single definition in `app/repositories/task/core.py` L211), `StaticReviewer` wiring (`lifespan.py` init), SSE fail-open for repository events (`events.py` L103–106 now fails closed), and `repository_files` constraints (migration `d5e6f7a8b9c0`). They are not re-raised here.

---

## 2. Detailed findings

### ISS-001 — Publicly known fallback `JWT_SECRET` passes the production validator
| Field | Detail |
|---|---|
| Status / Priority | Verified · **P0** · Complexity **S** |
| Files / lines | `docker-compose.yml` L44 (`api`) and L66 (`sync_worker`): `JWT_SECRET: ${JWT_SECRET:-production-deployment-minimum-32-chars-secret-key-ok}`; `backend/app/core/config.py` L339–345 (`validate_production_security`); `.env.production.example` L38 |
| Symbol | `Settings.validate_production_security` |
| Existing implementation | The validator rejects secrets shorter than 32 chars or containing `test-secret`, `dev-secret`, `changeme`, `placeholder`, or equal to `secret`. Compose supplies a 52-char default when `JWT_SECRET` is unset; the production example ships `generate-a-strong-32-character-secret-key-here-for-production`. |
| Problem | Both strings pass the validator. A compose deployment without an explicit `JWT_SECRET` signs tokens with a secret that is published in the repository, so anyone can mint a valid HS256 token (`sub` = any user UUID, `role` = `admin`). |
| Root cause | Fail-open default in compose; deny-list instead of entropy/known-value check. |
| Impact | Full authentication bypass and privilege escalation in that deployment mode. |
| Recommended solution | (1) Compose: `JWT_SECRET: ${JWT_SECRET:?JWT_SECRET must be set}` for both services. (2) Validator: reject any value that appears in repository files (`production-deployment-minimum-32-chars-secret-key-ok`, the `.env.production.example` placeholder), add `example`, `generate`, `your-`, `sample` to the deny-list, and require ≥ 128 bits of estimated entropy (e.g., ≥ 32 chars and ≥ 12 distinct characters, or base64/hex of ≥ 32 bytes). (3) Document `python -c "import secrets;print(secrets.token_urlsafe(48))"`. |
| Dependencies | DEP-11 (env audit); TST-01 |
| Testing | Unit tests for the validator with each known placeholder → `ValueError`; `docker compose config` without `JWT_SECRET` fails. |
| Acceptance criteria | No committed file contains a JWT secret value accepted by the validator; compose refuses to start without `JWT_SECRET`. |

### ISS-002 — Dev-login impersonation live outside explicit production
| Field | Detail |
|---|---|
| Status / Priority | Verified · **P0** (config-dependent exposure) · **S** |
| Files / lines | `backend/app/api/v1/auth.py` L367–410 (`dev_login`); `backend/app/core/auth.py` L38–52 (`/api/v1/auth/dev-login` in `PUBLIC_PATHS`); `config.py` L30 (`app_env: str = "development"`); `frontend/src/pages/Login.tsx` L30, L91 |
| Existing implementation | Allowed when `app_env ∈ {development, dev, local}`. Accepts `?login=` for **any existing user**; if not found, logs in as **the first user in the table** (`db.query(User).all()[0]`); else creates a user. Sets an auth cookie. |
| Problem | Settings default to `development`. Any deployment that forgets `APP_ENV` (e.g., Azure App Service configured without the Docker image, a staging slot, `run_local.sh` exposed on `0.0.0.0`) exposes one-request account takeover of any user. The frontend hides the button only by `import.meta.env.DEV`, which does not protect the API. |
| Root cause | Feature flag derived from environment name; impersonation-by-login design; fail-open default. |
| Impact | Complete account takeover; access to connected repositories and GitHub installation tokens through the platform. |
| Recommended solution | Require an explicit `ENABLE_DEV_LOGIN=true` setting (default `false`) **and** non-production **and** client IP in loopback; never fall back to "first user"; remove the hard-coded login (ISS-037); remove the path from `PUBLIC_PATHS` when disabled (return 404 instead of 403). Consider making `app_env` required (no default) so production is never inferred. |
| Dependencies | ISS-037; DEP-12 |
| Testing | API tests: disabled by default → 404; enabled + non-loopback → 403; unknown login → 404 (no fallback). |
| Acceptance criteria | With default settings, `POST /api/v1/auth/dev-login` returns 404; impersonation of an arbitrary existing user is impossible without the flag. |

### ISS-003 — MCP registry endpoints lack authorization and use global in-memory state
| Field | Detail |
|---|---|
| Status / Priority | Verified · **P0** · **M** |
| Files / lines | `backend/app/api/v1/mcp_registry.py` L49–70 (`_REGISTRY_SERVERS` module dict), L73–154 (5 routes) |
| Existing implementation | `GET/POST /mcp/servers`, `POST /ping`, `PATCH /toggle`, `PATCH /tools/{tool}/policy`. No `request` parameter, no `require_role`, no ownership. State is a process-global dict; new servers are reported `status="connected"` without any connection; `ping` pings the in-process platform server regardless of the target. |
| Problem | Any authenticated user (role `viewer` included) can register servers and flip `requiresApproval` on tools, and that change is visible to every user served by that process. State is lost on restart and differs per replica. The UI does not use these endpoints at all (ISS-033). |
| Root cause | Prototype admin API never connected to RBAC or persistence. |
| Impact | Integrity of the approval policy model is not enforceable; misleading status; inconsistent behaviour across replicas. Today the policy flag is not consumed by the task tool router (it reads its own catalogue), which limits real-world impact — **verify before relying on that**. |
| Recommended solution | Short term: add `Depends(require_role(UserRole.ADMIN))` to all mutating routes and `require_min_role(DEVELOPER)` to GET. Medium term: persist servers and tool policies in a new `mcp_servers` / `mcp_tool_policies` table (Alembic migration), make the task `ToolRouter` read policies from there, and compute `status`/latency from a real health probe. Or remove the API and the page until the feature is real (product decision, FEAT-14). |
| Dependencies | ISS-033, FEAT-14, DC-16 |
| Testing | RBAC tests (viewer/developer → 403 on mutations); persistence test across app restarts; policy change reflected in `/tasks/{id}/tools/{name}` approval behaviour. |
| Acceptance criteria | Only admins can mutate; state survives restart; UI shows server data from the API. |

### ISS-004 — Publication authorization is a request flag
| Field | Detail |
|---|---|
| Status / Priority | Verified · P1 · **M** |
| Files / lines | `backend/app/api/v1/tasks.py` L203–223 (`TaskDraftPRCreateRequest.publication_authorized/human_authorized`), L1680–1703 (`authorize_task_publication_endpoint`), L1706–1752 (`create-pr` and alias `publish`); `backend/app/services/task_execution_orchestrator.py` L1916–1921; `frontend/src/services/tasks.ts` L598–620 |
| Existing implementation | `create_draft_pull_request(publication_authorized=body.is_authorized)` only checks the boolean from the same request. A separate endpoint persists an authorization (`task_repo.authorize_publication(head_sha, notes)`), but creation never checks it. The frontend never calls `/authorize-publication`. |
| Problem | "Explicit human authorization (ADR-010)" is reduced to a checkbox value any client can send; the recorded authorization (bound to a `head_sha`) is not tied to the publication. |
| Root cause | Two authorization mechanisms evolved independently. |
| Impact | Weakened audit trail; a script or replayed request can publish without the dedicated authorization step; head SHA drift after authorization is not detected at publish time. |
| Recommended solution | Make `create-pr` require a persisted authorization record for the task whose `head_sha` equals the workspace head at publish time (and status `READY_FOR_PUBLICATION`/`PUBLISHING`). Remove `publication_authorized`/`human_authorized` from the body (or ignore them). Frontend: call `POST /tasks/{id}/authorize-publication` from the confirmation dialog, then `POST /tasks/{id}/create-pr`. Remove the `/publish` alias (DC-21). |
| Dependencies | ISS-017, DC-21, FEAT-12 |
| Testing | API tests: publish without prior authorization → 409; authorization with stale head SHA → 409; happy path → Draft PR created; audit event contains the authorizing user. |
| Acceptance criteria | No Draft PR can be created without a persisted, SHA-bound authorization by a developer+ user. |

### ISS-005 — No sync worker in production deployment
| Field | Detail |
|---|---|
| Status / Priority | **Suspected** · **P0 if confirmed** · **S–M** |
| Files / lines | `backend/app/core/config.py` L335–336 (in production, `disable_embedded_sync_worker` is forced `True` unless explicitly set); `backend/app/core/lifespan.py` L530–540; `.github/workflows/main_ai-powered-dev-platform-api.yml` jobs `build-and-package` → `deploy` (single Azure Web App); `.env.production.example` L13; `Docs/deployment/cloud_deployment_guide.md` L33; `startup.sh` (role switch exists) |
| Problem | In production the API process does not run the sync loop, and the deployment pipeline deploys only one web app with the default `api` role. Unless a second Azure resource runs `SERVICE_ROLE=sync_worker`, repository sync jobs are queued and never processed (repositories stay "queued"; nothing gets indexed). |
| What must be checked | The live Azure configuration: is there a WebJob / second App Service / Container App running `startup.sh` with `SERVICE_ROLE=sync_worker`? The repository contains no IaC for it. |
| Impact (if confirmed) | Core product loop (connect → index → chat/analysis) broken in production. |
| Recommended solution | Either (a) add a dedicated worker deployment (second Azure Web App/Container App with `SERVICE_ROLE=sync_worker`, and one with `SERVICE_ROLE=webhook_worker` — see ISS-014) to the deploy workflow and document it, or (b) for single-instance deployments set `DISABLE_EMBEDDED_SYNC_WORKER=false` explicitly (the validator only forces it when unset). Add a readiness signal: `/health/ready` should report `sync_worker_heartbeat_age` from the Redis heartbeat key `worker:heartbeat:*` written by `app/workers/sync_worker.py`. |
| Dependencies | ISS-014, DEP-13 |
| Testing | Deployment smoke test: connect a fixture repository → job reaches `completed` within N minutes; readiness fails when no worker heartbeat exists. |
| Acceptance criteria | Production has an observable, running sync worker; readiness reflects its absence. |

### ISS-006 — Container sandbox selected without Docker
| Field | Detail |
|---|---|
| Status / Priority | Suspected · P1 · **M** |
| Files / lines | `config.py` L386–397 (production silently switches unset `sandbox_backend` from `local` to `container`); `backend/sandbox/container_backend.py` (invokes `docker` CLI, L83, L350); `Dockerfile` runtime stage installs only `libpq5 git curl ca-certificates`; `docker-compose.yml` mounts no Docker socket |
| Problem | In the compose production profile, task execution/test runs will call a missing `docker` binary. |
| What must be checked | Run a task's `POST /tasks/{id}/tests` in the compose stack; expect a sandbox error. |
| Recommended solution | Make production fail fast at startup if the selected backend is unavailable (`shutil.which("docker")` for `container`, reachable `RUNNER_BASE_URL` for `runner`); add a `runner` service to compose (built from `backend/runner/main.py`) and set `SANDBOX_BACKEND=runner` + `RUNNER_AUTH_SECRET` there. Do **not** mount the Docker socket into the API container (equivalent to root on host). |
| Dependencies | ISS-005, DEP-14 |
| Testing | Startup test: production + `container` + no docker → readiness false with clear reason. Compose E2E for tests endpoint via runner. |
| Acceptance criteria | Every supported deployment profile has a working sandbox or refuses to report ready. |

### ISS-007 — Symbol-graph expansion never enabled
| Field | Detail |
|---|---|
| Status / Priority | Verified · P1 · **S** |
| Files / lines | `backend/app/core/lifespan.py` L162–166 |
| Existing implementation | `if getattr(settings, "symbol_graph_expansion_enabled", False): from ai.retrieval.graph_expander import SymbolGraphExpander` |
| Problem | (1) `Settings` has no `symbol_graph_expansion_enabled`; the real flag is `retrieval_graph_expansion_enabled` (`config.py` L128, default `True`). (2) The module is `ai/retrieval/graph_expansion.py`, not `graph_expander`. The branch is always skipped, and would raise `ImportError` (swallowed) if it ran. `HybridRetriever` therefore always receives `graph_expander=None`. |
| Impact | README-advertised "1-hop AST symbol graph expansion" is inactive in the app; retrieval quality for "who calls X / what depends on Y" questions is lower than benchmarked in tests that construct the expander directly. |
| Recommended solution | Use `settings.retrieval_graph_expansion_enabled` and `from ai.retrieval.graph_expansion import SymbolGraphExpander`; pass the configured `retrieval_graph_max_*` limits to the constructor; log at `error` (not `warning`) on failure; expose `graph_expansion` in `service_readiness`. |
| Dependencies | OPT-13 |
| Testing | Unit test on `init_rag_pipeline` asserting `app.state.rag_pipeline.retriever.graph_expander is not None` when the flag is true; retrieval benchmark (`scripts/benchmark_rag.py`) before/after. |
| Acceptance criteria | Graph expansion active by default; benchmark recall@k for graph-category queries ≥ baseline. |

### ISS-008 — Reranker settings ignored
| Field | Detail |
|---|---|
| Status / Priority | Verified · P2 · **S** |
| Files / lines | `lifespan.py` L145–146 (`CrossEncoderReranker()`); `ai/retrieval/reranker_factory.py` (`create_reranker` – no production caller); `config.py` L136–138 |
| Problem | `RERANKER_BACKEND`, `RERANKER_ONNX_ENABLED`, `RERANKER_QUANTIZATION` have no effect; the ONNX path (`reranker_onnx.py`) is unreachable. The reranker is also only built when Gemini keys exist (inside the embeddings `try`). |
| Recommended solution | Build the reranker via `create_reranker(settings)` independently of embeddings; fall back to no reranker on failure. |
| Dependencies | DC-03, OPT-14 |
| Testing | Factory unit tests for each backend; latency benchmark of rerank stage (pytorch vs ONNX) on 50 queries. |
| Acceptance criteria | Changing `RERANKER_BACKEND` changes the instantiated class; failure degrades gracefully. |

### ISS-009 — Synchronous DB I/O inside `async def` handlers
| Field | Detail |
|---|---|
| Status / Priority | Verified (static) · P1 · **L** |
| Files / lines | 42 handlers declared `async def` with `db: Session = Depends(get_db)` or direct `SessionLocal()` — full list in §3.1 |
| Problem | FastAPI runs `async def` handlers on the event loop; synchronous psycopg calls block it. While one request waits on the DB, **all** requests on that worker stall, including SSE streams and health checks. Several of these handlers also await LLM calls, so they hold a pooled connection across long awaits. |
| Root cause | Mixed sync/async data layer; handlers made `async` to call async services. |
| Impact | Tail-latency spikes and throughput collapse under concurrency; pool exhaustion. Magnitude requires load testing. |
| Recommended solution | Per handler, pick one: (a) make it `def` if it awaits nothing (FastAPI uses the threadpool); (b) keep `async` and wrap DB work in `await run_in_threadpool(...)` with a short-lived session scoped to that block; (c) migrate the hot paths (chat, analysis, history, search) to `AsyncSessionLocal` (already configured). Do not hold a session across LLM awaits: read inputs → close session → call LLM → open new session to persist. |
| Dependencies | OPT-05, ISS-032 |
| Testing | Load test (k6/Locust): 50 concurrent `/repositories/{id}/explain` + 50 `/health/live`; p95 of `/health/live` must stay < 50 ms. Add a CI lint (`ruff --select ASYNC`) to block regressions. |
| Acceptance criteria | Zero `async def` handlers perform sync DB calls on the loop (scan in §3.1 returns empty). |

### ISS-010 — Non-durable "durable" workflows
| Field | Detail |
|---|---|
| Status / Priority | Verified · P1 · **L** |
| Files / lines | `backend/ai/workflows/autonomous_task_workflow.py` L45–70 (`dbos_workflow` falls back to native execution when DBOS is not launched), L89–91 (`_active_workflows`, `_task_to_workflow` dicts + `RLock`), L519–560 (`submit_autonomous_workflow` → `threading.Thread`); no `DBOS(...)`/`DBOS.launch()` anywhere outside `poc/` |
| Problem | `POST /tasks/{id}/run-workflow?async=true` returns 202 and a `status_url`, but the workflow lives only in a thread of the API process. A restart, deploy or crash loses it; `/workflow-status` on another replica returns nothing. Unbounded thread creation per request. |
| Impact | Lost work, misleading status, possible half-executed workspaces. `TaskRepository.reconcile_interrupted_tasks` on startup only partially compensates. |
| Recommended solution | Option A (recommended, existing stack): persist workflow state in the existing `task_executions`/`task_checkpoints` tables and execute via the existing Redis-backed worker pattern (a `task_jobs` queue consumed by a worker role, lease + heartbeat like `sync_worker`). Option B: adopt DBOS properly (launch at startup with Postgres system DB, register workflows, use DBOS status APIs) — adds a dependency already listed in requirements. Either way, bound concurrency (`sandbox_max_concurrent_tasks`, currently unused for this path). See 06 OPT-08 for the comparison. |
| Dependencies | ISS-011, ISS-005, OPT-08 |
| Testing | Kill the worker mid-workflow → resumes from last checkpoint or marks `INTERRUPTED` deterministically; status endpoint consistent across two API replicas. |
| Acceptance criteria | No workflow state exists only in process memory. |

### ISS-011 — `asyncio.run` bridges inside threads
| Field | Detail |
|---|---|
| Status / Priority | Suspected · P2 · **M** |
| Files / lines | `ai/services/llm_repair_synthesizer.py` L320–350; `ai/services/edit_synthesizer.py` L710–730; `ai/services/ai_quality_evaluator.py` L555–575 |
| Problem | When called from inside a running loop, these spawn a thread and run `asyncio.run(...)` on a new loop while using the shared `LLMGateway`, whose providers hold `httpx.AsyncClient` objects bound to the main loop. This pattern commonly fails with "attached to a different loop"/"Event loop is closed". The code base contains defensive handling for exactly these errors in `app/core/auth.py` L140–152, which suggests it has been observed. |
| What must be checked | Execute a repair attempt through `POST /tasks/{id}/repair` with a live LLM key and inspect logs. |
| Recommended solution | Make the call chain async end-to-end (orchestrator methods `async def`, invoked from `async` routes or the worker loop), or give these synchronous paths a dedicated synchronous LLM client. Remove the thread/loop bridges. |
| Dependencies | ISS-010, ISS-009 |
| Testing | Integration test with a respx-mocked provider calling repair from an async context and from a worker thread. |
| Acceptance criteria | No `asyncio.run` in library code (only in entrypoints). |

### ISS-012 — No session renewal
| Field | Detail |
|---|---|
| Status / Priority | Verified · P1 · **M** |
| Files / lines | `config.py` L64 (`jwt_expire_minutes = 15`); `auth.py` sets the cookie only on login/callback (L163, L335, L348, L399); no `/auth/refresh`; `frontend/src/services/api.ts` L84–93 redirects to `/login` on any 401; `README.md` "refresh token rotation" claim |
| Problem | Every user is logged out 15 minutes after login, mid-task, and must redo GitHub OAuth. Long AI requests (up to 180 s) can straddle expiry. |
| Recommended solution | Add a refresh token (opaque, random, stored hashed in Redis or a `refresh_tokens` table with rotation + reuse detection), `POST /auth/refresh` (cookie-only, `SameSite=Lax`, path-scoped `/api/v1/auth`), and an Axios 401 interceptor that refreshes once then retries. Keep access token at 15 min. |
| Dependencies | ISS-021, TST-03 |
| Testing | Unit: rotation and reuse detection; E2E: idle 16 min → next request succeeds transparently; revoked refresh → login. |
| Acceptance criteria | Users stay signed in for the refresh lifetime (e.g., 7 days) without re-OAuth; reuse of a rotated refresh token revokes the family. |

### ISS-013 — Static scanners missing from production
| Field | Detail |
|---|---|
| Status / Priority | Verified (dependency manifests) · P1 · **M** |
| Files / lines | `backend/review/static_reviewer.py` L135–141 (`python -m ruff`, `python -m bandit`), L143 (`npx --no-install eslint`); `scanner/semgrep_runner.py` L120, `scanner/osv_runner.py` L263, `sandbox/gitleaks_scanner.py` L68–87 (`shutil.which`); `backend/requirements.txt` (no ruff/bandit); `Dockerfile` (installs only `backend/requirements.txt`, no node/semgrep/osv/gitleaks) |
| Problem | Review and bug detection advertise deterministic static analysis, but in the production image these tools are absent and each runner degrades silently (broad `except`, ISS-040). `pyproject.toml` lists ruff/bandit as runtime deps, contradicting `requirements.txt` (ISS-026). |
| Recommended solution | Decide the execution location: run scanners **inside the sandbox runner** (preferred; they process untrusted repos), and install them in the runner image (pinned versions). If kept in the API image, add `ruff`, `bandit` to `requirements.txt` and install semgrep/osv-scanner/gitleaks binaries with pinned checksums. Expose scanner availability in `/health/ready` and in each analysis result (`static_analysis.available_tools`). |
| Dependencies | ISS-026, ISS-006, DEP-03 |
| Testing | Container smoke test: `python -m ruff --version`, `semgrep --version` etc.; review of a fixture repo yields Ruff findings. |
| Acceptance criteria | Each analysis response states which scanners ran; production runs the documented set. |

### ISS-014 — Webhook worker topology
| Field | Detail |
|---|---|
| Status / Priority | Verified · P2 · **S** |
| Files / lines | `lifespan.py` L520 reads `settings.disable_embedded_webhook_worker` — not a `Settings` field (always `False`); `startup.sh` supports `SERVICE_ROLE=webhook_worker`; `docker-compose.yml` has no such service |
| Problem | Every API replica always runs an embedded webhook loop; the standalone worker is never deployed. With leasing this is mostly safe, but it couples webhook throughput to API scaling and cannot be turned off. |
| Recommended solution | Add `disable_embedded_webhook_worker: bool = False` to `Settings` (force `True` in production like the sync worker) and add a `webhook_worker` service to compose and to the deploy workflow. |
| Dependencies | ISS-005 |
| Acceptance criteria | Setting `DISABLE_EMBEDDED_WEBHOOK_WORKER=true` stops the embedded loop; production runs exactly one configured webhook worker deployment. |

### ISS-015 — Simulated chat streaming
| Field | Detail |
|---|---|
| Status / Priority | Verified · P2 · **M** |
| Files / lines | `app/api/v1/chat.py` L119–135 (`publish_chat_token(token=sanitized.answer, index=0, done=True)` after completion); `ai/llm/client.py` L401–450 (`generate_stream`, no production caller) |
| Problem | The UI waits for the whole answer (Axios timeout 180 s); the SSE "token" event carries the full answer once. `generate_stream`'s fallback restarts on the secondary provider after partial output was already yielded, so a mid-stream failure would emit duplicated/contradictory text. |
| Recommended solution | Add `POST /repositories/{id}/chat/stream` returning `text/event-stream` directly (not via the global Redis channel), driven by `LLMGateway.generate_stream`. Only fall back if **no** chunk has been yielded; otherwise emit an `error` event. Run grounding validation on the final buffer and send `sources` as a terminal event. |
| Dependencies | ISS-020, ISS-016, FEAT-05 |
| Acceptance criteria | First token visible < 2 s after request on a warm system (measure); no duplicated text on forced primary failure. |

### ISS-016 — Chat history not persisted
| Field | Detail |
|---|---|
| Status / Priority | Verified · P2 · **M** |
| Files / lines | `app/api/v1/chat.py` (accepts `payload.history`), `app/schemas/repository.py` (`RepositoryChatRequest`), `frontend/src/hooks/useRepositoryChat.ts` (in-memory state; no storage); no chat tables among the 26 models |
| Problem | Conversations vanish on refresh; the server trusts arbitrary client-supplied history (including fabricated "assistant" turns that steer the model); no audit of AI answers. |
| Recommended solution | Tables `chat_sessions(id, user_id, repository_id, title, created_at)` and `chat_messages(id, session_id, role, content, sources jsonb, mode, token_usage jsonb, created_at)`; endpoints `GET/POST /repositories/{id}/chat/sessions`, `GET /chat/sessions/{sid}/messages`; chat endpoint takes `session_id` and loads history server-side (bounded by token budget). |
| Dependencies | ISS-015, FEAT-05, OPT-17 |
| Acceptance criteria | Reloading the page restores the conversation; server ignores client-supplied assistant turns. |

### ISS-017 — Publication response contract mismatch
| Field | Detail |
|---|---|
| Status / Priority | Verified · P2 · **S** |
| Files / lines | FE `frontend/src/types/task.ts` L913–933 (`PublishTaskRequest`, `TaskPublicationResponse{success, summary, error,…}`); `frontend/src/components/tasks/PublicationPanel.tsx` L144–160 (uses `res.summary`); FE `services/tasks.ts` L598–620 (on 404 retries `/create-pr`); BE `app/schemas/task.py` L756–770 (`TaskPullRequestResponse{pr_id, head_sha, title, body,…}` — no `success`, no `summary`) |
| Problem | `summary` is always undefined in production (it exists only in the mock `frontend/src/mocks/handlers/task.ts`); `success` is never sent. The 404 fallback also fires when the *task* is not found, sending a second state-changing request. |
| Recommended solution | Generate TS types from the OpenAPI schema (`openapi-typescript`) and delete hand-written duplicates (OPT-03); update `TaskPublicationResponse` to the backend shape; remove the fallback (both routes exist). |
| Dependencies | ISS-004, DC-19, DC-21, OPT-03 |
| Acceptance criteria | `tsc` fails if FE types diverge from OpenAPI; one request per publish click. |

### ISS-018 — Simulated push success
| Field | Detail |
|---|---|
| Status / Priority | Verified (code path) · P1 · **S** |
| Files / lines | `app/services/task_execution_orchestrator.py` L1775 (`strict_remote: bool = False`), L1853–1885 |
| Problem | If `git push` fails and the workspace has no configured remote, the code records a `WorkspacePushResult(success=True, pushed_sha=<local HEAD or base revision>)` "simulated push". Downstream PR creation and the UI treat the branch as pushed. |
| Recommended solution | Only allow simulation when `settings.app_env` is development **and** an explicit `allow_simulated_push` flag is set; otherwise raise `502` and keep task status unchanged. Mark simulated results with `simulated=True` and surface it in the UI. |
| Dependencies | ISS-004 |
| Acceptance criteria | In production, a failed push never produces `success=True`. |

### ISS-019 — Token on git command line
| Field | Detail |
|---|---|
| Status / Priority | Verified · P2 · **S** |
| Files / lines | `sandbox/workspace_manager.py` L1306–1316 |
| Problem | `git -c http.extraheader=AUTHORIZATION: basic <b64(x-access-token:TOKEN)>` places the installation token in the process arguments, readable via `/proc/<pid>/cmdline` / `ps` by other processes on the host (including sandboxed processes when the `local` backend is used). |
| Recommended solution | Pass config through environment: `GIT_CONFIG_COUNT=1`, `GIT_CONFIG_KEY_0=http.extraheader`, `GIT_CONFIG_VALUE_0=AUTHORIZATION: basic …` (git ≥ 2.31), or a `GIT_ASKPASS` helper reading from an inherited fd. |
| Acceptance criteria | No token in argv (verify with a test that inspects the constructed `cmd`). |

### ISS-020 — SSE global channel fan-out
| Field | Detail |
|---|---|
| Status / Priority | Verified · P2 · **M** |
| Files / lines | `app/api/v1/events.py` L195–250 (`pubsub.subscribe("platform_events")`; `get_message` poll with `asyncio.sleep(0.5)`; `_should_deliver_event` per message); `channel` query param only affects Redis Stream replay |
| Problem | Every connection receives and JSON-parses every event of every tenant; CPU grows with (connections × events). Owned repo IDs are computed once at connect time, so repositories connected later are filtered out until reconnect. |
| Recommended solution | Publish to per-user channels (`events:user:{user_id}`) and subscribe only to that channel (the Redis Streams broker already keys by user); refresh ownership when a repository is connected; replace the 0.5 s poll with `pubsub.listen()`/blocking `get_message(timeout=…)`. |
| Dependencies | ISS-015, OPT-11 |
| Acceptance criteria | A connection never receives another user's payload at the Redis level; CPU per idle connection ≈ 0. |

### ISS-021 — CSRF regex anchoring and SameSite policy
| Field | Detail |
|---|---|
| Status / Priority | Verified (code); exploitability depends on configured regex · P2 · **S** |
| Files / lines | `app/core/auth.py` L185 (`re.match(effective_regex, origin_clean)`); `config.py` L298–302 (`effective_cookie_samesite` → `none` when `cookie_secure`); `.env.production.example` L47–49 ("COOKIE_SAMESITE MUST be none") |
| Problem | `re.match` anchors only at the start. A configured `CORS_ORIGIN_REGEX=https://.*\.vercel\.app` also matches `https://x.vercel.app.attacker.tld`. The same regex is given to Starlette CORS (which uses `fullmatch`), so CORS and CSRF disagree. With `SameSite=None`, cookies are sent on cross-site requests, so the Origin check is the only CSRF barrier. The Vercel rewrite makes the API same-origin to the browser, so `SameSite=None` is unnecessary in that topology. |
| Recommended solution | Use `re.fullmatch`; validate at startup that the regex is anchored (`^…$`); default production `COOKIE_SAMESITE=lax` when the frontend is served through the `/api` rewrite; keep `none` only for genuinely cross-site deployments. |
| Acceptance criteria | Test: origin `https://good.vercel.app.evil.com` rejected for regex `https://.*\.vercel\.app`. |

### ISS-022 — Latent SSRF gaps in MCP URL validation
| Field | Detail |
|---|---|
| Status / Priority | Suspected (latent: no server-side fetch of registered URLs exists today) · P3 · **S** |
| Files / lines | `app/services/mcp_elicitation_service.py` L54–140 |
| Problem | Only literal IPs are classified; hostnames are not resolved, so a DNS name pointing to `169.254.169.254` or RFC1918 passes. `http://localhost` is allowed regardless of environment. |
| Recommended solution | Before any future outbound call: resolve all A/AAAA records, reject private/link-local/metadata, pin the resolved IP for the connection, and disallow loopback in production. |
| Acceptance criteria | Validation rejects hostnames resolving to private ranges (test with a stub resolver). |

### ISS-023 — Forgeable automated memory endpoints
| Field | Detail |
|---|---|
| Status / Priority | Verified · P2 · **S** |
| Files / lines | `app/api/v1/memories.py` L139–163 (`/memories/automated/task-completion`), L165–186 (`/task-failure`) — developer role + repo ownership only; the orchestrator writes these memories directly through `ProjectMemoryService` (`task_execution_orchestrator.py` L890, L1502, L1536) |
| Problem | Records meant to be system-generated can be created with arbitrary content by any developer. Once ISS-036 wires memory into prompts, this becomes a stored prompt-injection channel. |
| Recommended solution | Remove both HTTP routes (no frontend caller) or restrict to admin; mark system memories with `source="system"` and render user-authored and system memories in separate, clearly delimited prompt sections. |
| Dependencies | ISS-036, DC-26 |

### ISS-024 — No server pagination for repositories
| Field | Detail |
|---|---|
| Status / Priority | Verified · P2 · **S** |
| Files / lines | BE `app/api/v1/repositories.py` L126–142 (returns full list with per-repo counts); FE `frontend/src/services/repositories.ts` L39–57 (client-side slice); `frontend/src/pages/Dashboard.tsx` L30 (polling `refetchInterval`) |
| Recommended solution | `GET /repositories?page=&page_size=&q=&status=` returning `{items,total,page,page_size}` (FE already models this shape); index `(user_id, created_at)`. |
| Acceptance criteria | Response size bounded by `page_size`; FE shim removed. |

### ISS-025 — No global LLM concurrency control
| Field | Detail |
|---|---|
| Status / Priority | Verified · P2 · **S** |
| Files / lines | `config.py` L94 `ai_max_concurrent_calls = 10` (no other reference); `ai/llm/client.py` |
| Problem | Bursts of analysis/chat requests fan out unbounded provider calls, causing provider 429s, key-rotation churn and cost spikes. Embeddings do have limits (`embedding_max_concurrency`). |
| Recommended solution | `asyncio.Semaphore(settings.ai_max_concurrent_calls)` inside `LLMGateway` around provider calls (per process) plus a Redis token bucket per user for AI endpoints. |
| Acceptance criteria | Load test shows ≤ N concurrent provider calls per process. |

### ISS-026 — Conflicting Python dependency manifests
| Field | Detail |
|---|---|
| Status / Priority | Verified · P1 · **S** |
| Files / lines | `pyproject.toml` L11–35 vs `backend/requirements.txt` |
| Problem | `sentence-transformers>=3.0,<4.0` (pyproject) vs `>=5.6.0,<7.0` (requirements) — mutually exclusive. pyproject lacks `transformers`, `dbos`, `jsonschema`, all `opentelemetry-*`, `langfuse`; includes `ruff`, `bandit` as runtime deps; `pytest-asyncio` ranges differ. `pip install .` and `pip install -r backend/requirements.txt` produce different, partly broken environments. |
| Recommended solution | Make `pyproject.toml` the single source (runtime + `[project.optional-dependencies] dev/scanners/eval`) and generate a lock (`uv pip compile` / `pip-tools`) consumed by Dockerfile and CI; reduce `requirements.txt` to `-e .` or the compiled lock. See 08 DEP-01…DEP-06. |
| Acceptance criteria | One manifest; lock file committed; CI installs from the lock. |

### ISS-027 — Unused `ASYNC_DATABASE_URL`
Verified · P3 · **S**. `docker-compose.yml` L41, L64 set `ASYNC_DATABASE_URL=postgresql+asyncpg://…`; `Settings` has no such field and `database.py` L81–90 derives `postgresql+psycopg_async://` from `DATABASE_URL`; `asyncpg` is not a dependency. **Fix:** remove the variable (or add a field and the driver if a separate async URL is wanted). **Acceptance:** compose env contains only consumed variables.

### ISS-028 — Documentation drift
Verified · P3 · **S**. Examples: `README.md` claims refresh-token rotation (ISS-012), active graph expansion (ISS-007), "500+ passed, 0 failed" (not reproducible here; note 7 test modules are symlinks that run the same tests twice, DC-29d); `Docs/audits/CODEBASE_CLEANUP_CHANGELOG.md` §2 lists `task2.md`/`task3.md` as removed but both are present at the repository root; `vercel.json` duplicated (DC-22). **Fix:** README "Status" table generated from CI artifacts; move historical sprint reports to `Docs/archive/`. **Acceptance:** every capability claim in README links to code or a test.

### ISS-029 — Unguarded destructive seed script
Verified · P2 · **S**. `backend/scripts/seed_database.py` L46–47 calls `Base.metadata.drop_all(engine)` then `create_all` on the configured `DATABASE_URL` (which may be Supabase/Azure), bypassing Alembic. **Fix:** refuse when `settings.is_production` or when the host is not localhost unless `--force --i-understand`; seed via Alembic `upgrade head` + inserts. **Acceptance:** running the script against a non-local URL without flags exits non-zero without changes.

### ISS-030 — Health router mounted twice
Verified · P3 · **S**. `backend/app/main.py` L82 mounts `health_router` at root, L83 mounts `api_router` (which also includes `health.router`) under `/api/v1`. The Dockerfile `HEALTHCHECK` and `run_local.sh` use the `/api/v1/health/*` paths, so the root mount serves only external probes that may target `/health`. **Fix:** keep one prefix and document probe URLs; exclude duplicates from OpenAPI (`include_in_schema=False`). Low risk.

### ISS-031 — Webhook body read before size check
Verified · P3 · **S**. `app/api/v1/github.py` L460–463 reads the whole body, then checks 5 MB. **Fix:** check `Content-Length` first and enforce a max body size at the proxy/ASGI level.

### ISS-032 — Connection budget
Suspected · P2 · **S**. `app/core/database.py` creates a sync engine (`pool_size=20`, `max_overflow=10`) and an async engine (`max(5, 20//2)=10`, `max(2, 10//2)=5`) per process → up to 45 connections per API process, plus the sync worker process, plus uvicorn workers if >1. Supabase/managed tiers commonly cap at 60–100 (**verify against the actual plan**). **Fix:** size pools per role via env, use the transaction pooler (port 6543, already supported) for API processes, and drop the unused engine per role. **Acceptance:** documented connection budget per deployment ≤ 80 % of the DB limit.

### ISS-033 — Tools & MCP admin page is mock UI
Verified · P1 · **M**. `frontend/src/pages/ToolsIntegrationsAdminPage.tsx` L25 (`INITIAL_SERVERS` constant), L89 (`useState(INITIAL_SERVERS)`); no import of `apiClient`/services; backend endpoints exist (ISS-003). Users see fabricated "connected" servers and latencies; edits are lost on reload. **Fix:** after ISS-003, add `services/mcp.ts` + `hooks/useMcpServers.ts` (TanStack Query) and bind the page; or remove the route until the feature is real. **Acceptance:** page reflects backend state; admin-only controls hidden for non-admins.

### ISS-034 — Missing `ondelete` on user FKs
Verified · P3 · **S**. `repositories.user_id`, `repositories.installation_id`, `github_installations.user_id`, `sync_jobs.user_id` have no `ondelete`. There is no account-deletion feature today, so impact is future-facing (GDPR deletion, uninstall events). **Fix:** decide policy (`CASCADE` for installations/repositories on user delete, `SET NULL` for audit tables) and add a migration. The `installation` webhook already handles `deleted`/`suspend` (`app/services/webhook_handlers.py` L253); align its row handling with the chosen FK policy.

### ISS-035 — Coverage gate scope
Verified · P2 · **S**. `pytest.ini` and the main workflow L110–114 use `--cov=app`; `ai/`, `sandbox/`, `scanner/`, `indexer/`, `review/`, `agent/` (~57k LOC including the security-critical sandbox) are not measured. **Fix:** `--cov=app --cov=ai --cov=sandbox --cov=scanner --cov=indexer --cov=review --cov=agent` with per-package floors (start at measured values; ratchet).

### ISS-036 — Project memory not used by the AI
| Field | Detail |
|---|---|
| Status / Priority | Verified (static) · P1 · **M** |
| Files / lines | `ai/pipeline.py` L204–245 (`RAGPipeline.chat(..., memory=None)` and `ContextBuilder` support memory); `app/api/v1/chat.py` L114 calls `pipeline.chat(question, repository_id, history)` without memory; no reads of `ProjectMemoryService`/`MemoryRepository` in `ai/services/task_planner.py`, `ai/agent/orchestrator.py`, review/explain/bug/test orchestrators |
| Problem | Users can pin "architectural rules" and the platform records task outcomes, but none of it influences chat, planning or review. The Project Memory panel implies otherwise. |
| Recommended solution | Add `ProjectMemoryService.get_context_memories(repository_id, query, limit, token_budget)` (pinned rules first, then semantic top-k via the existing HNSW index `ix_memory_entries_embedding_hnsw`); pass results into `RAGPipeline.chat(memory=…)`, `TaskPlanner`, and review context builders; record which memory IDs were used in the response metadata. Apply ISS-023 first. |
| Dependencies | ISS-023, FEAT-11, OPT-16 |
| Acceptance criteria | A pinned rule demonstrably appears in the prompt (trace/log) and is cited in planner output; response metadata lists memory IDs used. |

### ISS-037 — Hard-coded developer login
Verified · P3 · **S**. `frontend/src/pages/Login.tsx` L30 `devLogin('Meetvirugama')`; `backend/app/api/v1/auth.py` L383 default login. **Fix:** remove defaults; dev login takes an explicit login from `.env.local` (`VITE_DEV_LOGIN`) when enabled (ISS-002).

### ISS-038 — Silent in-memory fallback for analysis history
Verified · P2 · **S**. `app/api/v1/analysis/history.py` L113–134 wraps the DB query in `try/except Exception: pass` and then serves results from `app.state._analysis_run_history` (a 500-entry FIFO filled by `explanation_orchestrator.py` L885–895). `run_service.record_run` errors are also swallowed (`explanation_orchestrator.py` L878–882). On DB failure users see a partial, per-replica history instead of an error; persistence failures are invisible. **Fix:** remove the in-memory store; on DB error return `503` with `retryable=true`; log and count persistence failures (metric `analysis_run_persist_failures_total`). **Acceptance:** history results are identical across replicas; DB outage yields 503.

### ISS-039 — Dead `app.state` wiring
Verified (static) · P3 · **S**. Set in `lifespan.py` but never read anywhere: `app.state.explanation_history_service`, `bug_scan_history_service`, `task_history_service`, `context_service` (+ its `service_readiness` key). **Fix:** remove the assignments (and readiness keys) or route the corresponding endpoints through them consistently (choose one pattern; see DC-04).

### ISS-040 — Silent broad exception handlers
Verified (static) · P2 · **M**. 115 `except Exception:`/bare `except:` blocks whose body is only `pass`/`continue` (scan in §3.3). These hide real failures (e.g., ISS-007's import error, ISS-013's missing scanners, ISS-038's persistence errors). **Fix:** replace with specific exceptions, or log at `warning` with `exc_info=True` and a metric; enable Ruff `BLE001`, `S110`, `SIM105` in CI with a baseline. **Acceptance:** count reduced to justified cases, each with a comment.

### ISS-041 — Test-aware production code
Verified (static) · P2 · **M**. 28 occurrences in 14 files: `app/core/lifespan.py` (`PYTEST_CURRENT_TEST` gates workers/reconciliation), `app/core/auth.py` L56–58 (`is_live_environment = get_redis is default_get_redis` changes caching semantics when monkeypatched), `code_review_orchestrator.py` L208 (`_is_mock_db`), plus `bug_detection_orchestrator.py`, `api/v1/repositories.py`, `api/v1/analysis/common.py`, `ai/services/task_planner.py`, `ai/schemas/grounding.py`, `indexer/incremental.py`, `services/git_branch.py`, `explanation_orchestrator.py`, `ai/services/hierarchical_localizer.py`, `ai/retrieval/vector.py`, `ai/context/task_context.py`. Production behaviour differs from tested behaviour. **Fix:** inject dependencies (settings flags such as `run_background_workers`, repository/session interfaces) and remove environment sniffing. **Acceptance:** `grep -R "PYTEST_CURRENT_TEST\|_is_mock_db\|MagicMock" backend/{app,ai,sandbox,scanner,indexer,agent}` returns nothing.

### ISS-042 — Duplicate pull-request persistence
| Field | Detail |
|---|---|
| Status / Priority | Verified · P2 · **M** |
| Files / lines | `app/models/pull_request.py` (`pull_requests`; L22 `task_id` indexed but **no ForeignKey**); `app/models/task.py` (`TaskPullRequest` → `task_pull_requests`, FK to `tasks`); writers: `app/services/git_branch.py` L612–700 (`prepare_pr_metadata`/`get_pr_metadata`, exposed via `/repositories/{id}/source/pr-metadata*`) vs `task_execution_orchestrator.py` L2043 (Draft PR record) |
| Problem | PR metadata for the same task can live in two tables with different shapes; the frontend reads `GET /source/pr-metadata/{task_id}` (table `pull_requests`) **and** `GET /tasks/{id}/pull-request` (table `task_pull_requests`). Without an FK, `pull_requests` rows survive task deletion and can reference non-existent tasks. |
| Recommended solution | Make `task_pull_requests` canonical; add the "prepared metadata" fields it lacks (`changed_files`, `commit_message`, `test_summary`, `verification_summary`, `status`) as columns or a JSONB `metadata`; migrate rows from `pull_requests` (dedupe by `task_id`); serve `GET /tasks/{id}/pull-request` (with a `prepared` state) and retire `/source/pr-metadata*`; drop `pull_requests` in a later migration. |
| Dependencies | DC-30, FEAT-12, ISS-017 |
| Testing | Migration test with fixture rows in both tables; API test that the publication panel data comes from one endpoint. |
| Acceptance criteria | One PR table with FK `ON DELETE CASCADE`; one endpoint family. |

---

## 3. Evidence appendices

### 3.1 `async def` handlers doing synchronous DB I/O (ISS-009)

| File | Handlers (line) |
|---|---|
| `app/api/v1/analysis/bugs.py` | `detect_bugs` (60) |
| `app/api/v1/analysis/explain.py` | `explain_code` (106) |
| `app/api/v1/analysis/history.py` | `list_analysis_runs` (56), `get_analysis_runs_summary` (177), `export_analysis_runs_dataset` (269), `get_analysis_run` (382) |
| `app/api/v1/analysis/review.py` | `review_code` (67), `publish_review_to_github` (332), `submit_finding_feedback` (447), `get_repository_review_settings` (504), `update_repository_review_settings` (529) |
| `app/api/v1/analysis/tests.py` | `generate_tests` (58) |
| `app/api/v1/auth.py` | `github_callback` (176) |
| `app/api/v1/chat.py` | `chat_with_repository` (59) — ownership check uses `to_thread`, but the same sync session is then passed to the agent |
| `app/api/v1/events.py` | `stream_events` (117) — `SessionLocal()` at connect |
| `app/api/v1/github.py` | `list_github_repositories` (71), `connect_repository` (260), `link_github_installation` (370), `github_installation_callback` (402), `github_webhook` (442), `list_webhook_events` (598), `get_webhook_event` (677), `replay_webhook_event` (715), `get_repository_automation` (761), `update_repository_automation` (786) |
| `app/api/v1/health.py` | `health_readiness` (42) — `SessionLocal()` |
| `app/api/v1/issues.py` | `import_github_issue` (152), `list_repository_issues` (309), `create_github_issue` (368) |
| `app/api/v1/repositories.py` | `search_repository_get` (229), `search_repository` (253) |
| `app/api/v1/tasks.py` | `generate_task_plan` (626) |
| `app/integrations/github/routes.py` | `get_file_tree` (77), `get_file_content` (101), `list_commits` (137), `get_commit_detail` (167), `list_pull_requests` (199), `get_pull_request_diff` (224), `create_agent_branch_endpoint` (256), `commit_workspace_changes_endpoint` (296), `get_task_diff_ranges_endpoint` (395), `list_remote_issues` (426) |

Some handlers offload part of the work with `asyncio.to_thread`; each must be reviewed individually — the scan flags any handler that receives a sync `Session`.

### 3.2 Unused-import scan
82 unambiguous unused imports outside tests (name appears exactly once in its file). Largest: `ai/workflows/autonomous_task_workflow.py` (6), `app/services/test_execution_verifier.py` (6), `app/services/review_publication_service.py` (5), `app/services/incremental_review_service.py` (5), `ai/services/edit_synthesizer.py` (4), `ai/services/llm_repair_synthesizer.py` (4), `runner/main.py` (3). Availability probes such as `import onnxruntime` in `ai/retrieval/reranker_factory.py` L54 are intentional — keep with `# noqa: F401`. Full list: 05 §2.6.

### 3.3 Silent broad `except` scan (ISS-040), top files
`sandbox/workspace_manager.py` 6 · `sandbox/command_runner.py` 5 · `sandbox/container_backend.py` 5 · `sandbox/diff_verifier.py` 4 · `ai/llm/client.py` 4 · `ai/retrieval/cache_keys.py` 4 · `app/services/explanation_orchestrator.py` 4 · `app/observability/telemetry.py` 4 · `app/core/auth.py` 4 · `app/services/task_execution_orchestrator.py` 3 · `app/repositories/repository_repository.py` 3 · `app/integrations/github/service.py` 3.

### 3.4 Risk assessment

| Risk area | Level | Driving issues |
|---|---|---|
| Authentication / authorization | **High** until P0s fixed | ISS-001, ISS-002, ISS-003, ISS-004, ISS-021 |
| Production availability of core loop | **High (unverified)** | ISS-005, ISS-006, ISS-013 |
| Data durability / consistency | Medium | ISS-010, ISS-016, ISS-038, ISS-018, ISS-042 |
| Performance under load | Medium–High | ISS-009, ISS-020, ISS-024, ISS-025, ISS-032 |
| AI answer quality vs. claims | Medium | ISS-007, ISS-008, ISS-036, ISS-015 |
| Maintainability | Medium | ISS-040, ISS-041, ISS-026, DC items |
