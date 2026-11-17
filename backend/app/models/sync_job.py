"""Persisted repository synchronization jobs consumed by background workers."""

import enum
import uuid

from sqlalchemy import Enum, ForeignKey, Index
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.base import TimestampedModel


class SyncJobStatus(str, enum.Enum):
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class SyncJob(TimestampedModel, Base):
    __tablename__ = "sync_jobs"

    repository_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("repositories.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    # Index status so background workers polling for QUEUED jobs do not perform full table scans
    status: Mapped[SyncJobStatus] = mapped_column(Enum(SyncJobStatus), default=SyncJobStatus.QUEUED, index=True)

    # Composite index to speed up worker queue polling ordered by oldest job first
    __table_args__ = (
        Index("ix_sync_jobs_status_created", "status", "created_at"),
    )
