# Deep backend audit and Week 1 implementation plan for Antigravity

I inspected `Docs/week1.md` inside your uploaded ZIP and compared its Week 1 requirements against the actual backend modules, API routes, models, migrations, scanner, indexer, GitHub integration, AI pipeline, and tests.

The key point is that your backend is not just a FastAPI application. Week 1 requires a complete repository-intelligence system, from GitHub authentication to indexed code and grounded answers. Antigravity must audit that entire execution path, not simply clean up `backend/app/`.

## 1. Initial backend audit: confirmed blockers

Critical — the sync queue has no worker

`backend/app/services/repository_sync.py` enqueues jobs in Redis, but `backend/app/workers/` contains only `__init__.py`. The API can accept a sync request and return a job ID, but there is no implemented worker to complete clone → scan → chunk → embed → persist.

Critical — the ORM and migrations disagree

`CodeChunk` and `MemoryEntry` are registered ORM models, but the supplied Alembic migrations do not create `code_chunks` or `memory_entries`. The vector column is also hard-coded to 1,536 dimensions, conflicting with the configurable embedding design required by Week 1.

Critical — the search endpoint calls an unavailable pipeline method

`backend/app/api/v1/repositories.py` expects `pipeline.retrieve(...)`, while the inspected `RAGPipeline` exposes `chat(...)` and an internal `_retrieve(...)`. The startup configuration also explicitly injects `retriever=None`.

Critical — indexing uses placeholder vectors

`backend/indexer/incremental.py` inserts zero vectors and one chunk per file, bypassing the symbol-aware chunker and real embedding pipeline. New file inserts omit required `repository_files` fields, and deleted files are not reconciled in the inspected indexing loop.

Critical — the GitHub installation flow is incomplete

The GitHub API routes expect stored installation records, but the registered route set does not expose the installation callback/webhook needed to complete the documented registration flow. OAuth login and GitHub App installation are separate operations.

Critical — security and deployment configuration need repair

The archive includes a GitHub App private-key file, which must be treated as compromised if it is real. The setup documentation also refers to a missing `.env.example`, and the default database port does not match the Docker Compose host-port mapping previously identified in the archive.

### One additional testing limitation

I attempted to run the backend test suite, but collection stopped immediately because the `responses` package is missing from the audit environment. That is a blocked test run, not evidence that all tests pass or that all tests fail. Antigravity must install the correct test dependencies and report the actual results.

## 2. How the audit must align with `Docs/week1.md`

The implementation should be evaluated against the project's existing requirements, not a newly invented backend architecture.

| Week 1 area   | Required outcome                                               | Current concern                                                        |
| ------------- | -------------------------------------------------------------- | ---------------------------------------------------------------------- |
| W1-01 / W1-02 | Project configuration, PostgreSQL, pgvector, Redis, migrations | Schema and runtime configuration inconsistencies                       |
| W1-03 / W1-04 | GitHub integration and authenticated API                       | Installation registration and end-to-end auth need verification        |
| W1-06         | Async repository synchronization                               | Queue producer exists; worker implementation is missing                |
| W1-07–W1-09   | File walker, AST parsing, symbols, dependency graph            | Scanner stubs, dependency declarations, and integration require review |
| W1-10–W1-12   | Symbol-aware chunks, queue, embeddings                         | Incremental indexer bypasses the intended pipeline                     |
| W1-13         | Vector search, lexical search, RRF, reranking                  | Pipeline wiring and database persistence are incomplete                |
| W1-14–W1-15   | Memory and RAG context                                         | Memory schema and retrieval integration are incomplete                 |
| W1-16         | Chat API                                                       | Search and chat interfaces are inconsistent                            |
| W1-18 / W1-19 | Tests, security, isolation, observability                      | Tests are not yet verified end to end; security gate must be run       |

The target is the Week 1 Definition of Done: a user connects a repository, the platform safely analyzes and indexes it, and repository-aware chat returns answers with verifiable source references.

Provider constraint: retain only Gemini and Groq as hosted AI services. Replace the Week 1 document's old OpenAI-specific examples and requirements where necessary, without changing the intended architecture or expanding the scope.

## 3. Complete Antigravity prompt — deep backend audit and repair

