# 08 — Dependency and Configuration Audit

**Limits of this audit:** package registries could not be reached, so "latest version" and CVE status were **not verified**. Compatibility statements below are based on the declared ranges and on how the code imports each package. Run `pip-audit -r <lock>` and `npm audit --omit=dev` in CI (DEP-15) before any upgrade. No package was installed or upgraded.

---

## 1. Python dependency inventory

Source of truth today: `backend/requirements.txt` (used by `Dockerfile`, CI and Azure packaging: workflow installs `pip install -r requirements.txt` → `-r backend/requirements.txt`). `pyproject.toml` declares a **different** set (ISS-026).

| Package | `backend/requirements.txt` | `pyproject.toml` | Used by (non-test) | Finding |
|---|---|---|---|---|
| fastapi | `>=0.115,<1.0` | same | everywhere | OK |
| uvicorn[standard] | `>=0.30,<1.0` | same | `startup.sh`, `main.py` | OK |
| gunicorn | `>=22.0.0` | `>=22.0.0` | **no usage** (no import; not in `startup.sh`, Dockerfile, workflows) | **Unused** → DEP-02 |
| sqlalchemy | `>=2.0,<3.0` | same | data layer | OK |
| alembic | `>=1.13,<2.0` | same | migrations | OK |
| pydantic / pydantic-settings | `pydantic-settings>=2.5,<3.0` (pydantic transitive) | both pinned | everywhere | Pin `pydantic>=2.7,<3` explicitly in requirements too |
| redis | `>=5.0,<6.0` | same | core, workers, caches | OK |
| psycopg[binary] | `>=3.2,<4.0` | same | sync + async engines (`psycopg_async`) | OK; `[binary]` acceptable for containers; consider `psycopg[c]` built in builder stage for prod |
| pgvector | `>=0.3,<1.0` | same | models, retrieval | OK |
| httpx | `>=0.27,<1.0` | same | GitHub, LLM providers | OK |
| PyJWT[crypto] | `>=2.8,<3.0` | same | platform JWT (HS256) + GitHub App (RS256) | OK |
| sentence-transformers | `>=5.6.0,<7.0` | **`>=3.0,<4.0`** | `ai/retrieval/reranker.py` (lazy import) | **Version conflict** → DEP-01 |
| transformers | `>=5.22.0,<6.0` | — | no direct import (transitive of sentence-transformers) | Keep only as a compatibility pin, documented; otherwise remove → DEP-03 |
| tiktoken | `>=0.7,<1.0` | same | `ai/context/*` token budgets | OK |
| pathspec | `>=0.12.0` | same | `scanner/walker.py` | Add upper bound `<1` |
| greenlet | `>=3.0.0` | same | SQLAlchemy async | OK |
| tree-sitter, tree-sitter-language-pack, tree-sitter-{python,javascript,typescript} | ranges | same | `scanner/parser.py` (pack first, per-language bindings as fallback) | Two providers of grammars → DEP-04 (keep pack only if it covers all 8 languages; verify) |
| dbos | `>=3.4.0` | — | `ai/workflows/autonomous_task_workflow.py` (decorator only, never launched), `poc/dbos` | **Effectively unused at runtime** → DEP-05 (decide with ISS-010) |
| jsonschema | `>=4.23,<5` | — | `agent/tools/schema_validator.py` | Missing from pyproject |
| opentelemetry-* (api, sdk, exporter-otlp-proto-http, instrumentation-fastapi/httpx/sqlalchemy/redis) | `>=1.25` / `>=0.45b0` | — | `app/observability/*` | Missing from pyproject; instrumentation packages are pre-1.0 "b" releases with an open upper bound → pin to a tested set (DEP-06) |
| langfuse | `>=2.0.0,<6.0.0` | — | `app/observability/langfuse_adapter.py` | Range spans 4 majors with different APIs → pin the tested major (DEP-06) |
| ruff, bandit | **only in `requirements-dev.txt`** | runtime deps | `review/static_reviewer.py` invokes `python -m ruff/bandit` **at runtime** | **Missing at runtime** (ISS-013) → DEP-07 |
| onnxruntime | — | — | optional import in `reranker_factory.py`/`reranker_onnx.py` | Optional extra `[onnx]` if OPT-14 adopts it |
| asyncpg | — | — | none (compose sets an `asyncpg` URL that is never read) | Do not add; remove the env var (ISS-027) |

**Dev (`backend/requirements-dev.txt`):** pytest, pytest-asyncio `>=0.24,<1.0` (pyproject `>=0.23`), pytest-cov, respx (27 test files), responses (1 test file → candidate to drop, DEP-08), ruff, bandit, pip-audit.

