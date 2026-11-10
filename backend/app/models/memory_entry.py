import enum
import uuid
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import Enum, ForeignKey, Index, String, Text
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

    repository_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("repositories.id", ondelete="CASCADE"), index=True)
    type_: Mapped[MemoryType] = mapped_column("type", Enum(MemoryType))
    content: Mapped[str] = mapped_column(Text)
    source: Mapped[str] = mapped_column(String)
    status: Mapped[MemoryStatus] = mapped_column(Enum(MemoryStatus), default=MemoryStatus.active)
    embedding: Mapped[Any] = mapped_column(Vector(768), nullable=True)

    __table_args__ = (
        Index(
            "ix_memory_entries_embedding_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_with={"m": 16, "ef_construction": 64},
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )

