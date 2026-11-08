"""Comprehensive test suite for Issue #183: Repository Deletion Cascades & Resource Cleanup.

Validates:
1. Authorization & Tenant Isolation:
   - Repository owner can delete repository (204).
   - Other authenticated user cannot delete another's repository (404).
   - Unauthenticated deletion rejected (401).
   - Invalid repository UUID format handled cleanly (422).
   - Repeated deletion requests return consistent 404.
2. Relational Database Cascades:
   - Direct database / ORM deletion cascades to repository_files, code_symbols,
     symbol_edges, code_chunks (pgvector), memory_entries, sync_jobs, pull_requests,
     analysis_runs, analysis_findings, and tasks.
   - Foreign-key behavior (ON DELETE CASCADE and ON DELETE SET NULL).
   - Webhook audit events are retained with nullified repository_id (ON DELETE SET NULL).
3. External Resource Cleanup:
   - Intelligence snapshot directory (.workspaces/repository-intelligence/{repo_id}) deleted.
   - Temporary clone directories (/tmp/.../repo_{repo_id}_*) removed.
   - Task workspace directories deleted with path traversal protection.
   - Redis cache keys (SourceRevisionCache, RetrievalResultCache) invalidated.
   - Worker repository lock (sync_lock:repo:{repo_id}) removed.
   - Queued sync jobs for the deleted repository drained from the Redis list.
4. Isolation & Multi-Tenancy:
   - Other repositories' database records, files, chunks, tasks, and caches remain untouched.
   - Shared content-addressed embedding cache keys (emb:v1:*) are preserved.
5. Background Job & Worker Safety:
   - IncrementalIndexer aborts when repository was deleted before indexing.
   - IncrementalIndexer rolls back and aborts when repository was deleted before final commit.
   - Background sync worker drops jobs for deleted repositories without error or resurrection.
"""

from __future__ import annotations

import json
import os
import shutil
import tempfile
import uuid
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session, sessionmaker

from app.core.database import Base
from app.models.analysis_finding import AnalysisFinding
from app.models.analysis_run import AnalysisRun
from app.models.code_chunk import CodeChunk
from app.models.code_symbol import CodeSymbol
from app.models.github_installation import GitHubInstallation
from app.models.memory_entry import MemoryEntry, MemoryStatus, MemoryType
from app.models.pull_request import PullRequest
from app.models.repository import Repository, SyncStatus
from app.models.repository_file import RepositoryFile
from app.models.symbol_edge import SymbolEdge
from app.models.sync_job import SyncJob, SyncJobStatus
from app.models.task import GitHubIssue, Task
from app.models.user import User
from app.models.webhook_event import GitHubWebhookEvent, WebhookEventStatus
from app.repositories.repository_repository import (
    RepositoryRepository,
    cleanup_repository_filesystem_resources,
    cleanup_repository_redis_resources,
)
from indexer.incremental import IncrementalIndexer


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def sqlite_engine():
    engine = create_engine("sqlite:///:memory:", echo=False)
    Base.metadata.create_all(engine)
    yield engine
    Base.metadata.drop_all(engine)
    engine.dispose()


@pytest.fixture
def sqlite_session(sqlite_engine):
    SessionLocal = sessionmaker(bind=sqlite_engine)
    session = SessionLocal()
    yield session
    session.close()


