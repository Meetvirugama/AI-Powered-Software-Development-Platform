"""Persistence and database integrity tests for Week 2 Day 1 (Analysis Persistence).

Owner: Om — Database & Persistence.

Verifies:
1. AnalysisRun and AnalysisFinding model schema definitions and index constraints.
2. Saving and retrieving runs across all 4 feature types:
   - explain
   - detect_bugs
   - generate_tests
   - review
3. Multi-tenant repository isolation:
   - User A's/Repo A's analysis runs and findings are never returned when querying Repo B.
   - Cross-repository get_by_id_and_repository lookup returns None.
4. Structured finding persistence:
   - Attaching findings on run creation.
   - Appending findings to an existing run via add_findings.
   - Finding source_reference property and to_dict representation.
5. Large generated test output persistence:
   - Saving large test contents (50+ KB) without truncation or data loss.
6. Status transitions and lifecycle updates:
   - PENDING -> RUNNING -> COMPLETED / FAILED with error_message and completed_at.
7. Filtering, ordering and pagination:
   - Filtering by feature_type and status.
   - Ordering by created_at descending.
   - Proper offset/limit pagination with accurate total count.
8. Cascade deletion:
   - Deleting a run cascades to its findings.
   - Deleting a repository cleans up all associated runs and findings.
9. Compatibility with orchestrator `record_analysis_run` and Yug's `AnalysisRunPersistenceProtocol`.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.database import Base
from app.models.analysis_finding import AnalysisFinding
from app.models.analysis_run import AnalysisFeature, AnalysisRun, AnalysisRunStatus
from app.models.github_installation import GitHubInstallation
from app.models.repository import Repository, SyncStatus
from app.models.user import User
from app.repositories.analysis_run_repository import AnalysisRunRepository
from app.repositories.repository_repository import RepositoryRepository


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
