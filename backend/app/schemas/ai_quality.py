"""AI Quality Evaluation, False-Positive Metrics, Explanation Rubric, and Provider Validation Schemas.

Owner: Dev — Week 3 Day 6 Deliverable (Docs/daily_tasks.md line 664 & Docs/week3.md §4.1, §6) & Issue 2 (P-28 LLM-as-Judge Rubric)
Reference: Docs/week3.md §4.1 (AI Provider Policy), §4.3 (Quality & Reliability), §6

What this file does in simple words:
1. Defines the data models for measuring how accurate our AI models are.
2. Tracks 'False Positives' (meaning when the AI wrongly claims there is a bug in clean code).
3. Defines validation schemas for our two permitted AI providers: Gemini and Groq.
4. Defines the `ExplanationQualityRubric` for scoring code explanations (LLM-as-judge P-28 + deterministic rubric).
5. Produces a structured Quality Report showing precision, recall, and reliability scores.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

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
    """Result of checking an LLM provider against platform policies."""

    model_config = ConfigDict(from_attributes=True)

    provider_name: str = Field(..., description="Name of the LLM provider being checked.")
    status: ProviderValidationStatus = Field(
        ...,
        description="Status verdict: VALID, INVALID_PROVIDER, SERVICE_UNAVAILABLE, or FALLBACK_ACTIVE.",
    )
    is_allowed: bool = Field(
        ...,
        description="True if provider matches project policy (Gemini or Groq only).",
    )
    is_healthy: bool = Field(
        default=True,
        description="True if provider gateway is configured and reachable.",
    )
    active_model: str = Field(
        default="unknown",
        description="Active model identifier on this provider.",
    )
    message: str = Field(
        default="",
        description="Descriptive explanation of the provider check result.",
    )


class QualityBenchmarkSample(BaseModel):
    """A single code snippet evaluated for AI quality and accuracy."""

    model_config = ConfigDict(from_attributes=True)

    sample_id: str = Field(..., description="Identifier for this code benchmark sample.")
    sample_type: Literal["clean_baseline", "defect_fixture"] = Field(
        ...,
        description="Sample type: clean_baseline or defect_fixture.",
    )
    expected_defects: list[str] = Field(
        default_factory=list,
        description="Defect categories known to be in this code sample.",
    )
    detected_defects: list[str] = Field(
        default_factory=list,
        description="Defect categories the AI detected during analysis.",
    )
    is_false_positive: bool = Field(
        default=False,
        description="True if AI hallucinated an issue in clean code.",
    )
    is_true_positive: bool = Field(
        default=False,
        description="True if AI correctly identified a real defect.",
    )
    is_false_negative: bool = Field(
        default=False,
        description="True if AI failed to detect a known defect.",
    )


class ExplanationQualityRubric(BaseModel):
    """5-dimension quality evaluation rubric for `CodeExplanation` outputs (Issue 2 — P-28 LLM-as-Judge)."""

    model_config = ConfigDict(from_attributes=True)

    factual_accuracy: float = Field(
        default=4.0,
        ge=1.0,
        le=5.0,
        description="1.0-5.0 score for alignment with source code without hallucinated behavior.",
    )
    completeness: float = Field(
        default=4.0,
        ge=1.0,
        le=5.0,
        description="1.0-5.0 score for coverage of purpose, logic flow, key symbols, and inputs/outputs.",
    )
    call_graph_context_clarity: float = Field(
        default=4.0,
        ge=1.0,
        le=5.0,
        description="1.0-5.0 score for clarity of 1-hop caller/callee interactions and dependencies.",
    )
    citation_grounding: float = Field(
        default=4.0,
        ge=1.0,
        le=5.0,
        description="1.0-5.0 score for verifiable file and 1-indexed line-range citations.",
    )
    redaction_transparency: float = Field(
        default=5.0,
        ge=1.0,
        le=5.0,
        description="1.0-5.0 score for truthful handling of [REDACTED] placeholders without fabricating secrets.",
    )
    overall_score: float = Field(
        default=0.8,
        ge=0.0,
        le=1.0,
        description="Normalized composite rubric score in [0.0, 1.0].",
    )
    passed: bool = Field(
        default=True,
        description="True when overall_score >= 0.70 and factual_accuracy >= 3.0.",
    )
    judge_mode: Literal["llm_judge", "deterministic_rubric"] = Field(
        default="deterministic_rubric",
        description="Whether scored by LLM-as-judge (P-28) or deterministic offline rubric.",
    )
    rationale: str = Field(
        default="",
        description="Concise explanation of the rubric scores.",
    )
    improvement_suggestions: list[str] = Field(
        default_factory=list,
        description="Actionable suggestions to improve explanation quality.",
    )


class AIQualityReport(BaseModel):
    """Comprehensive AI quality evaluation report matching Day 6 goals."""

    model_config = ConfigDict(from_attributes=True)

    report_id: str = Field(..., description="Unique ID for this quality evaluation report.")
    timestamp: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(),
        description="ISO 8601 UTC timestamp of evaluation.",
    )
    total_samples: int = Field(default=0, ge=0, description="Total code samples analyzed.")
    clean_samples_count: int = Field(default=0, ge=0, description="Number of clean baseline samples.")
    defect_samples_count: int = Field(default=0, ge=0, description="Number of defect fixture samples.")
    false_positive_count: int = Field(
        default=0,
        ge=0,
        description="Count of false-positive detections on clean baseline code.",
    )
    false_positive_rate: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="False-positive rate: false_positives / clean_samples.",
    )
    precision: float = Field(
        default=1.0,
        ge=0.0,
        le=1.0,
        description="Precision score between 0.0 and 1.0.",
    )
    recall: float = Field(
        default=1.0,
        ge=0.0,
        le=1.0,
        description="Recall score between 0.0 and 1.0.",
    )
    f1_score: float = Field(
        default=1.0,
        ge=0.0,
        le=1.0,
        description="F1 score balancing precision and recall.",
    )
    schema_conformance_rate: float = Field(
        default=1.0,
        ge=0.0,
        le=1.0,
        description="Percentage of outputs passing strict Pydantic schema validation.",
    )
    provider_checks: list[ProviderValidationCheck] = Field(
        default_factory=list,
        description="List of provider policy checks evaluated.",
    )
    passed_quality_thresholds: bool = Field(
        default=True,
        description="True if quality and provider checks meet production standards.",
    )
    summary: str = Field(
        default="",
        description="Executive summary of the AI quality and provider benchmark.",
    )


__all__ = [
    "AIQualityReport",
    "ExplanationQualityRubric",
    "PermittedProviderName",
    "ProviderValidationCheck",
    "ProviderValidationStatus",
    "QualityBenchmarkSample",
]
