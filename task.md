# Retrieval System Optimization — Final Implementation Specification

## 0. Project context and objective

You are working on the existing **AI-Powered Software Development Platform** repository.

Your task is to improve the existing code-retrieval/RAG subsystem. This is an implementation task, not merely a research or planning task.

The objective is to make retrieval:

- More accurate for code-specific questions.
- More reliable for exact identifiers, function names, classes, file paths, and error messages.
- Faster for repeated queries.
- Consistent after repository re-indexing and code updates.
- More effective at retrieving related callers, callees, and dependent symbols.
- Measurable through repeatable offline relevance and latency benchmarks.
- Compatible with the existing infrastructure and deployment budget.

### Existing architecture

The repository already contains:

| Component | Existing location |
|---|---|
| Vector retrieval | `backend/ai/retrieval/vector.py` |
| Lexical retrieval | `backend/ai/retrieval/lexical.py` |
| Hybrid orchestration | `backend/ai/retrieval/hybrid.py` |
| Reciprocal Rank Fusion | `backend/ai/retrieval/fusion.py` |
| Cross-encoder reranking | `backend/ai/retrieval/reranker.py` |
| Retrieval pipeline | `backend/ai/retrieval/pipeline.py` |
| Retrieval optimization | `backend/ai/services/retrieval_optimizer.py` |
| Redis client | `backend/app/core/redis.py` |
| Application configuration | `backend/app/core/config.py` |
| Application lifespan | `backend/app/core/lifespan.py` |
| Incremental indexing | `backend/indexer/incremental.py` |
| Symbol-edge model | `backend/app/models/symbol_edge.py` |
| Symbol-edge repository | `backend/app/repositories/symbol_edge_repository.py` |
| Existing HNSW and GIN indexes | `backend/migrations/versions/e7b8c9d0f1a2_add_code_chunks_and_memory.py` |
| Hybrid retrieval tests | `backend/tests/test_hybrid_retrieval.py` |
| Vector retrieval tests | `backend/tests/test_vector_retrieval.py` |
| RAG tests | `backend/tests/test_rag.py` |

The current retrieval flow is:

```text
User Query
    |
    v
Query Processing
    |
    +-----------------------+
    |                       |
    v                       v
Vector Retrieval       Lexical Retrieval
(pgvector HNSW)        (PostgreSQL FTS)
    |                       |
    +-----------+-----------+
                |
                v
         RRF Fusion
                |
                v
       Cross-Encoder Reranker
                |
                v
          Top-K Chunks
                |
                v
       RAG Context Builder
                |
                v
           LLM Response
```

Do not replace this architecture unnecessarily. Improve it incrementally.

---

# 1. Final scope and implementation decisions

## 1.1 Features to implement

| ID | Improvement | Priority | Decision |
|---|---|---|---|
| R01 | Code-aware lexical retrieval | P1 | Implement |
| R02 | Adaptive HNSW retrieval settings | P1 | Implement |
| R03 | Redis-based asynchronous retrieval-result caching | P1 | Implement |
| R04 | Correct cache invalidation and index versioning | P1 | Implement |
| R05 | Query-intent classification and adaptive source weights | P1 | Implement |
| R06 | Bounded symbol-graph expansion | P1 | Implement |
| R07 | Expanded retrieval evaluation and benchmark suite | P1 | Implement |
| R08 | ONNX reranker evaluation | P2 | Evaluate; adopt only if results justify it |

## 1.2 Features explicitly excluded from implementation

| Feature | Decision |
|---|---|
| Zoekt integration | Do not implement |
| Prometheus/Grafana telemetry dashboard | Do not implement |
| Separate search infrastructure | Do not introduce |
| New paid vector database | Do not introduce |
| New paid embedding or reranking API | Do not introduce |

Zoekt and telemetry dashboard research must remain available in the documentation folder for future consideration.

Do not create a Zoekt service, Docker container, indexer, deployment resource, or runtime dependency.

Do not create Prometheus/Grafana infrastructure, dashboard pages, exporters, or a new telemetry deployment.

Existing application logs and error handling may be preserved. Do not expand this task into a telemetry-platform implementation.

---

# 2. Mandatory rules before making code changes

Before editing:

1. Inspect the entire existing retrieval subsystem.
2. Trace the actual application initialization and dependency injection.
3. Trace the repository indexing and incremental update lifecycle.
4. Inspect database models and migrations.
5. Inspect all callers of `HybridRetriever`.
6. Inspect existing tests and benchmark scripts.
7. Check current PostgreSQL and pgvector versions in the target environment.
8. Identify the actual Redis provider and its connection limits.
9. Identify how repository ownership and access permissions are enforced.
10. Check whether the repository already has index-generation or commit-version tracking.

Do not assume that the architecture description in this document is more current than the source code.

If implementation details differ, follow the repository's actual architecture while preserving the requirements in this document.

### Critical rules

- Do not delete existing functionality to simplify implementation.
- Do not break existing public function signatures unless absolutely necessary.
- Do not create duplicate Redis clients.
- Do not create a second embedding service.
- Do not create a second indexing pipeline.
- Do not bypass existing repository-level access checks.
- Do not remove graceful degradation.
- Do not silently hide database or Redis failures.
- Do not use an LLM call just to classify every retrieval query.
- Do not hardcode experimental ranking weights as permanent truth.
- Do not change embedding dimensions or embedding models as part of this task.
- Do not regenerate all embeddings unless a verified migration requirement makes it necessary.
- Do not modify unrelated frontend, authentication, billing, or AI features.

The application must continue to work if Redis is temporarily unavailable. Retrieval must fall back to the existing uncached path.

---

# 3. R01 — Code-aware lexical retrieval

## 3.1 Existing problem

The current `LexicalRetriever` uses:

```sql
to_tsvector('english', content)
```

and:

```sql
to_tsquery('english', :tsquery)
```

This is not sufficiently code-aware.

Natural-language PostgreSQL stemming and stop-word behavior can be unsuitable for source code.

Examples of important code queries:

```text
getUserById
get_user_by_id
UserAuthenticationService
AUTH_TOKEN_EXPIRED
src/auth/token_service.py
POST /api/v1/auth/login
TypeError: cannot read property
```

The lexical retrieval system should be able to find exact identifiers and useful identifier fragments.

## 3.2 Required design

Implement a code-aware lexical representation while preserving the existing vector retrieval.

The lexical representation should include useful searchable information from:

