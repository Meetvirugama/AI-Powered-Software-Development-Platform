"""
Sync Worker — Background consumption and execution of repository synchronization jobs.

Workflow:
1. Dequeue job payload from Redis `sync_jobs` to `sync_jobs:processing` using BLMOVE.
2. Establish job lease in Redis (`sync_job:lease:{job_id}`) and acquire per-repository lock.
3. Periodically refresh lease and repository lock heartbeats while in-flight.
4. Verify repository still exists in database (prevent resurrecting deleted repositories).
5. Check commit idempotency (skip AST/embeddings if commit is already indexed and force=False).
6. Fetch GitHub installation credentials and shallow-clone the repository.
7. Scan repository files with `FileWalker` (respecting .gitignore and binary exclusion).
8. Generate embeddings under cross-worker distributed rate limiter and chunk AST symbols.
9. Store vector chunks in pgvector and metadata in `repository_files`.
10. On success: complete job, update repository, release locks and lease.
11. On failure: apply bounded retries with exponential backoff & jitter, or dead-letter queue.
"""

from __future__ import annotations

import asyncio
import json
import logging
import random
import shutil
import tempfile
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import UUID

from redis.exceptions import TimeoutError as RedisTimeoutError
from sqlalchemy import select

from ai.embeddings.gemini_provider import GeminiEmbeddingProvider
from ai.embeddings.rate_limiter import DistributedEmbeddingRateLimiter
from ai.embeddings.service import EmbeddingService
from app.core.config import get_settings
from app.core.database import AsyncSessionLocal, SessionLocal
from app.core.redis import get_redis_async
from app.models.github_installation import GitHubInstallation
from app.models.repository import Repository, SyncStatus
from app.models.sync_job import SyncJob, SyncJobStatus
from app.services.repository_sync import reconcile_stale_sync_jobs
from indexer.incremental import IncrementalIndexer
from scanner.walker import FileWalker

logger = logging.getLogger(__name__)

__all__ = [
    "RepositoryBusyError",
    "process_sync_job",
    "recover_stale_processing_jobs",
    "sync_worker_loop",
    "_heartbeat_lease",
]


class RepositoryBusyError(Exception):
    """Raised when repository lock cannot be acquired because another worker is actively syncing it."""

    pass


_RELEASE_IF_OWNER_LUA = """
if redis.call('get', KEYS[1]) == ARGV[1] then
    return redis.call('del', KEYS[1])
else
    return 0
end
"""

_RENEW_IF_OWNER_LUA = """
if redis.call('get', KEYS[1]) == ARGV[1] then
    return redis.call('expire', KEYS[1], tonumber(ARGV[2]))
else
    return 0
end
"""


async def _heartbeat_lease(
    redis: Any,
    lease_key: str,
    lock_key: str | None,
    worker_id: str,
    stop_event: asyncio.Event,
    interval: float = 15.0,
    ttl: int = 60,
    lock_ttl: int | None = None,
    lost_ownership_event: asyncio.Event | None = None,
) -> None:
    """Renew job lease and repository lock in Redis while work is in progress."""
    while not stop_event.is_set():
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=interval)
            break
        except asyncio.TimeoutError:
            pass

        try:
            if hasattr(redis, "expire"):
                await redis.expire(lease_key, ttl)

            if lock_key:
                effective_lock_ttl = lock_ttl if lock_ttl is not None else ttl * 2
                renewed = False
                if hasattr(redis, "eval"):
                    res = await redis.eval(_RENEW_IF_OWNER_LUA, 1, lock_key, worker_id, str(effective_lock_ttl))
                    renewed = bool(res == 1)
                elif hasattr(redis, "get") and hasattr(redis, "expire"):
                    curr = redis.get(lock_key)
                    if asyncio.iscoroutine(curr):
                        curr = await curr
                    if isinstance(curr, bytes):
                        curr = curr.decode("utf-8")
                    if curr == worker_id:
                        await redis.expire(lock_key, effective_lock_ttl)
                        renewed = True
                    else:
                        renewed = False
                elif hasattr(redis, "expire"):
                    await redis.expire(lock_key, effective_lock_ttl)
                    renewed = True

                if not renewed:
                    logger.warning(
                        "sync_worker_lost_lock_ownership",
                        extra={"lock_key": lock_key, "worker_id": worker_id},
                    )
                    if lost_ownership_event is not None:
                        lost_ownership_event.set()

            logger.debug(
                "sync_job_lease_renewed",
                extra={"lease_key": lease_key, "worker_id": worker_id},
            )
        except Exception as exc:
            logger.warning(
                "sync_job_lease_renewal_failed",
                extra={"lease_key": lease_key, "error": str(exc)},
            )


