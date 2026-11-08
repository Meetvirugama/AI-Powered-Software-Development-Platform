"""
Comprehensive Test Suite for Issue #184:
Separate Background Workers and Reliable Job Processing Architecture.

Covers:
1. Worker Separation & Production Configuration Defaults
2. Standalone Worker Entrypoint, Identity, and Heartbeat
3. Redis Queue BLMOVE & Mock Fallbacks
4. Job Leases and Heartbeat Protection against Premature Reclaim
5. Bounded Retries, Exponential Backoff, and Dead-Letter Queue
6. Per-Repository Concurrency Locking & Race Condition Prevention
7. Redundant Commit Skipping & Deletion Safety Checks
8. Distributed Embedding Rate Limiter Coordination
9. DBOS Transact Durable Workflow Proof of Concept (All 10 Criteria)
"""

from __future__ import annotations

import asyncio
import json
import socket
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from redis.exceptions import TimeoutError as RedisTimeoutError

from ai.embeddings.client import EmbeddingProvider
from ai.embeddings.rate_limiter import DistributedEmbeddingRateLimiter
from ai.embeddings.service import EmbeddingService
from app.core.config import Settings
from app.models.github_installation import GitHubInstallation
from app.models.repository import Repository, SyncStatus
from app.models.sync_job import SyncJob, SyncJobStatus
from app.services.sync_worker import (
    _heartbeat_lease,
    process_sync_job,
    recover_stale_processing_jobs,
    sync_worker_loop,
)
from app.workers.sync_worker import (
    _worker_heartbeat_loop,
    generate_worker_id,
    run_worker,
)
from poc.dbos.workflow import (
    DurableSyncWorkflow,
    run_durable_sync_workflow,
)


# ---------------------------------------------------------------------------
# 1. Worker Separation & Production Configuration Defaults
# ---------------------------------------------------------------------------

def test_production_config_defaults_disable_embedded_sync_worker():
    """Verify production settings automatically default disable_embedded_sync_worker to True."""
    prod = Settings(
        _env_file=None,
        app_env="production",
        jwt_secret="a" * 32,
        cookie_secure=True,
        cors_allowed_origins="https://app.example.com",
    )
    assert prod.is_production is True
    assert prod.disable_embedded_sync_worker is True


def test_development_config_preserves_embedded_sync_worker():
    """Verify development settings default disable_embedded_sync_worker to False."""
    dev = Settings(_env_file=None, app_env="development")
    assert dev.is_production is False
    assert dev.disable_embedded_sync_worker is False


@pytest.mark.asyncio
async def test_lifespan_suppresses_embedded_sync_worker_when_disabled(monkeypatch):
    """Verify FastAPI lifespan suppresses sync_worker_loop when disable_embedded_sync_worker is True."""
    from app.core.lifespan import lifespan

    mock_app = MagicMock()
    mock_app.state = MagicMock()

    custom_settings = Settings(
        _env_file=None,
        app_env="production",
        jwt_secret="a" * 32,
        cookie_secure=True,
        cors_allowed_origins="https://app.example.com",
        disable_embedded_sync_worker=True,
    )
    monkeypatch.setattr("app.core.lifespan.settings", custom_settings)

    mock_sync_loop = AsyncMock()
    monkeypatch.setattr("app.services.sync_worker.sync_worker_loop", mock_sync_loop)

    async with lifespan(mock_app):
        # In lifespan, embedded worker should NOT be created
        pass

    assert mock_sync_loop.call_count == 0


# ---------------------------------------------------------------------------
# 2. Standalone Worker Entrypoint, Identity, and Heartbeat
# ---------------------------------------------------------------------------

def test_generate_worker_id_format():
    """Verify generated worker ID includes hostname prefix and unique suffix."""
    worker_id = generate_worker_id()
    assert worker_id.startswith("sync-worker-")
    parts = worker_id.split("-")
    assert len(parts) >= 3


