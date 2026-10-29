AI-Powered Software Development Platform — Deep Cross-Checked Audit
Audit date: 2026-10-28
Artifact reviewed: AI-Powered-Software-Development-Platform-main (2).zip
Target: Source-based audit and prioritized changes through Week 2 only.
Scope exclusions: Autonomous issue-to-PR, autonomous branch creation, agent tool execution, deployment automation, and other Week 3 workflow features are not implementation targets in this plan.
0. Executive conclusion
This repository is a substantial prototype, not a blank project. It contains a React/TypeScript frontend, FastAPI backend, SQLAlchemy/Alembic persistence, PostgreSQL/pgvector retrieval, Redis-backed sync/events/rate limiting, GitHub integration, AST scanning, four AI analysis features, and a sizeable test suite.

The most valuable next step is controlled consolidation and verification, not a broad rewrite and not mass deletion. There are real cross-layer correctness and maintainability risks, but many apparent duplicates serve different compatibility or feature-specific roles. Preserve those until callers, API contracts, database effects, and tests are traced.
What was actually checked
- Extracted the supplied ZIP and inventoried its source tree (564 archive entries; 302 .py, 75 .ts/.tsx combined, and 50 .md files, plus configs, fixtures, assets and migrations).
- Read top-level README/task plan, package manifests, requirements, Docker Compose, environment example, route registration, application startup/readiness, repository chat route, JWT/rate-limit middleware, core retrieval pipeline, analysis history/persistence interfaces, shared studio file-selection hook, workspace layouts and selected feature pages.
- Compared selected claims in README and Docs/ against current implementation structure.
- Parsed 304 Python source files successfully with Python's AST parser, excluding the intentionally malformed syntax fixture.
- Attempted backend test collection. It fails before tests execute because psycopg is missing in the audit environment.
- Did not run frontend build/lint/tests because frontend/node_modules is absent. No production build or full runtime verification is claimed.
Evidence labels
- Verified: directly supported by the source or by a reproducible command result in this audit.
- Strong concern: directly supported code pattern with a credible correctness, security, or performance consequence; runtime impact should be regression-tested.
- Needs runtime verification: source suggests a possible problem, but configuration/runtime/database behavior is required to prove it.
- Not a defect by itself: suspicious-looking structure that should not be removed without deeper caller tracing.
1. Repository inventory and architecture map
1.1 Main structure
Area	Current role	Audit direction
frontend/src/App.tsx	Lazy-loaded protected routes and nested repository studio routes	Keep route contracts; add route/refresh/navigation tests
frontend/src/layouts/	App shell, protected route and repository workspace layout	Keep one shared shell; verify height/overflow behavior at laptop widths
frontend/src/pages/	Dashboard, repository pages, Chat and four analysis studios	Reduce the oversized Explorer/workbench page; keep feature pages focused
frontend/src/components/explorer/	Code viewer, tree, analysis result/history and feature result views	Reuse where contracts match; do not force unlike result schemas into one component
frontend/src/components/studios/	Command palette, sub-navigation, target file picker	Continue consolidating common studio behavior here
frontend/src/hooks/	TanStack Query hooks, analysis mutations, shared file selection, chat	Audit server state vs local UI state and repository-switch behavior
frontend/src/services/	Axios API client and API adapters	Keep one canonical transport/error normalization layer
backend/app/api/v1/	HTTP routes for auth, repos, chat, analysis, GitHub and events	Preserve API compatibility; reduce route-level orchestration over time
backend/app/services/	Repository sync, analysis orchestration/history and Git operations	Largest consolidation opportunity; separate feature logic from shared lifecycle mechanics
backend/app/repositories/	Persistence/query layer	Keep DB access here; reduce oversized repository classes incrementally
backend/ai/	LLM providers, embeddings, RAG retrieval/context/schemas/prompts/engines	Maintain provider boundaries, retrieval isolation and grounding guarantees
backend/scanner/	File walking, AST parsing, symbol/import graphs, static bug rules and source mapping	Preserve as core IP; isolate parser fallbacks and test fixtures
backend/indexer/	Chunking, incremental indexing, embedding queue and indexing status	Add measurable performance and recovery tests before optimizing
backend/integrations/github/	GitHub API/App auth, clone/source operations, cache and routes	Security-sensitive; preserve path/installation/ownership validation
backend/migrations/versions/	Alembic schema history	Verify upgrade/downgrade against a fresh PostgreSQL+pgvector database
backend/tests/	Unit, API, integration, QA, security, fixture and acceptance tests	Consolidate test helpers only after preserving meaningful independent scenarios
Docs/	Week plans, acceptance reports, architecture and security notes	Align status claims with reproducible CI artifacts


