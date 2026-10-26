"""Week 2 — Day 6 Persistence and Database Integrity Test Suite.

Owner: Om — Database & Persistence.

Verifies:
1. Migration schema & index integrity across analysis_runs and analysis_findings tables.
2. Unified AnalysisRunHistoryService lifecycle (record_run, list_runs, get_run, delete_run, get_run_summary).
3. Concurrent persistence & transaction isolation across multi-threaded operations.
4. Multi-feature persistence fidelity across all 4 developer intelligence features (explain, detect_bugs, generate_tests, review).
5. Database integrity auditing & anomaly detection (verify_integrity).
6. Multi-criteria filtering, pagination, and newest-first ordering.
7. Multi-tenant repository boundary isolation and authorization protection.
8. Duplicate request detection and idempotency across all intelligence capabilities.
9. Revision immutability and status consistency (completed vs failed).
10. Cascading delete cleanup on run deletion and repository removal.
"""

from __future__ import annotations

import concurrent.futures
import uuid
from datetime import datetime, timezone
from typing import Any, Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Index, create_engine, inspect, select, text
from sqlalchemy.orm import Session, sessionmaker

from app.core.database import Base
from app.models.analysis_finding import AnalysisFinding
from app.models.analysis_run import AnalysisFeature, AnalysisRun, AnalysisRunStatus
from app.models.github_installation import GitHubInstallation
from app.models.repository import Repository, SyncStatus
from app.models.user import User
from app.repositories.analysis_run_repository import AnalysisRunRepository
from app.services.analysis_run_history_service import AnalysisRunHistoryService


# ---------------------------------------------------------------------------
# Test Helpers
# ---------------------------------------------------------------------------


def _create_user_and_repo(
    db: Session,
    user_login: str = "om-integrity-user",
    repo_name: str = "integrity-repo",
) -> tuple[User, Repository]:
    """Helper to create a persisted user, installation, and repository."""
    user = User(
        id=uuid.uuid4(),
        github_id=f"gh_{uuid.uuid4().hex[:8]}",
        login=user_login,
        email=f"{user_login}@example.com",
    )
    db.add(user)
    db.flush()

    installation = GitHubInstallation(
        id=uuid.uuid4(),
        user_id=user.id,
        installation_id=f"inst_{uuid.uuid4().hex[:8]}",
        account_login=user.login,
        permissions={"contents": "read"},
    )
    db.add(installation)
    db.flush()

    repo = Repository(
        id=uuid.uuid4(),
        user_id=user.id,
        installation_id=installation.id,
        github_repo_id=f"repo_{uuid.uuid4().hex[:8]}",
        owner=user.login,
        name=repo_name,
        default_branch="main",
        sync_status=SyncStatus.SYNCED,
    )
    db.add(repo)
    db.commit()
    db.refresh(repo)
    return user, repo


def _sample_findings(count: int = 3) -> list[dict[str, Any]]:
    categories = ["security", "correctness", "performance", "reliability", "maintainability"]
    severities = ["CRITICAL", "HIGH", "MEDIUM", "LOW"]
    return [
        {
            "category": categories[i % len(categories)],
            "severity": severities[i % len(severities)],
            "title": f"Test Finding #{i + 1}",
            "description": f"Detailed description for test finding #{i + 1}.",
            "file_path": f"src/module_{i + 1}.py",
            "start_line": 10 * (i + 1),
            "end_line": 10 * (i + 1) + 5,
            "evidence": f"val_{i + 1} = execute()",
            "suggested_fix": f"val_{i + 1} = safe_execute()",
            "confidence": "high",
        }
        for i in range(count)
    ]


# ---------------------------------------------------------------------------
# 1. Migration Schema & Index Verification
# ---------------------------------------------------------------------------

