import uuid
from typing import Optional

from sqlalchemy import ForeignKey, Integer, JSON, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.base import TimestampedModel


class PullRequest(TimestampedModel, Base):
    """PR metadata and lifecycle record for agent-generated tasks.

    Deliverable for Parth — Week 2 Day 5 (PR Metadata Preparation):
    Stores all branch, commit, test, and verification summaries required
    to open a pull request in Week 3.
    """

    __tablename__ = "pull_requests"

    task_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True, nullable=False)
    repository_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("repositories.id"), index=True, nullable=False)
    branch: Mapped[str] = mapped_column(String(255), nullable=False)
    base_branch: Mapped[str] = mapped_column(String(255), nullable=False, default="main")
    changed_files: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    commit_message: Mapped[str] = mapped_column(Text, nullable=False)
    test_summary: Mapped[str] = mapped_column(Text, nullable=False)
    verification_summary: Mapped[str] = mapped_column(Text, nullable=False)
    pr_number: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    pr_url: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    status: Mapped[str] = mapped_column(String(50), default="prepared", nullable=False)