1.2 Actual feature boundaries
The source currently registers nested routes for repository overview, chat, explain, bug detection, test generation and review. The four feature pages already share useStudioFile; do not recreate that hook or the proposed target-file picker. Existing APIs should remain the contract until each frontend page has tests proving that a change is safe.

The Week 2 APIs are registered in backend/app/api/v1/analysis.py and the router is mounted by backend/app/api/v1/router.py. The RAG chat endpoint is separate in backend/app/api/v1/chat.py. This division is reasonable: avoid merging all feature behavior into one mega-route or one generic engine.
2. Prioritized findings
P0 — Correctness, reliability, security boundaries
F-01 — RAG readiness can be marked healthy without a retriever
Status: Verified source defect.
Evidence: backend/app/main.py:112–144 initializes retriever = None; it only constructs the embedding service and hybrid retriever if settings.all_gemini_keys is non-empty. It nevertheless constructs RAGPipeline(retriever=None, ...) and sets service_readiness["rag_pipeline"] = True. backend/ai/pipeline.py returns an empty result when self.retriever is None; backend/app/api/v1/health.py checks that the pipeline object exists rather than validating its dependencies.

Impact: Health/readiness can imply repository chat is ready when vector/lexical retrieval is unavailable. The user may get an unhelpful no-context answer instead of a clear degraded/unavailable state.

Fix: Model readiness explicitly: ready, degraded, unavailable; require a configured retriever and a usable LLM gateway for full RAG readiness. Keep liveness independent of external services. Add tests for no Gemini key, no LLM key, missing DB, and normal configuration.
F-02 — Synchronous Redis calls block async middleware paths
Status: Strong concern, directly visible in source.
Evidence: backend/app/core/auth.py:31–54 calls synchronous get_redis().exists(...) in async JWTMiddleware.dispatch; backend/app/core/rate_limit.py:169–171, 183 onward creates a synchronous Redis client and calls its pipeline hit() from async middleware.

Impact: Redis latency can block the event loop and slow unrelated requests. Under connection stalls/outages, this can amplify tail latency across the API.

Fix: Use redis.asyncio in async middleware and await exists/pipeline operations, with explicit timeouts and clean lifecycle management. Alternatively offload sync I/O to a bounded thread pool; do not create unbounded per-request threads. Preserve rate-limit fallback policy and test Redis unavailable behavior.
F-03 — Sync SQLAlchemy session is passed across a thread boundary in repository chat
Status: Strong concern.
Evidence: backend/app/api/v1/chat.py:51–61 receives db: Session = Depends(get_db) and calls await asyncio.to_thread(_owned_repository, repository_id, request, db). get_db() creates a synchronous Session in backend/app/core/database.py.

Impact: SQLAlchemy Session is not intended for concurrent cross-thread use. Even though this specific call is sequential, creating/using/closing it across different execution contexts makes ownership and connection lifecycle harder to reason about.

Fix: Choose one model: (a) async SQLAlchemy session and async ownership repository; or (b) a sync ownership function that creates and closes its own session inside the worker thread. Keep the long-running RAG work asynchronous. Add an integration test that exercises chat ownership checks under concurrency.
F-04 — Production security defaults are permissive and inconsistent
Status: Verified configuration drift; deployment risk depends on environment.
Evidence: backend/app/core/config.py defaults jwt_expire_minutes to 10080 (7 days) and cookie_secure to False; .env.example sets JWT_EXPIRE_MINUTES=15 and COOKIE_SECURE=false. APP_ENV is configurable, but no production-only validation was observed in the inspected settings class. create_access_token() uses the settings value.

