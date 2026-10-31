"""
Sync Worker — Background consumption and execution of repository synchronization jobs.

Workflow:
1. Dequeue job payload from Redis `sync_jobs`.
2. Update SyncJob status to RUNNING.
3. Fetch GitHub installation credentials and shallow-clone the repository.
4. Scan repository files with `FileWalker` (respecting .gitignore and binary exclusion).
5. Incrementally chunk symbols and generate real 768-d Gemini vector embeddings.
6. Store vector chunks in pgvector and metadata in `repository_files`.
7. Clean up temporary clone directory.
8. Update SyncJob to COMPLETED and Repository to SYNCED.
"""

from __future__ import annotations

import asyncio
import json
import logging
import shutil
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import UUID

from redis.exceptions import TimeoutError as RedisTimeoutError
from sqlalchemy import select

from ai.embeddings.gemini_provider import GeminiEmbeddingProvider
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


async def process_sync_job(
    job_id: UUID,
    repository_id: UUID,
    user_id: UUID,
    github_service: Any = None,
) -> None:
    """Execute a single repository synchronization job end-to-end."""
    settings = get_settings()
    clone_dir: Path | None = None

    with SessionLocal() as db:
        repo: Repository | None = db.get(Repository, repository_id)
        job: SyncJob | None = db.get(SyncJob, job_id)
        if not repo or not job:
            logger.error("sync_job_missing_entities", extra={"job_id": str(job_id), "repo_id": str(repository_id)})
            return

        job.status = SyncJobStatus.RUNNING
        repo.sync_status = SyncStatus.SYNCING
        db.commit()

        installation = db.get(GitHubInstallation, repo.installation_id)
        if not installation:
            logger.error("sync_job_missing_installation", extra={"repo_id": str(repository_id)})
            job.status = SyncJobStatus.FAILED
            repo.sync_status = SyncStatus.FAILED
            db.commit()
            return

        installation_id = int(installation.installation_id)
        owner = repo.owner
        name = repo.name
        branch = repo.default_branch or "main"

    try:
        if github_service is None:
            raise RuntimeError("GitHubService is not initialized on app.state")

        # Create temporary workspace directory for shallow clone
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
            },
        )

        await github_service.clone_repository(
            installation_id=installation_id,
            owner=owner,
            repo=name,
            branch=branch,
            workspace_path=str(clone_dir),
        )

        # Walk repository files
        walker = FileWalker()
        scanned_files = walker.walk(str(clone_dir))
        logger.info(
            "sync_worker_files_scanned",
            extra={"repo_id": str(repository_id), "file_count": len(scanned_files)},
        )

        # Initialize real Gemini EmbeddingService (768-d)
        gemini_keys = settings.all_gemini_keys
        if not gemini_keys:
            raise ValueError("No GEMINI_API_KEYS configured for embeddings.")

        embedding_provider = GeminiEmbeddingProvider(
            api_keys=gemini_keys,
            dimensions=settings.embedding_dimensions,
            max_retries=max(len(gemini_keys) * 2, 6),
        )
        embedding_service = EmbeddingService(
            provider=embedding_provider,
            batch_size=30,
            max_concurrency=1,
        )

        # Run IncrementalIndexer
        indexer = IncrementalIndexer(
            db_session=AsyncSessionLocal,
            embedding_service=embedding_service,
        )

        try:
            stats = await indexer.sync(
                repository_id=repository_id,
                scanned_files=scanned_files,
                root_path=str(clone_dir),
            )
        finally:
            await embedding_service.aclose()

        # Mark completed
        with SessionLocal() as db:
            repo = db.get(Repository, repository_id)
            job = db.get(SyncJob, job_id)
            if repo and job:
                job.status = SyncJobStatus.COMPLETED
                repo.sync_status = SyncStatus.SYNCED
                repo.last_synced_at = datetime.now(timezone.utc)
                db.commit()

        # Notify connected frontend clients via Redis pub/sub
        try:
            redis: Any = await get_redis_async()
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
            },
        )

    except Exception as exc:
        logger.exception("sync_worker_job_failed", extra={"job_id": str(job_id), "error": str(exc)})
        with SessionLocal() as db:
            repo = db.get(Repository, repository_id)
            job = db.get(SyncJob, job_id)
            if repo and job:
                job.status = SyncJobStatus.FAILED
                repo.sync_status = SyncStatus.FAILED
                db.commit()

        try:
            redis: Any = await get_redis_async()
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

    finally:
        if clone_dir and clone_dir.exists():
            shutil.rmtree(clone_dir, ignore_errors=True)


async def recover_stale_processing_jobs(redis: Any, timeout_seconds: int = 600) -> list[str]:
    """Recover items stuck in `sync_jobs:processing` that exceeded timeout_seconds."""
    recovered: list[str] = []
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

                    if age >= timeout_seconds:
                        logger.warning(
                            "recovering_stalled_processing_sync_job",
                            extra={"job_id": str(job_id), "age_seconds": round(age, 1)},
                        )
                        if hasattr(redis, "lrem"):
                            await redis.lrem("sync_jobs:processing", 1, raw_item)
                        if hasattr(redis, "rpush"):
                            await redis.rpush("sync_jobs", decoded)
                        recovered.append(str(job_id))
                except Exception as parse_err:
                    logger.warning("stale_processing_job_parse_error", extra={"error": str(parse_err)})
                    if hasattr(redis, "lrem"):
                        await redis.lrem("sync_jobs:processing", 1, raw_item)
    except Exception as exc:
        logger.warning("recover_stale_processing_jobs_error", extra={"error": str(exc)})
    return recovered


async def sync_worker_loop(app_or_service: Any = None) -> None:
    """Continuously poll Redis `sync_jobs` queue and process sync jobs asynchronously."""
    logger.info("sync_worker_loop_started")
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
            gh_service = GitHubService(redis=redis, settings=get_settings())
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
                    }
                    await redis.rpush("sync_jobs", json.dumps(p_load))
                    logger.info("re_enqueued_pending_sync_job_at_startup", extra={"job_id": str(pj.id), "repo_id": str(p_repo.id)})
    except Exception as init_err:
        logger.warning("sync_worker_init_recovery_warning", extra={"error": str(init_err)})

    while True:
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

            # Dequeue with reliable queue hand-off
            raw_data = None
            try:
                if hasattr(redis, "brpoplpush"):
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
                # Idle polling timeout with no jobs is normal; proceed cleanly
                raw_data = None
            except Exception:
                # Fallback for Redis providers (like Upstash) where BRPOPLPUSH may be disallowed
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
                try:
                    payload = json.loads(decoded)
                    job_id = UUID(payload["job_id"])
                    repo_id = UUID(payload["repository_id"])
                    user_id = UUID(payload["user_id"])

                    logger.info("sync_worker_dequeued_job", extra={"job_id": str(job_id), "repo_id": str(repo_id)})
                    await process_sync_job(job_id, repo_id, user_id, gh_service)
                finally:
                    # Acknowledge completion or handled failure by removing from processing list
                    if hasattr(redis, "lrem"):
                        try:
                            await redis.lrem("sync_jobs:processing", 1, raw_data)
                        except Exception as lrem_exc:
                            logger.warning("sync_worker_ack_lrem_warning", extra={"error": str(lrem_exc)})
            else:
                await asyncio.sleep(0.5)

        except asyncio.CancelledError:
            logger.info("sync_worker_loop_cancelled")
            break
        except Exception as exc:
            logger.warning("sync_worker_loop_error: %s", exc, exc_info=True, extra={"error": str(exc)})
            await asyncio.sleep(2.0)