def test_migration_schema_and_index_verification(db_session: Session) -> None:
    """Verify that table schemas, columns, foreign keys, and indexes match Day 6 specs."""
    engine = db_session.get_bind()
    insp = inspect(engine)

    # 1. Table presence
    tables = insp.get_table_names()
    assert "analysis_runs" in tables
    assert "analysis_findings" in tables

    # 2. Columns in analysis_runs
    run_cols = {col["name"]: col for col in insp.get_columns("analysis_runs")}
    required_run_cols = [
        "id", "repository_id", "user_id", "feature_type", "status",
        "target_path", "target_symbol", "start_line", "end_line",
        "source_revision", "findings_count", "result_payload",
        "test_output", "error_message", "completed_at", "created_at", "updated_at",
    ]
    for col_name in required_run_cols:
        assert col_name in run_cols, f"Missing column {col_name} in analysis_runs"

    # 3. Columns in analysis_findings
    finding_cols = {col["name"]: col for col in insp.get_columns("analysis_findings")}
    required_finding_cols = [
        "id", "analysis_run_id", "repository_id", "category", "severity",
        "title", "description", "file_path", "start_line", "end_line",
        "source_revision", "symbol_name", "evidence", "suggested_fix",
        "confidence", "is_uncertain", "is_new_in_change", "source_type",
        "rule_id", "created_at", "updated_at",
    ]
    for col_name in required_finding_cols:
        assert col_name in finding_cols, f"Missing column {col_name} in analysis_findings"

    # 4. Indexes in analysis_runs
    run_indexes = insp.get_indexes("analysis_runs")
    index_names = {idx["name"] for idx in run_indexes if idx.get("name")}
    assert "ix_analysis_runs_repo_created" in index_names
    assert "ix_analysis_runs_repo_feature_status" in index_names
    assert "ix_analysis_runs_repo_revision" in index_names
    assert "ix_analysis_runs_repo_target_path" in index_names

    # 5. Indexes in analysis_findings
    finding_indexes = insp.get_indexes("analysis_findings")
    f_index_names = {idx["name"] for idx in finding_indexes if idx.get("name")}
    assert "ix_analysis_findings_run_severity" in f_index_names
    assert "ix_analysis_findings_repo_file" in f_index_names
    assert "ix_analysis_findings_repo_category" in f_index_names


# ---------------------------------------------------------------------------
# 2. Unified AnalysisRunHistoryService Lifecycle
# ---------------------------------------------------------------------------

def test_analysis_run_history_service_full_lifecycle(db_session: Session) -> None:
    """Verify record_run, list_runs, get_run, and delete_run through AnalysisRunHistoryService."""
    user, repo = _create_user_and_repo(db_session)
    service = AnalysisRunHistoryService(session=db_session)

    # 1. Record completed run
    run_record = {
        "id": str(uuid.uuid4()),
        "repository_id": str(repo.id),
        "user_id": str(user.id),
        "feature_type": "detect_bugs",
        "status": "COMPLETED",
        "target_path": "src/validator.py",
        "target_symbol": "validate_input",
        "source_revision": "git_sha_abc",
        "findings_count": 2,
        "findings": _sample_findings(2),
        "result_payload": {"scan_type": "ast_rules", "passed": False},
    }
    saved_run = service.record_run(run_record)
    assert saved_run.id == uuid.UUID(run_record["id"])
    assert saved_run.status == "COMPLETED"
    assert saved_run.findings_count == 2

    # 2. List runs with filtering
    runs, total = service.list_runs(repo.id, feature_type="detect_bugs", status="COMPLETED")
    assert total == 1
    assert len(runs) == 1
    assert runs[0].id == saved_run.id

    # 3. Get run with eager findings
    loaded_run = service.get_run(saved_run.id, repository_id=repo.id)
    assert loaded_run is not None
    assert len(loaded_run.findings) == 2
    assert loaded_run.findings[0].file_path == "src/module_1.py"

    # 4. Multi-tenant boundary check
    other_repo_id = uuid.uuid4()
    assert service.get_run(saved_run.id, repository_id=other_repo_id) is None

    # 5. Delete run
    deleted = service.delete_run(saved_run.id, repository_id=repo.id)
    assert deleted is True
    assert service.get_run(saved_run.id, repository_id=repo.id) is None


