"""Analysis persistence tests."""

from __future__ import annotations

import uuid
from datetime import datetime
from datetime import timezone
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.orm import sessionmaker
from app.core.database import Base
from app.models.analysis_finding import AnalysisFinding
from app.models.analysis_run import AnalysisFeature
from app.models.analysis_run import AnalysisRun
from app.models.analysis_run import AnalysisRunStatus
from app.models.github_installation import GitHubInstallation
from app.models.repository import Repository
from app.models.repository import SyncStatus
from app.models.user import User
from app.repositories.analysis_run_repository import AnalysisRunRepository
from app.repositories.repository_repository import RepositoryRepository
import concurrent.futures
from typing import Any
from typing import Generator
from fastapi.testclient import TestClient
from sqlalchemy import Index
from sqlalchemy import inspect
from sqlalchemy import select
from sqlalchemy import text
from app.services.analysis_run_history_service import AnalysisRunHistoryService
import os
import re
from datetime import timedelta
from pathlib import Path
from app.repositories.analysis_run_repository import scrub_sensitive_data
from app.repositories.analysis_run_repository import scrub_sensitive_text
from app.services.bug_scan_history_service import BugScanHistoryService
from app.services.explanation_history_service import ExplanationHistoryService
from app.services.review_history_service import ReviewHistoryService
from app.services.test_generation_history_service import TestGenerationHistoryService
from app.models import RepositoryFile
from app.models import CodeSymbol
from app.models import SymbolEdge
from app.models import CodeChunk
from app.models import MemoryEntry
from app.models import MemoryType
from app.models import MemoryStatus
from app.core.config import get_settings
from app.core.database import normalize_sync_database_url


# Persistence and database integrity tests for Week 2 Day 1 (Analysis Persistence).

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _create_test_user_and_repo(
    db: Session,
    login: str = "test-user",
    repo_name: str = "test-repo",
) -> tuple[User, Repository]:
    """Helper to seed valid User and Repository records for FK constraints."""
    user = User(
        id=uuid.uuid4(),
        github_id=f"gh_{uuid.uuid4().hex[:8]}",
        login=login,
        email=f"{login}@example.com",
    )
    db.add(user)
    db.flush()

    installation = GitHubInstallation(
        id=uuid.uuid4(),
        user_id=user.id,
        installation_id=f"inst_{uuid.uuid4().hex[:8]}",
        account_login=login,
        permissions={"contents": "read"},
    )
    db.add(installation)
    db.flush()

    repo = Repository(
        id=uuid.uuid4(),
        user_id=user.id,
        installation_id=installation.id,
        github_repo_id=f"repo_{uuid.uuid4().hex[:8]}",
        owner=login,
        name=repo_name,
        default_branch="main",
        sync_status=SyncStatus.SYNCED,
    )
    db.add(repo)
    db.commit()
    db.refresh(repo)
    return user, repo


# ---------------------------------------------------------------------------
# 1. Model & Repository Creation Tests
# ---------------------------------------------------------------------------

def test_create_and_retrieve_analysis_run_explain(db_session: Session) -> None:
    """Verify creating and retrieving a Code Explanation analysis run."""
    user, repo = _create_test_user_and_repo(db_session)
    repo_layer = AnalysisRunRepository(db_session)

    run = repo_layer.create_run(
        repository_id=repo.id,
        user_id=user.id,
        feature_type="explain",
        status="COMPLETED",
        target_path="backend/app/main.py",
        target_symbol="create_app",
        start_line=15,
        end_line=45,
        source_revision="abc1234",
        result_payload={"purpose": "Initializes FastAPI application", "confidence": "high"},
    )

    assert run.id is not None
    assert run.repository_id == repo.id
    assert run.user_id == user.id
    assert run.feature_type == "explain"
    assert run.status == "COMPLETED"
    assert run.target_path == "backend/app/main.py"
    assert run.target_symbol == "create_app"
    assert run.start_line == 15
    assert run.end_line == 45
    assert run.source_revision == "abc1234"
    assert run.completed_at is not None
    assert run.result_payload == {"purpose": "Initializes FastAPI application", "confidence": "high"}

    # Fetch back
    fetched = repo_layer.get_by_id(run.id)
    assert fetched is not None
    assert fetched.id == run.id
    assert fetched.feature_type == "explain"


def test_create_run_with_structured_findings_bug_detection(db_session: Session) -> None:
    """Verify creating a Bug Detection run with attached findings."""
    user, repo = _create_test_user_and_repo(db_session)
    repo_layer = AnalysisRunRepository(db_session)

    findings_data = [
        {
            "id": str(uuid.uuid4()),
            "category": "off_by_one",
            "severity": "HIGH",
            "title": "Loop index out of bounds",
            "description": "Loop iterates <= length instead of < length.",
            "source_reference": {
                "file_path": "src/parser.py",
                "start_line": 20,
                "end_line": 25,
                "revision": "main",
                "symbol_name": "parse_tokens",
            },
            "evidence": "for i in range(len(tokens) + 1):",
            "suggested_fix": "for i in range(len(tokens)):",
            "confidence": "high",
            "source_type": "AI",
            "rule_id": "OFF_BY_ONE_001",
        },
        {
            "id": str(uuid.uuid4()),
            "category": "security",
            "severity": "CRITICAL",
            "title": "Potential SQL injection",
            "description": "Raw string formatting in SQL query.",
            "source_reference": {
                "file_path": "src/db.py",
                "start_line": 50,
                "end_line": 52,
                "revision": "main",
                "symbol_name": "get_user",
            },
            "evidence": "f'SELECT * FROM users WHERE id = {user_id}'",
            "suggested_fix": "Use parameterized query with :user_id",
            "confidence": "high",
            "source_type": "STATIC",
            "rule_id": "B608",
        },
    ]

    run = repo_layer.create_run(
        repository_id=repo.id,
        user_id=user.id,
        feature_type="detect_bugs",
        status="COMPLETED",
        target_path="src/parser.py",
        source_revision="main",
        findings=findings_data,
    )

    assert run.findings_count == 2
    assert len(run.findings) == 2

    # Verify individual finding mapping
    critical_finding = next(f for f in run.findings if f.severity == "CRITICAL")
    assert critical_finding.category == "security"
    assert critical_finding.file_path == "src/db.py"
    assert critical_finding.start_line == 50
    assert critical_finding.end_line == 52
    assert critical_finding.rule_id == "B608"
    assert critical_finding.source_type == "STATIC"

    # Verify source_reference property
    ref = critical_finding.source_reference
    assert ref["file_path"] == "src/db.py"
    assert ref["start_line"] == 50
    assert ref["end_line"] == 52
    assert ref["repository_id"] == str(repo.id)

    # Verify to_dict output
    as_dict = critical_finding.to_dict()
    assert as_dict["id"] == str(critical_finding.id)
    assert as_dict["severity"] == "CRITICAL"
    assert as_dict["source_reference"] == ref