Impact: If production deployment omits or misconfigures variables, sessions may be longer-lived than expected and cookies may lack the Secure attribute over HTTPS.

Fix: Make production configuration fail closed: require a sufficiently strong JWT_SECRET, require secure cookies when APP_ENV=production, validate allowed origins, and explicitly set the intended token lifetime. Keep local-development defaults usable. Add settings tests for dev vs production.
F-05 — Repository-switch stale selection in shared studio hook is possible
Status: Strong concern; verify with UI test.
Evidence: frontend/src/hooks/useStudioFile.ts returns selectedFileOverride before resolving the file query parameter or searching the current files list. The override is not keyed/reset by repository ID. The hook is used by four studio pages. The repository detail page has separate normalized path matching logic, while the hook uses exact path equality.

Impact: Navigating from one repository directly to another while remaining on the same studio route may retain a stale file object or fail to select the requested deep-link file. A matching path may mask the issue; different repository metadata may not.

Fix: Key selection state by repository ID or reset the override when repository ID changes; validate that an override belongs to the current files set. Share a single path-normalization helper between Explorer and studios. Preserve other query parameters when updating file if they are part of supported deep links. Add regression tests for repository switch, refresh, case/path normalization and invalid file query.
F-06 — Test/CI claims are not reproducible from the supplied audit environment
Status: Verified environment blocker, not proof that the suite is failing.
Evidence: pytest -q --no-cov --disable-warnings --maxfail=5 aborts during backend/tests/conftest.py import because backend/app/core/database.py cannot load the configured PostgreSQL driver: ModuleNotFoundError: No module named 'psycopg'. The dependency is correctly declared in backend/requirements.txt; it is simply absent in this environment. Frontend node_modules is absent, so frontend lint/build/test commands were not run.

Impact: README and Docs test counts (including 369 passing tests and 71.31% coverage) are claims from project documentation, not independently confirmed by this audit. Do not label them false; mark them unverified until a clean environment reproduces them.

Fix: Create a reproducible CI job that installs backend/requirements.txt, provisions PostgreSQL with pgvector and Redis, runs migrations, then executes backend tests/coverage. A separate frontend job should run npm ci, npm run lint, npm test, and npm run build. Save command output and commit SHA as the release evidence.
P1 — Architecture, maintainability and UX
F-07 — Analysis history has overlapping lifecycle interfaces
Status: Verified architectural complexity; exact redundant writes not yet proven.
Evidence: The repository has AnalysisRunHistoryService plus ExplanationHistoryService, BugScanHistoryService, TestGenerationHistoryService, and ReviewHistoryService. AnalysisRunRepository contains generic run methods and feature-specific save/list/reopen/find/delete methods. explanation_orchestrator.py:574–650 searches multiple service attributes and method aliases (record_run, save_run, create_run) and also maintains a bounded in-memory history store.

Impact: More contracts to maintain, more fallback paths, harder failure diagnosis and greater risk that history endpoints disagree about status/result shape. The in-memory store is process-local and is not a durable source of truth.

Fix: Define one canonical lifecycle interface for run creation/status/ownership/pagination/deletion and keep feature-specific serialization/reconstruction in adapters. First trace the four feature-specific history endpoints and repository methods; migrate one feature at a time. Keep bounded in-memory history only as an explicitly documented fallback, never as equivalent to durable history. Add persistence failure tests and cross-feature lifecycle tests before deleting compatibility aliases.
F-08 — Oversized files mix multiple responsibilities
Status: Verified size/structure; extraction order is a recommendation.
Evidence: backend/app/repositories/analysis_run_repository.py is 2,612 lines; backend/app/api/v1/analysis.py is 1,672 lines; frontend/src/pages/RepositoryDetail.tsx is 1,558 lines; backend/scanner/ast_rules.py is 1,374 lines; backend/app/services/code_review_orchestrator.py is 1,190 lines; backend/scanner/source_mapper.py is 1,117 lines; backend/app/schemas/analysis.py is 1,009 lines; backend/ai/context/builder.py is 967 lines; backend/app/services/bug_detection_orchestrator.py is 914 lines.