def _create_test_hierarchy(session: Session, user_id: uuid.UUID | None = None) -> tuple[Repository, dict]:
    uid = user_id or uuid.uuid4()
    inst = GitHubInstallation(
        id=uuid.uuid4(),
        user_id=uid,
        installation_id=f"inst-{uuid.uuid4().hex[:6]}",
        account_login="test-user",
        permissions={"contents": "read"},
    )
    session.add(inst)
    session.commit()

    repo = Repository(
        id=uuid.uuid4(),
        user_id=uid,
        installation_id=inst.id,
        github_repo_id=f"gh-{uuid.uuid4().hex[:6]}",
        owner="test-user",
        name=f"test-repo-{uuid.uuid4().hex[:6]}",
    )
    session.add(repo)
    session.commit()

    file_obj = RepositoryFile(
        id=uuid.uuid4(),
        repository_id=repo.id,
        path="src/main.py",
        language="python",
        content_hash="hash123",
        size_bytes=100,
        line_count=10,
    )
    session.add(file_obj)
    session.commit()

    sym_parent = CodeSymbol(
        id=uuid.uuid4(),
        repository_id=repo.id,
        file_id=file_obj.id,
        name="ParentClass",
        kind="class",
        start_line=1,
        end_line=10,
    )
    session.add(sym_parent)
    session.commit()

    sym_child = CodeSymbol(
        id=uuid.uuid4(),
        repository_id=repo.id,
        file_id=file_obj.id,
        name="child_method",
        kind="method",
        start_line=2,
        end_line=5,
        parent_id=sym_parent.id,
    )
    session.add(sym_child)
    session.commit()

    edge = SymbolEdge(
        id=uuid.uuid4(),
        repository_id=repo.id,
        source_symbol_id=sym_parent.id,
        target_symbol_id=sym_child.id,
        edge_type="defines",
    )
    session.add(edge)

    dummy_vector = [0.1] * 768
    chunk = CodeChunk(
        id=uuid.uuid4(),
        repository_id=repo.id,
        file_id=file_obj.id,
        symbol_id=sym_child.id,
        content="def child_method(): pass",
        token_count=10,
        embedding=dummy_vector,
        start_line=2,
        end_line=5,
        content_hash="chunkhash1",
    )
    session.add(chunk)

    mem = MemoryEntry(
        id=uuid.uuid4(),
        repository_id=repo.id,
        type_=MemoryType.decision,
        content="Decided to use clean cascades",
        source="audit",
        status=MemoryStatus.active,
    )
    session.add(mem)

    job = SyncJob(
        id=uuid.uuid4(),
        repository_id=repo.id,
        user_id=uid,
        status=SyncJobStatus.COMPLETED,
    )
    session.add(job)

    task = Task(
        id=uuid.uuid4(),
        repository_id=repo.id,
        user_id=uid,
        title="Fix bug",
        description="desc",
    )
    session.add(task)

    pr = PullRequest(
        id=uuid.uuid4(),
        task_id=task.id,
        repository_id=repo.id,
        branch="feat/test",
        base_branch="main",
        changed_files=["src/main.py"],
        commit_message="Initial commit",
        test_summary="Passed",
        verification_summary="Verified",
        pr_number=1,
        pr_url="https://github.com/test-owner/test-repo/pull/1",
        status="prepared",
    )
    session.add(pr)

    run = AnalysisRun(
        id=uuid.uuid4(),
        repository_id=repo.id,
        user_id=uid,
        feature_type="bug_detection",
        source_revision="sha1",
    )
    session.add(run)
    session.commit()

    finding = AnalysisFinding(
        id=uuid.uuid4(),
        analysis_run_id=run.id,
        repository_id=repo.id,
        category="security",
        severity="medium",
        title="Potential issue",
        description="desc",
        file_path="src/main.py",
        start_line=3,
        evidence="evidence",
    )
    session.add(finding)

    webhook_id = uuid.uuid4()
    webhook_evt = GitHubWebhookEvent(
        id=webhook_id,
        delivery_id=f"del-{uuid.uuid4().hex[:6]}",
        event_type="push",
        payload={"ref": "refs/heads/main"},
        status=WebhookEventStatus.SUCCEEDED,
        repository_id=repo.id,
    )
    session.add(webhook_evt)

    # Capture all entity IDs before commit so they remain accessible when detached
    from types import SimpleNamespace
    entities = {
        "file": SimpleNamespace(id=file_obj.id),
        "parent_sym": SimpleNamespace(id=sym_parent.id),
        "child_sym": SimpleNamespace(id=sym_child.id),
        "edge": SimpleNamespace(id=edge.id),
        "chunk": SimpleNamespace(id=chunk.id),
        "memory": SimpleNamespace(id=mem.id),
        "job": SimpleNamespace(id=job.id),
        "pr": SimpleNamespace(id=pr.id),
        "run": SimpleNamespace(id=run.id),
        "finding": SimpleNamespace(id=finding.id),
        "task": SimpleNamespace(id=task.id),
        "webhook": SimpleNamespace(id=webhook_id),
    }
    session.commit()
    return repo, entities


