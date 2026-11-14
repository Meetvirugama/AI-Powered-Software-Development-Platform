# 10. Development Tasks — Master Task Board
> **Version:** 4.0 | **Created:** 2026-09-24 | **Last Updated:** 2026-11-08

> [!NOTE]
> Task data is synchronized with `Docs/daily_tasks.md`, `Docs/week1.md`, `Docs/week2.md`, `Docs/week3.md`, `Docs/retrieval/`, and `Docs/agentic-chat/`.

---

## Status Legend

```
DONE        — Merged, tested, and verified
IN PROGRESS — Actively being implemented
TODO        — Planned and scheduled
BLOCKED     — Waiting on dependency or review
```

---

## WEEK 1 — Repository Intelligence Foundation (100% COMPLETE)

### Week 1 Milestone Goal
A user connects a GitHub repository, the backend clones and scans it, extracts symbols and dependency edges, indexes chunks into pgvector, and answers grounded questions via the fixed-viewport React 19 Workbench with source citations.

| Task ID | Task | Owner | Priority | Status | Verification / Artifacts |
|---|---|---|---|---|---|
| W1-01 | FastAPI project skeleton + config + logging | Yug | P0 | DONE | `app/main.py`, `app/core/logging.py`, health API |
| W1-02 | Database foundation + pgvector + migrations | Om | P0 | DONE | Alembic migrations, `code_chunks`, `memory_entries` |
| W1-03 | GitHub App integration + OAuth flow | Parth / Yug | P0 | DONE | `app/integrations/github/`, JWT cookie auth |
| W1-04 | Repository Sync Service & Redis queue | Yug / Parth | P0 | DONE | `app/services/repository_sync.py`, worker loop |
| W1-05 | tree-sitter AST parser & language detector | Prit | P0 | DONE | `backend/scanner/`, 8 languages detected |
| W1-06 | Symbol & edge extractor | Prit | P0 | DONE | `symbols.py`, `graph.py`, symbol tables |
| W1-07 | Symbol chunker & tiktoken token counter | Devu | P0 | DONE | `backend/indexer/chunker.py` |
| W1-08 | LLM Gateway (Gemini + Groq) | Meet | P0 | DONE | `backend/ai/llm/client.py`, schemas & retries |
| W1-09 | Embedding service & pgvector storage | Meet | P0 | DONE | `backend/ai/embeddings/service.py` |
| W1-10 | Hybrid retrieval (Vector + Lexical FTS + RRF) | Meet | P0 | DONE | `vector.py`, `lexical.py`, `fusion.py`, `reranker.py` |
| W1-11 | ContextBuilder with token budget & truncation | Meet | P0 | DONE | `backend/ai/context/builder.py` |
| W1-12 | Prompt builder & output/grounding validator | Dev | P0 | DONE | `prompt_builder.py`, `validator.py`, `grounding.py` |
| W1-13 | End-to-end RAG pipeline | Meet / Dev | P0 | DONE | `backend/ai/pipeline.py` |
| W1-14 | Repository chat & search APIs | Yug | P0 | DONE | `POST /chat`, `POST /search` |
| W1-15 | React 19 Workbench UI (Fixed Viewport + Panels) | Dhramraj | P0 | DONE | `frontend/src/pages/RepositoryChat.tsx` |
| W1-16 | Security baseline, secret scrubbing & isolation | Sukun | P0 | DONE | `SecretScanner`, multi-tenant isolation tests |
| W1-17 | Comprehensive regression test suite | Keval | P0 | DONE | 369 passed tests, 71.31% code coverage |

---

## WEEK 2 — Developer Intelligence Suite (100% COMPLETE)

### Week 2 Milestone Goal
Provide four standalone, production-ready developer intelligence capabilities in the Workbench: Code Explanation, Bug Detection, Test Generation, and Standalone AI Code Review.