Impact: Large files increase merge conflicts, review cost, accidental coupling and difficulty isolating performance regressions. Size alone is not proof of duplicate code.

Fix: Extract along stable responsibilities, not arbitrary line counts:
1. RepositoryDetail: repository overview/sync state, explorer state, analysis actions, result/history display.
2. analysis.py: request/target validation, feature endpoint handlers, history endpoints and response mapping.
3. AnalysisRunRepository: generic run lifecycle plus one module/adapter per feature persistence/reconstruction.
4. ast_rules.py: rules grouped by language/rule family while keeping a stable scanner interface.
5. Context builder: token budgeting, memory deduplication, source chunk selection and serialization as separate testable helpers.
Avoid a large all-at-once file split; preserve behavior with characterization tests.
F-09 — UI pane sizing is desktop-biased and needs explicit narrow-screen behavior
Status: Verified layout pattern; exact usability should be tested at target viewport sizes.
Evidence: RepositoryBugStudio.tsx uses a two-pane split with a left pane w-1/2 min-w-[360px] and a right pane. Similar studio pages use two-pane code/result layouts. AppLayout.tsx uses a fixed h-screen overflow-hidden shell, while nested panes rely on min-h-0 and internal overflow classes.

Impact: On viewports narrower than the combined pane minimums, the workspace may compress or overflow horizontally. Fixed-position file-picker placement (left-4 top-24) can also be disconnected from its trigger at different viewport/header sizes.

Fix: Define a responsive breakpoint: side-by-side panes above the minimum desktop width; tabbed/stacked Source and Results on smaller widths. Use a positioned popover anchored to the trigger, not fixed coordinates. Add screenshot/manual acceptance checks at 1280×800, 1024×768, 768×1024 and 390×844. Verify keyboard/focus behavior for the command palette and picker.
F-10 — RepositoryDetail.tsx still combines Explorer and analysis orchestration
Status: Verified from imports and file size.
Evidence: It imports repository metadata/files/dependencies/sync/delete/content hooks, file tree/code viewer, analysis actions/results/history, four analysis mutation hooks, shared analysis state and many icons. It remains 1,558 lines despite separate studio pages.

Impact: Two user paths may implement the same action/result/history behavior differently: the old workbench and dedicated studios. Bug fixes can land in one and not the other.

Fix: Decide and document the canonical product flow. Keep Explorer/repository overview in the index route; move analysis actions to dedicated studios or retain only a lightweight “Open in studio” entry point. Do not remove the old controls until parity tests prove the new studio route covers their behavior. Keep existing deep links working via redirects or route adapters.
F-11 — Similar UI and state concepts exist across stores and query hooks, but not all are duplicates
Status: Needs call-site verification before cleanup.
Evidence: Zustand stores contain app sidebar UI state, authentication presentation state and selected repository UI state. TanStack Query manages repository server data; dedicated hooks handle repository and available GitHub repository discovery. The comments explicitly intend server state to live in TanStack Query.

Impact: If the same server data is also written into Zustand, stale copies can emerge. The current store comments alone do not prove that this is happening.

Fix: Keep TanStack Query as the sole source of server-owned repository data. Keep Zustand for durable cross-page UI state only. Search all useRepositoryStore and useAppStore call sites before deleting any store; if selected repository state is derivable from the URL, prefer repository ID in the route and query cache over storing the whole object.
F-12 — Docs status is internally inconsistent
Status: Verified documentation drift.
Evidence: Root README calls Week 1 complete and Week 2 active; Docs/README.md labels Week 2 active; several Week 2 Day 7 acceptance reports state complete/100% for their respective suites. These may reflect different scopes, but the overall release state is not stated consistently. README's 369-test/71.31%-coverage statement is not reproducible in the current audit environment.

Impact: Developers may assume all Week 2 functionality is production-ready when some acceptance reports only cover selected suites or mocked integration scenarios.

