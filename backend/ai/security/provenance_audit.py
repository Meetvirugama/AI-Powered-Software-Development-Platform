"""Structured Security Audit Logging for Provenance and Policy Decisions.

Reference:
- Task Security Specification (§10 Structured Security Audit Logging)
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
import logging
import threading
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from app.core.secret_redaction import redact_obj

logger = logging.getLogger(__name__)


class ProvenanceAuditEventType(str, Enum):
    """Categorized security audit event types for provenance and execution policy."""

    PROVENANCE_CREATED = "PROVENANCE_CREATED"
    TAINT_PROPAGATED = "TAINT_PROPAGATED"
    PROVENANCE_VALIDATION_FAILED = "PROVENANCE_VALIDATION_FAILED"
    EXECUTION_POLICY_EVALUATED = "EXECUTION_POLICY_EVALUATED"
    EXECUTION_APPROVAL_REQUIRED = "EXECUTION_APPROVAL_REQUIRED"
    EXECUTION_APPROVED = "EXECUTION_APPROVED"
    EXECUTION_DENIED = "EXECUTION_DENIED"
    EXECUTION_COMPLETED = "EXECUTION_COMPLETED"


class ProvenanceAuditEvent(BaseModel):
    """Immutable structured audit event capturing security and lineage decisions."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    event_id: str = Field(
        default_factory=lambda: f"audit-{uuid4().hex[:12]}",
        description="Unique identifier for the audit event.",
    )
    event_type: ProvenanceAuditEventType = Field(
        ...,
        description="Category of the audit event.",
    )
    timestamp: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(),
        description="UTC timestamp of the event.",
    )
    task_id: str | None = Field(
        default=None,
        description="Task ID associated with the event.",
    )
    step_id: str | None = Field(
        default=None,
        description="Plan step ID associated with the event.",
    )
    action_type: str | None = Field(
        default=None,
        description="Action type evaluated or executed.",
    )
    provenance_ids: list[str] = Field(
        default_factory=list,
        description="List of relevant provenance IDs.",
    )
    policy_decision: str | None = Field(
        default=None,
        description="Decision outcome (ALLOW, DENY, REQUIRES_APPROVAL).",
    )
    reason: str | None = Field(
        default=None,
        description="Security explanation or denial reason.",
    )
    resource_scope: list[str] = Field(
        default_factory=list,
        description="Files, targets, or resources scoped in the event.",
    )
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="Sanitized contextual metadata (secrets strictly redacted).",
    )

    def to_dict(self) -> dict[str, Any]:
        """Convert audit event to dictionary."""
        return self.model_dump(mode="json")


class ProvenanceAuditLogger:
    """Thread-safe structured audit logger for provenance tracking and policy gates."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._events: list[ProvenanceAuditEvent] = []

    def log(self, event: ProvenanceAuditEvent) -> None:
        """Record a structured audit event."""
        with self._lock:
            self._events.append(event)
        logger.info(
            "SECURITY_AUDIT: [%s] event=%s task=%s step=%s decision=%s reason=%s",
            event.event_id,
            event.event_type.value,
            event.task_id or "-",
            event.step_id or "-",
            event.policy_decision or "-",
            event.reason or "-",
        )

    def record_event(
        self,
        *,
        event_type: ProvenanceAuditEventType,
        task_id: str | None = None,
        step_id: str | None = None,
        action_type: str | None = None,
        provenance_ids: list[str] | None = None,
        policy_decision: str | None = None,
        reason: str | None = None,
        resource_scope: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> ProvenanceAuditEvent:
        """Create and record an audit event with secret redaction."""
        clean_meta = redact_obj(dict(metadata or {})) if metadata else {}
        clean_scope = [str(r) for r in (resource_scope or [])]
        clean_prov_ids = [str(p) for p in (provenance_ids or [])]

        event = ProvenanceAuditEvent(
            event_type=event_type,
            task_id=str(task_id) if task_id else None,
            step_id=str(step_id) if step_id else None,
            action_type=str(action_type) if action_type else None,
            provenance_ids=clean_prov_ids,
            policy_decision=policy_decision,
            reason=reason,
            resource_scope=clean_scope,
            metadata=clean_meta,
        )
        self.log(event)
        return event

    def get_events(
        self,
        task_id: str | None = None,
        event_type: ProvenanceAuditEventType | None = None,
    ) -> list[ProvenanceAuditEvent]:
        """Query recorded audit events, optionally filtered by task or event type."""
        with self._lock:
            results = list(self._events)

        if task_id:
            results = [e for e in results if e.task_id == str(task_id)]
        if event_type:
            results = [e for e in results if e.event_type == event_type]
        return results

    def clear(self) -> None:
        """Clear recorded events (for test isolation)."""
        with self._lock:
            self._events.clear()


_GLOBAL_AUDIT_LOGGER = ProvenanceAuditLogger()


def get_provenance_audit_logger() -> ProvenanceAuditLogger:
    """Return the global ProvenanceAuditLogger singleton."""
    return _GLOBAL_AUDIT_LOGGER


def reset_provenance_audit_logger() -> None:
    """Reset the global audit logger (used in tests)."""
    _GLOBAL_AUDIT_LOGGER.clear()


__all__ = [
    "ProvenanceAuditEvent",
    "ProvenanceAuditEventType",
    "ProvenanceAuditLogger",
    "get_provenance_audit_logger",
    "reset_provenance_audit_logger",
]
