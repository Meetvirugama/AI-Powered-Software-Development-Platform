import uuid
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.user import User, UserRole

VALID_ROLES = frozenset(role.value for role in UserRole)


class UserRepository:
    def __init__(self, session: Session):
        self.session = session

    def create_user(
        self,
        github_id: str,
        login: str,
        email: Optional[str] = None,
        avatar_url: Optional[str] = None,
        role: str = UserRole.DEVELOPER.value,
    ) -> User:
        user = User(
            github_id=github_id,
            login=login,
            email=email,
            avatar_url=avatar_url,
            role=role,
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

    def get_by_login(self, login: str) -> Optional[User]:
        # Exact, case-insensitive match. ``ilike`` treated "_" and "%" in a login as
        # wildcards, so "a_c" could resolve to the account "abc".
        stmt = select(User).where(func.lower(User.login) == login.strip().lower())
        return self.session.execute(stmt).scalars().first()

    def upsert_github_user(
        self,
        github_id: str,
        login: str,
        email: Optional[str] = None,
        avatar_url: Optional[str] = None,
        *,
        admin_logins: frozenset[str] | set[str] | None = None,
    ) -> User:
        """Create a GitHub user on first login or refresh mutable profile fields.

        Logins listed in ``admin_logins`` are promoted to ADMIN. Promotion is one-way:
        removing a login from the list never silently demotes an existing admin.
        """
        is_bootstrap_admin = bool(admin_logins) and login.lower() in admin_logins
        user = self.get_by_github_id(github_id)
        if user is None:
            role = UserRole.ADMIN.value if is_bootstrap_admin else UserRole.DEVELOPER.value
            return self.create_user(github_id, login, email, avatar_url, role=role)
        user.login = login
        # GitHub hides the email unless it is public; keep the last known one instead of wiping it.
        if email:
            user.email = email
        user.avatar_url = avatar_url
        if is_bootstrap_admin and user.role != UserRole.ADMIN.value:
            user.role = UserRole.ADMIN.value
        self.session.commit()
        self.session.refresh(user)
        return user

    # ------------------------------------------------------------------
    # Role management (admin only — enforced at the API layer)
    # ------------------------------------------------------------------

    def list_users(self, *, offset: int = 0, limit: int = 50, role: Optional[str] = None) -> tuple[list[User], int]:
        stmt = select(User)
        count_stmt = select(func.count(User.id))
        if role:
            stmt = stmt.where(User.role == role)
            count_stmt = count_stmt.where(User.role == role)
        total = int(self.session.execute(count_stmt).scalar_one())
        rows = self.session.execute(stmt.order_by(User.login).offset(offset).limit(limit)).scalars().all()
        return list(rows), total

    def count_by_role(self, role: str) -> int:
        stmt = select(func.count(User.id)).where(User.role == role)
        return int(self.session.execute(stmt).scalar_one())

    def set_role(self, user: User, role: str) -> User:
        normalized = (role or "").strip().lower()
        if normalized not in VALID_ROLES:
            raise ValueError(f"Unknown role '{role}'. Expected one of: {', '.join(sorted(VALID_ROLES))}.")
        user.role = normalized
        self.session.commit()
        self.session.refresh(user)
        return user
