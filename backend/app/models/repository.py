import enum
import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.base import TimestampedModel


class SyncStatus(str, enum.Enum):
    NOT_SYNCED = "NOT_SYNCED"
    SYNCING = "SYNCING"
    SYNCED = "SYNCED"
    FAILED = "FAILED"


class Repository(TimestampedModel, Base):
    __tablename__ = "repositories"

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    installation_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("github_installations.id", ondelete="CASCADE"), index=True)
    github_repo_id: Mapped[str] = mapped_column(String, index=True)
    owner: Mapped[str] = mapped_column(String)
    name: Mapped[str] = mapped_column(String)
    default_branch: Mapped[str] = mapped_column(String, default="main")
    language: Mapped[str | None] = mapped_column(String, nullable=True)
    sync_status: Mapped[SyncStatus] = mapped_column(Enum(SyncStatus), default=SyncStatus.NOT_SYNCED)
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    active_index_generation: Mapped[str | None] = mapped_column(String, nullable=True, default="gen_0")
    active_commit_sha: Mapped[str | None] = mapped_column(String, nullable=True)
    last_indexed_commit_sha: Mapped[str | None] = mapped_column(String(64), nullable=True)
    auto_sync_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    pr_review_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    pr_review_drafts: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    file_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    symbol_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    chunk_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    last_sync_error: Mapped[str | None] = mapped_column(String(512), nullable=True)

    # Composite index to accelerate looking up repositories by GitHub owner and repo name (owner/name)
    __table_args__ = (
        Index("ix_repositories_owner_name", "owner", "name"),
    )
