import uuid
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.repository_file import RepositoryFile


def get_file_by_path(db: Session, repository_id: uuid.UUID, path: str) -> Optional[RepositoryFile]:
    """
    Retrieve a specific repository file by its path and repository_id.
    """
    stmt = select(RepositoryFile).where(
        RepositoryFile.repository_id == repository_id,
        RepositoryFile.path == path
    )
    return db.execute(stmt).scalar_one_or_none()