- Chunk content.
- Symbol name, if available.
- Symbol type, if available.
- File path.
- Relevant identifier tokens.
- CamelCase fragments.
- snake_case fragments.
- Constants.
- Function and class names.

Do not blindly concatenate arbitrary repository metadata or sensitive content.

### Identifier normalization

Create a dedicated helper, preferably in:

`backend/ai/retrieval/code_tokenizer.py`

Responsibilities:

1. Normalize identifiers.
2. Preserve the original identifier.
3. Split camelCase and PascalCase.
4. Split snake_case.
5. Split kebab-case.
6. Preserve meaningful acronyms.
7. Preserve numeric identifier segments.
8. Normalize file paths.
9. Avoid generating excessive duplicate tokens.
10. Apply reasonable maximum input and token-length limits.

Examples:

| Input | Searchable forms |
|---|---|
| `getUserById` | `getUserById`, `get`, `user`, `by`, `id`, `get_user_by_id` |
| `UserAuthenticationService` | `UserAuthenticationService`, `user`, `authentication`, `service` |
| `get_user_by_id` | `get_user_by_id`, `get`, `user`, `by`, `id` |
| `AUTH_TOKEN_EXPIRED` | `AUTH_TOKEN_EXPIRED`, `auth`, `token`, `expired` |
| `token-service.py` | `token-service.py`, `token`, `service`, `py` |

Avoid indexing trivial punctuation as meaningful terms.

Do not discard the original identifier when adding normalized tokens.

## 3.3 Database/index design

Inspect the current `code_chunks` schema and choose the safest implementation.

Preferred approach:

- Add a dedicated code-search text representation or equivalent indexed field.
- Add a GIN index using PostgreSQL's `simple` text-search configuration where appropriate.
- Include file path and symbol metadata in the searchable representation.
- Keep the existing English FTS path temporarily as a compatibility fallback if required.
- Ensure the index is maintained for new, updated, and deleted chunks.

A possible schema direction is:

```text
code_chunks
    id
    repository_id
    file_id
    symbol_id
    content
    code_search_text
    ...
```

A possible index direction is:

```sql
CREATE INDEX ...
ON code_chunks
USING GIN (to_tsvector('simple', code_search_text));
```

This is a design direction, not permission to blindly execute the SQL. Confirm PostgreSQL compatibility and migration conventions first.

If using a generated column, verify that the expression is immutable and supported.

If using a normal persisted column, ensure the indexer always maintains it.

## 3.4 Indexer changes

Inspect:

`backend/indexer/incremental.py`

The current indexer persists chunks through an SQL INSERT into `code_chunks`.

Update the indexing path so that every newly inserted chunk receives the correct code-search representation.

Also update the representation whenever a file is re-indexed.

Ensure:

- Unchanged files are not unnecessarily reprocessed.
- Changed files remove or replace old chunks correctly.
- Deleted files do not leave stale searchable records.
- Repository isolation is maintained.
- Existing secret redaction is preserved.
- Metadata and search text are generated from the correct redacted/safe source.
- Failed indexing does not publish an incomplete index generation.

Do not break the current transaction behavior.

## 3.5 Retriever changes

Update:

`backend/ai/retrieval/lexical.py`

The retriever should support code-aware matching and natural-language matching.

Use parameterized SQL.

Every query must filter by `repository_id`.

Use deterministic ordering when scores are equal.

Return the existing `CodeChunk` interface so downstream RRF, reranking, and context-building code remain compatible.

Avoid treating a missing lexical match as an infrastructure failure.

## 3.6 Query behavior

Exact identifier searches should prioritize exact identifier matches.

Natural-language searches should continue to find relevant conceptual chunks.

For path lookups, path metadata must contribute to relevance.

Do not let a common token such as `get`, `data`, `service`, or `return` dominate the result list.

## 3.7 Required tests

Add tests for:

- CamelCase splitting.
- PascalCase splitting.
- snake_case splitting.
- Constants.
- File paths.
- Numeric identifiers.
- Duplicate token removal.
- Empty input.
- Unicode and punctuation handling.
- Exact identifier retrieval.
- Repository isolation.
- Indexer update behavior.
- Deleted-file cleanup.
- Existing natural-language lexical retrieval.
- Backward compatibility with current `CodeChunk` consumers.

---

# 4. R02 — Adaptive HNSW retrieval settings

## 4.1 Existing problem

The current vector retriever uses pgvector cosine distance and a repository filter.

The existing HNSW index is configured in:

`backend/migrations/versions/e7b8c9d0f1a2_add_code_chunks_and_memory.py`

It currently uses:

```text
m = 16
ef_construction = 64
```

The vector SQL filters by repository ID and limits the result count.

Filtered HNSW retrieval can return fewer candidates than requested if the search is not configured appropriately.

## 4.2 Objective

Use different HNSW search effort depending on the query type.

The goal is to balance:

- Recall.
- Retrieval latency.
- Database CPU.
- Candidate count.

Do not increase every query to an unnecessarily expensive HNSW setting.

## 4.3 Initial profiles

Implement configurable profiles with these initial experimental values:

```python
HNSW_PROFILES = {
    "exact": {
        "ef_search": 40,
        "iterative_scan": "relaxed_order",
    },
    "normal": {
        "ef_search": 64,
        "iterative_scan": "relaxed_order",
    },
    "complex": {
        "ef_search": 120,
        "iterative_scan": "relaxed_order",
    },
}
```

These are starting values, not guaranteed optimal values.

The benchmark suite must determine whether they should be adjusted.

## 4.4 Query profile mapping

| Query type | HNSW profile |
|---|---|
| Exact symbol | exact |
| Exact path | exact |
| Normal conceptual question | normal |
| Debugging | complex |
| Impact analysis | complex |
| Complex multi-file question | complex |
| Test-generation context retrieval | normal or complex, based on measured results |

## 4.5 Implementation

Update:

`backend/ai/retrieval/vector.py`

Add a safe way to select the HNSW profile.

Use transaction-local PostgreSQL settings where supported:

```sql
SET LOCAL hnsw.ef_search = 64;
SET LOCAL hnsw.iterative_scan = 'relaxed_order';
```

Important:

- `SET LOCAL` must execute in the same transaction and connection as the vector query.
- Do not use a global session-level setting that leaks into later requests.
- Do not execute the settings on one connection and the vector query on another.
- Handle SQLAlchemy transaction state correctly.
- Verify that the selected profile actually applies to the query.
- Check the installed pgvector version before relying on iterative scan features.
- If unsupported, fall back safely to supported settings.

