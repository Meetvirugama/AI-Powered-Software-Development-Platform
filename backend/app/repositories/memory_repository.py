import uuid
from typing import List

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.memory_entry import MemoryEntry, MemoryStatus


class MemoryRepository:
    def __init__(self, session: Session):
        self.session = session

    # Every repository-scoped query MUST filter by repository_id
    def get_memory_entries(self, repository_id: uuid.UUID) -> List[MemoryEntry]:
        """
        Retrieve all memory entries for a repository, enforcing repository isolation.
        """
        stmt = select(MemoryEntry).where(
            MemoryEntry.repository_id == repository_id
        ).order_by(MemoryEntry.created_at.desc())
        return list(self.session.scalars(stmt).all())

    def get_active_memory_entries(self, repository_id: uuid.UUID) -> List[MemoryEntry]:
        """
        Retrieve active memory entries for a repository, enforcing repository isolation.
        """
        stmt = select(MemoryEntry).where(
            MemoryEntry.repository_id == repository_id,
            MemoryEntry.status == MemoryStatus.active
        ).order_by(MemoryEntry.created_at.desc())
        return list(self.session.scalars(stmt).all())
