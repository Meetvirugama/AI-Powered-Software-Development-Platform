# Testing Guide

## Test suites

| Suite | Location | Runner | Scope |
|---|---|---|---|
| Backend unit/integration | `backend/tests` (260 modules) | pytest | Services, AI pipeline (mock providers), retrieval, scanner, sandbox, API (FastAPI TestClient), persistence |
| Backend security | `backend/tests/security`, `backend/tests/security/provenance`, `test_security_*` | pytest | Auth, RBAC, CSRF/CSP, SSRF, redaction, webhook guard, git argv, taint tracking |
| End-to-end (API) | `tests/e2e/test_tier{1..4}_*.py` | pytest | Feature, boundary, combination and scenario tiers |
| End-to-end (browser) | `tests/e2e/playwright` | Playwright | Compose-based UI flows (not executed in CI) |
| Frontend | `frontend/src/test` (33 files) | Vitest + Testing Library + jsdom | Components, hooks, services, error handling, workflows |
| Load / soak | `loadtests/locustfile.py`, `loadtests/run_load_soak.py` | Locust / Python | Health latency, SSE fan-out, retention purge |
| AI quality | `backend/scripts/benchmark_quality_suite.py`, `backend/ai/evaluation` | Python | Retrieval, bug detection, review grounding, test generation gates; Mini SWE-bench |

## Running tests

```bash
# Backend (from repository root; pytest.ini sets pythonpath and testpaths)
.venv/bin/pytest                         # with coverage of app, ai, sandbox, scanner, indexer, review, agent (fail-under 40)
.venv/bin/pytest -q --no-cov backend/tests/test_rag_pipeline.py
.venv/bin/pytest -m "not slow"           # markers: unit, integration, slow

# End-to-end API tiers
.venv/bin/pytest tests/e2e

# Frontend
cd frontend && npm test -- --run         # vitest
npm run lint && npx tsc -b && npm run build

# AI quality gates
python backend/scripts/benchmark_quality_suite.py
```

## Test infrastructure

- `backend/tests/conftest.py`: FastAPI `TestClient`, dependency overrides, mock DB/Redis, VCR-style recorded LLM fixtures (`fixtures/cassettes/platform_llm_vcr.json`), settings flags that disable startup reconciliation and embedded workers.
- `backend/tests/mocks/github.py`: GitHub API mocks.
- Fixture repositories: `fixtures/python_sample`, `nodejs_sample`, `typescript_sample`, `ast_sample` (one file per supported language + malformed/unsupported cases), `framework_samples` (pytest/unittest/jest/vitest/ambiguous), `defect_fixtures`, `security/prompt_injection`.
- Evaluation fixtures: `backend/tests/evaluation/fixtures/*` (defects, clean code, false positives, security, concurrency, performance, resource management, error handling).
- Frontend: `src/test/setup.ts` boots MSW handlers from `src/mocks`.
- PostgreSQL-specific behaviour (pgvector, JSONB, FTS, migrations) is tested by the `postgres-persistence-ci.yml` workflow against `pgvector/pgvector:pg16`.

## CI gates

| Workflow | Gates |
|---|---|
| `main_ai-powered-dev-platform-api.yml` | Python syntax, ruff, bandit; `pytest backend/tests tests/e2e --cov=app --cov-fail-under=71`; oxlint, `tsc -b`; Vitest; Vite build; migrations on Postgres + pgvector; security scan; package and deploy |
| `security-ci.yml` | Gitleaks, ruff/bandit, pip-audit, security gate and RBAC suites |
| `postgres-persistence-ci.yml` | Alembic upgrade + single head, migration lifecycle and persistence tests on Postgres 16 + pgvector |
| `nightly-quality-evaluation.yml` | Quality evaluation suite on fixtures + gate evaluator tests (daily 18:30 UTC) |

> Coverage thresholds differ by entry point: CI enforces ≥71% on `app`; local `pytest.ini` enforces ≥40% across all backend packages.

## Benchmarks

| Benchmark | Conditions | Recorded result (2026-11-16 report) |
|---|---|---|
| Retrieval (10 labelled questions over `python_sample`) | In-memory fixture retrievers + RRF + MiniLM reranker; **not** pgvector | Hit@5 100%, MRR 0.870, P@1 80%, latency P95 < 1 ms |
| Bug detection (8 defect + 4 clean cases) | Built-in scanner + AST analyzer | Precision 100%, Recall 87.5%, F1 0.933, FPR 0% |
| Review grounding | Fixture changesets | Line grounding 100%, hallucination 0% |
| Test generation safety | Fixture generations | Syntax validity 83.3%, assertion presence 66.7%, unsafe paths blocked 7/7 |

These are fixture-scale regression gates, not production quality measurements. Latency figures from in-memory retrievers do not represent database retrieval latency.

## Writing tests

- Place new backend tests by feature (e.g. `test_retrieval_*`, `test_task_*`), not by person or sprint day.
- Use mock providers or recorded LLM fixtures; tests must not call real LLM, GitHub or embedding APIs.
- Mark slow or LLM-heavy tests with `@pytest.mark.slow`.
- Security-relevant changes require a negative test (the attack must fail).
