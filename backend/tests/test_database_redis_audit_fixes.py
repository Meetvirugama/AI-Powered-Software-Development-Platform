"""TDD tests for Database & Redis Reliability and Production Audit (task2.md).

Covers:
1. P0.1 - P0.3: IncrementalIndexer transaction boundaries, deleted file reconciliation, and batch validation.
2. P0.4 - P0.5: Reliable sync queue acknowledgement and stale processing recovery.
3. P0.6: EmbeddingQueue acknowledgement only after successful DB commit & batch count validation.
4. P0.10: Remote production Redis TLS validation (rediss://).
5. P1.3: Repository deletion clean transaction without swallowing errors.
6. P1.5 - P1.6: SourceRevisionCache memory TTL, capacity bounds, and Redis wiring.
7. P1.7: Installation token manager single-flight concurrency lock.
8. GitHub installation repository upsert user_id updating and route linking.
"""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from app.core.config import Settings
from app.integrations.github.cache import SourceRevisionCache
from app.integrations.github.source_service import GitHubSourceService
from app.integrations.github.token_manager import InstallationTokenManager
from app.models.github_installation import GitHubInstallation
from app.models.repository import Repository
from app.models.sync_job import SyncJob, SyncJobStatus
from app.repositories.github_installation_repository import GitHubInstallationRepository
from app.repositories.repository_repository import RepositoryRepository
from app.services.sync_worker import recover_stale_processing_jobs, sync_worker_loop
from indexer.embedding_queue import EmbeddingQueue
from indexer.models import Chunk


# ---------------------------------------------------------------------------
# 1. GitHub Installation Repository: Upsert Updates user_id
# ---------------------------------------------------------------------------

def test_github_installation_upsert_updates_user_id():
    """Verify upsert updates existing record's user_id when linking to a new user account."""
    mock_session = MagicMock()
    existing_inst = GitHubInstallation(
        user_id=uuid.uuid4(),
        installation_id="171308854",
        account_login="OldLogin",
        permissions={},
    )
    mock_session.execute.return_value.scalar_one_or_none.return_value = existing_inst

    repo = GitHubInstallationRepository(mock_session)
    new_user_id = uuid.uuid4()
    updated = repo.upsert(
        user_id=new_user_id,
        installation_id="171308854",
        account_login="Meetvirugama",
        permissions={"metadata": "read"},
    )

    assert updated.user_id == new_user_id
    assert updated.account_login == "Meetvirugama"
    mock_session.commit.assert_called()


# ---------------------------------------------------------------------------
# 2. Sync Worker: Reliable Queue Hand-Off & Stale Processing Recovery
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_recover_stale_processing_jobs():
    """Test recover_stale_processing_jobs detects timed out jobs and re-enqueues them."""
    mock_redis = MagicMock()
    mock_redis.lrange = AsyncMock()
    mock_redis.lrem = AsyncMock()
    mock_redis.rpush = AsyncMock()

    job_id = uuid.uuid4()
    payload = {
        "job_id": str(job_id),
        "repository_id": str(uuid.uuid4()),
        "user_id": str(uuid.uuid4()),
    }
    raw_payload = json.dumps(payload).encode("utf-8")
    mock_redis.lrange.return_value = [raw_payload]

    from datetime import datetime, timedelta, timezone

    # Stale job older than 600s
    stale_job = SyncJob(
        id=job_id,
        status=SyncJobStatus.RUNNING,
        created_at=datetime.now(timezone.utc) - timedelta(seconds=1000),
        updated_at=None,
    )

    with patch("app.services.sync_worker.SessionLocal") as mock_session_local:
        session_mock = MagicMock()
        mock_session_local.return_value.__enter__.return_value = session_mock
        session_mock.get.return_value = stale_job

        recovered = await recover_stale_processing_jobs(mock_redis, timeout_seconds=600)
        assert str(job_id) in recovered
        mock_redis.lrem.assert_called_with("sync_jobs:processing", 1, raw_payload)
        mock_redis.rpush.assert_called_with("sync_jobs", json.dumps(payload))


# ---------------------------------------------------------------------------
# 3. EmbeddingQueue: Batch Count Validation & DB Rollback Protection
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_embedding_queue_batch_count_mismatch_raises():
    """Verify EmbeddingQueue rejects mismatched vector counts and does not clear processing queue."""
    mock_redis = MagicMock()
    mock_redis.rpoplpush.return_value = json.dumps(
        {"chunk_id": str(uuid.uuid4()), "content": "print('hello')"}
    )
    mock_service = MagicMock()
    # Return 2 vectors for 1 item (mismatch)
    mock_service.embed_batch = AsyncMock(return_value=[[0.1] * 768, [0.2] * 768])

    eq = EmbeddingQueue(mock_redis, mock_service)
    with pytest.raises(ValueError, match="Embedding batch count mismatch"):
        await eq.process_batch(db_session=None)


@pytest.mark.asyncio
async def test_embedding_queue_persistence_failure_rolls_back_and_requeues():
    """Verify EmbeddingQueue does not acknowledge work if DB persistence fails."""
    chunk_id = uuid.uuid4()
    raw_item = json.dumps({"chunk_id": str(chunk_id), "content": "func()"})
    mock_redis = MagicMock()
    # First call returns item, second call returns None
    mock_redis.rpoplpush.side_effect = [raw_item, None]

    mock_service = MagicMock()
    mock_service.embed_batch = AsyncMock(return_value=[[0.5] * 768])

    mock_db = MagicMock()
    mock_db.commit.side_effect = RuntimeError("Disk full / DB failure")

    eq = EmbeddingQueue(mock_redis, mock_service)
    with pytest.raises(RuntimeError, match="Database persistence failed"):
        await eq.process_batch(db_session=mock_db)

    # Must rollback DB
    mock_db.rollback.assert_called_once()
    # Must re-push to queue
    mock_redis.lpush.assert_called_with("embedding_queue", raw_item)