# ---------------------------------------------------------------------------
# 2. Multi-Tenant Repository Isolation Tests
# ---------------------------------------------------------------------------

def test_multi_tenant_repository_isolation(db_session: Session) -> None:
    """Verify that User A / Repo A runs and findings are never leaked to Repo B."""
    user_a, repo_a = _create_test_user_and_repo(db_session, "user_a", "repo_a")
    user_b, repo_b = _create_test_user_and_repo(db_session, "user_b", "repo_b")
    repo_layer = AnalysisRunRepository(db_session)

    # Repo A runs
    run_a1 = repo_layer.create_run(
        repository_id=repo_a.id,
        user_id=user_a.id,
        feature_type="explain",
        status="COMPLETED",
        target_path="secret_a.py",
    )
    run_a2 = repo_layer.create_run(
        repository_id=repo_a.id,
        user_id=user_a.id,
        feature_type="detect_bugs",
        status="COMPLETED",
        target_path="secret_a_bugs.py",
    )

    # Repo B run
    run_b = repo_layer.create_run(
        repository_id=repo_b.id,
        user_id=user_b.id,
        feature_type="review",
        status="COMPLETED",
        target_path="b_file.py",
    )

    # Querying Repo A must return only Repo A runs
    items_a, total_a = repo_layer.list_by_repository(repo_a.id)
    assert total_a == 2
    assert {r.id for r in items_a} == {run_a1.id, run_a2.id}
    assert all(r.repository_id == repo_a.id for r in items_a)

    # Querying Repo B must return only Repo B runs
    items_b, total_b = repo_layer.list_by_repository(repo_b.id)
    assert total_b == 1
    assert items_b[0].id == run_b.id
    assert items_b[0].repository_id == repo_b.id

    # Cross-repository direct lookup must return None
    cross_lookup = repo_layer.get_by_id_and_repository(run_a1.id, repo_b.id)
    assert cross_lookup is None


# ---------------------------------------------------------------------------
# 3. Filtering, Ordering, and Pagination Tests
# ---------------------------------------------------------------------------

def test_filtering_and_pagination(db_session: Session) -> None:
    """Verify filtering by feature_type, status, and paginating with limit/offset."""
    user, repo = _create_test_user_and_repo(db_session)
    repo_layer = AnalysisRunRepository(db_session)

    # Create multiple runs with different features and statuses
    repo_layer.create_run(repository_id=repo.id, user_id=user.id, feature_type="explain", status="COMPLETED")
    repo_layer.create_run(repository_id=repo.id, user_id=user.id, feature_type="explain", status="FAILED")
    repo_layer.create_run(repository_id=repo.id, user_id=user.id, feature_type="detect_bugs", status="COMPLETED")
    repo_layer.create_run(repository_id=repo.id, user_id=user.id, feature_type="detect_bugs", status="COMPLETED")
    repo_layer.create_run(repository_id=repo.id, user_id=user.id, feature_type="generate_tests", status="RUNNING")

    # Filter by feature_type
    explain_runs, total_explain = repo_layer.list_by_repository(repo.id, feature_type="explain")
    assert total_explain == 2
    assert len(explain_runs) == 2
    assert all(r.feature_type == "explain" for r in explain_runs)

    # Filter by status
    completed_runs, total_completed = repo_layer.list_by_repository(repo.id, status="COMPLETED")
    assert total_completed == 3
    assert len(completed_runs) == 3

    # Filter by both feature_type and status
    bugs_completed, total_bugs_completed = repo_layer.list_by_repository(
        repo.id, feature_type="detect_bugs", status="COMPLETED"
    )
    assert total_bugs_completed == 2
    assert len(bugs_completed) == 2

    # Pagination: limit=2, offset=0
    page1, total_all = repo_layer.list_by_repository(repo.id, limit=2, offset=0)
    assert total_all == 5
    assert len(page1) == 2

    # Pagination: limit=2, offset=2
    page2, _ = repo_layer.list_by_repository(repo.id, limit=2, offset=2)
    assert len(page2) == 2
    assert page1[0].id != page2[0].id


# ---------------------------------------------------------------------------
# 4. Large Test Output Persistence Tests
# ---------------------------------------------------------------------------

def test_large_generated_test_output_storage(db_session: Session) -> None:
    """Verify storing large test files in dedicated test_output column and result_payload."""
    user, repo = _create_test_user_and_repo(db_session)
    repo_layer = AnalysisRunRepository(db_session)

    # Generate a large test file (approx 60 KB)
    large_test_content = (
        "import pytest\n\n"
        + "\n".join(
            f"def test_scenario_{i}():\n    assert {i} * 2 == {i * 2}\n"
            for i in range(1200)
        )
    )
    assert len(large_test_content) > 50_000

    payload = {
        "detected_framework": "pytest",
        "proposed_test_path": "tests/test_generated_large.py",
        "test_content": large_test_content,
        "scenarios": ["scenario_1", "scenario_2"],
    }

    run = repo_layer.create_run(
        repository_id=repo.id,
        user_id=user.id,
        feature_type="generate_tests",
        status="COMPLETED",
        target_path="src/calc.py",
        result_payload=payload,
    )

    # Must be saved without truncation
    assert run.test_output == large_test_content
    assert run.result_payload["test_content"] == large_test_content

    # Fetch back and verify exact byte preservation
    fetched = repo_layer.get_by_id(run.id)
    assert fetched is not None
    assert fetched.test_output == large_test_content
    assert len(fetched.test_output) == len(large_test_content)


# ---------------------------------------------------------------------------
# 5. Lifecycle Updates & Incremental Findings Tests
# ---------------------------------------------------------------------------

def test_run_status_lifecycle_and_incremental_findings(db_session: Session) -> None:
    """Verify transitioning run status from PENDING -> RUNNING -> COMPLETED."""
    user, repo = _create_test_user_and_repo(db_session)
    repo_layer = AnalysisRunRepository(db_session)

    run = repo_layer.create_run(
        repository_id=repo.id,
        user_id=user.id,
        feature_type="review",
        status="PENDING",
        target_path="src/feature.py",
    )
    assert run.status == "PENDING"
    assert run.completed_at is None

    # Transition to RUNNING
    run = repo_layer.update_status(run.id, "RUNNING")
    assert run.status == "RUNNING"
    assert run.completed_at is None

    # Append findings
    new_findings = [
        {
            "category": "performance",
            "severity": "MEDIUM",
            "title": "N+1 database query in loop",
            "description": "Query inside loop causes performance degradation.",
            "file_path": "src/feature.py",
            "start_line": 34,
            "end_line": 40,
            "evidence": "for item in items:\n    db.query(ItemDetail)...",
            "suggested_fix": "Use selectinload or joinedload",
        }
    ]
    added = repo_layer.add_findings(run.id, new_findings)
    assert len(added) == 1
    assert run.findings_count == 1

    # Transition to COMPLETED
    run = repo_layer.update_status(
        run.id,
        "COMPLETED",
        result_payload={"summary": "Review complete with 1 warning"},
    )
    assert run.status == "COMPLETED"
    assert run.completed_at is not None
    assert run.result_payload["summary"] == "Review complete with 1 warning"


