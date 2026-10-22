from __future__ import annotations

import enum
import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, List, Optional

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.base import TimestampedModel

if TYPE_CHECKING:
    from app.models.analysis_finding import AnalysisFinding


class AnalysisRunStatus(str, enum.Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class AnalysisFeature(str, enum.Enum):
    EXPLAIN = "explain"
    DETECT_BUGS = "detect_bugs"
    GENERATE_TESTS = "generate_tests"
    REVIEW = "review"


class AnalysisRun(TimestampedModel, Base):
    """Persisted analysis run model for the Developer Intelligence Suite (Week 2 — Day 1).

    Owner: Om — Database & Persistence.
    Tracks execution lifecycle, parameters, target code coordinates, source revision,
    structured output payloads, and findings across all 4 intelligence features.
    """

    __tablename__ = "analysis_runs"

    repository_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("repositories.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    user_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        index=True,
        nullable=True,
    )
    feature_type: Mapped[str] = mapped_column(
        String(64),
        index=True,
        nullable=False,
    )
    status: Mapped[str] = mapped_column(
        String(32),
        default=AnalysisRunStatus.PENDING.value,
        index=True,
        nullable=False,
    )
    target_path: Mapped[Optional[str]] = mapped_column(String(1024), nullable=True)
    target_symbol: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    start_line: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    end_line: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    source_revision: Mapped[Optional[str]] = mapped_column(String(128), index=True, nullable=True)
    findings_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    # Structured result payload stored in JSONB (out-of-line TOAST in Postgres for large outputs)
    result_payload: Mapped[Optional[dict[str, Any]]] = mapped_column(JSONB, nullable=True)

    # Dedicated storage for large generated test files / artifacts
    test_output: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    # One-to-many relationship with structured findings
    findings: Mapped[List["AnalysisFinding"]] = relationship(
        "AnalysisFinding",
        back_populates="run",
        cascade="all, delete-orphan",
        order_by="AnalysisFinding.created_at",
    )

    __table_args__ = (
        Index("ix_analysis_runs_repo_created", "repository_id", "created_at"),
        Index("ix_analysis_runs_repo_feature_status", "repository_id", "feature_type", "status"),
        Index("ix_analysis_runs_repo_revision", "repository_id", "source_revision"),
    )