**Runtime binaries (not Python packages) expected by code:** `git` (installed in image), `docker` (container sandbox — **absent**), `semgrep`, `osv-scanner`, `gitleaks` (all **absent**), `node`/`npx` for ESLint/Biome review (**absent**). See ISS-006, ISS-013.

**Model artefacts:** reranker downloads `cross-encoder/ms-marco-MiniLM-L-6-v2` from Hugging Face at first use (`ai/retrieval/reranker.py` L25); the image does not pre-fetch it → cold-start latency and runtime egress to huggingface.co (DEP-09).

**Python version:** Docker `python:3.11-slim` (digest-pinned, good), CI 3.11, `requires-python >=3.11`. Local audit environment was 3.13 — no compatibility claims made for 3.12/3.13.

---

## 2. Frontend dependency inventory (`frontend/package.json`)

| Package | Range | Used | Finding |
|---|---|---|---|
| react / react-dom | `^19.2.8` | yes | OK |
| react-router-dom | `^7.18.4` | 29 files | OK (v7 re-exports from `react-router`; consider `react-router` directly — optional) |
| @tanstack/react-query | `^5.103.2` | 13 files | OK |
| axios | `^1.20.0` | 2 files | OK |
| zustand | `^5.0.15` | 2 stores | OK |
| clsx, tailwind-merge | yes | `lib/utils.ts` | OK |
| lucide-react | `^1.47.0` | 52 files | OK |
| tailwindcss / @tailwindcss/postcss | `^4.3.3` | yes (`@config "../tailwind.config.js"`) | v4 with legacy JS config via `@config` — works; migrating to CSS-first `@theme` is optional |
| autoprefixer | `^10.6.1` | `postcss.config.js` | **Likely redundant** with Tailwind v4 (DC-25, DEP-10) |
| typescript | `~6.0.2` | yes | Pinned minor — good |
| vite | `^8.3.0`, @vitejs/plugin-react `^6.1.1`, vitest `^4.1.12`, jsdom `^29`, oxlint `^1.81` | yes | Lint uses **oxlint** while backend uses Ruff — fine |
| msw | **not a dependency** | aliased to local shim | DC-19: replace shim with real `msw` dev dependency |

`package-lock.json` exists — CI uses `npm ci` (good).

---

## 3. Configuration audit

### 3.1 Settings vs environment files

`Settings` (`backend/app/core/config.py`) declares 141 fields. Cross-check results:

| Check | Result |
|---|---|
| Keys in `.env.example` not in Settings | none |
| Keys in `.env.production.example` not in Settings | `PORT`, `WEBSITES_PORT` (consumed by `startup.sh`, fine) |
| Keys in `docker-compose.yml` not in Settings | `ASYNC_DATABASE_URL` (**unused**, ISS-027), `SERVICE_ROLE`, `PORT` (startup.sh), `POSTGRES_*` (db container) |
| Settings read via `getattr(settings, name, default)` that **do not exist** | `symbol_graph_expansion_enabled` (ISS-007), `disable_embedded_webhook_worker` (ISS-014) |
| Settings declared but never read | `ai_max_concurrent_calls` (ISS-025); `retrieval_graph_*` limits (ISS-007); `reranker_backend`, `reranker_onnx_enabled`, `reranker_quantization` (only via unused factory, ISS-008); `sandbox_max_concurrent_tasks`, `sandbox_max_lifetime`, `sandbox_idle_timeout` (no reader anywhere outside `config.py`); `allow_local_embeddings` (eval only) |
| Direct `os.environ` reads in backend | `RUNNER_AUTH_SECRET`, `RUNNER_ALLOW_UNAUTHENTICATED_DEV` (`runner/main.py`, duplicates Settings fields), process env pass-through keys in sandbox (`PATH`, `HOME`, `LANG`, `TEMP`…) |

### 3.2 Configuration inconsistencies