@pytest.mark.asyncio
async def test_worker_heartbeat_loop_publishes_to_redis_and_cleans_up():
    """Verify _worker_heartbeat_loop writes periodic heartbeat with TTL and deletes key on exit."""
    mock_redis = MagicMock()
    mock_redis.set = AsyncMock()
    mock_redis.delete = AsyncMock()

    stop_event = asyncio.Event()
    worker_id = "test-worker-123"

    heartbeat_task = asyncio.create_task(
        _worker_heartbeat_loop(
            redis=mock_redis,
            worker_id=worker_id,
            stop_event=stop_event,
            interval=0.01,
            ttl=10,
        )
    )

    await asyncio.sleep(0.03)
    stop_event.set()
    await heartbeat_task

    assert mock_redis.set.call_count >= 1
    mock_redis.delete.assert_awaited_once_with(f"worker:heartbeat:{worker_id}")

    # Inspect set payload
    set_call_args = mock_redis.set.call_args_list[0]
    key_arg = set_call_args[0][0]
    payload_arg = json.loads(set_call_args[0][1])
    assert key_arg == f"worker:heartbeat:{worker_id}"
    assert payload_arg["worker_id"] == worker_id
    assert "pid" in payload_arg


# ---------------------------------------------------------------------------
# 3. Redis Queue BLMOVE & Fallbacks
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_sync_worker_loop_prefers_blmove_over_brpoplpush():
    """Verify sync_worker_loop calls modern BLMOVE when redis client supports it."""
    mock_redis = MagicMock()
    mock_redis.blmove = AsyncMock(return_value=None)
    mock_redis.brpoplpush = AsyncMock(return_value=None)
    mock_redis.lrange = AsyncMock(return_value=[])

    with patch("app.services.sync_worker.get_redis_async", AsyncMock(return_value=mock_redis)):
        stop_event = asyncio.Event()
        task = asyncio.create_task(sync_worker_loop(worker_id="test-blmove", stop_event=stop_event))
        await asyncio.sleep(0.05)
        stop_event.set()
        await task

    assert mock_redis.blmove.call_count >= 1
    assert mock_redis.brpoplpush.call_count == 0


@pytest.mark.asyncio
async def test_sync_worker_loop_falls_back_to_brpoplpush_when_blmove_absent():
    """Verify sync_worker_loop uses brpoplpush when blmove is not present on client."""
    mock_redis = MagicMock(spec=["brpoplpush", "lrange", "rpush", "lrem", "set", "get", "delete"])
    mock_redis.brpoplpush = AsyncMock(return_value=None)
    mock_redis.lrange = AsyncMock(return_value=[])

    with patch("app.services.sync_worker.get_redis_async", AsyncMock(return_value=mock_redis)):
        stop_event = asyncio.Event()
        task = asyncio.create_task(sync_worker_loop(worker_id="test-fallback", stop_event=stop_event))
        await asyncio.sleep(0.05)
        stop_event.set()
        await task

    assert mock_redis.brpoplpush.call_count >= 1


# ---------------------------------------------------------------------------
# 4. Job Leases and Heartbeat Protection against Premature Reclaim
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_heartbeat_lease_renews_ttl():
    """Verify _heartbeat_lease coroutine periodically calls expire on lease and lock."""
    mock_redis = MagicMock()
    mock_redis.expire = AsyncMock()

    stop_event = asyncio.Event()
    task = asyncio.create_task(
        _heartbeat_lease(
            redis=mock_redis,
            lease_key="sync_job:lease:j1",
            lock_key="sync_lock:repo:r1",
            worker_id="w1",
            stop_event=stop_event,
            interval=0.01,
            ttl=30,
        )
    )

    await asyncio.sleep(0.03)
    stop_event.set()
    await task

    assert mock_redis.expire.call_count >= 1


@pytest.mark.asyncio
async def test_recover_stale_processing_jobs_respects_active_lease():
    """Verify recover_stale_processing_jobs does NOT reclaim a job with an active heartbeating lease."""
    mock_redis = MagicMock()
    mock_redis.lrange = AsyncMock()
    mock_redis.lrem = AsyncMock()
    mock_redis.rpush = AsyncMock()
    mock_redis.get = AsyncMock()

    job_id = uuid.uuid4()
    payload = {"job_id": str(job_id), "repository_id": str(uuid.uuid4()), "user_id": str(uuid.uuid4())}
    mock_redis.lrange.return_value = [json.dumps(payload).encode("utf-8")]

    # Active lease exists in Redis!
    mock_redis.get.return_value = json.dumps({"worker_id": "w1", "job_id": str(job_id)})

    recovered = await recover_stale_processing_jobs(mock_redis, timeout_seconds=600)
    assert len(recovered) == 0
    mock_redis.lrem.assert_not_called()
    mock_redis.rpush.assert_not_called()