def test_failed_analysis_run_stores_error_message(db_session: Session) -> None:
    """Verify that a failed analysis run preserves error_message and completed_at."""
    user, repo = _create_test_user_and_repo(db_session)
    repo_layer = AnalysisRunRepository(db_session)

    run = repo_layer.create_run(
        repository_id=repo.id,
        user_id=user.id,
        feature_type="explain",
        status="FAILED",
        target_path="broken.py",
        error_message="LLMTimeoutError: Provider took longer than 30s to respond.",
    )

    assert run.status == "FAILED"
    assert "LLMTimeoutError" in run.error_message
    assert run.completed_at is not None

    fetched = repo_layer.get_by_id(run.id)
    assert fetched.status == "FAILED"
    assert fetched.error_message == run.error_message


# ---------------------------------------------------------------------------
# 6. Cascade Deletion Tests
# ---------------------------------------------------------------------------

def test_delete_run_cascades_findings(db_session: Session) -> None:
    """Verify deleting an analysis run cascades deletion to its findings."""
    user, repo = _create_test_user_and_repo(db_session)
    repo_layer = AnalysisRunRepository(db_session)

    run = repo_layer.create_run(
        repository_id=repo.id,
        user_id=user.id,
        feature_type="detect_bugs",
        findings=[
            {
                "category": "null_safety",
                "severity": "HIGH",
                "title": "Unchecked None",
                "description": "accessing attr on None",
                "evidence": "val.attr",
                "file_path": "a.py",
            }
        ],
    )
    finding_id = run.findings[0].id
    assert db_session.get(AnalysisFinding, finding_id) is not None

    deleted = repo_layer.delete(run.id)
    assert deleted is True

    # Finding must be gone
    assert db_session.get(AnalysisFinding, finding_id) is None
    assert db_session.get(AnalysisRun, run.id) is None


def test_repository_delete_cascades_analysis_data(db_session: Session) -> None:
    """Verify that deleting a repository deletes all analysis runs and findings."""
    user, repo = _create_test_user_and_repo(db_session)
    repo_layer = AnalysisRunRepository(db_session)
    repo_repo = RepositoryRepository(db_session)

    run = repo_layer.create_run(
        repository_id=repo.id,
        user_id=user.id,
        feature_type="review",
        findings=[
            {
                "category": "maintainability",
                "severity": "LOW",
                "title": "Long method",
                "description": "Method exceeds 80 lines",
                "evidence": "def long_method()...",
                "file_path": "m.py",
            }
        ],
    )
    run_id = run.id
    finding_id = run.findings[0].id

    # Delete repository via RepositoryRepository.delete
    res = repo_repo.delete(repo.id)
    assert res is True

    # Both run and finding must be removed
    assert db_session.get(AnalysisRun, run_id) is None
    assert db_session.get(AnalysisFinding, finding_id) is None


# ---------------------------------------------------------------------------
# 7. Orchestrator record_analysis_run Compatibility Test
# ---------------------------------------------------------------------------

def test_record_analysis_run_compatibility(db_session: Session) -> None:
    """Verify that kwargs passed by explanation_orchestrator.py persist cleanly."""
    user, repo = _create_test_user_and_repo(db_session)
    repo_layer = AnalysisRunRepository(db_session)

    # Replicate exact kwargs structure emitted by record_analysis_run in explanation_orchestrator.py
    run_id = str(uuid.uuid4())
    record = {
        "id": run_id,
        "repository_id": repo.id,
        "user_id": user.id,
        "feature_type": "explain",
        "status": "COMPLETED",
        "target_path": "backend/app/main.py",
        "target_symbol": None,
        "start_line": 1,
        "end_line": 20,
        "source_revision": "main",
        "findings_count": 0,
        "result_payload": {"purpose": "API entrypoint"},
        "findings": [],
        "error_message": None,
        "created_at": datetime.now(timezone.utc),
        "completed_at": datetime.now(timezone.utc),
    }

    # Must execute without error
    persisted = repo_layer.create_run(**record)
    assert str(persisted.id) == run_id
    assert persisted.status == "COMPLETED"
    assert persisted.target_path == "backend/app/main.py"
    assert persisted.result_payload == {"purpose": "API entrypoint"}


# Week 2 — Day 6 Persistence and Database Integrity Test Suite.

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


# Week 2 — Day 7 Acceptance, Regression & Verification Test Suite.

# ---------------------------------------------------------------------------
# Test Helpers & Fixture Builders
# ---------------------------------------------------------------------------

def _create_regression_user_and_repo(
    db: Session,
    user_login: str = "om-day7-user",
    repo_name: str = "day7-acceptance-repo",
) -> tuple[User, Repository]:
    """Create and persist a user, GitHub installation, and repository."""
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
        permissions={"contents": "read", "issues": "write"},
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


# ---------------------------------------------------------------------------
# 1. Verification of Analysis Persistence & History Retrieval (All 4 Features)
# ---------------------------------------------------------------------------

