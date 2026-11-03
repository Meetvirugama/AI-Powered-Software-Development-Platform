I’ll complete the remaining database and Redis audits in this same conversation, using the uploaded project ZIP and the same depth as the frontend, backend, and AI audits.

I’ll cover:
1. Database: schema, SQLAlchemy models, migrations, relationships, indexes, constraints, transactions, query efficiency, connection pooling, data integrity, security, and Supabase/pgvector compatibility.
2. Redis: queues, caching, sessions, rate limiting, pub/sub or streams, TTLs, failure handling, concurrency, memory limits, and production configuration.
3. Cross-layer audit: how the frontend, backend, AI, database, and Redis interact; duplicated responsibilities, inconsistent contracts, and deployment risks.
4. Final implementation plan: what to keep, remove, refactor, test, and prioritize for production readiness through Week 2.
I’ll distinguish confirmed source-code issues from recommendations that still need runtime or production verification.
1. Database audit
The database layer is built around PostgreSQL, SQLAlchemy 2.x, Alembic, and pgvector. The overall direction is sound, and the project already has useful foundations: UUID primary keys, timestamp fields, repository-scoped records, vector and full-text indexes, and a migration history.

However, I found several areas that should be addressed before treating the database as production-ready.
1.1 Critical findings
Priority	Finding	Why it matters
P0	Database migrations and ORM models need a formal drift check	The application can expect a different schema from the one actually deployed.
P0	Repository/file/chunk relationships lack consistent deletion rules	Deleting or re-indexing a repository can leave orphaned records or fail unexpectedly.
P1	Repository file paths lack a repository-scoped uniqueness constraint	Repeated syncs can create duplicate rows for the same file.
P1	Analysis history stores potentially large JSONB and text payloads	Unbounded history can increase storage, query cost, and backup size.
P1	Connection-pool sizing is fixed per process	Multiple Azure workers can collectively exhaust Supabase PostgreSQL connections.
P1	pgvector index and embedding dimensions are tightly coupled	Changing the embedding model or dimensions requires a coordinated migration and re-indexing.

These are source-level findings and risks; I have not connected to your live Supabase database to inspect its actual schema or data.
1.2 Database infrastructure
File: backend/app/core/database.py

What is already good:
- Separate synchronous and asynchronous SQLAlchemy engines.
- pool_pre_ping=True to detect stale connections.
- Configurable pool size, overflow, timeout, and recycle.
- expire_on_commit=False for the async session factory.
- A session dependency that closes the synchronous session.
What needs improvement:
1. There is no matching get_db_async() dependency in this module. Async services currently receive session factories or sessions through different paths. Standardize this instead of letting each service decide how to acquire and close sessions.
2. Both engines have independently configured pools. With pool_size=20 and max_overflow=10, one API process could theoretically open up to 60 connections across its sync and async engines. Multiple processes multiply that number.
3. The async URL is constructed using a string replacement. Validate the driver explicitly at startup, especially if a deployment changes from postgresql+psycopg to another PostgreSQL URL.
4. Pool sizing should be derived from the actual Supabase connection limit, number of API processes, worker processes, and migration/admin connections.
Recommended target: one documented session lifecycle for sync code and one for async code, explicit connection budgets, and startup validation.
1.3 ORM models and schema design
The main models are:
- User, GitHubInstallation, Repository
- RepositoryFile, CodeSymbol, SymbolEdge
- CodeChunk, MemoryEntry
- SyncJob, PullRequest
- AnalysisRun, AnalysisFinding
Important changes:
- RepositoryFile: add a unique constraint on (repository_id, path) after cleaning existing duplicates.
- CodeChunk: define a stable identity for a chunk, including repository/file, source revision, chunk location or symbol, and content hash. The current (repository_id, content_hash) index is not unique, so duplicate chunks can be inserted.
- CodeSymbol: consider uniqueness based on file, symbol identity, and source revision; avoid assuming a symbol name is unique within a file.
- SymbolEdge: add uniqueness for the source symbol, target symbol, edge type, and revision where appropriate. Add indexes for both source and target traversal.
- Repository: consider a unique constraint on the GitHub repository identity. Confirm whether the same GitHub repository can legitimately appear under multiple installation records in your product before choosing the exact constraint.
- SyncJob: add fields for attempts, last error code, started time, completed time, and next retry time if retries are required.
- AnalysisRun: validate status and feature type using database constraints or native enums consistently, rather than relying only on application code.
- AnalysisFinding: constrain line numbers, severity, confidence, and source type to valid values.
Do not add every suggested constraint blindly. First check existing rows and the intended semantics, then migrate safely.
1.4 Relationships and deletion behaviour
Several foreign keys do not specify ondelete, including important relationships involving repository files, code symbols, chunks, and memory entries.

That creates inconsistent deletion behaviour. For example, a repository may be deleted while dependent chunks or symbols remain, depending on the exact foreign-key path and current database state.

