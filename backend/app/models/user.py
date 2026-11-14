import enum
from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.base import TimestampedModel


class UserRole(str, enum.Enum):
    """User roles for Role-Based Access Control (RBAC - Issue #211 / F01)."""

    ADMIN = "admin"
    DEVELOPER = "developer"
    VIEWER = "viewer"


class User(TimestampedModel, Base):
    __tablename__ = "users"

    github_id: Mapped[str] = mapped_column(String, unique=True, index=True)
    login: Mapped[str] = mapped_column(String, unique=True, index=True)
    email: Mapped[str | None] = mapped_column(String, nullable=True)
    avatar_url: Mapped[str | None] = mapped_column(String, nullable=True)
    role: Mapped[str] = mapped_column(
        String(32),
        default=UserRole.DEVELOPER.value,
        server_default=UserRole.DEVELOPER.value,
        nullable=False,
    )
