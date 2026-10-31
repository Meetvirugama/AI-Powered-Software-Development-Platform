from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any, Optional

from sqlalchemy import Boolean, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.base import TimestampedModel

if TYPE_CHECKING:
    from app.models.analysis_run import AnalysisRun


class AnalysisFinding(TimestampedModel, Base):
    """Persisted structured finding model for Bug Detection and AI Code Review (Week 2 — Day 1).

    Owner: Om — Database & Persistence.
    Tracks individual defects and code review findings with concrete source locations,
    category, severity, evidence, remediation, and multi-tenant repository isolation.
    """

    __tablename__ = "analysis_findings"

    analysis_run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("analysis_runs.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    repository_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("repositories.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    category: Mapped[str] = mapped_column(
        String(128),
        index=True,
        nullable=False,
    )
    severity: Mapped[str] = mapped_column(
        String(32),
        index=True,
        nullable=False,
    )
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)

    # Source location metadata
    file_path: Mapped[str] = mapped_column(String(1024), index=True, nullable=False)
    start_line: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    end_line: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    source_revision: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    symbol_name: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)

    evidence: Mapped[str] = mapped_column(Text, nullable=False)
    suggested_fix: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    confidence: Mapped[str] = mapped_column(String(32), default="medium", nullable=False)
    is_uncertain: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_new_in_change: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    source_type: Mapped[str] = mapped_column(String(32), default="AI", nullable=False)
    rule_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)

    # Optional scanner/rule-specific raw metadata
    finding_metadata: Mapped[Optional[dict[str, Any]]] = mapped_column("metadata", JSONB, nullable=True)

    run: Mapped["AnalysisRun"] = relationship(
        "AnalysisRun",
        back_populates="findings",
    )

    @property
    def source_reference(self) -> dict[str, Any]:
        """Expose structured source reference compatible with AnalysisSourceReference."""
        return {
            "repository_id": str(self.repository_id) if self.repository_id else None,
            "file_path": self.file_path,
            "start_line": self.start_line,
            "end_line": self.end_line,
            "revision": self.source_revision,
            "symbol_name": self.symbol_name,
        }

    def to_dict(self) -> dict[str, Any]:
        """Convert model to dictionary compatible with BugFinding / ReviewFinding schemas."""
        meta = self.finding_metadata or {}
        prov = meta.get("provenance")
        if not prov:
            st = str(self.source_type or "").upper()
            prov = "static_rule" if st == "STATIC" else ("combined" if st == "COMBINED" else "llm")

        return {
            "id": str(self.id),
            "analysis_run_id": str(self.analysis_run_id),
            "repository_id": str(self.repository_id),
            "category": self.category,
            "severity": self.severity,
            "title": self.title,
            "description": self.description,
            "source_reference": self.source_reference,
            "evidence": self.evidence,
            "suggested_fix": self.suggested_fix,
            "confidence": self.confidence,
            "is_uncertain": self.is_uncertain,
            "is_new_in_change": self.is_new_in_change,
            "source_type": self.source_type,
            "rule_id": self.rule_id,
            "provenance": prov,
            "rule_version": meta.get("rule_version"),
            "model_version": meta.get("model_version"),
            "deduplication_key": meta.get("deduplication_key"),
            "evidence_hash": meta.get("evidence_hash"),
        }

    def __getitem__(self, key: str) -> Any:
        return self.to_dict()[key]

    def keys(self) -> Any:
        return self.to_dict().keys()

    def items(self) -> Any:
        return self.to_dict().items()

    def values(self) -> Any:
        return self.to_dict().values()

    def __iter__(self) -> Any:
        return iter(self.to_dict())

    def __len__(self) -> int:
        return len(self.to_dict())

    def get(self, key: str, default: Any = None) -> Any:
        return self.to_dict().get(key, default)

    __table_args__ = (
        Index("ix_analysis_findings_run_severity", "analysis_run_id", "severity"),
        Index("ix_analysis_findings_repo_file", "repository_id", "file_path"),
        Index("ix_analysis_findings_repo_category", "repository_id", "category"),
    )