Because the retriever can receive an `AsyncSession` or a session factory, support both correctly.

When using a session factory, open one session and execute both the configuration statements and vector query inside it.

When receiving a request-scoped session, preserve its transaction lifecycle.

Do not commit or roll back a caller-owned session unexpectedly.

## 4.6 Configuration

Add validated settings for:

```text
RETRIEVAL_HNSW_ENABLED=true
RETRIEVAL_HNSW_EXACT_EF_SEARCH=40
RETRIEVAL_HNSW_NORMAL_EF_SEARCH=64
RETRIEVAL_HNSW_COMPLEX_EF_SEARCH=120
RETRIEVAL_HNSW_ITERATIVE_SCAN=relaxed_order
```

Use the existing configuration conventions in:

`backend/app/core/config.py`

Validate values and prevent unsafe or unsupported configuration.

## 4.7 Required tests

- Correct profile selection.
- Exact query profile.
- Normal query profile.
- Complex query profile.
- Settings executed before vector SQL.
- Settings and vector query use the same session/transaction.
- Session-factory path.
- Request-scoped session path.
- Unsupported pgvector version fallback.
- Repository filtering remains enforced.
- Empty and failed vector retrieval behavior remains compatible.

---

# 5. R03 — Redis-based asynchronous retrieval-result cache

## 5.1 Existing situation

The application already has Redis infrastructure:

`backend/app/core/redis.py`

It exposes an asynchronous Redis client.

The current:

`backend/ai/services/retrieval_optimizer.py`

contains an in-memory LRU cache.

That cache is process-local. It is not shared across multiple application workers or instances.

The new retrieval cache should use the existing Redis infrastructure.

Do not introduce another Redis server or another cache service.

## 5.2 Objective

When the same repository query is repeated against the same index generation, avoid repeating:

- Query embedding.
- Vector retrieval.
- Lexical retrieval.
- RRF fusion.
- Cross-encoder reranking.

Cache the final retrieval result, not only the raw query.

The cache must be asynchronous.

## 5.3 New modules

Create or adapt:

```text
backend/ai/retrieval/cache.py
backend/ai/retrieval/cache_keys.py
backend/ai/retrieval/cache_serialization.py
```

Do not duplicate an existing cache abstraction if a suitable one is already present.

### Cache interface

Provide an interface equivalent to:

```python
class RetrievalResultCache:
    async def get(self, key: str):
        ...

    async def set(self, key: str, value, ttl_seconds: int):
        ...

    async def invalidate_repository(self, repository_id):
        ...
```

The implementation must use the existing shared async Redis client.

Use dependency injection where appropriate so unit tests can use a fake Redis client.

## 5.4 Cache key design

A cache key must distinguish all factors that can change retrieval results.

Include:

```text
tenant/access scope
repository_id
active index generation or commit SHA
normalized query
query intent
top_k
vector candidate limit
lexical candidate limit
embedding model/profile version
code chunker version
code-search tokenizer version
retrieval configuration version
RRF configuration version
reranker model/version
```

Use a stable hash for the final Redis key.

Example conceptual format:

```text
retrieval:v2:{scope}:{repository_id}:{index_generation}:{query_hash}
```

Do not put raw source code or sensitive query text into Redis keys.

Do not use a query-only cache key.

## 5.5 Serialization

Serialize `CodeChunk` results safely.

Preserve the fields required by downstream consumers, including:

- ID.
- Repository ID.
- File ID.
- Symbol ID.
- Content.
- Token count.
- Start line.
- End line.
- Content hash.
- File path.
- Retrieval score.
- Vector similarity, when available.
- Lexical rank, when available.
- RRF score, when available.
- Reranker score, when available.

Handle UUIDs and optional fields explicitly.

Do not use unsafe pickle deserialization.

Use JSON or another safe, versioned serialization format.

Add a serialization schema version so future changes do not break old cache entries.

## 5.6 TTL

Use a configurable TTL.

Initial proposed default:

```text
RETRIEVAL_CACHE_ENABLED=true
RETRIEVAL_CACHE_TTL_SECONDS=300
RETRIEVAL_CACHE_MAX_PAYLOAD_BYTES=...
```

Five minutes is an initial default, not a correctness guarantee.

Index-generation versioning must protect correctness even when cached entries remain until their TTL expires.

Set a payload-size limit. Do not cache excessively large results.

## 5.7 Failure behavior

If Redis is unavailable:

- Log a bounded warning.
- Continue with normal retrieval.
- Do not fail the RAG request.
- Do not return fabricated empty results.
- Do not disable vector or lexical retrieval.
- Do not repeatedly retry Redis indefinitely.

A cache failure must never become a retrieval failure.

## 5.8 Cache integration

Integrate caching at the hybrid retrieval boundary.

Preferred flow:

```text
HybridRetriever.retrieve()
        |
        v
Build versioned cache key
        |
        v
Redis GET
        |
        +------------------+
        |                  |
       HIT                MISS
        |                  |
        v                  v
Deserialize          Vector + Lexical
        |                  |
        |                  v
        |               RRF Fusion
        |                  |
        |                  v
        |               Graph Expansion
        |                  |
        |                  v
        |              Reranking
        |                  |
        |                  v
        |              Redis SET
        |                  |
        +--------+---------+
                 |
                 v
             Return Top-K
```

Cache the final ordered results after all retrieval stages.

Do not cache an intermediate result and mistakenly treat it as a final reranked result.

Do not cache infrastructure failures as successful empty results.

Consider short-lived negative caching only if the benchmark demonstrates a benefit and correctness is preserved.

## 5.9 Concurrent cache misses

Prevent unnecessary cache stampedes where practical.

If multiple requests ask for the same uncached key simultaneously, use a short-lived Redis lock or another bounded coordination mechanism.

Requirements:

- Lock must expire automatically.
- Lock release must verify ownership.
- Lock timeout must be short.
- If lock acquisition fails, the request must still have a safe fallback.
- Never let a stuck lock block retrieval indefinitely.

Do not add complex distributed coordination unless it is justified by actual concurrency.

## 5.10 Required tests

- Cache hit.
- Cache miss.
- TTL expiration.
- Serialization round trip.
- Invalid/corrupt payload.
- Schema-version mismatch.
- Redis unavailable.
- Cache disabled.
- Tenant/repository isolation.
- Index-generation change produces a different key.
- Query-intent change produces a different key.
- Different top_k produces a different key.
- Different reranker version produces a different key.
- Concurrent cache miss behavior.
- Oversized payload handling.

---

