"""
Retrieval evaluation metrics and benchmark suite (R07).
Owner: Meet — W1-12

Computes:
- Recall@5, 10, 20, 30
- Mean Reciprocal Rank (MRR)
- nDCG@5, 8, 10
- Precision@1, 5
- Latency percentiles: P50, P95, P99
"""

from __future__ import annotations

import dataclasses
import math
import time
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from .base import CodeChunk, Retriever

__all__ = [
    "RETRIEVAL_BENCHMARK_DATASET",
    "BenchmarkQuery",
    "EvaluationReport",
    "compute_latency_percentiles",
    "compute_mrr",
    "compute_ndcg_at_k",
    "compute_precision_at_k",
    "compute_recall_at_k",
    "evaluate_retriever",
]


@dataclass
class BenchmarkQuery:
    """A ground-truth query for retrieval benchmarking."""

    id: str
    query: str
    intent: str
    category: str
    expected_files: list[str] = field(default_factory=list)
    expected_symbols: list[str] = field(default_factory=list)
    expected_chunk_ids: list[str] = field(default_factory=list)
    relevance_grades: dict[str, int] = field(default_factory=dict)  # target -> grade (1..3)
    notes: str = ""


@dataclass
class EvaluationReport:
    """Aggregated retrieval benchmark report."""

    total_queries: int
    recall_at_5: float
    recall_at_10: float
    recall_at_20: float
    recall_at_30: float
    mrr: float
    ndcg_at_5: float
    ndcg_at_8: float
    ndcg_at_10: float
    precision_at_1: float
    precision_at_5: float
    p50_latency_ms: float
    p95_latency_ms: float
    p99_latency_ms: float
    per_intent_metrics: dict[str, dict[str, float]] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)


def compute_recall_at_k(retrieved: list[str], relevant: set[str], k: int) -> float:
    """Recall@K = |retrieved[:k] ∩ relevant| / |relevant|."""
    if not relevant or k <= 0:
        return 0.0
    top_k_set = set(retrieved[:k])
    return len(top_k_set & relevant) / float(len(relevant))


def compute_precision_at_k(retrieved: list[str], relevant: set[str], k: int) -> float:
    """Precision@K = |retrieved[:k] ∩ relevant| / k."""
    if k <= 0:
        return 0.0
    top_k_set = set(retrieved[:k])
    return len(top_k_set & relevant) / float(k)


def compute_mrr(retrieved: list[str], relevant: set[str]) -> float:
    """Mean Reciprocal Rank = 1 / first_relevant_rank (1-based), or 0.0 if not found."""
    if not relevant:
        return 0.0
    for rank, item in enumerate(retrieved, start=1):
        if item in relevant:
            return 1.0 / float(rank)
    return 0.0


def compute_ndcg_at_k(
    retrieved: list[str],
    relevance_grades: dict[str, int],
    k: int,
) -> float:
    """
    Normalized Discounted Cumulative Gain (nDCG@K).
    Uses standard graded relevance formula:
    DCG = Σ (2^rel_i - 1) / log2(i + 1)
    """
    if k <= 0 or not relevance_grades:
        return 0.0

    dcg = 0.0
    for i, item in enumerate(retrieved[:k], start=1):
        grade = relevance_grades.get(item, 0)
        if grade > 0:
            dcg += (2.0**grade - 1.0) / math.log2(i + 1)

    # Ideal DCG (sorted descending by grade)
    ideal_grades = sorted(relevance_grades.values(), reverse=True)[:k]
    idcg = sum(
        (2.0**g - 1.0) / math.log2(i + 1)
        for i, g in enumerate(ideal_grades, start=1)
    )

    if idcg <= 0.0:
        return 0.0
    return min(1.0, dcg / idcg)


def compute_latency_percentiles(latencies_ms: list[float]) -> dict[str, float]:
    """Compute P50, P95, and P99 latency percentiles in milliseconds."""
    if not latencies_ms:
        return {"p50": 0.0, "p95": 0.0, "p99": 0.0}

    sorted_lats = sorted(latencies_ms)
    n = len(sorted_lats)

    def percentile(p: float) -> float:
        idx = math.ceil((p / 100.0) * n) - 1
        return sorted_lats[max(0, min(idx, n - 1))]

    return {
        "p50": round(percentile(50), 2),
        "p95": round(percentile(95), 2),
        "p99": round(percentile(99), 2),
    }


