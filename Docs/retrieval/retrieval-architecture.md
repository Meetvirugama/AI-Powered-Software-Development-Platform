# End-to-End Hybrid Retrieval Architecture

## 1. Overview

The retrieval system combines dense semantic vector search (pgvector HNSW), code-aware lexical search (PostgreSQL simple tsvector with code tokenization), bounded graph expansion (PostgreSQL symbol edges), reciprocal rank fusion (RRF with query-intent source weights), asynchronous Redis result caching, and cross-encoder reranking.

```text
                 User Query
                      │
                      ▼
             Query Intent Classifier
                      │
                      ▼
               Build Cache Key
                      │
                      ▼
                 Redis Cache
                 /         \
              HIT           MISS
               │              │
               │              ▼
               │       Select HNSW Profile
               │              │
               │              ▼
               │       Vector Retrieval
               │              │
               │       Code Lexical Retrieval
               │              │
               │              ▼
               │         Initial RRF
               │              │
               │              ▼
               │      Bounded Graph Expansion
               │              │
               │              ▼
               │        Final RRF Fusion
               │              │
               │              ▼
               │       Cross-Encoder Reranking
               │              │
               │              ▼
               │        Cache Final Results
               │              │
               +──────┬───────+
                      │
                      ▼
                  Final Top-K
```

## 2. Pipeline Sequence

1. **Query Intent Classification**: Fast rule-based categorization into canonical intents: `exact_symbol`, `path_lookup`, `conceptual`, `debugging`, `impact_analysis`, `test_generation`, `configuration_lookup`.
2. **Cache Key Construction**: Deterministic hashing of scope, repository ID, active index generation, normalized query, intent, limits, and component versions.
3. **Redis Cache Lookup**: On hit, deserializes cached `CodeChunk` list and bypasses downstream database queries.
4. **HNSW Profile Selection**: Tunes PostgreSQL `hnsw.ef_search` and `hnsw.iterative_scan` based on query intent.
5. **Concurrent Retrieval**: `asyncio.gather` executes vector similarity and code lexical search concurrently. If one fails, the other serves as a fallback.
6. **Initial Reciprocal Rank Fusion**: RRF aggregates candidates with intent-specific weights ($k=60$).
7. **Bounded Graph Expansion**: Extracts seed symbols from top candidates and retrieves 1-hop related code chunks via `symbol_edges`.
8. **Final RRF Fusion**: Incorporates graph candidates with intent-specific graph source weights.
9. **Cross-Encoder Reranking**: Cross-encoder scores query-document pairs jointly, sorting final results by logit.
10. **Result Caching**: Asynchronously serializes top-K candidates into Redis with generation-bound TTL.