| ID | Inconsistency | Evidence | Recommendation |
|---|---|---|---|
| DEP-11 | Compose default `JWT_SECRET`; example placeholders accepted | ISS-001 | `${JWT_SECRET:?}`; empty placeholders in all examples; stronger validator |
| DEP-12 | `APP_ENV` defaults to `development` | `config.py` L30 | Make `APP_ENV` required (no default) or default to `production` and require explicit dev mode (ISS-002) |
| DEP-13 | Worker topology flags: prod forces `DISABLE_EMBEDDED_SYNC_WORKER=true`; webhook flag missing; deploy job has a single web app | ISS-005, ISS-014 | Explicit per-role env files: `api.env`, `sync_worker.env`, `webhook_worker.env`; deploy all roles |
| DEP-14 | Sandbox: compose prod → `container` (no docker); prod example → `runner` (runner not deployed) | ISS-006 | Add runner service; fail readiness when unavailable |
| DEP-16 | Cookie policy: example says `SameSite` **must** be `none` | `.env.production.example` L47–49 | With Vercel `/api` rewrite, use `lax` (ISS-021); keep `none` only when the API is called cross-site |
| DEP-17 | Postgres versions: compose `pg15`, CI persistence workflow PG16 | `docker-compose.yml`, `postgres-persistence-ci.yml` | Align on one major (match production: Supabase/Azure version — verify) |
| DEP-18 | Duplicate `vercel.json` with hard-coded Azure hostname | root and `frontend/` | One file; document the API origin as a deploy variable |
| — | `RUNNER_AUTH_SECRET=dev-runner-secret-key-12345` in `.env.example` | `.env.example` | Leave empty; runner should refuse to start without it (it fails closed already unless `RUNNER_ALLOW_UNAUTHENTICATED_DEV`) |
| — | `GROQ_CHAT_MODEL` default `openai/gpt-oss-120b` vs README "llama-3.3-70b-versatile" | `config.py` L80, README | Fix README (ISS-028) |
| — | `.dockerignore` excludes `*.md` | `.dockerignore` | Safe today (prompts are `.txt`); keep a test that `validate_required_prompts()` passes inside the built image |
| — | `pytest.ini` coverage only `app` | ISS-035 | Extend |

### 3.3 Docker / deployment configuration
- Multi-stage, digest-pinned base, non-root user, healthcheck, `PYTHONDONTWRITEBYTECODE` — good.
- Runtime image copies the whole repo minus `.dockerignore` exclusions; `backend/ai/evaluation/mini_swebench/dataset` and `backend/scripts` ship in the image (harmless, small) — optional exclusion.
- `startup.sh` runs `alembic upgrade head` on **every** API start in production (`RUN_MIGRATIONS_ON_STARTUP` default true). With multiple replicas this races. Recommendation: run migrations as a one-off release step (CI job or init container) and set `RUN_MIGRATIONS_ON_STARTUP=false` for replicas.
- `startup.sh` with `TRUST_PROXY_HEADERS=true` sets `--forwarded-allow-ips="${FORWARDED_ALLOW_IPS:-*}"` — `*` trusts any client's `X-Forwarded-For` when the app is reachable directly (bypassing Azure front end). Set `FORWARDED_ALLOW_IPS` to the platform's proxy range; this also affects IP-based rate limiting.

---

## 4. Dependency cleanup and upgrade plan

| ID | Action | Compatibility check before change | Risk |
|---|---|---|---|
| DEP-01 | Resolve sentence-transformers range: keep `>=5.6,<7` (what Docker/CI install) and delete the pyproject range | Run reranker unit tests + `CrossEncoder` load in the built image | Low |
| DEP-02 | Remove `gunicorn` | `grep -R gunicorn` (none) | Very low |
| DEP-03 | Decide on `transformers` pin (keep with comment, or drop) | `pip check` in built image | Low |
| DEP-04 | Grammar providers: verify `tree-sitter-language-pack` covers Python, TS, JS, Go, Rust, Java, C, C++; if yes, drop individual bindings | `tests/test_modernize_code_intelligence.py` + parser tests per language | Medium |
| DEP-05 | `dbos`: remove with `poc/dbos` and the decorator shim **or** adopt properly (OPT-08) | — | Low |
| DEP-06 | Pin OTel instrumentation and Langfuse to tested versions (lock file) | Observability unit tests; manual trace export | Low |
| DEP-07 | Scanners: install where they run (runner image preferred) with pinned versions; add `ruff`, `bandit` to the runtime manifest of that image | Container smoke test (`--version`) | Low |
| DEP-08 | Drop `responses` if the single test can use `respx`/`httpx.MockTransport` | That test passes | Very low |
| DEP-09 | Pre-download the reranker model in the image build (or mount a cache) and set `HF_HUB_OFFLINE=1` at runtime | Cold-start time; offline load works | Low |
| DEP-10 | Remove `autoprefixer` | CSS diff of `vite build` output | Low |
| DEP-15 | Add automated dependency updates (Dependabot/Renovate) and `pip-audit`/`npm audit` CI gates on the lock files | — | — |
| ISS-026 | **Single manifest**: move everything to `pyproject.toml` (`[project.dependencies]`, extras `dev`, `scanners`, `eval`, `onnx`); generate `requirements.lock` with `uv pip compile`/`pip-compile --generate-hashes`; Dockerfile/CI install from the lock | Build image; full test suite | Medium |

**Upgrade policy:** no blind upgrades. Upgrade one ecosystem per PR, from the lock file, with full test suite + benchmark suites (retrieval, quality) where AI libraries change.