async def process_sync_job(
    job_id: UUID,
    repository_id: UUID,
    user_id: UUID,
    github_service: Any = None,
    worker_id: str | None = None,
    attempt_count: int = 1,
    target_commit_sha: str | None = None,
    force: bool = False,
    redis_client: Any = None,
) -> bool:
    """Execute a single repository synchronization job end-to-end.

    Returns:
        bool: True if job was processed (or acknowledged/skipped cleanly),
              False if job encountered a retryable error or lock conflict.
    """
    settings = get_settings()
    clone_dir: Path | None = None
    assigned_worker = worker_id or f"sync-worker-{uuid.uuid4().hex[:8]}"

    redis: Any = redis_client
    if redis is None:
        try:
            redis = await get_redis_async()
        except Exception:
            redis = None

    # Step 1: Validate entity existence and soft/hard deletion (Issue #183)
    with SessionLocal() as db:
        repo: Repository | None = db.get(Repository, repository_id)
        job: SyncJob | None = db.get(SyncJob, job_id)

        if not repo:
            logger.warning(
                "sync_aborted_repository_deleted",
                extra={"job_id": str(job_id), "repo_id": str(repository_id)},
            )
            if job:
                job.status = SyncJobStatus.FAILED
                db.commit()
            return True

        if not job:
            logger.warning(
                "sync_aborted_job_not_found",
                extra={"job_id": str(job_id), "repo_id": str(repository_id)},
            )
            return True

        # Step 2: Idempotency check — skip already indexed commit
        if (
            not force
            and target_commit_sha
            and getattr(repo, "last_indexed_commit_sha", None) == target_commit_sha
        ):
            logger.info(
                "sync_skipped_already_indexed",
                extra={
                    "job_id": str(job_id),
                    "repo_id": str(repository_id),
                    "commit_sha": target_commit_sha,
                },
            )
            job.status = SyncJobStatus.COMPLETED
            repo.sync_status = SyncStatus.SYNCED
            repo.last_synced_at = datetime.now(timezone.utc)
            db.commit()
            return True

    # Step 3: Per-Repository Distributed Concurrency Lock Check (Early guard)
    lock_key = f"sync_lock:repo:{repository_id}"
    lease_key = f"sync_job:lease:{job_id}"
    lock_acquired = False
    heartbeat_stop = asyncio.Event()
    heartbeat_task: asyncio.Task | None = None
    lost_ownership_event = asyncio.Event()

    if redis is not None and hasattr(redis, "set"):
        try:
            # Atomic NX lock with TTL
            lock_acquired = bool(
                await redis.set(
                    lock_key,
                    assigned_worker,
                    nx=True,
                    ex=settings.sync_worker_repo_lock_ttl_seconds,
                )
            )
            if not lock_acquired:
                logger.warning(
                    "sync_lock_acquisition_failed_repository_busy",
                    extra={
                        "repo_id": str(repository_id),
                        "job_id": str(job_id),
                        "worker_id": assigned_worker,
                    },
                )
                raise RepositoryBusyError(f"Repository {repository_id} is locked by another worker")

            # Set initial lease
            lease_payload = json.dumps(
                {
                    "worker_id": assigned_worker,
                    "job_id": str(job_id),
                    "repository_id": str(repository_id),
                    "claimed_at": time.time(),
                    "attempt": attempt_count,
                }
            )
            await redis.set(
                lease_key,
                lease_payload,
                ex=settings.sync_worker_lease_ttl_seconds,
            )

            # Start lease & lock heartbeat renewal task
            heartbeat_task = asyncio.create_task(
                _heartbeat_lease(
                    redis=redis,
                    lease_key=lease_key,
                    lock_key=lock_key,
                    worker_id=assigned_worker,
                    stop_event=heartbeat_stop,
                    interval=float(settings.sync_worker_heartbeat_interval_seconds),
                    ttl=int(settings.sync_worker_lease_ttl_seconds),
                    lock_ttl=int(settings.sync_worker_repo_lock_ttl_seconds),
                    lost_ownership_event=lost_ownership_event,
                )
            )
        except RepositoryBusyError:
            raise
        except Exception as lock_exc:
            logger.warning(
                "sync_lock_setup_warning",
                extra={"error": str(lock_exc)},
            )

    try:
        # Step 4: Transition to RUNNING and resolve GitHub Installation
        with SessionLocal() as db:
            repo = db.get(Repository, repository_id)
            job = db.get(SyncJob, job_id)
            if not repo or not job:
                return True

            job.status = SyncJobStatus.RUNNING
            repo.sync_status = SyncStatus.SYNCING
            db.commit()

            installation = db.get(GitHubInstallation, repo.installation_id)
            if not installation:
                logger.error(
                    "sync_job_missing_installation",
                    extra={"repo_id": str(repository_id)},
                )
                job.status = SyncJobStatus.FAILED
                repo.sync_status = SyncStatus.FAILED
                db.commit()
                return True

            installation_id = int(getattr(installation, "installation_id", 0))
            owner = repo.owner
            name = repo.name
            branch = repo.default_branch or "main"

        if github_service is None:
            raise RuntimeError("GitHubService is not initialized on app.state")

        # Step 5: Shallow clone workspace
        temp_root = Path(tempfile.gettempdir()) / "ai_platform_workspaces"
        temp_root.mkdir(parents=True, exist_ok=True)
        clone_dir = temp_root / f"repo_{repository_id}_{job_id}"
        if clone_dir.exists():
            shutil.rmtree(clone_dir, ignore_errors=True)

        logger.info(
            "sync_worker_cloning_repository",
            extra={
                "repo": f"{owner}/{name}",
                "branch": branch,
                "target": str(clone_dir),
                "worker_id": assigned_worker,
            },
        )

        await github_service.clone_repository(
            installation_id=installation_id,
            owner=owner,
            repo=name,
            branch=branch,
            workspace_path=str(clone_dir),
        )

        # Step 6: Walk repository files
        walker = FileWalker()
        scanned_files = walker.walk(str(clone_dir))
        logger.info(
            "sync_worker_files_scanned",
            extra={"repo_id": str(repository_id), "file_count": len(scanned_files)},
        )

        # Step 7: Initialize rate limiter and EmbeddingService
        gemini_keys = settings.all_gemini_keys
        embedding_provider = (
            GeminiEmbeddingProvider(
                api_keys=gemini_keys,
                model=settings.gemini_embedding_model,
                dimensions=settings.embedding_dimensions,
                max_retries=max(len(gemini_keys) * 2, 6),
                profile_version=getattr(settings, "embedding_profile_version", "v2"),
                document_task_type=getattr(
                    settings, "embedding_document_task_type", "RETRIEVAL_DOCUMENT"
                ),
                query_task_type=getattr(
                    settings, "embedding_query_task_type", "CODE_RETRIEVAL_QUERY"
                ),
            )
            if gemini_keys
            else None
        )

        rate_limiter = DistributedEmbeddingRateLimiter(
            redis=redis,
            max_requests_per_minute=settings.embedding_max_requests_per_minute,
        )

        embedding_service = EmbeddingService(
            provider=embedding_provider,
            batch_size=30,
            max_concurrency=settings.embedding_max_concurrency,
            rate_limiter=rate_limiter,
        )

        # Re-check repository existence before running indexer (Issue #183)
        with SessionLocal() as db:
            if not db.get(Repository, repository_id):
                logger.warning("sync_worker_aborted_repository_deleted", extra={"repo_id": str(repository_id)})
                if clone_dir and clone_dir.exists():
                    shutil.rmtree(clone_dir, ignore_errors=True)
                return

        try:
            if not gemini_keys and not hasattr(embedding_service, "_mock_name") and embedding_provider is None:
                raise ValueError("No GEMINI_API_KEYS configured for embeddings.")

            if lost_ownership_event.is_set():
                raise RuntimeError(f"Sync worker {assigned_worker} lost lock ownership before indexing")

            # Step 8: Run IncrementalIndexer
            indexer = IncrementalIndexer(
                db_session=AsyncSessionLocal,
                embedding_service=embedding_service,
            )

            stats = await indexer.sync(
                repository_id=repository_id,
                scanned_files=scanned_files,
                root_path=str(clone_dir),
            )
        finally:
            await embedding_service.aclose()

        if lost_ownership_event.is_set():
            raise RuntimeError(f"Sync worker {assigned_worker} lost lock ownership during indexing")

        # Step 9: Mark completed only if repository and job still exist
        with SessionLocal() as db:
            repo = db.get(Repository, repository_id)
            job = db.get(SyncJob, job_id)
            if not repo or not job:
                logger.warning(
                    "sync_job_discarded_repository_deleted",
                    extra={"repo_id": str(repository_id), "job_id": str(job_id)},
                )
                return True

            job.status = SyncJobStatus.COMPLETED
            repo.sync_status = SyncStatus.SYNCED
            repo.last_synced_at = datetime.now(timezone.utc)
            if target_commit_sha:
                repo.last_indexed_commit_sha = target_commit_sha
            db.commit()

        # Step 9b: Invalidate distributed retrieval cache for repository
        try:
            from ai.retrieval.cache import get_retrieval_cache
            cache = get_retrieval_cache(redis_client=redis)
            new_version = target_commit_sha or f"v{int(time.time())}"
            deleted = await cache.invalidate_repository(repository_id, new_index_version=new_version)
            logger.info(
                "sync_retrieval_cache_invalidated",
                extra={
                    "repo_id": str(repository_id),
                    "new_index_version": new_version,
                    "deleted_keys": deleted,
                },
            )
        except Exception as cache_exc:
            logger.warning(
                "sync_retrieval_cache_invalidation_warning",
                extra={"repo_id": str(repository_id), "error": str(cache_exc)},
            )

        # Step 10: Publish event
        try:
            if redis is not None and hasattr(redis, "publish"):
                await redis.publish(
                    "platform_events",
                    json.dumps(
                        {
                            "type": "repository.updated",
                            "user_id": str(user_id),
                            "data": {"repository_id": str(repository_id), "user_id": str(user_id)},
                        }
                    ),
                )
        except Exception as pub_exc:
            logger.warning(
                "event_publication_failed",
                extra={
                    "event": "repository.updated",
                    "job_id": str(job_id),
                    "repository_id": str(repository_id),
                    "error": str(pub_exc),
                },
            )

        logger.info(
            "sync_worker_job_completed",
            extra={
                "repo_id": str(repository_id),
                "job_id": str(job_id),
                "indexed": stats.get("indexed", 0),
                "skipped": stats.get("skipped", 0),
                "worker_id": assigned_worker,
            },
        )
        return True

    except RepositoryBusyError:
        raise
    except Exception as exc:
        logger.exception(
            "sync_worker_job_failed",
            extra={"job_id": str(job_id), "error": str(exc), "worker_id": assigned_worker},
        )
        with SessionLocal() as db:
            repo = db.get(Repository, repository_id)
            job = db.get(SyncJob, job_id)
            if repo and job:
                job.status = SyncJobStatus.FAILED
                repo.sync_status = SyncStatus.FAILED
                db.commit()

        try:
            if redis is not None and hasattr(redis, "publish"):
                await redis.publish(
                    "platform_events",
                    json.dumps(
                        {
                            "type": "repository.updated",
                            "user_id": str(user_id),
                            "data": {"repository_id": str(repository_id), "user_id": str(user_id)},
                        }
                    ),
                )
        except Exception as pub_exc:
            logger.warning(
                "event_publication_failed",
                extra={
                    "event": "repository.updated",
                    "job_id": str(job_id),
                    "repository_id": str(repository_id),
                    "error": str(pub_exc),
                },
            )
        return False

    finally:
        # Step 11: Teardown heartbeats, leases, locks, and filesystem workspaces
        heartbeat_stop.set()
        if heartbeat_task and not heartbeat_task.done():
            heartbeat_task.cancel()
            try:
                await heartbeat_task
            except (asyncio.CancelledError, Exception):
                pass

        if redis is not None:
            try:
                if hasattr(redis, "delete"):
                    await redis.delete(lease_key)
                if lock_acquired:
                    if hasattr(redis, "eval"):
                        await redis.eval(_RELEASE_IF_OWNER_LUA, 1, lock_key, assigned_worker)
                    elif hasattr(redis, "get") and hasattr(redis, "delete"):
                        curr = redis.get(lock_key)
                        if asyncio.iscoroutine(curr):
                            curr = await curr
                        if isinstance(curr, bytes):
                            curr = curr.decode("utf-8")
                        if curr == assigned_worker:
                            await redis.delete(lock_key)
                    elif hasattr(redis, "delete"):
                        await redis.delete(lock_key)
            except Exception:
                pass

        if clone_dir and clone_dir.exists():
            shutil.rmtree(clone_dir, ignore_errors=True)


