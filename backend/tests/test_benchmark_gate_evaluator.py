"""Comprehensive unit tests for QualityGate and Benchmark Gate Evaluator (Phase 1, task3.md §5.6 & §11.1).

Verifies:
1. Strict inequality: values below target strictly produce status="FAIL" (e.g. 50% < 66%).
2. Inclusive equality: values equal to target produce status="PASS" (e.g. 66% >= 66%).
3. Values above target produce status="PASS" (e.g. 75% >= 66%).
4. Zero score handling (0.0 < 0.80 -> FAIL, 0.0 <= 0.05 -> PASS).
5. Missing measurement values (None) strictly produce status="FAIL".
6. Non-finite values: NaN strictly produces status="FAIL".
7. Non-finite values: Positive and Negative Infinity strictly produce status="FAIL".
8. Maximum-threshold metrics (e.g. FPR <= 5%, latency < 100ms).
9. Exact equality operator (e.g. safety rejection rate == 1.0).
10. Unsupported operator raises ValueError.
11. Multi-metric suite evaluation where 1 mandatory failure fails the entire gate.
12. Multi-metric suite evaluation where all metrics pass.
13. Zero-sample evaluation suite strictly fails (cannot pass with 0 samples).
14. AIQualityEvaluator empty fixture evaluation fails quality thresholds.
"""

from __future__ import annotations

import math
import pytest

from ai.evaluation.quality_gate import (
    ComparisonOperator,
    MetricThreshold,
    QualityGate,
    QualityGateConfig,
    QualityGateDecision,
)
from ai.services.ai_quality_evaluator import AIQualityEvaluator
from scripts.benchmark_quality_suite import evaluate_metric


class TestBenchmarkGateEvaluator:
    """Test suite for evaluate_metric, QualityGate, and centralized gating logic."""

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
        assert res["value"] == 0.66

    def test_value_above_target_passes(self) -> None:
        """Verify that a value above target (75% >= 66%) produces status='PASS'."""
        res = evaluate_metric(0.75, 0.66, ">=")
        assert res["status"] == "PASS"
        assert res["passed"] is True

    def test_zero_score_handling(self) -> None:
        """Verify zero score fails for minimum metrics and passes for maximum metrics."""
        # Minimum metric (precision >= 0.80): 0.0 must FAIL
        res_min = evaluate_metric(0.0, 0.80, ">=")
        assert res_min["status"] == "FAIL"
        assert res_min["passed"] is False

        # Maximum metric (FPR <= 0.05): 0.0 must PASS
        res_max = evaluate_metric(0.0, 0.05, "<=")
        assert res_max["status"] == "PASS"
        assert res_max["passed"] is True

    def test_missing_measurement_fails(self) -> None:
        """Verify that None / missing values strictly produce status='FAIL' and passed=False."""
        res = evaluate_metric(None, 0.80, ">=")
        assert res["status"] == "FAIL"
        assert res["passed"] is False
        assert "Missing" in res.get("error", "")

    def test_nan_measurement_strictly_fails(self) -> None:
        """Verify that float('nan') strictly produces status='FAIL'."""
        res = evaluate_metric(float("nan"), 0.80, ">=")
        assert res["status"] == "FAIL"
        assert res["passed"] is False
        assert "NaN" in res.get("error", "")

    def test_positive_infinity_strictly_fails(self) -> None:
        """Verify that float('inf') strictly produces status='FAIL'."""
        res = evaluate_metric(float("inf"), 0.80, ">=")
        assert res["status"] == "FAIL"
        assert res["passed"] is False
        assert "Infinite" in res.get("error", "")

    def test_negative_infinity_strictly_fails(self) -> None:
        """Verify that float('-inf') strictly produces status='FAIL'."""
        res = evaluate_metric(float("-inf"), 0.05, "<=")
        assert res["status"] == "FAIL"
        assert res["passed"] is False
        assert "Infinite" in res.get("error", "")

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

    def test_strict_less_than_operator(self) -> None:
        """Verify operator '<' (e.g. latency < 100 ms)."""
        pass_res = evaluate_metric(99.9, 100.0, "<")
        assert pass_res["status"] == "PASS"
        assert pass_res["passed"] is True

        edge_res = evaluate_metric(100.0, 100.0, "<")
        assert edge_res["status"] == "FAIL"
        assert edge_res["passed"] is False

        fail_res = evaluate_metric(105.0, 100.0, "<")
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
        with pytest.raises(ValueError, match="Unsupported comparison operator"):
            evaluate_metric(10, 5, "~=")

    def test_invalid_threshold_raises_error(self) -> None:
        """Verify NaN or Infinite thresholds raise ValueError."""
        with pytest.raises(ValueError, match="cannot be NaN or Infinite"):
            QualityGate.evaluate("test", 0.5, float("nan"), ">=")

        with pytest.raises(ValueError, match="cannot be NaN or Infinite"):
            QualityGate.evaluate("test", 0.5, float("inf"), ">=")

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

    def test_quality_gate_evaluate_suite(self) -> None:
        """Verify QualityGate.evaluate_suite aggregate decision logic."""
        gate = QualityGate()
        thresholds = [
            MetricThreshold(metric_name="precision", threshold=0.85, operator=ComparisonOperator.GTE, mandatory=True),
            MetricThreshold(metric_name="recall", threshold=0.85, operator=ComparisonOperator.GTE, mandatory=True),
            MetricThreshold(metric_name="fpr", threshold=0.05, operator=ComparisonOperator.LTE, mandatory=True),
            MetricThreshold(metric_name="extra_info", threshold=0.50, operator=ComparisonOperator.GTE, mandatory=False),
        ]

        # Case 1: All mandatory pass
        good_measurements = {"precision": 0.90, "recall": 0.88, "fpr": 0.02, "extra_info": 0.40}
        decision = gate.evaluate_suite(good_measurements, configured_thresholds=thresholds, total_samples=10)
        assert decision.all_passed is True
        assert decision.mandatory_failed_count == 0
        assert decision.failed_count == 1  # extra_info failed, but is non-mandatory

        # Case 2: One mandatory fails
        bad_measurements = {"precision": 0.70, "recall": 0.88, "fpr": 0.02}
        bad_decision = gate.evaluate_suite(bad_measurements, configured_thresholds=thresholds, total_samples=10)
        assert bad_decision.all_passed is False
        assert bad_decision.mandatory_failed_count >= 1

    def test_zero_samples_strictly_fails_gate(self) -> None:
        """Verify that an evaluation with 0 samples strictly fails the gate."""
        gate = QualityGate()
        decision = gate.evaluate_suite({"precision": 1.0}, total_samples=0)
        assert decision.all_passed is False
        assert "sample count <= 0" in decision.summary

    def test_ai_quality_evaluator_empty_samples_fails(self) -> None:
        """Verify that AIQualityEvaluator.generate_quality_report fails when 0 samples are provided."""
        evaluator = AIQualityEvaluator()
        report = evaluator.generate_quality_report(
            clean_samples=[],
            defect_fixtures=[],
            provider_checks=[],
        )
        assert report.total_samples == 0
        assert report.passed_quality_thresholds is False
        assert report.precision == 0.0
        assert report.recall == 0.0
