"""Tests for sync-job recovery, reconciliation, and structured logs for best-effort failures.

Week 2 Section 12:
- Item 15: Sync-job recovery and reconciliation (B-12).
- Item 16: Structured logs for swallowed best-effort failures (B-11, B-12).
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import UUID, uuid4

import pytest
from app.core.database import SessionLocal
from app.core.errors import APIError
from app.models.repository import Repository, SyncStatus
from app.models.sync_job import SyncJob, SyncJobStatus
from app.models.user import User
from app.repositories.repository_repository import RepositoryRepository
from app.services.repository_sync import (
    RedisSyncJobQueue,
    RepositorySyncService,
    reconcile_stale_sync_jobs,
)


class FakeRedisQueue:
    def __init__(self) -> None:
        self.enqueued: list[tuple[str, str]] = []

    def rpush(self, name: str, payload: str) -> None:
        self.enqueued.append((name, payload))


def test_reconcile_stale_sync_jobs_transitions_stalled_jobs_to_failed(db_session):
    """Verify that reconcile_stale_sync_jobs sweeps jobs older than timeout and unlocks repository."""
    # Create test user and repository
    user = User(
        github_id=f"gh_{uuid4().hex[:8]}",
        login=f"user_{uuid4().hex[:8]}",
        email=f"sync_test_{uuid4().hex[:8]}@example.com",
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)

    repo = Repository(
        user_id=user.id,
        installation_id=uuid4(),
        github_repo_id=f"github_{uuid4().hex[:8]}",
        owner="test-owner",
        name="test-repo",
        default_branch="main",
        sync_status=SyncStatus.SYNCING,
    )
    db_session.add(repo)
    db_session.commit()
    db_session.refresh(repo)

    # Stale job older than 15 minutes (900 seconds)
    stale_time = datetime.now(timezone.utc) - timedelta(seconds=900)
    stale_job = SyncJob(
        repository_id=repo.id,
        user_id=user.id,
        status=SyncJobStatus.RUNNING,
    )
    db_session.add(stale_job)
    db_session.commit()
    db_session.refresh(stale_job)

    # Manually backdate updated_at and created_at to simulate a crash 15 minutes ago
    db_session.execute(
        SyncJob.__table__.update()
        .where(SyncJob.id == stale_job.id)
        .values(created_at=stale_time, updated_at=stale_time)
    )
    db_session.commit()

    # Also add a fresh running job (< 60 seconds) that should NOT be touched
    fresh_job = SyncJob(
        repository_id=repo.id,
        user_id=user.id,
        status=SyncJobStatus.RUNNING,
    )
    db_session.add(fresh_job)
    db_session.commit()
    db_session.refresh(fresh_job)

    # Run sweep with 600s (10 min) timeout threshold
    reconciled_ids = reconcile_stale_sync_jobs(db_session, timeout_seconds=600)

    assert stale_job.id in reconciled_ids
    assert fresh_job.id not in reconciled_ids

    # Verify stale job is now FAILED
    db_session.refresh(stale_job)
    assert stale_job.status == SyncJobStatus.FAILED

    # Verify fresh job is still RUNNING
    db_session.refresh(fresh_job)
    assert fresh_job.status == SyncJobStatus.RUNNING

    # Clean up
    db_session.delete(fresh_job)
    db_session.delete(stale_job)
    db_session.delete(repo)
    db_session.delete(user)
    db_session.commit()


def test_request_sync_idempotency_reuses_in_flight_job():
    """Verify repeat sync requests for an in-flight job return existing job without enqueueing duplicates."""
    repo_id = uuid4()
    user_id = uuid4()
    existing_job_id = uuid4()

    fake_repo = SimpleNamespace(
        id=repo_id,
        installation_id=uuid4(),
        owner="owner",
        name="repo",
        default_branch="main",
    )
    active_job = SimpleNamespace(
        id=existing_job_id,
        repository_id=repo_id,
        user_id=user_id,
        status=SyncJobStatus.RUNNING,
        created_at=datetime.now(timezone.utc) - timedelta(seconds=10),
        updated_at=datetime.now(timezone.utc) - timedelta(seconds=10),
    )

    fake_repos = MagicMock()
    fake_repos.get_for_user.return_value = fake_repo
    fake_repos.get_active_sync_job.return_value = active_job

    fake_redis = FakeRedisQueue()
    fake_queue = RedisSyncJobQueue(fake_redis)
    service = RepositorySyncService(fake_repos, fake_queue, timeout_seconds=600)

    # First repeat call: should reuse active_job and NOT call enqueue or create_sync_job
    result = service.request_sync(repo_id, user_id)

    assert result.id == existing_job_id
    assert len(fake_redis.enqueued) == 0
    fake_repos.create_sync_job.assert_not_called()


def test_request_sync_supersedes_stale_job_with_fresh_job():
    """Verify that an active job older than timeout is marked FAILED and a fresh job is enqueued."""
    repo_id = uuid4()
    user_id = uuid4()
    stale_job_id = uuid4()
    fresh_job_id = uuid4()

    fake_repo = SimpleNamespace(
        id=repo_id,
        installation_id=uuid4(),
        owner="owner",
        name="repo",
        default_branch="main",
    )
    stale_job = SimpleNamespace(
        id=stale_job_id,
        repository_id=repo_id,
        user_id=user_id,
        status=SyncJobStatus.RUNNING,
        created_at=datetime.now(timezone.utc) - timedelta(seconds=900),
        updated_at=datetime.now(timezone.utc) - timedelta(seconds=900),
    )
    fresh_job = SimpleNamespace(
        id=fresh_job_id,
        repository_id=repo_id,
        user_id=user_id,
        status=SyncJobStatus.QUEUED,
    )

    fake_repos = MagicMock()
    fake_repos.get_for_user.return_value = fake_repo
    fake_repos.get_active_sync_job.return_value = stale_job
    fake_repos.create_sync_job.return_value = fresh_job

    fake_redis = FakeRedisQueue()
    fake_queue = RedisSyncJobQueue(fake_redis)
    service = RepositorySyncService(fake_repos, fake_queue, timeout_seconds=600)

    result = service.request_sync(repo_id, user_id)

    # Verify stale job was failed
    fake_repos.mark_sync_job_failed.assert_called_once_with(stale_job_id)
    # Verify fresh job was created and enqueued
    fake_repos.create_sync_job.assert_called_once_with(repo_id, user_id)
    assert result.id == fresh_job_id
    assert len(fake_redis.enqueued) == 1


def test_get_counts_for_repos_db_failure_logs_and_raises_503(caplog):
    """Verify B-11: DB failure in _get_counts_for_repos raises 503 retryable and logs structured error."""
    import logging
    from app.api.v1.repositories import _get_counts_for_repos

    broken_db = MagicMock()
    broken_db._is_mock_db = False
    broken_db.query.side_effect = RuntimeError("Database connection pool exhausted")

    fake_request = SimpleNamespace(state=SimpleNamespace(request_id="req-test-1234"))
    repo_id = uuid4()

    with caplog.at_level(logging.ERROR):
        with pytest.raises(APIError) as exc_info:
            _get_counts_for_repos([repo_id], broken_db, request=fake_request)

    assert exc_info.value.status_code == 503
    assert exc_info.value.retryable is True
    assert "Database service is temporarily unavailable" in exc_info.value.message

    # Verify structured error log was emitted
    assert any("repo_counts_query_failed" in r.message for r in caplog.records)


def test_event_publication_failure_logs_structured_warning(monkeypatch, caplog):
    """Verify B-12: Redis event publication failure in sync endpoint logs structured warning."""
    import logging
    from fastapi.testclient import TestClient
    from app.core.config import get_settings
    from app.core.database import get_db
    from app.core.security import create_access_token
    from app.main import app

    class FailingRedis:
        def exists(self, _):
            return 0

        def rpush(self, *args, **kwargs):
            pass

        def publish(self, *args, **kwargs):
            raise ConnectionError("Redis pubsub connection reset by peer")

        def pipeline(self):
            class _Pipe:
                def incr(self, _k):
                    pass

                def expire(self, _k, _s):
                    pass

                def execute(self):
                    return [1, True]

            return _Pipe()

    failing_redis = FailingRedis()
    monkeypatch.setenv("JWT_SECRET", "test-secret-key-12345")
    get_settings.cache_clear()
    monkeypatch.setattr("app.core.auth.get_redis", lambda: failing_redis)
    monkeypatch.setattr("app.core.redis.get_redis", lambda: failing_redis)
    monkeypatch.setattr("app.api.v1.repositories.get_redis", lambda: failing_redis)

    user_id = "0e969876-16d2-4c9f-8fe1-a849f32fa605"
    token, _ = create_access_token(user_id)
    repo_id = uuid4()

    fake_repo = SimpleNamespace(
        id=repo_id,
        user_id=UUID(user_id),
        installation_id=uuid4(),
        owner="test-owner",
        name="test-repo",
        default_branch="main",
        sync_status=SyncStatus.NOT_SYNCED,
    )
    fake_job = SimpleNamespace(id=uuid4(), repository_id=repo_id, user_id=UUID(user_id), status=SyncJobStatus.QUEUED)

    monkeypatch.setattr("app.api.v1.repositories._owned_repository", lambda *a, **kw: fake_repo)
    monkeypatch.setattr("app.repositories.repository_repository.RepositoryRepository.get_for_user", lambda *a, **kw: fake_repo)
    monkeypatch.setattr("app.repositories.repository_repository.RepositoryRepository.create_sync_job", lambda *a, **kw: fake_job)
    monkeypatch.setattr("app.repositories.repository_repository.RepositoryRepository.update_sync_status", lambda *a, **kw: None)

    app.dependency_overrides[get_db] = lambda: object()
    try:
        client = TestClient(app, raise_server_exceptions=False)
        with caplog.at_level(logging.WARNING):
            resp = client.post(
                f"/api/v1/repositories/{repo_id}/sync",
                headers={"Authorization": f"Bearer {token}"},
            )
    finally:
        app.dependency_overrides.clear()

    # The sync request succeeds with 202 ACCEPTED
    assert resp.status_code == 202
    assert resp.json()["job_id"] == str(fake_job.id)

    # But event_publication_failed warning was logged with structured extra
    assert any("event_publication_failed" in r.message for r in caplog.records)