This prompt covers the complete backend, not just the AI folder. Give Antigravity access to the extracted project, including `Docs/week1.md`, so it can inspect and modify the actual source files.

# Deep Backend Audit, Repair and Week 1 Completion

## Project

Repository: the existing project in the provided workspace/ZIP.

Primary specification: `Docs/week1.md`

Main backend directory: `backend/`

Related components: `backend/app/`, `backend/ai/`, `backend/scanner/`, `backend/indexer/`, `backend/migrations/`, `backend/tests/`, root configuration files, Docker Compose, and frontend API contracts.

## 1. Main objective

Perform a very deep, evidence-based audit of the entire backend. Align every implementation decision with `Docs/week1.md`, identify defects, missing functionality, unnecessary code, security weaknesses, broken integrations, inconsistent schemas, and missing tests.

Then implement the necessary fixes in the existing codebase.

**Do not stop after producing an audit report or implementation plan.** Inspect the code, make changes, run tests, fix failures, and verify the end-to-end Week 1 workflow.

The final system must support:

GitHub authentication → repository selection → secure synchronization → file scanning → AST/symbol extraction → dependency graph → symbol-aware chunking → Gemini embeddings → PostgreSQL/pgvector persistence → lexical and vector search → RRF fusion → reranking → context and memory assembly → Gemini/Groq generation → output validation → verified citations → API response.

### Hard constraints

1. Use `Docs/week1.md` as the authoritative Week 1 specification.
2. Use only Gemini and Groq for hosted AI generation/embedding services. Do not require OpenAI or another hosted AI provider.
3. Preserve useful existing implementations. Do not rewrite the entire project unnecessarily.
4. Do not begin autonomous agent execution, code execution, automatic pull requests, or Week 2 features. Finish the Week 1 foundation first.
5. Do not invent completed features, test results, API capabilities, credentials, or provider availability.
6. Never silently convert a failed operation into success.
7. Keep API contracts compatible with the existing frontend where possible. Document and test any required changes.
8. Never expose real secrets in code, logs, test fixtures, reports, or generated documentation.

## 2. Phase A — Complete repository inventory and requirements traceability

Inspect every relevant source file, not just the main application file.

Audit at least:

- `Docs/week1.md` and other relevant project documentation.
- `backend/app/main.py`.
- `backend/app/api/v1/`.
- `backend/app/core/`.
- `backend/app/models/`.
- `backend/app/schemas/`.
- `backend/app/repositories/`.
- `backend/app/services/`.
- `backend/app/integrations/github/`.
- `backend/app/workers/`.
- `backend/ai/`.
- `backend/scanner/`.
- `backend/indexer/`.
- `backend/migrations/`.
- `backend/tests/` and test mocks.
- `backend/requirements.txt`, root requirements, `pytest.ini`, Alembic configuration, Docker Compose, `.gitignore`, and `.env.example` if present.
- Relevant frontend API services and types for contract compatibility.

For every module:

1. Explain its intended responsibility.
2. Inspect every class, method, database query, import, external call, and important branch.
3. Trace which components call it.
4. Check whether it is actually used by the running application.
5. Identify duplicate implementations, stubs, dead code, placeholder data, unsafe defaults, inconsistent contracts, and incomplete error handling.
6. Identify dependencies that are missing, unnecessary, duplicated, or incompatible.
7. Check asynchronous behavior, transaction boundaries, resource cleanup, and failure recovery.
8. Compare implementation with the corresponding Week 1 task and acceptance criteria.

Produce a traceability matrix containing:

- Week 1 task ID and requirement.
- Required behavior.
- Relevant source files.
- Current implementation status: COMPLETE, PARTIAL, BROKEN, MISSING, or DEFERRED.
- Evidence for the status.
- Dependencies and blockers.
- Required change.
- Tests that prove completion.

Do not mark a task COMPLETE simply because a class or route exists.

## 3. Phase B — Repair configuration, startup, and infrastructure

Inspect the application lifecycle and make startup behavior reliable.

### Configuration

