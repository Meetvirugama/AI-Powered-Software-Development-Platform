"""SQLAlchemy ORM models for Week 3 GitHub Issues, Tasks, Plans, Approvals, and Audit Events.

Owner: Om — Week 3 Day 1–2 Persistence & Recovery (Docs/week3.md §6 F39 & Docs/daily_tasks.md)

Tables defined:
1. `github_issues` (`GitHubIssue`): Persists imported or created GitHub issues with unique `(repository_id, issue_number)` constraint.
2. `tasks` (`AgentTask`): Core development task entity with source traceability, state machine status, plan version, and retry budget.
3. `task_plans` (`TaskPlanRecord`): Versioned structured implementation plans with base revision and SHA-256 plan fingerprint.
4. `task_approvals` (`TaskApprovalRecord`): Immutable human approval/rejection audit records bound to exact `(task_id, plan_version, plan_hash, base_revision)`.
5. `task_events` (`TaskEventRecord`): Ordered timeline and audit history events for every state transition and governance action.
"""

from __future__ import annotations

import uuid
from typing import Any, Optional

from sqlalchemy import (
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.base import TimestampedModel


class GitHubIssue(TimestampedModel, Base):
    """Persisted GitHub issue imported into or created from the platform (F31)."""

    __tablename__ = "github_issues"

    repository_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("repositories.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    issue_number: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    body: Mapped[str] = mapped_column(Text, default="", nullable=False)
    state: Mapped[str] = mapped_column(String(32), default="open", nullable=False)
    labels: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    html_url: Mapped[str] = mapped_column(String(1024), nullable=False)
    author: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    origin_finding_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("analysis_findings.id", ondelete="SET NULL"),
        index=True,
        nullable=True,
    )

    tasks: Mapped[list["AgentTask"]] = relationship(
        "AgentTask",
        back_populates="github_issue",
    )

    __table_args__ = (
        UniqueConstraint(
            "repository_id",
            "issue_number",
            name="uq_github_issues_repo_issue_number",
        ),
        Index("ix_github_issues_repo_number", "repository_id", "issue_number"),
    )


class AgentTask(TimestampedModel, Base):
    """Persisted development task with lifecycle state, source reference, and retry budget (F31, F32, F39)."""

    __tablename__ = "tasks"

    repository_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("repositories.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    github_issue_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("github_issues.id", ondelete="SET NULL"),
        index=True,
        nullable=True,
    )
    origin_finding_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("analysis_findings.id", ondelete="SET NULL"),
        index=True,
        nullable=True,
    )

    title: Mapped[str] = mapped_column(String(512), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(64), default="CREATED", index=True, nullable=False)
    source_type: Mapped[str] = mapped_column(String(64), default="USER_PROMPT", nullable=False)
    source_ref: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)

    requirements: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list, nullable=False)
    assumptions: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list, nullable=False)
    constraints: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list, nullable=False)

    base_revision: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    plan_version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    approved_plan_version: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    repair_attempts_used: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    repair_attempts_max: Mapped[int] = mapped_column(Integer, default=3, nullable=False)

    github_issue: Mapped[Optional["GitHubIssue"]] = relationship(
        "GitHubIssue",
        back_populates="tasks",
    )
    plans: Mapped[list["TaskPlanRecord"]] = relationship(
        "TaskPlanRecord",
        back_populates="task",
        cascade="all, delete-orphan",
        order_by="TaskPlanRecord.plan_version.desc()",
    )
    approvals: Mapped[list["TaskApprovalRecord"]] = relationship(
        "TaskApprovalRecord",
        back_populates="task",
        cascade="all, delete-orphan",
        order_by="TaskApprovalRecord.created_at.desc()",
    )
    events: Mapped[list["TaskEventRecord"]] = relationship(
        "TaskEventRecord",
        back_populates="task",
        cascade="all, delete-orphan",
        order_by="TaskEventRecord.created_at.asc()",
    )

    __table_args__ = (
        Index("ix_tasks_repo_status", "repository_id", "status"),
        Index("ix_tasks_user_created", "user_id", "created_at"),
    )


class TaskPlanRecord(TimestampedModel, Base):
    """Versioned structured implementation plan for an AgentTask (F32, F39)."""

    __tablename__ = "task_plans"

    task_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tasks.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    plan_version: Mapped[int] = mapped_column(Integer, nullable=False)
    base_revision: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    plan_hash: Mapped[str] = mapped_column(String(128), nullable=False)

    summary: Mapped[str] = mapped_column(Text, nullable=False)
    problem_statement: Mapped[str] = mapped_column(Text, default="", nullable=False)
    assumptions: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list, nullable=False)
    relevant_files: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    relevant_symbols: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    steps: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list, nullable=False)
    expected_files: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    tests_to_run: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    validation_strategy: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    risks: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list, nullable=False)
    required_permissions: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    resource_budget: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    status: Mapped[str] = mapped_column(String(64), default="PENDING_APPROVAL", nullable=False)

    task: Mapped["AgentTask"] = relationship(
        "AgentTask",
        back_populates="plans",
    )

    __table_args__ = (
        UniqueConstraint(
            "task_id",
            "plan_version",
            name="uq_task_plans_task_version",
        ),
        Index("ix_task_plans_task_version", "task_id", "plan_version"),
    )


class TaskApprovalRecord(TimestampedModel, Base):
    """Immutable audit record of a human plan approval or rejection decision (F32, F39)."""

    __tablename__ = "task_approvals"

    task_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tasks.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    plan_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("task_plans.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    plan_version: Mapped[int] = mapped_column(Integer, nullable=False)
    approver_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    decision: Mapped[str] = mapped_column(String(32), nullable=False)  # APPROVED or REJECTED
    comment: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    base_revision: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    plan_hash: Mapped[str] = mapped_column(String(128), nullable=False)

    task: Mapped["AgentTask"] = relationship(
        "AgentTask",
        back_populates="approvals",
    )

    __table_args__ = (
        Index("ix_task_approvals_task_version", "task_id", "plan_version"),
    )


class TaskEventRecord(TimestampedModel, Base):
    """Ordered timeline and audit event record for a task (F38, F39)."""

    __tablename__ = "task_events"

    task_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tasks.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    event_type: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    actor_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), nullable=True)
    from_status: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    to_status: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)

    task: Mapped["AgentTask"] = relationship(
        "AgentTask",
        back_populates="events",
    )

    __table_args__ = (
        Index("ix_task_events_task_created", "task_id", "created_at"),
    )


__all__ = [
    "AgentTask",
    "GitHubIssue",
    "TaskApprovalRecord",
    "TaskEventRecord",
    "TaskPlanRecord",
]