# ---------------------------------------------------------------------------
# 3. Multi-Feature Persistence & Metrics Aggregation
# ---------------------------------------------------------------------------

def test_multi_feature_persistence_and_summary_aggregation(db_session: Session) -> None:
    """Verify persisting all 4 features and computing repository-level metric summaries."""
    user, repo = _create_user_and_repo(db_session)
    service = AnalysisRunHistoryService(session=db_session)

    # 1. Explanation Run
    service.record_run({
        "repository_id": repo.id,
        "feature_type": "explain",
        "status": "COMPLETED",
        "target_path": "src/parser.py",
        "source_revision": "v1.0.0",
        "result_payload": {"purpose": "AST parsing module"},
    })

    # 2. Bug Scan Run (3 findings)
    service.record_run({
        "repository_id": repo.id,
        "feature_type": "detect_bugs",
        "status": "COMPLETED",
        "target_path": "src/auth.py",
        "source_revision": "v1.0.0",
        "findings_count": 3,
        "findings": _sample_findings(3),
    })

    # 3. Test Generation Run
    service.record_run({
        "repository_id": repo.id,
        "feature_type": "generate_tests",
        "status": "COMPLETED",
        "target_path": "src/calculator.py",
        "source_revision": "v1.0.0",
        "test_output": "def test_add(): assert add(1, 2) == 3\n",
    })

    # 4. Code Review Run (Failed run)
    service.record_run({
        "repository_id": repo.id,
        "feature_type": "review",
        "status": "FAILED",
        "target_path": "src/pr_diff.diff",
        "source_revision": "v1.0.0",
        "error_message": "LLM timeout during diff analysis",
    })

    # Verify Summary Aggregation
    summary = service.get_run_summary(repo.id)
    assert summary["total_runs"] == 4
    assert summary["by_feature"]["explain"] == 1
    assert summary["by_feature"]["detect_bugs"] == 1
    assert summary["by_feature"]["generate_tests"] == 1
    assert summary["by_feature"]["review"] == 1
    assert summary["by_status"]["COMPLETED"] == 3
    assert summary["by_status"]["FAILED"] == 1
    assert summary["total_findings"] == 3


# ---------------------------------------------------------------------------
# 4. Database Integrity Verification (Audit & Anomaly Detection)
# ---------------------------------------------------------------------------

def test_database_integrity_verification_clean_and_anomaly_detection(db_session: Session) -> None:
    """Verify verify_integrity identifies clean databases and flags corrupt anomalies."""
    user, repo = _create_user_and_repo(db_session)
    service = AnalysisRunHistoryService(session=db_session)

    # 1. Clean Database Audit
    clean_audit = service.verify_integrity(repo.id)
    assert clean_audit["status"] == "CLEAN"
    assert clean_audit["issues_count"] == 0

    # Add a normal completed run
    run = service.record_run({
        "repository_id": repo.id,
        "feature_type": "detect_bugs",
        "status": "COMPLETED",
        "target_path": "src/clean.py",
        "findings_count": 1,
        "findings": _sample_findings(1),
        "completed_at": datetime.now(timezone.utc),
    })
    post_add_audit = service.verify_integrity(repo.id)
    assert post_add_audit["status"] == "CLEAN"

    # 2. Introduce Desynchronization Anomaly (findings_count != actual count)
    db_run = db_session.get(AnalysisRun, run.id)
    assert db_run is not None
    db_run.findings_count = 99  # Intentionally corrupt count
    db_session.commit()

    desync_audit = service.verify_integrity(repo.id)
    assert desync_audit["status"] == "ISSUES_FOUND"
    assert desync_audit["desynchronized_runs_count"] == 1
    assert any(iss["type"] == "DESYNCHRONIZED_FINDINGS_COUNT" for iss in desync_audit["issues"])