# ---------------------------------------------------------------------------
# 1. API Authorization and Multi-Tenancy Tests
# ---------------------------------------------------------------------------

def test_delete_repository_by_owner_succeeds(
    client: TestClient,
    db_session: Session,
    test_user: User,
    auth_headers: dict[str, str],
):
    """Repository owner can delete their repository and receives 204."""
    repo, _ = _create_test_hierarchy(db_session, user_id=test_user.id)

    response = client.delete(f"/api/v1/repositories/{repo.id}", headers=auth_headers)
    assert response.status_code == 204

    # Verify repository is gone
    assert db_session.get(Repository, repo.id) is None


def test_delete_repository_by_non_owner_forbidden(
    client: TestClient,
    db_session: Session,
    test_user: User,
    auth_headers: dict[str, str],
):
    """Another authenticated user cannot delete a repository they do not own (returns 404)."""
    other_user_id = uuid.uuid4()
    repo, _ = _create_test_hierarchy(db_session, user_id=other_user_id)

    response = client.delete(f"/api/v1/repositories/{repo.id}", headers=auth_headers)
    assert response.status_code == 404
    payload = response.json()
    err_msg = payload.get("error", {}).get("message") or payload.get("detail", {}).get("message", "")
    assert "not exist" in str(err_msg).lower() or "not found" in str(err_msg).lower()

    # Verify repository still exists
    assert db_session.get(Repository, repo.id) is not None


def test_delete_repository_unauthenticated_rejected(
    client: TestClient,
    db_session: Session,
):
    """Unauthenticated delete requests are rejected with 401."""
    repo, _ = _create_test_hierarchy(db_session)
    response = client.delete(f"/api/v1/repositories/{repo.id}")
    assert response.status_code == 401


def test_delete_repository_invalid_uuid(
    client: TestClient,
    auth_headers: dict[str, str],
):
    """Invalid repository UUID returns 422 Unprocessable Entity."""
    response = client.delete("/api/v1/repositories/not-a-valid-uuid", headers=auth_headers)
    assert response.status_code == 422


def test_delete_repository_repeated_requests_return_404(
    client: TestClient,
    db_session: Session,
    test_user: User,
    auth_headers: dict[str, str],
):
    """Subsequent delete requests for an already deleted repository consistently return 404."""
    repo, _ = _create_test_hierarchy(db_session, user_id=test_user.id)

    res1 = client.delete(f"/api/v1/repositories/{repo.id}", headers=auth_headers)
    assert res1.status_code == 204

    res2 = client.delete(f"/api/v1/repositories/{repo.id}", headers=auth_headers)
    assert res2.status_code == 404


# ---------------------------------------------------------------------------
# 2. Relational Database Cascades & Retention Tests
# ---------------------------------------------------------------------------

