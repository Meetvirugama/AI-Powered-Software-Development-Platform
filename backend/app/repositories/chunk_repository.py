import uuid
from typing import List, Optional

from sqlalchemy import select, delete
from sqlalchemy.orm import Session

from app.models.code_chunk import CodeChunk


class ChunkRepository:
    def __init__(self, session: Session):
        self.session = session

    # Every repository-scoped query MUST filter by repository_id
    def get_chunks(self, repository_id: uuid.UUID, query: str) -> List[CodeChunk]:
        """
        Retrieve code chunks for a repository, enforcing repository isolation.
        """
        stmt = select(CodeChunk).where(
            CodeChunk.repository_id == repository_id
        )
        if query:
            stmt = stmt.where(CodeChunk.content.ilike(f"%{query}%"))
            
        return list(self.session.scalars(stmt).all())

    def get_by_content_hash(self, repository_id: uuid.UUID, file_id: uuid.UUID, content_hash: str) -> Optional[CodeChunk]:
        """
        Check if a file's content hash is already indexed.
        Enforces repository isolation.
        """
        stmt = select(CodeChunk).where(
            CodeChunk.repository_id == repository_id,
            CodeChunk.file_id == file_id,
            CodeChunk.content_hash == content_hash
        ).limit(1)
        return self.session.execute(stmt).scalar_one_or_none()

    def delete_by_file_id(self, repository_id: uuid.UUID, file_id: uuid.UUID) -> None:
        """
        Delete all chunks for a specific file to avoid stale vectors.
        Enforces repository isolation.
        """
        stmt = delete(CodeChunk).where(
            CodeChunk.repository_id == repository_id,
            CodeChunk.file_id == file_id
        )
        self.session.execute(stmt)
        self.session.commit()
