import uuid
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.user import User


class UserRepository:
    def __init__(self, session: Session):
        self.session = session

    def create_user(self, github_id: str, login: str, email: Optional[str] = None, avatar_url: Optional[str] = None) -> User:
        user = User(
            github_id=github_id,
            login=login,
            email=email,
            avatar_url=avatar_url
        )
        self.session.add(user)
        self.session.commit()
        self.session.refresh(user)
        return user

    def get_by_github_id(self, github_id: str) -> Optional[User]:
        stmt = select(User).where(User.github_id == github_id)
        return self.session.execute(stmt).scalar_one_or_none()

    def get_by_id(self, user_id: uuid.UUID) -> Optional[User]:
        return self.session.get(User, user_id)

    def upsert_github_user(
        self,
        github_id: str,
        login: str,
        email: Optional[str] = None,
        avatar_url: Optional[str] = None,
    ) -> User:
        """Create a GitHub user on first login or refresh mutable profile fields."""
        user = self.get_by_github_id(github_id)
        if user is None:
            return self.create_user(github_id, login, email, avatar_url)
        user.login = login
        user.email = email
        user.avatar_url = avatar_url
        self.session.commit()
        self.session.refresh(user)
        return user
