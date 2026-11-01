"""Automated Feature Quality & Retrieval Benchmark Regression Suite (Week 2 Section 12 Item 13, Gate 3).

Verifies the platform's core quality gates against regression:
1. RAG retrieval benchmark (hit rate >= 80%, MRR >= 0.80, Precision@1 >= 70%)
2. Bug detection precision/recall/FPR (Precision >= 85%, Recall >= 85%, FPR <= 5%)
3. Code review grounding accuracy (100% bounded lines, 0% hallucination rate)
4. Test generation safety & syntax validity (100% safety rejection of unsafe paths/operations)
"""

from __future__ import annotations

import pytest

from scripts.benchmark_quality_suite import (
    run_bug_detection_quality_benchmark,
    run_code_review_grounding_benchmark,
    run_rag_retrieval_benchmark,
    run_test_generation_quality_benchmark,
)


@pytest.mark.asyncio
async def test_rag_retrieval_quality_benchmark_hit_rate_and_mrr() -> None:
    """Verify RAG hybrid retrieval achieves target >= 80% hit rate and >= 0.80 MRR on ground truth."""
    res = await run_rag_retrieval_benchmark()

    assert res["target_hit_rate_met"] is True, f"Hit rate {res['hit_rate_at_5']*100}% below required 80%"
    assert res["target_mrr_met"] is True, f"MRR {res['mrr']:.3f} below required 0.80"
    assert res["hit_rate_at_5"] >= 0.80
    assert res["mrr"] >= 0.80
    assert res["precision_at_1"] >= 0.70
    assert res["recall_at_5"] >= 0.80


def test_bug_detection_quality_benchmark_precision_recall_and_fpr() -> None:
    """Verify Bug Detection static & AST engines achieve precision >= 85%, recall >= 85%, FPR <= 5%."""
    res = run_bug_detection_quality_benchmark()

    assert res["target_precision_met"] is True, f"Precision {res['precision']*100}% below required 85%"
    assert res["target_recall_met"] is True, f"Recall {res['recall']*100}% below required 85%"
    assert res["target_fpr_met"] is True, f"False Positive Rate {res['false_positive_rate']*100}% exceeds 5%"
    assert res["precision"] >= 0.85
    assert res["recall"] >= 0.85
    assert res["f1_score"] >= 0.85
    assert res["false_positive_rate"] <= 0.05
    assert res["false_positives"] == 0, "Clean control code must produce 0 false positives"


def test_code_review_quality_benchmark_grounding_and_hallucination_rate() -> None:
    """Verify Code Review produces 100% bounded line citations and 0% hallucinated files."""
    res = run_code_review_grounding_benchmark()

    assert res["target_accuracy_met"] is True, f"Grounding accuracy {res['grounding_accuracy']*100}% != 100%"
    assert res["target_zero_hallucination_met"] is True, f"Hallucination rate {res['hallucination_rate']*100}% != 0%"
    assert res["grounding_accuracy"] == 1.0
    assert res["hallucination_rate"] == 0.0
    assert res["hallucinated_citations"] == 0
    assert res["grounded_findings"] > 0


def test_test_generation_quality_benchmark_safety_and_syntax() -> None:
    """Verify Test Generation enforces 100% rejection of unsafe/auto-executed paths and validates syntax."""
    res = run_test_generation_quality_benchmark()

    assert res["target_safety_met"] is True, f"Safety rejection rate {res['safety_rejection_rate']*100}% != 100%"
    assert res["safety_rejection_rate"] == 1.0
    assert res["rejected_unsafe_count"] == res["unsafe_paths_evaluated"]
    assert res["syntax_validity_rate"] >= 0.66
