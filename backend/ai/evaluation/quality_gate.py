"""Centralized Quality Gate Engine & Robust Metric Evaluation (P0 / Issue #210).

Provides:
1. `QualityGate`: Evaluator supporting standard operators (`gte`, `gt`, `lte`, `lt`, `eq`).
2. Mathematical bounds checking: Rejection of NaN, +inf, -inf, and invalid thresholds.
3. Explicit missing metric handling: None / omitted metrics strictly produce status='FAIL'.
4. Centralized threshold configurations (`QualityGateConfig`) for AI Quality, RAG Retrieval,
   Bug Detection, Code Review Grounding, and Test Generation.
5. Aggregate decision calculation: All mandatory metrics must pass for the gate to pass.
6. Zero-sample safety: Benchmarks with 0 evaluated samples strictly fail the gate.
"""

from __future__ import annotations

import math
from enum import Enum
from typing import Any, Dict, List, Literal, Optional, Union
from pydantic import BaseModel, Field


class ComparisonOperator(str, Enum):
    """Supported comparison operators for threshold evaluation."""

    GTE = ">="
    GT = ">"
    LTE = "<="
    LT = "<"
    EQ = "=="

    @classmethod
    def from_str(cls, op: str) -> "ComparisonOperator":
        norm = op.strip().lower()
        if norm in (">=", "gte", "ge"):
            return cls.GTE
        if norm in (">", "gt"):
            return cls.GT
        if norm in ("<=", "lte", "le"):
            return cls.LTE
        if norm in ("<", "lt"):
            return cls.LT
        if norm in ("==", "eq", "="):
            return cls.EQ
        raise ValueError(f"Unsupported comparison operator: {op}")


class MetricThreshold(BaseModel):
    """Configured threshold specification for a named quality metric."""

    metric_name: str
    threshold: float
    operator: ComparisonOperator = ComparisonOperator.GTE
    mandatory: bool = True
    description: Optional[str] = None