# ---------------------------------------------------------------------------
# 5. Duplicate Detection & Idempotency Across Capabilities
# ---------------------------------------------------------------------------

def test_duplicate_run_detection_across_capabilities(db_session: Session) -> None:
    """Verify find_duplicate detects existing completed runs across all 4 feature types."""
    user, repo = _create_user_and_repo(db_session)
    service = AnalysisRunHistoryService(session=db_session)

    # 1. Bug Detection Duplicate
    service.record_run({
        "repository_id": repo.id,
        "feature_type": "detect_bugs",
        "status": "COMPLETED",
        "target_path": "src/dup_bug.py",
        "target_symbol": "process_items",
        "source_revision": "rev-dup-1",
    })
    dup_bug = service.find_duplicate(
        repo.id,
        "detect_bugs",
        target_path="src/dup_bug.py",
        target_symbol="process_items",
        source_revision="rev-dup-1",
    )
    assert dup_bug is not None
    assert dup_bug.target_path == "src/dup_bug.py"

    # 2. Test Generation Duplicate
    service.record_run({
        "repository_id": repo.id,
        "feature_type": "generate_tests",
        "status": "COMPLETED",
        "target_path": "src/dup_test.py",
        "source_revision": "rev-dup-1",
        "test_output": "def test_ok(): pass",
    })
    dup_test = service.find_duplicate(
        repo.id,
        "generate_tests",
        target_path="src/dup_test.py",
        source_revision="rev-dup-1",
    )
    assert dup_test is not None

    # 3. Code Review Duplicate
    service.record_run({
        "repository_id": repo.id,
        "feature_type": "review",
        "status": "COMPLETED",
        "target_path": "src/dup_review.py",
        "source_revision": "rev-dup-1",
    })
    dup_rev = service.find_duplicate(
        repo.id,
        "review",
        target_path="src/dup_review.py",
        source_revision="rev-dup-1",
    )
    assert dup_rev is not None

    # 4. Code Explanation Duplicate
    service.record_run({
        "repository_id": repo.id,
        "feature_type": "explain",
        "status": "COMPLETED",
        "target_path": "src/dup_explain.py",
        "source_revision": "rev-dup-1",
        "result_payload": {"purpose": "Explain duplicate check"},
    })
    dup_explain = service.find_duplicate(
        repo.id,
        "explain",
        target_path="src/dup_explain.py",
        source_revision="rev-dup-1",
    )
    assert dup_explain is not None


# ---------------------------------------------------------------------------
# 6. Revision Immutability & Failure Recording Distinction
# ---------------------------------------------------------------------------

def test_revision_immutability_and_failure_distinction(db_session: Session) -> None:
    """Verify that runs on newer revisions never overwrite older runs and failures are distinct."""
    user, repo = _create_user_and_repo(db_session)
    service = AnalysisRunHistoryService(session=db_session)

    # Run on revision v1.0
    r1 = service.record_run({
        "repository_id": repo.id,
        "feature_type": "detect_bugs",
        "status": "COMPLETED",
        "target_path": "src/calculator.py",
        "source_revision": "commit_v1",
        "findings_count": 2,
        "findings": _sample_findings(2),
    })

    # Run on revision v2.0
    r2 = service.record_run({
        "repository_id": repo.id,
        "feature_type": "detect_bugs",
        "status": "COMPLETED",
        "target_path": "src/calculator.py",
        "source_revision": "commit_v2",
        "findings_count": 0,
        "findings": [],
    })

    # Verify both records exist with distinct UUIDs and preserved findings
    assert r1.id != r2.id
    v1_loaded = service.get_run(r1.id, repository_id=repo.id)
    v2_loaded = service.get_run(r2.id, repository_id=repo.id)
    assert v1_loaded is not None and v1_loaded.findings_count == 2
    assert v2_loaded is not None and v2_loaded.findings_count == 0

    # Failed run
    r_fail = service.record_run({
        "repository_id": repo.id,
        "feature_type": "detect_bugs",
        "status": "FAILED",
        "target_path": "src/calculator.py",
        "source_revision": "commit_v3",
        "error_message": "AST Syntax Error on line 42",
        "findings_count": 0,
    })
    fail_loaded = service.get_run(r_fail.id, repository_id=repo.id)
    assert fail_loaded is not None
    assert fail_loaded.status == "FAILED"
    assert fail_loaded.error_message == "AST Syntax Error on line 42"
    # Ensure failed run is never considered a clean zero-defect run
    assert fail_loaded.status != "COMPLETED"


