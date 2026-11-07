"""
Unit tests for retrieval evaluation metrics and benchmark harness (R07).
"""

from __future__ import annotations

from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from backend.ai.retrieval.base import CodeChunk
from backend.ai.retrieval.evaluation import (
    RETRIEVAL_BENCHMARK_DATASET,
    BenchmarkQuery,
    compute_latency_percentiles,
    compute_mrr,
    compute_ndcg_at_k,
    compute_precision_at_k,
    compute_recall_at_k,
    evaluate_retriever,
)


def test_benchmark_dataset_integrity() -> None:
    assert len(RETRIEVAL_BENCHMARK_DATASET) >= 150
    ids = [q.id for q in RETRIEVAL_BENCHMARK_DATASET]
    assert len(ids) == len(set(ids)), "Query IDs must be globally unique"

    categories = {q.category for q in RETRIEVAL_BENCHMARK_DATASET}
    expected_categories = {
        "exact_symbol",
        "path_lookup",
        "conceptual",
        "debugging",
        "impact_analysis",
        "test_generation",
        "cross_file",
        "error_handling",
        "configuration",
        "security",
    }
    assert expected_categories.issubset(categories)


def test_compute_recall_at_k() -> None:
    relevant = {"a.py", "b.py"}
    retrieved = ["x.py", "a.py", "y.py", "b.py", "z.py"]

    # At k=1: "x.py" -> 0 / 2 = 0.0
    assert compute_recall_at_k(retrieved, relevant, 1) == 0.0
    # At k=2: "x.py", "a.py" -> 1 / 2 = 0.5
    assert compute_recall_at_k(retrieved, relevant, 2) == 0.5
    # At k=4: 2 / 2 = 1.0
    assert compute_recall_at_k(retrieved, relevant, 4) == 1.0
    # Empty relevant -> 0.0
    assert compute_recall_at_k(retrieved, set(), 5) == 0.0


def test_compute_precision_at_k() -> None:
    relevant = {"a.py", "b.py"}
    retrieved = ["a.py", "x.py", "b.py"]

    # At k=1: 1/1 = 1.0
    assert compute_precision_at_k(retrieved, relevant, 1) == 1.0
    # At k=2: 1/2 = 0.5
    assert compute_precision_at_k(retrieved, relevant, 2) == 0.5
    # At k=3: 2/3 ≈ 0.6667
    assert round(compute_precision_at_k(retrieved, relevant, 3), 4) == 0.6667


def test_compute_mrr() -> None:
    relevant = {"target.py"}
    # First position
    assert compute_mrr(["target.py", "other.py"], relevant) == 1.0
    # Second position
    assert compute_mrr(["other.py", "target.py"], relevant) == 0.5
    # Not found
    assert compute_mrr(["other1.py", "other2.py"], relevant) == 0.0
    # Empty relevant
    assert compute_mrr(["a.py"], set()) == 0.0


def test_compute_ndcg_at_k() -> None:
    grades = {"docA": 3, "docB": 2, "docC": 1}

    # Perfect ranking: docA, docB, docC
    perfect = ["docA", "docB", "docC"]
    assert round(compute_ndcg_at_k(perfect, grades, 3), 4) == 1.0

    # Suboptimal ranking: docC, docB, docA
    suboptimal = ["docC", "docB", "docA"]
    ndcg_sub = compute_ndcg_at_k(suboptimal, grades, 3)
    assert 0.0 < ndcg_sub < 1.0

    # Completely irrelevant ranking
    irrelevant = ["x", "y", "z"]
    assert compute_ndcg_at_k(irrelevant, grades, 3) == 0.0


def test_compute_latency_percentiles() -> None:
    latencies = [10.0, 20.0, 30.0, 40.0, 50.0, 60.0, 70.0, 80.0, 90.0, 100.0]
    pcts = compute_latency_percentiles(latencies)
    assert pcts["p50"] == 50.0
    assert pcts["p95"] == 100.0
    assert pcts["p99"] == 100.0

    empty_pcts = compute_latency_percentiles([])
    assert empty_pcts == {"p50": 0.0, "p95": 0.0, "p99": 0.0}


@pytest.mark.asyncio
async def test_evaluate_retriever_harness() -> None:
    query = BenchmarkQuery(
        id="Q001",
        query="find user service",
        intent="exact_symbol",
        category="exact_symbol",
        expected_files=["src/user.py"],
        expected_symbols=["UserService"],
        relevance_grades={"src/user.py": 3},
    )

    mock_chunk = CodeChunk(
        id=uuid4(),
        repository_id=uuid4(),
        file_id=uuid4(),
        symbol_id=uuid4(),
        content="class UserService: pass",
        token_count=10,
        start_line=1,
        end_line=2,
        content_hash="h1",
        score=0.9,
        file_path="src/user.py",
    )

    mock_retriever = AsyncMock()
    mock_retriever.retrieve.return_value = [mock_chunk]

    report = await evaluate_retriever(mock_retriever, [query], repository_id=uuid4())
    assert report.total_queries == 1
    assert report.recall_at_5 == 1.0
    assert report.mrr == 1.0
    assert report.precision_at_1 == 1.0
    assert report.ndcg_at_5 == 1.0
    assert "exact_symbol" in report.per_intent_metrics