| Task ID | Task | Owner | Priority | Status | Deliverables |
|---|---|---|---|---|---|
| W2-01 | Shared `IntelligenceContext` interface & token bounding | Meet | P0 | DONE | `build_intelligence_context()`, `TargetSnippet`, caller graph |
| W2-02 | Pydantic output schemas (`CodeExplanation`, `BugFinding`, `TestGen`, `ReviewReport`) | Dev | P0 | DONE | `backend/ai/schemas/` models & validation tests |
| W2-03 | Repository Explorer & Drawer UI foundations | Dhramraj | P0 | DONE | Source viewer with line numbers & feature action buttons |
| W2-04 | Analysis API routing (`/explain`, `/detect-bugs`, `/generate-tests`, `/review`) | Yug | P0 | DONE | Validated request/response schemas & repository auth |
| W2-05 | Analysis run persistence (`analysis_runs`, `code_findings`) | Om | P0 | DONE | SQLAlchemy models, Alembic migration, `AnalysisRunRepository`, History Services (Day 1–7: Explain, Bugs, Tests, Review, Integrity & Day 7 Acceptance Suite, 87/87 tests passing) |
| W2-06 | GitHub source service (files, commits, PR diffs) | Parth | P0 | DONE | Authorized diff provider, revision integrity |
| W2-07 | AST symbol range resolution, target selector & rule integration | Prit | P0 | DONE | Exact line mapping, `TargetSelector`, and `ASTBugAnalyzer` with 10 structural rules |
| W2-08 | Static scanner adapter (Ruff, Bandit, secret scanner) | Devu | P0 | DONE | Normalized static finding schemas & deduplication |
| W2-09 | Prompt-injection boundaries & secret redaction | Sukun | P0 | DONE | Untrusted code boundaries & security test suite |
| W2-10 | QA defect fixtures & acceptance test matrix | Keval | P0 | DONE | Fixture repository with known bugs, QA evaluation suite |
| W2-11 | Feature 1: `CodeExplanationService` & pipeline | Dev / Meet | P0 | DONE | Purpose, logic flow, key symbols, data flow, limitations (Meet context enrichment done) |
| W2-12 | Feature 2: `BugDetectionEngine` (Static + AI) | Dev / Devu | P0 | DONE | Off-by-one, null safety, resource leak, exception analysis |
| W2-13 | Feature 3: `TestGenerationService` & `FrameworkDetector` | Dev / Prit | P0 | DONE | `FrameworkDetector` (DONE - Prit), test file generation (Dev) |
| W2-14 | Feature 4: `AICodeReviewEngine` & `ReviewSourceMapper` | Dev / Parth / Prit | P0 | DONE | `ReviewSourceMapper` (DONE - Prit), diff review engine (Dev/Parth) |
| W2-15 | Week 2 Integration, Hardening & Acceptance Gate | All | P0 | DONE | Scenarios A–E, zero mock in production, docs update (Meet: Shared context verification, provider policy & budget audit DONE; Prit: AST & framework reliability, Day 7 acceptance suite & language limitations DONE; Om: Persistence & Migration Acceptance Suite 87/87 DONE; Keval: QA Acceptance Suite 37/37 DONE) |

---

## WEEK 3 — Workflow Automation, GitHub Ecosystem & PR (100% COMPLETE)

### Week 3 Milestone Goal
Convert verified developer intelligence into a controlled development workflow: Issue intake -> Task planning -> Human Approval Gate -> Isolated workspace -> Bounded test repair -> Verification -> GitHub Draft PR.