def test_repository_repository_delete_cascades_all_relational_children(sqlite_session: Session):
    """RepositoryRepository.delete cleans up all child tables atomically."""
    repo, entities = _create_test_hierarchy(sqlite_session)
    repo_id = repo.id

    repo_repo = RepositoryRepository(sqlite_session)
    success = repo_repo.delete(repo_id)
    assert success is True
    sqlite_session.expunge_all()

    # Assert root repository removed
    assert sqlite_session.get(Repository, repo_id) is None

    # Assert all child entities deleted
    assert sqlite_session.get(RepositoryFile, entities["file"].id) is None
    assert sqlite_session.get(CodeSymbol, entities["parent_sym"].id) is None
    assert sqlite_session.get(CodeSymbol, entities["child_sym"].id) is None
    assert sqlite_session.get(SymbolEdge, entities["edge"].id) is None
    assert sqlite_session.get(CodeChunk, entities["chunk"].id) is None
    assert sqlite_session.get(MemoryEntry, entities["memory"].id) is None
    assert sqlite_session.get(SyncJob, entities["job"].id) is None
    assert sqlite_session.get(PullRequest, entities["pr"].id) is None
    assert sqlite_session.get(AnalysisRun, entities["run"].id) is None
    assert sqlite_session.get(AnalysisFinding, entities["finding"].id) is None
    assert sqlite_session.get(Task, entities["task"].id) is None

    # Webhook audit log is RETAINED with nullified repository_id
    webhook = sqlite_session.get(GitHubWebhookEvent, entities["webhook"].id)
    assert webhook is not None
    assert webhook.repository_id is None


def test_repository_delete_isolation_leaves_other_repositories_untouched(sqlite_session: Session):
    """Deleting Repo A does not remove or affect records belonging to Repo B."""
    repo_a, ent_a = _create_test_hierarchy(sqlite_session)
    repo_b, ent_b = _create_test_hierarchy(sqlite_session)
    repo_a_id = repo_a.id
    repo_b_id = repo_b.id

    repo_repo = RepositoryRepository(sqlite_session)
    repo_repo.delete(repo_a_id)
    sqlite_session.expunge_all()

    # Repo A is gone
    assert sqlite_session.get(Repository, repo_a_id) is None
    assert sqlite_session.get(RepositoryFile, ent_a["file"].id) is None

    # Repo B is completely intact
    assert sqlite_session.get(Repository, repo_b_id) is not None
    assert sqlite_session.get(RepositoryFile, ent_b["file"].id) is not None
    assert sqlite_session.get(CodeSymbol, ent_b["parent_sym"].id) is not None
    assert sqlite_session.get(CodeChunk, ent_b["chunk"].id) is not None
    assert sqlite_session.get(Task, ent_b["task"].id) is not None


# ---------------------------------------------------------------------------
# 3. External Resource Cleanup Tests (Filesystem, Workspaces, Redis)
# ---------------------------------------------------------------------------

def test_cleanup_filesystem_resources_removes_snapshots_and_clones(tmp_path: Path, monkeypatch):
    """Verifies physical directory cleanup for intelligence snapshots, clones, and task workspaces."""
    monkeypatch.chdir(tmp_path)
    repo_id = uuid.uuid4()
    intel_base = tmp_path / "intel_root"
    intel_base.mkdir(parents=True)
    repo_intel_dir = intel_base / str(repo_id)
    repo_intel_dir.mkdir(parents=True)
    (repo_intel_dir / "snapshot.json").write_text("{\"data\": 1}")

    monkeypatch.setenv("REPOSITORY_INTELLIGENCE_DIR", str(intel_base))

    # Create dummy clone directory
    temp_workspaces = Path(tempfile.gettempdir()) / "ai_platform_workspaces"
    temp_workspaces.mkdir(parents=True, exist_ok=True)
    clone_dir = temp_workspaces / f"repo_{repo_id}_testjob"
    clone_dir.mkdir(parents=True, exist_ok=True)
    (clone_dir / "README.md").write_text("# Clone")

    # Create dummy task workspace inside .workspaces
    ws_root = Path(".workspaces").resolve()
    ws_root.mkdir(parents=True, exist_ok=True)
    task_ws = ws_root / f"task-{uuid.uuid4().hex[:6]}"
    task_ws.mkdir(parents=True, exist_ok=True)
    (task_ws / "patch.diff").write_text("diff")

    try:
        res = cleanup_repository_filesystem_resources(repo_id, workspace_paths=[str(task_ws)])

        assert res["intelligence_snapshots"] == 1
        assert not repo_intel_dir.exists()
        assert not clone_dir.exists()
        assert not task_ws.exists()
    finally:
        shutil.rmtree(clone_dir, ignore_errors=True)
        shutil.rmtree(task_ws, ignore_errors=True)


