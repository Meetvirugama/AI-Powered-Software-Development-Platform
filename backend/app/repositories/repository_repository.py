import logging
import os
import shutil
import tempfile
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, List, Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.repository import Repository, SyncStatus
from app.models.repository_file import RepositoryFile
from app.models.code_symbol import CodeSymbol
from app.models.sync_job import SyncJob, SyncJobStatus

logger = logging.getLogger(__name__)


class RepositoryRepository:
    def __init__(self, session: Session):
        self.session = session

    def create(self, user_id: uuid.UUID, installation_id: uuid.UUID, github_repo_id: str, owner: str, name: str, default_branch: str, language: Optional[str] = None) -> Repository:
        repo = Repository(
            user_id=user_id,
            installation_id=installation_id,
            github_repo_id=github_repo_id,
            owner=owner,
            name=name,
            default_branch=default_branch,
            language=language
        )
        self.session.add(repo)
        self.session.commit()
        self.session.refresh(repo)
        return repo

    def get_by_id(self, repo_id: uuid.UUID) -> Optional[Repository]:
        return self.session.get(Repository, repo_id)

    def get_for_user(self, repo_id: uuid.UUID, user_id: uuid.UUID) -> Optional[Repository]:
        stmt = select(Repository).where(Repository.id == repo_id, Repository.user_id == user_id)
        return self.session.execute(stmt).scalar_one_or_none()

    def get_by_github_id_and_user(self, github_repo_id: str, user_id: uuid.UUID) -> Optional[Repository]:
        stmt = select(Repository).where(
            Repository.github_repo_id == github_repo_id,
            Repository.user_id == user_id,
        )
        return self.session.execute(stmt).scalar_one_or_none()

    def list_by_user(self, user_id: uuid.UUID) -> List[Repository]:
        stmt = select(Repository).where(Repository.user_id == user_id)
        return list(self.session.scalars(stmt).all())

    def update_sync_status(self, repo_id: uuid.UUID, status: SyncStatus) -> Optional[Repository]:
        repo = self.get_by_id(repo_id)
        if repo:
            repo.sync_status = status
            self.session.commit()
            self.session.refresh(repo)
        return repo

    def list_files(
        self, repo_id: uuid.UUID, offset: int, limit: int, path: Optional[str] = None
    ) -> tuple[list[RepositoryFile], int]:
        statement = select(RepositoryFile).where(RepositoryFile.repository_id == repo_id)
        if path:
            clean_path = path.strip().lstrip("./")
            statement = statement.where(RepositoryFile.path.ilike(f"%{clean_path}%"))
        statement = statement.order_by(RepositoryFile.path)
        total = self.session.scalar(select(func.count()).select_from(statement.subquery())) or 0
        return list(self.session.scalars(statement.offset(offset).limit(limit)).all()), total

    def get_file_by_path(self, repo_id: uuid.UUID, path: str) -> Optional[RepositoryFile]:
        clean_path = path.strip().lstrip("./")
        statement = select(RepositoryFile).where(
            RepositoryFile.repository_id == repo_id,
            RepositoryFile.path == clean_path,
        )
        return self.session.scalars(statement).first()

    def list_symbols(self, repo_id: uuid.UUID, offset: int, limit: int) -> tuple[list[CodeSymbol], int]:
        statement = select(CodeSymbol).where(CodeSymbol.repository_id == repo_id).order_by(CodeSymbol.name, CodeSymbol.start_line)
        total = self.session.scalar(select(func.count()).select_from(statement.subquery())) or 0
        return list(self.session.scalars(statement.offset(offset).limit(limit)).all()), total

    def create_sync_job(self, repository_id: uuid.UUID, user_id: uuid.UUID) -> SyncJob:
        job = SyncJob(repository_id=repository_id, user_id=user_id, status=SyncJobStatus.QUEUED)
        self.session.add(job)
        self.session.commit()
        self.session.refresh(job)
        return job

    def mark_sync_job_failed(self, job_id: uuid.UUID) -> Optional[SyncJob]:
        """Record a dispatch failure after a job has been persisted."""
        job = self.session.get(SyncJob, job_id)
        if job:
            job.status = SyncJobStatus.FAILED
            self.session.commit()
            self.session.refresh(job)
        return job

    def get_active_sync_job(self, repository_id: uuid.UUID) -> Optional[SyncJob]:
        """Find the most recent in-flight (QUEUED or RUNNING) sync job for a repository."""
        if not hasattr(self.session, "scalars"):
            return None
        stmt = (
            select(SyncJob)
            .where(
                SyncJob.repository_id == repository_id,
                SyncJob.status.in_([SyncJobStatus.QUEUED, SyncJobStatus.RUNNING]),
            )
            .order_by(SyncJob.created_at.desc())
        )
        return self.session.scalars(stmt).first()

    def get_stale_sync_jobs(self, timeout_seconds: int = 600) -> list[SyncJob]:
        """Retrieve all QUEUED or RUNNING sync jobs exceeding timeout threshold."""
        if not hasattr(self.session, "scalars"):
            return []
        cutoff = datetime.now(timezone.utc) - timedelta(seconds=timeout_seconds)
        stmt = (
            select(SyncJob)
            .where(
                SyncJob.status.in_([SyncJobStatus.QUEUED, SyncJobStatus.RUNNING]),
                func.coalesce(SyncJob.updated_at, SyncJob.created_at) < cutoff,
            )
            .order_by(SyncJob.created_at.asc())
        )
        return list(self.session.scalars(stmt).all())

    def delete(self, repo_id: uuid.UUID, redis_client: Any = None) -> bool:
        """Atomically delete a repository and all related dependent records without swallowing errors.

        Executes atomic database deletion, followed by safe post-commit cleanup of external
        filesystem resources (workspaces, clones, intelligence snapshots) and Redis keys/queues.
        """
        repo = self.get_by_id(repo_id)
        if not repo:
            return False

        from app.models.analysis_finding import AnalysisFinding
        from app.models.analysis_run import AnalysisRun
        from app.models.code_chunk import CodeChunk
        from app.models.code_symbol import CodeSymbol
        from app.models.symbol_edge import SymbolEdge
        from app.models.repository_file import RepositoryFile
        from app.models.sync_job import SyncJob
        from app.models.memory_entry import MemoryEntry
        from app.models.pull_request import PullRequest
        from app.models.task import GitHubIssue, Task
        from app.models.webhook_event import GitHubWebhookEvent
        from sqlalchemy import delete, update

        workspace_paths: list[str] = []
        try:
            # Audit log events are explicitly retained with repository_id set to NULL
            self.session.execute(
                update(GitHubWebhookEvent)
                .where(GitHubWebhookEvent.repository_id == repo_id)
                .values(repository_id=None)
            )

            # Pre-collect task workspace directories to clean up post-commit
            tasks = list(self.session.scalars(select(Task).where(Task.repository_id == repo_id)).all())
            for task_obj in tasks:
                workspace_paths.append(f".workspaces/task-{task_obj.id}")
                self.session.delete(task_obj)
            self.session.flush()

            self.session.execute(delete(GitHubIssue).where(GitHubIssue.repository_id == repo_id))
            self.session.execute(delete(AnalysisFinding).where(AnalysisFinding.repository_id == repo_id))
            self.session.execute(delete(AnalysisRun).where(AnalysisRun.repository_id == repo_id))
            self.session.execute(delete(PullRequest).where(PullRequest.repository_id == repo_id))
            self.session.execute(delete(CodeChunk).where(CodeChunk.repository_id == repo_id))
            self.session.execute(delete(SymbolEdge).where(SymbolEdge.repository_id == repo_id))
            self.session.execute(delete(CodeSymbol).where(CodeSymbol.repository_id == repo_id))
            self.session.execute(delete(RepositoryFile).where(RepositoryFile.repository_id == repo_id))
            self.session.execute(delete(SyncJob).where(SyncJob.repository_id == repo_id))
            self.session.execute(delete(MemoryEntry).where(MemoryEntry.repository_id == repo_id))
            self.session.delete(repo)
            self.session.commit()
        except Exception as exc:
            self.session.rollback()
            logger.error("repository_deletion_failed", extra={"repo_id": str(repo_id), "error": str(exc)})
            raise

        # Post-commit: Clean up external filesystem resources (Issue #183)
        try:
            cleanup_repository_filesystem_resources(repo_id, workspace_paths)
        except Exception as fs_exc:
            logger.warning("post_delete_filesystem_cleanup_warning", extra={"error": str(fs_exc), "repo_id": str(repo_id)})

        # Post-commit: Clean up Redis cache keys and job queue references (Issue #183)
        try:
            cleanup_repository_redis_resources(repo_id, redis_client)
        except Exception as redis_exc:
            logger.warning("post_delete_redis_cleanup_warning", extra={"error": str(redis_exc), "repo_id": str(repo_id)})

        return True