| Task ID | Task | Owner | Priority | Status | Deliverables |
|---|---|---|---|---|---|
| W3-01 | GitHub Issue Intake & Finding-to-Issue Converter (F31) | Parth / Yug | P0 | DONE | Issue import API, finding ownership validation, issue creation from findings (`PR #139, #143, #165`) |
| W3-02 | Task Planner & Structured Plan Schema (F32) | Meet / Dev | P0 | DONE | Meet: `TaskPlanner`, step dependencies, DAG validation & fallback plan synthesis DONE (`backend/ai/services/task_planner.py`, `backend/tests/test_meet_w3_all_days.py`); Dev: `PlannerSchema` DONE |
| W3-03 | Mandatory Human Approval Gate (F32) | Meet / Dhramraj | P0 | DONE | Meet: Server-enforced approval, invalidation on plan revision, approval gate endpoints DONE (`backend/ai/services/task_planner.py`, `backend/tests/test_week3_day1_day2.py`); Dhramraj: UI approval screen |
| W3-04 | Isolated Workspace & Task Branch Manager (F33) | Prit / Parth | P0 | DONE | Prit: `WorkspaceManager` execution start, human approval gate, lifecycle transitions, command allowlist runner, timeline events & Devu `ToolRouter` policy bridge DONE; Parth: Task branch manager |
| W3-05 | Tool Router & Allowed Command Policy Engine (F34) | Devu / Sukun | P0 | DONE | Command allowlist, sandboxed tool dispatch, audit logging (`backend/agent/tools/router.py`, `PR #163, #169`) |
| W3-06 | Restricted Test Runner & Execution Loop (F35) | Prit / Devu | P0 | DONE | Prit: Restricted test runner (`WorkspaceTestRunner`), failure classification, bounded 3-attempt repair loop & ToolRouter bridge DONE; Devu: Command allowlist |
| W3-07 | Bounded Self-Repair Loop (Max 3 attempts) (F35) | Meet / Dev | P0 | DONE | Meet: `BoundedRepairLoop` orchestrator, 3-attempt ceiling, duplicate patch rejection, re-test cycle DONE (`backend/ai/services/bounded_repair_loop.py`, `backend/tests/test_meet_w3_all_days.py`); Dev: Traceback diagnosis & patch validator DONE |
| W3-08 | Independent Verification & Review Engine (F36) | Dev / Keval / Prit | P0 | DONE | Prit: `WorkspaceDiffVerifier` diff extraction, approved scope validation, addition-level secret scanner & manifest deletion protection DONE (`Docs/independent_verification_and_draft_pr_audit.md`, `backend/sandbox/diff_verifier.py`, 30/30 tests passed); Dev: AI code review (`requirement_verifier.py`) |
| W3-09 | Authorized Push & GitHub Draft PR Creator (F37) | Parth / Yug / Prit | P0 | DONE | Prit: Authorized git commit & push, protected branch guards, draft PR preparation with structured task summary & ToolRouter dispatch DONE (`Docs/independent_verification_and_draft_pr_audit.md`, `backend/sandbox/workspace_manager.py`, `backend/sandbox/tool_policy_bridge.py`); Parth: GitHub draft PR API |
| W3-10 | Task Dashboard, Progress & Timeline UI (F38) | Dhramraj | P0 | DONE | Live task progress, timeline events, side-by-side diff (`RepositoryTaskStudio.tsx`, `ExecutionTimeline.tsx`) |
| W3-11 | Persistence, Checkpoints & Crash Recovery (F39) | Om / Yug / Prit | P0 | DONE | Prit: Workspace crash/restart recovery, stale revision divergence detection, verification diff immutability, orphan collection & task concurrency locking DONE (Docs/reliability_security_and_failure_recovery_audit.md, 32/32 tests passed); Om: Days 1-7 complete: database query performance, composite index optimization across all tables, append-only audit event immutability, worker restart crash recovery with retry budget preservation, 17-step end-to-end workflow acceptance, zero manual intervention verification (74/74 cumulative persistence tests passing) (Docs/persistence_week3_day6_day7_report.md, ackend/tests/test_om_w3_d6_d7_performance_recovery_acceptance.py) |
| W3-12 | Security Attack Matrix & Release Sign-off (F40) | Sukun / Keval / Prit | P0 | DONE | Prit: Week 3 Day 7 End-to-End Acceptance (Scenarios A-J, 17-step lifecycle, SLA benchmarks, zero-leak audit trail, 194/194 tests passed) DONE (`Docs/week3_day7_workspace_acceptance_report.md`, `backend/tests/test_prit_w3_d7_acceptance.py`); Sukun/Keval: Full E2E demo signoff |

