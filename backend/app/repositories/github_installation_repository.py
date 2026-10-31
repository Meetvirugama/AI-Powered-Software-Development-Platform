"""GitHub installation repository — DB access layer."""

import uuid
from typing import List, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.github_installation import GitHubInstallation


class GitHubInstallationRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def list_by_user(self, user_id: uuid.UUID) -> List[GitHubInstallation]:
        stmt = select(GitHubInstallation).where(GitHubInstallation.user_id == user_id)
        return list(self.session.scalars(stmt).all())

    def get_by_installation_id(self, installation_id: str) -> Optional[GitHubInstallation]:
        stmt = select(GitHubInstallation).where(
            GitHubInstallation.installation_id == installation_id
        )
        return self.session.execute(stmt).scalar_one_or_none()

    def upsert(
        self,
        user_id: uuid.UUID,
        installation_id: str,
        account_login: str,
        permissions: dict,
    ) -> GitHubInstallation:
        existing = self.get_by_installation_id(installation_id)
        if existing:
            existing.user_id = user_id
            existing.account_login = account_login
            existing.permissions = permissions
            self.session.commit()
            self.session.refresh(existing)
            return existing
        record = GitHubInstallation(
            user_id=user_id,
            installation_id=installation_id,
            account_login=account_login,
            permissions=permissions,
        )
        self.session.add(record)
        self.session.commit()
        self.session.refresh(record)
        return record

    def delete_by_installation_id(self, installation_id: str) -> bool:
        record = self.get_by_installation_id(installation_id)
        if record:
            self.session.delete(record)
            self.session.commit()
            return True
        return False