- Consolidate configuration into the existing settings class.
- Add and validate required environment variables.
- Create `.env.example` containing placeholders only.
- Ensure `.env`, private keys, caches, virtual environments, and generated artifacts are ignored by Git.
- Align PostgreSQL host ports and `DATABASE_URL`.
- Validate Redis configuration and connectivity.
- Configure database connection pooling appropriately for the actual workload.
- Add validation for production secrets and unsafe configuration.
- Remove duplicate configuration systems and unused variables only after checking references.

### Startup and shutdown

Inspect `backend/app/main.py`.

- Initialize database, Redis, GitHub, embedding, retrieval, and AI dependencies through a clear lifecycle.
- Inject fully configured services into application state or the existing dependency-injection mechanism.
- Do not initialize `RAGPipeline` with `retriever=None` in a supposedly functional configuration.
- Avoid swallowing initialization exceptions and silently running a broken application.
- Provide a documented degraded mode only when the remaining features can genuinely operate.
- Close HTTP clients, Redis connections, and model resources cleanly during shutdown.
- Ensure startup and shutdown are safe and deterministic.
- Avoid logging secrets or sensitive provider error payloads.

### Health checks

Separate basic liveness from readiness.

- Liveness indicates that the process is running.
- Readiness verifies the dependencies necessary for the advertised functionality.
- Report database, Redis, GitHub, embedding, and LLM configuration status without exposing credentials.
- Distinguish an unconfigured optional provider from a required dependency failure.
- Use accurate HTTP status codes.

## 4. Phase C — Database and migration audit

Compare every SQLAlchemy ORM model with the complete Alembic migration history.

Inspect:

- `User`
- `GitHubInstallation`
- `Repository`
- `RepositoryFile`
- `CodeSymbol`
- `SymbolEdge`
- `CodeChunk`
- `SyncJob`
- `MemoryEntry`

For each model, compare columns, data types, nullability, defaults, indexes, uniqueness, foreign keys, and enum values against the migrations.

### Known problems to investigate and fix

- `code_chunks` and `memory_entries` are declared in the ORM but are absent from the supplied creation migrations.
- `CodeChunk.embedding` is fixed at 1,536 dimensions, despite the requirement for configurable dimensions.
- The content schema and lexical-search index must support the actual queries used by the retriever.
- The database migration history must match the ORM definitions, including metadata and timestamps.
- Any raw SQL insertion must supply every required column.
- Foreign keys and repository/file relationships must remain consistent when files are updated or deleted.
- Repository ownership and installation relationships must be enforced.
- Existing enum migrations must work on a fresh database.

### Required actions

1. Add or revise migrations without silently discarding user data.
2. Preserve migration history and create forward migrations for schema corrections.
3. Verify a completely fresh database can migrate successfully.
4. Verify downgrade behavior where appropriate.
5. Verify the ORM can create, query, update, and delete the intended records.
6. Test all required indexes and vector dimensions.
7. Add appropriate unique constraints and transaction boundaries.
8. Ensure repository-scoped queries include authorization scope.

Never use `Base.metadata.create_all()` as a substitute for a correct production migration history.

## 5. Phase D — Authentication and API security

Inspect the entire authentication flow, including `auth.py`, `JWTMiddleware`, token utilities, Redis blocklisting, and GitHub OAuth.

### Authentication requirements

- Validate OAuth state correctly and prevent CSRF.
- Validate GitHub responses and handle timeouts and provider errors.
- Store or update user identity consistently.
- Enforce JWT signature, expiry, required claims, and the configured algorithm.
- Use a strong secret or appropriate signing mechanism.
- Keep browser session cookies HTTP-only and configure Secure/SameSite correctly for the deployment environment.
- Ensure logout invalidates the session according to the project's security requirements.
- Handle Redis failures without falsely claiming that logout succeeded.
- Review whether returning access tokens in the JSON response is necessary for the current frontend contract; avoid unnecessary token exposure.
- Ensure public routes are explicitly defined and protected routes cannot bypass authentication.
- Verify CORS, request IDs, rate limits, and security headers.

Do not weaken authentication to make development tests pass.

### Repository isolation

Audit every repository-scoped endpoint and database query.

Required endpoints include:

- Repository list and detail.
- Repository sync and sync status.
- File and symbol listing.
- Search and chat.
- GitHub repository listing and connection.
- Any file-content, symbol, memory, or chunk endpoint that exists.

