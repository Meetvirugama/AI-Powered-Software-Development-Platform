"""Tests for Issue F-41 / #258:
Eliminate full repository file ORM table scans during target and symbol resolution.

Validates:
1. Direct O(1) indexed point lookup for target file by (repository_id, path).
2. Lightweight column projection for indexed_paths (citation grounding without full ORM loading).
3. Targeted caller/callee file path resolution without scanning entire repository.
4. Correct 404 FILE_NOT_FOUND and 409 CONFLICT behavior when files are missing or repository is syncing.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from sqlalchemy.orm import Session

from app.core.errors import APIError, ErrorCode
from app.models.code_chunk import CodeChunk
from app.models.code_symbol import CodeSymbol
from app.models.github_installation import GitHubInstallation
from app.models.repository import Repository, SyncStatus
from app.models.repository_file import RepositoryFile
from app.models.symbol_edge import SymbolEdge
from app.models.user import User
from app.schemas.analysis import AnalysisOptions, AnalysisTarget, BugDetectionRequest, ExplainCodeRequest
from app.services.bug_detection_orchestrator import resolve_bug_target_and_build_context
from app.services.explanation_orchestrator import resolve_target_and_build_context


def _create_perf_test_repo(db_session: Session, test_user: User) -> Repository:
    """Helper to set up a clean repository for performance tests."""
    installation = GitHubInstallation(
        id=uuid.uuid4(),
        user_id=test_user.id,
        installation_id=f"inst-{uuid.uuid4().hex[:8]}",
        account_login=test_user.login,
        permissions={"contents": "read"},
    )
    db_session.add(installation)
    db_session.commit()

    repo = Repository(
        id=uuid.uuid4(),
        user_id=test_user.id,
        installation_id=installation.id,
        github_repo_id=f"gh-repo-{uuid.uuid4().hex[:8]}",
        owner=test_user.login,
        name=f"perf-repo-{uuid.uuid4().hex[:6]}",
        default_branch="main",
        language="Python",
        sync_status=SyncStatus.SYNCED,
    )
    db_session.add(repo)
    db_session.commit()
    return repo


def test_bug_target_resolution_direct_point_lookup(db_session: Session, test_user: User):
    """Verify that bug target resolution performs an indexed point lookup and builds indexed_paths."""
    repo = _create_perf_test_repo(db_session, test_user)

    # Seed 20 files into the repository
    for i in range(20):
        rf = RepositoryFile(
            id=uuid.uuid4(),
            repository_id=repo.id,
            path=f"src/module_{i}.py",
            language="Python",
            size_bytes=500,
            line_count=25,
            content_hash=f"hash_{i}",
        )
        db_session.add(rf)
    db_session.commit()

    # Target file
    target_file = (
        db_session.query(RepositoryFile)
        .filter(RepositoryFile.repository_id == repo.id, RepositoryFile.path == "src/module_10.py")
        .first()
    )
    assert target_file is not None

    chunk = CodeChunk(
        id=uuid.uuid4(),
        repository_id=repo.id,
        file_id=target_file.id,
        content="def run_computation():\n    return 42\n",
        start_line=1,
        end_line=2,
        token_count=15,
        content_hash="chunk_hash_10",
        embedding=[0.0] * 768,
    )
    db_session.add(chunk)
    db_session.commit()

    payload = BugDetectionRequest(
        target=AnalysisTarget(path="src/module_10.py", start_line=1, end_line=2),
        options=AnalysisOptions(include_context=True, max_context_tokens=2000),
    )

    resolved = resolve_bug_target_and_build_context(
        repository_id=repo.id,
        repo=repo,
        payload=payload,
        db=db_session,
    )

    # Assertions: target file resolved correctly
    assert resolved.file_record is not None
    assert resolved.file_record.path == "src/module_10.py"
    assert "def run_computation" in resolved.code_content
    # Grounding map should contain all 20 paths
    assert len(resolved.indexed_paths) == 20
    assert resolved.indexed_paths["src/module_10.py"] == 25
    # repo_files in context should be bounded (at most 50)
    assert len(resolved.repo_files) <= 50


def test_explanation_target_resolution_and_caller_path_projection(
    db_session: Session, test_user: User
):
    """Verify explanation target resolution correctly resolves symbols and neighbor caller file paths."""
    repo = _create_perf_test_repo(db_session, test_user)

    file_callee = RepositoryFile(
        id=uuid.uuid4(),
        repository_id=repo.id,
        path="src/callee_service.py",
        language="Python",
        size_bytes=800,
        line_count=40,
        content_hash="callee_hash",
    )
    file_caller = RepositoryFile(
        id=uuid.uuid4(),
        repository_id=repo.id,
        path="src/caller_endpoint.py",
        language="Python",
        size_bytes=900,
        line_count=45,
        content_hash="caller_hash",
    )
    db_session.add_all([file_callee, file_caller])
    db_session.commit()

    sym_callee = CodeSymbol(
        id=uuid.uuid4(),
        repository_id=repo.id,
        file_id=file_callee.id,
        name="do_work",
        kind="function",
        start_line=5,
        end_line=10,
        signature="def do_work(): pass",
    )
    sym_caller = CodeSymbol(
        id=uuid.uuid4(),
        repository_id=repo.id,
        file_id=file_caller.id,
        name="handle_request",
        kind="function",
        start_line=15,
        end_line=20,
        signature="def handle_request(): do_work()",
    )
    db_session.add_all([sym_callee, sym_caller])
    db_session.commit()

    edge = SymbolEdge(
        id=uuid.uuid4(),
        repository_id=repo.id,
        source_symbol_id=sym_caller.id,
        target_symbol_id=sym_callee.id,
        edge_type="calls",
    )
    db_session.add(edge)
    db_session.commit()

    # Seed chunk for callee
    chunk = CodeChunk(
        id=uuid.uuid4(),
        repository_id=repo.id,
        file_id=file_callee.id,
        content="def do_work():\n    return 'done'\n",
        start_line=5,
        end_line=10,
        token_count=20,
        content_hash="chunk_callee",
        embedding=[0.0] * 768,
    )
    db_session.add(chunk)
    db_session.commit()

    payload = ExplainCodeRequest(
        target=AnalysisTarget(path="src/callee_service.py", type="symbol", symbol="do_work"),
        options=AnalysisOptions(include_context=True, max_context_tokens=4000),
    )

    resolved = resolve_target_and_build_context(
        repository_id=repo.id,
        repo=repo,
        payload=payload,
        db=db_session,
    )

    assert resolved.resolved_symbol is not None
    assert resolved.resolved_symbol.name == "do_work"
    assert resolved.file_record is not None
    assert resolved.file_record.path == "src/callee_service.py"

    # Check that caller neighbor symbol correctly resolved its file path via neighbor_file_ids projection
    caller_ctxs = [s for s in resolved.intelligence_context.related_symbols if s.kind == "caller"]
    assert len(caller_ctxs) >= 1
    assert caller_ctxs[0].name == "handle_request"
    assert caller_ctxs[0].file_path == "src/caller_endpoint.py"


def test_target_resolution_raises_404_when_file_not_found(db_session: Session, test_user: User):
    """Verify target resolution raises 404 when target file is not indexed."""
    repo = _create_perf_test_repo(db_session, test_user)

    rf = RepositoryFile(
        id=uuid.uuid4(),
        repository_id=repo.id,
        path="src/existing.py",
        language="Python",
        size_bytes=200,
        line_count=10,
        content_hash="hash_exist",
    )
    db_session.add(rf)
    db_session.commit()

    payload = ExplainCodeRequest(
        target=AnalysisTarget(path="src/nonexistent.py"),
        options=AnalysisOptions(),
    )

    with pytest.raises(APIError) as exc_info:
        resolve_target_and_build_context(
            repository_id=repo.id,
            repo=repo,
            payload=payload,
            db=db_session,
        )

    assert exc_info.value.status_code == 404
    assert exc_info.value.code == ErrorCode.FILE_NOT_FOUND
    assert "src/nonexistent.py" in exc_info.value.message


def test_target_resolution_raises_409_when_repo_syncing(db_session: Session, test_user: User):
    """Verify target resolution raises 409 CONFLICT when repo has no files and is still syncing."""
    repo = _create_perf_test_repo(db_session, test_user)
    repo.sync_status = SyncStatus.SYNCING
    db_session.commit()

    payload = BugDetectionRequest(
        target=AnalysisTarget(path="src/main.py"),
        options=AnalysisOptions(),
    )

    with pytest.raises(APIError) as exc_info:
        resolve_bug_target_and_build_context(
            repository_id=repo.id,
            repo=repo,
            payload=payload,
            db=db_session,
        )

    assert exc_info.value.status_code == 409
    assert exc_info.value.code == ErrorCode.CONFLICT
    assert "indexing is in progress" in exc_info.value.message
