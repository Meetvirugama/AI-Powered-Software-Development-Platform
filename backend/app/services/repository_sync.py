"""Orchestration for repository synchronization requests.

The API must only create and dispatch a job.  Clone, scan, and indexing work is
performed by the sync worker, which consumes the ``sync_jobs`` queue.  Keeping
the payload explicit makes the hand-off to the GitHub integration independent
of HTTP request state.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Protocol
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.errors import APIError, ErrorCode
from app.models.repository import Repository, SyncStatus
from app.models.sync_job import SyncJob, SyncJobStatus
from app.repositories.repository_repository import RepositoryRepository

logger = logging.getLogger(__name__)


def reconcile_stale_sync_jobs(
    session: Session,
    timeout_seconds: int = 600,
) -> list[UUID]:
    """Sweep stalled or crashed sync jobs and reconcile repository states.

    Any SyncJob in QUEUED or RUNNING status past timeout_seconds is transitioned
    to FAILED with retryable status. If the repository is currently in SYNCING
    status, its status is also reset to FAILED so it does not remain indefinitely locked.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(seconds=timeout_seconds)
    stmt = (
        select(SyncJob)
        .where(
            SyncJob.status.in_([SyncJobStatus.QUEUED, SyncJobStatus.RUNNING]),
            func.coalesce(SyncJob.updated_at, SyncJob.created_at) < cutoff,
        )
    )
    stale_jobs = list(session.scalars(stmt).all())
    reconciled_ids: list[UUID] = []

    for job in stale_jobs:
        job.status = SyncJobStatus.FAILED
        reconciled_ids.append(job.id)
        repo = session.get(Repository, job.repository_id)
        if repo and repo.sync_status == SyncStatus.SYNCING:
            repo.sync_status = SyncStatus.FAILED
        logger.warning(
            "stale_sync_job_reconciled",
            extra={
                "job_id": str(job.id),
                "repository_id": str(job.repository_id),
                "timeout_seconds": timeout_seconds,
            },
        )

    # Reconcile any repositories stuck in SYNCING that have no active queued or running job
    active_job_repo_ids = select(SyncJob.repository_id).where(
        SyncJob.status.in_([SyncJobStatus.QUEUED, SyncJobStatus.RUNNING])
    )
    orphaned_syncing_repos = list(
        session.scalars(
            select(Repository).where(
                Repository.sync_status == SyncStatus.SYNCING,
                ~Repository.id.in_(active_job_repo_ids),
            )
        ).all()
    )
    for o_repo in orphaned_syncing_repos:
        o_repo.sync_status = SyncStatus.FAILED
        logger.warning(
            "orphaned_syncing_repository_reconciled",
            extra={"repository_id": str(o_repo.id)},
        )

    if reconciled_ids or orphaned_syncing_repos:
        session.commit()

    return reconciled_ids


class SyncJobQueue(Protocol):
    """Queue boundary consumed by Yug's worker and produced by the API."""

    def enqueue(self, job: SyncJob, repository: Repository) -> None:
        """Make a queued sync job available to a worker."""


@dataclass(frozen=True)
class RedisSyncJobQueue:
    """Redis implementation of the sync-worker hand-off."""

    redis: Any
    queue_name: str = "sync_jobs"

    def enqueue(self, job: SyncJob, repository: Repository) -> None:
        payload = {
            "job_id": str(job.id),
            "repository_id": str(repository.id),
            "user_id": str(job.user_id),
            # The worker uses these values to call Parth's GitHubService without
            # having to trust a client-supplied repository name or branch.
            "installation_id": str(repository.installation_id),
            "owner": repository.owner,
            "name": repository.name,
            "branch": repository.default_branch,
        }
        self.redis.rpush(self.queue_name, json.dumps(payload))


class RepositorySyncService:
    """Coordinate Om's repository layer with the asynchronous sync queue."""

    def __init__(
        self,
        repositories: RepositoryRepository,
        queue: SyncJobQueue,
        timeout_seconds: int = 600,
    ) -> None:
        self.repositories = repositories
        self.queue = queue
        self.timeout_seconds = timeout_seconds

    def request_sync(self, repository_id: UUID, user_id: UUID, force: bool = False) -> SyncJob:
        """Create a job and dispatch it for the GitHub-backed sync worker.

        Idempotently returns an existing in-flight job if one was recently created
        and has not exceeded the timeout threshold, unless force=True.
        """
        repository = self.repositories.get_for_user(repository_id, user_id)
        if repository is None:
            raise APIError(
                404,
                ErrorCode.REPOSITORY_NOT_FOUND,
                "Repository does not exist or you do not have access.",
            )

        # Idempotency check: Reuse existing active job if within timeout, unless force requested
        if hasattr(self.repositories, "get_active_sync_job"):
            active_job = self.repositories.get_active_sync_job(repository.id)
            if active_job is not None:
                if force:
                    logger.info(
                        "force_sync_requested_superseding_active_job",
                        extra={"job_id": str(active_job.id), "repository_id": str(repository_id)},
                    )
                    self.repositories.mark_sync_job_failed(active_job.id)
                else:
                    now = datetime.now(timezone.utc)
                    job_time = getattr(active_job, "updated_at", None) or getattr(active_job, "created_at", None)
                    if job_time and job_time.tzinfo is None:
                        job_time = job_time.replace(tzinfo=timezone.utc)
                    age_seconds = (now - job_time).total_seconds() if job_time else 0.0

                    if age_seconds < self.timeout_seconds:
                        logger.info(
                            "sync_job_idempotent_reuse",
                            extra={
                                "job_id": str(active_job.id),
                                "repository_id": str(repository_id),
                                "status": str(active_job.status),
                                "age_seconds": round(age_seconds, 1),
                            },
                        )
                        return active_job
                    else:
                        logger.warning(
                            "stale_active_sync_job_superseded",
                            extra={
                                "job_id": str(active_job.id),
                                "repository_id": str(repository_id),
                                "age_seconds": round(age_seconds, 1),
                            },
                        )
                        self.repositories.mark_sync_job_failed(active_job.id)

        job = self.repositories.create_sync_job(repository.id, user_id)
        try:
            self.queue.enqueue(job, repository)
        except Exception as exc:
            # The persisted job is useful for operations/debugging, but it must
            # not look runnable when no worker can receive it.
            self.repositories.mark_sync_job_failed(job.id)
            self.repositories.update_sync_status(repository.id, SyncStatus.FAILED)
            raise APIError(503, ErrorCode.SERVICE_UNAVAILABLE, "Sync queue is unavailable.", retryable=True) from exc

        self.repositories.update_sync_status(repository.id, SyncStatus.SYNCING)
        return job
