"""AI Quality Evaluation, False-Positive Metrics, and Provider Validation Schemas.

Owner: Dev — Week 3 Day 6 Deliverable (Docs/daily_tasks.md line 664 & Docs/week3.md §4.1, §6)
Reference: Docs/week3.md §4.1 (AI Provider Policy), §4.3 (Quality & Reliability), §6

What this file does in simple words:
1. Defines the data models for measuring how accurate our AI models are.
2. Tracks 'False Positives' (meaning when the AI wrongly claims there is a bug in clean code).
3. Defines validation schemas for our two permitted AI providers: Gemini and Groq.
4. Produces a structured Quality Report showing precision, recall, and reliability scores.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

# Valid provider policy statuses
ProviderValidationStatus = Literal[
    "VALID",
    "INVALID_PROVIDER",
    "SERVICE_UNAVAILABLE",
    "FALLBACK_ACTIVE",
]

# Supported LLM providers by policy (Docs/week3.md §4.1)
PermittedProviderName = Literal["gemini", "groq"]


class ProviderValidationCheck(BaseModel):
    """Result of checking an LLM provider against platform policies.

    Simple explanation:
    We check which AI company is being used (e.g. Google Gemini or Groq).
    Our project rules ONLY allow Gemini and Groq. If anyone tries to use OpenAI
    or an unapproved provider, this check flags it as invalid.
    """

    model_config = ConfigDict(from_attributes=True)

    # Name of the provider being tested (e.g. 'gemini', 'groq', 'openai')
    provider_name: str = Field(..., description="Name of the LLM provider being checked.")

    # Status result: VALID, INVALID_PROVIDER, SERVICE_UNAVAILABLE, or FALLBACK_ACTIVE
    status: ProviderValidationStatus = Field(
        ...,
        description="Status verdict: VALID, INVALID_PROVIDER, SERVICE_UNAVAILABLE, or FALLBACK_ACTIVE.",
    )

    # True if the provider is on the approved allowlist (Gemini or Groq)
    is_allowed: bool = Field(
        ...,
        description="True if provider matches project policy (Gemini or Groq only).",
    )

    # True if the provider is healthy and responding with valid credentials
    is_healthy: bool = Field(
        default=True,
        description="True if provider gateway is configured and reachable.",
    )

    # Model name currently active (e.g. 'gemini-1.5-pro', 'llama-3.3-70b-versatile')
    active_model: str = Field(
        default="unknown",
        description="Active model identifier on this provider.",
    )

    # Human-readable explanation of the check outcome
    message: str = Field(
        default="",
        description="Descriptive explanation of the provider check result.",
    )


class QualityBenchmarkSample(BaseModel):
    """A single code snippet evaluated for AI quality and accuracy.

    Simple explanation:
    We give the AI a piece of code (either perfectly clean code, or code with a known bug).
    Then we record whether the AI got the answer right or made a mistake.
    """

    model_config = ConfigDict(from_attributes=True)

    # Unique identifier for this sample (e.g. 'sample-clean-01')
    sample_id: str = Field(..., description="Identifier for this code benchmark sample.")

    # What type of code this is: 'clean_baseline' (no bugs) or 'defect_fixture' (has bugs)
    sample_type: Literal["clean_baseline", "defect_fixture"] = Field(
        ...,
        description="Sample type: clean_baseline or defect_fixture.",
    )

    # Categories of bugs we expect to find (empty list if clean code)
    expected_defects: list[str] = Field(
        default_factory=list,
        description="Defect categories known to be in this code sample.",
    )

    # Categories of bugs the AI actually detected
    detected_defects: list[str] = Field(
        default_factory=list,
        description="Defect categories the AI detected during analysis.",
    )

    # True if the AI falsely claimed there was a bug in clean code (False Alarm)
    is_false_positive: bool = Field(
        default=False,
        description="True if AI hallucinated an issue in clean code.",
    )

    # True if the AI correctly caught a real bug that actually existed
    is_true_positive: bool = Field(
        default=False,
        description="True if AI correctly identified a real defect.",
    )

    # True if the AI missed a real bug that was there
    is_false_negative: bool = Field(
        default=False,
        description="True if AI failed to detect a known defect.",
    )


class AIQualityReport(BaseModel):
    """Comprehensive AI quality evaluation report matching Day 6 goals.

    Simple explanation:
    This report summarizes how good our AI is across all tests:
    - How often it catches bugs (Recall).
    - How often its bug alerts are correct (Precision).
    - How often it falsely alarms on clean code (False Positive Rate - target: 0.0%).
    - How well it adheres to strict JSON schemas (Schema Conformance - target: 100.0%).
    """

    model_config = ConfigDict(from_attributes=True)

    # Unique report identifier
    report_id: str = Field(..., description="Unique ID for this quality evaluation report.")

    # Time when the evaluation was run in UTC
    timestamp: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(),
        description="ISO 8601 UTC timestamp of evaluation.",
    )

    # Total number of code samples evaluated
    total_samples: int = Field(default=0, ge=0, description="Total code samples analyzed.")

    # Number of clean code samples tested
    clean_samples_count: int = Field(default=0, ge=0, description="Number of clean baseline samples.")

    # Number of defect fixtures tested
    defect_samples_count: int = Field(default=0, ge=0, description="Number of defect fixture samples.")

    # Number of times the AI raised a false alarm on clean code
    false_positive_count: int = Field(
        default=0,
        ge=0,
        description="Count of false-positive detections on clean baseline code.",
    )

    # False positive percentage (Target: 0.0%)
    false_positive_rate: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="False-positive rate: false_positives / clean_samples.",
    )

    # Precision score: true_positives / (true_positives + false_positives)
    precision: float = Field(
        default=1.0,
        ge=0.0,
        le=1.0,
        description="Precision score between 0.0 and 1.0.",
    )

    # Recall score: true_positives / (true_positives + false_negatives)
    recall: float = Field(
        default=1.0,
        ge=0.0,
        le=1.0,
        description="Recall score between 0.0 and 1.0.",
    )

    # F1 score: harmonic mean of precision and recall
    f1_score: float = Field(
        default=1.0,
        ge=0.0,
        le=1.0,
        description="F1 score balancing precision and recall.",
    )

    # Schema conformance rate: percentage of AI outputs that strictly match our Pydantic models
    schema_conformance_rate: float = Field(
        default=1.0,
        ge=0.0,
        le=1.0,
        description="Percentage of outputs passing strict Pydantic schema validation.",
    )

    # Results of checking our LLM providers (Gemini and Groq)
    provider_checks: list[ProviderValidationCheck] = Field(
        default_factory=list,
        description="List of provider policy checks evaluated.",
    )

    # Overall verdict: did the AI pass all quality and policy thresholds?
    passed_quality_thresholds: bool = Field(
        default=True,
        description="True if quality and provider checks meet production standards.",
    )

    # One-sentence summary of the evaluation findings
    summary: str = Field(
        default="",
        description="Executive summary of the AI quality and provider benchmark.",
    )


__all__ = [
    "AIQualityReport",
    "PermittedProviderName",
    "ProviderValidationCheck",
    "ProviderValidationStatus",
    "QualityBenchmarkSample",
]

