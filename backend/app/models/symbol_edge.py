import uuid

from sqlalchemy import String, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.base import TimestampedModel


class SymbolEdge(TimestampedModel, Base):
    __tablename__ = "symbol_edges"

    repository_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("repositories.id"), index=True)
    source_symbol_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("code_symbols.id"))
    target_symbol_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("code_symbols.id"))
    edge_type: Mapped[str] = mapped_column(String)
