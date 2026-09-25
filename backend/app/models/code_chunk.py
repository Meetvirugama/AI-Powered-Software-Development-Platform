import uuid
from typing import Any

from sqlalchemy import String, Integer, ForeignKey, Index, Text, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from pgvector.sqlalchemy import Vector

from app.core.database import Base
from app.models.base import TimestampedModel


class CodeChunk(TimestampedModel, Base):
    __tablename__ = "code_chunks"

    repository_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("repositories.id"))
    file_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("repository_files.id"))
    symbol_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("code_symbols.id"), nullable=True)
    content: Mapped[str] = mapped_column(Text)
    token_count: Mapped[int] = mapped_column(Integer)
    embedding: Mapped[Any] = mapped_column(Vector(1536))
    start_line: Mapped[int] = mapped_column(Integer)
    end_line: Mapped[int] = mapped_column(Integer)
    content_hash: Mapped[str] = mapped_column(String)
    chunk_metadata: Mapped[dict[str, Any]] = mapped_column("metadata", JSONB)

    __table_args__ = (
        Index(
            "ix_code_chunks_embedding_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_with={"m": 16, "ef_construction": 64},
            postgresql_ops={"embedding": "vector_cosine_ops"}
        ),
        Index(
            "ix_code_chunks_content_gin",
            text("to_tsvector('english', content)"),
            postgresql_using="gin"
        ),
        Index("ix_code_chunks_repo_hash", "repository_id", "content_hash"),
    )