# Representative 150+ benchmark query dataset covering all 10 categories
_CATEGORIES = [
    ("exact_symbol", "exact_symbol", [
        ("Where is UserRepository defined?", ["backend/app/repositories/user_repository.py"], ["UserRepository"]),
        ("Find UserAuthenticationService", ["backend/app/core/auth.py"], ["UserAuthenticationService"]),
        ("Where is JWTMiddleware implemented?", ["backend/app/core/auth.py"], ["JWTMiddleware"]),
        ("Find hash_password implementation", ["backend/app/core/security.py"], ["hash_password"]),
        ("Where is CodeChunk defined?", ["backend/ai/retrieval/base.py"], ["CodeChunk"]),
        ("Find VectorRetriever class", ["backend/ai/retrieval/vector.py"], ["VectorRetriever"]),
        ("Where is LexicalRetriever defined?", ["backend/ai/retrieval/lexical.py"], ["LexicalRetriever"]),
        ("Find SymbolGraphExpander", ["backend/ai/retrieval/graph_expansion.py"], ["SymbolGraphExpander"]),
        ("Where is RRFFusion defined?", ["backend/ai/retrieval/fusion.py"], ["RRFFusion"]),
        ("Find RetrievalResultCache", ["backend/ai/retrieval/cache.py"], ["RetrievalResultCache"]),
        ("Where is CrossEncoderReranker defined?", ["backend/ai/retrieval/reranker.py"], ["CrossEncoderReranker"]),
        ("Find IncrementalIndexer", ["backend/indexer/incremental.py"], ["IncrementalIndexer"]),
        ("Where is create_access_token defined?", ["backend/app/core/security.py"], ["create_access_token"]),
        ("Find verify_token method", ["backend/app/core/security.py"], ["verify_token"]),
        ("Where is build_retrieval_cache_key implemented?", ["backend/ai/retrieval/cache_keys.py"], ["build_retrieval_cache_key"]),
    ]),
    ("path_lookup", "path_lookup", [
        ("Open backend/app/api/v1/auth.py", ["backend/app/api/v1/auth.py"], []),
        ("Open backend/ai/retrieval/vector.py", ["backend/ai/retrieval/vector.py"], []),
        ("Open backend/app/repositories/user_repository.py", ["backend/app/repositories/user_repository.py"], []),
        ("Open backend/app/core/config.py", ["backend/app/core/config.py"], []),
        ("Open backend/indexer/incremental.py", ["backend/indexer/incremental.py"], []),
        ("Open backend/app/core/auth.py", ["backend/app/core/auth.py"], []),
        ("Open backend/ai/retrieval/hybrid.py", ["backend/ai/retrieval/hybrid.py"], []),
        ("Open backend/ai/retrieval/fusion.py", ["backend/ai/retrieval/fusion.py"], []),
        ("Open backend/ai/retrieval/cache.py", ["backend/ai/retrieval/cache.py"], []),
        ("Open backend/ai/retrieval/reranker.py", ["backend/ai/retrieval/reranker.py"], []),
        ("Open backend/app/models/code_chunk.py", ["backend/app/models/code_chunk.py"], []),
        ("Open backend/app/models/symbol_edge.py", ["backend/app/models/symbol_edge.py"], []),
        ("Open backend/app/core/redis.py", ["backend/app/core/redis.py"], []),
        ("Open backend/app/core/database.py", ["backend/app/core/database.py"], []),
        ("Open backend/ai/retrieval/code_tokenizer.py", ["backend/ai/retrieval/code_tokenizer.py"], []),
    ]),
    ("conceptual", "conceptual", [
        ("Explain how user authentication works", ["backend/app/core/auth.py", "backend/app/api/v1/auth.py"], []),
        ("Which file contains the login route?", ["backend/app/api/v1/auth.py"], []),
        ("How does hybrid retrieval aggregate results?", ["backend/ai/retrieval/hybrid.py", "backend/ai/retrieval/fusion.py"], []),
        ("How does incremental indexing detect changed files?", ["backend/indexer/incremental.py"], []),
        ("Describe the Redis result caching mechanism", ["backend/ai/retrieval/cache.py"], []),
        ("How does token rate limiting protect API endpoints?", ["backend/app/core/redis.py"], []),
        ("Explain how pgvector cosine similarity search works", ["backend/ai/retrieval/vector.py"], []),
        ("How does code-aware lexical search tokenize identifiers?", ["backend/ai/retrieval/code_tokenizer.py"], []),
        ("Explain reciprocal rank fusion smoothing with k=60", ["backend/ai/retrieval/fusion.py"], []),
        ("How does symbol graph traversal enforce repository isolation?", ["backend/ai/retrieval/graph_expansion.py"], []),
        ("Describe cross-encoder reranking latency trade-offs", ["backend/ai/retrieval/reranker.py"], []),
        ("How is the active index generation incremented?", ["backend/indexer/incremental.py"], []),
        ("Explain how the database session lifecycle is managed", ["backend/app/core/database.py"], []),
        ("What is the structure of code chunks in postgres?", ["backend/app/models/code_chunk.py"], []),
        ("How are symbol edges stored and categorized?", ["backend/app/models/symbol_edge.py"], []),
    ]),
    ("debugging", "debugging", [
        ("Why does token refresh fail?", ["backend/app/core/security.py"], []),
        ("What happens when repository lookup fails?", ["backend/app/api/v1/repositories.py"], []),
        ("Why is vector search raising syntax error on hnsw scan?", ["backend/ai/retrieval/vector.py"], []),
        ("Why does Redis connection timeout during peak traffic?", ["backend/app/core/redis.py"], []),
        ("Fix bug in code chunk line range calculation", ["backend/indexer/incremental.py"], []),
        ("Why is lexical search returning zero results for camelCase?", ["backend/ai/retrieval/code_tokenizer.py"], []),
        ("Error in JSON deserialization of cached retrieval payload", ["backend/ai/retrieval/cache_serialization.py"], []),
        ("Why does database session rollback fail during sync error?", ["backend/indexer/incremental.py"], []),
        ("Fix crash when symbol_id is null in graph expansion", ["backend/ai/retrieval/graph_expansion.py"], []),
        ("Why is cross-encoder predict throwing OOM on large batch?", ["backend/ai/retrieval/reranker.py"], []),
        ("Fix race condition on simultaneous cache misses", ["backend/ai/retrieval/cache.py"], []),
        ("Why did repository sync fail with duplicate key constraint?", ["backend/indexer/incremental.py"], []),
        ("Fix issue where stale index generation returns old code", ["backend/ai/retrieval/cache_keys.py"], []),
        ("Why is HNSW ef_search not applied in SQLite in-memory test?", ["backend/ai/retrieval/vector.py"], []),
        ("Error when weights length does not match result lists", ["backend/ai/retrieval/fusion.py"], []),
    ]),
    ("impact_analysis", "impact_analysis", [
        ("What functions call validate_user?", ["src/auth/service.py", "src/auth/login.py"], ["validate_user"]),
        ("Find all callers of create_session", ["src/auth/session.py", "src/auth/service.py"], ["create_session"]),
        ("Which components depend on VectorRetriever?", ["backend/ai/retrieval/hybrid.py"], ["VectorRetriever"]),
        ("What depends on CodeChunk schema changes?", ["backend/ai/retrieval/base.py", "backend/app/models/code_chunk.py"], ["CodeChunk"]),
        ("What calls build_retrieval_cache_key?", ["backend/ai/retrieval/hybrid.py"], ["build_retrieval_cache_key"]),
        ("Which functions invoke generate_code_search_text?", ["backend/indexer/incremental.py"], ["generate_code_search_text"]),
        ("What code is affected if symbol_edges table changes?", ["backend/ai/retrieval/graph_expansion.py"], ["SymbolEdge"]),
        ("Find callers of detect_query_intent", ["backend/ai/retrieval/fusion.py", "backend/ai/retrieval/hybrid.py"], ["detect_query_intent"]),
        ("What calls invalidate_repository on sync completion?", ["backend/indexer/incremental.py"], ["invalidate_repository"]),
        ("Which methods call resolve_hnsw_profile?", ["backend/ai/retrieval/hybrid.py"], ["resolve_hnsw_profile"]),
        ("Find all references to CrossEncoderReranker", ["backend/ai/retrieval/hybrid.py"], ["CrossEncoderReranker"]),
        ("What calls fuse_adaptive?", ["backend/ai/retrieval/hybrid.py"], ["fuse_adaptive"]),
        ("Which endpoints depend on get_async_redis_client?", ["backend/ai/retrieval/cache.py"], ["get_async_redis_client"]),
        ("What services use SymbolEdgeRepository?", ["backend/app/services/bug_graph_context_service.py"], ["SymbolEdgeRepository"]),
        ("Find all callers of get_settings in retrieval pipeline", ["backend/ai/retrieval/vector.py", "backend/ai/retrieval/cache.py"], ["get_settings"]),
    ]),
    ("test_generation", "test_generation", [
        ("Generate tests for payment service", ["src/services/payment.py"], []),
        ("Generate tests for code tokenizer", ["backend/ai/retrieval/code_tokenizer.py"], []),
        ("Create unit tests for adaptive HNSW", ["backend/ai/retrieval/vector.py"], []),
        ("Write test cases for retrieval cache serialization", ["backend/ai/retrieval/cache_serialization.py"], []),
        ("Generate tests for query intent classification", ["backend/ai/retrieval/fusion.py"], []),
        ("Create tests for symbol graph expansion bounds", ["backend/ai/retrieval/graph_expansion.py"], []),
        ("Write tests for repository-scoped cache invalidation", ["backend/ai/retrieval/cache.py"], []),
        ("Generate tests for incremental indexer transaction rollback", ["backend/indexer/incremental.py"], []),
        ("Create test suite for hybrid retriever graceful degradation", ["backend/ai/retrieval/hybrid.py"], []),
        ("Generate unit tests for cross-encoder reranker batching", ["backend/ai/retrieval/reranker.py"], []),
        ("Write tests for SQLite fallback on set local ef_search", ["backend/ai/retrieval/vector.py"], []),
        ("Create tests for stampede lock acquisition and release", ["backend/ai/retrieval/cache.py"], []),
        ("Generate tests for multi-source RRF weight validation", ["backend/ai/retrieval/fusion.py"], []),
        ("Write tests for GIN index code search tsquery", ["backend/ai/retrieval/lexical.py"], []),
        ("Generate tests for active index generation increment", ["backend/indexer/incremental.py"], []),
    ]),
    ("cross_file", "conceptual", [
        ("How does the API call reach the database?", ["backend/app/api/v1/repositories.py", "backend/app/repositories/base.py"], []),
        ("Trace authentication token from header to user model", ["backend/app/api/v1/auth.py", "src/auth/service.py"], []),
        ("How does an index sync job write chunks and embeddings?", ["backend/indexer/incremental.py", "backend/ai/retrieval/vector.py"], []),
        ("Follow search query from hybrid retriever to postgres", ["backend/ai/retrieval/hybrid.py", "backend/ai/retrieval/lexical.py"], []),
        ("How is a task execution plan transitioned to verification?", ["backend/app/services/task_execution_orchestrator.py"], []),
        ("Trace repository file ingestion into code symbols and chunks", ["backend/scanner/symbols.py", "backend/indexer/incremental.py"], []),
        ("How does code review orchestrator interact with LLM gateway?", ["backend/app/services/code_review_orchestrator.py"], []),
        ("Trace Redis cache set to serialization and network socket", ["backend/ai/retrieval/cache.py", "backend/ai/retrieval/cache_serialization.py"], []),
        ("How does bug detection pipeline assemble graph context?", ["backend/app/services/bug_graph_context_service.py"], []),
        ("Trace grounding validator check on retrieved code chunks", ["backend/ai/pipeline.py"], []),
        ("Follow user signup request through bcrypt hashing and DB commit", ["src/auth/service.py", "src/auth/crypto.py"], []),
        ("How does git branch creation isolate task workspaces?", ["backend/app/services/git_branch.py"], []),
        ("Trace task recovery orchestration upon worker crash", ["backend/app/services/task_recovery.py"], []),
        ("How does independent verifier run test commands in harness?", ["backend/app/services/independent_verifier.py"], []),
        ("Trace symbol edge extraction to database persistence", ["backend/scanner/graph.py", "backend/indexer/incremental.py"], []),
    ]),
    ("error_handling", "debugging", [
        ("Where is RetrievalUnavailableError handled?", ["backend/ai/retrieval/hybrid.py"], ["RetrievalUnavailableError"]),
        ("How are database rollback exceptions handled in sync worker?", ["backend/app/workers/sync_worker.py"], []),
        ("Where is token expiration exception caught in auth middleware?", ["src/middleware/jwt.py"], []),
        ("How does the system handle missing pgvector extension gracefully?", ["backend/ai/retrieval/vector.py"], []),
        ("Where are GitHub API 429 rate limit errors retried?", ["backend/app/services/git_branch.py"], []),
        ("How does cache deserialization handle corrupt JSON payloads?", ["backend/ai/retrieval/cache_serialization.py"], []),
        ("Where is Redis connection error caught during cache get?", ["backend/ai/retrieval/cache.py"], []),
        ("How does symbol graph expander handle missing tables or edges?", ["backend/ai/retrieval/graph_expansion.py"], []),
        ("Where is lexical search query syntax error caught?", ["backend/ai/retrieval/lexical.py"], []),
        ("How are subprocess timeout errors caught in verification?", ["backend/app/services/independent_verifier.py"], []),
        ("Where is invalid RRF k constant rejected with ValueError?", ["backend/ai/retrieval/fusion.py"], []),
        ("How does the application recover from database connection drops?", ["backend/app/core/database.py"], []),
        ("Where is file not found error handled in code viewer?", ["backend/app/api/v1/repositories.py"], []),
        ("How does incremental indexer handle git diff failure?", ["backend/indexer/incremental.py"], []),
        ("Where is embedding service timeout logged and bypassed?", ["backend/ai/retrieval/vector.py"], []),
    ]),
    ("configuration", "configuration_lookup", [
        ("Where is the database URL configured?", ["backend/app/core/config.py"], []),
        ("Where is the Redis connection string configured?", ["backend/app/core/config.py"], []),
        ("Where is RETRIEVAL_CACHE_ENABLED defined?", ["backend/app/core/config.py"], []),
        ("Where is HNSW ef_search default configured?", ["backend/app/core/config.py"], []),
        ("Where is active_chat_model configured?", ["backend/app/core/config.py"], []),
        ("Where is RETRIEVAL_CACHE_TTL_SECONDS set?", ["backend/app/core/config.py"], []),
        ("Where is CORS allowed origins list configured?", ["backend/app/core/config.py"], []),
        ("Where is JWT secret key and algorithm loaded?", ["backend/app/core/config.py"], []),
        ("Where is pgvector dimensions set to 768?", ["backend/app/models/code_chunk.py"], []),
        ("Where is Alembic target_metadata configured?", ["backend/migrations/env.py"], []),
        ("Where is the default candidate top_k defined?", ["backend/ai/retrieval/hybrid.py"], []),
        ("Where is default RRF k=60 constant defined?", ["backend/ai/retrieval/fusion.py"], []),
        ("Where is maximum cache payload bytes configured?", ["backend/app/core/config.py"], []),
        ("Where is GitHub OAuth client ID loaded?", ["backend/app/core/config.py"], []),
        ("Where is cross-encoder model name specified?", ["backend/ai/retrieval/reranker.py"], []),
    ]),
    ("security", "conceptual", [
        ("Where are user permissions and roles checked?", ["backend/app/core/auth.py"], []),
        ("Where is secret redaction performed on logs and chunks?", ["backend/app/core/security.py"], []),
        ("How is repository isolation enforced in lexical search?", ["backend/ai/retrieval/lexical.py"], []),
        ("How is tenant isolation maintained in symbol graph expansion?", ["backend/ai/retrieval/graph_expansion.py"], []),
        ("Where is git history scanned for private keys and tokens?", ["backend/app/services/git_branch.py"], []),
        ("How does CSRF protection validate request origins?", ["backend/app/core/auth.py"], []),
        ("Where is input path traversal prevented for repository files?", ["backend/app/core/security.py"], []),
        ("How are passwords hashed and salted with bcrypt?", ["src/auth/crypto.py"], []),
        ("Where is JWT token signature verified?", ["src/middleware/jwt.py"], []),
        ("How does rate limiting mitigate brute-force authentication attacks?", ["backend/app/core/redis.py"], []),
        ("Where is SQL injection prevented in pgvector raw queries?", ["backend/ai/retrieval/vector.py"], []),
        ("How are subprocess arguments sanitized against command injection?", ["backend/app/services/git_branch.py"], []),
        ("Where is workspace symlink traversal checked and reaped?", ["backend/app/services/git_branch.py"], []),
        ("How does GitHub installation upsert prevent cross-tenant hijacking?", ["backend/app/api/v1/github.py"], []),
        ("Where are security headers set on API responses?", ["backend/app/core/security.py"], []),
    ]),
]


def _build_dataset() -> list[BenchmarkQuery]:
    dataset: list[BenchmarkQuery] = []
    idx = 1
    for cat_name, intent, queries in _CATEGORIES:
        for q_text, files, symbols in queries:
            qid = f"Q{idx:03d}"
            grades: dict[str, int] = {}
            for rank_idx, f in enumerate(files):
                grades[f] = 3 if rank_idx == 0 else 2

            dataset.append(
                BenchmarkQuery(
                    id=qid,
                    query=q_text,
                    intent=intent,
                    category=cat_name,
                    expected_files=files,
                    expected_symbols=symbols,
                    relevance_grades=grades,
                    notes=f"Category: {cat_name}, Intent: {intent}",
                )
            )
            idx += 1
    return dataset


RETRIEVAL_BENCHMARK_DATASET = _build_dataset()


async def evaluate_retriever(
    retriever: Retriever,
    queries: list[BenchmarkQuery],
    repository_id: UUID | str,
) -> EvaluationReport:
    """
    Run the full evaluation benchmark across all dataset queries.
    """
    recalls_5: list[float] = []
    recalls_10: list[float] = []
    recalls_20: list[float] = []
    recalls_30: list[float] = []
    mrrs: list[float] = []
    ndcgs_5: list[float] = []
    ndcgs_8: list[float] = []
    ndcgs_10: list[float] = []
    precisions_1: list[float] = []
    precisions_5: list[float] = []
    latencies_ms: list[float] = []

    per_intent: dict[str, list[tuple[float, float, float]]] = {}

    for bq in queries:
        t0 = time.perf_counter()
        results: list[CodeChunk] = await retriever.retrieve(
            query=bq.query,
            repository_id=repository_id,
            top_k=30,
        )
        elapsed_ms = (time.perf_counter() - t0) * 1000.0
        latencies_ms.append(elapsed_ms)

        # Deduplicate retrieved files preserving rank order
        retrieved_files: list[str] = []
        for c in results:
            if c.file_path and c.file_path not in retrieved_files:
                retrieved_files.append(c.file_path)
        relevant_files = set(bq.expected_files)

        r5 = compute_recall_at_k(retrieved_files, relevant_files, 5)
        r10 = compute_recall_at_k(retrieved_files, relevant_files, 10)
        r20 = compute_recall_at_k(retrieved_files, relevant_files, 20)
        r30 = compute_recall_at_k(retrieved_files, relevant_files, 30)

        mrr_val = compute_mrr(retrieved_files, relevant_files)

        ndcg_5 = compute_ndcg_at_k(retrieved_files, bq.relevance_grades, 5)
        ndcg_8 = compute_ndcg_at_k(retrieved_files, bq.relevance_grades, 8)
        ndcg_10 = compute_ndcg_at_k(retrieved_files, bq.relevance_grades, 10)

        p1 = compute_precision_at_k(retrieved_files, relevant_files, 1)
        p5 = compute_precision_at_k(retrieved_files, relevant_files, 5)

        recalls_5.append(r5)
        recalls_10.append(r10)
        recalls_20.append(r20)
        recalls_30.append(r30)
        mrrs.append(mrr_val)
        ndcgs_5.append(ndcg_5)
        ndcgs_8.append(ndcg_8)
        ndcgs_10.append(ndcg_10)
        precisions_1.append(p1)
        precisions_5.append(p5)

        if bq.intent not in per_intent:
            per_intent[bq.intent] = []
        per_intent[bq.intent].append((r10, mrr_val, ndcg_8))

    pcts = compute_latency_percentiles(latencies_ms)
    n = len(queries)

    intent_summary: dict[str, dict[str, float]] = {}
    for intent_name, triples in per_intent.items():
        intent_summary[intent_name] = {
            "recall_at_10": round(sum(t[0] for t in triples) / len(triples), 4),
            "mrr": round(sum(t[1] for t in triples) / len(triples), 4),
            "ndcg_at_8": round(sum(t[2] for t in triples) / len(triples), 4),
            "query_count": len(triples),
        }

    return EvaluationReport(
        total_queries=n,
        recall_at_5=round(sum(recalls_5) / n, 4),
        recall_at_10=round(sum(recalls_10) / n, 4),
        recall_at_20=round(sum(recalls_20) / n, 4),
        recall_at_30=round(sum(recalls_30) / n, 4),
        mrr=round(sum(mrrs) / n, 4),
        ndcg_at_5=round(sum(ndcgs_5) / n, 4),
        ndcg_at_8=round(sum(ndcgs_8) / n, 4),
        ndcg_at_10=round(sum(ndcgs_10) / n, 4),
        precision_at_1=round(sum(precisions_1) / n, 4),
        precision_at_5=round(sum(precisions_5) / n, 4),
        p50_latency_ms=pcts["p50"],
        p95_latency_ms=pcts["p95"],
        p99_latency_ms=pcts["p99"],
        per_intent_metrics=intent_summary,
    )