Every request must verify that the authenticated user has access to the selected repository before reading or modifying its data.

Test the following matrix:

- User A accessing User A's repository: allowed.
- User A accessing User B's repository: denied.
- Nonexistent repository: consistent not-found behavior.
- Invalid or missing session: rejected.
- Repository ID manipulated in query parameters or request bodies: still denied.

Use one consistent ownership policy. Prefer not revealing another user's repository existence unless the existing API contract explicitly requires a different response.

## 6. Phase E — GitHub App integration

Inspect every file under `backend/app/integrations/github/`, the GitHub routes, installation model/repository, OAuth flow, Redis token cache, and repository sync service.

### Separate OAuth from GitHub App installation

GitHub OAuth login identifies the user. GitHub App installation grants the application repository permissions. These are separate operations.

Implement and connect the actual installation callback or webhook flow needed to associate an installation with the authenticated user. Verify installation ownership before allowing repository access.

Check whether the application needs webhook handling in Week 1. If implemented, verify webhook signatures, event parsing, idempotency, and installation-removal behavior.

### Token manager

- Generate GitHub App JWTs correctly.
- Mint installation access tokens through the correct GitHub endpoint.
- Cache tokens safely in Redis.
- Use an appropriate TTL below the real expiration time.
- Handle expired tokens, cache failures, and permission errors.
- Never log tokens or private keys.
- Avoid storing credentials in the database.
- Handle concurrent token refresh without creating unnecessary token requests.

### Repository API wrapper

Verify actual implementations for:

- Listing repositories for a specific installation.
- Fetching repository metadata.
- Reading the default branch.
- Listing branches where needed.
- Handling pagination.
- Handling 401, 403, 404, 429, 5xx, and network errors.
- Respecting rate-limit headers and `Retry-After`.

Do not return connected repositories as though they represent a successful live GitHub query when GitHub integration is unavailable.

### Secure cloning

Implement and verify a secure shallow clone mechanism.

- Use the correct installation token and repository.
- Support the default branch and an explicitly validated branch override.
- Keep workspace paths inside a configured root.
- Reject path traversal and symlink escapes.
- Apply a timeout and resource limits.
- Clean up partial clones after failure.
- Avoid exposing tokens in command-line arguments, process listings, or logs.
- Use safe subprocess invocation without shell interpolation.
- Verify repository metadata before marking a clone successful.

Never treat a client-supplied owner/name as sufficient authorization.

## 7. Phase F — Repository scanner and dependency graph

Inspect all of `backend/scanner/`, including:

- `walker.py`
- `detector.py`
- `parser.py`
- `symbols.py`
- `graph.py`
- `test_mapper.py`

Also inspect `backend/requirements.txt`.

### FileWalker

The Week 1 requirements specify skipping `.git`, `node_modules`, binary files, and files larger than 1 MB.

Implement and test:

- Recursive traversal.
- Configurable excluded directories and patterns.
- File-size limits.
- Binary detection.
- Safe handling of unreadable files.
- Symlink handling.
- Safe relative paths.
- Stable results and deterministic sorting.
- Appropriate error reporting without crashing the entire scan.

Inspect `walker.py` and `detector.py` for unfinished `pass` branches.

### Language detection

Verify detection for Python, JavaScript, TypeScript, Java, and Go, as required by Week 1.

- Use a deterministic fallback for unknown file types.
- Do not treat an unknown extension as a confirmed supported language.
- Ensure language detection and parser selection agree.

### Tree-sitter parsing

- Verify required parser packages are declared in backend dependencies.
- Check the installed tree-sitter API versions and grammar compatibility.
- Ensure unsupported languages and syntax errors do not crash the entire repository scan.
- Handle missing parsers explicitly.
- Do not silently return a successful parse when no parser exists.

### Symbol extraction

For supported languages, extract:

- Functions and methods.
- Classes and relevant declarations.
- Stable symbol names and kinds.
- Correct original line ranges.
- Signatures where available.
- Parent/child relationships where supported.

Check line numbering carefully, including zero-based parser positions versus one-based source lines.

### Dependency graph

