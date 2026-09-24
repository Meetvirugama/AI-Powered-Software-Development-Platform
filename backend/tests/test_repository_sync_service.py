"""Contract tests for Yug's Day 4 sync orchestration."""

from __future__ import annotations

from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest

from app.core.errors import APIError
from app.models.repository import SyncStatus
from app.models.sync_job import SyncJobStatus
from app.services.repository_sync import RedisSyncJobQueue, RepositorySyncService


class FakeRedis:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def rpush(self, name: str, payload: str) -> None:
        self.calls.append((name, payload))


class FakeRepositoryRepository:
    def __init__(self, repository: object | None) -> None:
        self.repository = repository
        self.statuses: list[SyncStatus] = []
        self.failed_job_ids: list[UUID] = []

    def get_for_user(self, _: UUID, __: UUID) -> object | None:
        return self.repository

    def create_sync_job(self, repository_id: UUID, user_id: UUID) -> object:
        return SimpleNamespace(id=uuid4(), repository_id=repository_id, user_id=user_id, status=SyncJobStatus.QUEUED)

    def update_sync_status(self, _: UUID, status: SyncStatus) -> None:
        self.statuses.append(status)

    def mark_sync_job_failed(self, job_id: UUID) -> None:
        self.failed_job_ids.append(job_id)


def _repository() -> object:
    return SimpleNamespace(
        id=uuid4(), installation_id=uuid4(), owner="acme", name="platform", default_branch="main"
    )


def test_request_sync_enqueues_complete_worker_context() -> None:
    repository = _repository()
    repositories = FakeRepositoryRepository(repository)
    redis = FakeRedis()

    job = RepositorySyncService(repositories, RedisSyncJobQueue(redis)).request_sync(repository.id, uuid4())

    assert repositories.statuses == [SyncStatus.SYNCING]
    assert len(redis.calls) == 1
    assert redis.calls[0][0] == "sync_jobs"
    assert '"installation_id"' in redis.calls[0][1]
    assert str(job.id) in redis.calls[0][1]


def test_request_sync_does_not_enqueue_an_unowned_repository() -> None:
    redis = FakeRedis()
    service = RepositorySyncService(FakeRepositoryRepository(None), RedisSyncJobQueue(redis))

    with pytest.raises(APIError) as error:
        service.request_sync(uuid4(), uuid4())

    assert error.value.status_code == 404
    assert redis.calls == []
