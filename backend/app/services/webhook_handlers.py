"""Webhook event handlers for durable GitHub App event processing.

Implements handlers for:
- PushEventHandler: Automatic incremental repository sync on default branch push.
- InstallationEventHandler: GitHub App installation lifecycle (created, deleted).
- InstallationRepositoriesEventHandler: Repository access reconciliation (added, removed).
- PullRequestEventHandler: Opt-in automated AI and static PR code review.
- IssuesEventHandler: Read-only idempotent GitHub issue ingestion and synchronization.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Protocol

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.core.redis import get_redis_async
from app.models.github_installation import GitHubInstallation
from app.models.repository import Repository, SyncStatus
from app.models.sync_job import SyncJob, SyncJobStatus
from app.models.task import GitHubIssue
from app.models.webhook_event import GitHubWebhookEvent
from app.repositories.github_installation_repository import GitHubInstallationRepository
from app.repositories.user_repository import UserRepository

logger = logging.getLogger(__name__)


class WebhookHandlerError(Exception):
    """Base exception for webhook handler errors."""


class RetryableWebhookError(WebhookHandlerError):
    """Transient webhook handler error that should be retried with exponential backoff."""


class FatalWebhookError(WebhookHandlerError):
    """Non-retryable webhook error that immediately transitions event to DEAD_LETTER."""


class EventHandlerProtocol(Protocol):
    async def handle(
        self,
        event: GitHubWebhookEvent,
        db: Session,
        github_service: Any = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Process an event payload durably."""
        ...