@pytest.mark.asyncio
async def test_recover_stale_processing_jobs_reclaims_job_when_lease_expired():
    """Verify recover_stale_processing_jobs re-enqueues job when lease is expired/absent."""
    mock_redis = MagicMock()
    mock_redis.lrange = AsyncMock()
    mock_redis.lrem = AsyncMock()
    mock_redis.rpush = AsyncMock()
    mock_redis.get = AsyncMock()

    job_id = uuid.uuid4()
    repo_id = uuid.uuid4()
    payload = {"job_id": str(job_id), "repository_id": str(repo_id), "user_id": str(uuid.uuid4()), "attempt_count": 1}
    raw_payload = json.dumps(payload).encode("utf-8")
    mock_redis.lrange.return_value = [raw_payload]

    # Lease is expired (returns None)
    mock_redis.get.return_value = None

    stale_job = SyncJob(
        id=job_id,
        status=SyncJobStatus.RUNNING,
        created_at=datetime.now(timezone.utc) - timedelta(seconds=1000),
        repository_id=repo_id,
    )

    with patch("app.services.sync_worker.SessionLocal") as mock_session_local:
        session_mock = MagicMock()
        mock_session_local.return_value.__enter__.return_value = session_mock
        session_mock.get.return_value = stale_job

        recovered = await recover_stale_processing_jobs(mock_redis, timeout_seconds=600)
        assert str(job_id) in recovered
        mock_redis.lrem.assert_called_with("sync_jobs:processing", 1, raw_payload)
        # Check re-enqueued with attempt_count = 2
        enqueued_payload = json.loads(mock_redis.rpush.call_args[0][1])
        assert enqueued_payload["attempt_count"] == 2


# ---------------------------------------------------------------------------
# 5. Bounded Retries, Exponential Backoff, and Dead-Letter Queue
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_recover_stale_processing_jobs_moves_to_dead_letter_on_exhausted_retries():
    """Verify stale jobs past max_retries are sent to sync_jobs:dead_letter instead of retry."""
    mock_redis = MagicMock()
    mock_redis.lrange = AsyncMock()
    mock_redis.lrem = AsyncMock()
    mock_redis.rpush = AsyncMock()
    mock_redis.get = AsyncMock(return_value=None)

    job_id = uuid.uuid4()
    repo_id = uuid.uuid4()
    # Job has already reached attempt_count 3 (max_retries)
    payload = {"job_id": str(job_id), "repository_id": str(repo_id), "attempt_count": 3}
    raw_payload = json.dumps(payload).encode("utf-8")
    mock_redis.lrange.return_value = [raw_payload]

    stale_job = SyncJob(
        id=job_id,
        status=SyncJobStatus.RUNNING,
        created_at=datetime.now(timezone.utc) - timedelta(seconds=1000),
        repository_id=repo_id,
    )
    repo = Repository(id=repo_id, sync_status=SyncStatus.SYNCING)

    with patch("app.services.sync_worker.SessionLocal") as mock_session_local:
        session_mock = MagicMock()
        mock_session_local.return_value.__enter__.return_value = session_mock
        session_mock.get.side_effect = lambda model, ident: stale_job if model == SyncJob else repo

        recovered = await recover_stale_processing_jobs(mock_redis, timeout_seconds=600)
        assert str(job_id) in recovered
        mock_redis.lrem.assert_called_with("sync_jobs:processing", 1, raw_payload)

        # Verified moved to dead letter queue
        mock_redis.rpush.assert_called()
        queue_dest = mock_redis.rpush.call_args[0][0]
        assert queue_dest == "sync_jobs:dead_letter"
        assert stale_job.status == SyncJobStatus.FAILED
        assert repo.sync_status == SyncStatus.FAILED