class TestDay7AnalysisPersistenceAndRetrieval:
    """Verifies persistence, retrieval, and Scenario A-D reopening across all 4 features."""

    def test_feature1_code_explanation_persistence_and_reopening(self, db_session: Session):
        """Scenario A: Persist explanation run, retrieve metadata, reopen from history, and isolate failures."""
        user, repo = _create_regression_user_and_repo(db_session, "om-explain-user", "explain-repo")
        service = ExplanationHistoryService(session=db_session)

        # 1. Save completed explanation run (Scenario A Steps 4-6)
        explanation_payload = {
            "purpose": "Computes aggregate developer metrics for repository health.",
            "logic_flow": ["Validate inputs", "Aggregate commit stats", "Format JSON report"],
            "key_symbols": ["aggregate_metrics", "MetricCalculator"],
            "inputs_and_outputs": "Takes repo_id (UUID), returns dict of metric scores.",
            "dependencies": ["sqlalchemy", "pydantic"],
            "limitations": "Does not compute cross-repository benchmarks.",
            "sources": [{"file": "src/metrics.py", "lines": [10, 50]}],
        }

        run = service.save_explanation(
            repository_id=repo.id,
            target_path="src/metrics.py",
            explanation=explanation_payload,
            target_symbol="aggregate_metrics",
            start_line=10,
            end_line=50,
            source_revision="commit-abc1234",
            user_id=user.id,
        )
        assert run.id is not None
        assert run.status == AnalysisRunStatus.COMPLETED.value
        assert run.feature_type == AnalysisFeature.EXPLAIN.value

        # 2. Reopen explanation from history (Scenario A Step 7)
        reopened = service.reopen_explanation(run.id, repository_id=repo.id)
        assert reopened is not None
        assert reopened["status"] == "COMPLETED"
        assert reopened["target"]["path"] == "src/metrics.py"
        assert reopened["target"]["symbol"] == "aggregate_metrics"
        assert reopened["explanation"]["purpose"] == explanation_payload["purpose"]
        assert len(reopened["explanation"]["logic_flow"]) == 3

        # 3. Record failure separately without inventing fake results
        fail_run = service.record_failure(
            repository_id=repo.id,
            target_path="src/nonexistent.py",
            error_message="Target file not found in repository.",
            user_id=user.id,
        )
        assert fail_run.status == AnalysisRunStatus.FAILED.value
        assert "not found" in fail_run.error_message

    def test_feature2_bug_detection_persistence_and_reopening(self, db_session: Session):
        """Scenario B: Persist bug scan, attach categorized findings, check deduplication, and reopen."""
        user, repo = _create_regression_user_and_repo(db_session, "om-bug-user", "bug-repo")
        service = BugScanHistoryService(session=db_session)

        findings = [
            {
                "category": "security",
                "severity": "CRITICAL",
                "title": "SQL Injection in User Query",
                "description": "Unsanitized user parameter passed directly to raw SQL statement.",
                "file_path": "src/db/users.py",
                "start_line": 42,
                "end_line": 45,
                "evidence": 'conn.execute(f"SELECT * FROM users WHERE name = {user_input}")',
                "suggested_fix": 'conn.execute(text("SELECT * FROM users WHERE name = :name"), {"name": user_input})',
                "confidence": "high",
                "source_type": "COMBINED",
                "rule_id": "SEC001",
            },
            {
                "category": "correctness",
                "severity": "HIGH",
                "title": "Off-by-One Loop Indexing",
                "description": "Loop index exceeds array bounds when accessing buffer.",
                "file_path": "src/buffer.py",
                "start_line": 15,
                "end_line": 18,
                "evidence": "for i in range(len(buffer) + 1): process(buffer[i])",
                "suggested_fix": "for i in range(len(buffer)): process(buffer[i])",
                "confidence": "high",
                "source_type": "AI",
                "rule_id": "CORR002",
            },
        ]

        run = service.save_scan(
            repository_id=repo.id,
            target_path="src/db/users.py",
            findings=findings,
            target_symbol="get_user_by_name",
            start_line=40,
            end_line=55,
            source_revision="sha-known-defect-fixture",
            user_id=user.id,
        )
        assert run.id is not None
        assert run.findings_count == 2
        assert len(run.findings) == 2

        # Reopen bug scan (Scenario B Step 4)
        reopened = service.reopen_scan(run.id, repository_id=repo.id)
        assert reopened is not None
        assert reopened["status"] == "COMPLETED"
        assert len(reopened["findings"]) == 2
        categories = {f["category"] for f in reopened["findings"]}
        assert "security" in categories
        assert "correctness" in categories

        # Duplicate scan detection (Scenario B Step 6)
        repo_obj = AnalysisRunRepository(db_session)
        dup = repo_obj.find_duplicate_scan(
            repository_id=repo.id,
            target_path="src/db/users.py",
            target_symbol="get_user_by_name",
            start_line=40,
            end_line=55,
            source_revision="sha-known-defect-fixture",
        )
        assert dup is not None
        assert dup.id == run.id

    def test_feature3_test_generation_persistence_and_reopening(self, db_session: Session):
        """Scenario C: Persist generated test file, handle large output without truncation, and reopen."""
        user, repo = _create_regression_user_and_repo(db_session, "om-test-user", "test-gen-repo")
        service = TestGenerationHistoryService(session=db_session)

        test_code = (
            "import pytest\n"
            "from src.calculator import add\n\n"
            "def test_add_positive():\n"
            "    assert add(2, 3) == 5\n\n"
            "def test_add_negative():\n"
            "    assert add(-2, -3) == -5\n\n"
            "def test_add_overflow_boundary():\n"
            "    assert add(10**18, 10**18) == 2 * (10**18)\n"
        )

        test_result = {
            "test_path": "tests/test_calculator.py",
            "framework": "pytest",
            "test_content": test_code,
            "scenarios": [
                {"name": "test_add_positive", "type": "positive", "description": "Tests normal addition"},
                {"name": "test_add_negative", "type": "negative", "description": "Tests negative numbers"},
                {"name": "test_add_overflow_boundary", "type": "edge_case", "description": "Tests large numbers"},
            ],
            "explanation": "Generated 3 unit tests conforming to pytest framework conventions.",
        }

        run = service.save_test_generation(
            repository_id=repo.id,
            target_path="src/calculator.py",
            test_result=test_result,
            target_symbol="add",
            framework="pytest",
            source_revision="rev-calc-v1",
            user_id=user.id,
        )
        assert run.id is not None
        assert run.test_output == test_code
        assert run.feature_type == AnalysisFeature.GENERATE_TESTS.value

        # Reopen test generation (Scenario C Step 7)
        reopened = service.reopen_test_generation(run.id, repository_id=repo.id)
        assert reopened is not None
        assert reopened["status"] == "COMPLETED"
        assert reopened["result"]["framework"] == "pytest"
        assert reopened["result"]["test_path"] == "tests/test_calculator.py"
        assert reopened["result"]["test_content"] == test_code
        assert len(reopened["result"]["scenarios"]) == 3

    def test_feature4_code_review_persistence_and_reopening(self, db_session: Session):
        """Scenario D: Persist code review across 5 categories and multiple scopes (file, commit, pr diff)."""
        user, repo = _create_regression_user_and_repo(db_session, "om-review-user", "review-repo")
        service = ReviewHistoryService(session=db_session)

        review_findings = [
            {
                "category": "security",
                "severity": "CRITICAL",
                "title": "Insecure Deserialization",
                "description": "pickle.loads used on untrusted network payload.",
                "file_path": "app/worker.py",
                "start_line": 80,
                "end_line": 82,
                "evidence": "data = pickle.loads(raw_stream)",
                "suggested_fix": "data = json.loads(raw_stream.decode('utf-8'))",
                "confidence": "high",
            },
            {
                "category": "performance",
                "severity": "MEDIUM",
                "title": "N+1 Database Query in Loop",
                "description": "Repository queries user profiles in an unbatched loop.",
                "file_path": "app/services.py",
                "start_line": 120,
                "end_line": 125,
                "evidence": "for uid in user_ids: db.query(Profile).filter_by(user_id=uid).first()",
                "suggested_fix": "db.query(Profile).filter(Profile.user_id.in_(user_ids)).all()",
                "confidence": "high",
            },
            {
                "category": "maintainability",
                "severity": "LOW",
                "title": "Missing Docstring on Exported API",
                "description": "Public method lacks docstring describing parameters.",
                "file_path": "app/api.py",
                "start_line": 10,
                "end_line": 12,
                "evidence": "def handle_webhook(event): pass",
                "suggested_fix": "def handle_webhook(event):\n    '''Handle incoming webhook notification.'''",
                "confidence": "medium",
            },
        ]

        review_report = {
            "summary": "Review detected 1 critical security defect, 1 performance regression, and 1 style issue.",
            "risk_score": 75,
            "findings": review_findings,
            "target_type": "commit",
            "commit_sha": "commit-rev-9999",
            "files_analyzed": ["app/worker.py", "app/services.py", "app/api.py"],
        }

        run = service.save_review(
            repository_id=repo.id,
            review_report=review_report,
            review_target="commit",
            commit_sha="commit-rev-9999",
            source_revision="commit-rev-9999",
            user_id=user.id,
        )
        assert run.id is not None
        assert run.findings_count == 3

        # Reopen review (Scenario D Step 7)
        reopened = service.reopen_review(run.id, repository_id=repo.id)
        assert reopened is not None
        assert reopened["status"] == "COMPLETED"
        assert reopened["summary"] == review_report["summary"]
        assert len(reopened["findings"]) == 3
        cats = {f["category"] for f in reopened["findings"]}
        assert cats == {"security", "performance", "maintainability"}

    def test_unified_history_filtering_pagination_and_ordering(self, db_session: Session):
        """Unified history queries: ordering newest-first, pagination, and multi-criteria filtering."""
        user, repo = _create_regression_user_and_repo(db_session, "om-unified-user", "unified-repo")
        unified_service = AnalysisRunHistoryService(session=db_session)

        # Seed 10 runs with distinct features, statuses, and timestamps
        features = ["explain", "detect_bugs", "generate_tests", "review"]
        statuses = ["COMPLETED", "FAILED"]
        now = datetime.now(timezone.utc)

        for i in range(10):
            created_dt = now - timedelta(minutes=10 - i)  # i=9 is newest
            feat = features[i % len(features)]
            stat = statuses[i % len(statuses)]
            unified_service.record_run(
                {
                    "repository_id": repo.id,
                    "user_id": user.id,
                    "feature_type": feat,
                    "status": stat,
                    "target_path": f"src/file_{i % 3}.py",
                    "source_revision": f"rev_{i % 2}",
                    "created_at": created_dt,
                },
                db=db_session,
            )

        # 1. Newest-first ordering & pagination
        runs_p1, total = unified_service.list_runs(repo.id, offset=0, limit=5, db=db_session)
        assert total == 10
        assert len(runs_p1) == 5
        # Verify strictly descending created_at
        for j in range(len(runs_p1) - 1):
            assert runs_p1[j].created_at >= runs_p1[j + 1].created_at

        # 2. Filter by feature_type
        explain_runs, exp_total = unified_service.list_runs(repo.id, feature_type="explain", db=db_session)
        assert exp_total > 0
        assert all(r.feature_type == "explain" for r in explain_runs)

        # 3. Filter by status
        failed_runs, fail_total = unified_service.list_runs(repo.id, status="FAILED", db=db_session)
        assert fail_total == 5
        assert all(r.status == "FAILED" for r in failed_runs)

        # 4. Summary metrics
        summary = unified_service.get_run_summary(repo.id, db=db_session)
        assert summary["total_runs"] == 10
        assert summary["by_status"]["FAILED"] == 5
        assert summary["by_status"]["COMPLETED"] == 5

    def test_database_integrity_auditor_detects_clean_and_corrupt_states(self, db_session: Session):
        """Verify verify_integrity detects clean state and accurately flags orphaned findings or desync."""
        user, repo = _create_regression_user_and_repo(db_session, "om-audit-user", "audit-repo")
        unified_service = AnalysisRunHistoryService(session=db_session)

        # 1. Clean run with finding
        run = unified_service.record_run(
            {
                "repository_id": repo.id,
                "user_id": user.id,
                "feature_type": "detect_bugs",
                "status": "COMPLETED",
                "findings": [
                    {
                        "category": "security",
                        "severity": "HIGH",
                        "title": "Clean Finding",
                        "file_path": "src/clean.py",
                        "evidence": "assert True",
                    }
                ],
            },
            db=db_session,
        )

        clean_report = unified_service.verify_integrity(repo.id, db=db_session)
        assert clean_report["status"] == "CLEAN"
        assert clean_report["issues_count"] == 0

        # 2. Intentionally desynchronize findings_count
        run.findings_count = 999
        db_session.commit()

        dirty_report = unified_service.verify_integrity(repo.id, db=db_session)
        assert dirty_report["status"] == "ISSUES_FOUND"
        assert dirty_report["desynchronized_runs_count"] == 1


