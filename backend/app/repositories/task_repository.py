"""Task and Workflow Persistence Repository facade (F32 / F39).

Composes modular domain-specific aggregates:
- `plans`: ``TaskPlanMixin`` / ``TaskPlanRepository``
- `approvals`: ``TaskApprovalMixin`` / ``TaskApprovalRepository``
- `executions`: ``TaskExecutionMixin`` / ``TaskExecutionRepository``
- `publication`: ``TaskPublicationMixin`` / ``TaskPublicationRepository``
- `core`: ``TaskCoreMixin`` (task intake, lifecycle transitions, audit timeline, GitHub issues)

Preserves 100% backwards compatibility for all ``TaskRepository`` imports and methods.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.repositories.task import (
    InvalidStateTransitionError,
    PlanNotFoundError,
    TaskApprovalMixin,
    TaskApprovalRepository,
    TaskCoreMixin,
    TaskExecutionMixin,
    TaskExecutionRepository,
    TaskNotFoundError,
    TaskPlanMixin,
    TaskPlanRepository,
    TaskPublicationMixin,
    TaskPublicationRepository,
    VALID_TRANSITIONS,
    _ensure_uuid,
    scrub_sensitive_data,
    scrub_sensitive_text,
)


class TaskRepository(
    TaskPublicationMixin,
    TaskExecutionMixin,
    TaskApprovalMixin,
    TaskPlanMixin,
    TaskCoreMixin,
):
    """Unified backwards-compatible facade over domain-specific Task aggregates."""

    def __init__(self, session: Session) -> None:
        super().__init__(session)

    @property
    def plans(self) -> TaskPlanRepository:
        """Return a plan-focused repository bound to the active session."""
        return TaskPlanRepository(self.session)

    @property
    def approvals(self) -> TaskApprovalRepository:
        """Return an approval-focused repository bound to the active session."""
        return TaskApprovalRepository(self.session)

    @property
    def executions(self) -> TaskExecutionRepository:
        """Return an execution-focused repository bound to the active session."""
        return TaskExecutionRepository(self.session)

    @property
    def publication(self) -> TaskPublicationRepository:
        """Return a publication-focused repository bound to the active session."""
        return TaskPublicationRepository(self.session)


__all__ = [
    "InvalidStateTransitionError",
    "PlanNotFoundError",
    "TaskApprovalRepository",
    "TaskExecutionRepository",
    "TaskNotFoundError",
    "TaskPlanRepository",
    "TaskPublicationRepository",
    "TaskRepository",
    "VALID_TRANSITIONS",
    "_ensure_uuid",
    "scrub_sensitive_data",
    "scrub_sensitive_text",
]
