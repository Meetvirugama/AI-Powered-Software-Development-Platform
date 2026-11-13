# Retrieval Cache Architecture: Current State & Multi-Worker Gaps

> **Project:** AI-Powered Software Development Platform  
> **Component:** Multi-Stage Retrieval Engine & Retrieval Latency Optimizer  
> **Status:** Architecture Audit & Phase 0 Baseline  
> **Related Issue:** [#218](https://github.com/Meetvirugama/AI-Powered-Software-Development-Platform/issues/218)

---

## 1. Executive Summary

This document presents the Phase 0 audit of the existing query caching, latency optimization, and token budget infrastructure. The platform currently features two separate caching implementations:
1. **In-Memory LRU Cache (`LRUQueryCache` in `backend/ai/services/retrieval_optimizer.py`):** An in-process, sub-millisecond query cache used by `RetrievalLatencyOptimizer` to meet the strict `P95 < 400ms` SLO.
2. **Redis Result Cache (`RetrievalResultCache` in `backend/ai/retrieval/cache.py`):** An asynchronous Redis cache utilized by `HybridRetriever` for multi-stage hybrid search results.

While each mechanism performs well in isolation, they are disconnected. In multi-worker deployments (e.g. running multiple Uvicorn/FastAPI workers or background task processors), in-memory cache entries are not shared, resulting in redundant embedding computations and database queries. Furthermore, cache invalidation upon repository synchronization requires formal index-version coordination across all worker instances.

```mermaid
flowchart TD
    subgraph Multi-Worker Environment (Current State)
        Worker1["FastAPI Worker 1"] --> LRU1["Local LRU Cache 1<br/>(Process Memory)"]
        Worker2["FastAPI Worker 2"] --> LRU2["Local LRU Cache 2<br/>(Process Memory)"]
        WorkerN["Background Worker N"] --> LRUN["Local LRU Cache N<br/>(Process Memory)"]
        
        LRU1 -.->|Not Shared| LRU2
        LRU2 -.->|Not Shared| LRUN
    end

    subgraph Independent Redis Result Cache
        Worker1 -.->|Async Round-Trip| Redis[(Redis Server)]
        Worker2 -.->|Async Round-Trip| Redis
        WorkerN -.->|Async Round-Trip| Redis
    end

    subgraph Data Stores
        Worker1 --> DB[(PostgreSQL + pgvector)]
        Worker2 --> DB
        WorkerN --> DB
    end
```

---

## 2. Audit of Existing Components

### 2.1 `LRUQueryCache` (`retrieval_optimizer.py`)

- **Implementation:** `collections.OrderedDict[str, tuple[float, Any]]` tracking insert timestamp and value.
- **Key Hashing:** SHA-256 of stringified key `_hash_key(self, key)`.
- **Eviction & Expiration:**
  - TTL expiration checked on `get()`: entries older than `ttl_seconds` (default: 300s) are evicted as cache misses.
  - Least-Recently-Used eviction when `len(_cache) > maxsize` (default: 256) via `popitem(last=False)`.
  - Cache hits reposition entries using `move_to_end()`.
- **Metrics:** Tracks internal counters for `hits`, `misses`, and `size`.
- **Strengths:** Microsecond latency (< 0.1ms), zero network overhead, no external dependencies.
- **Limitations:** Isolated to a single Python process. Does not know about repository ID or repository index updates.

### 2.2 `RetrievalLatencyOptimizer` (`retrieval_optimizer.py`)

- **Optimization Loop:** `execute_optimized_retrieval(query, retrieval_fn, use_cache=True)`:
  - Cache hits artificially record `0.5ms` latency.
  - Cache misses record `time.perf_counter()` duration of `retrieval_fn(query)` and populate `self.cache`.
- **Latency Percentiles:** Computes exact `P50`, `P90`, `P95`, `P99`, `min`, `max`, and `avg` latencies.
- **SLO Verification:** Enforces `target_met = (p95 <= 400.0)` ms.
- **Concurrent Dispatch:** `execute_concurrent_search` dispatches vector and lexical queries to a `ThreadPoolExecutor` to eliminate serial overhead.

### 2.3 `AgentTokenBudgetManager` (`retrieval_optimizer.py`)

- **Ceilings:** Enforces `max_budget_tokens` (default: 30,000) and `max_step_tokens` (default: 4,000).
- **Estimation:** Standardized ~4 characters per token heuristic (`ceil(len(text) / 4.0)`).
- **Enforcement:** `consume()` raises `TokenBudgetExhaustedError` if consumption exceeds ceiling.
- **Safe Truncation:** `truncate_to_budget()` truncates text to fit within remaining headroom with standard truncation marker.

### 2.4 `RetrievalResultCache` (`backend/ai/retrieval/cache.py`)

- **Implementation:** Asynchronous client wrapper around `redis.asyncio.Redis`.
- **Serialization:** Safe JSON serialization in `cache_serialization.py` using `CURRENT_SCHEMA_VERSION = "2.0"` and schema validation.
- **Payload Limits:** Skips caching payloads exceeding `retrieval_cache_max_payload_bytes` (500 KB).
- **Invalidation:** Repository-scoped invalidation using `client.scan_iter(match=f"retrieval:v2:*:{repo_str}:*", count=100)`.
- **Stampede Guard:** `acquire_stampede_lock(key, ttl_seconds)` uses atomic `NX` keys with UUID ownership tokens to coordinate concurrent cache misses.

---

## 3. Technical Gaps & Multi-Worker Inefficiencies

| Dimension | In-Memory LRU (`LRUQueryCache`) | Redis Cache (`RetrievalResultCache`) | Gap / Problem |
|---|---|---|---|
| **Scope** | Single Worker Process | Shared across all instances | Multiple backend workers cannot reuse each other's warm cache entries. |
| **Lookup Speed** | < 0.1 ms | 2 – 10 ms (network RTT) | Checking Redis on every single call adds network round-trips for hot local loops. |
| **Repo Invalidation** | Manual / Process-local | Key scanning via `scan_iter` | When sync finishes, only the worker that ran sync knows about it unless coordinated via Redis. |
| **Index Versioning** | Untracked (raw query key) | Parameter `index_generation` | No dynamic resolution of active repository index version from database/Redis. |
| **Resilience** | 100% resilient (in-memory) | Fails gracefully to None | Lack of unified two-level coordinator where Redis failure seamlessly falls back to LRU. |

---

## 4. Proposed Two-Level (L1 / L2) Architecture

To achieve the speed of in-memory caching with the consistency and multi-worker sharing of Redis:

```mermaid
flowchart TD
    Req["Retrieval Query (query, repo_id)"] --> L1{"L1: Local LRU Cache<br/>(In-Memory)"}
    
    L1 -->|L1 Hit<br/>(< 0.5ms)| ReturnResult["Return Results"]
    
    L1 -->|L1 Miss| RedisCheck{"Redis Enabled &<br/>Connected?"}
    
    RedisCheck -->|No / Offline| DirectRetrieval["Execute Retrieval Pipeline"]
    RedisCheck -->|Yes| L2{"L2: Redis Query Cache<br/>(Key: repo_id:index_version:query_hash)"}
    
    L2 -->|L2 Hit<br/>(2 - 5ms)| PopulateL1["Populate L1 Local Cache"]
    PopulateL1 --> ReturnResult
    
    L2 -->|L2 Miss| StampedeLock{"Acquire Stampede Lock?<br/>(nx=True, ttl=5s)"}
    
    StampedeLock -->|Lock Won| DirectRetrieval
    StampedeLock -->|Lock Held by Other| WaitBriefly["Wait / Fallback to Retrieval"]
    WaitBriefly --> DirectRetrieval
    
    DirectRetrieval --> SaveL2["Write to L2 Redis Cache<br/>(TTL: 600s)"]
    SaveL2 --> SaveL1["Write to L1 Local Cache<br/>(TTL: 300s)"]
    SaveL1 --> ReturnResult
```

### Key Behavioral Invariants:
1. **L1 Local-First:** Frequently accessed queries are resolved in-memory with near-zero latency, preserving the `P95 < 400ms` SLO.
2. **L2 Shared Fallback:** Uncached local queries check Redis, instantly benefiting from warm caches populated by sibling workers.
3. **Fail-Safe Graceful Fallback:** Any Redis connection timeout, disconnect, or serialization failure logs a warning and falls back to local retrieval without throwing exceptions.
4. **Versioned Key Isolation:** Invalidation increments the repository's index version; queries automatically compute keys using the new version, rendering obsolete entries instantly unreachable.
