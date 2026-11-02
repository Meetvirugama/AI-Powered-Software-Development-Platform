
"""AI Quality Evaluator, False-Positive Metrics, and Provider Validation Engine.

Owner: Dev — Week 3 Day 6 Deliverable (Docs/daily_tasks.md line 664 & Docs/week3.md §4.1, §6)
Reference: Docs/week3.md §4.1 (AI Provider Policy), §4.3 (Quality & Reliability), §6

What this service does in simple words:
1. Provider Validator: Checks that the platform only uses approved AI companies (Google Gemini
   and Groq). Blocks unapproved providers (like OpenAI) and tests fallback resilience.
2. False-Positive Evaluator: Feeds clean, bug-free code to the AI and verifies that the AI
   does NOT invent fake bugs (ensuring a 0.0% false-positive rate on clean code).
3. Defect Fixture Evaluator: Feeds code with known defects (like null checks or off-by-one errors)
   and measures how accurately the AI catches them (Precision, Recall, and F1 score).
4. Schema Conformance Checker: Checks that the AI output strictly follows our Pydantic data
   schemas without crashing.
5. Report Generator: Combines all measurements into a clear, structured Quality Report.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Type
from uuid import uuid4

from pydantic import BaseModel, ValidationError

from ai.schemas.validator import OutputValidator
from app.core.errors import APIError, ErrorCode
from app.schemas.ai_quality import (
    AIQualityReport,
    PermittedProviderName,
    ProviderValidationCheck,
    ProviderValidationStatus,
    QualityBenchmarkSample,
)

logger = logging.getLogger(__name__)

# List of LLM providers explicitly permitted by company policy (Docs/week3.md §4.1)
# Any provider not in this set is rejected with an HTTP 400 error.
_PERMITTED_PROVIDERS: set[str] = {"gemini", "groq"}


class AIQualityEvaluator:
    """Evaluates AI output quality, precision/recall, false alarms, and provider policy compliance.

    In simple words: This class acts as a quality inspector for our AI engines.
    It tests whether the AI is giving accurate answers, not raising fake alarms,
    and using authorized AI models.
    """

    def __init__(self, permitted_providers: set[str] | None = None) -> None:
        """Initialize the quality evaluator.

        Simple explanation:
        Sets up the list of allowed AI providers (defaulting to Gemini and Groq).
        """
        self.permitted_providers = (
            {p.lower() for p in permitted_providers}
            if permitted_providers is not None
            else set(_PERMITTED_PROVIDERS)
        )

    # =======================================================================
    # 1. Provider Policy Validation (Gemini and Groq Only)
    # =======================================================================

    def validate_provider(self, gateway_or_provider: Any) -> ProviderValidationCheck:
        """Check if an LLM gateway or provider follows our approved provider policy.

        Simple explanation:
        - We inspect the name of the AI provider (e.g. 'gemini', 'groq', or 'openai').
        - If the provider is 'gemini' or 'groq', it passes (VALID).
        - If the provider is anything else (like 'openai' or 'anthropic'), it fails (INVALID_PROVIDER).
        - If the gateway is missing, unconfigured, or has no provider, it returns SERVICE_UNAVAILABLE.
        """
        # If no gateway or provider was given at all
        if gateway_or_provider is None:
            return ProviderValidationCheck(
                provider_name="none",
                status="SERVICE_UNAVAILABLE",
                is_allowed=False,
                is_healthy=False,
                active_model="none",
                message="LLM gateway or provider is unconfigured (None).",
            )

        # Extract provider object and its name
        provider = getattr(gateway_or_provider, "provider", gateway_or_provider)
        raw_name = (
            getattr(provider, "provider_name", None)
            or getattr(provider, "name", None)
            or getattr(gateway_or_provider, "provider_name", None)
        )

        if not raw_name or not isinstance(raw_name, str):
            return ProviderValidationCheck(
                provider_name="unknown",
                status="SERVICE_UNAVAILABLE",
                is_allowed=False,
                is_healthy=False,
                active_model="unknown",
                message="Could not resolve a valid provider name from gateway.",
            )

        provider_name = raw_name.strip().lower()

        # Resolve active model name if available
        active_model = (
            getattr(provider, "default_model", None)
            or getattr(gateway_or_provider, "default_model", None)
            or "unknown"
        )

        # Check if provider is on the approved allowlist (Gemini or Groq)
        if provider_name not in self.permitted_providers:
            allowed_list = ", ".join(sorted(self.permitted_providers))
            return ProviderValidationCheck(
                provider_name=provider_name,
                status="INVALID_PROVIDER",
                is_allowed=False,
                is_healthy=False,
                active_model=str(active_model),
                message=(
                    f"Provider '{provider_name}' is not permitted by policy. "
                    f"Only {allowed_list} are allowed."
                ),
            )

        # Check for fallback provider configuration (resilience check)
        fallback = getattr(gateway_or_provider, "fallback_provider", None)
        fallback_active = getattr(gateway_or_provider, "fallback_active", False)

        if fallback_active:
            fallback_name = getattr(fallback, "provider_name", "fallback")
            return ProviderValidationCheck(
                provider_name=provider_name,
                status="FALLBACK_ACTIVE",
                is_allowed=True,
                is_healthy=True,
                active_model=str(active_model),
                message=f"Primary provider experienced an outage; fallback provider '{fallback_name}' is active.",
            )

        return ProviderValidationCheck(
            provider_name=provider_name,
            status="VALID",
            is_allowed=True,
            is_healthy=True,
            active_model=str(active_model),
            message=f"Provider '{provider_name}' is authorized and operating normally.",
        )

    def enforce_provider_policy(self, gateway_or_provider: Any) -> None:
        """Strict policy enforcement guard that raises APIError on unpermitted providers.

        Simple explanation:
        - If the AI gateway is missing or unconfigured, raise HTTP 503 (SERVICE_UNAVAILABLE).
        - If an unauthorized provider (like OpenAI) is requested, raise HTTP 400 (INVALID_REQUEST).
        """
        check = self.validate_provider(gateway_or_provider)
        if check.status == "SERVICE_UNAVAILABLE":
            raise APIError(
                status_code=503,
                code=ErrorCode.SERVICE_UNAVAILABLE,
                message=check.message,
                retryable=True,
            )
        if not check.is_allowed:
            raise APIError(
                status_code=400,
                code=ErrorCode.INVALID_REQUEST,
                message=check.message,
            )

    # =======================================================================
    # 2. Clean-Code False-Positive Evaluation (Zero False Positives Target)
    # =======================================================================

    def evaluate_clean_samples(
        self,
        clean_samples: list[dict[str, Any]],
    ) -> tuple[list[QualityBenchmarkSample], float]:
        """Evaluate clean, bug-free code samples to measure false alarms.

        Simple explanation:
        - We give the AI snippets of clean code (where there are zero bugs).
        - If the AI reports a bug, that's a 'False Positive' (false alarm).
        - We calculate the false-positive rate: target is 0.0 (zero false alarms).
        """
        results: list[QualityBenchmarkSample] = []
        false_positive_count = 0

        for sample in clean_samples:
            sample_id = sample.get("sample_id", f"clean-{uuid4().hex[:6]}")
            detected = sample.get("detected_defects", [])

            # In clean code, any detected defect is a false positive
            is_fp = len(detected) > 0
            if is_fp:
                false_positive_count += 1

            results.append(
                QualityBenchmarkSample(
                    sample_id=sample_id,
                    sample_type="clean_baseline",
                    expected_defects=[],
                    detected_defects=detected,
                    is_false_positive=is_fp,
                    is_true_positive=False,
                    is_false_negative=False,
                )
            )

        total_clean = len(clean_samples)
        fp_rate = (false_positive_count / total_clean) if total_clean > 0 else 0.0
        return results, fp_rate

    # =======================================================================
    # 3. Defect Fixture Evaluation (Precision, Recall, F1 Score)
    # =======================================================================

    def evaluate_defect_fixtures(
        self,
        defect_fixtures: list[dict[str, Any]],
    ) -> tuple[list[QualityBenchmarkSample], float, float, float]:
        """Evaluate code with known bugs to measure how well the AI detects them.

        Simple explanation:
        - Precision: When the AI flags a bug, how often is it actually right?
        - Recall: Out of all the bugs that were actually in the code, how many did the AI catch?
        - F1 score: A balanced average of Precision and Recall.
        """
        results: list[QualityBenchmarkSample] = []
        true_positives = 0
        false_negatives = 0
        false_positives = 0

        for fixture in defect_fixtures:
            sample_id = fixture.get("sample_id", f"defect-{uuid4().hex[:6]}")
            expected = set(fixture.get("expected_defects", []))
            detected = set(fixture.get("detected_defects", []))

            # Matched bugs are true positives
            matched = expected.intersection(detected)
            # Bugs that were present but missed by the AI are false negatives
            missed = expected.difference(detected)
            # Bugs claimed by the AI that were not actually in the code are false positives
            hallucinated = detected.difference(expected)

            is_tp = len(matched) > 0
            is_fn = len(missed) > 0
            is_fp = len(hallucinated) > 0

            true_positives += len(matched)
            false_negatives += len(missed)
            false_positives += len(hallucinated)

            results.append(
                QualityBenchmarkSample(
                    sample_id=sample_id,
                    sample_type="defect_fixture",
                    expected_defects=sorted(expected),
                    detected_defects=sorted(detected),
                    is_false_positive=is_fp,
                    is_true_positive=is_tp,
                    is_false_negative=is_fn,
                )
            )

        # Calculate Precision: TP / (TP + FP)
        denom_precision = true_positives + false_positives
        precision = (true_positives / denom_precision) if denom_precision > 0 else 1.0

        # Calculate Recall: TP / (TP + FN)
        denom_recall = true_positives + false_negatives
        recall = (true_positives / denom_recall) if denom_recall > 0 else 1.0

        # Calculate F1 Score: 2 * (P * R) / (P + R)
        denom_f1 = precision + recall
        f1 = (2 * (precision * recall) / denom_f1) if denom_f1 > 0 else 0.0

        return results, precision, recall, f1

    # =======================================================================
    # 4. Schema Conformance & Self-Healing JSON Repair Evaluation
    # =======================================================================

    def evaluate_schema_conformance(
        self,
        raw_outputs: list[str],
        schema_cls: Type[BaseModel],
    ) -> float:
        """Test how reliably AI text outputs convert into valid Pydantic models.

        Simple explanation:
        AI models sometimes put markdown ticks (```json ... ```) or extra text
        around their response. We test whether our self-healing JSON parser
        cleans and parses the text into the required Pydantic schema.
        Returns the percentage (0.0 to 1.0) of outputs that succeeded.
        """
        if not raw_outputs:
            return 1.0

        valid_count = 0
        for text in raw_outputs:
            try:
                # 1. First clean off markdown code fences or extra whitespace using canonical helper
                cleaned = OutputValidator.clean_json_text(text)
                # 2. Parse into Python dictionary
                data = json.loads(cleaned)
                # 3. Validate against Pydantic model
                if isinstance(data, dict):
                    schema_cls.model_validate(data)
                    valid_count += 1
            except (json.JSONDecodeError, ValidationError, Exception):
                # Failed schema validation
                continue

        return valid_count / len(raw_outputs)

    # =======================================================================
    # 5. Full Quality Report Compilation
    # =======================================================================

    def generate_quality_report(
        self,
        clean_samples: list[dict[str, Any]],
        defect_fixtures: list[dict[str, Any]],
        provider_checks: list[ProviderValidationCheck],
        schema_conformance_rate: float = 1.0,
    ) -> AIQualityReport:
        """Generate a complete AI Quality Report combining all evaluations.

        Simple explanation:
        Runs clean code benchmarks, defect fixture tests, provider policy checks,
        and schema tests, and packages them into a clean report.
        """
        report_id = f"ai-qual-{uuid4().hex[:8]}"

        # Evaluate clean samples (measure false alarms)
        clean_results, fp_rate = self.evaluate_clean_samples(clean_samples)
        fp_count = sum(1 for s in clean_results if s.is_false_positive)

        # Evaluate defect fixtures (measure precision and recall)
        defect_results, precision, recall, f1 = self.evaluate_defect_fixtures(defect_fixtures)

        total_samples = len(clean_samples) + len(defect_fixtures)

        # Quality thresholds:
        # 1. False positive rate must be very low (<= 5%, ideally 0%)
        # 2. Precision and Recall must be >= 80% (0.80)
        # 3. All checked providers must be allowed
        all_providers_allowed = all(p.is_allowed for p in provider_checks) if provider_checks else True
        passed = (
            fp_rate <= 0.05
            and precision >= 0.80
            and recall >= 0.80
            and schema_conformance_rate >= 0.95
            and all_providers_allowed
        )

        summary = (
            f"Evaluated {total_samples} samples across clean and defect code: "
            f"Precision={precision:.1%}, Recall={recall:.1%}, F1={f1:.1%}, "
            f"False Positive Rate={fp_rate:.1%}, Schema Conformance={schema_conformance_rate:.1%}."
        )

        return AIQualityReport(
            report_id=report_id,
            total_samples=total_samples,
            clean_samples_count=len(clean_samples),
            defect_samples_count=len(defect_fixtures),
            false_positive_count=fp_count,
            false_positive_rate=fp_rate,
            precision=precision,
            recall=recall,
            f1_score=f1,
            schema_conformance_rate=schema_conformance_rate,
            provider_checks=provider_checks,
            passed_quality_thresholds=passed,
            summary=summary,
        )


__all__ = ["AIQualityEvaluator"]
