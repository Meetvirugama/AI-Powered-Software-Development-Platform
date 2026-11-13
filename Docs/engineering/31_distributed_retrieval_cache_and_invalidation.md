# Distributed Retrieval Cache & Version-Aware Invalidation

> **Document ID:** ENG-31  
> **Status:** Production Implementation  
> **Author:** Meet  
> **Date:** 2026-11-13  
> **Related ADR:** ADR-018  
> **Related Issue:** [#218](https://github.com/Meetvirugama/AI-Powered-Software-Development-Platform/issues/218)

---

## 1. Context & Architecture

In high-concurrency environments with multiple FastAPI workers and Celery background workers, repeated hybrid retrieval queries across codebases generate heavy database load and redundant embedding inferences. 

This engineering document outlines the **Two-Level Hierarchical Query Caching Architecture** introduced in Feature 37:
1. **L1 Local In-Memory Cache:** Python process memory LRU cache providing microsecond response times for hot local loops.
2. **L2 Shared Redis Cache:** Distributed key-value cache allowing workers to share warm retrieval results across nodes.
3. **Versioned Key Partitioning:** Invalidation strategy utilizing repository commit tokens to eliminate stale retrieval results across workers.

```mermaid
flowchart TD
    Client["Client / Agent Analysis"] --> Opt["RetrievalLatencyOptimizer<br/>(execute_optimized_retrieval_async)"]
    
    Opt --> L1{"L1: Local In-Memory LRU<br/>(InMemoryRetrievalCache)"}
    L1 -->|Hit (< 0.2ms)| Return["Return Retrieval Results"]
    
    L1 -->|Miss| L2{"L2: Distributed Redis<br/>(RedisRetrievalCache)"}
    L2 -->|Hit (2-3ms)| Backfill["Populate L1 Local Memory"]
    Backfill --> Return
    
    L2 -->|Miss| StampedeLock{"Stampede Lock?<br/>(nx=True, ttl=5s)"}
    StampedeLock --> Search["Hybrid Retrieval Engine<br/>(pgvector dense + BM25 lexical + RRF)"]
    Search --> Store["Write to L2 (Redis) & L1 (LRU)"]
    Store --> Return
```

---

## 2. Key Components & Implementation

### 2.1 Cache Abstraction (`backend/ai/retrieval/cache.py`)

- **`RetrievalCache` (ABC):** Defines `get()`, `set()`, `delete()`, and `invalidate_repository()`.
- **`InMemoryRetrievalCache`:** Implements `RetrievalCache` over `LRUQueryCache`. Synchronous and asynchronous methods supported.
- **`RedisRetrievalCache` / `RetrievalResultCache`:** Implements `RetrievalCache` over `redis.asyncio.Redis` with safe JSON serialization, payload size checks (max 500 KB), and non-blocking `scan_iter` cursor invalidation.
- **`TwoLevelRetrievalCache`:** High-level coordinator implementing local-first lookup, Redis fallback, backfilling, and version-aware invalidation.
- **`get_retrieval_cache()`:** Process-wide factory returning the configured cache coordinator or standalone memory cache.

### 2.2 Deterministic Key Hashing & Index Versioning (`backend/ai/retrieval/cache_keys.py`)

- **Cache Key Schema:** `retrieval:v2:{scope}:{repo_id}:{index_version}:{query_hash}`
- **Query Hashing:** Computes deterministic SHA-256 over canonical JSON `{ "q": normalized_query, "cfg": sorted_config }`.
- **Index Version Resolution:** Queries Redis pointer `retrieval:repo_index_version:{repo_id}`. Defaults to target commit SHA or `"v1"` if Redis is absent.

### 2.3 Safe Serialization (`backend/ai/retrieval/cache_serialization.py`)

- Schema version: `"2.0"`.
- Validates payload envelope, timestamps, and data types.
- Supports both typed `CodeChunk` lists and generic retrieval result dictionaries.
- Strictly avoids `pickle` in favor of standard JSON serialization.

### 2.4 Invalidation Hook (`backend/app/services/sync_worker.py`)

- In Step 9 of the repository synchronization pipeline, immediately following `db.commit()` marking the repository as `SYNCED`, the sync worker triggers:
  ```python
  await cache.invalidate_repository(repository_id, new_index_version=target_commit_sha)
  ```
- This atomically updates the index version pointer in Redis and schedules cursor-based deletion of old keys.

---

## 3. Resilience & Degradation Guarantees

1. **Redis Down / Connection Dropped:**
   - All Redis operations are wrapped in defensive try/except blocks.
   - Failures log structured warnings and return `None` (on read) or `False` (on write).
   - Invalidation errors do not prevent repository sync jobs from succeeding.
   - Retrieval queries continue uninterrupted using local memory and direct database search.
2. **SLO Verification:**
   - Latency optimizer records separate measurements for L1 hits, L2 hits, and full searches.
   - P95 latency remains well below the `< 400ms` SLO threshold.
3. **Token Budgets:**
   - Caching operates strictly within token budget ceilings enforced by `AgentTokenBudgetManager`.

---

## 4. Verification & Testing

Validated across 84 tests in the test suite:
- `backend/tests/test_distributed_retrieval_cache_f37.py` (18 tests)
- `backend/tests/test_retrieval_cache.py` (9 tests)
- `backend/tests/test_retrieval_cache_invalidation.py` (4 tests)
- `backend/tests/test_meet_w3_all_days.py -k Day6` (3 tests)
- `backend/tests/test_hybrid_retrieval.py` (50 tests)

All tests passed with zero regressions.