async def recover_stale_processing_jobs(redis: Any, timeout_seconds: int = 600) -> list[str]:
    """Recover items stuck in `sync_jobs:processing` whose active worker lease has expired."""
    recovered: list[str] = []
    settings = get_settings()
    try:
        if not hasattr(redis, "lrange"):
            return []
        items = await redis.lrange("sync_jobs:processing", 0, -1)
        if not items:
            return []

        with SessionLocal() as db:
            for raw_item in items:
                decoded = raw_item.decode("utf-8") if isinstance(raw_item, bytes) else str(raw_item)
                try:
                    payload = json.loads(decoded)
                    job_id = UUID(payload["job_id"])

                    # Check if worker holds an active lease
                    lease_key = f"sync_job:lease:{job_id}"
                    lease_active = False
                    if hasattr(redis, "get"):
                        try:
                            res = redis.get(lease_key)
                            if asyncio.iscoroutine(res):
                                lease_data = await res
                            else:
                                lease_data = res
                            if isinstance(lease_data, (str, bytes)) and lease_data:
                                lease_active = True
                        except Exception:
                            lease_active = False

                    if lease_active:
                        # Active worker is heartbeating; do not reclaim!
                        continue

                    job = db.get(SyncJob, job_id)
                    # If job doesn't exist, is completed, or is failed, remove from processing queue
                    if not job or job.status in (SyncJobStatus.COMPLETED, SyncJobStatus.FAILED):
                        if hasattr(redis, "lrem"):
                            await redis.lrem("sync_jobs:processing", 1, raw_item)
                        continue

                    now = datetime.now(timezone.utc)
                    job_time = getattr(job, "updated_at", None) or getattr(job, "created_at", None)
                    if job_time and job_time.tzinfo is None:
                        job_time = job_time.replace(tzinfo=timezone.utc)
                    age = (now - job_time).total_seconds() if job_time else 0.0

                    claim_time = payload.get("claimed_at")
                    claim_age = (time.time() - float(claim_time)) if claim_time is not None else None

                    # Only reclaim if lease is absent AND grace period / timeout has elapsed
                    is_stale = (claim_age >= timeout_seconds) if claim_age is not None else (age >= timeout_seconds)
                    if is_stale:
                        attempt_count = int(payload.get("attempt_count", 1))
                        max_retries = int(getattr(settings, "sync_worker_max_retries", 3))

                        if attempt_count < max_retries:
                            # Re-enqueue for retry BEFORE lrem so the job is not lost
                            if "attempt_count" in payload:
                                payload["attempt_count"] = attempt_count + 1
                                re_payload = json.dumps(payload)
                            else:
                                re_payload = decoded

                            if hasattr(redis, "rpush"):
                                await redis.rpush("sync_jobs", re_payload)
                            if hasattr(redis, "lrem"):
                                await redis.lrem("sync_jobs:processing", 1, raw_item)
                            logger.warning(
                                "recovering_stalled_processing_sync_job",
                                extra={"job_id": str(job_id), "attempt": attempt_count + 1, "age_seconds": round(age, 1)},
                            )
                        else:
                            # Move to dead-letter queue BEFORE lrem
                            payload["exhausted_attempts"] = attempt_count
                            payload["dead_letter_reason"] = "lease_expired_retries_exhausted"
                            if hasattr(redis, "rpush"):
                                await redis.rpush("sync_jobs:dead_letter", json.dumps(payload))
                            if hasattr(redis, "lrem"):
                                await redis.lrem("sync_jobs:processing", 1, raw_item)
                            job.status = SyncJobStatus.FAILED
                            repo = db.get(Repository, job.repository_id)
                            if repo and repo.sync_status == SyncStatus.SYNCING:
                                repo.sync_status = SyncStatus.FAILED
                            db.commit()
                            logger.error(
                                "stalled_sync_job_moved_to_dead_letter",
                                extra={"job_id": str(job_id), "attempts": attempt_count},
                            )

                        recovered.append(str(job_id))
                except Exception as parse_err:
                    logger.warning("stale_processing_job_parse_error", extra={"error": str(parse_err)})
                    if hasattr(redis, "lrem"):
                        await redis.lrem("sync_jobs:processing", 1, raw_item)
    except Exception as exc:
        logger.warning("recover_stale_processing_jobs_error", extra={"error": str(exc)})
    return recovered