class MetricEvaluationResult(BaseModel):
    """The result of evaluating a single metric against its configured threshold."""

    metric_name: str
    value: Optional[float]
    threshold: float
    operator: str
    status: Literal["PASS", "FAIL"]
    passed: bool
    mandatory: bool = True
    error: Optional[str] = None
    reason: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dict matching legacy evaluate_metric return contract."""
        data: Dict[str, Any] = {
            "metric_name": self.metric_name,
            "value": self.value,
            "threshold": self.threshold,
            "operator": self.operator,
            "status": self.status,
            "passed": self.passed,
            "mandatory": self.mandatory,
        }
        if self.error:
            data["error"] = self.error
        if self.reason:
            data["reason"] = self.reason
        return data


class QualityGateDecision(BaseModel):
    """Aggregated decision for an entire benchmark evaluation suite."""

    all_passed: bool
    total_metrics: int
    passed_count: int
    failed_count: int
    mandatory_failed_count: int
    results: Dict[str, MetricEvaluationResult]
    summary: str


class QualityGateConfig(BaseModel):
    """Centralized quality gate thresholds across all platform intelligence features."""

    # 1. AI Quality & Defect Detection (Docs/week3.md §4.3)
    ai_quality_precision: MetricThreshold = Field(
        default_factory=lambda: MetricThreshold(
            metric_name="ai_quality_precision", threshold=0.80, operator=ComparisonOperator.GTE, mandatory=True
        )
    )
    ai_quality_recall: MetricThreshold = Field(
        default_factory=lambda: MetricThreshold(
            metric_name="ai_quality_recall", threshold=0.80, operator=ComparisonOperator.GTE, mandatory=True
        )
    )
    ai_quality_f1: MetricThreshold = Field(
        default_factory=lambda: MetricThreshold(
            metric_name="ai_quality_f1", threshold=0.80, operator=ComparisonOperator.GTE, mandatory=True
        )
    )
    ai_quality_fpr: MetricThreshold = Field(
        default_factory=lambda: MetricThreshold(
            metric_name="ai_quality_fpr", threshold=0.05, operator=ComparisonOperator.LTE, mandatory=True
        )
    )
    ai_quality_schema_conformance: MetricThreshold = Field(
        default_factory=lambda: MetricThreshold(
            metric_name="ai_quality_schema_conformance", threshold=0.95, operator=ComparisonOperator.GTE, mandatory=True
        )
    )

    # 2. RAG Retrieval Benchmarks (Gate 3)
    rag_hit_rate_at_5: MetricThreshold = Field(
        default_factory=lambda: MetricThreshold(
            metric_name="rag_hit_rate_at_5", threshold=0.80, operator=ComparisonOperator.GTE, mandatory=True
        )
    )
    rag_mrr: MetricThreshold = Field(
        default_factory=lambda: MetricThreshold(
            metric_name="rag_mrr", threshold=0.80, operator=ComparisonOperator.GTE, mandatory=True
        )
    )
    rag_precision_at_1: MetricThreshold = Field(
        default_factory=lambda: MetricThreshold(
            metric_name="rag_precision_at_1", threshold=0.70, operator=ComparisonOperator.GTE, mandatory=True
        )
    )
    rag_recall_at_5: MetricThreshold = Field(
        default_factory=lambda: MetricThreshold(
            metric_name="rag_recall_at_5", threshold=0.80, operator=ComparisonOperator.GTE, mandatory=True
        )
    )
    rag_latency_p50_ms: MetricThreshold = Field(
        default_factory=lambda: MetricThreshold(
            metric_name="rag_latency_p50_ms", threshold=100.0, operator=ComparisonOperator.LT, mandatory=True
        )
    )
    rag_latency_p95_ms: MetricThreshold = Field(
        default_factory=lambda: MetricThreshold(
            metric_name="rag_latency_p95_ms", threshold=250.0, operator=ComparisonOperator.LT, mandatory=True
        )
    )

    # 3. Bug Detection Quality Benchmark
    bug_detection_precision: MetricThreshold = Field(
        default_factory=lambda: MetricThreshold(
            metric_name="bug_detection_precision", threshold=0.85, operator=ComparisonOperator.GTE, mandatory=True
        )
    )
    bug_detection_recall: MetricThreshold = Field(
        default_factory=lambda: MetricThreshold(
            metric_name="bug_detection_recall", threshold=0.85, operator=ComparisonOperator.GTE, mandatory=True
        )
    )
    bug_detection_f1: MetricThreshold = Field(
        default_factory=lambda: MetricThreshold(
            metric_name="bug_detection_f1", threshold=0.85, operator=ComparisonOperator.GTE, mandatory=True
        )
    )
    bug_detection_fpr: MetricThreshold = Field(
        default_factory=lambda: MetricThreshold(
            metric_name="bug_detection_fpr", threshold=0.05, operator=ComparisonOperator.LTE, mandatory=True
        )
    )

    # 4. Code Review Grounding Benchmark
    review_grounding_accuracy: MetricThreshold = Field(
        default_factory=lambda: MetricThreshold(
            metric_name="review_grounding_accuracy", threshold=1.0, operator=ComparisonOperator.EQ, mandatory=True
        )
    )
    review_hallucination_rate: MetricThreshold = Field(
        default_factory=lambda: MetricThreshold(
            metric_name="review_hallucination_rate", threshold=0.0, operator=ComparisonOperator.EQ, mandatory=True
        )
    )

    # 5. Test Generation Benchmark
    testgen_safety_rejection_rate: MetricThreshold = Field(
        default_factory=lambda: MetricThreshold(
            metric_name="testgen_safety_rejection_rate", threshold=1.0, operator=ComparisonOperator.EQ, mandatory=True
        )
    )
    testgen_syntax_validity_rate: MetricThreshold = Field(
        default_factory=lambda: MetricThreshold(
            metric_name="testgen_syntax_validity_rate", threshold=0.66, operator=ComparisonOperator.GTE, mandatory=True
        )
    )
    testgen_assertion_presence_rate: MetricThreshold = Field(
        default_factory=lambda: MetricThreshold(
            metric_name="testgen_assertion_presence_rate", threshold=0.66, operator=ComparisonOperator.GTE, mandatory=True
        )
    )

    # 6. Mini SWE-bench Agent Benchmark
    swebench_pass_at_1: MetricThreshold = Field(
        default_factory=lambda: MetricThreshold(
            metric_name="swebench_pass_at_1", threshold=0.50, operator=ComparisonOperator.GTE, mandatory=True
        )
    )
    swebench_reproduction_rate: MetricThreshold = Field(
        default_factory=lambda: MetricThreshold(
            metric_name="swebench_reproduction_rate", threshold=0.80, operator=ComparisonOperator.GTE, mandatory=True
        )
    )


class QualityGate:
    """Robust Quality Gate Evaluator for benchmarks and CI quality thresholds."""

    def __init__(self, config: Optional[QualityGateConfig] = None) -> None:
        self.config = config or QualityGateConfig()

    @staticmethod
    def evaluate(
        metric_name: str,
        actual: Optional[Union[float, int]],
        threshold: Union[float, int],
        comparison: str = ">=",
        mandatory: bool = True,
    ) -> MetricEvaluationResult:
        """Evaluate a single metric against a threshold with complete mathematical validation.
        
        Guarantees:
        - None / missing values strictly produce status='FAIL'.
        - NaN values strictly produce status='FAIL'.
        - Infinite values (+inf / -inf) strictly produce status='FAIL'.
        - Values below threshold (for '>=') strictly produce status='FAIL'.
        - Values equal to threshold (for '>=') strictly produce status='PASS'.
        - Values above threshold (for '<=') strictly produce status='FAIL'.
        - Unsupported operator raises ValueError.
        """
        # Validate operator
        op_enum = ComparisonOperator.from_str(comparison)
        op_str = op_enum.value

        # Validate threshold
        if threshold is None or not isinstance(threshold, (int, float)):
            raise ValueError(f"Invalid threshold for metric '{metric_name}': {threshold}")
        if math.isnan(threshold) or math.isinf(threshold):
            raise ValueError(f"Threshold for metric '{metric_name}' cannot be NaN or Infinite: {threshold}")

        # Check missing measurement
        if actual is None:
            return MetricEvaluationResult(
                metric_name=metric_name,
                value=None,
                threshold=float(threshold),
                operator=op_str,
                status="FAIL",
                passed=False,
                mandatory=mandatory,
                error="Missing measurement value",
                reason=f"Metric '{metric_name}' was not recorded (value is None).",
            )

        # Validate float/int type
        if not isinstance(actual, (int, float)) or isinstance(actual, bool):
            return MetricEvaluationResult(
                metric_name=metric_name,
                value=None,
                threshold=float(threshold),
                operator=op_str,
                status="FAIL",
                passed=False,
                mandatory=mandatory,
                error=f"Invalid metric value type: {type(actual).__name__}",
                reason=f"Metric '{metric_name}' must be a numeric value.",
            )

        # Reject NaN
        if math.isnan(actual):
            return MetricEvaluationResult(
                metric_name=metric_name,
                value=None,
                threshold=float(threshold),
                operator=op_str,
                status="FAIL",
                passed=False,
                mandatory=mandatory,
                error="Invalid metric value: NaN",
                reason=f"Metric '{metric_name}' evaluated to NaN.",
            )

        # Reject Infinity
        if math.isinf(actual):
            return MetricEvaluationResult(
                metric_name=metric_name,
                value=None,
                threshold=float(threshold),
                operator=op_str,
                status="FAIL",
                passed=False,
                mandatory=mandatory,
                error="Invalid metric value: Infinite",
                reason=f"Metric '{metric_name}' evaluated to infinite ({actual}).",
            )

        actual_f = float(actual)
        threshold_f = float(threshold)

        # Evaluate comparison
        passed: bool = False
        if op_enum == ComparisonOperator.GTE:
            passed = actual_f >= threshold_f
        elif op_enum == ComparisonOperator.GT:
            passed = actual_f > threshold_f
        elif op_enum == ComparisonOperator.LTE:
            passed = actual_f <= threshold_f
        elif op_enum == ComparisonOperator.LT:
            passed = actual_f < threshold_f
        elif op_enum == ComparisonOperator.EQ:
            passed = math.isclose(actual_f, threshold_f, abs_tol=1e-5)

        status: Literal["PASS", "FAIL"] = "PASS" if passed else "FAIL"
        reason = (
            f"Metric '{metric_name}'={actual_f} satisfied threshold {op_str} {threshold_f}."
            if passed
            else f"Metric '{metric_name}'={actual_f} failed threshold {op_str} {threshold_f}."
        )

        return MetricEvaluationResult(
            metric_name=metric_name,
            value=actual_f,
            threshold=threshold_f,
            operator=op_str,
            status=status,
            passed=passed,
            mandatory=mandatory,
            reason=reason,
        )

    def evaluate_metric(
        self,
        value: Optional[Union[float, int]],
        threshold: Union[float, int],
        operator: str = ">=",
        metric_name: str = "metric",
        mandatory: bool = True,
    ) -> MetricEvaluationResult:
        """Instance method wrapping static evaluate()."""
        return self.evaluate(
            metric_name=metric_name,
            actual=value,
            threshold=threshold,
            comparison=operator,
            mandatory=mandatory,
        )

    def evaluate_suite(
        self,
        measurements: Dict[str, Optional[Union[float, int]]],
        configured_thresholds: Optional[List[MetricThreshold]] = None,
        total_samples: Optional[int] = None,
    ) -> QualityGateDecision:
        """Evaluate an entire dictionary of benchmark measurements against thresholds."""
        # Zero samples strictly fail closed
        if total_samples is not None and total_samples <= 0:
            return QualityGateDecision(
                all_passed=False,
                total_metrics=0,
                passed_count=0,
                failed_count=1,
                mandatory_failed_count=1,
                results={},
                summary="Quality gate FAILED: No evaluation samples were provided (sample count <= 0).",
            )

        thresholds = configured_thresholds or []
        # If no explicit list passed, match against all config fields
        if not thresholds:
            for field_name, val in self.config:
                if isinstance(val, MetricThreshold):
                    thresholds.append(val)

        results: Dict[str, MetricEvaluationResult] = {}
        passed_count = 0
        failed_count = 0
        mandatory_failed = 0

        for mt in thresholds:
            actual = measurements.get(mt.metric_name)
            res = self.evaluate(
                metric_name=mt.metric_name,
                actual=actual,
                threshold=mt.threshold,
                comparison=mt.operator.value,
                mandatory=mt.mandatory,
            )
            results[mt.metric_name] = res
            if res.passed:
                passed_count += 1
            else:
                failed_count += 1
                if mt.mandatory:
                    mandatory_failed += 1

        all_passed = mandatory_failed == 0 and len(results) > 0
        status_word = "PASSED" if all_passed else "FAILED"
        summary = (
            f"Quality gate {status_word}: {passed_count}/{len(results)} metrics passed. "
            f"Mandatory failures: {mandatory_failed}."
        )

        return QualityGateDecision(
            all_passed=all_passed,
            total_metrics=len(results),
            passed_count=passed_count,
            failed_count=failed_count,
            mandatory_failed_count=mandatory_failed,
            results=results,
            summary=summary,
        )


__all__ = [
    "ComparisonOperator",
    "MetricThreshold",
    "MetricEvaluationResult",
    "QualityGateDecision",
    "QualityGateConfig",
    "QualityGate",
]
