import json
import logging
import math
import uuid
from typing import Any, List, Optional, Sequence, Tuple

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.models.memory_entry import MemoryEntry, MemoryStatus, MemoryType

logger = logging.getLogger(__name__)


def _cosine_similarity(a: Sequence[float], b: Sequence[float]) -> float:
    """Compute cosine similarity between two vector sequences in Python fallback."""
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)


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
        embedding: Optional[List[float]] = None,
    ) -> MemoryEntry:
        """Create and persist a new episodic memory entry with repository scoping and optional vector embedding."""
        resolved_type = MemoryType(type_) if isinstance(type_, str) else type_
        resolved_status = MemoryStatus(status) if isinstance(status, str) else status

        entry = MemoryEntry(
            id=entry_id or uuid.uuid4(),
            repository_id=repository_id,
            type_=resolved_type,
            content=content.strip(),
            source=source.strip() if source else "manual",
            status=resolved_status,
            embedding=embedding,
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
        embedding: Optional[List[float]] = None,
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
        if embedding is not None:
            entry.embedding = embedding

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

    def semantic_search_entries(
        self,
        repository_id: uuid.UUID,
        query_vector: List[float],
        *,
        type_: Optional[MemoryType | str] = None,
        status: Optional[MemoryStatus | str] = None,
        limit: int = 20,
        min_similarity: float = 0.0,
    ) -> List[Tuple[MemoryEntry, float]]:
        """Perform semantic vector search using cosine similarity, strictly scoped to repository_id."""
        bind = self.session.get_bind()
        dialect_name = getattr(getattr(bind, "dialect", None), "name", "sqlite")

        resolved_type = MemoryType(type_) if isinstance(type_, str) else type_
        resolved_status = MemoryStatus(status) if isinstance(status, str) else status

        if dialect_name == "postgresql":
            # PostgreSQL + pgvector query using <=> cosine distance operator
            vec_literal = "[" + ",".join(str(float(v)) for v in query_vector) + "]"
            where_clauses = ["repository_id = CAST(:repo_id AS uuid)", "embedding IS NOT NULL"]
            params: dict[str, Any] = {
                "repo_id": str(repository_id),
                "query_vec": vec_literal,
                "limit": limit,
            }
            if resolved_type:
                where_clauses.append("CAST(type AS TEXT) = :m_type")
                params["m_type"] = resolved_type.value
            if resolved_status:
                where_clauses.append("CAST(status AS TEXT) = :m_status")
                params["m_status"] = resolved_status.value

            sql = f"""
                SELECT id, (1 - (embedding <=> CAST(:query_vec AS vector))) AS similarity
                FROM memory_entries
                WHERE {' AND '.join(where_clauses)}
                ORDER BY embedding <=> CAST(:query_vec AS vector) ASC
                LIMIT :limit
            """
            rows = self.session.execute(text(sql), params).all()
            results: List[Tuple[MemoryEntry, float]] = []
            for row in rows:
                sim = float(row.similarity)
                if sim >= min_similarity:
                    entry = self.get_by_id(row.id, repository_id=repository_id)
                    if entry:
                        results.append((entry, sim))
            return results

        # In-memory / SQLite fallback for local test suites
        stmt = select(MemoryEntry).where(
            MemoryEntry.repository_id == repository_id,
            MemoryEntry.embedding.is_not(None),
        )
        if resolved_type:
            stmt = stmt.where(MemoryEntry.type_ == resolved_type)
        if resolved_status:
            stmt = stmt.where(MemoryEntry.status == resolved_status)

        candidates = list(self.session.scalars(stmt).all())
        scored: List[Tuple[MemoryEntry, float]] = []
        for c in candidates:
            emb = c.embedding
            if isinstance(emb, str):
                try:
                    emb = json.loads(emb)
                except Exception:
                    continue
            if emb and hasattr(emb, "__len__") and len(emb) == len(query_vector):
                sim = _cosine_similarity(query_vector, emb)
                if sim >= min_similarity:
                    scored.append((c, sim))

        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[:limit]

