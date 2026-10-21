import uuid
from typing import List

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.symbol_edge import SymbolEdge


class SymbolEdgeRepository:
    def __init__(self, session: Session):
        self.session = session

    # Every repository-scoped query MUST filter by repository_id
    def get_edges_for_source_symbol(self, repository_id: uuid.UUID, source_symbol_id: uuid.UUID) -> List[SymbolEdge]:
        """Retrieve all outgoing edges for a symbol, enforcing repository isolation."""
        stmt = select(SymbolEdge).where(
            SymbolEdge.repository_id == repository_id,
            SymbolEdge.source_symbol_id == source_symbol_id
        )
        return list(self.session.scalars(stmt).all())

    def get_edges_for_target_symbol(self, repository_id: uuid.UUID, target_symbol_id: uuid.UUID) -> List[SymbolEdge]:
        """Retrieve all incoming edges for a symbol, enforcing repository isolation."""
        stmt = select(SymbolEdge).where(
            SymbolEdge.repository_id == repository_id,
            SymbolEdge.target_symbol_id == target_symbol_id
        )
        return list(self.session.scalars(stmt).all())
