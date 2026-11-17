"""Unit and schema tests for Issue #265 (F-45): composite indexes for worker queue polling, repository lookups, and graph traversals."""

import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from app.core.database import Base
from app.models.code_symbol import CodeSymbol
from app.models.memory_entry import MemoryEntry, MemoryStatus, MemoryType
from app.models.repository import Repository, SyncStatus
from app.models.repository_file import RepositoryFile
from app.models.symbol_edge import SymbolEdge
from app.models.sync_job import SyncJob, SyncJobStatus
from app.models.user import User
from app.models.webhook_event import GitHubWebhookEvent, WebhookEventStatus


def test_sync_job_indexes_declared():
    """Verify SyncJob model defines status index and (status, created_at) composite index."""
    indexes = {idx.name: [c.name for c in idx.columns] for idx in SyncJob.__table__.indexes}
    assert "ix_sync_jobs_status_created" in indexes
    assert indexes["ix_sync_jobs_status_created"] == ["status", "created_at"]
    # Check that status column itself has an index
    status_col = SyncJob.__table__.c.status
    assert status_col.index is True or any(
        idx.name == "ix_sync_jobs_status" for idx in SyncJob.__table__.indexes
    )


def test_webhook_event_composite_index_declared():
    """Verify GitHubWebhookEvent model defines (status, available_at) composite index."""
    indexes = {idx.name: [c.name for c in idx.columns] for idx in GitHubWebhookEvent.__table__.indexes}
    assert "ix_webhook_events_status_available" in indexes
    assert indexes["ix_webhook_events_status_available"] == ["status", "available_at"]


def test_repository_composite_index_declared():
    """Verify Repository model defines (owner, name) composite index."""
    indexes = {idx.name: [c.name for c in idx.columns] for idx in Repository.__table__.indexes}
    assert "ix_repositories_owner_name" in indexes
    assert indexes["ix_repositories_owner_name"] == ["owner", "name"]


def test_symbol_edge_composite_indexes_declared():
    """Verify SymbolEdge model defines (repository_id, source_symbol_id) and (repository_id, target_symbol_id) composite indexes."""
    indexes = {idx.name: [c.name for c in idx.columns] for idx in SymbolEdge.__table__.indexes}
    assert "ix_symbol_edges_repo_source" in indexes
    assert indexes["ix_symbol_edges_repo_source"] == ["repository_id", "source_symbol_id"]
    assert "ix_symbol_edges_repo_target" in indexes
    assert indexes["ix_symbol_edges_repo_target"] == ["repository_id", "target_symbol_id"]


def test_memory_entry_composite_index_declared():
    """Verify MemoryEntry model defines (repository_id, type, status) composite index."""
    indexes = {idx.name: [c.name for c in idx.columns] for idx in MemoryEntry.__table__.indexes}
    assert "ix_memory_entries_repo_type_status" in indexes
    assert indexes["ix_memory_entries_repo_type_status"] == ["repository_id", "type", "status"]


def test_queries_execute_with_indexed_models(db_session: Session):
    """Verify querying through the newly indexed models functions seamlessly with zero errors."""
    user = User(
        email="dev_f45@example.com",
        github_id="gh_999",
        login="octocat",
        avatar_url="https://avatar.url",
    )
    db_session.add(user)
    db_session.flush()

    repo = Repository(
        user_id=user.id,
        installation_id=uuid.uuid4(),
        github_repo_id="gh_repo_123",
        owner="octocat",
        name="hello-world",
        default_branch="main",
    )
    db_session.add(repo)
    db_session.flush()

    # 1. Test repository lookup by (owner, name)
    found_repo = db_session.execute(
        select(Repository).where(Repository.owner == "octocat", Repository.name == "hello-world")
    ).scalar_one_or_none()
    assert found_repo is not None
    assert found_repo.id == repo.id

    # 2. Test SyncJob queue query
    job = SyncJob(
        repository_id=repo.id,
        user_id=user.id,
        status=SyncJobStatus.QUEUED,
    )
    db_session.add(job)
    db_session.flush()

    queued_jobs = db_session.execute(
        select(SyncJob).where(SyncJob.status == SyncJobStatus.QUEUED).order_by(SyncJob.created_at)
    ).scalars().all()
    assert len(queued_jobs) >= 1
    assert queued_jobs[0].id == job.id

    # 3. Test GitHubWebhookEvent draining query
    now_utc = datetime.now(timezone.utc)
    wh_event = GitHubWebhookEvent(
        delivery_id=f"del_{uuid.uuid4().hex[:12]}",
        event_type="push",
        payload={"ref": "refs/heads/main"},
        status=WebhookEventStatus.PENDING,
        available_at=now_utc,
    )
    db_session.add(wh_event)
    db_session.flush()

    pending_events = db_session.execute(
        select(GitHubWebhookEvent).where(
            GitHubWebhookEvent.status == WebhookEventStatus.PENDING,
            GitHubWebhookEvent.available_at <= now_utc,
        )
    ).scalars().all()
    assert len(pending_events) >= 1
    assert any(e.id == wh_event.id for e in pending_events)

    # 4. Test MemoryEntry convention query
    memory = MemoryEntry(
        repository_id=repo.id,
        type_=MemoryType.rule,
        content="Use snake_case for functions",
        source="system",
        status=MemoryStatus.active,
        embedding=[0.0] * 768,
    )
    db_session.add(memory)
    db_session.flush()

    active_rules = db_session.execute(
        select(MemoryEntry).where(
            MemoryEntry.repository_id == repo.id,
            MemoryEntry.type_ == MemoryType.rule,
            MemoryEntry.status == MemoryStatus.active,
        )
    ).scalars().all()
    assert len(active_rules) == 1
    assert active_rules[0].content == "Use snake_case for functions"

    # 5. Test SymbolEdge caller/callee traversal query
    repo_file = RepositoryFile(
        repository_id=repo.id,
        path="src/main.py",
        language="python",
        size_bytes=100,
        line_count=10,
        content_hash="hash123",
    )
    db_session.add(repo_file)
    db_session.flush()

    caller_sym = CodeSymbol(
        file_id=repo_file.id,
        repository_id=repo.id,
        name="do_work",
        kind="function",
        start_line=1,
        end_line=5,
    )
    callee_sym = CodeSymbol(
        file_id=repo_file.id,
        repository_id=repo.id,
        name="helper",
        kind="function",
        start_line=6,
        end_line=10,
    )
    db_session.add_all([caller_sym, callee_sym])
    db_session.flush()

    edge = SymbolEdge(
        repository_id=repo.id,
        source_symbol_id=caller_sym.id,
        target_symbol_id=callee_sym.id,
        edge_type="calls",
    )
    db_session.add(edge)
    db_session.flush()

    found_edges = db_session.execute(
        select(SymbolEdge).where(
            SymbolEdge.repository_id == repo.id,
            SymbolEdge.source_symbol_id == caller_sym.id,
        )
    ).scalars().all()
    assert len(found_edges) == 1
    assert found_edges[0].target_symbol_id == callee_sym.id