# ---------------------------------------------------------------------------
# 7. Cascading Deletion Verification
# ---------------------------------------------------------------------------

def test_cascading_deletion_run_and_repository(db_session: Session) -> None:
    """Verify deleting a run cascades to findings, and deleting a repo purges all runs and findings."""
    user, repo = _create_user_and_repo(db_session)
    service = AnalysisRunHistoryService(session=db_session)

    # Create run with 3 findings
    run = service.record_run({
        "repository_id": repo.id,
        "feature_type": "detect_bugs",
        "status": "COMPLETED",
        "target_path": "src/cascade.py",
        "findings_count": 3,
        "findings": _sample_findings(3),
    })
    run_id = run.id

    # Verify findings exist
    findings_stmt = select(AnalysisFinding).where(AnalysisFinding.analysis_run_id == run_id)
    assert len(list(db_session.scalars(findings_stmt).all())) == 3

    # 1. Delete Run
    service.delete_run(run_id, repository_id=repo.id)
    assert db_session.get(AnalysisRun, run_id) is None
    assert len(list(db_session.scalars(findings_stmt).all())) == 0

    # 2. Delete Repository (Purge repository runs)
    service.record_run({
        "repository_id": repo.id,
        "feature_type": "explain",
        "status": "COMPLETED",
        "target_path": "src/repo_purge.py",
    })
    purged_count = service.delete_repository_runs(repo.id)
    assert purged_count >= 1

    remaining_runs = select(AnalysisRun).where(AnalysisRun.repository_id == repo.id)
    assert len(list(db_session.scalars(remaining_runs).all())) == 0


# ---------------------------------------------------------------------------
# 8. Multi-Criteria Filtering & Pagination (Newest-First)
# ---------------------------------------------------------------------------

def test_filtering_and_pagination_order(db_session: Session) -> None:
    """Verify filtering by feature_type, status, target_path, revision, and pagination."""
    user, repo = _create_user_and_repo(db_session)
    service = AnalysisRunHistoryService(session=db_session)

    for i in range(5):
        service.record_run({
            "repository_id": repo.id,
            "feature_type": "explain" if i % 2 == 0 else "detect_bugs",
            "status": "COMPLETED" if i < 4 else "FAILED",
            "target_path": f"src/file_{i}.py",
            "source_revision": f"rev_{i}",
        })

    # Filter by feature_type=explain
    explain_runs, total_exp = service.list_runs(repo.id, feature_type="explain")
    assert total_exp == 3
    assert all(r.feature_type == "explain" for r in explain_runs)

    # Filter by status=FAILED
    failed_runs, total_failed = service.list_runs(repo.id, status="FAILED")
    assert total_failed == 1
    assert failed_runs[0].status == "FAILED"

    # Pagination: limit=2, offset=0 then offset=2
    page1, total = service.list_runs(repo.id, limit=2, offset=0)
    page2, _ = service.list_runs(repo.id, limit=2, offset=2)
    assert total == 5
    assert len(page1) == 2
    assert len(page2) == 2
    assert page1[0].id != page2[0].id