# ---------------------------------------------------------------------------
# 2. Migration Consistency & Alembic Schema Chain Invariants
# ---------------------------------------------------------------------------

class TestDay7MigrationConsistency:
    """Confirms migration consistency, chain continuity, and model schema parity."""

    def test_alembic_migration_chain_unbroken_and_acyclic(self):
        """Verify all migration versions form an unbroken, acyclic revision chain from root to head."""
        versions_dir = Path(__file__).resolve().parent.parent / "migrations" / "versions"
        assert versions_dir.is_dir(), f"Migrations versions dir not found at {versions_dir}"

        migration_files = list(versions_dir.glob("*.py"))
        assert len(migration_files) >= 6, f"Expected at least 6 migrations, found {len(migration_files)}"

        revisions: dict[str, str | None] = {}
        for py_file in migration_files:
            content = py_file.read_text(encoding="utf-8")
            rev_match = re.search(r'revision:\s*(?:str\s*=\s*)?["\']([a-f0-9]+)["\']', content)
            down_match = re.search(r'down_revision:\s*(?:[A-Za-z0-9_, \[\]\|]*\s*=\s*)?(?:["\']([a-f0-9]+)["\']|None)', content)

            if rev_match:
                rev_id = rev_match.group(1)
                down_id = down_match.group(1) if (down_match and down_match.group(1)) else None
                revisions[rev_id] = down_id

        # Verify known milestones exist in the chain
        known_milestones = [
            "24498ac67b3e",  # pgvector
            "5f6dc031921b",  # identity
            "aef3bb17eb34",  # content
            "cb4e2a7d0f31",  # sync jobs
            "e7b8c9d0f1a2",  # chunks & memory
            "f1c2d3e4b5a6",  # analysis runs & findings (Week 2)
        ]
        for milestone in known_milestones:
            assert milestone in revisions, f"Milestone revision {milestone} missing from Alembic chain"

        # Traverse backwards from head (f1c2d3e4b5a6) to root (None)
        curr: str | None = "f1c2d3e4b5a6"
        visited: list[str] = []
        while curr is not None:
            visited.append(curr)
            assert curr in revisions, f"Dangling down_revision {curr}"
            curr = revisions[curr]
            assert len(visited) <= len(revisions), "Cycle detected in Alembic migration chain!"

        # Root must be 24498ac67b3e with down_revision None
        assert visited[-1] == "24498ac67b3e"
        assert revisions["24498ac67b3e"] is None

    def test_orm_models_match_migration_schema(self, db_session: Session):
        """Verify AnalysisRun and AnalysisFinding ORM models match migration columns and types."""
        engine = db_session.get_bind()
        insp = inspect(engine)

        # 1. analysis_runs table inspection
        run_cols = {col["name"]: col for col in insp.get_columns("analysis_runs")}
        expected_run_cols = {
            "id", "repository_id", "user_id", "feature_type", "status",
            "target_path", "target_symbol", "start_line", "end_line",
            "source_revision", "findings_count", "result_payload",
            "test_output", "error_message", "completed_at", "created_at", "updated_at",
        }
        for col_name in expected_run_cols:
            assert col_name in run_cols, f"Column '{col_name}' missing from analysis_runs schema"

        # 2. analysis_findings table inspection
        finding_cols = {col["name"]: col for col in insp.get_columns("analysis_findings")}
        expected_finding_cols = {
            "id", "analysis_run_id", "repository_id", "category", "severity",
            "title", "description", "file_path", "start_line", "end_line",
            "source_revision", "symbol_name", "evidence", "suggested_fix",
            "confidence", "is_uncertain", "is_new_in_change", "source_type",
            "rule_id", "created_at", "updated_at",
        }
        for col_name in expected_finding_cols:
            assert col_name in finding_cols, f"Column '{col_name}' missing from analysis_findings schema"

    def test_all_seven_composite_indexes_defined(self, db_session: Session):
        """Verify all 7 composite query-pattern indexes are configured on analysis_runs and analysis_findings."""
        engine = db_session.get_bind()
        insp = inspect(engine)

        run_idx_names = {idx["name"] for idx in insp.get_indexes("analysis_runs") if idx.get("name")}
        assert "ix_analysis_runs_repo_created" in run_idx_names
        assert "ix_analysis_runs_repo_feature_status" in run_idx_names
        assert "ix_analysis_runs_repo_revision" in run_idx_names
        assert "ix_analysis_runs_repo_target_path" in run_idx_names

        finding_idx_names = {idx["name"] for idx in insp.get_indexes("analysis_findings") if idx.get("name")}
        assert "ix_analysis_findings_run_severity" in finding_idx_names
        assert "ix_analysis_findings_repo_file" in finding_idx_names
        assert "ix_analysis_findings_repo_category" in finding_idx_names


