# Retrieval Optimization & Architecture Guide (F07 / #187)

This directory documents the production retrieval architecture for the AI-Powered Software Development Platform, implementing Issue #187 (F07: Improve code retrieval with hybrid search, graph expansion, and evaluation).

## Documentation Sitemap

| Document | Topic |
|---|---|
| [retrieval-architecture.md](retrieval-architecture.md) | High-level hybrid retrieval flow, component pipeline, and sequence diagrams |
| [code-aware-lexical-search.md](code-aware-lexical-search.md) | Code tokenizer, identifier splitting, GIN index, and tsquery generation |
| [adaptive-hnsw.md](adaptive-hnsw.md) | Adaptive HNSW profiles (`ef_search`, `iterative_scan`) based on query intent |
| [redis-retrieval-cache.md](redis-retrieval-cache.md) | Asynchronous Redis caching, deterministic key hashing, and stampede mitigation |
| [cache-invalidation-and-index-generation.md](cache-invalidation-and-index-generation.md) | Atomic index generation versioning and safe cursor-based cache invalidation |
| [query-intent-and-rrf.md](query-intent-and-rrf.md) | Deterministic rule-based intent classification and adaptive RRF weighting |
| [symbol-graph-expansion.md](symbol-graph-expansion.md) | Bounded 1-hop PostgreSQL symbol graph expansion with strict repository isolation |
| [retrieval-benchmarking.md](retrieval-benchmarking.md) | 150-query ground-truth benchmark suite, evaluation metrics, and harness |
| [onnx-reranker-evaluation.md](onnx-reranker-evaluation.md) | ONNX Runtime cross-encoder evaluation, factory pattern, and fallbacks |
| [future-enhancements.md](future-enhancements.md) | Architectural roadmap for deferred features (Zoekt integration & Prometheus/Grafana) |

## Quick Reference

- **Retriever Pipeline**: `backend.ai.retrieval.HybridRetriever`
- **Code Tokenizer**: `backend.ai.retrieval.code_tokenizer`
- **Adaptive Vector Search**: `backend.ai.retrieval.vector.VectorRetriever`
- **Intent & Fusion**: `backend.ai.retrieval.fusion.RRFFusion`
- **Graph Expansion**: `backend.ai.retrieval.graph_expansion.SymbolGraphExpander`
- **Cache**: `backend.ai.retrieval.cache.RetrievalResultCache`
- **Evaluation**: `backend.ai.retrieval.evaluation.evaluate_retriever`
- **Reranker Factory**: `backend.ai.retrieval.reranker_factory.create_reranker`
