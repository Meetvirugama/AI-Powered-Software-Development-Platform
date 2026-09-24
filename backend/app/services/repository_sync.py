"""Orchestration for repository synchronization requests.

The API must only create and dispatch a job.  Clone, scan, and indexing work is
performed by the sync worker, which consumes the ``sync_jobs`` queue.  Keeping
the payload explicit makes the hand-off to the GitHub integration independent
of HTTP request state.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from app.core.errors import APIError, ErrorCode
from app.models.repository import Repository, SyncStatus
from app.models.sync_job import SyncJob
from app.repositories.repository_repository import RepositoryRepository


class SyncJobQueue(Protocol):
    """Queue boundary consumed by Yug's worker and produced by the API."""

    def enqueue(self, job: SyncJob, repository: Repository) -> None:
        """Make a queued sync job available to a worker."""


@dataclass(frozen=True)
class RedisSyncJobQueue:
    """Redis implementation of the sync-worker hand-off."""

    redis: object
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

    def __init__(self, repositories: RepositoryRepository, queue: SyncJobQueue):
        self.repositories = repositories
        self.queue = queue

    def request_sync(self, repository_id: UUID, user_id: UUID) -> SyncJob:
        """Create a job and dispatch it for the GitHub-backed sync worker."""
        repository = self.repositories.get_for_user(repository_id, user_id)
        if repository is None:
            raise APIError(
                404,
                ErrorCode.REPOSITORY_NOT_FOUND,
                "Repository does not exist or you do not have access.",
            )

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
