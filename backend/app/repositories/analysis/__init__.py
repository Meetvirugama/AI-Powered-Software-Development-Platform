"""Modular domain-specific persistence aggregates for Analysis Runs and Findings."""

from app.repositories.analysis.base import (
    AnalysisRepositoryBase,
    _ensure_datetime,
    _ensure_uuid,
    scrub_sensitive_data,
    scrub_sensitive_text,
)
from app.repositories.analysis.bug_scans import BugScanRunMixin, BugScanRunRepository
from app.repositories.analysis.core import AnalysisCoreMixin
from app.repositories.analysis.explanations import ExplanationRunMixin, ExplanationRunRepository
from app.repositories.analysis.retention import AnalysisRetentionMixin, AnalysisRetentionRepository
from app.repositories.analysis.reviews import ReviewRunMixin, ReviewRunRepository
from app.repositories.analysis.test_generation import TestGenerationRunMixin, TestGenerationRunRepository

__all__ = [
    "AnalysisCoreMixin",
    "AnalysisRepositoryBase",
    "AnalysisRetentionMixin",
    "AnalysisRetentionRepository",
    "BugScanRunMixin",
    "BugScanRunRepository",
    "ExplanationRunMixin",
    "ExplanationRunRepository",
    "ReviewRunMixin",
    "ReviewRunRepository",
    "TestGenerationRunMixin",
    "TestGenerationRunRepository",
    "_ensure_datetime",
    "_ensure_uuid",
    "scrub_sensitive_data",
    "scrub_sensitive_text",
]