# 6. R04 — Correct cache invalidation and index versioning

This feature is mandatory if retrieval-result caching is enabled.

## 6.1 Problem

A repository can change after a retrieval result is cached.

If the cache is not invalidated or versioned, users can receive old code chunks after:

- A new commit.
- A file update.
- A file deletion.
- A complete repository re-index.
- A chunker change.
- A tokenizer change.
- An embedding profile change.
- A symbol graph rebuild.

TTL alone is not sufficient.

## 6.2 Preferred strategy: generation-based invalidation

Introduce a reliable repository index generation.

Inspect existing repository and sync-job models before adding new fields.

If no equivalent field exists, add an appropriate version/generation field through an Alembic migration.

Conceptually:

```text
repository_id
active_index_generation
active_commit_sha
chunker_version
embedding_profile_version
code_tokenizer_version
symbol_graph_version
updated_at
```

Do not add duplicate fields if the current schema already stores equivalent data.

## 6.3 Publish only complete generations

The active generation must not be changed until the corresponding index is complete and valid.

Required behavior:

```text
Repository Sync Begins
        |
        v
Prepare New Index Generation
        |
        v
Update Files, Symbols, Chunks, Embeddings and Edges
        |
        v
Validate Index Completeness
        |
        +-------------------+
        |                   |
      SUCCESS             FAILURE
        |                   |
        v                   v
Publish New          Roll Back / Keep
Active Generation    Previous Generation
        |
        v
New Cache Keys Used
```

The exact implementation must respect the current indexing transaction model.

Do not publish the new generation before indexing has successfully completed.

If the current indexer performs a fully atomic transaction, preserve that property.

If the current architecture uses staged indexing, make the active-generation switch atomic.

## 6.4 Cache invalidation

Use generation changes as the primary correctness mechanism.

Also provide explicit invalidation for:

- Repository deletion.
- Repository permission changes where cached access could become invalid.
- Manual re-index requests.
- Failed or cancelled indexing where temporary cache state needs cleanup.
- Administrative cache clearing.

Do not invalidate every repository's cache when only one repository changes.

Use repository-scoped invalidation.

If Redis key scanning is necessary, use a safe cursor-based approach. Do not use an unbounded blocking `KEYS` command in production.

## 6.5 Required tests

- New commit changes generation.
- File update changes generation.
- File deletion changes generation.
- Failed indexing does not publish a new generation.
- Successful indexing publishes the new generation.
- Old cached results cannot be used with the new generation.
- Repository A invalidation does not affect Repository B.
- Repository deletion invalidates its entries.
- Existing incremental indexing remains correct.

---

# 7. R05 — Query-intent classification and adaptive RRF weights

## 7.1 Existing situation

`backend/ai/retrieval/fusion.py` already has:

- `detect_query_intent()`
- `fuse()`
- `fuse_adaptive()`

The current intent logic is relatively simple and recognizes symbol-like queries.

The current adaptive weights are:

```python
weights = [0.8, 1.4] if intent == "symbol" else [1.2, 0.9]
```

Improve this existing implementation instead of creating a parallel fusion system.

## 7.2 Required query-intent classes

Implement a lightweight rule-based classifier.

Required classes:

```text
exact_symbol
path_lookup
conceptual
debugging
impact_analysis
test_generation
```

Optional class:

```text
configuration_lookup
```

The classifier must not call an LLM.

It must be deterministic, fast, testable, and easy to extend.

## 7.3 Classification examples

| User query | Intent |
|---|---|
| `Where is getUserById defined?` | exact_symbol |
| `Find UserAuthenticationService` | exact_symbol |
| `Open src/auth/login.py` | path_lookup |
| `Which file contains the login route?` | conceptual |
| `Why does token refresh fail?` | debugging |
| `What functions call validate_user?` | impact_analysis |
| `Find all callers of create_session` | impact_analysis |
| `Generate tests for payment service` | test_generation |
| `What happens when payment verification fails?` | debugging |

Use clear precedence rules so one query is not unpredictably assigned to multiple classes.

For ambiguous queries, use a safe default such as `conceptual`.

## 7.4 Retriever-specific behavior

Intent should influence:

- Vector candidate count.
- Lexical candidate count.
- HNSW profile.
- RRF source weights.
- Graph expansion.
- Optional reranker candidate count.

Do not make every query use every expensive stage.

Example routing:

| Intent | Vector | Code lexical | Graph |
|---|---|---|---|
| exact_symbol | Yes | High priority | Optional |
| path_lookup | Optional | High priority | No |
| conceptual | High priority | Yes | Optional |
| debugging | Yes | Yes | Yes |
| impact_analysis | Yes | Yes | High priority |
| test_generation | Yes | Yes | Yes |

Do not disable a source without benchmark evidence.

## 7.5 Initial RRF weights

Use these as initial experimental values:

| Intent | Vector | Code lexical | Graph |
|---|---:|---:|---:|
| exact_symbol | 0.7 | 1.6 | 0.2 |
| path_lookup | 0.6 | 1.0 | 0.3 |
| conceptual | 1.4 | 0.7 | 0.5 |
| debugging | 1.2 | 1.0 | 1.0 |
| impact_analysis | 0.8 | 1.0 | 1.5 |
| test_generation | 1.0 | 1.2 | 1.2 |

These are initial hypotheses, not final optimized values.

If graph results are not integrated for a particular query, do not create a fake graph contribution.

Keep the source-weight configuration centralized and versioned.

## 7.6 RRF implementation requirements

Update:

`backend/ai/retrieval/fusion.py`

Requirements:

- Preserve the existing RRF formula.
- Preserve deduplication by chunk ID.
- Preserve stable ordering.
- Preserve the default `k=60` unless benchmark results justify a change.
- Support a variable number of sources.
- Validate weight count and values.
- Reject negative, non-finite, or invalid weights.
- Keep source weights explicit and testable.
- Record the intent and configuration version in bounded structured logs if useful.

Do not overwrite original retrieval-source scores in a way that makes debugging or benchmarking impossible.

Preserve source-specific scores in the chunk metadata or a compatible internal result structure.

---

# 8. R06 — Bounded symbol-graph expansion

## 8.1 Existing infrastructure

The repository already has:

```text
backend/app/models/symbol_edge.py
backend/app/repositories/symbol_edge_repository.py
```

The model stores:

- `repository_id`
- `source_symbol_id`
- `target_symbol_id`
- `edge_type`

The repository already has methods for outgoing and incoming edges.

Other services already use symbol edges, including bug detection, code review, explanation, and task context.