def cleanup_repository_filesystem_resources(
    repo_id: uuid.UUID,
    workspace_paths: list[str] | None = None,
) -> dict[str, int]:
    """Clean up filesystem workspaces, snapshots, and temporary clones for a deleted repository."""
    removed = {"intelligence_snapshots": 0, "clones": 0, "task_workspaces": 0}

    # 1. Clean repository intelligence snapshots: .workspaces/repository-intelligence/{repo_id}
    try:
        raw_intel_base = os.getenv("REPOSITORY_INTELLIGENCE_DIR", ".workspaces/repository-intelligence")
        base_intel = Path(raw_intel_base).resolve()
        repo_intel_dir = (base_intel / str(repo_id)).resolve()
        if (
            repo_intel_dir.is_relative_to(base_intel)
            and repo_intel_dir != base_intel
            and repo_intel_dir.exists()
        ):
            shutil.rmtree(repo_intel_dir, ignore_errors=True)
            removed["intelligence_snapshots"] += 1
    except Exception as exc:
        logger.debug("cleanup_intelligence_dir_skipped", extra={"error": str(exc), "repo_id": str(repo_id)})

    # Also clear in-memory snapshot cache if loaded
    try:
        from ai.intelligence.snapshot_manager import RepositoryIntelligenceSnapshotManager
        RepositoryIntelligenceSnapshotManager._cache.clear()
    except Exception:
        pass

    # 2. Clean temporary clone directories in temp folders
    for temp_base in [
        Path(tempfile.gettempdir()) / "ai_platform_workspaces",
        Path(tempfile.gettempdir()) / "ai_platform_repos",
    ]:
        if temp_base.exists():
            for match_dir in temp_base.glob(f"repo_{repo_id}_*"):
                if match_dir.is_dir():
                    shutil.rmtree(match_dir, ignore_errors=True)
                    removed["clones"] += 1

    # 3. Clean task workspace directories with strict containment validation
    if workspace_paths:
        ws_root = Path(".workspaces").resolve()
        for ws_p in workspace_paths:
            try:
                p = Path(ws_p).resolve()
                if p.is_relative_to(ws_root) and p != ws_root and p.exists():
                    shutil.rmtree(p, ignore_errors=True)
                    removed["task_workspaces"] += 1
            except Exception:
                pass

    return removed


