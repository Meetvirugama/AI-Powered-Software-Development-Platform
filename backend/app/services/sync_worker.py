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
import os
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import UUID

from ai.embeddings.gemini_provider import GeminiEmbeddingProvider
from ai.embeddings.service import EmbeddingService
from app.core.config import get_settings
from app.core.database import AsyncSessionLocal, SessionLocal
from app.core.redis import get_redis_async
from app.models.github_installation import GitHubInstallation
from app.models.repository import Repository, SyncStatus
from app.models.sync_job import SyncJob, SyncJobStatus
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
        )
        embedding_service = EmbeddingService(
            provider=embedding_provider,
            batch_size=50,
            max_concurrency=4,
        )

        # Run IncrementalIndexer
        indexer = IncrementalIndexer(
            db_session=AsyncSessionLocal,
            embedding_service=embedding_service,
        )

        stats = await indexer.sync(
            repository_id=repository_id,
            scanned_files=scanned_files,
            root_path=str(clone_dir),
        )

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

    finally:
        if clone_dir and clone_dir.exists():
            shutil.rmtree(clone_dir, ignore_errors=True)


async def sync_worker_loop(app: Any) -> None:
    """Continuously poll Redis `sync_jobs` queue and process sync jobs asynchronously."""
    logger.info("sync_worker_loop_started")
    redis = await get_redis_async()

    while True:
        try:
            # Pop job from Redis queue with 2 second timeout
            item = await redis.blpop("sync_jobs", timeout=2)
            if item:
                _, raw_data = item
                if isinstance(raw_data, bytes):
                    raw_data = raw_data.decode("utf-8")
                payload = json.loads(raw_data)
                job_id = UUID(payload["job_id"])
                repo_id = UUID(payload["repository_id"])
                user_id = UUID(payload["user_id"])
                gh_service = getattr(app.state, "github_service", None)

                logger.info("sync_worker_dequeued_job", extra={"job_id": str(job_id), "repo_id": str(repo_id)})
                await process_sync_job(job_id, repo_id, user_id, gh_service)

        except asyncio.CancelledError:
            logger.info("sync_worker_loop_cancelled")
            break
        except Exception as exc:
            logger.warning("sync_worker_loop_error", extra={"error": str(exc)})
            await asyncio.sleep(2)