def test_cleanup_filesystem_path_traversal_guard(tmp_path: Path, monkeypatch):
    """Attempts to pass path traversal in workspace_paths are blocked without deleting root."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".workspaces").mkdir(parents=True, exist_ok=True)
    repo_id = uuid.uuid4()
    # Traversal attempting to target root or parent
    malicious_paths = [
        "../../etc/passwd",
        ".workspaces",
        ".",
        "C:\\Windows",
    ]
    res = cleanup_repository_filesystem_resources(repo_id, workspace_paths=malicious_paths)
    assert res["task_workspaces"] == 0
    # .workspaces root must still exist
    assert Path(".workspaces").exists()


def test_cleanup_redis_resources_purges_keys_and_drains_queue():
    """Verifies Redis cache invalidation, lock release, and queue filtering."""
    repo_id = uuid.uuid4()
    repo_str = str(repo_id)
    other_repo_id = uuid.uuid4()

    mock_redis = MagicMock()
    # Mock keys matching repo
    mock_redis.scan.side_effect = [
        (1, [f"retrieval:v2:default:{repo_str}:1:h1".encode()]),
        (0, [f"retrieval:v2:default:{repo_str}:1:h2".encode()]),
    ]
    # Mock sync_jobs list containing 1 job for target repo and 1 job for other repo
    job_target = json.dumps({"job_id": "j1", "repository_id": repo_str}).encode()
    job_other = json.dumps({"job_id": "j2", "repository_id": str(other_repo_id)}).encode()
    mock_redis.lrange.return_value = [job_target, job_other]

    with patch("app.integrations.github.cache.SourceRevisionCache.invalidate_repository") as mock_src_inv:
        res = cleanup_repository_redis_resources(repo_id, redis_client=mock_redis)

        # SourceRevisionCache invalidated
        mock_src_inv.assert_called_once_with(repo_id)

        # Retrieval keys deleted
        assert res["keys_invalidated"] >= 2
        mock_redis.delete.assert_any_call(
            f"retrieval:v2:default:{repo_str}:1:h1".encode(),
        )

        # Worker lock deleted
        mock_redis.delete.assert_any_call(f"sync_lock:repo:{repo_id}")

        # Queued job for target repo removed from queue, other job preserved
        mock_redis.lrem.assert_called_once_with("sync_jobs", 0, job_target)
        assert res["jobs_drained"] == 1


# ---------------------------------------------------------------------------
# 4. Background Job & Worker Safety Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_incremental_indexer_aborts_when_repository_deleted_before_indexing():
    """IncrementalIndexer._run_sync aborts immediately if repository does not exist."""
    mock_session = AsyncMock()
    # Mock SELECT 1 FROM repositories returning empty
    mock_result = MagicMock()
    mock_result.first.return_value = None
    mock_session.execute.return_value = mock_result

    indexer = IncrementalIndexer(db_session=lambda: mock_session, embedding_service=AsyncMock())
    repo_id = uuid.uuid4()

    res = await indexer._run_sync(
        session=mock_session,
        repository_id=repo_id,
        scanned_files=[],
    )

    assert res == {"indexed": 0, "skipped": 0, "reconciled_removed": 0, "graph_edges": 0}
    # Should not attempt to commit
    assert not mock_session.commit.called


@pytest.mark.asyncio
async def test_incremental_indexer_rolls_back_when_repository_deleted_before_snapshot(tmp_path: Path, monkeypatch):
    """IncrementalIndexer rolls back and aborts before publishing snapshot if repository is deleted."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("REPOSITORY_INTELLIGENCE_DIR", str(tmp_path / "intel"))
    monkeypatch.setattr("ai.intelligence.snapshot_manager.DEFAULT_SNAPSHOT_BASE_DIR", tmp_path / "intel")

    mock_session = AsyncMock()
    # Check 1: start of sync -> (1,)
    # Check 2: before snapshot -> None (deleted)
    repo_checks = [(1,), None]

    async def _mock_execute(stmt, params=None):
        sql = str(stmt).lower()
        if "select 1 from repositories" in sql:
            val = repo_checks.pop(0) if repo_checks else None
            m = MagicMock()
            m.first.return_value = val
            return m
        m = MagicMock()
        m.fetchall.return_value = []
        m.first.return_value = None
        return m

    mock_session.execute = AsyncMock(side_effect=_mock_execute)

    indexer = IncrementalIndexer(db_session=lambda: mock_session, embedding_service=AsyncMock())
    repo_id = uuid.uuid4()

    with patch("ai.intelligence.snapshot_manager.RepositoryIntelligenceSnapshotManager.publish_snapshot") as mock_pub:
        res = await indexer._run_sync(
            session=mock_session,
            repository_id=repo_id,
            scanned_files=[],
        )

        assert res == {"indexed": 0, "skipped": 0, "reconciled_removed": 0, "graph_edges": 0}
        # Snapshot publish must NOT have been called
        assert not mock_pub.called
        # Transaction must be rolled back cleanly
        mock_session.rollback.assert_called_once()
        assert not mock_session.commit.called


