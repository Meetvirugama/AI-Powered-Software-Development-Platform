"""Week 2 — Day 7 Acceptance, Regression & Verification Test Suite.

Owner: Om — Database & Persistence Lead.
Milestone: Week 2 — Developer Intelligence Suite Final Gate & Handoff to Week 3.

Comprehensive verification of Om's Day 7 tasks from Docs/week2.md:
1. Analysis Persistence and History Retrieval (All 4 features: Explanation, Bug Detection, Test Generation, AI Code Review).
2. Migration Consistency & Alembic Schema Chain Invariants.
3. Repository and User Scoping (Multi-tenant isolation, user filtering, and cascade deletes).
4. Data Retention and Sensitive-Data Handling (Automatic secret scrubbing, purge/pruning policies, retention metrics).
"""

from __future__ import annotations

import os
import re
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import inspect, select
from sqlalchemy.orm import Session

from app.models.analysis_finding import AnalysisFinding
from app.models.analysis_run import AnalysisFeature, AnalysisRun, AnalysisRunStatus
from app.models.github_installation import GitHubInstallation
from app.models.repository import Repository, SyncStatus
from app.models.user import User
from app.repositories.analysis_run_repository import (
    AnalysisRunRepository,
    scrub_sensitive_data,
    scrub_sensitive_text,
)
from app.services.analysis_run_history_service import AnalysisRunHistoryService
from app.services.bug_scan_history_service import BugScanHistoryService
from app.services.explanation_history_service import ExplanationHistoryService
from app.services.review_history_service import ReviewHistoryService
from app.services.test_generation_history_service import TestGenerationHistoryService


# ---------------------------------------------------------------------------
# Test Helpers & Fixture Builders
# ---------------------------------------------------------------------------

def _create_user_and_repo(
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
        user, repo = _create_user_and_repo(db_session, "om-explain-user", "explain-repo")
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
        user, repo = _create_user_and_repo(db_session, "om-bug-user", "bug-repo")
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
        user, repo = _create_user_and_repo(db_session, "om-test-user", "test-gen-repo")
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
        user, repo = _create_user_and_repo(db_session, "om-review-user", "review-repo")
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
        user, repo = _create_user_and_repo(db_session, "om-unified-user", "unified-repo")
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
        user, repo = _create_user_and_repo(db_session, "om-audit-user", "audit-repo")
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
        user1, repo1 = _create_user_and_repo(db_session, "tenant1", "repo-alpha")
        user2, repo2 = _create_user_and_repo(db_session, "tenant2", "repo-beta")

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
        userA, repo = _create_user_and_repo(db_session, "collab-a", "shared-collab-repo")
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
        user, repo = _create_user_and_repo(db_session, "cascade-user", "cascade-repo")
        repo_obj = AnalysisRunRepository(db_session)

        run = repo_obj.create_run(
            repository_id=repo.id,
            user_id=user.id,
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
        db_session.delete(user)
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
        user, repo = _create_user_and_repo(db_session, "om-scrub-user", "scrub-repo")
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
        user, repo = _create_user_and_repo(db_session, "om-retention-user", "retention-repo")
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
        user, repo = _create_user_and_repo(db_session, "om-stale-user", "stale-repo")
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
        user, repo = _create_user_and_repo(db_session, "om-metrics-user", "metrics-repo")
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
        user, repo = _create_user_and_repo(db_session, "om-retro-user", "retro-repo")
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
