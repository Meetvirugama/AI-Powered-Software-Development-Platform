# Redis-Based Asynchronous Retrieval Cache

## 1. Overview

The `RetrievalResultCache` (`backend/ai/retrieval/cache.py`) provides multi-worker asynchronous caching using the platform's shared Redis client (`backend/app/core/redis.py`).

## 2. Cache Key Design

Keys are deterministic, collision-resistant SHA-256 hashes containing all variables that impact retrieval results:

```text
retrieval:v2:{scope}:{repository_id}:{index_generation}:{query_hash}
```

Components included in `query_hash`:
- Normalized query string (lowercase, trimmed, collapsed whitespace)
- Query intent class
- Candidate limits (`top_k`, `vector_top_k`, `lexical_top_k`)
- Component versions (`embedding_version`, `chunker_version`, `tokenizer_version`, `retrieval_version`, `rrf_version`, `reranker_version`)

**Security Note**: Raw source code and sensitive query text are never stored in Redis key names.

## 3. Serialization & Limits

- Format: Versioned JSON (`CURRENT_SCHEMA_VERSION = "2.0"`). Unsafe pickle is prohibited.
- Size Limits: `RETRIEVAL_CACHE_MAX_PAYLOAD_BYTES` (default 500 KB). Chunks exceeding payload limits bypass the cache to protect Redis memory.
- Default TTL: 300 seconds (configurable via `RETRIEVAL_CACHE_TTL_SECONDS`).

## 4. Concurrency & Stampede Lock

To prevent cache stampedes when multiple workers simultaneously execute the same uncached query:
- A short-lived distributed lock (`lock:{key}`) with an automatic 5-second TTL can be acquired via `acquire_stampede_lock()`.
- Ownership verification ensures only the acquiring worker releases the lock via `release_stampede_lock()`.

## 5. Resilience

A cache failure is never a retrieval failure. Redis timeouts, connection drops, or deserialization errors log a warning and fall back directly to database retrieval.
