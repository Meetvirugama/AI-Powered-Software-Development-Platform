import uuid
from typing import List, Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.repository import Repository, SyncStatus
from app.models.repository_file import RepositoryFile
from app.models.code_symbol import CodeSymbol
from app.models.sync_job import SyncJob, SyncJobStatus


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

    def get_for_user(self, repo_id: uuid.UUID, user_id: uuid.UUID) -> Optional[Repository]:
        stmt = select(Repository).where(Repository.id == repo_id, Repository.user_id == user_id)
        return self.session.execute(stmt).scalar_one_or_none()

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

    def list_files(self, repo_id: uuid.UUID, offset: int, limit: int) -> tuple[list[RepositoryFile], int]:
        statement = select(RepositoryFile).where(RepositoryFile.repository_id == repo_id).order_by(RepositoryFile.path)
        total = self.session.scalar(select(func.count()).select_from(statement.subquery())) or 0
        return list(self.session.scalars(statement.offset(offset).limit(limit)).all()), total

    def list_symbols(self, repo_id: uuid.UUID, offset: int, limit: int) -> tuple[list[CodeSymbol], int]:
        statement = select(CodeSymbol).where(CodeSymbol.repository_id == repo_id).order_by(CodeSymbol.name, CodeSymbol.start_line)
        total = self.session.scalar(select(func.count()).select_from(statement.subquery())) or 0
        return list(self.session.scalars(statement.offset(offset).limit(limit)).all()), total

    def create_sync_job(self, repository_id: uuid.UUID, user_id: uuid.UUID) -> SyncJob:
        job = SyncJob(repository_id=repository_id, user_id=user_id, status=SyncJobStatus.QUEUED)
        self.session.add(job)
        self.session.commit()
        self.session.refresh(job)
        return job

    def mark_sync_job_failed(self, job_id: uuid.UUID) -> Optional[SyncJob]:
        """Record a dispatch failure after a job has been persisted."""
        job = self.session.get(SyncJob, job_id)
        if job:
            job.status = SyncJobStatus.FAILED
            self.session.commit()
            self.session.refresh(job)
        return job
