import enum
import uuid

from sqlalchemy import Float, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column, synonym

from app.core.database import Base
from app.models.base import TimestampedModel


class EdgeRelationType(str, enum.Enum):
    CALLS = "calls"
    IMPORTS = "imports"
    INHERITS = "inherits"
    IMPLEMENTS = "implements"


class EdgeProvenance(str, enum.Enum):
    TREE_SITTER = "tree_sitter"
    IMPORT_TRACKER = "import_tracker"
    SCIP = "scip"


class EdgeResolutionStatus(str, enum.Enum):
    RESOLVED = "resolved"
    AMBIGUOUS = "ambiguous"
    UNRESOLVED = "unresolved"


class SymbolEdge(TimestampedModel, Base):
    __tablename__ = "symbol_edges"

    repository_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("repositories.id", ondelete="CASCADE"), index=True
    )
    source_symbol_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("code_symbols.id", ondelete="CASCADE")
    )
    target_symbol_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("code_symbols.id", ondelete="CASCADE"), nullable=True
    )
    target_name: Mapped[str | None] = mapped_column(String(512), nullable=True)
    edge_type: Mapped[str] = mapped_column(String)
    provenance: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        default=EdgeProvenance.TREE_SITTER.value,
        server_default=EdgeProvenance.TREE_SITTER.value,
    )
    resolution_status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default=EdgeResolutionStatus.RESOLVED.value,
        server_default=EdgeResolutionStatus.RESOLVED.value,
    )
    confidence: Mapped[float] = mapped_column(
        Float, nullable=False, default=1.0, server_default="1.0"
    )
    weight: Mapped[float] = mapped_column(
        Float, nullable=False, default=1.0, server_default="1.0"
    )

    source_id = synonym("source_symbol_id")
    target_id = synonym("target_symbol_id")
    relation_type = synonym("edge_type")

    __table_args__ = (
        Index("ix_symbol_edges_source", "source_symbol_id"),
        Index("ix_symbol_edges_target", "target_symbol_id"),
        Index("ix_symbol_edges_repo_status", "repository_id", "resolution_status"),
    )
