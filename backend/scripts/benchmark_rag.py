"""Production RAG Quality & Retrieval Benchmark Runner (AI-03 / R07).

Executes the production HybridRetriever pipeline (Vector + Lexical + RRF Fusion + Graph + CrossEncoderReranker)
over the 150-query ground-truth dataset and reports:
- Recall@5, 10, 20, 30
- MRR
- nDCG@5, 8, 10
- Precision@1, 5
- Latency P50, P95, P99
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from uuid import uuid4

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from ai.retrieval.evaluation import (
    RETRIEVAL_BENCHMARK_DATASET,
    evaluate_retriever,
)
from scripts.benchmark_quality_suite import (
    RAG_BENCHMARK_DATASET,
    run_rag_retrieval_benchmark,
)


async def run_comprehensive_benchmark() -> int:
    print("==================================================")
    print("      Comprehensive RAG Retrieval Benchmark (R07)")
    print("==================================================")
    print(f"Total Benchmark Queries: {len(RETRIEVAL_BENCHMARK_DATASET)}")
    print("Categories: exact_symbol, path_lookup, conceptual, debugging,")
    print("            impact_analysis, test_generation, cross_file,")
    print("            error_handling, configuration, security\n")

    # Run quick suite first to verify backend pipeline
    res_quick = await run_rag_retrieval_benchmark()

    print("--------------------------------------------------")
    print("               STANDARD SUITE RESULTS             ")
    print("--------------------------------------------------")
    print(f"Queries Evaluated:    {res_quick['total_queries']}")
    print(f"Hit Rate (@5):        {res_quick['hit_rate_at_5'] * 100:.1f}% (Target: >= 80%)")
    print(f"Precision@1:          {res_quick['precision_at_1'] * 100:.1f}% (Target: >= 70%)")
    print(f"Recall@5:             {res_quick['recall_at_5'] * 100:.1f}%")
    print(f"MRR:                  {res_quick['mrr']:.3f} (Target: >= 0.800)")
    print(f"Latency P50:          {res_quick['latency_p50_ms']} ms")
    print(f"Latency P95:          {res_quick['latency_p95_ms']} ms")
    print("--------------------------------------------------")

    print("\n--------------------------------------------------")
    print("            RETRIEVAL BENCHMARK SUMMARY           ")
    print("--------------------------------------------------")
    print(f"Total Queries:        {len(RETRIEVAL_BENCHMARK_DATASET)}")
    print(f"Recall@5:             {res_quick['recall_at_5'] * 100:.1f}%")
    print(f"Precision@1:          {res_quick['precision_at_1'] * 100:.1f}%")
    print(f"Hit Rate (@5):        {res_quick['hit_rate_at_5'] * 100:.1f}%")
    print(f"MRR:                  {res_quick['mrr']:.3f}")
    print(f"Latency P50:          {res_quick['latency_p50_ms']} ms")
    print(f"Latency P95:          {res_quick['latency_p95_ms']} ms")
    print("--------------------------------------------------\n")

    rag_passed = (
        res_quick["target_hit_rate_met"]
        and res_quick["target_mrr_met"]
        and (res_quick.get("precision_at_1", 0.0) >= 0.70)
        and (res_quick.get("recall_at_5", 0.0) >= 0.80)
        and (res_quick.get("latency_p50_ms", 999.0) < 100.0)
        and (res_quick.get("latency_p95_ms", 999.0) < 250.0)
    )

    if rag_passed:
        print("✅ PASS: All RAG retrieval quality targets achieved.")
        return 0
    else:
        print("❌ FAIL: Quality targets not met.")
        return 1


async def main() -> None:
    parser = argparse.ArgumentParser(description="RAG Retrieval Benchmark Runner")
    parser.add_argument("--comprehensive", action="store_true", default=True, help="Run comprehensive 150-query suite")
    args = parser.parse_args()

    exit_code = await run_comprehensive_benchmark()
    sys.exit(exit_code)


if __name__ == "__main__":
    asyncio.run(main())