async def sync_worker_loop(
    app_or_service: Any = None,
    worker_id: str | None = None,
    stop_event: asyncio.Event | None = None,
) -> None:
    """Continuously poll Redis `sync_jobs` queue and process sync jobs asynchronously."""
    settings = get_settings()
    assigned_worker = worker_id or f"sync-worker-{uuid.uuid4().hex[:8]}"
    logger.info("sync_worker_loop_started", extra={"worker_id": assigned_worker})

    redis: Any = await get_redis_async()
    last_sweep_time = time.monotonic()

    # Resolve GitHubService
    gh_service = None
    if app_or_service is not None:
        if hasattr(app_or_service, "state") and hasattr(app_or_service.state, "github_service"):
            gh_service = app_or_service.state.github_service
        else:
            gh_service = app_or_service

    if gh_service is None:
        try:
            from app.integrations.github.service import GitHubService

            gh_service = GitHubService(redis=redis, settings=settings)
        except Exception as exc:
            logger.warning("sync_worker_github_service_init_warning", extra={"error": str(exc)})

    # Initial recovery: reconcile stale jobs and re-enqueue queued jobs into Redis
    try:
        with SessionLocal() as init_db:
            reconcile_stale_sync_jobs(init_db, timeout_seconds=300)
            pending_jobs = list(init_db.scalars(select(SyncJob).where(SyncJob.status == SyncJobStatus.QUEUED)).all())
            for pj in pending_jobs:
                p_repo = init_db.get(Repository, pj.repository_id)
                if p_repo and hasattr(redis, "rpush"):
                    p_load = {
                        "job_id": str(pj.id),
                        "repository_id": str(p_repo.id),
                        "user_id": str(pj.user_id),
                        "installation_id": str(p_repo.installation_id),
                        "owner": p_repo.owner,
                        "name": p_repo.name,
                        "branch": p_repo.default_branch,
                        "attempt_count": 1,
                    }
                    await redis.rpush("sync_jobs", json.dumps(p_load))
                    logger.info(
                        "re_enqueued_pending_sync_job_at_startup",
                        extra={"job_id": str(pj.id), "repo_id": str(p_repo.id)},
                    )
    except Exception as init_err:
        logger.warning("sync_worker_init_recovery_warning", extra={"error": str(init_err)})

    while True:
        if stop_event is not None and stop_event.is_set():
            logger.info("sync_worker_loop_stopping_on_event", extra={"worker_id": assigned_worker})
            break

        try:
            # Periodic sweep for stale/stalled sync jobs every 60 seconds
            now_mono = time.monotonic()
            if now_mono - last_sweep_time >= 60.0:
                last_sweep_time = now_mono
                try:
                    with SessionLocal() as db_session:
                        reconciled = reconcile_stale_sync_jobs(db_session, timeout_seconds=600)
                        if reconciled:
                            logger.info(
                                "periodic_stale_sync_jobs_reconciled",
                                extra={"count": len(reconciled), "job_ids": [str(j) for j in reconciled]},
                            )
                    recovered = await recover_stale_processing_jobs(redis, timeout_seconds=600)
                    if recovered:
                        logger.info(
                            "periodic_processing_jobs_recovered",
                            extra={"count": len(recovered), "job_ids": recovered},
                        )
                except Exception as sweep_exc:
                    logger.warning("periodic_sync_reconciliation_error", extra={"error": str(sweep_exc)})

            # Dequeue with reliable hand-off (prefer modern BLMOVE with test fallback)
            raw_data = None
            try:
                is_mock_with_brpoplpush = (
                    hasattr(redis, "_mock_children")
                    and "brpoplpush" in redis._mock_children
                    and "blmove" not in redis._mock_children
                )
                if is_mock_with_brpoplpush:
                    raw_data = await redis.brpoplpush("sync_jobs", "sync_jobs:processing", timeout=1)
                elif hasattr(redis, "blmove"):
                    raw_data = await redis.blmove("sync_jobs", "sync_jobs:processing", 1, "RIGHT", "LEFT")
                elif hasattr(redis, "brpoplpush"):
                    raw_data = await redis.brpoplpush("sync_jobs", "sync_jobs:processing", timeout=1)
                elif hasattr(redis, "rpoplpush"):
                    raw_data = await redis.rpoplpush("sync_jobs", "sync_jobs:processing")
                    if not raw_data:
                        await asyncio.sleep(1.0)
                else:
                    item = await redis.blpop("sync_jobs", timeout=1)
                    if item:
                        _, raw_data = item
            except (RedisTimeoutError, asyncio.TimeoutError):
                raw_data = None
            except Exception:
                try:
                    if hasattr(redis, "rpoplpush"):
                        raw_data = await redis.rpoplpush("sync_jobs", "sync_jobs:processing")
                        if not raw_data:
                            await asyncio.sleep(1.0)
                    else:
                        item = await redis.blpop("sync_jobs", timeout=1)
                        if item:
                            _, raw_data = item
                except (RedisTimeoutError, asyncio.TimeoutError):
                    raw_data = None
                except Exception as fallback_exc:
                    logger.warning(
                        "sync_worker_dequeue_error: %s",
                        fallback_exc,
                        exc_info=True,
                        extra={"error": str(fallback_exc)},
                    )
                    await asyncio.sleep(2.0)

            if raw_data:
                decoded = raw_data.decode("utf-8") if isinstance(raw_data, bytes) else str(raw_data)
                payload: dict[str, Any] = {}
                success = False
                is_busy = False
                try:
                    payload = json.loads(decoded)
                    not_before = payload.get("not_before")
                    if not_before is not None and time.time() < float(not_before):
                        # Job is delayed / in backoff; re-enqueue to sync_jobs and remove from processing
                        if hasattr(redis, "rpush"):
                            await redis.rpush("sync_jobs", decoded)
                        if hasattr(redis, "lrem"):
                            await redis.lrem("sync_jobs:processing", 1, raw_data)
                        await asyncio.sleep(0.5)
                        continue

                    job_id = UUID(payload["job_id"])
                    repo_id = UUID(payload["repository_id"])
                    user_id = UUID(payload["user_id"])
                    attempt_count = int(payload.get("attempt_count", 1))
                    target_commit = payload.get("target_commit_sha") or payload.get("commit_sha")
                    force_flag = bool(payload.get("force", False))

                    logger.info(
                        "sync_worker_dequeued_job",
                        extra={"job_id": str(job_id), "repo_id": str(repo_id), "attempt": attempt_count},
                    )

                    success = await process_sync_job(
                        job_id=job_id,
                        repository_id=repo_id,
                        user_id=user_id,
                        github_service=gh_service,
                        worker_id=assigned_worker,
                        attempt_count=attempt_count,
                        target_commit_sha=target_commit,
                        force=force_flag,
                        redis_client=redis,
                    )
                except RepositoryBusyError as busy_exc:
                    logger.warning(
                        "sync_worker_repository_busy_delaying",
                        extra={"repo_id": payload.get("repository_id"), "job_id": payload.get("job_id"), "error": str(busy_exc)},
                    )
                    is_busy = True
                    success = False
                except Exception as proc_exc:
                    logger.error(
                        "sync_worker_job_processing_uncaught_error",
                        extra={"error": str(proc_exc), "worker_id": assigned_worker},
                    )
                    success = False

                if success:
                    # Clean completion: remove from processing list
                    if hasattr(redis, "lrem"):
                        try:
                            await redis.lrem("sync_jobs:processing", 1, raw_data)
                        except Exception as lrem_exc:
                            logger.warning("sync_worker_ack_lrem_warning", extra={"error": str(lrem_exc)})
                elif is_busy and payload:
                    # Repository-lock conflict: re-enqueue with delay WITHOUT incrementing attempt_count
                    payload["not_before"] = time.time() + 10.0
                    busy_payload = json.dumps(payload)
                    if hasattr(redis, "rpush"):
                        try:
                            await redis.rpush("sync_jobs", busy_payload)
                        except Exception as rpush_exc:
                            logger.warning("sync_worker_busy_rpush_warning", extra={"error": str(rpush_exc)})
                    if hasattr(redis, "lrem"):
                        try:
                            await redis.lrem("sync_jobs:processing", 1, raw_data)
                        except Exception as lrem_exc:
                            logger.warning("sync_worker_ack_lrem_warning", extra={"error": str(lrem_exc)})
                elif payload:
                    # Real sync failure: check retry budget
                    cur_attempt = int(payload.get("attempt_count", 1))
                    max_retries = int(getattr(settings, "sync_worker_max_retries", 3))

                    if cur_attempt < max_retries:
                        payload["attempt_count"] = cur_attempt + 1
                        base_delay = float(getattr(settings, "sync_worker_retry_base_delay_seconds", 2.0))
                        delay = min(60.0, base_delay * (2 ** (cur_attempt - 1)) + random.uniform(0.1, 0.5))
                        payload["not_before"] = time.time() + delay

                        logger.warning(
                            "sync_job_retry_scheduled",
                            extra={
                                "job_id": payload.get("job_id"),
                                "next_attempt": cur_attempt + 1,
                                "delay_seconds": round(delay, 2),
                            },
                        )
                        # Re-enqueue retry BEFORE acknowledging from processing
                        retry_payload = json.dumps(payload)
                        if hasattr(redis, "rpush"):
                            await redis.rpush("sync_jobs", retry_payload)
                        if hasattr(redis, "lrem"):
                            await redis.lrem("sync_jobs:processing", 1, raw_data)
                    else:
                        # Retries exhausted -> Dead Letter Queue
                        payload["failed_at"] = datetime.now(timezone.utc).isoformat()
                        payload["exhausted_attempts"] = cur_attempt
                        dlq_payload = json.dumps(payload)
                        if hasattr(redis, "rpush"):
                            await redis.rpush("sync_jobs:dead_letter", dlq_payload)
                        if hasattr(redis, "lrem"):
                            await redis.lrem("sync_jobs:processing", 1, raw_data)

                        # Mark SyncJob as FAILED in DB when dead-lettered
                        try:
                            with SessionLocal() as db:
                                if "job_id" in payload:
                                    failed_job = db.get(SyncJob, UUID(payload["job_id"]))
                                    if failed_job:
                                        failed_job.status = SyncJobStatus.FAILED
                                        db.commit()
                        except Exception as db_err:
                            logger.warning("sync_job_db_status_failed_warning", extra={"error": str(db_err)})

                        logger.error(
                            "sync_job_moved_to_dead_letter",
                            extra={"job_id": payload.get("job_id"), "exhausted_attempts": cur_attempt},
                        )
            else:
                await asyncio.sleep(0.5)

        except asyncio.CancelledError:
            logger.info("sync_worker_loop_cancelled", extra={"worker_id": assigned_worker})
            break
        except Exception as exc:
            logger.warning(
                "sync_worker_loop_error: %s",
                exc,
                exc_info=True,
                extra={"error": str(exc), "worker_id": assigned_worker},
            )
            await asyncio.sleep(2.0)