# ---------------------------------------------------------------------------
# 3. Repository and User Scoping Verification
# ---------------------------------------------------------------------------

class TestDay7RepositoryAndUserScoping:
    """Verifies strict multi-tenant repository isolation, user filtering, and foreign key cascades."""

    def test_cross_tenant_repository_boundary_isolation(self, db_session: Session):
        """Scenario E Step 1: Querying Repo A's analysis runs from Repo B returns zero results."""
        user1, repo1 = _create_regression_user_and_repo(db_session, "tenant1", "repo-alpha")
        user2, repo2 = _create_regression_user_and_repo(db_session, "tenant2", "repo-beta")

        repo_obj = AnalysisRunRepository(db_session)

        # Create run in Repo 1
        run1 = repo_obj.create_run(
            repository_id=repo1.id,
            user_id=user1.id,
            feature_type="explain",
            status="COMPLETED",
            target_path="src/sensitive.py",
        )

        # 1. Attempt to get Repo 1's run using Repo 2's scope -> MUST return None
        cross_run = repo_obj.get_by_id_and_repository(run1.id, repo2.id)
        assert cross_run is None, "Cross-repository access breach: Repo 2 accessed Repo 1's run!"

        # 2. List runs in Repo 2 -> MUST NOT show Repo 1's runs
        runs2, count2 = repo_obj.list_by_repository(repo2.id)
        assert count2 == 0
        assert len(runs2) == 0

    def test_user_scoping_filters_history_by_author(self, db_session: Session):
        """Verify user_id parameter in list_runs isolates runs by author within a shared repository."""
        userA, repo = _create_regression_user_and_repo(db_session, "collab-a", "shared-collab-repo")
        userB = User(id=uuid.uuid4(), github_id="gh_collab_b", login="collab-b", email="b@collab.com")
        db_session.add(userB)
        db_session.commit()

        repo_obj = AnalysisRunRepository(db_session)

        # Create 2 runs for User A and 3 runs for User B
        for i in range(2):
            repo_obj.create_run(repository_id=repo.id, user_id=userA.id, feature_type="explain", status="COMPLETED")
        for i in range(3):
            repo_obj.create_run(repository_id=repo.id, user_id=userB.id, feature_type="detect_bugs", status="COMPLETED")

        # 1. Query for User A
        runs_a, count_a = repo_obj.list_by_repository(repo.id, user_id=userA.id)
        assert count_a == 2
        assert len(runs_a) == 2
        assert all(r.user_id == userA.id for r in runs_a)

        # 2. Query for User B
        runs_b, count_b = repo_obj.list_by_repository(repo.id, user_id=userB.id)
        assert count_b == 3
        assert len(runs_b) == 3
        assert all(r.user_id == userB.id for r in runs_b)

        # 3. Query without user filter returns all 5
        runs_all, count_all = repo_obj.list_by_repository(repo.id)
        assert count_all == 5

    def test_cascade_delete_integrity_repository_run_and_user(self, db_session: Session):
        """Confirm ON DELETE CASCADE on repo/run and ON DELETE SET NULL on user."""
        owner, repo = _create_regression_user_and_repo(db_session, "cascade-owner", "cascade-repo")
        runner_user = User(
            id=uuid.uuid4(),
            github_id=f"gh_{uuid.uuid4().hex[:8]}",
            login="cascade-runner-user",
            email="cascade-runner@example.com",
        )
        db_session.add(runner_user)
        db_session.commit()
        repo_obj = AnalysisRunRepository(db_session)

        run = repo_obj.create_run(
            repository_id=repo.id,
            user_id=runner_user.id,
            feature_type="detect_bugs",
            status="COMPLETED",
            findings=[
                {
                    "category": "security",
                    "severity": "HIGH",
                    "title": "Cascade Finding",
                    "file_path": "src/app.py",
                    "evidence": "pass",
                }
            ],
        )
        run_id = run.id
        finding_id = run.findings[0].id

        # 1. Verify schema foreign key constraints
        user_fks = list(AnalysisRun.__table__.c.user_id.foreign_keys)
        assert len(user_fks) == 1
        assert user_fks[0].ondelete.upper() == "SET NULL"

        repo_fks = list(AnalysisRun.__table__.c.repository_id.foreign_keys)
        assert len(repo_fks) == 1
        assert repo_fks[0].ondelete.upper() == "CASCADE"

        finding_run_fks = list(AnalysisFinding.__table__.c.analysis_run_id.foreign_keys)
        assert len(finding_run_fks) == 1
        assert finding_run_fks[0].ondelete.upper() == "CASCADE"

        finding_repo_fks = list(AnalysisFinding.__table__.c.repository_id.foreign_keys)
        assert len(finding_repo_fks) == 1
        assert finding_repo_fks[0].ondelete.upper() == "CASCADE"

        # 2. Deleting user does not cascade delete run (run is preserved)
        db_session.delete(runner_user)
        db_session.commit()

        reloaded_run = repo_obj.get_by_id(run_id)
        assert reloaded_run is not None, "Run was deleted when user was deleted (should be preserved)!"

        # 3. Deleting run cascades to its findings
        deleted = repo_obj.delete_run(run_id)
        assert deleted is True

        orphan_finding = db_session.get(AnalysisFinding, finding_id)
        assert orphan_finding is None, "Finding was not cascaded upon run deletion!"

        # 4. Deleting repository runs purges all runs and their findings
        run2 = repo_obj.create_run(
            repository_id=repo.id,
            feature_type="review",
            status="COMPLETED",
            findings=[{"title": "Repo finding", "category": "security", "severity": "LOW"}],
        )
        assert repo_obj.get_by_id(run2.id) is not None
        purged_count = repo_obj.delete_repository_runs(repo.id)
        assert purged_count >= 1
        assert repo_obj.get_by_id(run2.id) is None


