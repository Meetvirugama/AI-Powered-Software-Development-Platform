"""Core Task lifecycle, timeline events, and GitHub issue aggregate."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, List, Optional, Sequence, Tuple

from sqlalchemy import desc, func, select
from sqlalchemy.orm import selectinload

from app.models.analysis_finding import AnalysisFinding
from app.models.task import (
    GitHubIssue,
    Task,
    TaskEvent,
    TaskEventType,
    TaskSourceType,
    TaskStatus,
)
from app.schemas.task import TaskIntakePayload
from app.repositories.task.exceptions import (
    InvalidStateTransitionError,
    TaskNotFoundError,
    TaskRepositoryBase,
    VALID_TRANSITIONS,
    _ensure_uuid,
    scrub_sensitive_data,
    scrub_sensitive_text,
)


class TaskCoreMixin(TaskRepositoryBase):
    """Task intake, status transitions, audit timeline, and GitHub issue operations."""

    def create_task(
        self,
        repository_id: uuid.UUID | str | None = None,
        title: Optional[str] = None,
        source_type: TaskSourceType | str = TaskSourceType.DIRECT,
        description: Optional[str] = None,
        source_id: Optional[str] = None,
        source_metadata: Optional[dict[str, Any]] = None,
        finding_id: Optional[uuid.UUID | str] = None,
        user_id: Optional[uuid.UUID | str] = None,
        base_revision: Optional[str] = None,
        *,
        intake: Optional[TaskIntakePayload] = None,
        github_issue_id: uuid.UUID | str | None = None,
        origin_finding_id: uuid.UUID | str | None = None,
        initial_event_type: Optional[str] = None,
        initial_event_summary: Optional[str] = None,
    ) -> Task:
        """Create and persist a new workflow task with source and finding traceability."""
        if intake is not None:
            repo_val = intake.repository_id
            title_val = intake.title
            desc_val = intake.description
            source_type_val = intake.source.type
            source_dict = scrub_sensitive_data(intake.source.model_dump(mode="json"))
            source_metadata = source_dict if isinstance(source_dict, dict) else {}
            reqs_list = scrub_sensitive_data([r.model_dump(mode="json") for r in intake.requirements])
            asms_list = scrub_sensitive_data([a.model_dump(mode="json") for a in intake.assumptions])
            csts_list = scrub_sensitive_data([c.model_dump(mode="json") for c in intake.constraints])
            base_rev_val = intake.base_revision or intake.source.base_revision or base_revision or "main"
            finding_val = origin_finding_id or intake.source.finding_id or finding_id
            issue_val = github_issue_id
            source_id_val = source_id or (str(intake.source.issue_number) if intake.source.issue_number else None)
        else:
            repo_val = repository_id
            title_val = title
            desc_val = description
            source_type_val = source_type.value if isinstance(source_type, TaskSourceType) else str(source_type)
            reqs_list = []
            asms_list = []
            csts_list = []
            base_rev_val = base_revision or "main"
            finding_val = finding_id or origin_finding_id
            issue_val = github_issue_id
            source_id_val = source_id

        repo_uuid = _ensure_uuid(repo_val)
        if not repo_uuid:
            raise ValueError("A valid repository_id is required.")

        user_uuid = _ensure_uuid(user_id)
        finding_uuid = _ensure_uuid(finding_val)
        issue_uuid = _ensure_uuid(issue_val)

        # Validate finding ownership if supplied
        if finding_uuid:
            finding = self.session.execute(
                select(AnalysisFinding).where(
                    AnalysisFinding.id == finding_uuid,
                    AnalysisFinding.repository_id == repo_uuid,
                )
            ).scalar_one_or_none()
            if not finding:
                raise ValueError("Referenced finding does not belong to this repository.")

        clean_metadata = scrub_sensitive_data(source_metadata) if source_metadata else None
        safe_title = scrub_sensitive_text((title_val or "").strip()) or "Untitled Task"
        safe_desc = scrub_sensitive_text(desc_val)

        task = Task(
            id=uuid.uuid4(),
            repository_id=repo_uuid,
            user_id=user_uuid,
            github_issue_id=issue_uuid,
            finding_id=finding_uuid,
            origin_finding_id=finding_uuid,
            title=safe_title,
            description=safe_desc,
            status=TaskStatus.CREATED.value,
            source_type=source_type_val,
            source_id=source_id_val,
            source_metadata=clean_metadata,
            source_ref=clean_metadata or {},
            requirements=reqs_list if isinstance(reqs_list, list) else [],
            assumptions=asms_list if isinstance(asms_list, list) else [],
            constraints=csts_list if isinstance(csts_list, list) else [],
            base_revision=base_rev_val,
            plan_version=1,
            approved_plan_version=None,
            repair_attempts_used=0,
            repair_attempts_max=3,
        )
        self.session.add(task)
        self.session.flush()

        evt_type = (
            initial_event_type
            or (
                TaskEventType.ISSUE_IMPORTED.value
                if source_type_val in (TaskSourceType.GITHUB_ISSUE.value, "GITHUB_ISSUE")
                else TaskEventType.TASK_CREATED.value
            )
        )
        self.record_event(
            task_id=task.id,
            repository_id=repo_uuid,
            event_type=evt_type,
            event_data={
                "title": task.title,
                "source_type": task.source_type,
                "source_id": task.source_id,
                "finding_id": str(task.finding_id) if task.finding_id else None,
                "base_revision": task.base_revision,
            },
            user_id=user_uuid,
        )

        self.session.commit()
        self.session.refresh(task)
        return task

    def get_task(
        self,
        task_id: uuid.UUID | str,
        repository_id: Optional[uuid.UUID | str] = None,
        user_id: Optional[uuid.UUID | str] = None,
    ) -> Optional[Task]:
        """Fetch task enforcing strict multi-tenant isolation when repository_id or user_id is supplied."""
        t_uuid = _ensure_uuid(task_id)
        if not t_uuid:
            return None

        stmt = select(Task).where(Task.id == t_uuid)
        if repository_id is not None:
            r_uuid = _ensure_uuid(repository_id)
            if not r_uuid:
                return None
            stmt = stmt.where(Task.repository_id == r_uuid)
        if user_id is not None:
            u_uuid = _ensure_uuid(user_id)
            if not u_uuid:
                return None
            stmt = stmt.where(Task.user_id == u_uuid)

        stmt = stmt.options(
            selectinload(Task.plans),
            selectinload(Task.approvals),
            selectinload(Task.workspace),
            selectinload(Task.repair_attempts),
            selectinload(Task.verification_results),
            selectinload(Task.pull_request),
            selectinload(Task.finding),
            selectinload(Task.events),
            selectinload(Task.executions),
        )
        return self.session.execute(stmt).scalar_one_or_none()

    def get(
        self,
        task_id: uuid.UUID | str,
        repository_id: Optional[uuid.UUID | str] = None,
        user_id: Optional[uuid.UUID | str] = None,
    ) -> Optional[Task]:
        """Fetch task by ID (alias for get_task)."""
        return self.get_task(task_id, repository_id=repository_id, user_id=user_id)

    def get_by_id(
        self,
        task_id: uuid.UUID | str,
        repository_id: Optional[uuid.UUID | str] = None,
        user_id: Optional[uuid.UUID | str] = None,
    ) -> Optional[Task]:
        """Fetch task by ID (alias for get_task)."""
        return self.get_task(task_id, repository_id=repository_id, user_id=user_id)

    def get_task_for_user(
        self,
        task_id: uuid.UUID | str,
        user_id: uuid.UUID | str,
    ) -> Optional[Task]:
        """Fetch a task verifying user ownership without eager loads."""
        t_uuid = _ensure_uuid(task_id)
        u_uuid = _ensure_uuid(user_id)
        if not t_uuid or not u_uuid:
            return None
        stmt = select(Task).where(Task.id == t_uuid, Task.user_id == u_uuid)
        return self.session.execute(stmt).scalar_one_or_none()

    def list_tasks(
        self,
        repository_id: uuid.UUID | str,
        status: Optional[str] = None,
        source_type: Optional[str] = None,
        user_id: Optional[uuid.UUID | str] = None,
        offset: int = 0,
        limit: int = 20,
    ) -> Tuple[List[Task], int]:
        """Retrieve paginated tasks for repository dashboard ordered newest-first."""
        r_uuid = _ensure_uuid(repository_id)
        if not r_uuid:
            return [], 0

        query = select(Task).where(Task.repository_id == r_uuid)
        count_query = select(func.count(Task.id)).where(Task.repository_id == r_uuid)

        if status:
            query = query.where(Task.status == status)
            count_query = count_query.where(Task.status == status)

        if source_type:
            query = query.where(Task.source_type == source_type)
            count_query = count_query.where(Task.source_type == source_type)

        u_uuid = _ensure_uuid(user_id)
        if u_uuid:
            query = query.where(Task.user_id == u_uuid)
            count_query = count_query.where(Task.user_id == u_uuid)

        total = self.session.execute(count_query).scalar_one()
        stmt = query.order_by(desc(Task.created_at)).offset(offset).limit(limit)
        results = list(self.session.execute(stmt).scalars().all())
        return results, total

    def transition_status(
        self,
        task_or_id: uuid.UUID | str | Task | None = None,
        repository_id_or_status: uuid.UUID | str | TaskStatus | None = None,
        new_status: TaskStatus | str | None = None,
        user_id: Optional[uuid.UUID | str] = None,
        reason: Optional[str] = None,
        *,
        task_id: uuid.UUID | str | Task | None = None,
        repository_id: uuid.UUID | str | None = None,
        actor_id: uuid.UUID | str | None = None,
        event_type: str | None = None,
        summary: str | None = None,
        payload: dict[str, Any] | None = None,
        commit: bool = True,
    ) -> Task:
        """Validate and execute a task state transition, recording an audit event."""
        task_or_id = task_id if task_id is not None else task_or_id
        if repository_id is not None:
            repository_id_or_status = repository_id
        if isinstance(task_or_id, Task):
            task = task_or_id
            target_status_raw = repository_id_or_status
            u_id = actor_id or user_id
        else:
            if new_status is not None:
                task_id = task_or_id
                repo_id = repository_id_or_status
                target_status_raw = new_status
                u_id = user_id or actor_id
                task = self.get_task(task_id, repo_id)
                if not task:
                    raise TaskNotFoundError(f"Task {task_id} not found in repository {repo_id}")
            else:
                task_id = task_or_id
                target_status_raw = repository_id_or_status
                u_id = user_id or actor_id
                task = self.get_task(task_id)
                if not task:
                    raise TaskNotFoundError(f"Task {task_id} not found")

        target_status_enum = TaskStatus(target_status_raw) if isinstance(target_status_raw, str) else target_status_raw
        current_status_enum = TaskStatus(task.status)

        if target_status_enum == current_status_enum:
            return task

        allowed_targets = VALID_TRANSITIONS.get(current_status_enum, set())
        if target_status_enum not in allowed_targets:
            raise InvalidStateTransitionError(
                f"Invalid state transition from {current_status_enum.value} to {target_status_enum.value}. "
                f"Permitted next states: {[s.value for s in allowed_targets]}"
            )

        # Precondition checks (§7.2)
        if target_status_enum == TaskStatus.EXECUTING:
            if not task.approved_plan_version:
                raise InvalidStateTransitionError("Cannot execute task: Plan has not been approved.")
            if not task.workspace:
                raise InvalidStateTransitionError("Cannot execute task: Workspace has not been initialized.")

        if target_status_enum == TaskStatus.REPAIRING:
            if task.repair_attempts_used >= task.repair_attempts_max:
                raise InvalidStateTransitionError("Cannot enter repair state: Retry budget is exhausted.")

        old_status = task.status
        task.status = target_status_enum.value
        task.updated_at = datetime.now(timezone.utc)
        self.session.flush()

        # Emit audit event
        safe_reason = scrub_sensitive_text(reason)
        event_dict = {
            "from_status": old_status,
            "to_status": target_status_enum.value,
        }
        if safe_reason:
            event_dict["reason"] = safe_reason
        if payload:
            event_dict.update(scrub_sensitive_data(payload))

        evt_type = event_type or TaskEventType.STATE_TRANSITIONED.value
        safe_summary = scrub_sensitive_text(summary) or f"Task transitioned from {old_status} to {target_status_enum.value}."

        self.record_event(
            task_id=task.id,
            repository_id=task.repository_id,
            event_type=evt_type,
            event_data=event_dict,
            user_id=u_id,
            from_status=old_status,
            to_status=target_status_enum.value,
            summary=safe_summary,
        )

        if commit:
            self.session.commit()
            self.session.refresh(task)
        return task

    def update_task_context(
        self,
        task_id: uuid.UUID | str,
        repository_id: uuid.UUID | str,
        context_summary: Optional[str] = None,
        base_revision: Optional[str] = None,
    ) -> Task:
        """Update task context gathered through existing intelligence services."""
        task = self.get_task(task_id, repository_id)
        if not task:
            raise TaskNotFoundError(f"Task {task_id} not found in repository {repository_id}")

        if context_summary:
            task.context_summary = scrub_sensitive_text(context_summary)
        if base_revision:
            task.base_revision = base_revision

        self.session.flush()

        self.record_event(
            task_id=task.id,
            repository_id=task.repository_id,
            event_type=TaskEventType.CHECKPOINT_SAVED.value,
            event_data={
                "action": "context_updated",
                "base_revision": task.base_revision,
            },
        )

        self.session.commit()
        self.session.refresh(task)
        return task

    def get_task_detail_for_user(
        self,
        task_id: uuid.UUID | str,
        user_id: uuid.UUID | str,
    ) -> Optional[Task]:
        """Fetch a task with eager-loaded collections verifying user ownership."""
        t_uuid = _ensure_uuid(task_id)
        u_uuid = _ensure_uuid(user_id)
        if not t_uuid or not u_uuid:
            return None

        stmt = (
            select(Task)
            .where(Task.id == t_uuid, Task.user_id == u_uuid)
            .options(
                selectinload(Task.plans),
                selectinload(Task.approvals),
                selectinload(Task.events),
                selectinload(Task.workspace),
                selectinload(Task.executions),
            )
        )
        return self.session.execute(stmt).scalar_one_or_none()

    def list_tasks_for_user(
        self,
        user_id: uuid.UUID | str,
        *,
        repository_id: uuid.UUID | str | None = None,
        status: Optional[TaskStatus | str] = None,
        limit: int = 20,
        offset: int = 0,
    ) -> tuple[list[Task], int]:
        """List tasks owned by a user with pagination and total count."""
        u_uuid = _ensure_uuid(user_id)
        if not u_uuid:
            return [], 0

        filters = [Task.user_id == u_uuid]
        if repository_id is not None:
            r_uuid = _ensure_uuid(repository_id)
            if r_uuid:
                filters.append(Task.repository_id == r_uuid)
        if status is not None:
            status_val = status.value if isinstance(status, TaskStatus) else str(status)
            filters.append(Task.status == status_val)

        count_stmt = select(func.count(Task.id)).where(*filters)
        total = self.session.scalar(count_stmt) or 0

        stmt = (
            select(Task)
            .where(*filters)
            .order_by(Task.created_at.desc())
            .offset(offset)
            .limit(limit)
            .options(
                selectinload(Task.plans),
                selectinload(Task.approvals),
                selectinload(Task.events),
            )
        )
        items = list(self.session.scalars(stmt).all())
        return items, int(total)

    @staticmethod
    def _default_event_summary(
        event_type: str,
        event_data: Optional[dict[str, Any]] = None,
        from_status: Optional[str] = None,
        to_status: Optional[str] = None,
    ) -> str:
        """Synthesize a readable timeline summary when one is not explicitly supplied."""
        data = event_data or {}
        evt = (event_type or "EVENT").upper()
        if evt == "TASK_CREATED":
            return f"Task created: {data.get('title') or 'Untitled Task'}."
        if evt == "ISSUE_IMPORTED":
            return f"Imported GitHub issue: {data.get('title') or data.get('source_id') or ''}."
        if evt == "PLAN_GENERATED":
            return f"Generated implementation plan v{data.get('plan_version', 1)} ({data.get('step_count') or data.get('steps_count') or 0} steps)."
        if evt == "PLAN_APPROVED":
            return f"Plan v{data.get('plan_version', 1)} approved for workspace execution."
        if evt == "PLAN_REJECTED":
            return f"Plan v{data.get('plan_version', 1)} rejected: {data.get('reason') or 'Requires revision'}."
        if evt == "WORKSPACE_CREATED":
            return f"Isolated workspace provisioned on branch {data.get('task_branch') or data.get('branch_name') or 'agent/task'}."
        if evt == "TOOL_INVOKED":
            return f"Executed workspace tool '{data.get('tool_name', 'unknown')}' ({data.get('status', 'COMPLETED')})."
        if evt == "TESTS_EXECUTED":
            return (
                f"Executed test suite '{data.get('command', 'pytest')}': "
                f"{data.get('status', 'COMPLETED')} ({data.get('passed', 0)} passed, {data.get('failed', 0)} failed)."
            )
        if evt == "REPAIR_ATTEMPTED":
            return (
                f"Executed bounded repair attempt {data.get('attempt_number', 1)} "
                f"(remaining budget: {data.get('remaining_budget', 0)})."
            )
        if evt == "VERIFICATION_COMPLETED":
            return f"Independent verification completed with status {data.get('status', 'PASSED')}."
        if evt == "DRAFT_PR_CREATED":
            return f"Created Draft Pull Request {data.get('pr_url') or ''}."
        if evt == "CHECKPOINT_SAVED":
            return f"Saved recovery checkpoint at step '{data.get('step_name', 'step')}'."
        if evt == "EXECUTION_FAILED":
            return f"Execution failed: {data.get('reason') or data.get('error') or 'Error during task execution'}."
        if from_status and to_status:
            return f"Task transitioned from {from_status} to {to_status}."
        return f"Recorded task event: {event_type}."

    def record_event(
        self,
        task_id: uuid.UUID | str,
        repository_id: uuid.UUID | str | None = None,
        event_type: str = "EVENT",
        event_data: Optional[dict[str, Any]] = None,
        user_id: Optional[uuid.UUID | str] = None,
        *,
        from_status: str | None = None,
        to_status: str | None = None,
        summary: str = "",
    ) -> TaskEvent:
        """Append ordered timeline audit event."""
        t_uuid = _ensure_uuid(task_id)
        u_uuid = _ensure_uuid(user_id)

        clean_event_data = scrub_sensitive_data(event_data)
        raw_summary = (summary or "").strip()
        if not raw_summary:
            raw_summary = self._default_event_summary(
                event_type=event_type,
                event_data=clean_event_data if isinstance(clean_event_data, dict) else None,
                from_status=from_status,
                to_status=to_status,
            )
        safe_summary = scrub_sensitive_text(raw_summary) or ""

        event = TaskEvent(
            id=uuid.uuid4(),
            task_id=t_uuid,
            event_type=event_type,
            event_data=clean_event_data,
            user_id=u_uuid,
            actor_id=u_uuid,
            from_status=from_status,
            to_status=to_status,
            summary=safe_summary,
        )
        self.session.add(event)
        self.session.flush()
        return event

    def get_task_timeline(
        self,
        task_id: uuid.UUID | str,
        repository_id: Optional[uuid.UUID | str] = None,
    ) -> List[TaskEvent]:
        """Fetch all audit events for a task in ascending chronological order."""
        t_uuid = _ensure_uuid(task_id)
        if not t_uuid:
            return []

        if repository_id is not None:
            r_uuid = _ensure_uuid(repository_id)
            if not r_uuid:
                return []
            stmt = (
                select(TaskEvent)
                .join(Task, Task.id == TaskEvent.task_id)
                .where(TaskEvent.task_id == t_uuid, Task.repository_id == r_uuid)
                .order_by(TaskEvent.created_at.asc())
            )
        else:
            stmt = (
                select(TaskEvent)
                .where(TaskEvent.task_id == t_uuid)
                .order_by(TaskEvent.created_at.asc())
            )
        return list(self.session.execute(stmt).scalars().all())

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
        repo_uuid = _ensure_uuid(repository_id)
        if repo_uuid is None:
            raise ValueError(f"Invalid repository_id: {repository_id}")

        finding_uuid = _ensure_uuid(origin_finding_id)
        safe_title = scrub_sensitive_text((title or "").strip()) or f"Issue #{issue_number}"
        safe_body = scrub_sensitive_text(body or "") or ""
        safe_labels = [scrub_sensitive_text(str(lbl).strip()) for lbl in (labels or []) if str(lbl).strip()]
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

    def get_issue_by_number(
        self,
        repository_id: uuid.UUID | str,
        issue_number: int,
    ) -> Optional[GitHubIssue]:
        """Find an existing GitHubIssue by `(repository_id, issue_number)`."""
        repo_uuid = _ensure_uuid(repository_id)
        if repo_uuid is None:
            return None
        stmt = select(GitHubIssue).where(
            GitHubIssue.repository_id == repo_uuid,
            GitHubIssue.issue_number == int(issue_number),
        )
        return self.session.execute(stmt).scalar_one_or_none()

    def list_issues_by_repository(
        self,
        repository_id: uuid.UUID | str,
        *,
        limit: int = 50,
        offset: int = 0,
    ) -> list[GitHubIssue]:
        """List persisted GitHub issues for a repository, ordered by issue_number desc."""
        repo_uuid = _ensure_uuid(repository_id)
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

    def get_task_by_issue(
        self,
        repository_id: uuid.UUID | str,
        github_issue_id: uuid.UUID | str,
    ) -> Optional[Task]:
        """Return an existing active task linked to `(repository_id, github_issue_id)`."""
        repo_uuid = _ensure_uuid(repository_id)
        issue_uuid = _ensure_uuid(github_issue_id)
        if repo_uuid is None or issue_uuid is None:
            return None
        stmt = (
            select(Task)
            .where(
                Task.repository_id == repo_uuid,
                Task.github_issue_id == issue_uuid,
            )
            .order_by(Task.created_at.desc())
            .options(
                selectinload(Task.plans),
                selectinload(Task.approvals),
                selectinload(Task.events),
                selectinload(Task.workspace),
                selectinload(Task.executions),
            )
        )
        return self.session.scalars(stmt).first()

    def list_events(self, task_id: uuid.UUID | str) -> list[TaskEvent]:
        """List all events for a task, ordered by created_at asc."""
        t_uuid = _ensure_uuid(task_id)
        if t_uuid is None:
            return []
        stmt = (
            select(TaskEvent)
            .where(TaskEvent.task_id == t_uuid)
            .order_by(TaskEvent.created_at.asc())
        )
        return list(self.session.scalars(stmt).all())

    def delete_event(self, event_id: uuid.UUID | str) -> None:
        """Enforce append-only audit event immutability. Deletions are strictly prohibited."""
        raise PermissionError("Audit events are immutable and cannot be deleted.")

    def update_event(self, event_id: uuid.UUID | str, *args: Any, **kwargs: Any) -> None:
        """Enforce append-only audit event immutability. Updates are strictly prohibited."""
        raise PermissionError("Audit events are immutable and cannot be modified.")
