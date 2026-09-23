import enum
import uuid
from datetime import datetime

from sqlalchemy import Enum, ForeignKey, String, DateTime
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

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True)
    installation_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("github_installations.id"), index=True)
    github_repo_id: Mapped[str] = mapped_column(String, index=True)
    owner: Mapped[str] = mapped_column(String)
    name: Mapped[str] = mapped_column(String)
    default_branch: Mapped[str] = mapped_column(String, default="main")
    language: Mapped[str | None] = mapped_column(String, nullable=True)
    sync_status: Mapped[SyncStatus] = mapped_column(Enum(SyncStatus), default=SyncStatus.NOT_SYNCED)
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