Inspect import parsing, inheritance, and call relationships.

- Avoid fabricated edges when a target symbol cannot be resolved.
- Handle relative imports and language-specific syntax.
- Deduplicate edges.
- Validate source and target symbol IDs.
- Persist edges through the repository layer.
- Provide a queryable graph, not only an in-memory list.

Do not claim complete call-graph resolution where static analysis cannot resolve dynamic behavior.

## 8. Phase G — Chunking, embedding queue, and incremental indexing

Inspect all of `backend/indexer/`, the code chunk model, embedding service, repositories, and database schema.

### Symbol-aware chunking

Use the stable scanner symbol schema as required by the Week 1 dependency rules.

- Generate chunks at meaningful function/class/module boundaries.
- Preserve file path, language, symbol ID, start/end lines, and content hash.
- Split large symbols at logical boundaries or safe line windows.
- Enforce input/token limits.
- Avoid duplicating entire files in addition to every symbol without a clear retrieval reason.
- Handle files without extractable symbols through a documented fallback.

### Embedding queue

Inspect `embedding_queue.py`.

The current implementation removes items from Redis before embedding succeeds and returns vectors without persisting their results to their corresponding chunks.

Fix this reliability problem.

- Use a durable processing pattern with acknowledgements or equivalent recovery.
- Preserve the chunk ID and repository/file metadata throughout the job.
- Retry transient failures with bounded backoff.
- Ensure permanently failing items are recorded and do not disappear silently.
- Persist generated vectors to the correct chunk rows.
- Prevent duplicate processing from producing duplicate chunks.
- Respect Gemini's actual batch and input limits.
- Do not rely on arbitrary fixed batch assumptions without validating them.

### Incremental indexing

Inspect `backend/indexer/incremental.py`.

Replace the current placeholder workflow, which inserts whole-file chunks with zero vectors.

Implement:

1. Read files from the trusted cloned workspace.
2. Calculate content hashes.
3. Skip unchanged files.
4. Parse changed files and regenerate symbols/chunks.
5. Generate real Gemini embeddings.
6. Replace obsolete chunk data transactionally.
7. Remove records for deleted files.
8. Update file metadata and index status.
9. Recover from failed jobs without corrupting previously valid data.

Fix incomplete `repository_files` inserts, including required size and line-count metadata.

Review the current use of `AsyncSession` against the application's synchronous SQLAlchemy session setup. Use one coherent database access strategy in each execution path; do not mix sync and async session semantics incorrectly.

For Week 1, a reliable full reindex is acceptable if incremental indexing cannot be completed safely. However, the implementation must not pretend to support incremental indexing when it does not.

## 9. Phase H — Complete the Gemini/Groq AI and RAG integration

Use the separate AI-folder audit as a prerequisite, but verify its integration with the backend rather than assuming it is correct.

### Provider constraint

- Gemini: primary text generation and embedding service.
- Groq: secondary text generation provider.
- No OpenAI API key requirement or other hosted AI provider.
- Verify current supported model IDs and actual account access.
- Respect free-tier quotas; do not evade rate limits by rotating accounts.

### Required backend integration

Inspect:

- `backend/ai/pipeline.py`
- `backend/ai/llm/`
- `backend/ai/embeddings/`
- `backend/ai/retrieval/`
- `backend/ai/context/`
- `backend/ai/schemas/`
- `backend/ai/prompts/`
- `backend/app/api/v1/repositories.py`
- `backend/app/api/v1/chat.py`
- `backend/app/main.py`

Fix these known contract problems:

1. Startup configures only Groq even though Gemini settings exist.
2. Startup injects `retriever=None`.
3. The search route calls `pipeline.retrieve(...)`, but the RAG pipeline does not expose that public method.
4. The pipeline and validator have hard-coded OpenAI model assumptions.
5. Grounding can report a source as verified when no database session is available.
6. The embedding and indexing paths are not connected to real stored vectors.

Wire the real embedding service, database-backed vector retriever, lexical retriever, RRF fusion, optional reranker, context builder, LLM gateway, output validation, and grounding validator.

### Retrieval behavior

Follow the Week 1 design:

