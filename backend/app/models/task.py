"""Database models for Week 3 Workflow Automation, Task Planning, and Recovery.

Owner: Om — Database & Persistence Lead.
Implements: Feature F39 — Persistence, Checkpoints and Recovery.

Provides the comprehensive data models for:
- Task entity with lifecycle state machine and source references
- TaskPlan and plan versioning
- TaskApproval (immutable approval records)
- Workspace execution tracking
- TaskExecution attempts
- ToolInvocation auditing
- TestRun logging and metrics
- RepairAttempt tracking (max 3 task-level attempts)
- VerificationResult strictly tied to verified revision
- TaskCheckpoint for safe failure recovery (secret-scrubbed)
- TaskEvent for complete ordered audit timeline
- TaskPullRequest for GitHub Draft PR tracking
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, List, Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.base import TimestampedModel

if TYPE_CHECKING:
    from app.models.analysis_finding import AnalysisFinding
    from app.models.repository import Repository
    from app.models.user import User


class TaskStatus(str, enum.Enum):
    """Lifecycle states for workflow automation tasks (Week 3 — §7.1)."""

    CREATED = "CREATED"
    PLANNING = "PLANNING"
    PENDING_APPROVAL = "PENDING_APPROVAL"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    WORKSPACE_SETUP = "WORKSPACE_SETUP"
    EXECUTING = "EXECUTING"
    TESTING = "TESTING"
    REPAIRING = "REPAIRING"
    VERIFYING = "VERIFYING"
    READY_FOR_PUBLICATION = "READY_FOR_PUBLICATION"
    PUBLISHING = "PUBLISHING"
    DRAFT_PR_CREATED = "DRAFT_PR_CREATED"

    # Terminal or exceptional states
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    RECOVERY_REQUIRED = "RECOVERY_REQUIRED"
    BLOCKED = "BLOCKED"


class TaskSourceType(str, enum.Enum):
    """Source origin of a development task."""

    GITHUB_ISSUE = "GITHUB_ISSUE"
    USER_REQUIREMENT = "USER_REQUIREMENT"
    BUG_FINDING = "BUG_FINDING"
    REVIEW_FINDING = "REVIEW_FINDING"


class TaskPlanStatus(str, enum.Enum):
    """Status of an implementation plan version."""

    DRAFT = "DRAFT"
    PROPOSED = "PROPOSED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    SUPERSEDED = "SUPERSEDED"


class ApprovalDecision(str, enum.Enum):
    """Decision recorded in task approvals."""

    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class WorkspaceStatus(str, enum.Enum):
    """Lifecycle of isolated task workspace environments."""

    NOT_CREATED = "NOT_CREATED"
    CREATING = "CREATING"
    READY = "READY"
    IN_USE = "IN_USE"
    STOPPED = "STOPPED"
    FAILED = "FAILED"
    CLEANUP_PENDING = "CLEANUP_PENDING"
    CLEANED = "CLEANED"


class ExecutionStatus(str, enum.Enum):
    """Status of task worker execution attempts."""

    STARTED = "STARTED"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class ToolInvocationStatus(str, enum.Enum):
    """Outcome status of controlled tool router executions."""

    ALLOWED = "ALLOWED"
    BLOCKED = "BLOCKED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class TestRunStatus(str, enum.Enum):
    """Outcome status of permitted test suite runs."""

    __test__ = False

    PASSED = "PASSED"
    FAILED = "FAILED"
    TIMED_OUT = "TIMED_OUT"
    ERROR = "ERROR"


class RepairResult(str, enum.Enum):
    """Outcome of a bounded repair attempt."""

    SUCCESS = "SUCCESS"
    RETRY_EXHAUSTED = "RETRY_EXHAUSTED"
    FAILED = "FAILED"


class VerificationStatus(str, enum.Enum):
    """Independent verification status."""

    PASSED = "PASSED"
    FAILED = "FAILED"
    REQUIRES_HUMAN_REVIEW = "REQUIRES_HUMAN_REVIEW"
    INCONCLUSIVE = "INCONCLUSIVE"


class TaskEventType(str, enum.Enum):
    """Event types for ordered audit timeline."""

    TASK_CREATED = "TASK_CREATED"
    ISSUE_IMPORTED = "ISSUE_IMPORTED"
    PLAN_GENERATED = "PLAN_GENERATED"
    PLAN_APPROVED = "PLAN_APPROVED"
    PLAN_REJECTED = "PLAN_REJECTED"
    WORKSPACE_CREATED = "WORKSPACE_CREATED"
    TOOL_INVOKED = "TOOL_INVOKED"
    TESTS_EXECUTED = "TESTS_EXECUTED"
    REPAIR_ATTEMPTED = "REPAIR_ATTEMPTED"
    VERIFICATION_COMPLETED = "VERIFICATION_COMPLETED"
    PUBLICATION_AUTHORIZED = "PUBLICATION_AUTHORIZED"
    BRANCH_PUSHED = "BRANCH_PUSHED"
    DRAFT_PR_CREATED = "DRAFT_PR_CREATED"
    EXECUTION_FAILED = "EXECUTION_FAILED"
    RECOVERY_TRIGGERED = "RECOVERY_TRIGGERED"
    STATE_TRANSITIONED = "STATE_TRANSITIONED"
    CHECKPOINT_SAVED = "CHECKPOINT_SAVED"


# ---------------------------------------------------------------------------
# 1. Main Task Model
# ---------------------------------------------------------------------------


class Task(TimestampedModel, Base):
    """Core development task model managing workflow automation, approval, and execution state."""

    __tablename__ = "tasks"

    repository_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("repositories.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    user_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        index=True,
        nullable=True,
    )

    title: Mapped[str] = mapped_column(String(512), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    status: Mapped[str] = mapped_column(
        String(32),
        default=TaskStatus.CREATED.value,
        index=True,
        nullable=False,
    )

    source_type: Mapped[str] = mapped_column(
        String(64),
        default=TaskSourceType.GITHUB_ISSUE.value,
        index=True,
        nullable=False,
    )
    source_id: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    source_metadata: Mapped[Optional[dict[str, Any]]] = mapped_column(JSONB, nullable=True)

    # Issue-to-task persistence relationships: foreign key to Week 2 findings
    finding_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("analysis_findings.id", ondelete="SET NULL"),
        index=True,
        nullable=True,
    )

    base_revision: Mapped[str] = mapped_column(String(128), default="main", nullable=False)
    plan_version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    approved_plan_version: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    # Bounded repair loop controls
    repair_attempts_used: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    repair_attempts_max: Mapped[int] = mapped_column(Integer, default=3, nullable=False)

    context_summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Relationships
    finding: Mapped[Optional["AnalysisFinding"]] = relationship(
        "AnalysisFinding",
        foreign_keys=[finding_id],
    )
    repository: Mapped["Repository"] = relationship(
        "Repository",
        foreign_keys=[repository_id],
    )
    user: Mapped[Optional["User"]] = relationship(
        "User",
        foreign_keys=[user_id],
    )

    plans: Mapped[List["TaskPlan"]] = relationship(
        "TaskPlan",
        back_populates="task",
        cascade="all, delete-orphan",
        order_by="TaskPlan.version.desc()",
    )
    approvals: Mapped[List["TaskApproval"]] = relationship(
        "TaskApproval",
        back_populates="task",
        cascade="all, delete-orphan",
        order_by="TaskApproval.created_at.desc()",
    )
    executions: Mapped[List["TaskExecution"]] = relationship(
        "TaskExecution",
        back_populates="task",
        cascade="all, delete-orphan",
        order_by="TaskExecution.started_at.desc()",
    )
    workspace: Mapped[Optional["Workspace"]] = relationship(
        "Workspace",
        back_populates="task",
        uselist=False,
        cascade="all, delete-orphan",
    )
    tool_invocations: Mapped[List["ToolInvocation"]] = relationship(
        "ToolInvocation",
        back_populates="task",
        cascade="all, delete-orphan",
        order_by="ToolInvocation.created_at.asc()",
    )
    test_runs: Mapped[List["TestRun"]] = relationship(
        "TestRun",
        back_populates="task",
        cascade="all, delete-orphan",
        order_by="TestRun.created_at.desc()",
    )
    repair_attempts: Mapped[List["RepairAttempt"]] = relationship(
        "RepairAttempt",
        back_populates="task",
        cascade="all, delete-orphan",
        order_by="RepairAttempt.attempt_number.asc()",
    )
    verification_results: Mapped[List["VerificationResult"]] = relationship(
        "VerificationResult",
        back_populates="task",
        cascade="all, delete-orphan",
        order_by="VerificationResult.created_at.desc()",
    )
    checkpoints: Mapped[List["TaskCheckpoint"]] = relationship(
        "TaskCheckpoint",
        back_populates="task",
        cascade="all, delete-orphan",
        order_by="TaskCheckpoint.created_at.desc()",
    )
    events: Mapped[List["TaskEvent"]] = relationship(
        "TaskEvent",
        back_populates="task",
        cascade="all, delete-orphan",
        order_by="TaskEvent.created_at.asc()",
    )
    pull_request: Mapped[Optional["TaskPullRequest"]] = relationship(
        "TaskPullRequest",
        back_populates="task",
        uselist=False,
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        Index("ix_tasks_repo_status", "repository_id", "status"),
        Index("ix_tasks_repo_created", "repository_id", "created_at"),
        Index("ix_tasks_repo_source", "repository_id", "source_type", "source_id"),
    )

    def to_dict(self) -> dict[str, Any]:
        """Convert Task model to canonical response envelope dictionary (§7.3)."""
        return {
            "task_id": str(self.id),
            "repository_id": str(self.repository_id),
            "user_id": str(self.user_id) if self.user_id else None,
            "title": self.title,
            "description": self.description,
            "status": self.status,
            "source_type": self.source_type,
            "source_id": self.source_id,
            "source_metadata": self.source_metadata,
            "finding_id": str(self.finding_id) if self.finding_id else None,
            "base_revision": self.base_revision,
            "plan_version": self.plan_version,
            "approved_plan_version": self.approved_plan_version,
            "repair_attempts_used": self.repair_attempts_used,
            "repair_attempts_max": self.repair_attempts_max,
            "context_summary": self.context_summary,
            "error_message": self.error_message,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


# ---------------------------------------------------------------------------
# 2. Implementation Plans & Approvals
# ---------------------------------------------------------------------------


class TaskPlan(TimestampedModel, Base):
    """Structured implementation plan version for a task."""

    __tablename__ = "task_plans"

    task_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tasks.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    base_revision: Mapped[str] = mapped_column(String(128), nullable=False)
    summary: Mapped[str] = mapped_column(String(512), nullable=False)
    problem_statement: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Ordered implementation steps, expected files, and test commands
    steps: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)
    expected_files: Mapped[Optional[list[str]]] = mapped_column(JSONB, nullable=True)
    tests_to_run: Mapped[Optional[list[str]]] = mapped_column(JSONB, nullable=True)
    validation_strategy: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    risks: Mapped[Optional[list[str]]] = mapped_column(JSONB, nullable=True)

    status: Mapped[str] = mapped_column(
        String(32),
        default=TaskPlanStatus.PROPOSED.value,
        index=True,
        nullable=False,
    )

    task: Mapped["Task"] = relationship("Task", back_populates="plans")

    __table_args__ = (
        Index("ix_task_plans_task_version", "task_id", "version", unique=True),
    )


class TaskApproval(TimestampedModel, Base):
    """Immutable human approval or rejection record for a specific plan version."""

    __tablename__ = "task_approvals"

    task_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tasks.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    plan_version: Mapped[int] = mapped_column(Integer, nullable=False)
    user_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        index=True,
        nullable=True,
    )
    decision: Mapped[str] = mapped_column(String(32), nullable=False)  # APPROVED / REJECTED
    feedback: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    task: Mapped["Task"] = relationship("Task", back_populates="approvals")
    user: Mapped[Optional["User"]] = relationship("User")

    __table_args__ = (
        Index("ix_task_approvals_task_plan", "task_id", "plan_version"),
    )


# ---------------------------------------------------------------------------
# 3. Workspace & Execution Tracking
# ---------------------------------------------------------------------------


class Workspace(TimestampedModel, Base):
    """Dedicated workspace directory and Git worktree metadata for task execution."""

    __tablename__ = "workspaces"

    task_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tasks.id", ondelete="CASCADE"),
        unique=True,
        index=True,
        nullable=False,
    )
    workspace_path: Mapped[str] = mapped_column(String(1024), nullable=False)
    task_branch: Mapped[str] = mapped_column(String(256), nullable=False)
    base_revision: Mapped[str] = mapped_column(String(128), nullable=False)
    current_revision: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)

    status: Mapped[str] = mapped_column(
        String(32),
        default=WorkspaceStatus.NOT_CREATED.value,
        index=True,
        nullable=False,
    )
    cleanup_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    task: Mapped["Task"] = relationship("Task", back_populates="workspace")


class TaskExecution(TimestampedModel, Base):
    """Record of worker execution attempts for an approved task."""

    __tablename__ = "task_executions"

    task_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tasks.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    attempt_number: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    worker_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    status: Mapped[str] = mapped_column(
        String(32),
        default=ExecutionStatus.STARTED.value,
        index=True,
        nullable=False,
    )
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    task: Mapped["Task"] = relationship("Task", back_populates="executions")


# ---------------------------------------------------------------------------
# 4. Tool Invocations, Test Runs & Repair Attempts
# ---------------------------------------------------------------------------


class ToolInvocation(TimestampedModel, Base):
    """Audit record for operations routed through the controlled ToolRouter."""

    __tablename__ = "tool_invocations"

    task_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tasks.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    tool_name: Mapped[str] = mapped_column(String(128), index=True, nullable=False)
    sanitized_arguments: Mapped[Optional[dict[str, Any]]] = mapped_column(JSONB, nullable=True)
    status: Mapped[str] = mapped_column(String(32), index=True, nullable=False)  # ALLOWED, BLOCKED, COMPLETED, FAILED
    duration_ms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    output_summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    task: Mapped["Task"] = relationship("Task", back_populates="tool_invocations")


class TestRun(TimestampedModel, Base):
    """Execution outcome, counts, and exit code from permitted test commands."""

    __test__ = False

    __tablename__ = "test_runs"

    task_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tasks.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    command: Mapped[str] = mapped_column(String(512), nullable=False)
    status: Mapped[str] = mapped_column(String(32), index=True, nullable=False)  # PASSED, FAILED, TIMED_OUT, ERROR
    exit_code: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    duration_ms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    tests_total: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    tests_passed: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    tests_failed: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    sanitized_output: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    target_revision: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)

    task: Mapped["Task"] = relationship("Task", back_populates="test_runs")


class RepairAttempt(TimestampedModel, Base):
    """Bounded repair cycle attempt (max 3 task-level attempts)."""

    __tablename__ = "repair_attempts"

    task_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tasks.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    attempt_number: Mapped[int] = mapped_column(Integer, nullable=False)
    failure_classification: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    diagnosis: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    applied_patch: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    result: Mapped[str] = mapped_column(String(32), nullable=False)  # SUCCESS, RETRY_EXHAUSTED, FAILED

    task: Mapped["Task"] = relationship("Task", back_populates="repair_attempts")

    __table_args__ = (
        Index("ix_repair_attempts_task_attempt", "task_id", "attempt_number", unique=True),
    )


# ---------------------------------------------------------------------------
# 5. Independent Verification, Checkpoints, Timeline & Pull Requests
# ---------------------------------------------------------------------------


class VerificationResult(TimestampedModel, Base):
    """Multi-dimensional verification result tied strictly to verified revision."""

    __tablename__ = "verification_results"

    task_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tasks.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    verified_revision: Mapped[str] = mapped_column(String(128), index=True, nullable=False)
    status: Mapped[str] = mapped_column(String(32), index=True, nullable=False)

    checks: Mapped[Optional[list[dict[str, Any]]]] = mapped_column(JSONB, nullable=True)
    blocking_findings: Mapped[Optional[list[dict[str, Any]]]] = mapped_column(JSONB, nullable=True)
    warnings: Mapped[Optional[list[dict[str, Any]]]] = mapped_column(JSONB, nullable=True)
    summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    task: Mapped["Task"] = relationship("Task", back_populates="verification_results")


class TaskCheckpoint(TimestampedModel, Base):
    """Persisted snapshot state for safe worker restart recovery (secret-scrubbed)."""

    __tablename__ = "task_checkpoints"

    task_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tasks.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    step_name: Mapped[str] = mapped_column(String(128), index=True, nullable=False)
    state_data: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    recovery_instructions: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    task: Mapped["Task"] = relationship("Task", back_populates="checkpoints")


class TaskEvent(TimestampedModel, Base):
    """Ordered audit event and state transition record for timeline visualization."""

    __tablename__ = "task_events"

    task_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tasks.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    event_type: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    event_data: Mapped[Optional[dict[str, Any]]] = mapped_column(JSONB, nullable=True)
    user_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        index=True,
        nullable=True,
    )

    task: Mapped["Task"] = relationship("Task", back_populates="events")
    user: Mapped[Optional["User"]] = relationship("User")

    __table_args__ = (
        Index("ix_task_events_task_created", "task_id", "created_at"),
    )


class TaskPullRequest(TimestampedModel, Base):
    """Published GitHub Draft PR metadata and revision tracking."""

    __tablename__ = "task_pull_requests"

    task_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tasks.id", ondelete="CASCADE"),
        unique=True,
        index=True,
        nullable=False,
    )
    repository_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("repositories.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    github_pr_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    pr_number: Mapped[Optional[int]] = mapped_column(Integer, index=True, nullable=True)
    pr_url: Mapped[str] = mapped_column(String(512), nullable=False)
    base_branch: Mapped[str] = mapped_column(String(256), nullable=False)
    head_branch: Mapped[str] = mapped_column(String(256), nullable=False)
    head_sha: Mapped[str] = mapped_column(String(128), nullable=False)
    is_draft: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    body: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    task: Mapped["Task"] = relationship("Task", back_populates="pull_request")
    repository: Mapped["Repository"] = relationship("Repository")


__all__ = [
    "TaskStatus",
    "TaskSourceType",
    "TaskPlanStatus",
    "ApprovalDecision",
    "WorkspaceStatus",
    "ExecutionStatus",
    "ToolInvocationStatus",
    "TestRunStatus",
    "RepairResult",
    "VerificationStatus",
    "TaskEventType",
    "Task",
    "TaskPlan",
    "TaskApproval",
    "Workspace",
    "TaskExecution",
    "ToolInvocation",
    "TestRun",
    "RepairAttempt",
    "VerificationResult",
    "TaskCheckpoint",
    "TaskEvent",
    "TaskPullRequest",
]
