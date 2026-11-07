# Cache Invalidation and Index Versioning

## 1. The Cache Invalidation Problem

When code files are modified, added, or deleted, cached retrieval results can serve stale chunks. TTL expiration alone is insufficient because stale chunks could be served within the TTL window.

## 2. Generation-Based Invalidation

To guarantee instantaneous correctness without complex distributed locks:
- The `repositories` table includes `active_index_generation` (integer, default 0) and `active_commit_sha`.
- Every cache key includes `active_index_generation`.
- When an index generation increments from $N$ to $N+1$, all previous cache keys for generation $N$ become immediately unreachable.

## 3. Atomic Promotion on Sync Completion

`IncrementalIndexer` processes sync jobs atomically:
1. Ingests modified and deleted files.
2. Extracts code symbols, builds chunks, and generates embeddings and symbol edges.
3. Upon full sync validation, right before transaction commit, advances `active_index_generation = active_index_generation + 1`.
4. Commits the transaction.
5. In the post-commit phase, asynchronously invalidates old Redis cache keys.

If indexing fails or rolls back, `active_index_generation` is never published.

## 4. Cursor-Based Redis Invalidation

When explicit invalidation is triggered (repository deletion, manual re-indexing, or background eviction):
- The cache executes `client.scan_iter(match=f"retrieval:v2:*:{repo_id}:*", count=100)`.
- Keys are batched and deleted in non-blocking chunks.
- The blocking, dangerous `KEYS` command is strictly banned in production.
- Invalidation is strictly scoped to the target repository; Repository A invalidation never affects Repository B.