Define a consistent policy:
- Deleting a repository should delete its files, chunks, symbols, edges, memory, sync jobs, analysis runs, and findings where those records have no independent retention requirement.
- Deleting a user should follow an explicit account-retention policy; do not automatically delete audit history if you need it for compliance or operational investigation.
- Deleting a file should remove its chunks and symbols.
- Deleting a symbol should either remove its edges or use a deliberate restricted-deletion policy.
Use database-level ON DELETE rules and matching ORM relationship cascades. Do not rely only on application-level cleanup.
1.5 Migrations and Alembic
Files: backend/migrations/env.py and backend/migrations/versions/

The migration chain is linear:

pgvector extension → identity schema → content tables → sync jobs → chunks and memory → analysis runs and findings

The model registry is imported in env.py, which is good for autogeneration.

What I would change:
- Add a CI check that compares the current ORM metadata against the latest migration.
- Test migrations from an empty database and from the previous production schema.
- Test downgrade scripts in a disposable database.
- Verify that the Supabase PostgreSQL role has permission to use the vector extension. Extension installation may require elevated privileges.
- Do not use alembic upgrade head concurrently from every application replica. Run migrations as a single deployment step.
- Review the raw enum creation and subsequent ALTER COLUMN operations. Keep enum creation, ORM enum names, and downgrade behaviour consistent.
- Treat the embedding dimension as a schema contract. Do not change Vector(768) without a migration and a complete embedding refresh plan.
One important production rule: never use Base.metadata.create_all() as a replacement for Alembic migrations in deployment.
1.6 pgvector and retrieval indexes
File: backend/app/models/code_chunk.py

The model already defines:
- A 768-dimensional vector.
- An HNSW index using cosine distance.
- A GIN full-text index.
- A repository/content-hash index.
This is a useful baseline, but test the actual query plans against representative data.

Recommended checks:
- Confirm the vector query uses the HNSW index at realistic repository sizes.
- Confirm the lexical query uses the GIN index.
- Check that repository filtering is applied to both retrieval paths.
- Test whether a composite or partial index improves repository-scoped retrieval.
- Benchmark HNSW m, ef_construction, and query-time ef_search instead of assuming defaults are optimal.
- Monitor index size and insertion/update latency during repository re-indexing.
Do not change the embedding model, vector dimensions, or chunk identity in isolation. These changes must be coordinated with the AI indexing and database migration phases.
1.7 A critical indexing transaction problem
File: backend/indexer/incremental.py

This is one of the most important database findings.

The production sync worker passes AsyncSessionLocal—a session factory—to IncrementalIndexer. In _execute(), when the supplied object is a factory rather than a session, the indexer opens a new session, executes one SQL statement, and commits it.

That means a single file update can be committed as several separate transactions:
1. Delete old chunks.
2. Delete old symbol edges.
3. Delete old symbols.
4. Update the file record.
5. Insert replacement symbols.
6. Insert replacement chunks.
7. Insert dependency edges.
If a later operation fails, earlier changes have already committed. The final _commit() does not repair this: the factory itself has no transaction to commit.

Required fix: open one AsyncSession for a defined indexing transaction, pass that session into the indexer, and commit or roll back at the correct boundary. For very large repositories, use bounded transactions per file or per batch—but make each file's replacement atomic.

Also fix these related indexing problems:
- Files removed from GitHub are not visibly reconciled against existing repository_files records in this sync flow. Add a missing-file reconciliation step so deleted files do not remain searchable.
- A modified file has old chunks deleted before replacement chunks are successfully embedded and inserted. With separate commits, an embedding or database failure can leave the file with no usable chunks.
- Validate that the embedding result count exactly matches the chunk count before insertion. Do not insert null vectors into the non-null embedding column or silently accept incomplete batches.
- Add a failure-recovery test that simulates an exception after old chunks are deleted and verifies that the previous file index remains intact or that the operation is safely resumable.
1.8 Repository deletion and transaction safety
File: backend/app/repositories/repository_repository.py

The repository deletion method manually deletes dependent records. That is understandable given the current foreign-key definitions, but it has two problems:
- It wraps some deletes in broad except Exception: pass blocks. In PostgreSQL, a failed statement can leave the transaction aborted. Swallowing the exception does not restore the transaction; subsequent statements can fail too.
- The deletion logic is duplicated application-level knowledge of the schema. Every new dependent table must be added manually.
Fix: remove broad exception swallowing, use one explicit transaction, and add database-level deletion rules where appropriate. If a delete fails, roll back and return a controlled error. Add an integration test that deletes a repository containing every dependent record type.
1.9 Data lifecycle and query performance
Additional changes to schedule:
- Add retention policies for old analysis runs, findings, and large generated test outputs. Keep the policy configurable and do not delete records required for audit.
- Paginate repository and analysis history queries at the database level. Avoid fetching all rows and slicing in application memory.
- Add composite indexes based on real query patterns, not just one index per column.
- Review the standalone indexes on analysis_runs and analysis_findings against their composite indexes using EXPLAIN (ANALYZE, BUFFERS).
- Add database constraints for valid line ranges (start_line > 0, end_line >= start_line when present) and non-negative file sizes and line counts.
- Ensure updated_at is maintained for raw SQL updates as well as ORM updates. The current mixin's onupdate=func.now() is an ORM-side update behaviour, not a database-wide trigger.
- Review JSON versus JSONB use. Use JSONB where you need PostgreSQL querying/indexing; retain ordinary JSON where you only store and retrieve a document.

