import uuid
from typing import List, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.repository import Repository, SyncStatus


class RepositoryRepository:
    def __init__(self, session: Session):
        self.session = session

    def create(self, user_id: uuid.UUID, installation_id: uuid.UUID, github_repo_id: str, owner: str, name: str, default_branch: str, language: Optional[str] = None) -> Repository:
        repo = Repository(
            user_id=user_id,
            installation_id=installation_id,
            github_repo_id=github_repo_id,
            owner=owner,
            name=name,
            default_branch=default_branch,
            language=language
        )
        self.session.add(repo)
        self.session.commit()
        self.session.refresh(repo)
        return repo

    def get_by_id(self, repo_id: uuid.UUID) -> Optional[Repository]:
        return self.session.get(Repository, repo_id)

    def list_by_user(self, user_id: uuid.UUID) -> List[Repository]:
        stmt = select(Repository).where(Repository.user_id == user_id)
        return list(self.session.scalars(stmt).all())

    def update_sync_status(self, repo_id: uuid.UUID, status: SyncStatus) -> Optional[Repository]:
        repo = self.get_by_id(repo_id)
        if repo:
            repo.sync_status = status
            self.session.commit()
            self.session.refresh(repo)
        return repo