Fix: Add a single release status table with: feature, API contract verified, unit tests, DB integration tests, live-provider tests, UI tests, known limitation, and evidence artifact. Generate test totals from CI rather than manually maintaining numbers. Label provider-dependent tests separately from deterministic tests.
P2 — Efficiency and operational quality
F-13 — Worker and resource lifecycle needs failure-path cleanup tests
Status: Strong concern.
Evidence: backend/app/services/sync_worker.py creates an embedding service and calls await embedding_service.aclose() after successful indexing. The shown exception path marks the job failed and removes the clone directory, but the embedding close call is not in a finally block around indexing.

Impact: A failure during indexing can leave HTTP client/provider resources unclosed until garbage collection/process shutdown.

Fix: Put provider/indexer cleanup in try/finally; make close operations idempotent and test exceptions during clone, scan, embedding and DB persistence. Also ensure the async Redis client created by get_redis_async() is closed; the inspected close_redis() closes only the synchronous cached client.
F-14 — Sync worker is coupled to the web process lifecycle
Status: Architectural trade-off, not necessarily a defect for local/single-process use.
Evidence: FastAPI lifespan starts sync_worker_loop(app) as a background task in each app process.

Impact: API and worker scale/deploy/restart together; multiple web workers may all consume from the same queue. Redis queue semantics can support competing consumers, but resource limits and deployment expectations need to be explicit.

Fix: For Week 2, document the intended process model and test shutdown/recovery. Do not undertake a separate worker deployment as a prerequisite unless production scaling requires it. Week 3 automation remains out of scope.
F-15 — Model/provider configuration has a default-value discrepancy
Status: Verified configuration drift.
Evidence: .env.example and README refer to gemini-flash-lite-latest; Settings.gemini_chat_model defaults to gemini-flash-latest. main.py passes this setting to analysis services and the RAG pipeline. With a copied .env, the explicit env value should win; without it, runtime behavior differs from docs.

Fix: Use one documented default in settings and .env.example; add tests for environment override and provider fallback. Avoid assuming a model name is available without a live-provider smoke test.
F-16 — Embedding model dimension is a cross-layer invariant that should be tested end-to-end
Status: Verified invariant, regression risk.
Evidence: Settings.embedding_dimensions defaults to 768; startup rejects values other than 768; CodeChunk model validates vector length against settings; migrations create Vector(768); VectorRetriever serializes and optionally validates query dimensions.

Impact: The current consistency is good, but any future model/dimension change requires a coordinated migration, re-embedding strategy, index rebuild and rollout plan. Updating only an environment variable will not work.

Fix: Keep 768 as a single explicit schema invariant for Week 1–2. Add a test that asserts the setting, ORM column, migration and embedding provider all agree. Treat dimension changes as a data migration, not a config-only change.
F-17 — Test inventory contains many overlapping day/owner/acceptance suites
Status: Verified naming pattern; not proof tests are redundant.
Evidence: backend/tests/ includes general behavior tests, test_dev_w2_*, test_keval_w2_*, test_meet_day*, test_om_w2_*, day-specific tests and final acceptance tests. There are many independent fixtures for defects, syntax, prompt injection and repository samples.

Impact: Similar scenarios may be repeated, increasing test runtime and making failures hard to triage. However, owner/day-specific tests may capture different regressions and must not be deleted based on names alone.

Fix: Tag tests by layer (unit, api, db, security, provider, e2e) and by feature; measure runtime and coverage overlap. Consolidate only duplicate setup/assertions, not unique threat cases. Keep adversarial prompt-injection fixtures, malformed syntax fixture, multi-tenant isolation tests and path-traversal tests.
F-18 — Retrieval benchmark docs need repeatable generated evidence
Status: Needs runtime verification.
Evidence: Docs/rag_benchmark_results.md describes a 10-query ground-truth benchmark and points to backend/scripts/benchmark_rag.py; backend/scripts/benchmark_quality_suite.py and quality reports also exist. This audit did not execute benchmarks because dependencies/database/provider access are unavailable.

Impact: RAG changes to chunking, fusion, reranking or context budgets can silently worsen retrieval quality even when unit tests pass.