2. Redis audit
Redis is used for several different responsibilities. These should not all be treated as equivalent: losing a cache entry is usually recoverable, but losing a repository-sync job or an authentication revocation record can affect correctness or security.
2.1 Current Redis usage
Responsibility	Current implementation	Assessment
Repository sync queue	Redis list: sync_jobs	Critical  Not reliably acknowledged
Embedding queue	Redis lists: embedding_queue and embedding_queue:processing	Critical  Failure handling can lose work
GitHub installation tokens	gh_token:{installation_id}, TTL 55 minutes	Good foundation; needs concurrent refresh protection
JWT revocation	auth:blocklist:{jti}, TTL until token expiry	Good pattern; Redis availability is security-critical
Rate limiting	ratelimit:*, fixed one-minute windows	Good baseline; fallback is process-local
Repository source cache	SourceRevisionCache	Implemented, but not wired into the normal GitHub source-service construction
Real-time events	Redis Pub/Sub channel platform_events	Suitable for transient notifications, not durable events

2.2 Critical: repository sync queue can lose jobs
Files:
- backend/app/services/repository_sync.py
- backend/app/services/sync_worker.py
The API pushes a job to the Redis list using RPUSH. The worker consumes it with BLPOP.

BLPOP removes the job immediately. If the worker process crashes after receiving the item but before completing the sync, Redis no longer has that job in the pending queue.

The database has a stale-job reconciliation routine, but it marks old jobs as failed; it does not reliably re-deliver the lost work.

There is also a database/Redis dual-write problem:
1. The database job is committed.
2. The API pushes the job into Redis.
3. If the process crashes between those steps, the database contains a queued job that Redis never received.
Recommended solution: use a transactional outbox.
- Create the SyncJob and an outbox event in the same PostgreSQL transaction.
- A dispatcher publishes pending outbox events to Redis.
- Use Redis Streams consumer groups, or another queue with explicit acknowledgement and pending-message recovery.
- Track attempts, delivery time, last error, and dead-letter status.
- Make the sync handler idempotent so a retried job cannot corrupt the repository index.
Do not simply switch from BLPOP to another list command and assume the reliability problem is solved.
2.3 Critical: embedding queue acknowledges failed persistence
File: backend/indexer/embedding_queue.py

I found several concrete problems:
1. If db_session is absent, the method can still remove the processed items from the processing queue.
2. If database persistence fails, the exception is logged and the transaction rolled back, but the code still acknowledges and removes the items.
3. The returned embedding count is not checked against the number of queued chunks.
4. Items moved into embedding_queue:processing are not recovered automatically after a worker crash.
5. The fallback path using LPOP followed by RPUSH is not atomic.
6. The implementation uses synchronous Redis and database operations inside an async method, which can block the event loop.
There is an additional architectural issue: I found no production construction/use of EmbeddingQueue outside its tests. The main sync flow currently calls EmbeddingService directly through IncrementalIndexer.

Recommendation: do not maintain two competing embedding pipelines. First decide whether embeddings are processed directly during repository sync or through a separate queue. Keep one production path. If the queue is retained, require successful embedding generation, exact result-count validation, successful database commit, and only then acknowledgement.
2.4 Redis connection management
File: backend/app/core/redis.py

Good:
- Lazy client creation.
- Separate sync and async clients.
- Connection and socket timeouts.
- Explicit shutdown functions.
Improvements:
- Add configurable maximum connections and pool sizing.
- Add a bounded retry policy for transient connection failures.
- Avoid silently swallowing every close error; log at debug or warning level.
- Make async client initialization safe against concurrent first requests.
- Use distinct key prefixes for environments and application components.
- Add a Redis client lifecycle test covering startup, reconnect, and shutdown.
A single Redis database number is not a reliable isolation boundary between development, staging, and production. Use separate instances or clearly separated deployment namespaces and credentials.
2.5 Source cache is not actually using Redis in the normal route path
Files:
- backend/app/integrations/github/cache.py
- backend/app/integrations/github/source_service.py
- backend/app/integrations/github/routes.py
SourceRevisionCache supports Redis, but GitHubSourceService defaults to SourceRevisionCache() with no Redis client. The normal routes construct GitHubSourceService(db) without supplying a Redis-backed cache.

So the implemented source cache is effectively process-local in those paths, not shared Redis caching.

There is another issue: the in-memory cache does not enforce the Redis TTL. Entries can remain in process memory indefinitely, and each API process has a separate cache.

Fix: inject a shared Redis-backed cache through application startup, enforce expiration in the memory layer, bound its size, and make invalidation behaviour explicit. Keep the revision and commit-SHA validation; that is important for source correctness.
2.6 Authentication revocation and Redis outages
Files:
- backend/app/core/auth.py
- backend/app/api/v1/auth.py
The blocklist design is sensible: the JWT ID is stored with a TTL equal to the remaining token lifetime.

