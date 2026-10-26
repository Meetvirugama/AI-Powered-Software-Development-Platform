import uuid
from typing import List, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.pull_request import PullRequest


class PullRequestRepository:
    """Repository layer for the pull_requests table.

    Rule: Parth is the sole writer for pull_requests (team_rules.md:500).
    """

    def __init__(self, session: Session):
        self.session = session

    def create_or_update(
        self,
        task_id: uuid.UUID,
        repository_id: uuid.UUID,
        branch: str,
        base_branch: str,
        changed_files: list[str],
        commit_message: str,
        test_summary: str,
        verification_summary: str,
        status: str = "prepared",
        pr_number: Optional[int] = None,
        pr_url: Optional[str] = None,
    ) -> PullRequest:
        """Create or update PR metadata for a specific task."""
        stmt = select(PullRequest).where(PullRequest.task_id == task_id)
        pr = self.session.execute(stmt).scalar_one_or_none()

        if pr is None:
            pr = PullRequest(
                task_id=task_id,
                repository_id=repository_id,
                branch=branch,
                base_branch=base_branch,
                changed_files=changed_files,
                commit_message=commit_message,
                test_summary=test_summary,
                verification_summary=verification_summary,
                status=status,
                pr_number=pr_number,
                pr_url=pr_url,
            )
            self.session.add(pr)
        else:
            pr.repository_id = repository_id
            pr.branch = branch
            pr.base_branch = base_branch
            pr.changed_files = changed_files
            pr.commit_message = commit_message
            pr.test_summary = test_summary
            pr.verification_summary = verification_summary
            pr.status = status
            if pr_number is not None:
                pr.pr_number = pr_number
            if pr_url is not None:
                pr.pr_url = pr_url

        self.session.commit()
        self.session.refresh(pr)
        return pr

    def get_by_task_id(self, task_id: uuid.UUID) -> Optional[PullRequest]:
        """Fetch PR metadata record by task_id."""
        stmt = select(PullRequest).where(PullRequest.task_id == task_id)
        return self.session.execute(stmt).scalar_one_or_none()

    def list_by_repository(self, repository_id: uuid.UUID) -> List[PullRequest]:
        """List all PR metadata records for a given repository."""
        stmt = select(PullRequest).where(PullRequest.repository_id == repository_id).order_by(PullRequest.created_at.desc())
        return list(self.session.scalars(stmt).all())

    def update_status(
        self,
        task_id: uuid.UUID,
        status: str,
        pr_number: Optional[int] = None,
        pr_url: Optional[str] = None,
    ) -> Optional[PullRequest]:
        """Update lifecycle status and PR URL/number when PR is created or transitioned."""
        pr = self.get_by_task_id(task_id)
        if pr is not None:
            pr.status = status
            if pr_number is not None:
                pr.pr_number = pr_number
            if pr_url is not None:
                pr.pr_url = pr_url
            self.session.commit()
            self.session.refresh(pr)
        return pr

    def delete_by_task_id(self, task_id: uuid.UUID) -> bool:
        """Delete PR metadata for a cancelled task."""
        pr = self.get_by_task_id(task_id)
        if pr is not None:
            self.session.delete(pr)
            self.session.commit()
            return True
        return False
