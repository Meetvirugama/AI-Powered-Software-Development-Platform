import json
import uuid
from typing import List, Optional

from sqlalchemy import delete, insert, select
from sqlalchemy.orm import Session

from app.core.secret_redaction import redact
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

    def create_batch(self, chunks_data: list[dict], batch_size: int = 250) -> int:
        """
        Insert multiple code chunks in chunked database batch queries.

        Slices inserts into `batch_size` (default 250) to prevent exceeding
        PostgreSQL's 65,535 bind-parameter limit on large files/repositories,
        and enforces mandatory secret redaction on chunk content.
        """
        if not chunks_data:
            return 0
        if batch_size <= 0:
            batch_size = 250

        cleaned = []
        for c in chunks_data:
            row = dict(c)
            # Ensure UUID fields are valid UUID objects so SQLAlchemy does not fail
            for k in ("id", "repository_id", "file_id", "symbol_id"):
                if row.get(k) and isinstance(row[k], str):
                    try:
                        row[k] = uuid.UUID(row[k])
                    except (ValueError, TypeError):
                        row[k] = None if k == "symbol_id" else row[k]
            # Enforce defence-in-depth secret redaction on stored chunk content
            if "content" in row and isinstance(row["content"], str):
                row["content"] = redact(row["content"])
            # If metadata was passed as string JSON, convert to dict for JSONB column
            if "metadata" in row and isinstance(row["metadata"], str):
                try:
                    row["metadata"] = json.loads(row["metadata"])
                except Exception:
                    pass
            # If embedding was passed as JSON string, parse into list for Vector type
            if "embedding" in row and isinstance(row["embedding"], str):
                try:
                    row["embedding"] = json.loads(row["embedding"])
                except Exception:
                    pass
            cleaned.append(row)

        stmt = insert(CodeChunk)
        for i in range(0, len(cleaned), batch_size):
            self.session.execute(stmt, cleaned[i : i + batch_size])
        return len(cleaned)