Do not introduce a new graph database.

Use the existing PostgreSQL symbol graph.

## 8.2 Objective

Improve retrieval for questions that require relationships between symbols.

Examples:

- Which functions call this function?
- What happens after login validation?
- Which components depend on this service?
- Where is this function used?
- Which functions may be affected by this change?
- Which files should be considered while generating tests?

## 8.3 Expansion design

Add a retrieval-specific graph expansion component.

Suggested module:

`backend/ai/retrieval/graph_expansion.py`

Responsibilities:

1. Receive the initial fused candidates.
2. Identify valid seed symbols.
3. Fetch bounded incoming and outgoing edges.
4. Apply query-intent-specific edge selection.
5. Resolve related symbol IDs to symbols and chunks.
6. Add related chunks as candidates.
7. Deduplicate candidates.
8. Preserve source attribution.
9. Return candidates for final fusion/reranking.

## 8.4 Expansion rules

Start with one-hop expansion.

Do not implement unlimited graph traversal.

Initial bounds:

```text
Maximum seed symbols: 5
Maximum hops: 1
Maximum related symbols per seed: 10
Maximum expanded chunks: 30
```

Treat these as configurable starting limits.

Use tighter limits if the database or repository size requires it.

## 8.5 Edge selection

Use query intent to choose edge direction.

| Intent | Preferred relationships |
|---|---|
| exact_symbol | limited callers/callees |
| conceptual | limited related symbols |
| debugging | incoming and outgoing calls |
| impact_analysis | incoming callers and dependency relationships |
| test_generation | relevant callers, callees, and test-related symbols |
| path_lookup | graph expansion generally unnecessary |

Only use edge types that the existing indexer actually produces.

Do not assume every edge type exists.

Inspect the symbol extraction and graph-building implementation before defining edge semantics.

## 8.6 Security and correctness

Every graph query must include `repository_id`.

Never traverse into symbols from another repository.

Do not return deleted or stale symbol records.

Deduplicate by symbol ID and chunk ID.

Do not treat graph relationships as proof of runtime behavior.

Graph-expanded results must be marked as graph-derived candidates internally.

## 8.7 Ranking

Graph-expanded candidates should participate in RRF with a graph source weight.

Do not automatically place every graph-expanded candidate above direct retrieval results.

Direct matches should remain competitive.

Graph expansion should improve recall, not flood the final context with unrelated code.

## 8.8 Failure behavior

If graph expansion fails:

- Preserve vector and lexical results.
- Log the failure.
- Continue retrieval.
- Do not fail the entire RAG request.

## 8.9 Required tests

- Incoming edge expansion.
- Outgoing edge expansion.
- Repository isolation.
- Missing symbol IDs.
- No-edge behavior.
- Duplicate symbols.
- Maximum seed limit.
- Maximum expanded candidate limit.
- One-hop bound.
- Query-intent-specific expansion.
- Graph failure fallback.
- Stale/deleted symbol handling.

---

# 9. R07 — Retrieval evaluation and benchmark suite

This is essential. Do not declare retrieval improvements successful based only on passing unit tests.

## 9.1 Existing benchmark situation

Inspect:

- `backend/tests/test_rag.py`
- `backend/scripts/benchmark_quality_suite.py`
- `backend/scripts/benchmark_rag.py`

The current benchmark coverage is not sufficient to prove that the new retrieval architecture improves retrieval quality across different repository types and query intents.

## 9.2 Build a benchmark dataset

Create a documented retrieval evaluation dataset containing approximately 150–300 questions.

Use multiple repositories or representative fixtures.

The dataset should cover:

| Category | Example |
|---|---|
| Exact symbol | Find `validate_user` |
| File path | Find the authentication route |
| Conceptual | Explain the login flow |
| Debugging | Why does token refresh fail? |
| Impact analysis | Which functions call this method? |
| Test generation | Which code should be tested for payment validation? |
| Cross-file | How does the API call reach the database? |
| Error handling | Where is this exception caught? |
| Configuration | Where is the database URL configured? |
| Security | Where are user permissions checked? |

Each benchmark item must have:

- Stable query ID.
- Repository/fixture ID.
- Query text.
- Query intent.
- Relevant chunk IDs or file/symbol ground truth.
- Relevance grade where appropriate.
- Notes explaining the expected evidence.

Do not fabricate ground truth.

Generate labels by inspecting the repository and manually validate them.

Do not let the retrieval implementation generate its own evaluation labels.

## 9.3 Metrics

Calculate:

### Recall@K

Measures whether relevant chunks appear in the first K results.

Required:

```text
Recall@5
Recall@10
Recall@20
Recall@30
```

### MRR

Measures how early the first relevant result appears.

### nDCG@K

Measures ranking quality when multiple relevant chunks have different relevance grades.

Required:

```text
nDCG@5
nDCG@8
nDCG@10
```

### Precision@K

Measures how many returned results are relevant.

### Latency

Measure:

```text
P50
P95
P99
```

Measure total retrieval latency and, where possible, individual stages in the benchmark harness.

Do not build a Prometheus/Grafana dashboard as part of this work.

## 9.4 Compare configurations

Run a controlled comparison:

```text
A. Existing vector retrieval
B. Existing lexical retrieval
C. Existing vector + lexical + RRF
D. New code-aware lexical retrieval
E. Adaptive HNSW
F. Query-intent-aware RRF
G. Graph expansion
H. Hybrid + reranker
I. Full proposed retrieval pipeline
```

Use the same benchmark dataset for every configuration.

Record:

- Retrieval configuration.
- Model version.
- Index generation.
- Database/pgvector version.
- Candidate limits.
- RRF weights.
- HNSW settings.
- Reranker configuration.
- Metrics.
- Runtime.

Do not compare runs with different ground-truth datasets.

## 9.5 Acceptance criteria

The final system should:

- Improve or preserve overall Recall@10.
- Improve exact-symbol retrieval compared with the old English-only lexical implementation.
- Improve impact-analysis retrieval when graph expansion is enabled.
- Avoid meaningful regressions in conceptual retrieval.
- Preserve repository isolation.
- Avoid increasing P95 latency beyond the agreed budget without a measured quality benefit.

Use the existing P95 target of 400 ms as a measurement target, not a claim that it is already achievable on every deployment.

Report actual measurements.

If quality and latency trade off, document the trade-off instead of hiding it.

## 9.6 Weight tuning

Use the benchmark to tune source weights.

A simple grid search is acceptable.

Do not tune against the final held-out test set.

