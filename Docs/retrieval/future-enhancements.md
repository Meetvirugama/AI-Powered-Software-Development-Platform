# Future Retrieval Enhancements (Deferred Architectural Scope)

As outlined in the retrieval improvement plan (`task.md` §1.2 and §14.1), the following capabilities are documented for future evaluation and are explicitly excluded from the current runtime implementation:

---

## 1. Zoekt Integration (Trigram Code Search Engine)

### Overview
Zoekt is an open-source, trigram-based full-text code search engine originally developed by Google and adopted by Sourcegraph. It compiles an inverted index of trigrams specifically optimized for regular expression matching and exact identifier lookups across massive git repositories.

### Architectural Fit
In a future phase, Zoekt could serve as a high-speed lexical search tier alongside PostgreSQL FTS:
- **Pros**: Sub-millisecond substring and regex queries across tens of gigabytes of source code; line-number and column-exact matches.
- **Cons**: Requires a dedicated Go-based daemon process, separate disk-based index files (`.zoekt`), index synchronization lifecycle management, and additional operational complexity.

### Integration Blueprint (Deferred)
```text
HybridRetriever
     │
     ├── VectorRetriever (pgvector HNSW)
     ├── LexicalRetriever (PostgreSQL simple FTS)
     ├── [Future] ZoektRetriever (gRPC/HTTP daemon client)
     └── RRFFusion
```

---

## 2. Prometheus & Grafana Telemetry Dashboards

### Overview
Dedicated metrics collection and monitoring dashboards for retrieval health and latency percentiles.

### Proposed Metrics (Deferred)
- `retrieval_query_total{intent="exact_symbol|..."}`: Counter of total queries processed per intent class.
- `retrieval_latency_seconds{stage="vector|lexical|fusion|graph|rerank"}`: Histogram tracking latency per pipeline stage.
- `retrieval_cache_hits_total`: Counter tracking Redis cache hits vs misses.
- `retrieval_graph_expansion_count`: Histogram of expanded symbol nodes.

### Rationale for Current Deferral
Existing stage metrics in `AnalysisRun.result_payload["stage_metrics"]` and structured application logs provide sufficient real-time observability without adding external time-series database infrastructure.
