import uuid
from datetime import datetime, timezone

from sqlalchemy import JSON, String, ForeignKey, DateTime, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.base import TimestampedModel


class GitHubInstallation(TimestampedModel, Base):
    __tablename__ = "github_installations"

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True)
    installation_id: Mapped[str] = mapped_column(String, unique=True, index=True)
    account_login: Mapped[str] = mapped_column(String)
    permissions: Mapped[dict] = mapped_column(JSON, default=dict)
    installed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=func.now())
