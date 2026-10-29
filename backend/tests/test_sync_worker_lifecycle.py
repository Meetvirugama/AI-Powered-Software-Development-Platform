"""Tests for sync worker resource lifecycle and failure-path cleanup (F-13)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app.models.github_installation import GitHubInstallation
from app.models.repository import Repository, SyncStatus
from app.models.sync_job import SyncJob, SyncJobStatus
from app.services.sync_worker import process_sync_job


@pytest.mark.asyncio
async def test_sync_worker_closes_embedding_service_on_failure(db_session, monkeypatch) -> None:
    """F-13: embedding_service.aclose() must be awaited even when indexer.sync() raises an exception."""
    repo_id = uuid4()
    job_id = uuid4()
    user_id = uuid4()
    inst_id = uuid4()

    installation = GitHubInstallation(
        id=inst_id,
        user_id=user_id,
        installation_id="123456",
        account_login="test-owner",
    )
    repo = Repository(
        id=repo_id,
        user_id=user_id,
        installation_id=inst_id,
        github_repo_id="gh-12345",
        owner="test-owner",
        name="test-repo",
        default_branch="main",
        sync_status=SyncStatus.NOT_SYNCED,
    )
    job = SyncJob(
        id=job_id,
        repository_id=repo_id,
        user_id=user_id,
        status=SyncJobStatus.QUEUED,
    )
    db_session.add(installation)
    db_session.add(repo)
    db_session.add(job)
    db_session.commit()

    monkeypatch.setattr("app.services.sync_worker.SessionLocal", lambda: db_session)
    # Prevent committing closed session in SessionLocal context
    monkeypatch.setattr(db_session, "close", lambda: None)

    # Mock github_service
    mock_github = MagicMock()
    mock_github.clone_repository = AsyncMock()

    # Mock FileWalker
    mock_walker = MagicMock()
    mock_walker.walk.return_value = []
    monkeypatch.setattr("app.services.sync_worker.FileWalker", lambda: mock_walker)

    # Mock Redis publisher
    mock_redis = AsyncMock()
    monkeypatch.setattr("app.services.sync_worker.get_redis_async", AsyncMock(return_value=mock_redis))

    # Mock EmbeddingService and GeminiEmbeddingProvider
    mock_embedding_service = MagicMock()
    mock_embedding_service.aclose = AsyncMock()
    monkeypatch.setattr("app.services.sync_worker.EmbeddingService", lambda **kw: mock_embedding_service)
    monkeypatch.setattr("app.services.sync_worker.GeminiEmbeddingProvider", MagicMock())

    # Mock IncrementalIndexer to raise an error during sync()
    mock_indexer = MagicMock()
    mock_indexer.sync = AsyncMock(side_effect=RuntimeError("Embedding API connection error"))
    monkeypatch.setattr("app.services.sync_worker.IncrementalIndexer", lambda **kw: mock_indexer)

    # Execute sync job
    await process_sync_job(
        job_id=job_id,
        repository_id=repo_id,
        user_id=user_id,
        github_service=mock_github,
    )

    # Assert embedding_service.aclose() was awaited despite the runtime error
    mock_embedding_service.aclose.assert_awaited_once()

    # Assert job and repository were marked FAILED
    updated_job = db_session.get(SyncJob, job_id)
    updated_repo = db_session.get(Repository, repo_id)
    assert updated_job.status == SyncJobStatus.FAILED
    assert updated_repo.sync_status == SyncStatus.FAILED