However, Redis availability is part of authentication correctness. The middleware currently returns a service-unavailable response when it cannot check the blocklist. That is a deliberate fail-closed policy and should remain so unless you replace it with another secure revocation design.

Required tests:
- Revoked token is rejected.
- Expired blocklist entry is removed automatically.
- Redis unavailable causes protected requests to fail closed.
- Logout does not report success when revocation could not be persisted.
- Multiple API processes see the same revocation.
Do not change authentication revocation to fail open just to improve availability.
2.7 Rate limiting
File: backend/app/core/rate_limit.py

This is one of the better Redis integrations:
- Uses a fixed time window.
- Uses a Redis pipeline for increment and expiry.
- Uses user identity for expensive AI routes.
- Uses IP identity for OAuth callback limits.
- Has a bounded local fallback for expensive AI operations.
Remaining risks:
- The in-memory fallback is per process, so multiple Azure instances do not share the fallback count.
- Non-AI endpoints fail open when Redis is unavailable.
- X-Forwarded-For must only be trusted behind a correctly configured trusted proxy.
- Add explicit tests for the same identity reaching different API instances.
- Add limits for other costly operations, including large repository syncs and any future agent execution endpoints.
Keep the current fallback for AI endpoints, but monitor Redis failures and expose fallback activation in metrics.
2.8 GitHub token cache
File: backend/app/integrations/github/token_manager.py

The 55-minute TTL for a token with a 60-minute lifetime is sensible.

The main missing feature is protection against concurrent cache misses. If many requests arrive together for the same installation, they can all attempt to mint a token.

Add a short-lived per-installation distributed lock or another single-flight mechanism, with a safe lock-release strategy. Also test token invalidation after GitHub returns 401.
2.9 Redis Pub/Sub and SSE
Files:
- backend/app/services/sync_worker.py
- backend/app/api/v1/events.py
Pub/Sub is suitable for transient UI notifications. It is not durable: a disconnected frontend misses messages published while it is offline.

That is acceptable if the frontend always refreshes authoritative state from the API after reconnecting. It is not acceptable if the event itself is the only record of a completed operation.

Additional concerns:
- Use structured, validated event payloads.
- Do not allow malformed event payloads to be broadcast to clients.
- Keep user and repository authorization checks strict.
- Reconnect or terminate cleanly when Redis Pub/Sub fails.
- Consider one subscription per SSE connection's lifecycle, with bounded connection counts and cleanup.
- Do not send sensitive source content, tokens, or raw analysis payloads through broad Pub/Sub channels.
Keep Pub/Sub for notifications; keep the database as the source of truth.
2.10 Redis deployment configuration
Files: backend/app/core/config.py, .env.example, docker-compose.yml

The local Docker Compose configuration is appropriate for development, but it is not a production Redis configuration.

The current production settings validation checks JWT and cookie security, but it does not validate database or Redis connection security.