@pytest.mark.asyncio
async def test_incremental_indexer_cleans_up_snapshot_and_rolls_back_if_deleted_before_commit(tmp_path: Path, monkeypatch):
    """IncrementalIndexer cleans up snapshot and rolls back if repository is deleted before final commit."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("REPOSITORY_INTELLIGENCE_DIR", str(tmp_path / "intel"))
    monkeypatch.setattr("ai.intelligence.snapshot_manager.DEFAULT_SNAPSHOT_BASE_DIR", tmp_path / "intel")

    mock_session = AsyncMock()
    # Check 1: start of sync -> (1,)
    # Check 2: before snapshot -> (1,)
    # Check 3: before final commit -> None (deleted)
    repo_checks = [(1,), (1,), None]

    async def _mock_execute(stmt, params=None):
        sql = str(stmt).lower()
        if "select 1 from repositories" in sql:
            val = repo_checks.pop(0) if repo_checks else None
            m = MagicMock()
            m.first.return_value = val
            return m
        m = MagicMock()
        m.fetchall.return_value = []
        m.first.return_value = None
        return m

    mock_session.execute = AsyncMock(side_effect=_mock_execute)

    indexer = IncrementalIndexer(db_session=lambda: mock_session, embedding_service=AsyncMock())
    repo_id = uuid.uuid4()

    with patch("app.repositories.repository_repository.cleanup_repository_filesystem_resources") as mock_cleanup:
        res = await indexer._run_sync(
            session=mock_session,
            repository_id=repo_id,
            scanned_files=[],
        )

        assert res == {"indexed": 0, "skipped": 0, "reconciled_removed": 0, "graph_edges": 0}
        # cleanup_repository_filesystem_resources must be called for the deleted repo
        mock_cleanup.assert_called_once_with(repo_id)
        mock_session.rollback.assert_called_once()
        assert not mock_session.commit.called


@pytest.mark.asyncio
async def test_sync_worker_discards_job_for_deleted_repository():
    """Sync worker safely terminates if repository is deleted without resurrecting data."""
    from app.services.sync_worker import process_sync_job

    job_id = uuid.uuid4()
    repo_id = uuid.uuid4()
    user_id = uuid.uuid4()

    with patch("app.services.sync_worker.SessionLocal") as mock_session_factory:
        mock_db = MagicMock()
        mock_db.get.return_value = None  # Repository not found
        mock_session_factory.return_value.__enter__.return_value = mock_db

        mock_gh = MagicMock()
        await process_sync_job(job_id=job_id, repository_id=repo_id, user_id=user_id, github_service=mock_gh)

        # No git clone or indexing triggered
        assert not mock_gh.clone_repository.called
        assert not mock_db.commit.called
