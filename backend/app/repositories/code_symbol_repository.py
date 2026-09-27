import uuid
from typing import List, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.code_symbol import CodeSymbol


class CodeSymbolRepository:
    def __init__(self, session: Session):
        self.session = session

    # Every repository-scoped query MUST filter by repository_id
    def get_by_id(self, repository_id: uuid.UUID, symbol_id: uuid.UUID) -> Optional[CodeSymbol]:
        """Retrieve a specific code symbol, enforcing repository isolation."""
        stmt = select(CodeSymbol).where(
            CodeSymbol.repository_id == repository_id,
            CodeSymbol.id == symbol_id
        )
        return self.session.execute(stmt).scalar_one_or_none()

    def get_symbols_for_file(self, repository_id: uuid.UUID, file_id: uuid.UUID) -> List[CodeSymbol]:
        """Retrieve all symbols for a specific file, enforcing repository isolation."""
        stmt = select(CodeSymbol).where(
            CodeSymbol.repository_id == repository_id,
            CodeSymbol.file_id == file_id
        ).order_by(CodeSymbol.start_line)
        return list(self.session.scalars(stmt).all())
