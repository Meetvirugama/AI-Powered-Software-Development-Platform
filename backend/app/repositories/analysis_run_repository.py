"""Database query-layer facade for Analysis Runs and Findings (F32 / Week 2).

Composes modular domain-specific aggregates:
- `explanations`: ``ExplanationRunMixin`` / ``ExplanationRunRepository``
- `bug_scans`: ``BugScanRunMixin`` / ``BugScanRunRepository``
- `test_generation`: ``TestGenerationRunMixin`` / ``TestGenerationRunRepository``
- `reviews`: ``ReviewRunMixin`` / ``ReviewRunRepository``
- `retention`: ``AnalysisRetentionMixin`` / ``AnalysisRetentionRepository``
- `core`: ``AnalysisCoreMixin``

Preserves 100% backwards compatibility for all ``AnalysisRunRepository`` imports and methods.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.repositories.analysis import (
    AnalysisCoreMixin,
    AnalysisRetentionMixin,
    AnalysisRetentionRepository,
    BugScanRunMixin,
    BugScanRunRepository,
    ExplanationRunMixin,
    ExplanationRunRepository,
    ReviewRunMixin,
    ReviewRunRepository,
    TestGenerationRunMixin,
    TestGenerationRunRepository,
    _ensure_datetime,
    _ensure_uuid,
    scrub_sensitive_data,
    scrub_sensitive_text,
)


class AnalysisRunRepository(
    AnalysisRetentionMixin,
    ReviewRunMixin,
    TestGenerationRunMixin,
    BugScanRunMixin,
    ExplanationRunMixin,
    AnalysisCoreMixin,
):
    """Unified backwards-compatible facade over domain-specific Analysis aggregates."""

    def __init__(self, session: Session) -> None:
        super().__init__(session)

    @property
    def explanations(self) -> ExplanationRunRepository:
        """Return an explanation-focused repository bound to the active session."""
        return ExplanationRunRepository(self.session)

    @property
    def bug_scans(self) -> BugScanRunRepository:
        """Return a bug-scan-focused repository bound to the active session."""
        return BugScanRunRepository(self.session)

    @property
    def test_generation(self) -> TestGenerationRunRepository:
        """Return a test-generation-focused repository bound to the active session."""
        return TestGenerationRunRepository(self.session)

    @property
    def reviews(self) -> ReviewRunRepository:
        """Return a code-review-focused repository bound to the active session."""
        return ReviewRunRepository(self.session)

    @property
    def retention(self) -> AnalysisRetentionRepository:
        """Return an integrity/retention-focused repository bound to the active session."""
        return AnalysisRetentionRepository(self.session)


__all__ = [
    "AnalysisRetentionRepository",
    "AnalysisRunRepository",
    "BugScanRunRepository",
    "ExplanationRunRepository",
    "ReviewRunRepository",
    "TestGenerationRunRepository",
    "_ensure_datetime",
    "_ensure_uuid",
    "scrub_sensitive_data",
    "scrub_sensitive_text",
]