# ---------------------------------------------------------------------------
# 6. Per-Repository Concurrency Locking & Race Condition Prevention
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_process_sync_job_aborts_when_repository_is_locked_by_another_worker():
    """Verify process_sync_job returns False when repository lock cannot be acquired."""
    mock_redis = MagicMock()
    # Redis SET NX returns None/False when key is already locked by another worker
    mock_redis.set = AsyncMock(return_value=False)
    mock_redis.delete = AsyncMock()

    job_id = uuid.uuid4()
    repo_id = uuid.uuid4()
    user_id = uuid.uuid4()

    repo = Repository(id=repo_id, sync_status=SyncStatus.SYNCING, installation_id=uuid.uuid4(), owner="org", name="repo")
    job = SyncJob(id=job_id, status=SyncJobStatus.QUEUED, repository_id=repo_id)

    with patch("app.services.sync_worker.SessionLocal") as mock_session_local:
        session_mock = MagicMock()
        mock_session_local.return_value.__enter__.return_value = session_mock
        session_mock.get.side_effect = lambda model, ident: repo if model == Repository else job

        result = await process_sync_job(
            job_id=job_id,
            repository_id=repo_id,
            user_id=user_id,
            redis_client=mock_redis,
        )

        assert result is False
        mock_redis.set.assert_awaited()


# ---------------------------------------------------------------------------
# 7. Redundant Commit Skipping & Deletion Safety Checks
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_process_sync_job_skips_redundant_already_indexed_commit():
    """Verify process_sync_job completes immediately without cloning when commit is already indexed."""
    mock_redis = MagicMock()
    job_id = uuid.uuid4()
    repo_id = uuid.uuid4()
    user_id = uuid.uuid4()
    target_sha = "abc123456789"

    repo = Repository(
        id=repo_id,
        sync_status=SyncStatus.SYNCED,
        last_indexed_commit_sha=target_sha,
        owner="org",
        name="repo",
    )
    job = SyncJob(id=job_id, status=SyncJobStatus.QUEUED, repository_id=repo_id)

    with patch("app.services.sync_worker.SessionLocal") as mock_session_local:
        session_mock = MagicMock()
        mock_session_local.return_value.__enter__.return_value = session_mock
        session_mock.get.side_effect = lambda model, ident: repo if model == Repository else job

        # Call with target_commit_sha matching last_indexed_commit_sha and force=False
        result = await process_sync_job(
            job_id=job_id,
            repository_id=repo_id,
            user_id=user_id,
            target_commit_sha=target_sha,
            force=False,
            redis_client=mock_redis,
        )

        assert result is True
        assert job.status == SyncJobStatus.COMPLETED


@pytest.mark.asyncio
async def test_process_sync_job_safely_aborts_when_repository_was_deleted():
    """Verify process_sync_job aborts cleanly without recreating records if repo was deleted."""
    mock_redis = MagicMock()
    job_id = uuid.uuid4()
    repo_id = uuid.uuid4()
    user_id = uuid.uuid4()

    job = SyncJob(id=job_id, status=SyncJobStatus.QUEUED, repository_id=repo_id)

    with patch("app.services.sync_worker.SessionLocal") as mock_session_local:
        session_mock = MagicMock()
        mock_session_local.return_value.__enter__.return_value = session_mock
        # Repo does NOT exist (deleted via Issue #183 cascades)
        session_mock.get.side_effect = lambda model, ident: None if model == Repository else job

        result = await process_sync_job(
            job_id=job_id,
            repository_id=repo_id,
            user_id=user_id,
            redis_client=mock_redis,
        )

        assert result is True
        assert job.status == SyncJobStatus.FAILED


# ---------------------------------------------------------------------------
# 8. Distributed Embedding Rate Limiter Coordination
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_distributed_rate_limiter_in_memory_sliding_window():
    """Verify DistributedEmbeddingRateLimiter enforces rate caps in in-memory mode."""
    limiter = DistributedEmbeddingRateLimiter(redis=None, max_requests_per_minute=2, window_seconds=0.2)

    t0 = time.monotonic()
    w1 = await limiter.acquire("test_provider")
    w2 = await limiter.acquire("test_provider")
    assert w1 == 0.0
    assert w2 == 0.0

    # Third request exceeds quota of 2; must wait for window to slide
    w3 = await limiter.acquire("test_provider")
    elapsed = time.monotonic() - t0
    assert w3 > 0.0
    assert elapsed >= 0.15