- Vector search retrieves up to 30 candidates.
- PostgreSQL full-text search retrieves up to 30 candidates.
- RRF uses the documented constant `k=60`.
- Fuse unique candidates.
- Optionally rerank the top 30 with the existing local cross-encoder.
- Select up to 8 relevant chunks for the final context.

Validate the local reranker dependency and runtime before requiring it. The basic pipeline must still behave honestly if reranking is unavailable.

Ensure query-time embeddings use the same compatible model and dimensions as indexed document embeddings.

## 10. Phase I — Context, memory, and grounded chat

### Context builder

Use the existing context builder and verify that it assembles:

- Retrieved code chunks.
- Relevant project memory.
- Related file metadata.
- A bounded amount of recent chat history.

Rules:

- Repository content must be kept separate from system instructions.
- Context must respect the selected model's actual token budget.
- Memory must be repository-scoped, deduplicated, and ordered according to its documented policy.
- User-supplied history must be validated and size-limited.
- Untrusted repository text must not override system instructions.

### Memory persistence

Compare `MemoryEntry`, `memory_repository.py`, migrations, and context-builder integration.

- Add missing migrations.
- Scope memory by repository and authorization.
- Define the intended lifecycle and statuses.
- Do not invent memory entries from arbitrary untrusted text without validation.
- Ensure unavailable memory does not silently become fabricated context.
- If memory is intentionally deferred, mark it deferred and remove misleading active-path claims.

### Grounding

Implement actual source verification.

- Verify that each citation belongs to the selected repository.
- Verify file identity and indexed version.
- Validate line ranges against the actual file metadata.
- Confirm that cited evidence was retrieved and supplied to the model.
- Remove invalid citations or report insufficient evidence.
- Never claim verification when the database is unavailable.

### API response

Preserve the existing `RepositoryAnswer` contract where possible.

The answer must contain the actual answer text and verified file/line sources. Keep provider metadata and usage telemetry internal unless the existing public contract explicitly exposes them.

## 11. Phase J — Repository APIs and consistent errors

Inspect every route under `backend/app/api/v1/` and all corresponding request/response schemas.

Required Week 1 routes include:

- Health and readiness.
- GitHub login, callback, current user, and logout.
- GitHub repository discovery and connection.
- Connected repository list and detail.
- Repository synchronization.
- File and symbol listing.
- Repository search.
- Repository chat.

Ensure route handlers are thin and delegate business logic to services/repositories.

Fix the duplicated ownership logic in `repositories.py` and `chat.py`. Use consistent repository-scoped authorization and error behavior.

### API contracts

- Validate all input through Pydantic schemas.
- Bound pagination, question length, history size, and top-k.
- Use appropriate HTTP status codes, including 202 for queued jobs.
- Ensure every response matches its declared schema.
- Keep error envelopes consistent across exceptions and middleware.
- Use shared error codes rather than ad hoc strings.
- Ensure sync status and job state accurately reflect actual work.
- Make OpenAPI documentation reflect the implemented contracts.

Verify the frontend's current request/response assumptions before changing API fields.

## 12. Phase K — Async jobs, status, and transaction safety

Implement the missing synchronization worker under `backend/app/workers/` and connect it to the Redis queue.

The worker should execute:

Queued job → validate repository/installation → clone → scan → parse → extract symbols and dependency edges → chunk → embed → persist → update status.

Required job behavior:

- `QUEUED` → `RUNNING` → `COMPLETED` or `FAILED`.
- Persist meaningful, sanitized error information.
- Handle duplicate jobs and retries safely.
- Prevent two workers from corrupting the same repository index.
- Handle cancellation or process restart where practical.
- Clean up temporary workspaces.
- Update repository status and last-synced time accurately.
- Ensure the job is not marked complete before all required indexing steps finish.

Use Redis with the existing architecture; do not introduce Celery or another queue framework unless there is a demonstrated requirement.

Review transaction boundaries around job creation and enqueueing. Avoid a persisted job that appears runnable when enqueueing failed. Document any remaining delivery guarantees.

Provide an actual status endpoint or make the existing repository detail endpoint return accurate status information consistent with the frontend.

## 13. Phase L — Security gate

Inspect `backend/app/core/input_security.py`, authentication middleware, rate limiting, security headers, GitHub cloning, file access, indexing, prompts, and persistence.