For your deployment:
Component	Recommended configuration
PostgreSQL	Supabase PostgreSQL connection string with SSL
Redis	Upstash Redis connection URL using TLS (rediss://)
Redis credentials	Stored only in Azure environment variables
Redis pools	Bounded connections with timeouts
Database pools	Sized for all API and worker processes combined
Local Docker	Keep local PostgreSQL and Redis for development only

Add production validation for:
- A configured database URL.
- A configured Redis URL.
- TLS for externally hosted production Redis.
- No default local credentials or localhost service URLs in production.
- Connection pool limits appropriate for the hosting plan.
Do not commit real .env files or connection strings.

3. Cross-layer audit: frontend + backend + AI + database + Redis
This is where the biggest architectural problems appear. Each individual layer has useful functionality, but their responsibilities and failure behaviour are not yet consistently coordinated.
3.1 Recommended target architecture
React frontend — Vercel

Repositories · Studios · Chat · Analysis history · SSE


FastAPI API — Azure

Authentication · Authorization · Validation · API contracts · Orchestration

Supabase PostgreSQL

Source of truth · History · Jobs · Files · pgvector


Upstash Redis

Queues · Cache · Rate limits · Token revocation · Events




Separate background worker — Azure

Repository sync · Clone · Scan · Index · Embedding · Retry


AI services

LLM Gateway · RAG · Hybrid retrieval · Grounding · Explain · Bug detection · Tests · Review


Important architectural rule: PostgreSQL is the source of truth. Redis is an operational support layer, not the permanent owner of important application data.
3.2 Cross-layer problems to resolve
Problem	Layers affected	Required resolution
Sync job can be committed to DB but never dispatched to Redis	Backend + DB + Redis	Transactional outbox
Worker can lose a job after BLPOP	Backend + Redis	Acknowledgement and recovery
Indexing can partially commit	AI/indexer + DB	Explicit transaction boundaries
Deleted GitHub files can remain in the index	GitHub + indexer + DB + RAG	Deleted-file reconciliation
Source cache is not injected with Redis	Backend + Redis	Central cache initialization
Source revision and embedding model must stay aligned	AI + DB	Versioned indexing contract
SSE events are transient	Backend + Redis + frontend	Re-fetch authoritative state on reconnect
Sync state may not reflect the actual worker state	Backend + DB + frontend	Explicit job state transitions
Database pool limits multiply across processes	Azure + DB	Global connection budget
Rate-limit fallback is process-local	Backend + Redis + Azure	Monitor degraded operation and bound fallback

3.3 Define one repository indexing lifecycle
Your repository sync, indexing, AI retrieval, and frontend status should follow one consistent lifecycle.
#chatgpt-mermaid-_r_s8_{font-family:-apple-system-body,ui-sans-serif,-apple-system,system-ui,Segoe UI,Helvetica,Apple Color Emoji,Arial,sans-serif,Segoe UI Emoji,Segoe UI Symbol;font-size:16px;fill:rgb(237, 237, 237);}@keyframes edge-animation-frame{from{stroke-dashoffset:0;}}@keyframes dash{to{stroke-dashoffset:0;}}#chatgpt-mermaid-_r_s8_ .edge-animation-slow{stroke-dasharray:9,5!important;stroke-dashoffset:900;animation:dash 50s linear infinite;stroke-linecap:round;}#chatgpt-mermaid-_r_s8_ .edge-animation-fast{stroke-dasharray:9,5!important;stroke-dashoffset:900;animation:dash 20s linear infinite;stroke-linecap:round;}#chatgpt-mermaid-_r_s8_ .error-icon{fill:rgb(48, 48, 48);}#chatgpt-mermaid-_r_s8_ .error-text{fill:rgb(237, 237, 237);stroke:rgb(237, 237, 237);}#chatgpt-mermaid-_r_s8_ .edge-thickness-normal{stroke-width:1px;}#chatgpt-mermaid-_r_s8_ .edge-thickness-thick{stroke-width:3.5px;}#chatgpt-mermaid-_r_s8_ .edge-pattern-solid{stroke-dasharray:0;}#chatgpt-mermaid-_r_s8_ .edge-thickness-invisible{stroke-width:0;fill:none;}#chatgpt-mermaid-_r_s8_ .edge-pattern-dashed{stroke-dasharray:3;}#chatgpt-mermaid-_r_s8_ .edge-pattern-dotted{stroke-dasharray:2;}#chatgpt-mermaid-_r_s8_ .marker{fill:rgb(175, 175, 175);stroke:rgb(175, 175, 175);}#chatgpt-mermaid-_r_s8_ .marker.cross{stroke:rgb(175, 175, 175);}#chatgpt-mermaid-_r_s8_ svg{font-family:-apple-system-body,ui-sans-serif,-apple-system,system-ui,Segoe UI,Helvetica,Apple Color Emoji,Arial,sans-serif,Segoe UI Emoji,Segoe UI Symbol;font-size:16px;}#chatgpt-mermaid-_r_s8_ p{margin:0;}#chatgpt-mermaid-_r_s8_ .label{font-family:-apple-system-body,ui-sans-serif,-apple-system,system-ui,Segoe UI,Helvetica,Apple Color Emoji,Arial,sans-serif,Segoe UI Emoji,Segoe UI Symbol;color:rgb(237, 237, 237);}#chatgpt-mermaid-_r_s8_ .cluster-label text{fill:rgb(237, 237, 237);}#chatgpt-mermaid-_r_s8_ .cluster-label span{color:rgb(237, 237, 237);}#chatgpt-mermaid-_r_s8_ .cluster-label span p{background-color:transparent;}#chatgpt-mermaid-_r_s8_ .label text,#chatgpt-mermaid-_r_s8_ span{fill:rgb(237, 237, 237);color:rgb(237, 237, 237);}#chatgpt-mermaid-_r_s8_ .node rect,#chatgpt-mermaid-_r_s8_ .node circle,#chatgpt-mermaid-_r_s8_ .node ellipse,#chatgpt-mermaid-_r_s8_ .node polygon,#chatgpt-mermaid-_r_s8_ .node path{fill:rgb(9, 23, 44);stroke:rgb(31, 78, 148);stroke-width:1px;}#chatgpt-mermaid-_r_s8_ .rough-node .label text,#chatgpt-mermaid-_r_s8_ .node .label text,#chatgpt-mermaid-_r_s8_ .image-shape .label,#chatgpt-mermaid-_r_s8_ .icon-shape .label{text-anchor:middle;}#chatgpt-mermaid-_r_s8_ .node .katex path{fill:#000;stroke:#000;stroke-width:1px;}#chatgpt-mermaid-_r_s8_ .rough-node .label,#chatgpt-mermaid-_r_s8_ .node .label,#chatgpt-mermaid-_r_s8_ .image-shape .label,#chatgpt-mermaid-_r_s8_ .icon-shape .label{text-align:center;}#chatgpt-mermaid-_r_s8_ .node.clickable{cursor:pointer;}#chatgpt-mermaid-_r_s8_ .root .anchor path{fill:rgb(175, 175, 175)!important;stroke-width:0;stroke:rgb(175, 175, 175);}#chatgpt-mermaid-_r_s8_ .arrowheadPath{fill:rgb(175, 175, 175);}#chatgpt-mermaid-_r_s8_ .edgePath .path{stroke:rgb(175, 175, 175);stroke-width:1px;}#chatgpt-mermaid-_r_s8_ .flowchart-link{stroke:rgb(175, 175, 175);fill:none;}#chatgpt-mermaid-_r_s8_ .edgeLabel{background-color:rgb(0, 0, 0);text-align:center;}#chatgpt-mermaid-_r_s8_ .edgeLabel p{background-color:rgb(0, 0, 0);}#chatgpt-mermaid-_r_s8_ .edgeLabel rect{opacity:0.5;background-color:rgb(0, 0, 0);fill:rgb(0, 0, 0);}#chatgpt-mermaid-_r_s8_ .labelBkg{background-color:rgba(0, 0, 0, 0.5);}#chatgpt-mermaid-_r_s8_ .cluster rect{fill:rgb(48, 48, 48);stroke:rgba(255, 255, 255, 0.15);stroke-width:1px;}#chatgpt-mermaid-_r_s8_ .cluster text{fill:rgb(237, 237, 237);}#chatgpt-mermaid-_r_s8_ .cluster span{color:rgb(237, 237, 237);}#chatgpt-mermaid-_r_s8_ div.mermaidTooltip{position:absolute;text-align:center;max-width:200px;padding:2px;font-family:-apple-system-body,ui-sans-serif,-apple-system,system-ui,Segoe UI,Helvetica,Apple Color Emoji,Arial,sans-serif,Segoe UI Emoji,Segoe UI Symbol;font-size:12px;background:rgb(48, 48, 48);border:1px solid rgba(255, 255, 255, 0.15);border-radius:2px;pointer-events:none;z-index:100;}#chatgpt-mermaid-_r_s8_ .flowchartTitleText{text-anchor:middle;font-size:18px;fill:rgb(237, 237, 237);}#chatgpt-mermaid-_r_s8_ rect.text{fill:none;stroke-width:0;}#chatgpt-mermaid-_r_s8_ .icon-shape,#chatgpt-mermaid-_r_s8_ .image-shape{background-color:rgb(0, 0, 0);text-align:center;}#chatgpt-mermaid-_r_s8_ .icon-shape p,#chatgpt-mermaid-_r_s8_ .image-shape p{background-color:rgb(0, 0, 0);padding:2px;}#chatgpt-mermaid-_r_s8_ .icon-shape .label rect,#chatgpt-mermaid-_r_s8_ .image-shape .label rect{opacity:0.5;background-color:rgb(0, 0, 0);fill:rgb(0, 0, 0);}#chatgpt-mermaid-_r_s8_ .label-icon{display:inline-block;height:1em;overflow:visible;vertical-align:-0.125em;}#chatgpt-mermaid-_r_s8_ .node .label-icon path{fill:currentColor;stroke:revert;stroke-width:revert;}#chatgpt-mermaid-_r_s8_ .node .neo-node{stroke:rgb(31, 78, 148);}#chatgpt-mermaid-_r_s8_ [data-look="neo"].node rect,#chatgpt-mermaid-_r_s8_ [data-look="neo"].cluster rect,#chatgpt-mermaid-_r_s8_ [data-look="neo"].node polygon{stroke:url(#chatgpt-mermaid-_r_s8_-gradient);filter:drop-shadow( 1px 2px 2px rgba(185,185,185,1));}#chatgpt-mermaid-_r_s8_ [data-look="neo"].swimlane.cluster rect{filter:none;}#chatgpt-mermaid-_r_s8_ [data-look="neo"].node path{stroke:url(#chatgpt-mermaid-_r_s8_-gradient);stroke-width:1px;}#chatgpt-mermaid-_r_s8_ [data-look="neo"].node .outer-path{filter:drop-shadow( 1px 2px 2px rgba(185,185,185,1));}#chatgpt-mermaid-_r_s8_ [data-look="neo"].node .neo-line path{stroke:rgb(31, 78, 148);filter:none;}#chatgpt-mermaid-_r_s8_ [data-look="neo"].node circle{stroke:url(#chatgpt-mermaid-_r_s8_-gradient);filter:drop-shadow( 1px 2px 2px rgba(185,185,185,1));}#chatgpt-mermaid-_r_s8_ [data-look="neo"].node circle .state-start{fill:#000000;}#chatgpt-mermaid-_r_s8_ [data-look="neo"].icon-shape .icon{fill:url(#chatgpt-mermaid-_r_s8_-gradient);filter:drop-shadow( 1px 2px 2px rgba(185,185,185,1));}#chatgpt-mermaid-_r_s8_ [data-look="neo"].icon-shape .icon-neo path{stroke:url(#chatgpt-mermaid-_r_s8_-gradient);filter:drop-shadow( 1px 2px 2px rgba(185,185,185,1));}#chatgpt-mermaid-_r_s8_ .node text{font-size:14px;font-weight:600;letter-spacing:normal;fill:rgb(153, 206, 255);}#chatgpt-mermaid-_r_s8_ .edgeLabels text{font-size:13px;font-weight:600;letter-spacing:-0.08px;fill:rgb(153, 206, 255);}#chatgpt-mermaid-_r_s8_ .node tspan[font-weight="normal"],#chatgpt-mermaid-_r_s8_ .edgeLabels tspan[font-weight="normal"]{font-weight:600;}#chatgpt-mermaid-_r_s8_ .edgeLabel .label rect{opacity:1;rx:13px;ry:13px;fill:rgb(0, 14, 26);stroke:rgb(26, 62, 95);stroke-width:1px;}#chatgpt-mermaid-_r_s8_ .node rect,#chatgpt-mermaid-_r_s8_ .node circle,#chatgpt-mermaid-_r_s8_ .node ellipse,#chatgpt-mermaid-_r_s8_ .node polygon,#chatgpt-mermaid-_r_s8_ .node path{fill:rgb(0, 40, 77);stroke:rgba(255, 255, 255, 0.1);stroke-width:1px;}#chatgpt-mermaid-_r_s8_ .node rect{rx:16px;ry:16px;}#chatgpt-mermaid-_r_s8_ .mermaid-decision .label-container{fill:rgb(0, 14, 26);stroke:rgb(26, 62, 95);stroke-dasharray:2,2;}#chatgpt-mermaid-_r_s8_ .edgePaths .flowchart-link{stroke:rgb(175, 175, 175);stroke-width:1px;stroke-linecap:round;stroke-linejoin:round;}#chatgpt-mermaid-_r_s8_ .marker{fill:rgb(175, 175, 175);stroke:rgb(175, 175, 175);}#chatgpt-mermaid-_r_s8_ :root{--mermaid-font-family:-apple-system-body,ui-sans-serif,-apple-system,system-ui,Segoe UI,Helvetica,Apple Color Emoji,Arial,sans-serif,Segoe UI Emoji,Segoe UI Symbol;}User requests repository syncAPI authorizes repositoryCreate SyncJob + Outboxevent in PostgreSQLDispatcher publishes jobWorker claims jobClone repositoryScan and compare file hashesIdentify new, changed anddeleted filesParse symbols and createchunksRedact secrets and generateembeddingsAtomically persist eachindexing batchValidate index and sourcerevisionMark job and repositorySYNCEDPublish repository.updatedFrontend refreshes repositorystateFailure / retryRetry with bounded attemptsDead-letter / terminal failure





Do not mark the repository SYNCED until the required indexing work has completed and its final state has been verified.
3.4 Standardize status and error contracts
Use a single job status vocabulary across the database, worker, API, and frontend.
Status	Meaning
QUEUED	Persisted and waiting for a worker
RUNNING	Worker has claimed the job
RETRYING	Failed temporarily; eligible for retry
COMPLETED	All required work completed
FAILED	Terminal failure
CANCELLED	Explicitly cancelled

Add separate progress stages such as CLONING, SCANNING, INDEXING, and EMBEDDING rather than overloading the job status.

The frontend should not infer these stages from a generic SYNCING status. The backend must provide them.
3.5 Keep responsibilities separated
Component	Should own	Should not own
Frontend	UI state, interaction, presentation	Database or Redis business logic
API	Auth, authorization, request validation, orchestration	Long-running repository processing
Database	Durable records, constraints, transactions	Temporary cache
Redis	Queue transport, cache, rate limits, revocation	Permanent job history
Worker	Sync, indexing, retries, recovery	HTTP request lifecycle
AI services	Retrieval, prompts, generation, validation	Direct ownership of repository lifecycle


4. What to keep, refactor, and remove
The goal should be to reduce duplication without removing working functionality.
Database
File or component	Decision
app/core/database.py	Keep; standardize session lifecycle and pool configuration
app/models/base.py	Keep; standardize timestamp handling
All existing ORM models	Keep; improve constraints and deletion policies
migrations/versions/	Keep all migration history
migrations/env.py	Keep; improve migration configuration and CI checks
app/repositories/repository_repository.py	Refactor deletion and transaction handling
indexer/incremental.py	Refactor transaction ownership and file reconciliation
app/repositories/analysis_run_repository.py	Keep; optimize pagination and query patterns

There is already a migration smoke test at backend/tests/test_migration_smoke.py. It checks the migration chain, clean migration lifecycle, and ORM schema drift. Keep it and make sure CI actually runs it against PostgreSQL with pgvector. Its database-dependent checks skip when the database is unavailable, so a green test run alone does not prove the migration checks executed.
Redis
File or component	Decision
app/core/redis.py	Keep; improve pools, lifecycle, and production validation
app/core/rate_limit.py	Keep; improve distributed fallback and monitoring
app/core/auth.py	Keep; preserve fail-closed revocation checks
app/integrations/github/token_manager.py	Keep; add concurrent refresh protection
app/integrations/github/cache.py	Keep; fix TTL and wire Redis into actual routes
app/services/repository_sync.py	Refactor around durable dispatch
app/services/sync_worker.py	Refactor job acknowledgement and recovery
indexer/embedding_queue.py	Do not keep as a second production embedding path unless deliberately redesigned

Do not delete the Redis embedding queue immediately. First confirm whether any deployment or external worker consumes it. The source search found no production construction outside its tests, but deployment configuration should also be checked before removal.

5. Final priority plan — production readiness through Week 2
This is the combined plan for all audited areas, not a request to rewrite the whole project at once.
P0 — Fix before production use
Task	Area	Deliverable
P0.1	Database	Fix IncrementalIndexer session and transaction handling
P0.2	Database	Reconcile removed files during indexing
P0.3	Database	Validate embedding batch count and prevent incomplete persistence
P0.4	Redis	Replace destructive sync-job consumption with reliable acknowledgement
P0.5	DB + Redis	Add transactional outbox for sync dispatch
P0.6	Redis	Fix embedding queue acknowledgement and recovery, or retire unused path
P0.7	Backend	Separate API process from worker process
P0.8	Security	Preserve strict repository isolation, auth revocation, and prompt/tool boundaries
P0.9	Database	Verify migrations against actual Supabase schema
P0.10	Deployment	Validate production database and Redis TLS/configuration

P1 — Required for a robust Week 2 release
Task	Area	Deliverable
P1.1	Database	Add repository-scoped file uniqueness and safe chunk identity
P1.2	Database	Define consistent foreign-key deletion policies
P1.3	Database	Remove broad exception swallowing in repository deletion
P1.4	Database	Define analysis history retention and pagination
P1.5	Redis	Inject Redis-backed source cache into GitHub source routes
P1.6	Redis	Enforce memory-cache TTL and maximum size
P1.7	Redis	Add token refresh single-flight protection
P1.8	Redis	Add queue retries, dead-letter handling, and worker recovery
P1.9	Azure + DB	Calculate connection budget for API and worker instances
P1.10	Frontend	Refresh authoritative sync state after SSE reconnect
P1.11	AI + DB	Preserve embedding model, dimensions, and source revision consistency

P2 — Optimization and maintainability
- Benchmark pgvector HNSW and lexical indexes with representative repository data.
- Remove redundant database indexes only after query-plan analysis.
- Add Redis memory and eviction monitoring.
- Add queue depth, oldest pending job, retry count, and failure metrics.
- Add analysis history cleanup jobs.
- Add database query latency and pool saturation monitoring.
- Add structured logs with request ID, repository ID, job ID, and worker ID.
- Add production backup and restore drills.
- Add performance benchmarks for large repositories.

6. Testing checklist before declaring the platform production-ready
Release verification
0/14 passed



[ ] Database migration

Fresh PostgreSQL + pgvector database upgrades to head successfully.


[ ] Schema parity

ORM metadata and deployed schema have no unexplained differences.


[ ] Indexing rollback

An injected failure during file replacement does not leave a partial index.


[ ] Deleted files

Files removed from GitHub are removed from the searchable index.


[ ] Embedding integrity

A short or malformed embedding batch is rejected without acknowledging work.


[ ] Repository isolation

One user cannot retrieve another user's files, chunks, findings, or events.


[ ] Sync queue recovery

A worker crash after claiming a job results in safe redelivery.


[ ] Outbox recovery

A dispatcher crash does not permanently lose a committed sync request.


[ ] Duplicate requests

Repeated sync requests do not create uncontrolled duplicate work.


[ ] Redis outage

Authentication fails closed; expensive AI operations retain bounded fallback limits.


[ ] Cache expiry

Expired source data is not returned from process memory.


[ ] SSE reconnect

The frontend reloads actual job status after reconnecting.


[ ] Connection budget

Load testing does not exhaust Supabase connection limits.


[ ] Retention

History cleanup does not remove records still required by the product.


Reset checklist
7. Final assessment
My assessment of the current architecture
- Frontend: needs consolidation of duplicated studio UI and improved state handling.
- Backend: needs stronger worker separation, transaction boundaries, and job reliability.
- AI: has a good foundation, but needs canonical pipeline and model/grounding consistency.
- Database: has a reasonable schema foundation, but indexing transaction safety and data lifecycle need attention.
- Redis: has useful integrations, but queue durability and cache wiring need attention.
The most urgent two fixes are the indexing transaction problem and the sync queue reliability problem. They affect whether the platform can reliably synchronize a repository and produce trustworthy AI retrieval results.

What I would not do
- Do not replace PostgreSQL with another database.
- Do not remove pgvector or the existing hybrid retrieval architecture.
- Do not add another queue system before fixing the current queue's reliability.
- Do not introduce a second production embedding pipeline.
- Do not change the embedding model or vector dimensions without a coordinated re-indexing migration.
- Do not merge all AI engines into one generic engine.
- Do not enable autonomous agent tool execution before authorization, sandboxing, and approval controls are ready.
Audit limitation: this is a source-level audit of the uploaded ZIP. I inspected the database models, migrations, Redis clients, queue implementations, indexing flow, cache, rate limiter, and related tests. I did not connect to live Supabase or Upstash, execute a full migration against your production schema, run a multi-worker crash-recovery test, or verify Azure/Vercel deployment behaviour. No source files have been changed.

The best next implementation milestone is to fix P0.1–P0.6 as one coordinated database/Redis reliability phase, then run the release checklist before starting the lower-priority cleanup.