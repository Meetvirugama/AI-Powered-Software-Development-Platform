# Known Limitations

Verified against the source at commit `5d0b3ff` (2026-11-16).

| # | Area | Limitation | Evidence | Impact |
|---|---|---|---|---|
| L1 | Task workflows | Background workflows run in `threading.Thread` with an in-memory registry (`_active_workflows`). DBOS decorators are present but no DBOS runtime is launched. | `ai/workflows/autonomous_task_workflow.py` | A restart loses in-flight workflow state; recovery relies on checkpoints and `RECOVERY_REQUIRED` reconciliation. Multiple API replicas do not share workflow status. |
| L2 | Chat | No token streaming: the full answer is published once to the SSE stream after generation. | `app/api/v1/chat.py` | Perceived latency equals full generation time. |
| L3 | Chat | No server-side conversation history; the client sends history with each request and keeps it in component state. | `RepositoryChatRequest.history`, `useRepositoryChat` | Conversations are lost on reload. |
| L4 | MCP registry | Registered servers are stored in a process-local dict; ping always contacts the in-process platform MCP server. | `app/api/v1/mcp_registry.py` | Registrations disappear on restart and differ between replicas; ping latency does not reflect the registered endpoint. |
| L5 | Production sync | The embedded sync loop is disabled by default in production and CI deploys only the API role. | `app/core/config.py`, CI `deploy` job | Repositories stay queued unless a `sync_worker` is deployed or the embedded loop is re-enabled. |
| L6 | Sandbox | The production image has no Docker CLI; isolated execution in production requires a provisioned runner host. | `Dockerfile`, `sandbox/factory.py` | Without a runner, tests/repair/execution-verified test generation cannot run in production. |
| L7 | Static scanners | ruff/bandit are dev dependencies; Semgrep, OSV-Scanner, Gitleaks and SCIP are optional binaries not in the image. | `backend/requirements*.txt`, `Dockerfile` | In production, bug detection and review rely on built-in AST/taint analysis and the LLM unless binaries are installed. |
| L8 | Readiness metric | `webhook_backlog` in `/health/ready` reads a Redis list, while webhook events are queued in the database table. | `app/api/v1/health.py` | The backlog figure may not reflect pending webhook events. |
| L9 | PR persistence | Two PR tables exist: `pull_requests` (prepared metadata, `task_id` without FK) and `task_pull_requests` (published PRs). | `app/models/pull_request.py`, `app/models/task.py` | Possible divergence between prepared metadata and published PRs. |
| L10 | Code size | Several modules exceed 1,000 lines (`task_execution_orchestrator.py` 2.5k, `workspace_manager.py` 2.1k, `api/v1/tasks.py` 2.0k). | `wc -l` | Harder review and testing. |
| L11 | Benchmarks | The quality-gate retrieval benchmark uses in-memory fixture retrievers over 10 questions; `benchmark_rag.py` reuses it. | `backend/scripts/benchmark_quality_suite.py` | Results do not measure pgvector retrieval quality or latency. |
| L12 | E2E | The active end-to-end suite exercises the API through pytest. Frontend tests exercise components and workflows through Vitest. | `tests/e2e`, `frontend/src/test` | Full browser flows lack automated regression coverage. |
| L13 | Coverage gates | CI enforces 50% combined coverage on `app` and `ai`. The local pytest default enforces 40% across seven backend packages. | CI workflow, `pytest.ini` | Local and CI reports measure different package sets. |
| L14 | Deprecated routes | `/repositories/{id}/source/task/*` and `/source/task-workspace/*` remain mounted (deprecated duplicates). | `openapi.json` | Larger attack surface; clients should use `/tasks/{id}/*`. |
| L15 | Pricing | Cost estimates use a static price table. | `app/core/stage_metrics.py` | Cost numbers may be stale. |
| L16 | Exception handling | 532 `except Exception` clauses remain across backend packages (most log or re-raise). | `grep` | Some failures may be degraded rather than surfaced. |