# ---------------------------------------------------------------------------
# 4. Data Retention & Sensitive-Data Handling
# ---------------------------------------------------------------------------

class TestDay7DataRetentionAndSensitiveDataHandling:
    """Verifies automatic secret scrubbing, retention pruning, and historical data sanitization."""

    def test_automatic_secret_scrubbing_on_persistence(self, db_session: Session):
        """Scenario E Step 8: Credentials, API keys, tokens, and DB URIs are scrubbed upon persistence."""
        user, repo = _create_regression_user_and_repo(db_session, "om-scrub-user", "scrub-repo")
        repo_obj = AnalysisRunRepository(db_session)

        raw_error = "Connection failed to postgresql://postgres_admin:SuperSecretPass123!@db.internal:5432/main"
        raw_test_code = (
            "import os\n"
            "OPENAI_KEY = 'sk-proj-abcdef1234567890abcdef1234567890'\n"
            "GH_TOKEN = 'ghp_1234567890abcdef1234567890abcdef1234'\n"
            "def test_auth():\n"
            "    assert True\n"
        )
        raw_finding = {
            "category": "security",
            "severity": "CRITICAL",
            "title": "Exposed GitHub Token in auth_client.py",
            "description": "Found raw token ghp_1234567890abcdef1234567890abcdef1234 in file.",
            "file_path": "src/auth_client.py",
            "evidence": "TOKEN = 'ghp_1234567890abcdef1234567890abcdef1234'",
            "suggested_fix": "TOKEN = os.getenv('GITHUB_TOKEN')",
            "metadata": {"raw_assignment": 'api_key="sk-ant-api03-abcdef12345678901234"'},
        }

        run = repo_obj.create_run(
            repository_id=repo.id,
            user_id=user.id,
            feature_type="generate_tests",
            status="FAILED",
            test_output=raw_test_code,
            error_message=raw_error,
            findings=[raw_finding],
        )

        # 1. Error message sanitized
        assert "SuperSecretPass123!" not in run.error_message
        assert "[REDACTED]" in run.error_message
        assert "postgresql://postgres_admin:[REDACTED]@db.internal:5432/main" in run.error_message

        # 2. Test output sanitized
        assert "sk-proj-abcdef" not in run.test_output
        assert "ghp_1234567890" not in run.test_output
        assert "[REDACTED]" in run.test_output

        # 3. Finding fields sanitized
        persisted_f = run.findings[0]
        assert "ghp_1234567890" not in persisted_f.description
        assert "ghp_1234567890" not in persisted_f.evidence
        assert "[REDACTED]" in persisted_f.description
        assert "[REDACTED]" in persisted_f.evidence
        assert "sk-ant-api03" not in str(persisted_f.finding_metadata)

    def test_purge_expired_runs_retention_policy(self, db_session: Session):
        """Purge analysis runs and findings older than 30 days retention policy."""
        user, repo = _create_regression_user_and_repo(db_session, "om-retention-user", "retention-repo")
        repo_obj = AnalysisRunRepository(db_session)

        now = datetime.now(timezone.utc)
        # Create an expired run (45 days old)
        old_run = repo_obj.create_run(
            repository_id=repo.id,
            user_id=user.id,
            feature_type="detect_bugs",
            status="COMPLETED",
            created_at=now - timedelta(days=45),
            findings=[{"category": "security", "severity": "LOW", "title": "Old Finding", "file_path": "src/old.py", "evidence": "x=1"}],
        )
        old_finding_id = old_run.findings[0].id

        # Create a fresh run (5 days old)
        recent_run = repo_obj.create_run(
            repository_id=repo.id,
            user_id=user.id,
            feature_type="detect_bugs",
            status="COMPLETED",
            created_at=now - timedelta(days=5),
        )

        # Execute retention purge for runs > 30 days
        purged_count = repo_obj.purge_expired_runs(repository_id=repo.id, retention_days=30)
        assert purged_count == 1

        # Verify old run and its findings are purged
        assert repo_obj.get_by_id(old_run.id) is None
        assert db_session.get(AnalysisFinding, old_finding_id) is None

        # Verify recent run is preserved
        assert repo_obj.get_by_id(recent_run.id) is not None

    def test_prune_uncompleted_stale_runs(self, db_session: Session):
        """Time-out and fail stuck PENDING or RUNNING runs older than 24 hours."""
        user, repo = _create_regression_user_and_repo(db_session, "om-stale-user", "stale-repo")
        repo_obj = AnalysisRunRepository(db_session)

        now = datetime.now(timezone.utc)
        # Create stuck PENDING run from 30 hours ago
        stuck_run = repo_obj.create_run(
            repository_id=repo.id,
            user_id=user.id,
            feature_type="generate_tests",
            status=AnalysisRunStatus.PENDING.value,
            created_at=now - timedelta(hours=30),
        )

        # Prune stale runs
        pruned_count = repo_obj.prune_uncompleted_stale_runs(older_than_hours=24, mark_as_failed=True)
        assert pruned_count >= 1

        db_session.refresh(stuck_run)
        assert stuck_run.status == AnalysisRunStatus.FAILED.value
        assert "timed out after 24 hours" in stuck_run.error_message
        assert stuck_run.completed_at is not None

    def test_retention_metrics_calculation(self, db_session: Session):
        """Calculate data retention metrics (volume by age brackets, oldest, newest)."""
        user, repo = _create_regression_user_and_repo(db_session, "om-metrics-user", "metrics-repo")
        repo_obj = AnalysisRunRepository(db_session)

        now = datetime.now(timezone.utc)
        # Create runs at 10d, 40d, and 70d ago
        repo_obj.create_run(repository_id=repo.id, feature_type="explain", created_at=now - timedelta(days=10))
        repo_obj.create_run(repository_id=repo.id, feature_type="detect_bugs", created_at=now - timedelta(days=40))
        repo_obj.create_run(repository_id=repo.id, feature_type="review", created_at=now - timedelta(days=70))

        metrics = repo_obj.get_retention_metrics(repository_id=repo.id)
        assert metrics["total_runs"] == 3
        assert metrics["runs_older_30d"] == 2
        assert metrics["runs_older_60d"] == 1
        assert metrics["runs_older_90d"] == 0
        assert metrics["oldest_run_at"] is not None
        assert metrics["newest_run_at"] is not None

    def test_sanitize_sensitive_data_in_history_retroactive(self, db_session: Session):
        """Retroactively audit and sanitize existing historical records containing credentials."""
        user, repo = _create_regression_user_and_repo(db_session, "om-retro-user", "retro-repo")
        repo_obj = AnalysisRunRepository(db_session)

        # Seed raw run with unsanitized error message directly
        run = AnalysisRun(
            id=uuid.uuid4(),
            repository_id=repo.id,
            user_id=user.id,
            feature_type="review",
            status="FAILED",
            error_message="Raw leak: aws_key=AKIA1234567890ABCDEF",
        )
        db_session.add(run)
        db_session.commit()

        # Execute retroactive sanitizer
        sanitized_count = repo_obj.sanitize_sensitive_data_in_history(repository_id=repo.id)
        assert sanitized_count >= 1

        db_session.refresh(run)
        assert "AKIA1234567890ABCDEF" not in run.error_message
        assert "[REDACTED]" in run.error_message


