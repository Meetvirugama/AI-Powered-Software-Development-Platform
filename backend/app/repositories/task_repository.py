"""Database query & persistence layer for Week 3 GitHub Issues, Tasks, Plans, Approvals, and Events.

Owner: Om — Week 3 Day 1–2 Persistence & Recovery (Docs/week3.md §6 F31, F32, F39 & Docs/daily_tasks.md)

Responsibilities:
1. Persist and deduplicate GitHub issues by `(repository_id, issue_number)`.
2. Persist `AgentTask` records with source traceability (issue, bug finding, review finding, user prompt).
3. Enforce valid state transitions (`can_transition`) at the persistence/service boundary.
4. Persist versioned `TaskPlanRecord` items and automatically invalidate prior approvals when a plan or `base_revision` changes materially.
5. Record immutable `TaskApprovalRecord` entries and ordered `TaskEventRecord` audit timeline events.
6. Scrub secrets (`redact` / `redact_obj`) before writing any text or JSON payload to PostgreSQL.
"""

from __future__ import annotations

import uuid
from typing import Any, Optional, Sequence

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.core.errors import APIError, ErrorCode
from app.core.secret_redaction import redact, redact_obj
from app.models.task import (
    AgentTask,
    GitHubIssue,
    TaskApprovalRecord,
    TaskEventRecord,
    TaskPlanRecord,
)
from app.schemas.plan import PlannerSchema
from app.schemas.task import TaskIntakePayload, TaskStatus, can_transition


def _to_uuid(val: uuid.UUID | str | None) -> Optional[uuid.UUID]:
    if val is None:
        return None
    if isinstance(val, uuid.UUID):
        return val
    try:
        return uuid.UUID(str(val))
    except (ValueError, TypeError):
        return None


