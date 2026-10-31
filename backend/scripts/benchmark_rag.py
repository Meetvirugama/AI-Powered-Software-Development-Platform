"""Production RAG Quality & Retrieval Benchmark Runner (AI-03).

Executes the production HybridRetriever pipeline (Vector + Lexical + RRF Fusion + CrossEncoderReranker)
over the 10 ground-truth questions, reporting Hit Rate@5, MRR, Precision@1, and p50/p95 latency.
"""

from __future__ import annotations

import asyncio
import os
import sys
from uuid import uuid4

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from scripts.benchmark_quality_suite import (
    RAG_BENCHMARK_DATASET,
    build_fixture_chunks,
    run_rag_retrieval_benchmark,
)


async def main() -> None:
    print("==================================================")
    print("      Production RAG Quality Benchmark Runner     ")
    print("==================================================\n")

    repo_id = uuid4()
    print(f"Target Repository ID: {repo_id}")
    print(f"Total Questions: {len(RAG_BENCHMARK_DATASET)}\n")

    res = await run_rag_retrieval_benchmark()

    print("==================================================")
    print("                 FINAL RESULTS                    ")
    print("==================================================")
    print(f"Total Queries:        {res['total_queries']}")
    print(f"File Hit Rate (@5):   {res['hit_rate_at_5'] * 100:.1f}% (Target: >= 80%)")
    print(f"Precision@1:          {res['precision_at_1'] * 100:.1f}% (Target: >= 70%)")
    print(f"Recall@5:             {res['recall_at_5'] * 100:.1f}%")
    print(f"MRR:                  {res['mrr']:.3f} (Target: >= 0.800)")
    print(f"Latency P50:          {res['latency_p50_ms']} ms")
    print(f"Latency P95:          {res['latency_p95_ms']} ms")
    print("==================================================")

    if res["target_hit_rate_met"] and res["target_mrr_met"]:
        print("✅ PASS: All RAG retrieval quality targets achieved.")
        sys.exit(0)
    else:
        print("❌ FAIL: Quality targets not met.")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
