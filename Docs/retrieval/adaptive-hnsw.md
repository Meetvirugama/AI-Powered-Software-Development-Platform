# Adaptive HNSW Retrieval Settings

## 1. Motivation

PostgreSQL `pgvector` HNSW indexes use `hnsw.ef_search` to control the trade-off between search speed and recall during vector nearest-neighbor traversal. Static `ef_search` values either waste compute on simple queries or suffer poor recall on complex, multi-hop reasoning tasks.

## 2. Intent-Driven HNSW Profiles

The retriever resolves an adaptive HNSW profile for each query:

| Profile | Target Intents | `ef_search` | `iterative_scan` | Rationale |
|---|---|---:|---|---|
| `exact` | `exact_symbol`, `path_lookup` | 40 | `relaxed_order` | Symbol matches rely primarily on lexical retrieval; lower vector search depth saves latency |
| `normal` | `conceptual`, `configuration_lookup` | 80 | `relaxed_order` | Balanced semantic search depth for general conceptual questions |
| `complex` | `debugging`, `impact_analysis`, `test_generation` | 160 | `relaxed_order` | High-depth graph scan maximizing semantic recall across disparate code patterns |

## 3. Safe Execution & Fallbacks

Before running the vector cosine search query, the retriever applies session settings:

```sql
SET LOCAL hnsw.ef_search = :ef_search;
SET LOCAL hnsw.iterative_scan = :iterative_scan;
```

Each `SET LOCAL` statement is executed in an isolated try/except block. On unsupported database engines (e.g., SQLite in-memory CI runners or older pgvector releases lacking `iterative_scan`), the retriever logs a debug warning and proceeds with default index settings without failing the request.