Fix: Make the benchmark deterministic where possible, record Recall@k/MRR/NDCG or another declared metric, preserve per-query expected files, and compare baseline vs candidate. Record provider/model version, dataset revision, latency and token usage. Do not use one small benchmark as a claim of general correctness.
3. Things that look duplicated but must not be deleted blindly
Component pair/group	Why it looks redundant	Safe decision
Four feature history services + unified history service	All expose run/history operations	Consolidate lifecycle interface, keep feature payload reconstruction adapters until migrated and tested
Four analysis orchestrators	All call LLMs and handle structured outputs	Share provider/error/telemetry/validation helpers; retain different feature logic and schemas
backend/app/services/sync_worker.py and backend/app/workers/sync_worker.py	Similar names	The worker module is a compatibility re-export; remove only after import references are confirmed
frontend/src/services/api.ts and feature service modules	All participate in HTTP requests	Keep shared Axios transport/error normalization; feature services should remain thin endpoint adapters
TanStack Query and Zustand stores	Both are state management	Query cache owns server data; Zustand owns UI/session presentation state only
Scanner AST rules and AI analysis	Both detect bugs/review issues	Keep deterministic static evidence and AI reasoning as separate sources, merge through explicit provenance/deduplication
RAG vector and lexical retrieval	Both search repository code	Both are intentional hybrid retrieval channels; keep fusion and repository filters
Tests by owner/day and cross-feature suites	Similar feature names and assertions	Measure overlap before consolidation; preserve unique security, integration and acceptance coverage
Multiple prompt files	Similar instruction wording	Keep feature-specific prompts where output schemas/goals differ; centralize only shared safety/grounding fragments


