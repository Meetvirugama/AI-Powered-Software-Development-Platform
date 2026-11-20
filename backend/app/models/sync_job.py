"""Persisted repository synchronization jobs consumed by background workers."""

import enum
import uuid
from datetime import datetime

from sqlalchemy import JSON, DateTime, Enum, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.base import TimestampedModel


class SyncJobStatus(str, enum.Enum):
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class SyncJobStage(str, enum.Enum):
    """Fine-grained progress so the UI can show *what* a running sync is doing."""

    QUEUED = "QUEUED"
    CLONING = "CLONING"
    SCANNING = "SCANNING"
    INDEXING = "INDEXING"
    FINALIZING = "FINALIZING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


# Error text is user-visible; keep it bounded and free of stack traces.
SYNC_ERROR_MAX_CHARS = 2000


class SyncJob(TimestampedModel, Base):
    __tablename__ = "sync_jobs"

    repository_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("repositories.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    # Index status so background workers polling for QUEUED jobs do not perform full table scans
    status: Mapped[SyncJobStatus] = mapped_column(Enum(SyncJobStatus), default=SyncJobStatus.QUEUED, index=True)

    # Progress & failure tracking (stored as plain strings so new stages need no enum migration)
    stage: Mapped[str | None] = mapped_column(String(32), nullable=True, default=SyncJobStage.QUEUED.value)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    commit_sha: Mapped[str | None] = mapped_column(String(64), nullable=True)
    stats: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    # Composite index to speed up worker queue polling ordered by oldest job first
    __table_args__ = (
        Index("ix_sync_jobs_status_created", "status", "created_at"),
        Index("ix_sync_jobs_repository_created", "repository_id", "created_at"),
    )
