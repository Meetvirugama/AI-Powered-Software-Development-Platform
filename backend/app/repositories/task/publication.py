"""Task publication authorization, Pull Request recording, and traceability aggregate."""

from __future__ import annotations

import uuid
from typing import Any, Optional

from sqlalchemy import select

from app.models.task import (
    Task,
    TaskEventType,
    TaskPullRequest,
    TaskStatus,
    VerificationStatus,
)
from app.repositories.task.exceptions import (
    InvalidStateTransitionError,
    TaskNotFoundError,
    _ensure_uuid,
    scrub_sensitive_text,
)

from app.repositories.task.approvals import TaskApprovalMixin
from app.repositories.task.core import TaskCoreMixin
from app.repositories.task.executions import TaskExecutionMixin
from app.repositories.task.plans import TaskPlanMixin


class TaskPublicationMixin:
    """Publication authorization gates, PR recording, and end-to-end traceability."""

    def authorize_publication(
        self,
        task_id: uuid.UUID | str,
        repository_id: uuid.UUID | str,
        head_sha: str,
        user_id: Optional[uuid.UUID | str] = None,
        notes: Optional[str] = None,
    ) -> Task:
        """Authorize branch publication and transition task from READY_FOR_PUBLICATION to PUBLISHING (Day 5)."""
        task = self.get_task(task_id, repository_id)
        if not task:
            raise TaskNotFoundError(f"Task {task_id} not found in repository {repository_id}")

        if task.status != TaskStatus.READY_FOR_PUBLICATION.value:
            raise InvalidStateTransitionError(
                f"Task {task.id} is in status '{task.status}', but publication authorization requires READY_FOR_PUBLICATION."
            )

        latest_ver = self.get_latest_verification_result(task_id, repository_id)
        if not latest_ver:
            raise InvalidStateTransitionError(
                f"Task {task.id} cannot be authorized for publication without passing verification."
            )

        if latest_ver.verified_revision != head_sha:
            raise InvalidStateTransitionError(
                f"Authorized revision '{head_sha}' does not match latest verified revision '{latest_ver.verified_revision}'."
            )

        has_blocking = bool(latest_ver.blocking_findings and len(latest_ver.blocking_findings) > 0)
        if latest_ver.status not in {VerificationStatus.PASSED.value, "PASS"} or has_blocking:
            raise InvalidStateTransitionError(
                f"Cannot authorize publication: verification status is '{latest_ver.status}' with {len(latest_ver.blocking_findings or [])} blocking findings."
            )

        task.status = TaskStatus.PUBLISHING.value
        self.session.flush()

        self.record_event(
            task_id=task.id,
            repository_id=task.repository_id,
            event_type=TaskEventType.PUBLICATION_AUTHORIZED.value,
            event_data={
                "authorized_head_sha": head_sha,
                "notes": scrub_sensitive_text(notes),
                "verified_revision": latest_ver.verified_revision,
            },
            user_id=user_id,
        )
        self.session.commit()
        self.session.refresh(task)
        return task

    def record_pull_request(
        self,
        task_id: uuid.UUID | str,
        repository_id: uuid.UUID | str,
        pr_url: str,
        base_branch: str,
        head_branch: str,
        head_sha: str,
        title: str,
        body: Optional[str] = None,
        pr_number: Optional[int] = None,
        github_pr_id: Optional[int] = None,
        is_draft: bool = True,
    ) -> TaskPullRequest:
        """Record published Draft PR and advance task to DRAFT_PR_CREATED (Day 5)."""
        task = self.get_task(task_id, repository_id)
        if not task:
            raise TaskNotFoundError(f"Task {task_id} not found in repository {repository_id}")

        if task.status not in {TaskStatus.PUBLISHING.value, TaskStatus.READY_FOR_PUBLICATION.value, TaskStatus.DRAFT_PR_CREATED.value}:
            raise InvalidStateTransitionError(
                f"Cannot record Pull Request for task in status '{task.status}'. Publication authorization is required."
            )

        existing_pr = self.session.execute(
            select(TaskPullRequest).where(TaskPullRequest.task_id == task.id)
        ).scalar_one_or_none()

        if existing_pr:
            existing_pr.pr_url = pr_url
            existing_pr.pr_number = pr_number or existing_pr.pr_number
            existing_pr.base_branch = base_branch
            existing_pr.head_branch = head_branch
            existing_pr.head_sha = head_sha
            existing_pr.title = scrub_sensitive_text(title.strip())
            existing_pr.body = scrub_sensitive_text(body)
            existing_pr.is_draft = is_draft
            pr = existing_pr
        else:
            pr = TaskPullRequest(
                id=uuid.uuid4(),
                task_id=task.id,
                repository_id=task.repository_id,
                github_pr_id=github_pr_id,
                pr_number=pr_number,
                pr_url=pr_url,
                base_branch=base_branch,
                head_branch=head_branch,
                head_sha=head_sha,
                is_draft=is_draft,
                title=scrub_sensitive_text(title.strip()),
                body=scrub_sensitive_text(body),
            )
            self.session.add(pr)

        task.status = TaskStatus.DRAFT_PR_CREATED.value
        self.session.flush()

        self.record_event(
            task_id=task.id,
            repository_id=task.repository_id,
            event_type=TaskEventType.DRAFT_PR_CREATED.value,
            event_data={
                "pr_url": pr_url,
                "pr_number": pr_number,
                "base_branch": base_branch,
                "head_branch": head_branch,
                "head_sha": head_sha,
            },
        )
        self.session.commit()
        self.session.refresh(pr)
        return pr

    def get_pull_request(
        self,
        task_id: uuid.UUID | str,
        repository_id: Optional[uuid.UUID | str] = None,
    ) -> Optional[TaskPullRequest]:
        """Fetch recorded Pull Request for an authorized task (Day 5)."""
        if repository_id is not None:
            task = self.get_task(task_id, repository_id)
            if not task:
                raise TaskNotFoundError(f"Task {task_id} not found in repository {repository_id}")
            t_uuid = task.id
        else:
            t_uuid = _ensure_uuid(task_id)
            if t_uuid is None:
                return None

        stmt = select(TaskPullRequest).where(TaskPullRequest.task_id == t_uuid)
        return self.session.execute(stmt).scalar_one_or_none()

    def get_task_traceability(
        self,
        task_id: uuid.UUID | str,
        repository_id: uuid.UUID | str,
    ) -> dict[str, Any]:
        """Return complete end-to-end traceability linking finding -> issue -> task -> plan -> workspace -> execution -> tests -> repair -> verification -> Draft PR (Day 5)."""
        task = self.get_task(task_id, repository_id)
        if not task:
            raise TaskNotFoundError(f"Task {task_id} not found in repository {repository_id}")

        latest_plan = self.get_plan(task.id, repository_id, version=None)
        latest_approval = (
            self.get_approval(task.id, repository_id, plan_version=latest_plan.version)
            if latest_plan
            else self.get_approval(task.id, repository_id)
        )
        workspace = self.get_workspace(task.id, repository_id)
        executions = self.get_executions(task.id, repository_id)
        latest_execution = executions[-1] if executions else None
        latest_test = self.get_latest_test_run(task.id, repository_id)
        repairs = self.get_repair_attempts(task.id, repository_id)
        latest_repair = repairs[-1] if repairs else None
        latest_ver = self.get_latest_verification_result(task.id, repository_id)
        pr = self.get_pull_request(task.id, repository_id)
        timeline = self.get_task_timeline(task.id, repository_id)

        finding_data = None
        if task.finding:
            finding_data = {
                "finding_id": str(task.finding.id),
                "title": task.finding.title,
                "category": task.finding.category,
                "severity": task.finding.severity,
                "file_path": task.finding.file_path,
                "start_line": task.finding.start_line,
                "end_line": task.finding.end_line,
                "source_reference": task.finding.source_reference,
            }

        tools = self.get_tool_invocations(task.id, repository_id)
        test_runs = self.get_test_runs(task.id, repository_id)

        status_str = "IN_PROGRESS"
        if task.status == TaskStatus.DRAFT_PR_CREATED.value:
            status_str = "COMPLETE"
        elif task.status in {TaskStatus.FAILED.value, TaskStatus.BLOCKED.value, TaskStatus.REJECTED.value}:
            status_str = task.status
        elif task.status in {TaskStatus.READY_FOR_PUBLICATION.value, TaskStatus.PUBLISHING.value}:
            status_str = "READY_FOR_PR"

        is_complete = bool(
            pr
            and task.status == TaskStatus.DRAFT_PR_CREATED.value
            and latest_ver
            and latest_ver.status == VerificationStatus.PASSED.value
            and task.approved_plan_version
        )

        return {
            "task": task.to_dict(),
            "finding": finding_data,
            "latest_plan": latest_plan.to_dict() if latest_plan else None,
            "latest_approval": latest_approval.to_dict() if latest_approval else None,
            "workspace": workspace.to_dict() if workspace else None,
            "latest_execution": latest_execution.to_dict() if latest_execution else None,
            "latest_test_run": latest_test.to_dict() if latest_test else None,
            "repair_attempts_used": task.repair_attempts_used,
            "latest_repair": latest_repair.to_dict() if latest_repair else None,
            "latest_verification": latest_ver.to_dict() if latest_ver else None,
            "pull_request": pr.to_dict() if pr else None,
            "timeline": [ev.to_dict() for ev in timeline],
            "tool_invocations": [t.to_dict() for t in tools],
            "test_runs": [tr.to_dict() for tr in test_runs],
            "repair_attempts": [ra.to_dict() for ra in repairs],
            "traceability_status": status_str,
            "is_complete_workflow": is_complete,
        }


class TaskPublicationRepository(TaskPublicationMixin, TaskExecutionMixin, TaskApprovalMixin, TaskPlanMixin, TaskCoreMixin):
    """Standalone domain aggregate for task publication and PR traceability."""