Explicitly preserve: parser fixtures, malformed syntax fixtures, prompt-injection samples, test fixtures, migration history, source-reference validation, repository-isolation checks, and secret-redaction/security tests.
4. Cross-layer flow checks to make release gates
4.1 Repository sync/indexing
Expected flow:
1. Authenticated user requests sync.
2. API verifies repository ownership.
3. Sync service creates/reuses a persisted SyncJob and queues a minimal trusted payload.
4. Worker marks job/repository state, obtains installation credentials, clones to a bounded workspace, walks files, incrementally chunks and embeds, persists file/symbol/chunk metadata, and emits a repository update event.
5. Failure marks both job and repository failed, publishes an update if possible, and removes temporary clone data.
Required tests: queue unavailable; worker restart; stale job reconciliation; duplicate sync request; deleted repository during sync; missing GitHub installation; embedding failure; partial DB failure; cleanup on every exception path; repository-specific event payload; large repository performance.
4.2 RAG/chat
Expected flow:
1. Validate authenticated ownership.
2. Retrieve vector and lexical candidates with repository ID enforced in both queries.
3. Fuse/rerank results and construct a token-bounded context.
4. Keep repository content as untrusted data, separate from system instructions.
5. Call configured LLM gateway, validate output schema, validate source citations against repository/file/line records, redact secrets, return typed response.
Required tests: zero indexed chunks vs retrieval outage; no embedding key; no LLM key; vector/lexical partial failure; cross-repository isolation; prompt injection in comments; invalid/missing citations; source revision mismatch; oversized history/context; cancellation and timeout; token/latency metrics.
4.3 Explain / bug detection / test generation / review
Expected flow:
1. API validates repository ownership and safe target path/range.
2. Context builder retrieves target and related repository context.
3. Deterministic analysis and AI output remain distinguishable.
4. Output schema, source locations, paths, secret redaction and provenance are validated.
5. Persist run lifecycle and feature result/finding payload once through a clear canonical path.
6. Frontend handles loading, error, retry, stale response, history reopening and source navigation.
Required tests: each endpoint with valid and invalid path/range; unindexed repository; LLM unavailable; malformed LLM output; repair limit reached; history save fails; reopen after process restart; repository switch while request is pending; no false claim that generated tests were executed; review target/commit source revision remains stable.
4.4 Frontend navigation and state
Required checks:
- Direct URL and refresh work for all six repository destinations.
- Repository switching cannot retain a stale selected file/result/history.
- Query parameters for source path and line ranges are preserved/normalized.
- Cmd/Ctrl+K command palette traps/restores focus, supports Escape and does not intercept typing in text inputs unexpectedly.
- Every pane has independent scrolling and no page-level accidental horizontal scroll at laptop resolution.
- Loading/error/empty/success states are consistent across studios.
- A slow response from repository A cannot overwrite results after navigation to repository B.
- Clicking a citation opens the correct file and line; nonexistent references are not shown as valid.
- AI request cancellation and retry do not duplicate expensive runs without an idempotency policy.
5. Week 1–2 implementation plan
Phase 0 — Baseline and contract map (first)
1. Install exact backend requirements and frontend lockfile dependencies.
2. Provision PostgreSQL 15 with pgvector and Redis 7.
3. Apply migrations to a fresh DB; verify current head and downgrade/re-upgrade path in a disposable database.
4. Run backend tests/coverage, frontend tests/lint/build; save raw logs and commit SHA.
5. Export route/OpenAPI contract and map each frontend service call to the exact backend request/response schema.
6. Add a dependency map for proposed removals: imports, route registrations, tests, migration/model references and public API consumers.
Gate: no source deletion until baseline commands and known failures are documented.
Week 1 — Correctness first, then shared workspace cleanup
Day 1 — Runtime baseline and readiness
- Fix RAG readiness state and test missing-provider modes.
- Fix async Redis blocking in auth/rate limiting or document a bounded offload approach.
- Decide the chat DB session threading model and add concurrency regression tests.
Day 2 — Shared studio selection and navigation
- Reset/key file selection on repository changes.
- Centralize path normalization and citation-to-file selection.
- Add route/deep-link/refresh/repository-switch tests.
Day 3 — Explorer/workbench decomposition
- Extract sync/repository overview, file explorer state, analysis actions and result/history panels from RepositoryDetail.tsx.
- Preserve all supported actions and URLs; remove only verified duplicated UI after parity tests.
Day 4 — Layout/interaction pass
- Define breakpoints and responsive pane behavior.
- Replace fixed-coordinate picker positioning with anchored positioning.
- Check keyboard focus, accessible labels, empty/loading/error states and independent scrolling.
Day 5 — API/client and state consistency
- Ensure Axios is the single transport/error-normalization layer.
- Verify TanStack Query owns server data; remove duplicate store copies only if call-site analysis proves they exist.
- Add stale-response/cancellation tests.
Day 6 — Cross-feature behavior
- Check result panel, source reference, severity, status and history components against each actual feature schema.
- Avoid a universal result schema that erases meaningful differences.
Day 7 — Week 1 acceptance
- All workspace destinations load and refresh.
- No known stale file/result after repository switching.
- Lint/build/UI tests pass; screenshot/manual checks at declared viewports.
Week 2 — Canonical analysis lifecycle and reliability
Day 8 — History call graph
- Map each endpoint → orchestrator → history service → repository method → table.
- Record whether each feature creates one or multiple rows, how failures are stored, and how reopening reconstructs the response.
Day 9 — Canonical lifecycle interface
- Define create/start/complete/fail/cancel/get/list/delete/summary semantics.
- Standardize status transitions, timestamps, ownership and pagination.
- Keep feature-specific payload adapters.
Day 10 — Incremental migration
- Migrate one feature at a time behind existing service contracts.
- Add tests proving one canonical run identity, correct feature payload and no lost findings.
- Do not remove legacy methods until all call sites are migrated.
Day 11 — Persistence and secret safety
- Test DB transaction failure and history retry semantics.
- Verify raw source, generated output, error text and history payloads pass through secret redaction.
- Check result size/retention and avoid logging source code or tokens.
Day 12 — Retrieval/indexing resilience
- Add failure-path cleanup for embedding provider and async Redis clients.
- Test interrupted indexing, stale sync job reconciliation, incremental re-index idempotency and vector dimension invariants.
Day 13 — Performance/benchmark baseline
- Measure scan time, chunks per file, embedding batches, DB query count, retrieval latency, reranking latency, context tokens and LLM latency.
- Run the repository RAG benchmark and quality suite in the configured environment.
- Optimize only measured bottlenecks; preserve quality metrics.
Day 14 — Week 2 acceptance and cleanup
- Run complete backend DB integration/security tests and frontend test/lint/build.
- Verify feature history after server restart.
- Publish a single acceptance matrix with evidence links, limitations and unresolved defects.
- Delete only dead code proven unreferenced by imports, routes, tests, migrations and runtime call paths.
6. Removal rules: safe vs unsafe
Safe to remove after verification
- Unused imports, unused variables and dead branches identified by lint/type checks.
- Duplicated UI state logic already replaced by useStudioFile, if the old copy is still present and parity tests cover it.
- Obsolete compatibility wrappers after all references are removed and tests confirm the new public interface.
- Stale docs that conflict with current behavior, after replacing them with accurate contract/status documentation.
- Unused demo assets such as default Vite/React assets only if they are not referenced by the app or docs.
Do not remove in this audit phase
- Any migration file already applied in shared environments.
- AST parser fallbacks or malformed syntax fixtures.
- Security tests, secret-redaction patterns, path traversal checks, repository isolation tests or prompt-injection fixtures.
- Separate feature prompts, schemas, or context builders solely because they share terminology.
- Feature-specific history reconstruction until a canonical adapter passes equivalence tests.
- The Week 3 tool router merely because it returns “execution disabled”; this is an intentional fail-closed boundary until policy/argument validation is implemented.
- Any branch/commit/PR-related source solely because autonomous PR execution is out of Week 1–2 scope; do not expose new autonomous execution features, but avoid breaking existing read-only/source APIs.
7. Acceptance matrix
Area	Must pass before Week 2 is considered complete
Environment	Clean dependency installation; config validation; no secrets committed
DB/migrations	Fresh PostgreSQL+pgvector upgrade succeeds; schema matches ORM; data isolation holds
Auth	JWT expiry/revocation, ownership checks, secure production defaults, Redis outage behavior tested
Repository sync	Idempotent job handling, retry/reconciliation, cleanup, event update and incremental indexing verified
RAG	Retrieval required dependencies reflected in readiness; vector/lexical isolation; citation grounding and redaction verified
AI analysis	Four features have typed contracts, bounded repair, accurate status, grounded sources and failure handling
History	Canonical run lifecycle, feature payload reopening, durable persistence, repository ownership and restart behavior verified
Frontend	Route refresh, repository switching, file/citation navigation, stale-response protection, responsive layout verified
Performance	Baseline timings and RAG quality benchmark recorded before and after optimization
Tests	Backend and frontend test/lint/build commands pass in CI with raw logs and pinned commit
Documentation	README, Docs index and acceptance reports show one consistent release status and known limitations