# test_om_day7

TEST_DATABASE_URL = normalize_sync_database_url(
    os.environ.get(
        "TEST_DATABASE_URL",
        get_settings().database_url,
    )
)

@pytest.fixture(scope="session")
def pgvector_engine():
    if TEST_DATABASE_URL.startswith("sqlite"):
        pytest.skip("PostgreSQL test database not available (SQLite active)")
    pgvector_engine = create_engine(TEST_DATABASE_URL, connect_args={"connect_timeout": 2})
    try:
        with pgvector_engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception:
        pytest.skip("PostgreSQL test database not available")
    with pgvector_engine.begin() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
    Base.metadata.create_all(pgvector_engine)
    yield pgvector_engine
    pgvector_engine.dispose()


@pytest.fixture
def pgvector_db_session(pgvector_engine):
    Session = sessionmaker(bind=pgvector_engine)
    session = Session()
    yield session
    session.rollback()
    session.close()

def test_complete_data_pipeline_end_to_end(pgvector_db_session):
    """
    Day 7 - DB Integration Test
    Verify the complete data pipeline writes correctly end-to-end:
    GH[GitHub Clone] --> RF[repository_files] --> CS[code_symbols] --> SE[symbol_edges]\x20
    --> CC[code_chunks] --> EM[embedding vector] --> ME[memory_entries]
    """
    # 1. Identity Schema
    user_id = uuid.uuid4()
    user = User(id=user_id, github_id=f"gh_{uuid.uuid4().hex[:8]}", login=f"test_{uuid.uuid4().hex[:6]}", email="test@example.com")
    pgvector_db_session.add(user)
    pgvector_db_session.flush()

    install_id = uuid.uuid4()
    installation = GitHubInstallation(
        id=install_id, user_id=user_id, installation_id=f"inst_{uuid.uuid4().hex[:8]}", account_login=user.login, permissions={}
    )
    pgvector_db_session.add(installation)
    pgvector_db_session.flush()

    repo_id = uuid.uuid4()
    repository = Repository(
        id=repo_id, user_id=user_id, installation_id=install_id, github_repo_id=f"repo_{uuid.uuid4().hex[:8]}",
        owner=user.login, name="testrepo", default_branch="main"
    )
    pgvector_db_session.add(repository)
    pgvector_db_session.flush()

    # 2. Repository Content Schema
    file_id = uuid.uuid4()
    repo_file = RepositoryFile(
        id=file_id, repository_id=repo_id, path="src/main.py", language="python",
        size_bytes=1024, line_count=50, content_hash="hash_123"
    )
    pgvector_db_session.add(repo_file)
    pgvector_db_session.flush()

    symbol_id_1 = uuid.uuid4()
    symbol_1 = CodeSymbol(
        id=symbol_id_1, repository_id=repo_id, file_id=file_id, name="MyClass",
        kind="class", start_line=10, end_line=20, signature="class MyClass:"
    )
    symbol_id_2 = uuid.uuid4()
    symbol_2 = CodeSymbol(
        id=symbol_id_2, repository_id=repo_id, file_id=file_id, name="my_function",
        kind="function", start_line=22, end_line=30, signature="def my_function():"
    )
    pgvector_db_session.add_all([symbol_1, symbol_2])
    pgvector_db_session.flush()

    edge_id = uuid.uuid4()
    edge = SymbolEdge(
        id=edge_id, repository_id=repo_id, source_symbol_id=symbol_id_2,
        target_symbol_id=symbol_id_1, edge_type="calls"
    )
    pgvector_db_session.add(edge)
    pgvector_db_session.flush()

    # 3. RAG Schema (Code Chunks with Embeddings)
    chunk_id = uuid.uuid4()
    chunk = CodeChunk(
        id=chunk_id, repository_id=repo_id, file_id=file_id, symbol_id=symbol_id_1,
        content="class MyClass: ...", token_count=10, embedding=[0.1] * 768,
        start_line=10, end_line=20, content_hash="hash_chunk_123", chunk_metadata={"type": "class"}
    )
    pgvector_db_session.add(chunk)
    pgvector_db_session.flush()

    # 4. Memory Schema
    memory_id = uuid.uuid4()
    memory = MemoryEntry(
        id=memory_id, repository_id=repo_id, type_=MemoryType.decision,
        content="We decided to use PostgreSQL", source="agent_run:123", status=MemoryStatus.active
    )
    pgvector_db_session.add(memory)

    # 5. Commit and Verify Data Pipeline Execution
    pgvector_db_session.commit()

    saved_chunk = pgvector_db_session.query(CodeChunk).filter_by(id=chunk_id).first()
    assert saved_chunk is not None
    assert saved_chunk.repository_id == repo_id
    assert len(saved_chunk.embedding) == 768

    saved_memory = pgvector_db_session.query(MemoryEntry).filter_by(id=memory_id).first()
    assert saved_memory is not None
    assert saved_memory.type_ == MemoryType.decision
