"""
Benchmark Evaluation Unit Tests (task.md §23).

Tests the benchmark suite for:
- Completeness of dataset (at least 30-50 questions across 7 categories)
- Evaluation metric computation and comparisons
- Validation that Agentic Chat excels on multi-step investigation while Normal Chat remains fast and lightweight
"""

from ai.agent.benchmark import BENCHMARK_DATASET, run_benchmark_simulation


def test_benchmark_dataset_completeness():
    assert len(BENCHMARK_DATASET) >= 30
    categories = {q.category for q in BENCHMARK_DATASET}
    expected_categories = {
        "symbol_lookup",
        "file_location",
        "function_behavior",
        "authentication_flow",
        "data_flow",
        "dependency",
        "caller_callee",
    }
    assert expected_categories.issubset(categories)


def test_benchmark_simulation_results():
    results = run_benchmark_simulation()
    assert "normal" in results
    assert "agentic" in results

    normal = results["normal"]
    agentic = results["agentic"]

    # Normal mode has lower latency and 0 tools
    assert normal.avg_latency_ms < agentic.avg_latency_ms
    assert normal.avg_tools_used == 0.0

    # Agentic mode has higher citation recall and higher success rate on complex queries
    assert agentic.citation_recall > normal.citation_recall
    assert agentic.citation_precision >= normal.citation_precision
    assert agentic.successful_answers >= normal.successful_answers
    assert agentic.avg_tools_used > 1.0
