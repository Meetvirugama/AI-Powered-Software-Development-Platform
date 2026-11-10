import uuid
from typing import List, Optional, Tuple

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.models.memory_entry import MemoryEntry, MemoryStatus, MemoryType


class MemoryRepository:
    def __init__(self, session: Session):
        self.session = session

    # Every repository-scoped query MUST filter by repository_id
    def get_memory_entries(self, repository_id: uuid.UUID) -> List[MemoryEntry]:
        """Retrieve all memory entries for a repository, enforcing repository isolation."""
        stmt = select(MemoryEntry).where(
            MemoryEntry.repository_id == repository_id
        ).order_by(MemoryEntry.created_at.desc())
        return list(self.session.scalars(stmt).all())

    def get_active_memory_entries(self, repository_id: uuid.UUID) -> List[MemoryEntry]:
        """Retrieve active memory entries for a repository, enforcing repository isolation."""
        stmt = select(MemoryEntry).where(
            MemoryEntry.repository_id == repository_id,
            MemoryEntry.status == MemoryStatus.active
        ).order_by(MemoryEntry.created_at.desc())
        return list(self.session.scalars(stmt).all())

    def create_entry(
        self,
        repository_id: uuid.UUID,
        type_: MemoryType | str,
        content: str,
        source: str = "manual",
        status: MemoryStatus | str = MemoryStatus.active,
        entry_id: Optional[uuid.UUID] = None,
    ) -> MemoryEntry:
        """Create and persist a new episodic memory entry with repository scoping."""
        resolved_type = MemoryType(type_) if isinstance(type_, str) else type_
        resolved_status = MemoryStatus(status) if isinstance(status, str) else status

        entry = MemoryEntry(
            id=entry_id or uuid.uuid4(),
            repository_id=repository_id,
            type_=resolved_type,
            content=content.strip(),
            source=source.strip() if source else "manual",
            status=resolved_status,
        )
        self.session.add(entry)
        self.session.commit()
        self.session.refresh(entry)
        return entry

    def get_by_id(
        self,
        entry_id: uuid.UUID,
        repository_id: Optional[uuid.UUID] = None,
    ) -> Optional[MemoryEntry]:
        """Retrieve a memory entry by ID with optional repository tenant boundary check."""
        stmt = select(MemoryEntry).where(MemoryEntry.id == entry_id)
        if repository_id is not None:
            stmt = stmt.where(MemoryEntry.repository_id == repository_id)
        return self.session.scalars(stmt).first()

    def update_entry(
        self,
        entry_id: uuid.UUID,
        repository_id: uuid.UUID,
        *,
        content: Optional[str] = None,
        status: Optional[MemoryStatus | str] = None,
        type_: Optional[MemoryType | str] = None,
        source: Optional[str] = None,
    ) -> Optional[MemoryEntry]:
        """Update an existing memory entry scoped to an authorized repository."""
        entry = self.get_by_id(entry_id, repository_id=repository_id)
        if entry is None:
            return None

        if content is not None:
            entry.content = content.strip()
        if status is not None:
            entry.status = MemoryStatus(status) if isinstance(status, str) else status
        if type_ is not None:
            entry.type_ = MemoryType(type_) if isinstance(type_, str) else type_
        if source is not None:
            entry.source = source.strip()

        self.session.commit()
        self.session.refresh(entry)
        return entry

    def delete_entry(
        self,
        entry_id: uuid.UUID,
        repository_id: uuid.UUID,
    ) -> bool:
        """Delete a memory entry scoped to an authorized repository."""
        entry = self.get_by_id(entry_id, repository_id=repository_id)
        if entry is None:
            return False

        self.session.delete(entry)
        self.session.commit()
        return True

    def search_entries(
        self,
        repository_id: uuid.UUID,
        *,
        query: Optional[str] = None,
        type_: Optional[MemoryType | str] = None,
        status: Optional[MemoryStatus | str] = None,
        offset: int = 0,
        limit: int = 50,
    ) -> Tuple[List[MemoryEntry], int]:
        """Search and list memory entries with optional text query, type, and status filtering."""
        stmt = select(MemoryEntry).where(MemoryEntry.repository_id == repository_id)

        if type_:
            resolved_type = MemoryType(type_) if isinstance(type_, str) else type_
            stmt = stmt.where(MemoryEntry.type_ == resolved_type)

        if status:
            resolved_status = MemoryStatus(status) if isinstance(status, str) else status
            stmt = stmt.where(MemoryEntry.status == resolved_status)

        if query and query.strip():
            clean_q = f"%{query.strip()}%"
            stmt = stmt.where(
                (MemoryEntry.content.ilike(clean_q)) | (MemoryEntry.source.ilike(clean_q))
            )

        count_stmt = select(func.count()).select_from(stmt.subquery())
        total = self.session.scalar(count_stmt) or 0

        ordered_stmt = (
            stmt.order_by(MemoryEntry.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
        items = list(self.session.scalars(ordered_stmt).all())
        return items, total
