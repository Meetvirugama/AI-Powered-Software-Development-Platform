"""Tool Approval Gate Service.

Part of F19 — Human approval gate (Issue #199).
Provides cryptographic binding of tool name and canonical argument hash to human approval,
enforcing single-use atomic consumption, expiration TTL, and zero raw secrets exposure.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import json
import logging
from typing import Any
import uuid
from uuid import UUID

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from agent.tools.models import is_approval_required
from app.core.errors import APIError, ErrorCode
from app.core.secret_redaction import redact_obj
from app.models.task import AgentTask, TaskApproval

logger = logging.getLogger(__name__)


def _as_utc(dt: datetime | None) -> datetime | None:
    """Normalize datetime to timezone-aware UTC datetime."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def canonicalize_tool_arguments(arguments: dict[str, Any] | None) -> str:
    """Deterministically serialize tool arguments into a sorted JSON string.

    Ensures that argument key order, nested dictionary ordering, and whitespace
    variations produce identical canonical representations.
    """
    if arguments is None:
        arguments = {}
    return json.dumps(arguments, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def compute_argument_hash(arguments: dict[str, Any] | None) -> str:
    """Compute deterministic SHA-256 digest of canonicalized tool arguments."""
    canonical = canonicalize_tool_arguments(arguments)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class ToolApprovalGateService:
    """Service governing explicit human approval for high-risk tool executions."""

    def __init__(self, default_ttl_seconds: int = 3600) -> None:
        self.default_ttl_seconds = default_ttl_seconds

    def request_tool_approval(
        self,
        session: Session,
        task: AgentTask,
        tool_name: str,
        arguments: dict[str, Any] | None,
        user_id: UUID | None = None,
        risk_tier: str | None = None,
        expires_in_seconds: int | None = None,
    ) -> TaskApproval:
        """Create or return an existing pending approval request for a tool invocation.

        Bound to the exact task_id, tool_name, and SHA-256 argument hash.
        Stored arguments are scrubbed using redact_obj to prevent secret leakage.
        """
        arg_hash = compute_argument_hash(arguments)
        now = datetime.now(timezone.utc)
        ttl = expires_in_seconds or self.default_ttl_seconds

        # Check if an active pending approval already exists for this exact tool and arguments
        existing = session.execute(
            select(TaskApproval)
            .where(
                TaskApproval.task_id == task.id,
                TaskApproval.approval_type == "tool",
                TaskApproval.tool_name == tool_name,
                TaskApproval.argument_hash == arg_hash,
                TaskApproval.status == "pending",
            )
            .order_by(desc(TaskApproval.created_at))
        ).scalars().first()

        if existing:
            exp = _as_utc(existing.expires_at)
            if exp and exp < now:
                existing.status = "expired"
                existing.decision = "EXPIRED"
                session.commit()
            else:
                return existing

        # Create new pending approval record
        approval = TaskApproval(
            task_id=task.id,
            plan_id=getattr(task, "approved_plan_id", None),
            plan_version=getattr(task, "approved_plan_version", 1) or 1,
            user_id=user_id,
            plan_hash="",
            decision="PENDING",
            feedback=None,
            approval_type="tool",
            tool_name=tool_name,
            argument_hash=arg_hash,
            sanitized_arguments=redact_obj(dict(arguments or {})),
            risk_level=risk_tier or "write-external",
            status="pending",
            expires_at=now + timedelta(seconds=ttl),
        )
        session.add(approval)
        session.commit()
        session.refresh(approval)
        logger.info(
            "Created tool approval request %s for task %s tool %s (hash: %s)",
            approval.id,
            task.id,
            tool_name,
            arg_hash[:12],
        )
        return approval

    def approve_tool(
        self,
        session: Session,
        task_id: UUID,
        approval_id: UUID,
        user_id: UUID | None = None,
        feedback: str | None = None,
    ) -> TaskApproval:
        """Approve a pending tool approval request."""
        approval = session.execute(
            select(TaskApproval).where(
                TaskApproval.task_id == task_id,
                TaskApproval.id == approval_id,
            )
        ).scalars().first()

        if not approval:
            raise APIError(404, ErrorCode.RESOURCE_NOT_FOUND, "Tool approval record not found")

        if approval.approval_type != "tool":
            raise APIError(400, ErrorCode.BAD_REQUEST, "Approval record is not a tool approval")

        if approval.status != "pending":
            raise APIError(
                409,
                ErrorCode.CONFLICT,
                f"Tool approval cannot be approved in state '{approval.status}'",
            )

        now = datetime.now(timezone.utc)
        exp = _as_utc(approval.expires_at)
        if exp and exp < now:
            approval.status = "expired"
            approval.decision = "EXPIRED"
            session.commit()
            raise APIError(410, ErrorCode.APPROVAL_EXPIRED, "Tool approval has expired")

        approval.status = "approved"
        approval.decision = "APPROVED"
        approval.user_id = user_id or approval.user_id
        approval.feedback = feedback
        session.commit()
        session.refresh(approval)
        logger.info("Tool approval %s approved by user %s", approval.id, user_id)
        return approval

    def reject_tool(
        self,
        session: Session,
        task_id: UUID,
        approval_id: UUID,
        user_id: UUID | None = None,
        reason: str | None = None,
    ) -> TaskApproval:
        """Reject a pending tool approval request."""
        approval = session.execute(
            select(TaskApproval).where(
                TaskApproval.task_id == task_id,
                TaskApproval.id == approval_id,
            )
        ).scalars().first()

        if not approval:
            raise APIError(404, ErrorCode.RESOURCE_NOT_FOUND, "Tool approval record not found")

        if approval.approval_type != "tool":
            raise APIError(400, ErrorCode.BAD_REQUEST, "Approval record is not a tool approval")

        if approval.status != "pending":
            raise APIError(
                409,
                ErrorCode.CONFLICT,
                f"Tool approval cannot be rejected in state '{approval.status}'",
            )

        approval.status = "rejected"
        approval.decision = "REJECTED"
        approval.user_id = user_id or approval.user_id
        approval.feedback = reason or "Tool approval rejected by reviewer."
        session.commit()
        session.refresh(approval)
        logger.info("Tool approval %s rejected by user %s", approval.id, user_id)
        return approval

    def verify_and_consume_tool(
        self,
        session: Session,
        task: AgentTask,
        tool_name: str,
        arguments: dict[str, Any] | None,
        user_id: UUID | None = None,
        risk_tier: str | None = None,
    ) -> TaskApproval | None:
        """Verify explicit human approval for high-risk tools and atomically consume it.

        If risk_tier does not require approval, returns None without side effects.
        If approval is required:
        - Computes argument hash and checks for matching approved, unexpired record.
        - If matched, transitions state atomically to 'consumed' with consumed_at timestamp.
        - If no matching approval exists, automatically provisions a pending approval request
          and raises APIError(403, ErrorCode.APPROVAL_REQUIRED, ...).
        - If matching approval is expired, marks expired and raises APIError(410).
        """
        if not is_approval_required(risk_tier):
            return None

        arg_hash = compute_argument_hash(arguments)
        now = datetime.now(timezone.utc)

        # Look for approved record matching exact task, tool, and argument hash
        approval = session.execute(
            select(TaskApproval)
            .where(
                TaskApproval.task_id == task.id,
                TaskApproval.approval_type == "tool",
                TaskApproval.tool_name == tool_name,
                TaskApproval.argument_hash == arg_hash,
                TaskApproval.status == "approved",
            )
            .order_by(desc(TaskApproval.created_at))
        ).scalars().first()

        if approval:
            # Check expiration TTL
            exp = _as_utc(approval.expires_at)
            if exp and exp < now:
                approval.status = "expired"
                approval.decision = "EXPIRED"
                session.commit()
                raise APIError(
                    410,
                    ErrorCode.APPROVAL_EXPIRED,
                    f"Tool approval for '{tool_name}' has expired.",
                )

            # Single-use consumption guarantee
            approval.status = "consumed"
            approval.decision = "CONSUMED"
            approval.consumed_at = now
            session.commit()
            session.refresh(approval)
            logger.info(
                "Tool approval %s consumed for task %s tool %s (hash: %s)",
                approval.id,
                task.id,
                tool_name,
                arg_hash[:12],
            )
            return approval

        # No valid approved record. Ensure a pending record exists so user can review it in UI.
        self.request_tool_approval(session, task, tool_name, arguments, user_id, risk_tier)
        raise APIError(
            403,
            ErrorCode.APPROVAL_REQUIRED,
            f"Tool '{tool_name}' with risk tier '{risk_tier}' requires explicit human approval before execution.",
        )

    def list_tool_approvals(
        self,
        session: Session,
        task_id: UUID,
        status: str | None = None,
    ) -> list[TaskApproval]:
        """List tool approvals for a task, optionally filtered by status."""
        query = select(TaskApproval).where(
            TaskApproval.task_id == task_id,
            TaskApproval.approval_type == "tool",
        )
        if status:
            query = query.where(TaskApproval.status == status.lower())
        query = query.order_by(desc(TaskApproval.created_at))
        return list(session.execute(query).scalars().all())


# Singleton instance
tool_approval_gate_service = ToolApprovalGateService()