---

## POST-WEEK 3 — Enterprise Hardening & Advanced Intelligence (100% COMPLETE)

### Post-Week 3 Milestone Goal
Harden security primitives to enterprise standards, establish durable and idempotent GitHub webhook event processing with lease-based workers, build a production-grade 7-stage code retrieval engine, and deliver bounded, tool-augmented repository chat with dual LLM provider support.

| Task ID | Task | Owner | Priority | Status | Deliverables |
|---|---|---|---|---|---|
| PW3-01 | **JWT & OAuth Security Hardening (F-34)**<br>(Issue #181, PR #202) | Meet / Sukun | P0 | DONE | Timing-safe HMAC JWT signature verification, mandatory >=32-byte secret enforcement, atomic Redis CSRF state nonces via `GETDEL`, cookie security hardening (`app/core/security.py`, `app/api/v1/auth.py`, `backend/tests/test_jwt_and_oauth_hardening.py`) |
| PW3-02 | **Durable Webhook & Event Automation (F-35)**<br>(Issue #182, PR #219) | Meet / Parth | P0 | DONE | `github_webhook_events` durable state machine table, lease-based background worker (`webhook_worker.py`), automated push re-indexing, PR review bot with comment emission, replay API (`backend/tests/test_durable_webhook_automation.py`) |
| PW3-03 | **Multi-Stage Code Retrieval Engine (F-36)**<br>(Issue #187, PR #220) | Meet | P0 | DONE | 7-stage retrieval pipeline: intent detection, simple GIN lexical FTS (`code_search_text`), adaptive HNSW savepoints, 1-hop symbol graph expansion, ONNX cross-encoder reranking, Redis cache with active generation invalidation, 150-query benchmark (`backend/app/retrieval/`, `backend/tests/test_hybrid_retrieval.py`, `backend/tests/test_reranker_onnx.py`) |
| PW3-04 | **Bounded Agentic Repository Chat (F-37)**<br>(Issue #188, PR #220) | Meet / Dhramraj | P0 | DONE | Normalized Gemini & Groq tool calling, read-only repo tools (`search_code`, `read_file_range`, `find_symbol`, `list_directory`), `ExecutionPolicy` path traversal guard, `BudgetManager` (tokens/rounds/time), dual-mode API, React UI mode switch & tool badge inspection (`backend/app/ai/agent/`, `backend/tests/test_agent_*.py`, `frontend/src/pages/RepositoryChat.tsx`) |
| PW3-05 | **API Security, Role-Based Access Control (RBAC) & CI Security Pipeline (F30)**<br>(Issue #211) | Om / Sukun | P0 | DONE | Role-Based Access Control (Admin > Developer > Viewer) across all API routes, JWT role and permission claims, multi-tenant isolation preservation, Alembic migration for user role, pre-commit and CI Gitleaks integration, Bandit, Ruff, pip-audit and security gate pipeline (`.github/workflows/security-ci.yml`, `backend/tests/test_rbac_and_api_security.py`, `Docs/security/api_security_rbac_and_ci_report.md`) |
| PW3-06 | **Independent Verification & Multi-Engine Security (F25)**<br>(Issue #206) | Om | P0 | DONE | Secondary Gitleaks secret detection engine (`GitleaksDiffScanner`), `.gitleaks.toml` allowlist handling, P-28 LLM-as-judge requirement verification with structured `DiffHunkCitation` & `CriterionJudgeEvidence`, PR Markdown citations table, 19/19 tests passing (`backend/sandbox/gitleaks_scanner.py`, `backend/ai/services/requirement_verifier.py`, `backend/tests/test_independent_verification_f25.py`, `Docs/security/independent_verification_f25_report.md`) |
| PW3-07 | **Amortized Static Scanner Subprocess Execution & Parallel Analysis (F39)**<br>(Issue #243) | Meet / Dev | P1 | DONE | Batch target amortization via `--` separator, concurrent subprocess execution via `asyncio.create_subprocess_exec` & `asyncio.gather`, AST multi-file scanning, 85-90% latency reduction (`backend/review/static_reviewer.py`, `backend/scanner/static_bug_scanner.py`, `backend/tests/test_amortized_static_reviewer_f39.py`, `Docs/code-review/AMORTIZED_STATIC_SCANNER_PERFORMANCE.md`, `Docs/engineering/32_amortized_static_scanner_parallel_analysis.md`) |
| PW3-08 | **Redis Singleton & Bounded Connection Pooling (F40)**<br>(Issue #244) | Meet / Dev | P1 | DONE | Thread/coroutine-safe double-checked lock, explicit `max_connections=50` ceiling, `run_with_redis_retry` exponential backoff, clean shutdown draining, 12/12 tests passing (`backend/app/core/redis.py`, `backend/app/core/config.py`, `backend/tests/test_redis_reliability_f40.py`, `Docs/engineering/33_redis_singleton_and_bounded_connection_pooling.md`, `Docs/engineering/13_architecture_decisions.md` ADR-020) |
| PW3-09 | **Stream Unified Git Diffs & Memory-Bound Patch Verification (F40/F41)**<br>(Issue #245) | Meet / Dev | P1 | DONE | Incremental generator diff parsing (`iter_diff_lines`, `iter_parse_unified_diff`), 10MB memory threshold with truncation markers, early path guard interception, dual-engine secret stream scanning, peak heap memory < 20MB, 19/19 tests passing (`backend/sandbox/diff_verifier.py`, `backend/sandbox/gitleaks_scanner.py`, `backend/app/services/repair_service.py`, `backend/tests/test_stream_diff_verifier_f40.py`, `Docs/engineering/34_stream_unified_git_diffs_and_memory_bound_patch_verification.md`, `Docs/engineering/13_architecture_decisions.md` ADR-021) |

---

## Current Team Assignments

| Member | Current Focus | Deliverables |
|---|---|---|
| **Meet** | AI Architecture, Retrieval & Agent Lead | 7-stage retrieval engine (`retrieval/`), ONNX reranker, symbol graph expansion, `AgentOrchestrator`, `ToolRegistry`, `ExecutionPolicy`, `BudgetManager`, normalized tool calling, durable webhooks & security hardening |
| **Dev** | Schemas, AI Engines & Verifier Lead | Pydantic output schemas, failure traceback diagnosis, independent verification, AI quality evaluation |
| **Dhramraj** | Frontend Studio & Workbench Lead | Agentic chat UI mode toggle, tool call badges, execution metrics drawer, Task Studio, MSW bootstrap (329/329 tests passing) |
| **Yug** | API Gateway & Service Orchestration Lead | FastAPI routing, dual-mode chat endpoint, webhook event management endpoints, repo automation endpoints |
| **Om** | Workflow Automation, Database Persistence & Security Infrastructure | 13 linear database migrations, `users.role` RBAC migration, API route security guards, security gate allowlist & test suites, `github_webhook_events` table, `code_search_text` GIN index, repository active index generation tracking, F25 Secondary Gitleaks Engine & P-28 LLM-as-judge Requirement Verification |
| **Parth** | GitHub Ecosystem & Branch Manager Lead | GitHub App OAuth, durable webhook ingestion, push-sync and PR review comment automation |
| **Prit** | Repository Engine & Workspace Lead | `WorkspaceManager`, `WorkspaceDiffVerifier`, `WorkspaceTestRunner`, tree-sitter AST, symbol graph extraction |
| **Devu** | Tool Router & Policy Lead | Policy-enforced `ToolRouter`, command allowlists, read-only repo tool execution |
| **Sukun** | Security Architecture Lead | Timing-safe HMAC verification, secret entropy validation, Redis state nonces, path traversal guards |
| **Keval** | Quality Assurance Lead | 500+ backend regression tests, 150-query retrieval benchmark, QA acceptance sign-off |

