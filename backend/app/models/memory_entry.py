import enum
import uuid

from sqlalchemy import Enum, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.base import TimestampedModel


class MemoryType(str, enum.Enum):
    project = "project"
    decision = "decision"
    rule = "rule"
    task_summary = "task_summary"
    failure = "failure"


class MemoryStatus(str, enum.Enum):
    active = "active"
    stale = "stale"
    archived = "archived"


class MemoryEntry(TimestampedModel, Base):
    __tablename__ = "memory_entries"

    repository_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("repositories.id"), index=True)
    type_: Mapped[MemoryType] = mapped_column("type", Enum(MemoryType))
    content: Mapped[str] = mapped_column(Text)
    source: Mapped[str] = mapped_column(String)
    status: Mapped[MemoryStatus] = mapped_column(Enum(MemoryStatus), default=MemoryStatus.active)