### Secrets

The archive contains a GitHub App private-key file. If it is real, treat it as compromised and rotate/revoke it.

- Remove real credentials from distributed source files.
- Ensure `.env` and private keys are ignored.
- Create `.env.example` with placeholders.
- Check repository history where available.
- Redact tokens and credentials from logs and exceptions.
- Never expose Gemini/Groq keys to the frontend.

### Repository content secret scanning

Implement or verify secret scanning before content enters embeddings, database storage, LLM context, or memory.

- Detect configured secret patterns.
- Redact values before indexing.
- Log only the safe detection metadata.
- Avoid false claims that heuristic scanning detects every secret.
- Test that secret values do not reach embedding calls or prompts.

### Path safety

Verify paths from cloned repositories, file access, indexing, and generated citations.

- Reject absolute paths and traversal.
- Resolve symlinks safely.
- Keep all access within the trusted repository workspace.
- Do not use unvalidated repository-relative paths as absolute filesystem paths.
- Handle malicious filenames safely.

### Prompt injection

Treat README files, comments, and repository content as untrusted data. Do not execute repository code. Test that malicious source content cannot override system instructions or expose secrets.

### Rate limiting and headers

Verify the configured per-IP/per-user rate limits and ensure limits are applied to the intended routes.

Check:

- CORS restricted to configured origins.
- `X-Content-Type-Options`.
- `X-Frame-Options`.
- Appropriate HSTS behavior only over HTTPS.
- Request ID correlation.
- Safe error messages.
- Authentication and authorization on every protected route.

Produce a Week 1 security gate report with actual evidence.

## 14. Phase M — Tests and CI

First inspect the existing tests and their intended contracts. Do not delete tests merely because they currently fail.

Resolve missing test dependencies, including the `responses` dependency identified during the initial test collection attempt. Declare the required testing packages in the correct dependency file.

Run tests in stages.

### Unit tests

- Configuration and model validation.
- Authentication and JWT utilities.
- Repository ownership checks.
- GitHub response normalization and error handling.
- Token caching and refresh.
- File walking and language detection.
- Tree-sitter parsing and symbol extraction.
- Dependency graph construction.
- Chunking and content hashes.
- Embedding service and vector dimensions.
- Lexical/vector retrieval and RRF.
- Context budgets and grounding.
- Queue state transitions and retry behavior.

### Integration tests

- Fresh database migrations.
- ORM persistence for every required model.
- GitHub API calls using mocks.
- Authenticated repository connection.
- Queue creation and worker consumption.
- Scanner-to-indexer integration.
- Real database-backed lexical and vector search.
- Repository-scoped chat with mocked Gemini/Groq.
- Output schema validation and citation grounding.
- Repository isolation for every scoped endpoint.

### End-to-end test

Use a small deterministic test repository.

1. Authenticate a user or use a controlled test identity.
2. Connect or register the test repository through the supported integration path.
3. Trigger synchronization.
4. Verify that the worker completes the job.
5. Confirm files, symbols, dependency edges, chunks, and embeddings are stored.
6. Run lexical search and vector search.
7. Run hybrid retrieval and reranking.
8. Ask: `Where is authentication implemented?`
9. Verify that the returned source paths and line ranges exist and support the answer.
10. Confirm that a different user cannot retrieve the same private repository's data.

Use mocked AI providers for ordinary tests. Run a live API test only when valid credentials and network access are available.

Run the frontend build and contract checks if backend API changes affect frontend integration.

Report results as PASSED, FAILED, BLOCKED, or NOT RUN. Never claim an unexecuted test passed.

## 15. Phase N — Code cleanup and unnecessary code

Perform cleanup only after tracing references and integration dependencies.

For every file, classify it as:

- KEEP.
- FIX.
- REPLACE.
- REMOVE.
- DEFER TO WEEK 2/3.

Check for:

- Duplicate services or business logic.
- Unused imports and dependencies.
- Stub methods and unfinished branches.
- Placeholder responses and zero vectors.
- Dead endpoints.
- Redundant models or schemas.
- Duplicate authorization logic.
- Outdated model/provider assumptions.
- Generated files, caches, native dependencies, and artifacts included in source archives.

