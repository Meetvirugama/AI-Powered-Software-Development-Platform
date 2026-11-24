"""Run the deterministic RAG retrieval fixture benchmark and validate its quality gates."""

from __future__ import annotations

import argparse
import asyncio
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from scripts.benchmark_quality_suite import (
    run_rag_retrieval_benchmark,
)


async def run_comprehensive_benchmark() -> int:
    res_quick = await run_rag_retrieval_benchmark()

    print("--------------------------------------------------")
    print("               RETRIEVAL FIXTURE RESULTS             ")
    print("--------------------------------------------------")
    print(f"Queries Evaluated:    {res_quick['total_queries']}")
    print(f"Hit Rate (@5):        {res_quick['hit_rate_at_5'] * 100:.1f}% (Target: >= 80%)")
    print(f"Precision@1:          {res_quick['precision_at_1'] * 100:.1f}% (Target: >= 70%)")
    print(f"Recall@5:             {res_quick['recall_at_5'] * 100:.1f}%")
    print(f"MRR:                  {res_quick['mrr']:.3f} (Target: >= 0.800)")
    print(f"Latency P50:          {res_quick['latency_p50_ms']} ms")
    print(f"Latency P95:          {res_quick['latency_p95_ms']} ms")
    print("--------------------------------------------------")

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
    parser.add_argument("--comprehensive", action="store_true", default=True, help="Run the retrieval fixture suite")
    parser.parse_args()

    exit_code = await run_comprehensive_benchmark()
    sys.exit(exit_code)


if __name__ == "__main__":
    asyncio.run(main())
