"""Unit tests for Week 3 Day 6 AI Quality Evaluation and Provider Validation.

Owner: Dev — Week 3 Day 6 Deliverable (Docs/daily_tasks.md line 664 & Docs/week3.md §4.1, §6)

What these tests verify in simple words:
1. Provider policy: Make sure only Google Gemini and Groq are allowed; OpenAI or others must be rejected.
2. Gateway resilience: Make sure unconfigured or missing providers fail safely with HTTP 503 instead of crashing.
3. Fallback support: Make sure switching to fallback provider during outages is properly detected.
4. Clean code tests: Verify that the AI does NOT raise false alarms on clean, bug-free code (0.0% false positives).
5. Defect detection: Verify that the AI correctly catches real bugs (measuring Precision and Recall).
6. Schema conformance: Verify that the AI's output can be safely parsed into our data schemas even if wrapped in markdown.
7. Quality report: Verify that a complete AI Quality Report is generated with accurate benchmark statistics.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock
import pytest
from pydantic import BaseModel, Field

from ai.services.ai_quality_evaluator import AIQualityEvaluator
from app.core.errors import APIError, ErrorCode
from app.schemas.ai_quality import (
    AIQualityReport,
    ProviderValidationCheck,
    QualityBenchmarkSample,
)


# ---------------------------------------------------------------------------
# Simple Test Schemas & Mock Objects
# ---------------------------------------------------------------------------

class SampleOutputSchema(BaseModel):
    """Simple test schema to check JSON parsing and validation."""

    analysis_id: str = Field(..., description="Unique ID.")
    summary: str = Field(..., description="Brief summary.")
    score: float = Field(default=1.0, ge=0.0, le=1.0)


class MockProvider:
    """Fake LLM provider used to test policy checks without making real network calls."""

    def __init__(self, name: str, default_model: str = "test-model-1") -> None:
        self.provider_name = name
        self.default_model = default_model


class MockGateway:
    """Fake LLM Gateway holding a primary provider and optional fallback."""

    def __init__(
        self,
        provider: Any,
        fallback_provider: Any = None,
        fallback_active: bool = False,
    ) -> None:
        self.provider = provider
        self.fallback_provider = fallback_provider
        self.fallback_active = fallback_active
        self.provider_name = getattr(provider, "provider_name", "none")


# ---------------------------------------------------------------------------
# 1. Provider Policy Validation Tests (Gemini & Groq Allowed, Others Blocked)
# ---------------------------------------------------------------------------

def test_provider_validation_accepts_gemini():
    """Verify that Google Gemini is permitted by platform policy.

    Simple explanation:
    Gemini is an approved provider. The check should mark it as VALID and is_allowed=True.
    """
    evaluator = AIQualityEvaluator()
    gateway = MockGateway(provider=MockProvider(name="gemini", default_model="gemini-1.5-pro"))

    check = evaluator.validate_provider(gateway)

    assert check.status == "VALID"
    assert check.is_allowed is True
    assert check.is_healthy is True
    assert check.provider_name == "gemini"
    assert "gemini-1.5-pro" in check.active_model


def test_provider_validation_accepts_groq():
    """Verify that Groq is permitted by platform policy.

    Simple explanation:
    Groq is also an approved provider. The check should mark it as VALID and is_allowed=True.
    """
    evaluator = AIQualityEvaluator()
    gateway = MockGateway(provider=MockProvider(name="groq", default_model="llama-3.3-70b-versatile"))

    check = evaluator.validate_provider(gateway)

    assert check.status == "VALID"
    assert check.is_allowed is True
    assert check.is_healthy is True
    assert check.provider_name == "groq"


def test_provider_validation_rejects_openai():
    """Docs/week3.md §4.1: Only Gemini and Groq are permitted. OpenAI must be rejected.

    Simple explanation:
    If someone configures OpenAI, the validator must block it as INVALID_PROVIDER.
    """
    evaluator = AIQualityEvaluator()
    gateway = MockGateway(provider=MockProvider(name="openai", default_model="gpt-4o"))

    check = evaluator.validate_provider(gateway)

    assert check.status == "INVALID_PROVIDER"
    assert check.is_allowed is False
    assert check.is_healthy is False
    assert "not permitted by policy" in check.message


def test_provider_validation_rejects_unapproved_providers():
    """Verify other third-party providers (Anthropic, DeepSeek) are blocked.

    Simple explanation:
    Any provider other than Gemini or Groq must be rejected to prevent unauthorized costs.
    """
    evaluator = AIQualityEvaluator()
    for unapproved in ["anthropic", "deepseek", "ollama", "cohere"]:
        gateway = MockGateway(provider=MockProvider(name=unapproved))
        check = evaluator.validate_provider(gateway)
        assert check.is_allowed is False
        assert check.status == "INVALID_PROVIDER"


def test_enforce_provider_policy_raises_http_400_on_invalid_provider():
    """Verify that enforce_provider_policy immediately raises an HTTP 400 error.

    Simple explanation:
    If an analysis request is made with OpenAI, the server must stop execution and return HTTP 400.
    """
    evaluator = AIQualityEvaluator()
    gateway = MockGateway(provider=MockProvider(name="openai"))

    with pytest.raises(APIError) as exc_info:
        evaluator.enforce_provider_policy(gateway)

    assert exc_info.value.status_code == 400
    assert exc_info.value.code == ErrorCode.INVALID_REQUEST
    assert "not permitted by policy" in exc_info.value.message


def test_provider_validation_handles_missing_gateway():
    """Verify unconfigured or None gateway fails closed with SERVICE_UNAVAILABLE.

    Simple explanation:
    If the gateway wasn't set up, fail gracefully with an HTTP 503 instead of crashing.
    """
    evaluator = AIQualityEvaluator()

    check = evaluator.validate_provider(None)

    assert check.status == "SERVICE_UNAVAILABLE"
    assert check.is_allowed is False
    assert check.is_healthy is False

    # Check that enforcement raises HTTP 503
    with pytest.raises(APIError) as exc_info:
        evaluator.enforce_provider_policy(None)
    assert exc_info.value.status_code == 503
    assert exc_info.value.code == ErrorCode.SERVICE_UNAVAILABLE


def test_provider_validation_detects_active_fallback():
    """Verify that during primary outages, the active fallback is identified.

    Simple explanation:
    If Gemini is having an outage and Groq steps in as a backup, report FALLBACK_ACTIVE.
    """
    evaluator = AIQualityEvaluator()
    primary = MockProvider(name="gemini")
    fallback = MockProvider(name="groq")
    gateway = MockGateway(provider=primary, fallback_provider=fallback, fallback_active=True)

    check = evaluator.validate_provider(gateway)

    assert check.status == "FALLBACK_ACTIVE"
    assert check.is_allowed is True
    assert check.is_healthy is True
    assert "fallback provider 'groq' is active" in check.message


# ---------------------------------------------------------------------------
# 2. Clean-Code False-Positive Benchmark Tests (Zero False Positives Target)
# ---------------------------------------------------------------------------

def test_clean_samples_achieve_zero_false_positives():
    """Verify that analyzing clean code results in 0.0% false-positive rate.

    Simple explanation:
    When testing clean math or utility code, the AI should find 0 bugs.
    If it reports 0 bugs across all samples, the false-positive rate is 0.0%.
    """
    evaluator = AIQualityEvaluator()
    clean_samples = [
        {"sample_id": "clean-math-1", "detected_defects": []},
        {"sample_id": "clean-string-2", "detected_defects": []},
        {"sample_id": "clean-sorting-3", "detected_defects": []},
        {"sample_id": "clean-helper-4", "detected_defects": []},
    ]

    results, fp_rate = evaluator.evaluate_clean_samples(clean_samples)

    assert len(results) == 4
    assert fp_rate == 0.0  # Perfect score: 0 false alarms!
    for sample in results:
        assert sample.is_false_positive is False
        assert sample.sample_type == "clean_baseline"


def test_clean_samples_detects_false_positive_if_bug_hallucinated():
    """Verify that if the AI falsely flags a bug in clean code, it is caught as a false alarm.

    Simple explanation:
    If clean code gets wrongly flagged with a 'null_safety' bug, our evaluator must
    record is_false_positive=True and raise the false-positive rate.
    """
    evaluator = AIQualityEvaluator()
    clean_samples = [
        {"sample_id": "clean-math-1", "detected_defects": []},
        {"sample_id": "clean-math-2", "detected_defects": ["null_safety"]},  # False alarm!
    ]

    results, fp_rate = evaluator.evaluate_clean_samples(clean_samples)

    assert fp_rate == 0.5  # 1 out of 2 had a false positive (50%)
    assert results[0].is_false_positive is False
    assert results[1].is_false_positive is True


# ---------------------------------------------------------------------------
# 3. Defect Fixture Evaluation Tests (Precision, Recall, F1)
# ---------------------------------------------------------------------------

def test_defect_fixtures_precision_recall_calculation():
    """Verify accurate calculation of Precision, Recall, and F1 scores.

    Simple explanation:
    - Sample 1: Has 'off_by_one' -> AI detected 'off_by_one' (True Positive).
    - Sample 2: Has 'null_safety' -> AI detected 'null_safety' (True Positive).
    - Sample 3: Has 'resource_leak' -> AI missed it (False Negative).
    With 2 TPs and 1 FN, Recall should be 2/3 (66.7%), Precision should be 100%.
    """
    evaluator = AIQualityEvaluator()
    fixtures = [
        {
            "sample_id": "defect-1",
            "expected_defects": ["off_by_one"],
            "detected_defects": ["off_by_one"],
        },
        {
            "sample_id": "defect-2",
            "expected_defects": ["null_safety"],
            "detected_defects": ["null_safety"],
        },
        {
            "sample_id": "defect-3",
            "expected_defects": ["resource_leak"],
            "detected_defects": [],  # Missed defect
        },
    ]

    results, precision, recall, f1 = evaluator.evaluate_defect_fixtures(fixtures)

    assert len(results) == 3
    assert precision == 1.0  # 100% precision: every bug reported was real
    assert abs(recall - (2 / 3)) < 0.01  # Caught 2 out of 3 bugs (~66.7%)
    assert f1 > 0.0
    assert results[0].is_true_positive is True
    assert results[2].is_false_negative is True


# ---------------------------------------------------------------------------
# 4. Schema Conformance & Self-Healing JSON Repair Tests
# ---------------------------------------------------------------------------

def test_schema_conformance_handles_clean_and_fenced_json():
    """Verify that clean JSON and markdown-fenced JSON parse into Pydantic models.

    Simple explanation:
    AI models often reply with ```json ... ```. Our evaluator tests that
    markdown fences are automatically stripped and the data validates into the schema.
    """
    evaluator = AIQualityEvaluator()
    valid_raw_json = '{"analysis_id": "id-1", "summary": "Clean test", "score": 0.95}'
    fenced_json = """```json
{
  "analysis_id": "id-2",
  "summary": "Fenced test",
  "score": 0.88
}
```"""
    invalid_json = "This is just random text with no JSON at all!"

    # Test with 2 valid outputs (one raw, one fenced) and 1 invalid output
    conformance_rate = evaluator.evaluate_schema_conformance(
        raw_outputs=[valid_raw_json, fenced_json, invalid_json],
        schema_cls=SampleOutputSchema,
    )

    # 2 out of 3 succeeded -> ~66.7% conformance rate
    assert abs(conformance_rate - (2 / 3)) < 0.01

    # Test with 100% valid outputs
    perfect_rate = evaluator.evaluate_schema_conformance(
        raw_outputs=[valid_raw_json, fenced_json],
        schema_cls=SampleOutputSchema,
    )
    assert perfect_rate == 1.0


# ---------------------------------------------------------------------------
# 5. Full Quality Report Compilation Tests
# ---------------------------------------------------------------------------

def test_generate_quality_report_comprehensive_metrics():
    """Verify compilation of the complete AIQualityReport data model.

    Simple explanation:
    Tests that the report combines clean samples, defect samples, provider checks,
    and schema conformance into an executive summary report with passing thresholds.
    """
    evaluator = AIQualityEvaluator()
    clean_samples = [
        {"sample_id": "c-1", "detected_defects": []},
        {"sample_id": "c-2", "detected_defects": []},
    ]
    defect_fixtures = [
        {
            "sample_id": "d-1",
            "expected_defects": ["null_safety"],
            "detected_defects": ["null_safety"],
        },
        {
            "sample_id": "d-2",
            "expected_defects": ["off_by_one"],
            "detected_defects": ["off_by_one"],
        },
    ]
    provider_checks = [
        ProviderValidationCheck(
            provider_name="gemini",
            status="VALID",
            is_allowed=True,
            is_healthy=True,
            active_model="gemini-1.5-pro",
            message="Authorized.",
        )
    ]

    report = evaluator.generate_quality_report(
        clean_samples=clean_samples,
        defect_fixtures=defect_fixtures,
        provider_checks=provider_checks,
        schema_conformance_rate=1.0,
    )

    assert report.total_samples == 4
    assert report.clean_samples_count == 2
    assert report.defect_samples_count == 2
    assert report.false_positive_count == 0
    assert report.false_positive_rate == 0.0
    assert report.precision == 1.0
    assert report.recall == 1.0
    assert report.f1_score == 1.0
    assert report.schema_conformance_rate == 1.0
    assert report.passed_quality_thresholds is True
    assert "Precision=100.0%" in report.summary
    assert "False Positive Rate=0.0%" in report.summary

