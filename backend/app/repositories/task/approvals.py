"""Task plan approval, rejection, and execution-gate aggregate."""

from __future__ import annotations

import hashlib
import json
import uuid
from typing import Any, Optional

from sqlalchemy import desc, select

from app.core.errors import APIError, ErrorCode
from app.models.task import (
    ApprovalDecision,
    Task,
    TaskApproval,
    TaskEventType,
    TaskPlan,
    TaskPlanStatus,
    TaskStatus,
)
from app.schemas.plan import PlannerSchema
from app.repositories.task.exceptions import (
    PlanNotFoundError,
    TaskNotFoundError,
    _ensure_uuid,
    scrub_sensitive_text,
)

from app.repositories.task.core import TaskCoreMixin
from app.repositories.task.plans import TaskPlanMixin


class TaskApprovalMixin:
    """Immutable human approval decisions and execution gate verification."""

    def get_approval(
        self,
        task_id: uuid.UUID | str,
        repository_id: Optional[uuid.UUID | str] = None,
        plan_version: Optional[int] = None,
    ) -> Optional[TaskApproval]:
        """Fetch approval for a specific plan version or latest approval for an authorized task."""
        t_uuid = _ensure_uuid(task_id)
        if t_uuid is None:
            return None
        if repository_id is not None:
            task = self.get_task(task_id, repository_id)
            if not task:
                raise TaskNotFoundError(f"Task {task_id} not found in repository {repository_id}")
            t_uuid = task.id

        query = select(TaskApproval).where(TaskApproval.task_id == t_uuid)
        if plan_version is not None:
            query = query.where(TaskApproval.plan_version == plan_version)

        query = query.order_by(desc(TaskApproval.plan_version), desc(TaskApproval.created_at))
        return self.session.execute(query).scalars().first()

    def list_approvals(
        self,
        task_id: uuid.UUID | str,
        repository_id: Optional[uuid.UUID | str] = None,
    ) -> list[TaskApproval]:
        """List all approval and rejection records for an authorized task ordered by creation time."""
        t_uuid = _ensure_uuid(task_id)
        if t_uuid is None:
            return []
        if repository_id is not None:
            task = self.get_task(task_id, repository_id)
            if not task:
                raise TaskNotFoundError(f"Task {task_id} not found in repository {repository_id}")
            t_uuid = task.id

        stmt = select(TaskApproval).where(TaskApproval.task_id == t_uuid).order_by(TaskApproval.created_at.asc())
        return list(self.session.execute(stmt).scalars().all())

    def approve_plan(
        self,
        task_id: uuid.UUID | str | Task | None = None,
        repository_id: uuid.UUID | str | None = None,
        plan_version: Optional[int] = None,
        user_id: Optional[uuid.UUID | str] = None,
        feedback: Optional[str] = None,
        *,
        task: Optional[Task] = None,
        approver_id: uuid.UUID | str | None = None,
        base_revision: str | None = None,
        comment: str | None = None,
    ) -> TaskApproval:
        """Record an immutable plan approval and advance task to APPROVED."""
        target_task: Optional[Task] = None
        if task is not None:
            target_task = task
        elif isinstance(task_id, Task):
            target_task = task_id
        elif task_id is not None:
            target_task = self.get_task(task_id, repository_id)

        if target_task is None:
            raise TaskNotFoundError(f"Task {task_id} not found in repository {repository_id}")

        effective_user_id = user_id or approver_id
        u_uuid = _ensure_uuid(effective_user_id)

        latest_plan = self.get_latest_plan(target_task.id)
        if latest_plan is None:
            raise APIError(
                409,
                ErrorCode.INVALID_STATE_TRANSITION,
                "Cannot approve task before an implementation plan has been generated.",
            )

        target_version = plan_version if plan_version is not None else latest_plan.plan_version

        if plan_version is not None and int(plan_version) != latest_plan.plan_version:
            plan_record = self.get_plan_by_version(target_task.id, plan_version)
            if not plan_record:
                raise PlanNotFoundError(f"Plan version {plan_version} does not exist for task {target_task.id}")
            raise APIError(
                409,
                ErrorCode.PLAN_VERSION_MISMATCH,
                f"Requested approval for plan_version {plan_version}, but current plan_version is {latest_plan.plan_version}.",
            )

        if base_revision is not None and latest_plan.base_revision and base_revision.strip() != latest_plan.base_revision:
            raise APIError(
                409,
                ErrorCode.PLAN_VERSION_MISMATCH,
                f"Base revision '{base_revision}' does not match plan base revision '{latest_plan.base_revision}'. Please re-plan.",
            )

        if target_task.base_revision and latest_plan.base_revision and target_task.base_revision != latest_plan.base_revision:
            raise APIError(
                409,
                ErrorCode.PLAN_VERSION_MISMATCH,
                "Task base revision has drifted from the plan base revision. Please generate a new plan version.",
            )

        curr_status = TaskStatus(target_task.status)
        if curr_status == TaskStatus.REJECTED:
            raise APIError(
                409,
                ErrorCode.INVALID_STATE_TRANSITION,
                "A rejected plan cannot be approved directly. Generate a revised plan first.",
            )

        safe_feedback = scrub_sensitive_text(feedback or comment)

        approval = TaskApproval(
            id=uuid.uuid4(),
            task_id=target_task.id,
            plan_id=latest_plan.id,
            plan_version=target_version,
            user_id=u_uuid,
            decision=ApprovalDecision.APPROVED.value,
            feedback=safe_feedback,
            plan_hash=latest_plan.plan_hash,
            base_revision=latest_plan.base_revision,
        )
        self.session.add(approval)

        latest_plan.status = TaskPlanStatus.APPROVED.value
        prev_status = target_task.status
        target_task.approved_plan_version = target_version
        target_task.status = TaskStatus.APPROVED.value
        self.session.flush()

        self.record_event(
            task_id=target_task.id,
            repository_id=target_task.repository_id,
            event_type=TaskEventType.PLAN_APPROVED.value,
            event_data={
                "plan_version": target_version,
                "plan_hash": latest_plan.plan_hash,
                "base_revision": latest_plan.base_revision,
                "decision": approval.decision,
                "comment": safe_feedback,
            },
            user_id=effective_user_id,
            from_status=prev_status,
            to_status=TaskStatus.APPROVED.value,
            summary=f"Plan v{target_version} approved by user.",
        )

        self.session.commit()
        self.session.refresh(approval)
        self.session.refresh(target_task)
        return approval

    def reject_plan(
        self,
        task_id: uuid.UUID | str | Task | None = None,
        repository_id: uuid.UUID | str | None = None,
        plan_version: Optional[int] = None,
        user_id: Optional[uuid.UUID | str] = None,
        feedback: Optional[str] = None,
        *,
        task: Optional[Task] = None,
        approver_id: uuid.UUID | str | None = None,
        reason: str | None = None,
    ) -> TaskApproval:
        """Reject the current pending implementation plan version."""
        target_task: Optional[Task] = None
        if task is not None:
            target_task = task
        elif isinstance(task_id, Task):
            target_task = task_id
        elif task_id is not None:
            target_task = self.get_task(task_id, repository_id)

        if target_task is None:
            raise TaskNotFoundError(f"Task {task_id} not found in repository {repository_id}")

        effective_user_id = user_id or approver_id
        u_uuid = _ensure_uuid(effective_user_id)

        latest_plan = self.get_latest_plan(target_task.id)
        if latest_plan is None:
            raise APIError(
                409,
                ErrorCode.INVALID_STATE_TRANSITION,
                "Cannot reject task before an implementation plan has been generated.",
            )

        target_version = plan_version if plan_version is not None else latest_plan.plan_version

        if plan_version is not None and int(plan_version) != latest_plan.plan_version:
            plan_record = self.get_plan_by_version(target_task.id, plan_version)
            if not plan_record:
                raise PlanNotFoundError(f"Plan version {plan_version} does not exist for task {target_task.id}")
            raise APIError(
                409,
                ErrorCode.PLAN_VERSION_MISMATCH,
                f"Requested rejection for plan_version {plan_version}, but current plan_version is {latest_plan.plan_version}.",
            )

        safe_reason = scrub_sensitive_text(feedback or reason)

        approval = TaskApproval(
            id=uuid.uuid4(),
            task_id=target_task.id,
            plan_id=latest_plan.id,
            plan_version=target_version,
            user_id=u_uuid,
            decision=ApprovalDecision.REJECTED.value,
            feedback=safe_reason,
            plan_hash=latest_plan.plan_hash,
            base_revision=latest_plan.base_revision,
        )
        self.session.add(approval)

        latest_plan.status = TaskPlanStatus.REJECTED.value
        prev_status = target_task.status
        target_task.status = TaskStatus.REJECTED.value
        target_task.approved_plan_version = None
        self.session.flush()

        self.record_event(
            task_id=target_task.id,
            repository_id=target_task.repository_id,
            event_type="PLAN_REJECTED",
            event_data={
                "plan_version": target_version,
                "plan_hash": latest_plan.plan_hash,
                "base_revision": latest_plan.base_revision,
                "decision": approval.decision,
                "reason": safe_reason,
                "feedback": safe_reason,
                "approver_id": str(effective_user_id) if effective_user_id else None,
            },
            user_id=effective_user_id,
            from_status=prev_status,
            to_status=TaskStatus.REJECTED.value,
            summary=f"Plan v{target_version} rejected by user.",
        )

        self.session.commit()
        self.session.refresh(approval)
        self.session.refresh(target_task)
        return approval

    def verify_execution_approval_gate(self, task: Task) -> TaskPlan:
        """Server-enforced approval gate (Sukun W3 Day 2 — Docs/week3.md §6 F32 & §7.2).

        Blocks execution unless:
        1. `task.status` is `APPROVED` (or `WORKSPACE_SETUP` / `EXECUTING` when already started).
        2. `task.approved_plan_version` is non-null and equals `task.plan_version`.
        3. The latest `TaskPlan` matches `task.approved_plan_version` and `task.base_revision`.
        4. An immutable `TaskApproval` with `decision == 'APPROVED'` exists for `(task.id, latest_plan.plan_version, latest_plan.plan_hash)`.
        5. Recomputes the structural SHA-256 `plan_hash` from the persisted `latest_plan` steps/files/base_revision to detect any post-approval tampering.
        """
        curr_status = TaskStatus(task.status)
        if curr_status in (TaskStatus.CREATED, TaskStatus.PLANNING, TaskStatus.PENDING_APPROVAL):
            raise APIError(
                403,
                ErrorCode.APPROVAL_REQUIRED,
                "The task cannot execute until the implementation plan is explicitly approved by a human.",
            )
        if curr_status == TaskStatus.REJECTED:
            raise APIError(
                403,
                ErrorCode.APPROVAL_REQUIRED,
                "The implementation plan was rejected. Generate and approve a revised plan before executing.",
            )
        if curr_status in (TaskStatus.CANCELLED, TaskStatus.FAILED, TaskStatus.BLOCKED):
            raise APIError(
                409,
                ErrorCode.INVALID_STATE_TRANSITION,
                f"Task in terminal/blocked status '{curr_status.value}' cannot be executed.",
            )

        if task.approved_plan_version is None:
            raise APIError(
                403,
                ErrorCode.APPROVAL_REQUIRED,
                "Task has no approved plan version. Human approval is required before execution.",
            )

        if task.approved_plan_version != task.plan_version:
            raise APIError(
                409,
                ErrorCode.PLAN_VERSION_MISMATCH,
                f"Approved plan version (v{task.approved_plan_version}) does not match current plan version (v{task.plan_version}). Renewed approval is required.",
            )

        latest_plan = self.get_latest_plan(task.id)
        if latest_plan is None:
            raise APIError(
                404,
                ErrorCode.RESOURCE_NOT_FOUND,
                f"No plan records found for task {task.id}.",
            )

        if latest_plan.plan_version != task.approved_plan_version:
            raise APIError(
                409,
                ErrorCode.PLAN_VERSION_MISMATCH,
                f"Latest plan version (v{latest_plan.plan_version}) does not match approved version (v{task.approved_plan_version}).",
            )

        if task.base_revision and latest_plan.base_revision and task.base_revision != latest_plan.base_revision:
            raise APIError(
                409,
                ErrorCode.PLAN_VERSION_MISMATCH,
                f"Task base revision '{task.base_revision}' differs from plan base revision '{latest_plan.base_revision}'. Re-plan and renewed approval required.",
            )

        # Confirm that an immutable approval record exists
        stmt = (
            select(TaskApproval)
            .where(
                TaskApproval.task_id == task.id,
                TaskApproval.plan_version == latest_plan.plan_version,
                TaskApproval.decision == "APPROVED",
            )
            .order_by(TaskApproval.created_at.desc())
        )
        approval_rec = self.session.scalars(stmt).first()
        if approval_rec is None:
            raise APIError(
                403,
                ErrorCode.APPROVAL_REQUIRED,
                f"No valid immutable approval record found for plan v{latest_plan.plan_version}.",
            )

        if latest_plan.plan_hash and approval_rec.plan_hash and latest_plan.plan_hash != approval_rec.plan_hash:
            raise APIError(
                409,
                ErrorCode.PLAN_VERSION_MISMATCH,
                "Tampering detected: plan hash does not match approval record hash. Renewed approval required.",
            )

        # Tampering check: recompute plan hash directly from persisted material fields
        if latest_plan.plan_hash:
            material = {
                "base_revision": latest_plan.base_revision or "",
                "summary": latest_plan.summary or "",
                "expected_files": sorted(latest_plan.expected_files or []),
                "steps": [
                    {
                        "step_id": s.get("step_id") if isinstance(s, dict) else getattr(s, "step_id", ""),
                        "action_type": (s.get("action_type") or s.get("step_type") or "modify") if isinstance(s, dict) else (getattr(s, "action_type", None) or getattr(s, "step_type", None) or "modify"),
                        "description": s.get("description", "") if isinstance(s, dict) else getattr(s, "description", ""),
                        "expected_files": sorted(s.get("expected_files", [])) if isinstance(s, dict) else sorted(getattr(s, "expected_files", []) or []),
                        "depends_on": sorted(s.get("depends_on") or s.get("dependencies") or []) if isinstance(s, dict) else sorted(getattr(s, "depends_on", None) or getattr(s, "dependencies", None) or []),
                        "verification": list(s.get("verification") or []) if isinstance(s, dict) else list(getattr(s, "verification", []) or []),
                    }
                    for s in (latest_plan.steps or [])
                ],
            }
            canonical = json.dumps(material, sort_keys=True, separators=(",", ":"))
            direct_hash = hashlib.sha256(canonical.encode("utf-8")).hexdigest()

            if direct_hash != latest_plan.plan_hash:
                # Secondary check via reconstructed schema
                try:
                    reconstructed_schema = PlannerSchema(
                        summary=latest_plan.summary,
                        problem_statement=latest_plan.problem_statement or "",
                        assumptions=latest_plan.assumptions or [],
                        relevant_files=latest_plan.relevant_files or [],
                        relevant_symbols=latest_plan.relevant_symbols or [],
                        steps=latest_plan.steps or [],
                        expected_files=latest_plan.expected_files or [],
                        tests_to_run=latest_plan.tests_to_run or [],
                        validation_strategy=latest_plan.validation_strategy if isinstance(latest_plan.validation_strategy, list) else ([latest_plan.validation_strategy] if latest_plan.validation_strategy else []),
                        risks=latest_plan.risks or [],
                        required_permissions=latest_plan.required_permissions or [],
                        resource_budget=latest_plan.resource_budget or {},
                    )
                    schema_hash = reconstructed_schema.compute_plan_hash(latest_plan.base_revision)
                    if schema_hash != latest_plan.plan_hash:
                        raise APIError(
                            409,
                            ErrorCode.PLAN_VERSION_MISMATCH,
                            "Plan tampering detected: recomputed plan hash does not match stored hash. Execution halted.",
                        )
                except APIError:
                    raise
                except Exception:
                    raise APIError(
                        409,
                        ErrorCode.PLAN_VERSION_MISMATCH,
                        "Plan tampering detected: recomputed plan hash does not match stored hash. Execution halted.",
                    )

        return latest_plan

    def update_approval(self, approval_id: uuid.UUID | str, *args: Any, **kwargs: Any) -> None:
        """Enforce human approval immutability. Approval decisions cannot be altered."""
        raise PermissionError("Task approvals are immutable and cannot be modified.")


class TaskApprovalRepository(TaskApprovalMixin, TaskPlanMixin, TaskCoreMixin):
    """Standalone domain aggregate for task plan approvals."""
