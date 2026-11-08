"""Unit tests for the Benchmark Quality Gate Evaluator (Phase 1, task.md §9).

Verifies:
1. Values below target strictly produce status="FAIL" (e.g. 50% < 66%).
2. Values equal to target produce status="PASS".
3. Values above target produce status="PASS".
4. Missing / None measurements strictly produce status="FAIL".
5. Reverse operator "<=" (e.g. FPR <= 5%) correctly passes below and fails above.
6. All quality gates aggregation fails if any single mandatory gate fails.
"""

from __future__ import annotations

import pytest

from scripts.benchmark_quality_suite import evaluate_metric


class TestBenchmarkGateEvaluator:
    """Test suite for evaluate_metric and quality gate decision logic."""

    def test_value_below_target_strictly_fails(self) -> None:
        """Verify that a value below target (50% < 66%) strictly produces status='FAIL'."""
        res = evaluate_metric(0.50, 0.66, ">=")
        assert res["status"] == "FAIL"
        assert res["passed"] is False
        assert res["value"] == 0.50
        assert res["threshold"] == 0.66

    def test_value_at_target_passes(self) -> None:
        """Verify that a value exactly at target (66% >= 66%) produces status='PASS'."""
        res = evaluate_metric(0.66, 0.66, ">=")
        assert res["status"] == "PASS"
        assert res["passed"] is True

    def test_value_above_target_passes(self) -> None:
        """Verify that a value above target (75% >= 66%) produces status='PASS'."""
        res = evaluate_metric(0.75, 0.66, ">=")
        assert res["status"] == "PASS"
        assert res["passed"] is True

    def test_missing_measurement_fails(self) -> None:
        """Verify that None / missing values strictly produce status='FAIL' and passed=False."""
        res = evaluate_metric(None, 0.80, ">=")
        assert res["status"] == "FAIL"
        assert res["passed"] is False
        assert "Missing" in res.get("error", "")

    def test_less_than_or_equal_operator(self) -> None:
        """Verify operator '<=' (e.g. FPR target <= 5%)."""
        # Passing case (0% <= 5%)
        pass_res = evaluate_metric(0.00, 0.05, "<=")
        assert pass_res["status"] == "PASS"
        assert pass_res["passed"] is True

        # At threshold (5% <= 5%)
        edge_res = evaluate_metric(0.05, 0.05, "<=")
        assert edge_res["status"] == "PASS"
        assert edge_res["passed"] is True

        # Failing case (6% > 5%)
        fail_res = evaluate_metric(0.06, 0.05, "<=")
        assert fail_res["status"] == "FAIL"
        assert fail_res["passed"] is False

    def test_exact_equality_operator(self) -> None:
        """Verify operator '==' (e.g. safety rejection rate == 1.0)."""
        pass_res = evaluate_metric(1.0, 1.0, "==")
        assert pass_res["status"] == "PASS"
        assert pass_res["passed"] is True

        fail_res = evaluate_metric(0.99, 1.0, "==")
        assert fail_res["status"] == "FAIL"
        assert fail_res["passed"] is False

    def test_unsupported_operator_raises_error(self) -> None:
        """Verify invalid operator raises ValueError."""
        with pytest.raises(ValueError, match="Unsupported operator"):
            evaluate_metric(10, 5, "~=")

    def test_overall_quality_gates_aggregation(self) -> None:
        """Verify that overall_passed is False if any mandatory gate fails."""
        gates = {
            "retrieval_hit_rate": evaluate_metric(0.85, 0.80, ">="),
            "retrieval_mrr": evaluate_metric(0.82, 0.80, ">="),
            "bug_precision": evaluate_metric(0.90, 0.85, ">="),
            "bug_recall": evaluate_metric(0.88, 0.85, ">="),
            "assertion_presence": evaluate_metric(0.50, 0.66, ">="),  # Fails!
        }

        all_passed = all(g["passed"] for g in gates.values())
        assert all_passed is False

        # Now fix assertion presence
        gates["assertion_presence"] = evaluate_metric(0.67, 0.66, ">=")
        all_passed = all(g["passed"] for g in gates.values())
        assert all_passed is True
