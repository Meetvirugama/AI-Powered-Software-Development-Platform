"""Incremental Pull Request Review Service (PR-Agent pattern adaptation).

Handles PR 'synchronize' events when new commits are pushed:
- Compares previous reviewed commit SHA against the new HEAD commit SHA.
- Determines the set of changed files and hunks introduced by the new commits.
- Re-reviews modified files and affected context.
- Tracks finding resolution (FIXED) and preservation (ACTIVE/REOPENED).
- Publishes comments ONLY for new or updated findings to prevent repetitive spam.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import logging
from typing import Any, Optional
from uuid import UUID

from app.schemas.analysis import CodeReviewRequest, ReviewFinding, ReviewReportResponse
from app.services.review_lifecycle_service import ReviewLifecycleService
from app.services.review_publication_service import ReviewPublicationResult, ReviewPublicationService

logger = logging.getLogger(__name__)


@dataclass
class IncrementalReviewResult:
    """Outcome of an incremental pull request review."""

    is_incremental: bool
    previous_commit_sha: Optional[str]
    new_commit_sha: str
    modified_files_count: int
    new_findings_count: int
    resolved_findings_count: int
    publication_result: Optional[ReviewPublicationResult] = None
    new_findings: list[dict[str, Any]] = field(default_factory=list)
    resolved_findings: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "is_incremental": self.is_incremental,
            "previous_commit_sha": self.previous_commit_sha,
            "new_commit_sha": self.new_commit_sha,
            "modified_files_count": self.modified_files_count,
            "new_findings_count": self.new_findings_count,
            "resolved_findings_count": self.resolved_findings_count,
            "publication": self.publication_result.to_dict() if self.publication_result else None,
        }


class IncrementalReviewService:
    """Orchestrates delta reviews on pull request synchronize events."""

    __test__ = False

    def __init__(
        self,
        lifecycle_service: Optional[ReviewLifecycleService] = None,
        publication_service: Optional[ReviewPublicationService] = None,
    ) -> None:
        self.lifecycle_service = lifecycle_service or ReviewLifecycleService()
        self.publication_service = publication_service or ReviewPublicationService()

    async def execute_incremental_review(
        self,
        *,
        repository: Any,
        pr_number: int,
        new_commit_sha: str,
        previous_commit_sha: Optional[str],
        previous_findings: list[dict[str, Any]],
        current_findings: list[dict[str, Any]],
        github_service: Any,
        installation_id: Any = None,
        custom_summary: Optional[str] = None,
        is_complete_review: bool = True,
    ) -> IncrementalReviewResult:
        """Run delta comparison and publish review comments for new findings only."""
        is_incremental = bool(previous_commit_sha and previous_commit_sha != new_commit_sha)

        # 1. Update lifecycle across commits
        updated_current, resolved_findings = self.lifecycle_service.track_findings_across_commits(
            current_findings=current_findings,
            previous_findings=previous_findings if is_incremental else [],
            current_commit_sha=new_commit_sha,
            is_complete_review=is_complete_review,
        )

        # 2. Filter publishable findings: on incremental runs, prioritize NEW or REOPENED findings
        if is_incremental:
            new_publish_candidates = [
                f for f in updated_current
                if (f.get("finding_metadata", {}).get("lifecycle", {}).get("status") in ("NEW", "REOPENED"))
            ]
        else:
            new_publish_candidates = updated_current

        # 3. Publish via ReviewPublicationService
        pub_summary = custom_summary
        if is_incremental:
            prefix = (
                f"### 🔄 Incremental Review (Commits `{previous_commit_sha[:8]}` → `{new_commit_sha[:8]}`)\n"
                f"- **New Issues Detected:** {len(new_publish_candidates)}\n"
                f"- **Previously Detected Issues Resolved:** {len(resolved_findings)}\n\n"
            )
            pub_summary = prefix + (custom_summary or "")

        pub_result = await self.publication_service.publish_pull_request_review(
            owner=repository.owner,
            repo_name=repository.name,
            pr_number=pr_number,
            commit_sha=new_commit_sha,
            findings=new_publish_candidates,
            github_service=github_service,
            repository=repository,
            installation_id=installation_id,
            custom_summary=pub_summary,
        )

        logger.info(
            "incremental_review_completed",
            extra={
                "pr": pr_number,
                "is_incremental": is_incremental,
                "new_count": len(new_publish_candidates),
                "resolved_count": len(resolved_findings),
            },
        )

        return IncrementalReviewResult(
            is_incremental=is_incremental,
            previous_commit_sha=previous_commit_sha,
            new_commit_sha=new_commit_sha,
            modified_files_count=len(set(f.get("file_path") for f in updated_current if f.get("file_path"))),
            new_findings_count=len(new_publish_candidates),
            resolved_findings_count=len(resolved_findings),
            publication_result=pub_result,
            new_findings=new_publish_candidates,
            resolved_findings=resolved_findings,
        )
