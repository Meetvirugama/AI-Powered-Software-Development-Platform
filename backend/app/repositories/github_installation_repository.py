from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import APIError, ErrorCode
from app.models.github_installation import GitHubInstallation


class GitHubInstallationRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get_by_id(self, installation_uuid: uuid.UUID) -> GitHubInstallation | None:
        return self.session.get(GitHubInstallation, installation_uuid)

    def get_by_installation_id(self, installation_id: str) -> GitHubInstallation | None:
        stmt = select(GitHubInstallation).where(
            GitHubInstallation.installation_id == installation_id
        )
        return self.session.execute(stmt).scalar_one_or_none()

    def list_by_user(self, user_id: uuid.UUID) -> list[GitHubInstallation]:
        stmt = select(GitHubInstallation).where(GitHubInstallation.user_id == user_id)
        return list(self.session.execute(stmt).scalars().all())

    def upsert(
        self,
        user_id: uuid.UUID,
        installation_id: str,
        account_login: str,
        permissions: dict,
        *,
        allow_reassign: bool | None = None,
    ) -> GitHubInstallation:
        existing = self.get_by_installation_id(installation_id)
        if existing:
            if existing.user_id != user_id:
                if allow_reassign is False:
                    raise APIError(
                        403,
                        ErrorCode.FORBIDDEN,
                        "This GitHub installation is already linked to another user account.",
                    )
                if allow_reassign is not True:
                    raise ValueError(
                        f"GitHub installation {installation_id} is already linked to user {existing.user_id} "
                        f"and cannot be reassigned to user {user_id}."
                    )
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
        existing = self.get_by_installation_id(installation_id)
        if not existing:
            return False
        self.session.delete(existing)
        self.session.commit()
        return True