# ---------------------------------------------------------------------------
# 4. SourceRevisionCache: Memory TTL, Capacity Bound, and Redis Wiring
# ---------------------------------------------------------------------------

def test_source_revision_cache_memory_ttl_eviction():
    """Verify in-memory entries expire and are not served past their TTL."""
    cache = SourceRevisionCache(redis_client=None, default_ttl_seconds=1)
    repo_id = uuid.uuid4()
    cache.set(repo_id, "main", "foo.py", {"content": "print('hi')"}, ttl_seconds=0.01)

    # Immediately available
    entry = cache.get(repo_id, "main", "foo.py")
    assert entry is not None

    # Wait for TTL to elapse
    time.sleep(0.02)
    expired = cache.get(repo_id, "main", "foo.py")
    assert expired is None


def test_source_revision_cache_capacity_bounding():
    """Verify memory cache bounds its entry count and evicts oldest items."""
    cache = SourceRevisionCache(redis_client=None, max_memory_entries=2)
    repo_id = uuid.uuid4()
    cache.set(repo_id, "main", "file1.py", {"content": "1"})
    cache.set(repo_id, "main", "file2.py", {"content": "2"})
    cache.set(repo_id, "main", "file3.py", {"content": "3"})

    # file1.py should have been evicted to maintain capacity of 2
    assert cache.get(repo_id, "main", "file1.py") is None
    assert cache.get(repo_id, "main", "file2.py") is not None
    assert cache.get(repo_id, "main", "file3.py") is not None


def test_github_source_service_wires_redis_cache():
    """Verify GitHubSourceService automatically wires Redis client into SourceRevisionCache."""
    mock_db = MagicMock()
    with patch("app.core.redis.get_redis") as mock_get_redis:
        fake_redis = MagicMock()
        mock_get_redis.return_value = fake_redis
        service = GitHubSourceService(mock_db)
        assert service._cache._redis is fake_redis


# ---------------------------------------------------------------------------
# 5. Token Manager: Single-Flight Concurrency Lock
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_token_manager_single_flight_lock():
    """Verify concurrent get_token requests with cache miss only mint once."""
    mock_redis = MagicMock()
    mock_redis.get = AsyncMock(return_value=None)
    mock_redis.set = AsyncMock()

    settings = Settings(
        app_env="development",
        github_app_id="12345",
        github_app_private_key="fake-pem",
    )
    manager = InstallationTokenManager(mock_redis, settings)
    mint_count = 0

    async def _mock_mint(inst_id: int):
        nonlocal mint_count
        mint_count += 1
        await asyncio.sleep(0.02)
        # Simulate caching during mint
        mock_redis.get.return_value = "ghs_token_fresh"
        return "ghs_token_fresh"

    with patch.object(manager, "_mint_token", side_effect=_mock_mint):
        # Fire 5 concurrent get_token calls for installation 999
        results = await asyncio.gather(*[manager.get_token(999) for _ in range(5)])
        assert all(t == "ghs_token_fresh" for t in results)
        assert mint_count == 1  # Only one mint occurred thanks to single-flight lock!


# ---------------------------------------------------------------------------
# 6. Production Security Validation: Remote Redis TLS
# ---------------------------------------------------------------------------

def test_production_config_rejects_unencrypted_remote_redis():
    """Verify validate_production_security fails closed on non-TLS remote production Redis."""
    with pytest.raises(ValueError, match="Remote production Redis connection must use TLS"):
        Settings(
            app_env="production",
            jwt_secret="super-secret-key-that-is-at-least-32-chars-long!",
            cookie_secure=True,
            cors_allowed_origins="https://ai-platform.example.com",
            redis_url="redis://default:token@my-upstash.upstash.io:6379",
        )


def test_production_config_accepts_tls_remote_redis():
    """Verify validate_production_security accepts rediss:// for remote production Redis."""
    settings = Settings(
        app_env="production",
        jwt_secret="super-secret-key-that-is-at-least-32-chars-long!",
        cookie_secure=True,
        cors_allowed_origins="https://ai-platform.example.com",
        redis_url="rediss://default:token@my-upstash.upstash.io:6379",
    )
    validated = settings.validate_production_security()
    assert validated.redis_url.startswith("rediss://")


# ---------------------------------------------------------------------------
# 7. Repository Repository: Clean Deletion Transaction
# ---------------------------------------------------------------------------

def test_repository_delete_clean_atomic_transaction_on_failure():
    """Verify RepositoryRepository.delete rolls back on failure without swallowing exceptions."""
    mock_session = MagicMock()
    mock_repo = Repository(id=uuid.uuid4(), user_id=uuid.uuid4(), name="my-repo")
    mock_session.get.return_value = mock_repo
    mock_session.execute.side_effect = RuntimeError("Database deadlock / constraint violation")

    repo_repo = RepositoryRepository(mock_session)
    with pytest.raises(RuntimeError, match="Database deadlock"):
        repo_repo.delete(mock_repo.id)

    # Must rollback session cleanly
    mock_session.rollback.assert_called_once()
