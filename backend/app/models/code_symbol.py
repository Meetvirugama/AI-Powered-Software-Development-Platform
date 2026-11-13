import uuid

from sqlalchemy import Float, ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.base import TimestampedModel


class CodeSymbol(TimestampedModel, Base):
    __tablename__ = "code_symbols"

    file_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("repository_files.id", ondelete="CASCADE"))
    repository_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("repositories.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String)
    kind: Mapped[str] = mapped_column(String)
    start_line: Mapped[int] = mapped_column(Integer)
    end_line: Mapped[int] = mapped_column(Integer)
    signature: Mapped[str | None] = mapped_column(String, nullable=True)
    parent_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("code_symbols.id", ondelete="SET NULL"), nullable=True)
    importance_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0, server_default="0.0")

    __table_args__ = (
        Index("ix_code_symbols_file_id_start_line", "file_id", "start_line"),
        Index("ix_code_symbols_repository_importance", "repository_id", "importance_score"),
    )