@pytest.mark.asyncio
async def test_embedding_service_invokes_rate_limiter():
    """Verify EmbeddingService queries rate limiter before issuing provider requests."""
    mock_provider = MagicMock(spec=EmbeddingProvider)
    mock_provider.provider_name = "test_gemini"
    mock_provider.embedding_dimensions = 4
    mock_provider.embed_batch = AsyncMock(return_value=[[0.1, 0.2, 0.3, 0.4]])

    mock_limiter = MagicMock()
    mock_limiter.acquire = AsyncMock()

    service = EmbeddingService(
        provider=mock_provider,
        batch_size=10,
        max_concurrency=2,
        rate_limiter=mock_limiter,
    )

    res = await service.embed_batch(["sample code"])
    assert len(res) == 1
    mock_limiter.acquire.assert_awaited_with("test_gemini")


# ---------------------------------------------------------------------------
# 9. DBOS Transact Durable Workflow Proof of Concept (All 10 Criteria)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_dbos_workflow_full_execution():
    """Criterion 1 & 2: Test complete 4-step durable workflow execution."""
    wf_id = f"wf-{uuid.uuid4().hex[:8]}"
    result = await run_durable_sync_workflow(
        workflow_id=wf_id,
        repository_id="repo-1",
        owner="org",
        repo="project",
    )

    assert result.status == "SUCCESS"
    assert "clone" in result.completed_steps
    assert "scan" in result.completed_steps
    assert "embed" in result.completed_steps
    assert "commit" in result.completed_steps
    assert result.output["status"] == "COMPLETED"


@pytest.mark.asyncio
async def test_dbos_workflow_crash_recovery_resumes_from_checkpoint():
    """Criterion 3: Test that simulated process crash resumes without repeating completed steps."""
    wf_id = f"wf-crash-{uuid.uuid4().hex[:8]}"

    # Step A: Run with crash injected after 'scan' step
    interrupted_result = await run_durable_sync_workflow(
        workflow_id=wf_id,
        repository_id="repo-2",
        owner="org",
        repo="project",
        simulate_crash_after="scan",
    )
    assert interrupted_result.status == "FAILED"
    assert "clone" in interrupted_result.completed_steps
    assert "scan" in interrupted_result.completed_steps
    assert "embed" not in interrupted_result.completed_steps

    # Step B: Restart workflow process with same workflow_id
    resumed_result = await run_durable_sync_workflow(
        workflow_id=wf_id,
        repository_id="repo-2",
        owner="org",
        repo="project",
    )
    assert resumed_result.status == "SUCCESS"
    assert resumed_result.resumed_from_checkpoint is True
    # All 4 steps now complete
    assert len(resumed_result.completed_steps) == 4


@pytest.mark.asyncio
async def test_dbos_workflow_deduplication_by_id():
    """Criterion 7: Test that duplicate workflow submission returns existing result."""
    wf_id = f"wf-dedup-{uuid.uuid4().hex[:8]}"
    res1 = await run_durable_sync_workflow(
        workflow_id=wf_id,
        repository_id="repo-3",
        owner="org",
        repo="project",
    )
    res2 = await run_durable_sync_workflow(
        workflow_id=wf_id,
        repository_id="repo-3",
        owner="org",
        repo="project",
    )
    assert res1.status == "SUCCESS"
    assert res2.status == "SUCCESS"
    assert res1.total_duration_ms == res2.total_duration_ms


@pytest.mark.asyncio
async def test_dbos_workflow_step_retries_transient_failure():
    """Criterion 5: Test that transient step failure is retried with backoff."""
    wf_id = f"wf-retry-{uuid.uuid4().hex[:8]}"
    result = await run_durable_sync_workflow(
        workflow_id=wf_id,
        repository_id="repo-4",
        owner="org",
        repo="project",
        fail_embed_attempts=2,  # First 2 attempts fail with transient 429
        max_retries=3,
    )
    assert result.status == "SUCCESS"
    assert result.step_records["embed"].attempts == 3