Use:

```text
Training/tuning split
Validation split
Held-out test split
```

Version the final selected weight configuration.

Do not automatically deploy a new weight configuration without tests.

---

# 10. R08 — ONNX reranker evaluation

## 10.1 Existing reranker

The existing reranker is:

`backend/ai/retrieval/reranker.py`

Current model:

```text
cross-encoder/ms-marco-MiniLM-L-6-v2
```

It lazily loads a Sentence Transformers CrossEncoder and reranks the fused candidates.

Do not remove this implementation.

## 10.2 Objective

Evaluate whether ONNX Runtime can improve:

- CPU inference latency.
- Memory consumption.
- Model startup.
- Deployment footprint.

Do not assume ONNX is automatically faster.

Do not assume INT8 quantization preserves relevance.

## 10.3 Implementation

Create an experimental ONNX implementation separately:

```text
backend/ai/retrieval/reranker_onnx.py
backend/ai/retrieval/reranker_factory.py
```

Reuse the same model and tokenizer semantics.

Evaluate:

```text
PyTorch FP32
ONNX FP32
ONNX INT8
```

Keep the current PyTorch implementation as the fallback.

The factory should select the implementation through configuration.

Suggested settings:

```text
RERANKER_BACKEND=pytorch
RERANKER_ONNX_ENABLED=false
RERANKER_QUANTIZATION=none
```

Do not make ONNX the production default until the benchmark proves it is beneficial.

## 10.4 Fair comparison

Use the same:

- Model weights.
- Tokenizer.
- Input text.
- Query/chunk pairs.
- Maximum sequence length.
- Candidate count.
- Batch size.
- Hardware.
- Benchmark dataset.

Measure:

- nDCG@8.
- MRR.
- P95 reranker latency.
- Cold-start time.
- Peak memory.
- Model artifact size.
- CPU utilization where measurable.

## 10.5 Decision rule

Adopt ONNX only if it provides a meaningful deployment or performance benefit without unacceptable ranking degradation.

If the difference is negligible, keep PyTorch.

Do not introduce ONNX merely to add another technology.

---

# 11. Integration into the existing HybridRetriever

Update:

`backend/ai/retrieval/hybrid.py`

The intended final flow:

```text
                 User Query
                      |
                      v
             Query Intent Classifier
                      |
                      v
              Build Cache Key
                      |
                      v
                 Redis Cache
                 /         \
              HIT           MISS
               |              |
               |              v
               |       Select HNSW Profile
               |              |
               |              v
               |       Vector Retrieval
               |              |
               |       Code Lexical Retrieval
               |              |
               |              v
               |         Initial RRF
               |              |
               |              v
               |      Bounded Graph Expansion
               |              |
               |              v
               |        Final RRF Fusion
               |              |
               |              v
               |       Cross-Encoder Reranking
               |              |
               |              v
               |        Cache Final Results
               |              |
               +------+-------+
                      |
                      v
                 Final Top-K
                      |
                      v
                RAG Context Builder
```

Important implementation details:

- Do not execute graph expansion for every query unnecessarily.
- Keep vector and lexical retrieval concurrent where session ownership permits.
- Do not concurrently execute multiple operations on the same `AsyncSession`.
- The current application initialization passes `AsyncSessionLocal` into retrievers; preserve independent session creation where required.
- Preserve the existing `RetrievalUnavailableError` behavior.
- Preserve fallback when one retrieval source fails.
- If both primary sources fail, continue raising the existing retrieval-unavailable error.
- Graph failure must not fail the entire request.
- Redis failure must not fail the entire request.
- Reranker failure must preserve the existing fallback behavior.
- Keep the output compatible with the current RAG context builder.

Do not add a second RAG pipeline.

---

# 12. Configuration changes

Use the existing Pydantic settings architecture in:

`backend/app/core/config.py`

Add validated settings for the new features.

Suggested configuration:

```text
RETRIEVAL_CACHE_ENABLED=true
RETRIEVAL_CACHE_TTL_SECONDS=300

RETRIEVAL_HNSW_ENABLED=true
RETRIEVAL_HNSW_EXACT_EF_SEARCH=40
RETRIEVAL_HNSW_NORMAL_EF_SEARCH=64
RETRIEVAL_HNSW_COMPLEX_EF_SEARCH=120
RETRIEVAL_HNSW_ITERATIVE_SCAN=relaxed_order

RETRIEVAL_CODE_LEXICAL_ENABLED=true

RETRIEVAL_GRAPH_EXPANSION_ENABLED=true
RETRIEVAL_GRAPH_MAX_SEEDS=5
RETRIEVAL_GRAPH_MAX_HOPS=1
RETRIEVAL_GRAPH_MAX_NEIGHBORS_PER_SEED=10
RETRIEVAL_GRAPH_MAX_CANDIDATES=30

RETRIEVAL_INTENT_ROUTING_ENABLED=true

RERANKER_BACKEND=pytorch
RERANKER_ONNX_ENABLED=false
RERANKER_QUANTIZATION=none
```

Add settings for candidate counts and weight configuration if needed.

All settings must have:

- Sensible defaults.
- Validation.
- Clear documentation.
- Safe fallback behavior.

Do not place secrets or credentials in these settings.

Update `.env.example` or the repository's existing example configuration file.

Never overwrite the user's actual `.env`.

---

# 13. Database migrations and indexing safety

Before creating migrations:

1. Inspect the current Alembic head.
2. Inspect existing `code_chunks` columns and indexes.
3. Inspect existing repository and sync-job models.
4. Check whether an index-generation field already exists.
5. Check whether symbol metadata is available in the current schema.
6. Check PostgreSQL and pgvector compatibility.

Migrations must:

- Have a correct `down_revision`.
- Be reversible where practical.
- Avoid dropping existing indexes without justification.
- Avoid full-table destructive updates.
- Be safe for existing repositories.
- Support incremental rollout.

If adding code-search data to existing chunks, implement a controlled backfill.

The backfill must:

- Process data in batches.
- Be restartable.
- Avoid loading the entire repository corpus into memory.
- Preserve existing embeddings.
- Preserve existing chunk IDs.
- Report progress and failures.
- Avoid exposing secret content in logs.

Do not silently assume existing rows have the new searchable representation.

Do not enable the new lexical search path until the backfill and index are ready.

---

# 14. Documentation requirements

Create or update the following documentation.

```text
docs/
    retrieval/
        README.md
        retrieval-architecture.md
        code-aware-lexical-search.md
        adaptive-hnsw.md
        redis-retrieval-cache.md
        cache-invalidation-and-index-generation.md
        query-intent-and-rrf.md
        symbol-graph-expansion.md
        retrieval-benchmarking.md
        onnx-reranker-evaluation.md
        implementation-changelog.md
        future-enhancements.md
```

If the repository already has a documentation convention, use it rather than creating duplicate documentation structures.

## 14.1 Required documentation contents

### README.md

Explain:

- Current retrieval architecture.
- New retrieval architecture.
- Main components.
- Configuration.
- How to run tests.
- How to run benchmarks.
- Feature enable/disable switches.
- Known limitations.

### retrieval-architecture.md

Include:

- Existing architecture.
- New architecture.
- Component responsibilities.
- Data flow.
- Cache flow.
- Index update flow.
- Failure fallback flow.

### code-aware-lexical-search.md

Document:

- Why English-only FTS was insufficient.
- Identifier normalization.
- Database schema/index changes.
- Indexing behavior.
- Query behavior.
- Backfill procedure.
- Test results.

### adaptive-hnsw.md

Document:

- Existing HNSW index.
- Profile selection.
- pgvector version requirements.
- Transaction-local settings.
- Benchmark results.
- Final selected values.

### redis-retrieval-cache.md

Document:

- Cache interface.
- Key structure.
- Serialization.
- TTL.
- Failure behavior.
- Stampede protection.
- Security boundaries.

### cache-invalidation-and-index-generation.md

Document:

- Index generation.
- Commit/version tracking.
- Publication sequence.
- Invalidation triggers.
- Rollback behavior.
- Failure handling.

### query-intent-and-rrf.md

Document:

- Intent categories.
- Classification rules.
- Source selection.
- Initial weights.
- Final tuned weights.
- Benchmark evidence.

### symbol-graph-expansion.md

Document:

- Existing symbol graph schema.
- Edge types actually supported.
- Expansion rules.
- Limits.
- Security.
- Ranking.
- Failure fallback.

### retrieval-benchmarking.md

Document:

- Dataset structure.
- Dataset creation methodology.
- Ground-truth labels.
- Metrics.
- Baseline.
- Final comparison.
- Latency results.
- Limitations.

### onnx-reranker-evaluation.md

Document:

- Current PyTorch implementation.
- ONNX conversion approach.
- FP32/INT8 comparison.
- Accuracy results.
- Latency results.
- Memory results.
- Adoption decision.

### future-enhancements.md

Keep the following ideas for future reference only:

1. Zoekt integration.
2. Retrieval telemetry dashboard using Prometheus and Grafana.

For Zoekt, document:

- Why it could help exact code search.
- How it differs from PostgreSQL FTS and vector search.
- Possible integration architecture.
- Synchronization requirements.
- Storage/compute implications.
- Operational risks.
- Reasons it is not being implemented now.

For the telemetry dashboard, document:

- Possible retrieval metrics.
- Potential Prometheus/Grafana architecture.
- Potential dashboards.
- Privacy and cardinality concerns.
- Infrastructure requirements.
- Reasons it is not being implemented now.

**Do not implement either future enhancement.**

---

# 15. Testing strategy

Run the existing tests before changes and record the baseline.

Then add focused tests for each feature.

Required test files can include:

```text
backend/tests/test_code_tokenizer.py
backend/tests/test_code_lexical_retrieval.py
backend/tests/test_adaptive_hnsw.py
backend/tests/test_retrieval_cache.py
backend/tests/test_retrieval_cache_invalidation.py
backend/tests/test_query_intent.py
backend/tests/test_graph_expansion.py
backend/tests/test_retrieval_benchmark.py
backend/tests/test_reranker_onnx.py
```

Use existing naming and test conventions where possible.

Do not duplicate existing tests unnecessarily.

### Regression tests

Verify that:

- Existing vector retrieval still works.
- Existing lexical retrieval remains compatible.
- Existing RRF behavior remains compatible.
- Existing reranker behavior remains compatible.
- Existing RAG pipeline still returns valid results.
- Repository access boundaries remain enforced.
- Redis outage does not break retrieval.
- Graph failure does not break retrieval.
- One retrieval source failing still permits the other source to work.
- Both primary sources failing still produces the expected retrieval-unavailable behavior.
- Existing indexing and re-indexing still work.
- Existing secret redaction is preserved.
- No unrelated feature is broken.

### Commands

Use the project's actual test environment and dependency instructions.

At minimum, run the relevant test modules:

```bash
pytest backend/tests/test_hybrid_retrieval.py -v
pytest backend/tests/test_vector_retrieval.py -v
pytest backend/tests/test_rag.py -v
```

Run the new focused tests.

Then run the broader backend test suite, or the widest feasible suite in the available environment.

Run formatting, linting, and type checks using the repository's configured tools.

Do not claim tests passed if they were not executed.

If database-backed tests require PostgreSQL/pgvector and the environment does not provide it, report that limitation explicitly and separate mocked tests from real integration tests.

---

# 16. Performance and cost constraints

The project should reuse existing infrastructure:

- Existing PostgreSQL/Supabase database.
- Existing pgvector extension and HNSW index.
- Existing Redis/Upstash connection.
- Existing embedding service.
- Existing cross-encoder model unless ONNX proves better.

Do not introduce:

- A new managed vector database.
- A separate search server.
- A new paid embedding API.
- A paid reranking API.
- A mandatory new cloud service.

### Expected cost approach

| Improvement | Expected additional infrastructure |
|---|---|
| Code-aware lexical retrieval | Existing PostgreSQL; index storage increases |
| Adaptive HNSW | Existing PostgreSQL; query CPU can increase |
| Redis result cache | Existing Redis; memory/command usage increases |
| Index generation | Existing PostgreSQL and Redis |
| Query intent/RRF | Negligible compute |
| Graph expansion | Existing PostgreSQL; additional bounded queries |
| Benchmark suite | Development/test compute |
| ONNX evaluation | Development/test CPU and temporary model artifacts |

Do not promise zero cost. Measure actual Redis memory, PostgreSQL storage, and CPU usage where available.

Keep cache limits and graph limits conservative for the current deployment.

---

# 17. Implementation sequence

Implement in dependency order.

## Phase 0 — Audit and baseline

- Inspect the existing architecture.
- Record the current test baseline.
- Record current retrieval benchmark results.
- Confirm PostgreSQL/pgvector version.
- Confirm Redis configuration.
- Inspect indexing and symbol graph lifecycle.
- Write a short implementation plan.