8. Commands to reproduce the audit in a configured local environment
Run from repository root. Use a fresh virtual environment and never paste real credentials into logs.
# Backend environment
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r backend/requirements.txt

# Infrastructure
cp .env.example .env
# Fill local-only secrets and required provider/GitHub settings as needed
docker compose up -d

# Database migration
cd backend
../.venv/bin/alembic upgrade head
cd ..

# Backend test suite (requires PostgreSQL/pgvector and Redis configuration)
.venv/bin/pytest --cov=app --cov-report=term-missing --cov-fail-under=70

# Frontend checks
cd frontend
npm ci
npm run lint
npm test
npm run build
For a meaningful live-provider smoke test, run separately from deterministic tests and record the provider/model, date, latency, request count and token usage. Never make live provider availability a prerequisite for every unit test.
9. Final decisions
1. Do not rewrite the platform. Preserve existing API contracts and working code.
2. Fix verified correctness/reliability concerns first: RAG readiness, synchronous Redis in async middleware, chat DB session ownership, production configuration validation, and stale studio file selection.
3. Refactor by call graph: canonical history lifecycle and large files are Week 2 work, but only after contract/behavior tests exist.
4. UI cleanup is consolidation, not a visual-only redesign: establish one workspace shell, shared selection/source references/history states, responsive panes, and correct navigation.
5. Treat README test counts as unverified until CI reproduces them. This audit's test run was blocked before collection by the missing psycopg dependency; frontend commands were not run because dependencies were not installed.
6. No source files were modified or deleted. This report is a cross-checked audit and execution plan, not a claim that remediation has already been implemented.