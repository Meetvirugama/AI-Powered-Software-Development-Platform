"""Modular domain-specific persistence aggregates for Tasks & Workflows."""

from app.repositories.task.approvals import TaskApprovalMixin, TaskApprovalRepository
from app.repositories.task.core import TaskCoreMixin
from app.repositories.task.exceptions import (
    InvalidStateTransitionError,
    PlanNotFoundError,
    TaskNotFoundError,
    TaskRepositoryBase,
    VALID_TRANSITIONS,
    _ensure_uuid,
    scrub_sensitive_data,
    scrub_sensitive_text,
)
from app.repositories.task.executions import TaskExecutionMixin, TaskExecutionRepository
from app.repositories.task.plans import TaskPlanMixin, TaskPlanRepository
from app.repositories.task.publication import TaskPublicationMixin, TaskPublicationRepository

__all__ = [
    "InvalidStateTransitionError",
    "PlanNotFoundError",
    "TaskApprovalMixin",
    "TaskApprovalRepository",
    "TaskCoreMixin",
    "TaskExecutionMixin",
    "TaskExecutionRepository",
    "TaskNotFoundError",
    "TaskPlanMixin",
    "TaskPlanRepository",
    "TaskPublicationMixin",
    "TaskPublicationRepository",
    "TaskRepositoryBase",
    "VALID_TRANSITIONS",
    "_ensure_uuid",
    "scrub_sensitive_data",
    "scrub_sensitive_text",
]