Do not start large code changes until this audit is complete.

## Phase 1 — Code-aware lexical retrieval

- Implement tokenizer.
- Add searchable representation.
- Add migration/index.
- Update incremental indexer.
- Implement code-aware lexical SQL.
- Backfill existing chunks.
- Add tests.
- Compare against old lexical retrieval.

## Phase 2 — Adaptive HNSW

- Implement query profile selection.
- Add transaction-local HNSW settings.
- Add version compatibility handling.
- Add tests.
- Benchmark recall and latency.

## Phase 3 — Query intent and RRF

- Implement rule-based intent classifier.
- Add source profiles.
- Extend RRF configuration.
- Preserve existing fusion behavior.
- Add tests.
- Tune initial weights against the benchmark.

## Phase 4 — Symbol graph expansion

- Inspect supported edge types.
- Implement bounded one-hop expansion.
- Integrate graph candidates into fusion.
- Add tests.
- Benchmark impact-analysis and debugging queries.

## Phase 5 — Redis cache and invalidation

- Implement cache key builder.
- Implement serialization.
- Implement asynchronous Redis cache.
- Integrate into HybridRetriever.
- Implement index generation.
- Integrate generation publication with indexing.
- Add invalidation.
- Add failure handling and tests.

Do not enable caching before generation-based correctness is ready.

## Phase 6 — Benchmark and tune

- Build the 150–300 query dataset.
- Run baseline.
- Run each individual improvement.
- Run the complete pipeline.
- Tune candidate counts and weights.
- Record results.
- Fix regressions.

## Phase 7 — ONNX evaluation

- Export model.
- Evaluate ONNX FP32.
- Evaluate ONNX INT8.
- Compare against PyTorch.
- Keep PyTorch unless ONNX demonstrates a measurable benefit.

## Phase 8 — Documentation and final verification

- Complete all required documentation.
- Update environment examples.
- Run tests.
- Run migrations in a test environment.
- Verify incremental indexing.
- Verify cache invalidation.
- Verify fallback behavior.
- Prepare a final implementation report.

---

# 18. Definition of done

The task is not complete until all applicable requirements below are satisfied.

## Functionality

- [ ] Code-aware lexical retrieval works.
- [ ] Exact identifiers are searchable.
- [ ] File paths contribute to lexical retrieval.
- [ ] Existing natural-language search remains functional.
- [ ] Adaptive HNSW profiles work.
- [ ] HNSW settings are transaction-local.
- [ ] Query-intent classification works.
- [ ] RRF uses configurable intent-specific weights.
- [ ] Symbol graph expansion is bounded and repository-scoped.
- [ ] Redis retrieval-result caching works asynchronously.
- [ ] Cache serialization is safe and versioned.
- [ ] Cache invalidation is generation-aware.
- [ ] Failed indexing cannot publish a new active generation.
- [ ] Redis failure gracefully bypasses the cache.
- [ ] ONNX has been evaluated against the existing reranker.
- [ ] PyTorch fallback remains available.

## Quality and security

- [ ] Repository isolation is enforced at every retrieval source.
- [ ] Tenant/access scope is part of cache isolation.
- [ ] No unsafe pickle deserialization is used.
- [ ] No secret content is introduced into search metadata or logs.
- [ ] No unbounded graph traversal exists.
- [ ] No unbounded Redis key scan exists.
- [ ] No unbounded cache payload exists.
- [ ] Existing error-handling behavior is preserved.
- [ ] Existing RAG consumers remain compatible.

## Evaluation

- [ ] Benchmark dataset is documented.
- [ ] Ground truth is validated.
- [ ] Recall@K is reported.
- [ ] MRR is reported.
- [ ] nDCG@K is reported.
- [ ] P50/P95/P99 latency is reported.
- [ ] Baseline and final results are compared.
- [ ] Regressions are explained.
- [ ] Final weights and HNSW profiles are evidence-based.

## Exclusions

- [ ] Zoekt is not implemented.
- [ ] Prometheus/Grafana dashboard is not implemented.
- [ ] Both are documented under future enhancements only.
- [ ] No unnecessary external infrastructure has been introduced.

---

# 19. Required final report from you

After implementation, provide a detailed report with these sections:

1. **Initial audit findings**
   - What existed before.
   - What was missing.
   - Any architecture discrepancies discovered.

2. **Files created**
   - Exact paths.
   - Purpose of each file.

3. **Files modified**
   - Exact paths.
   - What changed and why.

4. **Database changes**
   - Migration IDs.
   - New columns.
   - New indexes.
   - Backfill details.
   - Rollback instructions.

5. **Retrieval architecture**
   - Final architecture diagram.
   - Data flow.
   - Failure fallback behavior.

6. **Cache implementation**
   - Key structure.
   - TTL.
   - Serialization.
   - Invalidation.
   - Generation behavior.
   - Redis failure behavior.

7. **Retrieval quality**
   - Benchmark dataset details.
   - Baseline metrics.
   - Final metrics.
   - Exact-symbol performance.
   - Conceptual-query performance.
   - Impact-analysis performance.

8. **Performance**
   - Actual P50/P95/P99.
   - HNSW profile comparison.
   - Cache hit/miss test results.
   - Reranker comparison.

9. **Tests**
   - Commands executed.
   - Passed tests.
   - Failed tests.
   - Skipped tests.
   - Tests not run and why.

10. **Configuration**
    - New environment variables.
    - Defaults.
    - Production recommendations.

11. **Deployment and migration instructions**
    - Required migration order.
    - Backfill order.
    - Feature flags.
    - Safe rollout and rollback.

12. **Documentation**
    - Exact documentation paths created or updated.

13. **Deferred features**
    - Confirm Zoekt and telemetry dashboard are documentation-only.

14. **Remaining risks**
    - Any unresolved issue.
    - Any unverified assumption.
    - Any follow-up work.

Never claim that a feature is complete merely because a file was created.

Never claim a benchmark passed without actual benchmark execution.

Never fabricate performance numbers.

If something cannot be implemented or verified, explain precisely why and provide the remaining steps.

---

# 20. Final instruction

Work directly in the existing repository.

First inspect and understand. Then implement in phases.

Prefer small, testable changes over a large rewrite.

Preserve current behavior and compatibility.

Do not implement Zoekt or the telemetry dashboard.

Do not introduce paid services or unnecessary infrastructure.

Prioritize retrieval correctness, security, relevance, and measured performance over adding technologies.

The final result must be production-oriented, documented, tested, and maintainable.