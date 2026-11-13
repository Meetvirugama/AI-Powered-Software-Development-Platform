"""Task plan versioning and lookup aggregate."""

from __future__ import annotations

import uuid
from typing import Any, Optional

from sqlalchemy import desc, func, select

from app.core.errors import APIError, ErrorCode
from app.models.task import (
    Task,
    TaskEventType,
    TaskPlan,
    TaskPlanStatus,
    TaskStatus,
)
from app.schemas.plan import PlannerSchema
from app.schemas.task import can_transition
from app.repositories.task.exceptions import (
    TaskNotFoundError,
    _ensure_uuid,
    scrub_sensitive_data,
    scrub_sensitive_text,
)

from app.repositories.task.core import TaskCoreMixin


class TaskPlanMixin:
    """Versioned implementation plan persistence and query operations."""

    def save_plan(
        self,
        task_id: uuid.UUID | str | Task | None = None,
        repository_id: uuid.UUID | str | None = None,
        summary: Optional[str] = None,
        steps: Optional[list[dict[str, Any]]] = None,
        base_revision: Optional[str] = None,
        problem_statement: Optional[str] = None,
        expected_files: Optional[list[str]] = None,
        tests_to_run: Optional[list[str]] = None,
        validation_strategy: Optional[str | list[str]] = None,
        risks: Optional[list[str] | list[dict[str, Any]]] = None,
        *,
        task: Optional[Task] = None,
        plan_schema: Optional[PlannerSchema] = None,
        actor_id: uuid.UUID | str | None = None,
    ) -> TaskPlan:
        """Create and version a structured implementation plan, invalidating stale approvals."""
        target_task: Optional[Task] = None
        if task is not None:
            target_task = task
        elif isinstance(task_id, Task):
            target_task = task_id
        elif task_id is not None:
            target_task = self.get_task(task_id, repository_id)

        if target_task is None:
            raise TaskNotFoundError(f"Task {task_id} not found in repository {repository_id}")

        # Plan schema path (Sukun Planner / Week 3 Day 2 intake)
        if plan_schema is not None:
            # Enforce forbidden_files disjointness against task constraints
            forbidden_lower: dict[str, str] = {}
            for cst in target_task.constraints or []:
                if isinstance(cst, dict):
                    for f_path in cst.get("forbidden_files", []) or []:
                        forbidden_lower[str(f_path).lower()] = str(f_path)

            violating_files = [
                f for f in plan_schema.expected_files if f.lower() in forbidden_lower
            ]
            if violating_files:
                raise APIError(
                    400,
                    ErrorCode.POLICY_VIOLATION,
                    f"Generated plan modifies forbidden protected file(s): {', '.join(sorted(set(violating_files)))}",
                )

            effective_base_rev = base_revision or target_task.base_revision
            new_hash = plan_schema.compute_plan_hash(effective_base_rev)

            existing_plans = self.list_plans(target_task.id)
            highest_v = max((p.plan_version for p in existing_plans), default=0)
            next_version = highest_v + 1

            curr_status = TaskStatus(target_task.status)
            if curr_status != TaskStatus.PLANNING:
                if not can_transition(curr_status, TaskStatus.PLANNING):
                    raise APIError(
                        409,
                        ErrorCode.INVALID_STATE_TRANSITION,
                        f"Cannot generate plan when task is in state '{curr_status.value}'.",
                    )
                target_task.status = TaskStatus.PLANNING.value

            prior_approved = target_task.approved_plan_version
            approval_invalidated = prior_approved is not None

            target_task.plan_version = next_version
            target_task.approved_plan_version = None
            if effective_base_rev:
                target_task.base_revision = effective_base_rev
                if isinstance(target_task.source_ref, dict):
                    updated_ref = dict(target_task.source_ref)
                    updated_ref["base_revision"] = effective_base_rev
                    target_task.source_ref = updated_ref

            plan_record = TaskPlan(
                id=uuid.uuid4(),
                task_id=target_task.id,
                version=next_version,
                base_revision=effective_base_rev,
                plan_hash=new_hash,
                summary=scrub_sensitive_text(plan_schema.summary),
                problem_statement=scrub_sensitive_text(plan_schema.problem_statement),
                assumptions=scrub_sensitive_data([a.model_dump(mode="json") if hasattr(a, "model_dump") else a for a in plan_schema.assumptions]),
                relevant_files=list(plan_schema.relevant_files),
                relevant_symbols=list(plan_schema.relevant_symbols),
                steps=scrub_sensitive_data([s.model_dump(mode="json") if hasattr(s, "model_dump") else s for s in plan_schema.steps]),
                expected_files=list(plan_schema.expected_files),
                tests_to_run=list(plan_schema.tests_to_run),
                validation_strategy=scrub_sensitive_text("; ".join(plan_schema.validation_strategy) if isinstance(plan_schema.validation_strategy, list) else plan_schema.validation_strategy),
                risks=scrub_sensitive_data([r.model_dump(mode="json") if hasattr(r, "model_dump") else r for r in plan_schema.risks]),
                required_permissions=list(plan_schema.required_permissions),
                resource_budget=plan_schema.resource_budget.model_dump(mode="json") if hasattr(plan_schema.resource_budget, "model_dump") else (plan_schema.resource_budget or {}),
                status=TaskPlanStatus.PENDING_APPROVAL.value,
            )
            self.session.add(plan_record)

            for old_p in existing_plans:
                if old_p.status in (TaskPlanStatus.PROPOSED.value, TaskPlanStatus.APPROVED.value, "PENDING_APPROVAL", "APPROVED"):
                    old_p.status = "SUPERSEDED"

            target_task.status = TaskStatus.PENDING_APPROVAL.value

            self.record_event(
                task_id=target_task.id,
                repository_id=target_task.repository_id,
                event_type=TaskEventType.PLAN_GENERATED.value,
                event_data={
                    "plan_version": next_version,
                    "plan_hash": new_hash,
                    "base_revision": effective_base_rev,
                    "steps_count": len(plan_schema.steps),
                    "approval_invalidated": approval_invalidated,
                    "prior_approved_plan_version": prior_approved,
                },
                user_id=actor_id,
                from_status=curr_status.value,
                to_status=TaskStatus.PENDING_APPROVAL.value,
                summary=(
                    f"Generated structured implementation plan v{next_version} ({len(plan_schema.steps)} steps)."
                    + (f" Previous approval for v{prior_approved} invalidated." if approval_invalidated else "")
                ),
            )
            self.session.commit()
            self.session.refresh(plan_record)
            self.session.refresh(target_task)
            return plan_record

        # Direct argument path (Om Day 1 Persistence)
        highest_v = (
            self.session.execute(
                select(func.max(TaskPlan.version)).where(TaskPlan.task_id == target_task.id)
            ).scalar_one_or_none()
            or 0
        )
        new_version = highest_v + 1
        rev = base_revision or target_task.base_revision

        curr_status = TaskStatus(target_task.status)
        if curr_status != TaskStatus.PLANNING:
            if not can_transition(curr_status, TaskStatus.PLANNING):
                raise APIError(
                    409,
                    ErrorCode.INVALID_STATE_TRANSITION,
                    f"Cannot generate plan when task is in state '{curr_status.value}'.",
                )
            target_task.status = TaskStatus.PLANNING.value

        prior_approved = target_task.approved_plan_version
        approval_invalidated = prior_approved is not None

        # Mark previous active plans as SUPERSEDED
        existing_plans = list(
            self.session.execute(
                select(TaskPlan).where(
                    TaskPlan.task_id == target_task.id,
                    TaskPlan.status.in_([
                        TaskPlanStatus.PROPOSED.value,
                        TaskPlanStatus.APPROVED.value,
                        "PENDING_APPROVAL",
                        "APPROVED",
                    ]),
                )
            ).scalars().all()
        )
        for prev_plan in existing_plans:
            prev_plan.status = TaskPlanStatus.SUPERSEDED.value

        validation_str = (
            "; ".join(validation_strategy)
            if isinstance(validation_strategy, list)
            else validation_strategy
        )

        plan = TaskPlan(
            id=uuid.uuid4(),
            task_id=target_task.id,
            version=new_version,
            base_revision=rev,
            summary=scrub_sensitive_text((summary or "").strip()),
            problem_statement=scrub_sensitive_text(problem_statement),
            steps=scrub_sensitive_data(steps or []),
            expected_files=expected_files or [],
            tests_to_run=tests_to_run or [],
            validation_strategy=scrub_sensitive_text(validation_str),
            risks=scrub_sensitive_data(risks) if isinstance(risks, list) else [],
            status=TaskPlanStatus.PROPOSED.value,
        )
        self.session.add(plan)

        target_task.plan_version = new_version
        target_task.approved_plan_version = None
        target_task.status = TaskStatus.PENDING_APPROVAL.value

        self.session.flush()

        self.record_event(
            task_id=target_task.id,
            repository_id=target_task.repository_id,
            event_type=TaskEventType.PLAN_GENERATED.value,
            event_data={
                "plan_version": new_version,
                "summary": plan.summary,
                "step_count": len(steps or []),
                "base_revision": rev,
                "approval_invalidated": approval_invalidated,
                "prior_approved_plan_version": prior_approved,
            },
            user_id=actor_id,
            from_status=curr_status.value,
            to_status=TaskStatus.PENDING_APPROVAL.value,
            summary=(
                f"Generated implementation plan v{new_version}."
                + (f" Previous approval for v{prior_approved} invalidated." if approval_invalidated else "")
            ),
        )

        self.session.commit()
        self.session.refresh(plan)
        return plan

    def get_plan(
        self,
        task_id: uuid.UUID | str,
        repository_id: Optional[uuid.UUID | str] = None,
        version: Optional[int] = None,
    ) -> Optional[TaskPlan]:
        """Fetch a specific plan version or the latest plan for an authorized task."""
        t_uuid = _ensure_uuid(task_id)
        if t_uuid is None:
            return None
        if repository_id is not None:
            task = self.get_task(task_id, repository_id)
            if not task:
                raise TaskNotFoundError(f"Task {task_id} not found in repository {repository_id}")
            t_uuid = task.id

        query = select(TaskPlan).where(TaskPlan.task_id == t_uuid)
        if version is not None:
            query = query.where(TaskPlan.version == version)

        query = query.order_by(desc(TaskPlan.version))
        return self.session.execute(query).scalars().first()

    def list_plans(
        self,
        task_id: uuid.UUID | str,
        repository_id: Optional[uuid.UUID | str] = None,
    ) -> list[TaskPlan]:
        """List all plan versions for a task, ordered by version descending."""
        t_uuid = _ensure_uuid(task_id)
        if t_uuid is None:
            return []
        if repository_id is not None:
            task = self.get_task(task_id, repository_id)
            if not task:
                raise TaskNotFoundError(f"Task {task_id} not found in repository {repository_id}")
            t_uuid = task.id
        stmt = (
            select(TaskPlan)
            .where(TaskPlan.task_id == t_uuid)
            .order_by(TaskPlan.version.asc())
        )
        return list(self.session.scalars(stmt).all())

    def get_latest_plan(self, task_id: uuid.UUID | str) -> Optional[TaskPlan]:
        """Return the most recent plan version for a task."""
        t_uuid = _ensure_uuid(task_id)
        if t_uuid is None:
            return None
        stmt = (
            select(TaskPlan)
            .where(TaskPlan.task_id == t_uuid)
            .order_by(TaskPlan.version.desc())
        )
        return self.session.scalars(stmt).first()

    def get_plan_by_version(
        self,
        task_id: uuid.UUID | str,
        plan_version: int,
    ) -> Optional[TaskPlan]:
        """Return a specific version of a plan for a task."""
        t_uuid = _ensure_uuid(task_id)
        if t_uuid is None:
            return None
        stmt = select(TaskPlan).where(
            TaskPlan.task_id == t_uuid,
            TaskPlan.version == int(plan_version),
        )
        return self.session.scalars(stmt).first()

    def get_approved_plan(
        self,
        task_id: uuid.UUID | str,
    ) -> Optional[TaskPlan]:
        """Return the currently approved plan for a task, or None if unapproved."""
        t_uuid = _ensure_uuid(task_id)
        if t_uuid is None:
            return None
        task = self.get_task(t_uuid)
        if not task or not task.approved_plan_version:
            return None
        return self.get_plan_by_version(task.id, task.approved_plan_version)


class TaskPlanRepository(TaskPlanMixin, TaskCoreMixin):
    """Standalone domain aggregate for versioned task plans."""