def cleanup_repository_redis_resources(
    repo_id: uuid.UUID,
    redis_client: Any = None,
) -> dict[str, int]:
    """Invalidate Redis cache keys, locks, and queued jobs for a deleted repository."""
    if redis_client is None:
        try:
            from app.core.redis import get_redis
            redis_client = get_redis()
        except Exception:
            redis_client = None

    if redis_client is None:
        return {"keys_invalidated": 0, "jobs_drained": 0}

    keys_invalidated = 0
    jobs_drained = 0

    # 1. Invalidate SourceRevisionCache: gh_src:{repo_id}:*
    try:
        from app.integrations.github.cache import SourceRevisionCache
        cache = SourceRevisionCache(redis_client=redis_client)
        cache.invalidate_repository(repo_id)
        keys_invalidated += 1
    except Exception as exc:
        logger.debug("source_revision_cache_invalidation_skipped", extra={"error": str(exc), "repo_id": str(repo_id)})

    # 2. Invalidate RetrievalResultCache: retrieval:v2:default:{repo_id}:*
    try:
        cursor = 0
        match_pat = f"retrieval:v2:default:{repo_id}:*"
        while True:
            if hasattr(redis_client, "scan"):
                cursor, keys = redis_client.scan(cursor=cursor, match=match_pat, count=100)
                if keys:
                    redis_client.delete(*keys)
                    keys_invalidated += len(keys)
                if cursor == 0:
                    break
            else:
                break
    except Exception as exc:
        logger.debug("retrieval_cache_invalidation_skipped", extra={"error": str(exc), "repo_id": str(repo_id)})

    # 3. Remove worker repository lock: sync_lock:repo:{repo_id}
    try:
        if hasattr(redis_client, "delete"):
            redis_client.delete(f"sync_lock:repo:{repo_id}")
    except Exception:
        pass

    # 4. Drain pending sync jobs for this repository from sync_jobs Redis list
    try:
        if hasattr(redis_client, "lrange") and hasattr(redis_client, "lrem"):
            repo_str = str(repo_id)
            items = redis_client.lrange("sync_jobs", 0, -1)
            if items:
                for item in items:
                    item_str = item.decode("utf-8") if isinstance(item, bytes) else str(item)
                    if f'"repository_id": "{repo_str}"' in item_str or f'"repository_id":"{repo_str}"' in item_str:
                        redis_client.lrem("sync_jobs", 0, item)
                        jobs_drained += 1
    except Exception as exc:
        logger.debug("sync_jobs_queue_purge_skipped", extra={"error": str(exc), "repo_id": str(repo_id)})

    return {"keys_invalidated": keys_invalidated, "jobs_drained": jobs_drained}