Remove obsolete OpenAI-only dependencies after migrating all active callers. Retain Groq-compatible message contracts where useful.

Do not delete legitimate future scaffolding just because it is not needed for Week 1. Clearly document deferred components.

Do not make broad style-only refactors that obscure functional changes.

## 16. Phase O — Required deliverables

Produce all of the following:

### A. Backend audit report

A file-by-file report with:

- File path and responsibility.
- Current behavior.
- Confirmed defect and evidence.
- Severity: CRITICAL, HIGH, MEDIUM, LOW.
- Week 1 task ID.
- Dependencies and root cause.
- Exact fix made or recommended.
- Test proving the behavior.

### B. Week 1 traceability matrix

Mark every relevant checkbox in `Docs/week1.md` as COMPLETE, PARTIAL, BROKEN, MISSING, or DEFERRED, with evidence.

Update documentation only when implementation changes justify the update. Do not mark requirements complete simply because the plan has been written.

### C. Code changes

Modify the actual project files, migrations, tests, and configuration necessary to complete Week 1.

### D. Change log

List added, modified, removed, and deferred files with reasons.

### E. Setup instructions

Provide accurate commands for:

- Environment setup.
- PostgreSQL and Redis startup.
- Fresh migrations.
- API startup.
- Worker startup.
- Frontend startup.
- Test execution.
- End-to-end verification.

### F. Test report

Include actual commands, pass/fail counts, failures, blockers, and remaining manual verification.

### G. Remaining risks

List any Week 1 requirement that cannot be completed safely or verified in the available environment. Explain its impact and the next required action.

## 17. Execution order

Work in this dependency order:

1. Inventory, requirements matrix, and baseline tests.
2. Secrets, configuration, and dependency fixes.
3. Database models and migrations.
4. Authentication and repository isolation.
5. GitHub installation and secure cloning.
6. File walker, parser, symbols, and dependency graph.
7. Symbol-aware chunking and persistence.
8. Gemini embeddings and reliable queue processing.
9. Worker and repository synchronization.
10. Lexical/vector search, RRF, and reranking.
11. Context, memory, and Gemini/Groq RAG integration.
12. API contract and frontend integration.
13. Security gate and comprehensive tests.
14. Documentation, cleanup, and final acceptance report.

Respect the dependency rules in `Docs/week1.md`. In particular, stabilize the symbol schema before finalizing chunking, verify indexed chunks before retrieval, and do not start autonomous agent execution before the knowledge layer works.

## Final acceptance criteria

The backend is ready for Week 2 only when the Week 1 Definition of Done is demonstrated on a fresh, reproducible setup.

The system must connect and synchronize a repository, safely scan and parse it, persist symbols and chunks, generate real Gemini embeddings, support PostgreSQL lexical and vector retrieval, combine results with RRF, rerank relevant chunks where supported, assemble bounded context with memory, generate through Gemini/Groq, and return verifiable source citations.

Authentication, authorization, job status, secret handling, error responses, migrations, and tests must be part of the acceptance gate.

**Start by auditing the actual code against `Docs/week1.md`, then implement and verify the fixes. Do not stop at an architecture proposal.**

## 4. How to run this with Antigravity efficiently

I recommend letting Antigravity execute this in stages rather than attempting a huge blind rewrite.

1. First pass — audit and traceability. Have it read `Docs/week1.md`, inspect the complete backend, produce the defect matrix, and establish the baseline test results. No large code edits yet.
2. Second pass — infrastructure and ingestion. Fix configuration, migrations, GitHub installation, scanner, chunker, embedding queue, and the missing worker. Verify that a small repository can be indexed.
3. Third pass — search and chat. Wire real embeddings, lexical/vector retrieval, RRF, reranking, context, Gemini/Groq, and grounding. Verify a known repository question.
4. Fourth pass — security and final tests. Verify repository isolation, secret redaction, path safety, rate limits, fresh migrations, and the frontend/backend contract.

My priority for your project: do not begin Week 2 until you can demonstrate the complete path from a connected repository to a grounded chat answer. That is the strongest evidence that the Week 1 backend foundation is genuinely working.