class TaskRepository:
    """Repository managing persistence for GitHub issues, tasks, plans, approvals, and timeline events."""

    def __init__(self, session: Session) -> None:
        self.session = session

    # ------------------------------------------------------------------
    # 1. GitHub Issues (F31)
    # ------------------------------------------------------------------

    def get_issue_by_number(
        self,
        repository_id: uuid.UUID | str,
        issue_number: int,
    ) -> Optional[GitHubIssue]:
        """Find an existing GitHubIssue by `(repository_id, issue_number)`."""
        repo_uuid = _to_uuid(repository_id)
        if repo_uuid is None:
            return None
        stmt = select(GitHubIssue).where(
            GitHubIssue.repository_id == repo_uuid,
            GitHubIssue.issue_number == int(issue_number),
        )
        return self.session.execute(stmt).scalar_one_or_none()

    def upsert_github_issue(
        self,
        *,
        repository_id: uuid.UUID | str,
        issue_number: int,
        title: str,
        body: str = "",
        state: str = "open",
        labels: Sequence[str] | None = None,
        html_url: str,
        author: str | None = None,
        origin_finding_id: uuid.UUID | str | None = None,
    ) -> tuple[GitHubIssue, bool]:
        """Insert or update a GitHubIssue record. Returns `(issue, created_new)`."""
        repo_uuid = _to_uuid(repository_id)
        if repo_uuid is None:
            raise ValueError(f"Invalid repository_id: {repository_id}")

        finding_uuid = _to_uuid(origin_finding_id)
        safe_title = redact((title or "").strip()) or f"Issue #{issue_number}"
        safe_body = redact(body or "")
        safe_labels = [redact(str(lbl).strip()) for lbl in (labels or []) if str(lbl).strip()]
        safe_url = (html_url or "").strip()

        existing = self.get_issue_by_number(repo_uuid, issue_number)
        if existing is not None:
            existing.title = safe_title
            existing.body = safe_body
            existing.state = state or existing.state
            existing.labels = safe_labels
            if safe_url:
                existing.html_url = safe_url
            if author is not None:
                existing.author = author
            if finding_uuid is not None and existing.origin_finding_id is None:
                existing.origin_finding_id = finding_uuid
            self.session.commit()
            self.session.refresh(existing)
            return existing, False

        issue = GitHubIssue(
            repository_id=repo_uuid,
            issue_number=int(issue_number),
            title=safe_title,
            body=safe_body,
            state=state or "open",
            labels=safe_labels,
            html_url=safe_url,
            author=author,
            origin_finding_id=finding_uuid,
        )
        self.session.add(issue)
        self.session.commit()
        self.session.refresh(issue)
        return issue, True

    def list_issues_by_repository(
        self,
        repository_id: uuid.UUID | str,
        *,
        limit: int = 50,
        offset: int = 0,
    ) -> list[GitHubIssue]:
        """List persisted GitHub issues for a repository, ordered by issue_number desc."""
        repo_uuid = _to_uuid(repository_id)
        if repo_uuid is None:
            return []
        stmt = (
            select(GitHubIssue)
            .where(GitHubIssue.repository_id == repo_uuid)
            .order_by(GitHubIssue.issue_number.desc())
            .offset(offset)
            .limit(limit)
        )
        return list(self.session.scalars(stmt).all())

    # ------------------------------------------------------------------
    # 2. Tasks & Intake (F31, F32, F39)
    # ------------------------------------------------------------------

    def get_task_by_issue(
        self,
        repository_id: uuid.UUID | str,
        github_issue_id: uuid.UUID | str,
    ) -> Optional[AgentTask]:
        """Return an existing active task linked to `(repository_id, github_issue_id)`."""
        repo_uuid = _to_uuid(repository_id)
        issue_uuid = _to_uuid(github_issue_id)
        if repo_uuid is None or issue_uuid is None:
            return None
        stmt = (
            select(AgentTask)
            .where(
                AgentTask.repository_id == repo_uuid,
                AgentTask.github_issue_id == issue_uuid,
            )
            .order_by(AgentTask.created_at.desc())
            .options(
                selectinload(AgentTask.plans),
                selectinload(AgentTask.approvals),
                selectinload(AgentTask.events),
            )
        )
        return self.session.scalars(stmt).first()

    def create_task(
        self,
        *,
        user_id: uuid.UUID | str,
        intake: TaskIntakePayload,
        github_issue_id: uuid.UUID | str | None = None,
        origin_finding_id: uuid.UUID | str | None = None,
        initial_event_type: str = "TASK_CREATED",
        initial_event_summary: str | None = None,
    ) -> AgentTask:
        """Create a persisted AgentTask from a validated TaskIntakePayload and record its initial timeline event."""
        user_uuid = _to_uuid(user_id)
        repo_uuid = _to_uuid(intake.repository_id)
        if user_uuid is None or repo_uuid is None:
            raise ValueError("Valid user_id and repository_id are required to create a task.")

        issue_uuid = _to_uuid(github_issue_id)
        finding_uuid = _to_uuid(origin_finding_id) or _to_uuid(intake.source.finding_id)
        effective_base_rev = intake.base_revision or intake.source.base_revision

        source_dict = redact_obj(intake.source.model_dump(mode="json"))
        reqs_list = redact_obj([r.model_dump(mode="json") for r in intake.requirements])
        asms_list = redact_obj([a.model_dump(mode="json") for a in intake.assumptions])
        csts_list = redact_obj([c.model_dump(mode="json") for c in intake.constraints])

        task = AgentTask(
            repository_id=repo_uuid,
            user_id=user_uuid,
            github_issue_id=issue_uuid,
            origin_finding_id=finding_uuid,
            title=redact(intake.title),
            description=redact(intake.description),
            status=TaskStatus.CREATED.value,
            source_type=intake.source.type,
            source_ref=source_dict if isinstance(source_dict, dict) else {},
            requirements=reqs_list if isinstance(reqs_list, list) else [],
            assumptions=asms_list if isinstance(asms_list, list) else [],
            constraints=csts_list if isinstance(csts_list, list) else [],
            base_revision=effective_base_rev,
            plan_version=1,
            approved_plan_version=None,
            repair_attempts_used=0,
            repair_attempts_max=3,
        )
        self.session.add(task)
        self.session.flush()

        self._append_event(
            task_id=task.id,
            event_type=initial_event_type,
            actor_id=user_uuid,
            from_status=None,
            to_status=TaskStatus.CREATED.value,
            summary=initial_event_summary or f"Task created from {intake.source.type}: {task.title}",
            payload={
                "source_type": intake.source.type,
                "issue_number": intake.source.issue_number,
                "finding_id": intake.source.finding_id,
                "base_revision": effective_base_rev,
            },
        )
        self.session.commit()
        self.session.refresh(task)
        return task

    def get_task(self, task_id: uuid.UUID | str) -> Optional[AgentTask]:
        """Load an AgentTask with eager-loaded plans, approvals, and events."""
        t_uuid = _to_uuid(task_id)
        if t_uuid is None:
            return None
        stmt = (
            select(AgentTask)
            .where(AgentTask.id == t_uuid)
            .options(
                selectinload(AgentTask.plans),
                selectinload(AgentTask.approvals),
                selectinload(AgentTask.events),
            )
        )
        return self.session.execute(stmt).scalar_one_or_none()

    def get_task_for_user(
        self,
        task_id: uuid.UUID | str,
        user_id: uuid.UUID | str,
    ) -> Optional[AgentTask]:
        """Load an AgentTask strictly scoped to the owning user."""
        t_uuid = _to_uuid(task_id)
        u_uuid = _to_uuid(user_id)
        if t_uuid is None or u_uuid is None:
            return None
        stmt = (
            select(AgentTask)
            .where(
                AgentTask.id == t_uuid,
                AgentTask.user_id == u_uuid,
            )
            .options(
                selectinload(AgentTask.plans),
                selectinload(AgentTask.approvals),
                selectinload(AgentTask.events),
            )
        )
        return self.session.execute(stmt).scalar_one_or_none()

    def list_tasks_for_user(
        self,
        user_id: uuid.UUID | str,
        *,
        repository_id: uuid.UUID | str | None = None,
        status: str | None = None,
        offset: int = 0,
        limit: int = 20,
    ) -> tuple[list[AgentTask], int]:
        """List paginated tasks owned by `user_id`, optionally filtered by `repository_id` and `status`."""
        u_uuid = _to_uuid(user_id)
        if u_uuid is None:
            return [], 0

        stmt = select(AgentTask).where(AgentTask.user_id == u_uuid)
        if repository_id is not None:
            r_uuid = _to_uuid(repository_id)
            if r_uuid is not None:
                stmt = stmt.where(AgentTask.repository_id == r_uuid)
        if status:
            stmt = stmt.where(AgentTask.status == status.upper())

        count_stmt = select(func.count()).select_from(stmt.subquery())
        total = self.session.scalar(count_stmt) or 0

        ordered = (
            stmt.order_by(AgentTask.updated_at.desc(), AgentTask.created_at.desc())
            .offset(offset)
            .limit(limit)
            .options(selectinload(AgentTask.plans), selectinload(AgentTask.approvals))
        )
        items = list(self.session.scalars(ordered).all())
        return items, total

    # ------------------------------------------------------------------
    # 3. State Transition Enforcement (Docs/week3.md §7.2)
    # ------------------------------------------------------------------

    def transition_status(
        self,
        task: AgentTask,
        target_status: TaskStatus,
        *,
        actor_id: uuid.UUID | str | None = None,
        event_type: str | None = None,
        summary: str | None = None,
        payload: dict[str, Any] | None = None,
        commit: bool = True,
    ) -> AgentTask:
        """Validate and execute a task state transition, recording an audit event."""
        current_status = TaskStatus(task.status)
        if not can_transition(current_status, target_status):
            raise APIError(
                409,
                ErrorCode.INVALID_STATE_TRANSITION,
                f"Invalid task state transition from '{current_status.value}' to '{target_status.value}'.",
            )

        prev_val = current_status.value
        task.status = target_status.value

        self._append_event(
            task_id=task.id,
            event_type=event_type or f"STATUS_{target_status.value}",
            actor_id=_to_uuid(actor_id),
            from_status=prev_val,
            to_status=target_status.value,
            summary=summary or f"Task transitioned from {prev_val} to {target_status.value}.",
            payload=payload or {},
        )

        if commit:
            self.session.commit()
            self.session.refresh(task)
        return task

    # ------------------------------------------------------------------
    # 4. Plans & Approval Invalidation (F32, F39)
    # ------------------------------------------------------------------

    def save_plan(
        self,
        *,
        task: AgentTask,
        plan_schema: PlannerSchema,
        base_revision: str | None = None,
        actor_id: uuid.UUID | str | None = None,
    ) -> TaskPlanRecord:
        """Persist a structured implementation plan version and transition task to PENDING_APPROVAL.

        Invariants enforced (Docs/week3.md §6 F32 & §7.2):
        - First plan uses `plan_version = 1`; subsequent revisions increment `plan_version`.
        - If the task previously had an approved plan (`approved_plan_version is not None`),
          generating or saving a material plan revision or changing `base_revision` invalidates
          the prior approval (`approved_plan_version = None`) and requires renewed approval.
        - Validates that none of the plan's `expected_files` overlap with task `forbidden_files`.
        """
        # Enforce forbidden_files disjointness against task constraints
        forbidden_lower: dict[str, str] = {}
        for cst in task.constraints or []:
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

        effective_base_rev = base_revision or task.base_revision
        new_hash = plan_schema.compute_plan_hash(effective_base_rev)

        existing_plans = self.list_plans(task.id)
        latest_existing = existing_plans[0] if existing_plans else None

        # Determine next plan_version
        if latest_existing is None:
            next_version = 1
        else:
            next_version = latest_existing.plan_version + 1

        # Transition task through PLANNING -> PENDING_APPROVAL
        curr_status = TaskStatus(task.status)
        if curr_status != TaskStatus.PLANNING:
            if not can_transition(curr_status, TaskStatus.PLANNING):
                raise APIError(
                    409,
                    ErrorCode.INVALID_STATE_TRANSITION,
                    f"Cannot generate plan when task is in state '{curr_status.value}'.",
                )
            task.status = TaskStatus.PLANNING.value

        prior_approved = task.approved_plan_version
        approval_invalidated = prior_approved is not None

        # Invalidate previous approval when new plan version is created
        task.plan_version = next_version
        task.approved_plan_version = None
        if effective_base_rev:
            task.base_revision = effective_base_rev
            if isinstance(task.source_ref, dict):
                updated_ref = dict(task.source_ref)
                updated_ref["base_revision"] = effective_base_rev
                task.source_ref = updated_ref

        plan_record = TaskPlanRecord(
            task_id=task.id,
            plan_version=next_version,
            base_revision=effective_base_rev,
            plan_hash=new_hash,
            summary=redact(plan_schema.summary),
            problem_statement=redact(plan_schema.problem_statement),
            assumptions=redact_obj([a.model_dump(mode="json") for a in plan_schema.assumptions]),  # type: ignore[arg-type]
            relevant_files=list(plan_schema.relevant_files),
            relevant_symbols=list(plan_schema.relevant_symbols),
            steps=redact_obj([s.model_dump(mode="json") for s in plan_schema.steps]),  # type: ignore[arg-type]
            expected_files=list(plan_schema.expected_files),
            tests_to_run=list(plan_schema.tests_to_run),
            validation_strategy=list(plan_schema.validation_strategy),
            risks=redact_obj([r.model_dump(mode="json") for r in plan_schema.risks]),  # type: ignore[arg-type]
            required_permissions=list(plan_schema.required_permissions),
            resource_budget=plan_schema.resource_budget.model_dump(mode="json"),
            status=TaskStatus.PENDING_APPROVAL.value,
        )
        self.session.add(plan_record)

        # Mark older plan records as SUPERSEDED
        for old_p in existing_plans:
            if old_p.status in ("PENDING_APPROVAL", "APPROVED"):
                old_p.status = "SUPERSEDED"

        task.status = TaskStatus.PENDING_APPROVAL.value

        self._append_event(
            task_id=task.id,
            event_type="PLAN_GENERATED",
            actor_id=_to_uuid(actor_id),
            from_status=curr_status.value,
            to_status=TaskStatus.PENDING_APPROVAL.value,
            summary=(
                f"Generated structured implementation plan v{next_version} "
                f"({len(plan_schema.steps)} steps)."
                + (
                    f" Previous approval for v{prior_approved} invalidated."
                    if approval_invalidated
                    else ""
                )
            ),
            payload={
                "plan_version": next_version,
                "plan_hash": new_hash,
                "base_revision": effective_base_rev,
                "steps_count": len(plan_schema.steps),
                "approval_invalidated": approval_invalidated,
                "prior_approved_plan_version": prior_approved,
            },
        )

        self.session.commit()
        self.session.refresh(plan_record)
        self.session.refresh(task)
        return plan_record

    def get_latest_plan(self, task_id: uuid.UUID | str) -> Optional[TaskPlanRecord]:
        """Return the highest-versioned TaskPlanRecord for `task_id`."""
        t_uuid = _to_uuid(task_id)
        if t_uuid is None:
            return None
        stmt = (
            select(TaskPlanRecord)
            .where(TaskPlanRecord.task_id == t_uuid)
            .order_by(TaskPlanRecord.plan_version.desc())
        )
        return self.session.scalars(stmt).first()

    def get_plan_by_version(
        self,
        task_id: uuid.UUID | str,
        plan_version: int,
    ) -> Optional[TaskPlanRecord]:
        """Return a specific plan version for `task_id`."""
        t_uuid = _to_uuid(task_id)
        if t_uuid is None:
            return None
        stmt = select(TaskPlanRecord).where(
            TaskPlanRecord.task_id == t_uuid,
            TaskPlanRecord.plan_version == int(plan_version),
        )
        return self.session.execute(stmt).scalar_one_or_none()

    def list_plans(self, task_id: uuid.UUID | str) -> list[TaskPlanRecord]:
        """Return all plan versions for `task_id`, newest version first."""
        t_uuid = _to_uuid(task_id)
        if t_uuid is None:
            return []
        stmt = (
            select(TaskPlanRecord)
            .where(TaskPlanRecord.task_id == t_uuid)
            .order_by(TaskPlanRecord.plan_version.desc())
        )
        return list(self.session.scalars(stmt).all())

    # ------------------------------------------------------------------
    # 5. Human Approval & Rejection Gate (F32, Sukun Security Gate)
    # ------------------------------------------------------------------

    def approve_plan(
        self,
        *,
        task: AgentTask,
        approver_id: uuid.UUID | str,
        plan_version: int | None = None,
        base_revision: str | None = None,
        comment: str | None = None,
    ) -> TaskApprovalRecord:
        """Approve the current pending implementation plan version.

        Enforces:
        1. Task must have a generated plan and be in `PENDING_APPROVAL` (or already `APPROVED` for idempotent re-check of same version).
        2. If `plan_version` is specified, it MUST match `latest_plan.plan_version` (otherwise 409 `PLAN_VERSION_MISMATCH`).
        3. If `base_revision` is specified (or if `task.base_revision` drifted from `latest_plan.base_revision`), raises 409 `PLAN_VERSION_MISMATCH`.
        4. Records an immutable `TaskApprovalRecord(decision='APPROVED')`.
        """
        approver_uuid = _to_uuid(approver_id)
        if approver_uuid is None:
            raise APIError(401, ErrorCode.UNAUTHORIZED, "Valid approver identity is required.")

        latest_plan = self.get_latest_plan(task.id)
        if latest_plan is None:
            raise APIError(
                409,
                ErrorCode.INVALID_STATE_TRANSITION,
                "Cannot approve task before an implementation plan has been generated.",
            )

        if plan_version is not None and int(plan_version) != latest_plan.plan_version:
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

        if task.base_revision and latest_plan.base_revision and task.base_revision != latest_plan.base_revision:
            raise APIError(
                409,
                ErrorCode.PLAN_VERSION_MISMATCH,
                "Task base revision has drifted from the plan base revision. Please generate a new plan version.",
            )

        curr_status = TaskStatus(task.status)
        if curr_status == TaskStatus.REJECTED:
            raise APIError(
                409,
                ErrorCode.INVALID_STATE_TRANSITION,
                "A rejected plan cannot be approved directly. Generate a revised plan first.",
            )
        if not can_transition(curr_status, TaskStatus.APPROVED):
            raise APIError(
                409,
                ErrorCode.INVALID_STATE_TRANSITION,
                f"Task in status '{curr_status.value}' cannot transition to APPROVED.",
            )

        safe_comment = redact(comment.strip()) if comment else None

        approval = TaskApprovalRecord(
            task_id=task.id,
            plan_id=latest_plan.id,
            plan_version=latest_plan.plan_version,
            approver_id=approver_uuid,
            decision="APPROVED",
            comment=safe_comment,
            base_revision=latest_plan.base_revision,
            plan_hash=latest_plan.plan_hash,
        )
        self.session.add(approval)

        latest_plan.status = TaskStatus.APPROVED.value
        prev_status = task.status
        task.status = TaskStatus.APPROVED.value
        task.approved_plan_version = latest_plan.plan_version

        self._append_event(
            task_id=task.id,
            event_type="PLAN_APPROVED",
            actor_id=approver_uuid,
            from_status=prev_status,
            to_status=TaskStatus.APPROVED.value,
            summary=f"Plan v{latest_plan.plan_version} approved by user.",
            payload={
                "plan_version": latest_plan.plan_version,
                "plan_hash": latest_plan.plan_hash,
                "base_revision": latest_plan.base_revision,
                "comment": safe_comment,
            },
        )

        self.session.commit()
        self.session.refresh(approval)
        self.session.refresh(task)
        return approval

    def reject_plan(
        self,
        *,
        task: AgentTask,
        approver_id: uuid.UUID | str,
        plan_version: int | None = None,
        reason: str = "Plan rejected by reviewer.",
    ) -> TaskApprovalRecord:
        """Reject the current implementation plan version and block execution."""
        approver_uuid = _to_uuid(approver_id)
        if approver_uuid is None:
            raise APIError(401, ErrorCode.UNAUTHORIZED, "Valid approver identity is required.")

        latest_plan = self.get_latest_plan(task.id)
        if latest_plan is None:
            raise APIError(
                409,
                ErrorCode.INVALID_STATE_TRANSITION,
                "Cannot reject plan because no implementation plan exists for this task.",
            )

        if plan_version is not None and int(plan_version) != latest_plan.plan_version:
            raise APIError(
                409,
                ErrorCode.PLAN_VERSION_MISMATCH,
                f"Requested rejection for plan_version {plan_version}, but current plan_version is {latest_plan.plan_version}.",
            )

        curr_status = TaskStatus(task.status)
        if not can_transition(curr_status, TaskStatus.REJECTED):
            raise APIError(
                409,
                ErrorCode.INVALID_STATE_TRANSITION,
                f"Task in status '{curr_status.value}' cannot transition to REJECTED.",
            )

        safe_reason = redact((reason or "Plan rejected by reviewer.").strip())

        approval = TaskApprovalRecord(
            task_id=task.id,
            plan_id=latest_plan.id,
            plan_version=latest_plan.plan_version,
            approver_id=approver_uuid,
            decision="REJECTED",
            comment=safe_reason,
            base_revision=latest_plan.base_revision,
            plan_hash=latest_plan.plan_hash,
        )
        self.session.add(approval)

        latest_plan.status = TaskStatus.REJECTED.value
        prev_status = task.status
        task.status = TaskStatus.REJECTED.value
        task.approved_plan_version = None

        self._append_event(
            task_id=task.id,
            event_type="PLAN_REJECTED",
            actor_id=approver_uuid,
            from_status=prev_status,
            to_status=TaskStatus.REJECTED.value,
            summary=f"Plan v{latest_plan.plan_version} rejected: {safe_reason}",
            payload={
                "plan_version": latest_plan.plan_version,
                "plan_hash": latest_plan.plan_hash,
                "reason": safe_reason,
            },
        )

        self.session.commit()
        self.session.refresh(approval)
        self.session.refresh(task)
        return approval

    def verify_execution_approval_gate(self, task: AgentTask) -> TaskPlanRecord:
        """Server-enforced approval gate (Sukun W3 Day 2 — Docs/week3.md §6 F32 & §7.2).

        Blocks execution unless:
        1. `task.status` is `APPROVED` (or `WORKSPACE_SETUP` / `EXECUTING` when already started).
        2. `task.approved_plan_version` is non-null and equals `task.plan_version`.
        3. The latest `TaskPlanRecord` matches `task.approved_plan_version` and `task.base_revision`.
        4. An immutable `TaskApprovalRecord` with `decision == 'APPROVED'` exists for `(task.id, latest_plan.plan_version, latest_plan.plan_hash)`.
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
        if latest_plan is None or latest_plan.plan_version != task.approved_plan_version:
            raise APIError(
                409,
                ErrorCode.PLAN_VERSION_MISMATCH,
                "Approved plan record could not be verified against the latest task plan version.",
            )

        if task.base_revision and latest_plan.base_revision and task.base_revision != latest_plan.base_revision:
            # Base revision changed after approval -> invalidate approval and require re-approval
            task.approved_plan_version = None
            task.status = TaskStatus.PENDING_APPROVAL.value
            latest_plan.status = TaskStatus.PENDING_APPROVAL.value
            self.session.commit()
            raise APIError(
                409,
                ErrorCode.PLAN_VERSION_MISMATCH,
                "Repository base revision changed after plan approval. Previous approval has been invalidated; please re-approve.",
            )

        # Recompute structural hash of the persisted plan to detect any material modification after approval
        reconstructed = PlannerSchema.model_validate(
            {
                "summary": latest_plan.summary,
                "problem_statement": latest_plan.problem_statement,
                "assumptions": latest_plan.assumptions or [],
                "relevant_files": latest_plan.relevant_files or [],
                "relevant_symbols": latest_plan.relevant_symbols or [],
                "steps": latest_plan.steps or [],
                "expected_files": latest_plan.expected_files or [],
                "tests_to_run": latest_plan.tests_to_run or [],
                "validation_strategy": latest_plan.validation_strategy or [],
                "risks": latest_plan.risks or [],
                "required_permissions": latest_plan.required_permissions or [],
                "resource_budget": latest_plan.resource_budget or {},
            }
        )
        computed_hash = reconstructed.compute_plan_hash(latest_plan.base_revision)
        if computed_hash != latest_plan.plan_hash:
            task.approved_plan_version = None
            task.status = TaskStatus.PENDING_APPROVAL.value
            latest_plan.status = TaskStatus.PENDING_APPROVAL.value
            latest_plan.plan_hash = computed_hash
            self.session.commit()
            raise APIError(
                409,
                ErrorCode.PLAN_VERSION_MISMATCH,
                "Plan content was modified after approval. Previous approval has been invalidated; renewed approval is required.",
            )

        # Verify immutable approval decision record exists for this exact version and hash
        stmt = (
            select(TaskApprovalRecord)
            .where(
                TaskApprovalRecord.task_id == task.id,
                TaskApprovalRecord.plan_version == latest_plan.plan_version,
            )
            .order_by(TaskApprovalRecord.created_at.desc())
        )
        latest_decision = self.session.scalars(stmt).first()
        if (
            latest_decision is None
            or latest_decision.decision != "APPROVED"
            or latest_decision.plan_hash != computed_hash
        ):
            raise APIError(
                403,
                ErrorCode.APPROVAL_REQUIRED,
                "No valid matching approval record found for the current plan version and hash.",
            )

        return latest_plan

    # ------------------------------------------------------------------
    # 6. Timeline Events (F38, F39)
    # ------------------------------------------------------------------

    def list_events(self, task_id: uuid.UUID | str) -> list[TaskEventRecord]:
        """Return ordered timeline events for `task_id` (oldest to newest)."""
        t_uuid = _to_uuid(task_id)
        if t_uuid is None:
            return []
        stmt = (
            select(TaskEventRecord)
            .where(TaskEventRecord.task_id == t_uuid)
            .order_by(TaskEventRecord.created_at.asc())
        )
        return list(self.session.scalars(stmt).all())

    def list_approvals(self, task_id: uuid.UUID | str) -> list[TaskApprovalRecord]:
        """Return approval/rejection records for `task_id` (newest first)."""
        t_uuid = _to_uuid(task_id)
        if t_uuid is None:
            return []
        stmt = (
            select(TaskApprovalRecord)
            .where(TaskApprovalRecord.task_id == t_uuid)
            .order_by(TaskApprovalRecord.created_at.desc())
        )
        return list(self.session.scalars(stmt).all())

    def _append_event(
        self,
        *,
        task_id: uuid.UUID,
        event_type: str,
        actor_id: uuid.UUID | None,
        from_status: str | None,
        to_status: str | None,
        summary: str,
        payload: dict[str, Any] | None = None,
    ) -> TaskEventRecord:
        safe_summary = redact(summary)
        safe_payload = redact_obj(payload or {})
        evt = TaskEventRecord(
            task_id=task_id,
            event_type=event_type,
            actor_id=actor_id,
            from_status=from_status,
            to_status=to_status,
            summary=safe_summary,
            payload=safe_payload if isinstance(safe_payload, dict) else {},
        )
        self.session.add(evt)
        return evt


__all__ = ["TaskRepository"]