class PushEventHandler:
    """Handle GitHub `push` webhook events.
    
    Automates repository indexing when commits are pushed to the default branch.
    Skips non-default branches, deleted branches, disabled auto-sync, and redundant commit SHAs.
    Retries with backoff if a sync job is already in progress.
    """

    async def handle(
        self,
        event: GitHubWebhookEvent,
        db: Session,
        github_service: Any = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        payload = event.payload or {}
        repo_payload = payload.get("repository", {})
        gh_repo_id = str(repo_payload.get("id", ""))

        if not gh_repo_id:
            return {"status": "ignored_missing_repo_id"}

        repo = db.scalar(
            select(Repository).where(Repository.github_repo_id == gh_repo_id)
        )
        if not repo:
            logger.info("webhook_push_unknown_repository", extra={"github_repo_id": gh_repo_id})
            return {"status": "ignored_unknown_repository", "github_repo_id": gh_repo_id}

        if not event.repository_id:
            event.repository_id = repo.id
            db.commit()

        # Branch verification: Only sync configured default branch (or 'main'/'master' fallback)
        ref = payload.get("ref", "")
        default_branch = repo.default_branch or "main"
        expected_ref = f"refs/heads/{default_branch}"

        if ref != expected_ref:
            logger.debug(
                "webhook_push_ignored_non_default_branch",
                extra={"ref": ref, "expected": expected_ref, "repo_id": str(repo.id)},
            )
            return {"status": "ignored_non_default_branch", "ref": ref, "expected": expected_ref}

        # Skip deleted branch
        if payload.get("deleted") is True or payload.get("after") == "0000000000000000000000000000000000000000":
            return {"status": "ignored_deleted_branch"}

        # Respect repository auto_sync_enabled flag
        if not repo.auto_sync_enabled:
            logger.info("webhook_push_auto_sync_disabled", extra={"repo_id": str(repo.id)})
            return {"status": "ignored_auto_sync_disabled", "repo_id": str(repo.id)}

        # Skip redundant commit SHA if already indexed
        after_sha = payload.get("after")
        if after_sha and repo.last_indexed_commit_sha == after_sha:
            logger.info(
                "webhook_push_already_indexed",
                extra={"repo_id": str(repo.id), "sha": after_sha},
            )
            return {"status": "ignored_already_indexed", "sha": after_sha}

        # Reconcile against current branch HEAD to prevent older out-of-order events from overwriting newer indexed state
        if github_service and hasattr(github_service, "get_branch"):
            try:
                branch_info = await github_service.get_branch(
                    owner=repo.owner,
                    repo=repo.name,
                    branch=default_branch,
                    installation_id=repo.installation_id,
                )
                current_head = (branch_info or {}).get("commit", {}).get("sha")
                if current_head and current_head != after_sha and repo.last_indexed_commit_sha == current_head:
                    logger.info("push_ignored_stale_commit", extra={"sha": after_sha, "current_head": current_head})
                    return {"status": "ignored_stale_commit", "sha": after_sha, "current_head": current_head}
            except RetryableWebhookError:
                raise
            except Exception as branch_exc:
                err_text = str(branch_exc).lower()
                if "rate limit" in err_text or "timeout" in err_text or "50" in err_text:
                    raise RetryableWebhookError(f"GitHub API transient error: {branch_exc}") from branch_exc

        # Concurrency check: If repository is currently syncing, retry later with exponential backoff
        if repo.sync_status == SyncStatus.SYNCING:
            raise RetryableWebhookError(
                f"Repository {repo.id} is currently syncing. Deferring push event for commit {after_sha}."
            )

        # Trigger incremental sync execution
        from app.services.sync_worker import process_sync_job

        job = SyncJob(
            id=uuid.uuid4(),
            repository_id=repo.id,
            user_id=repo.user_id,
            status=SyncJobStatus.QUEUED,
        )
        db.add(job)
        repo.sync_status = SyncStatus.SYNCING
        db.commit()

        try:
            await process_sync_job(
                job_id=job.id,
                repository_id=repo.id,
                user_id=repo.user_id,
                github_service=github_service,
            )
        except Exception as exc:
            logger.error("webhook_push_sync_failed", extra={"repo_id": str(repo.id), "error": str(exc)})
            repo.sync_status = SyncStatus.FAILED
            db.commit()
            raise RetryableWebhookError(f"Incremental sync execution failed: {exc}") from exc

        # Update last indexed commit SHA on success
        repo = db.get(Repository, repo.id)
        if repo:
            if after_sha:
                repo.last_indexed_commit_sha = after_sha
            repo.sync_status = SyncStatus.SYNCED
            repo.last_synced_at = datetime.now(timezone.utc)
            db.commit()

        logger.info(
            "webhook_push_sync_completed",
            extra={"repo_id": str(repo.id), "commit_sha": after_sha, "job_id": str(job.id)},
        )
        return {"status": "push_synced", "commit_sha": after_sha, "job_id": str(job.id)}


class InstallationEventHandler:
    """Handle GitHub App `installation` lifecycle events (created, deleted, suspend, unsuspend)."""

    async def handle(
        self,
        event: GitHubWebhookEvent,
        db: Session,
        github_service: Any = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        payload = event.payload or {}
        action = event.action or payload.get("action", "")
        installation_data = payload.get("installation", {})
        inst_id = str(installation_data.get("id", ""))
        account_login = installation_data.get("account", {}).get("login", "")

        if not inst_id:
            return {"status": "ignored_missing_installation_id"}

        inst_repo = GitHubInstallationRepository(db)

        if action in ("created", "added", "unsuspend"):
            user = UserRepository(db).get_by_login(account_login)
            if user:
                inst_repo.upsert(
                    user_id=user.id,
                    installation_id=inst_id,
                    account_login=account_login,
                    permissions=installation_data.get("permissions", {}),
                )
                db.commit()
                logger.info(
                    "webhook_installation_upserted",
                    extra={"installation_id": inst_id, "user_id": str(user.id), "login": account_login},
                )
                return {"status": "installation_created", "installation_id": inst_id, "user_id": str(user.id)}
            else:
                logger.warning(
                    "webhook_installation_user_not_found",
                    extra={"installation_id": inst_id, "login": account_login},
                )
                return {"status": "installation_user_not_found", "login": account_login}

        elif action in ("deleted", "removed", "suspend"):
            installation = inst_repo.get_by_installation_id(inst_id)
            if installation:
                # Mark associated repositories as disconnected/failed & cancel active sync jobs
                repos = db.scalars(
                    select(Repository).where(Repository.installation_id == installation.id)
                ).all()
                for r in repos:
                    r.sync_status = SyncStatus.FAILED
                    db.execute(
                        update(SyncJob)
                        .where(
                            SyncJob.repository_id == r.id,
                            SyncJob.status.in_([SyncJobStatus.QUEUED, SyncJobStatus.RUNNING]),
                        )
                        .values(status=SyncJobStatus.FAILED)
                    )

                # Revoke permissions while preserving historical user tasks, analysis, and files
                installation.permissions = {
                    "revoked": True,
                    "revoked_at": datetime.now(timezone.utc).isoformat(),
                    "action": action,
                }
                db.commit()
                logger.info(
                    "webhook_installation_revoked",
                    extra={"installation_id": inst_id, "repos_affected": len(repos)},
                )
                return {"status": "installation_revoked", "installation_id": inst_id, "repos_affected": len(repos)}

            return {"status": "ignored_unknown_installation", "installation_id": inst_id}

        return {"status": "ignored_unhandled_action", "action": action}


class InstallationRepositoriesEventHandler:
    """Handle `installation_repositories` events (repositories added or removed from GitHub App)."""

    async def handle(
        self,
        event: GitHubWebhookEvent,
        db: Session,
        github_service: Any = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        payload = event.payload or {}
        action = event.action or payload.get("action", "")
        installation_data = payload.get("installation", {})
        inst_id = str(installation_data.get("id", ""))

        if not inst_id:
            return {"status": "ignored_missing_installation_id"}

        inst_repo = GitHubInstallationRepository(db)
        installation = inst_repo.get_by_installation_id(inst_id)
        if not installation:
            logger.info("webhook_installation_repos_unknown_inst", extra={"installation_id": inst_id})
            return {"status": "ignored_unknown_installation", "installation_id": inst_id}

        if action == "added":
            repos_added = payload.get("repositories_added", [])
            added_count = 0
            for r_data in repos_added:
                gh_repo_id = str(r_data.get("id"))
                name = r_data.get("name", "")
                full_name = r_data.get("full_name", "")
                owner = full_name.split("/")[0] if "/" in full_name else installation.account_login
                default_branch = r_data.get("default_branch", "main")

                existing = db.scalar(
                    select(Repository).where(
                        Repository.github_repo_id == gh_repo_id,
                        Repository.installation_id == installation.id,
                    )
                )
                if not existing:
                    new_repo = Repository(
                        id=uuid.uuid4(),
                        user_id=installation.user_id,
                        installation_id=installation.id,
                        github_repo_id=gh_repo_id,
                        owner=owner,
                        name=name,
                        default_branch=default_branch,
                        sync_status=SyncStatus.NOT_SYNCED,
                        auto_sync_enabled=True,
                        pr_review_enabled=False,
                        pr_review_drafts=False,
                    )
                    db.add(new_repo)
                    added_count += 1

            db.commit()
            logger.info(
                "webhook_installation_repositories_added",
                extra={"installation_id": inst_id, "added_count": added_count},
            )
            return {"status": "repositories_added", "added_count": added_count}

        elif action == "removed":
            repos_removed = payload.get("repositories_removed", [])
            removed_count = 0
            for r_data in repos_removed:
                gh_repo_id = str(r_data.get("id"))
                repo = db.scalar(
                    select(Repository).where(
                        Repository.github_repo_id == gh_repo_id,
                        Repository.installation_id == installation.id,
                    )
                )
                if repo:
                    # Mark disconnected and cancel active sync jobs
                    repo.sync_status = SyncStatus.FAILED
                    db.execute(
                        update(SyncJob)
                        .where(
                            SyncJob.repository_id == repo.id,
                            SyncJob.status.in_([SyncJobStatus.QUEUED, SyncJobStatus.RUNNING]),
                        )
                        .values(status=SyncJobStatus.FAILED)
                    )
                    removed_count += 1

            db.commit()
            logger.info(
                "webhook_installation_repositories_removed",
                extra={"installation_id": inst_id, "removed_count": removed_count},
            )
            return {"status": "repositories_removed", "removed_count": removed_count}

        return {"status": "ignored_unhandled_action", "action": action}


class PullRequestEventHandler:
    """Handle `pull_request` webhook events for opt-in automated AI & static code review.
    
    Triggered on `opened`, `synchronize`, `reopened`, and `ready_for_review`.
    Verifies that PR review is enabled for the repository and checks draft PR policies.
    Guarantees that reviews are abandoned if the head commit SHA has changed.
    Strictly publishes comments with `event="COMMENT"` and never auto-approves or merges.
    """

    SUPPORTED_ACTIONS = {
        "opened",
        "synchronize",
        "reopened",
        "ready_for_review",
        "closed",
        "converted_to_draft",
    }

    @staticmethod
    def _format_consolidated_review(report: Any, head_sha: str, pr_number: int) -> str:
        """Format consolidated review markdown without inventing inline positions for unmappable findings."""
        risk_level = getattr(report, "risk_level", "NONE") if report else "NONE"
        findings = getattr(report, "findings", []) if report else []
        total_findings = getattr(report, "total_findings", len(findings)) if report else 0
        summary = getattr(report, "summary", "Review completed successfully.") if report else "Automated analysis completed."

        lines = [
            f"## 🤖 Automated Code Review (SHA: `{head_sha[:8]}`)",
            "",
            f"- **Target:** Pull Request #{pr_number}",
            f"- **Overall Risk Level:** `{risk_level}`",
            f"- **Total Findings:** {total_findings}",
            "",
            "### Summary",
            summary,
            "",
        ]

        mappable_findings = []
        unmappable_findings = []
        for f in findings:
            file_path = getattr(f, "file_path", None)
            start_line = getattr(f, "start_line", None)
            if file_path and start_line is not None:
                mappable_findings.append(f)
            else:
                unmappable_findings.append(f)

        if mappable_findings:
            lines.append("### Findings Breakdown")
            lines.append("| Category | Severity | File | Lines | Description |")
            lines.append("|---|---|---|---|---|")
            for f in mappable_findings:
                cat = getattr(f, "category", "general")
                sev = getattr(f, "severity", "medium")
                path = getattr(f, "file_path", "")
                start = getattr(f, "start_line", "")
                end = getattr(f, "end_line", start)
                loc = f"L{start}-L{end}" if end and end != start else f"L{start}"
                desc = (getattr(f, "title", "") or getattr(f, "description", "")).replace("\n", " ")[:120]
                lines.append(f"| {cat} | {sev} | `{path}` | {loc} | {desc} |")
            lines.append("")

        if unmappable_findings:
            lines.append("### Unmappable & Structural Findings")
            for f in unmappable_findings:
                cat = getattr(f, "category", "general")
                sev = getattr(f, "severity", "medium")
                desc = getattr(f, "description", "") or getattr(f, "title", "")
                lines.append(f"- **[{cat.upper()}] [{sev.upper()}]**: {desc}")
            lines.append("")

        lines.append("> *Note: Automated review generated by AI-Powered Software Development Platform.*")
        lines.append("> *Never automatically approved or merged. Review posted as a COMMENT.*")
        return "\n".join(lines)

    async def handle(
        self,
        event: GitHubWebhookEvent,
        db: Session,
        github_service: Any = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        payload = event.payload or {}
        action = event.action or payload.get("action", "")

        if action not in self.SUPPORTED_ACTIONS:
            return {"status": "ignored_pr_action", "action": action}

        # Terminal / passive actions
        if action == "closed":
            return {"status": "skipped", "reason": "pr_closed"}
        if action == "converted_to_draft":
            return {"status": "skipped", "reason": "pr_converted_to_draft"}

        repo_payload = payload.get("repository", {})
        gh_repo_id = str(repo_payload.get("id", ""))
        repo = db.scalar(
            select(Repository).where(Repository.github_repo_id == gh_repo_id)
        )
        if not repo:
            return {"status": "ignored_unknown_repository", "github_repo_id": gh_repo_id}

        if not event.repository_id:
            event.repository_id = repo.id
            db.commit()

        # Check repository opt-in configuration
        if not repo.pr_review_enabled:
            return {"status": "ignored_pr_review_disabled", "repo_id": str(repo.id)}

        pr_data = payload.get("pull_request", {})
        pr_number = pr_data.get("number")
        is_draft = bool(pr_data.get("draft", False))

        # Check draft PR policy
        if is_draft and not repo.pr_review_drafts:
            return {"status": "ignored_draft_pr", "pr_number": pr_number}

        head_sha = pr_data.get("head", {}).get("sha", "")
        if not head_sha or not pr_number:
            return {"status": "ignored_missing_pr_metadata"}

        # In-flight deduplication per (repo, pr_number, head_sha)
        dedup_key = f"pr_review_dedup:{repo.id}:{pr_number}:{head_sha}"
        try:
            redis = await get_redis_async()
            was_set = await redis.set(dedup_key, "1", ex=3600, nx=True)
            if not was_set:
                return {"status": "ignored_duplicate_pr_review", "head_sha": head_sha}
        except Exception as redis_exc:
            logger.warning("pr_review_dedup_redis_failed", extra={"error": str(redis_exc)})

        # Pre-publish verification: Check if PR is still open and current head matches reviewed head
        if github_service:
            try:
                pr_detail = await github_service.get_pull_request_detail(
                    owner=repo.owner,
                    repo=repo.name,
                    pr_number=pr_number,
                    installation_id=repo.installation_id,
                )
                if pr_detail.state != "open":
                    logger.info(
                        "pr_review_abandoned_pr_closed",
                        extra={"pr_number": pr_number, "state": pr_detail.state},
                    )
                    return {"status": "review_abandoned_pr_closed", "state": pr_detail.state}

                current_head = getattr(pr_detail, "head_commit_sha", None) or getattr(pr_detail, "head_sha", "")
                if current_head and current_head != head_sha:
                    logger.info(
                        "pr_review_abandoned_stale_head",
                        extra={
                            "pr_number": pr_number,
                            "current_head": current_head,
                            "reviewed_head": head_sha,
                        },
                    )
                    return {
                        "status": "review_abandoned_stale_head",
                        "current_head": current_head,
                        "reviewed_head": head_sha,
                    }
            except Exception as exc:
                logger.warning("pr_review_precheck_failed", extra={"error": str(exc)})

        # Execute CodeReviewOrchestrator (Phase 5)
        report = None
        try:
            from app.schemas.analysis import CodeReviewRequest, ReviewTarget
            from app.services.code_review_orchestrator import CodeReviewOrchestrator

            review_request = CodeReviewRequest(
                target=ReviewTarget.PR,
                pr_number=pr_number,
            )
            orchestrator = CodeReviewOrchestrator(
                db_session=db,
                github_source_service=getattr(github_service, "source_service", getattr(github_service, "_source_service", None)),
            )
            report = await orchestrator.execute_code_review(
                repository=repo,
                request=review_request,
                user_id=repo.user_id,
            )
        except Exception as review_exc:
            logger.warning("pr_review_orchestration_warning", extra={"error": str(review_exc)})

        # Compose consolidated review summary
        review_body = self._format_consolidated_review(report, head_sha, pr_number)

        # Publish review comment via GitHub API with event="COMMENT"
        if github_service and hasattr(github_service, "create_pull_request_review"):
            try:
                await github_service.create_pull_request_review(
                    owner=repo.owner,
                    repo=repo.name,
                    pr_number=pr_number,
                    body=review_body,
                    event="COMMENT",
                    installation_id=repo.installation_id,
                )
                logger.info(
                    "pr_review_comment_published",
                    extra={"repo_id": str(repo.id), "pr_number": pr_number, "head_sha": head_sha},
                )
            except Exception as exc:
                logger.error(
                    "pr_review_publish_failed",
                    extra={"repo_id": str(repo.id), "pr_number": pr_number, "error": str(exc)},
                )
                raise RetryableWebhookError(f"Failed to post PR review comment: {exc}") from exc

        return {"status": "review_published", "pr_number": pr_number, "head_sha": head_sha}


class IssuesEventHandler:
    """Handle `issues` webhook events (opened, edited, closed, reopened, labeled, assigned).
    
    Maintains read-only synchronized `GitHubIssue` database records.
    Strictly never posts comments, modifies labels, or closes issues on GitHub.
    """

    SUPPORTED_ACTIONS = {
        "opened", "edited", "closed", "reopened",
        "labeled", "unlabeled", "assigned", "unassigned",
    }

    async def handle(
        self,
        event: GitHubWebhookEvent,
        db: Session,
        github_service: Any = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        payload = event.payload or {}
        action = event.action or payload.get("action", "")

        if action not in self.SUPPORTED_ACTIONS:
            return {"status": "ignored_issue_action", "action": action}

        repo_payload = payload.get("repository", {})
        gh_repo_id = str(repo_payload.get("id", ""))
        repo = db.scalar(
            select(Repository).where(Repository.github_repo_id == gh_repo_id)
        )
        if not repo:
            return {"status": "ignored_unknown_repository", "github_repo_id": gh_repo_id}

        if not event.repository_id:
            event.repository_id = repo.id
            db.commit()

        issue_data = payload.get("issue", {})
        issue_number = issue_data.get("number")
        if not issue_number:
            return {"status": "ignored_missing_issue_number"}

        title = issue_data.get("title", "")
        body = issue_data.get("body", "") or ""
        state = issue_data.get("state", "open")
        html_url = issue_data.get("html_url", "")
        author = issue_data.get("user", {}).get("login", "")
        labels = [
            lbl.get("name") if isinstance(lbl, dict) else str(lbl)
            for lbl in issue_data.get("labels", [])
        ]

        existing = db.scalar(
            select(GitHubIssue).where(
                GitHubIssue.repository_id == repo.id,
                GitHubIssue.issue_number == issue_number,
            )
        )

        if existing:
            existing.title = title
            existing.body = body
            existing.state = state
            existing.labels = labels
            existing.html_url = html_url
            existing.author = author
            issue_id = existing.id
        else:
            new_issue = GitHubIssue(
                id=uuid.uuid4(),
                repository_id=repo.id,
                issue_number=issue_number,
                title=title,
                body=body,
                state=state,
                labels=labels,
                html_url=html_url,
                author=author,
            )
            db.add(new_issue)
            issue_id = new_issue.id

        db.commit()
        logger.info(
            "webhook_issue_upserted",
            extra={
                "repo_id": str(repo.id),
                "issue_number": issue_number,
                "action": action,
                "issue_id": str(issue_id),
            },
        )
        return {"status": "issue_upserted", "issue_id": str(issue_id), "issue_number": issue_number}


class WebhookEventDispatcher:
    """Route webhook events to registered handlers based on event_type."""

    def __init__(self) -> None:
        self.handlers: dict[str, EventHandlerProtocol] = {
            "push": PushEventHandler(),
            "installation": InstallationEventHandler(),
            "installation_repositories": InstallationRepositoriesEventHandler(),
            "pull_request": PullRequestEventHandler(),
            "issues": IssuesEventHandler(),
        }

    def register(self, event_type: str, handler: EventHandlerProtocol) -> None:
        self.handlers[event_type] = handler

    async def dispatch(
        self,
        event: GitHubWebhookEvent,
        db: Session,
        github_service: Any = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        handler = self.handlers.get(event.event_type)
        if not handler:
            logger.info("webhook_event_no_handler", extra={"event_type": event.event_type})
            return {"status": "ignored_unsupported_event", "event_type": event.event_type}

        return await handler.handle(
            event=event,
            db=db,
            github_service=github_service,
            **kwargs,
        )
