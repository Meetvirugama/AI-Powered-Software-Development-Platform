import uuid
from typing import List, Optional

# pyrefly: ignore [missing-import]
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

    def create_batch(self, symbols_data: list[dict]) -> int:
        """
        Insert multiple code symbols in a single database batch query.
        
        Simple explanation:
        Instead of running multiple INSERT commands for each symbol, this method
        takes a list of symbol dictionaries and saves all of them in one go.
        """
        if not symbols_data:
            return 0
        from sqlalchemy import insert
        cleaned = []
        for s in symbols_data:
            row = dict(s)
            # Ensure UUID fields are valid UUID objects so SQLAlchemy does not fail
            for k in ("id", "file_id", "repository_id", "parent_id"):
                if row.get(k) and isinstance(row[k], str):
                    try:
                        row[k] = uuid.UUID(row[k])
                    except (ValueError, TypeError):
                        pass
            cleaned.append(row)
        stmt = insert(CodeSymbol)
        self.session.execute(stmt, cleaned)
        return len(cleaned)
