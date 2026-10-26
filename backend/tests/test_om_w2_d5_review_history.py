"""Comprehensive test suite for Week 2 Day 5 (Standalone AI Code Review History & Persistence).

Owner: Om — Database & Persistence.

Verifies all Day 5 deliverables and acceptance criteria from `Docs/week2.md` §9 & §12 (Scenario D):
1. Persist review reports and findings:
   - Saving review runs (`feature_type="review"`) with structured reports and categorized findings.
   - Categories: correctness, security, performance, reliability, maintainability.
   - Concrete source locations (file_path, 1-indexed inclusive line range).
   - Severity, evidence, suggested remediation, confidence, source_type (AI/STATIC/COMBINED).
2. Associate with repository, source revision, and analysis run:
   - Preserving multi-target review contexts: single file, commit SHA, PR diff, unified diff.
   - Preserving base/head revisions, commit SHAs, and PR numbers.
3. Ensure a review of a newer revision does not silently overwrite the old result:
   - Each review run creates an immutable, historical record.
   - Reviews across multiple revisions (e.g. revision 1 vs revision 2) coexist independently.
4. Retrieve previous reviews and history:
   - Multi-criteria filtering by status, target_path, source_revision, commit_sha, pr_number.
   - Ordering newest first (`created_at.desc()`).
   - Accurate total counts and pagination.
5. Reopen review from persistent history (Scenario D Step 7):
   - Reconstituting past review runs matching `ReviewReportResponse` with full fidelity.
6. Persist failed review runs:
   - Recording explicit failures (`status="FAILED"`, `error_message`), strictly preventing
     execution failures from masquerading as clean reviews with zero findings.
7. Clean review handling:
   - Distinguishing a successful review with zero findings (`status="COMPLETED"`, `findings_count=0`)
     from a failed review.
8. Duplicate detection and latest review lookup:
   - Finding duplicate completed runs to prevent redundant AI review runs.
   - Fetching latest completed review for a target or revision.
9. Multi-tenant repository isolation:
   - Cross-repository access is strictly blocked; Repo A's review runs are never visible to Repo B.
10. `ReviewHistoryService` business logic and session management.
11. End-to-end API integration:
    - `POST /api/v1/repositories/{id}/review` -> persistence ->
    - Retrieval via `GET /api/v1/analysis-runs/{run_id}` ->
    - Listing via `GET /api/v1/repositories/{id}/analysis-runs?feature_type=review`.
12. Failure recording on service errors.
13. Foreign key safety with synthetic/unpersisted user IDs.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.main import app
from app.models.analysis_finding import AnalysisFinding
from app.models.analysis_run import AnalysisFeature, AnalysisRun, AnalysisRunStatus
from app.models.github_installation import GitHubInstallation
from app.models.repository import Repository, SyncStatus
from app.models.repository_file import RepositoryFile
from app.models.user import User
from app.repositories.analysis_run_repository import AnalysisRunRepository
from app.services.review_history_service import ReviewHistoryService


# ---------------------------------------------------------------------------
# Test Helpers & Seeders
# ---------------------------------------------------------------------------


def _create_test_user_and_repo(
    db: Session,
    login: str = "om-review-user",
    repo_name: str = "review-suite-repo",
) -> tuple[User, Repository]:
    """Seed user, GitHub installation, and repository records with valid UUIDs."""
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


def _sample_review_findings() -> list[dict]:
    """Sample categorized ReviewFinding dictionaries covering all 5 review categories."""
    return [
        {
            "id": str(uuid.uuid4()),
            "category": "security",
            "severity": "CRITICAL",
            "title": "SQL Injection in User Lookup",
            "description": "Raw string formatting used in SQL query execution without parameterization.",
            "source_reference": {
                "file_path": "src/auth/service.py",
                "start_line": 42,
                "end_line": 45,
                "revision": "git_rev_abc123",
                "symbol_name": "lookup_user",
            },
            "evidence": "query = f'SELECT * FROM users WHERE email = {email}'",
            "suggested_fix": "Use SQLAlchemy parameterized select(User).where(User.email == email)",
            "confidence": "high",
            "is_uncertain": False,
            "is_new_in_change": True,
            "source_type": "AI",
            "rule_id": "SEC-SQLI-001",
        },
        {
            "id": str(uuid.uuid4()),
            "category": "correctness",
            "severity": "HIGH",
            "title": "Off-by-one Error in Token Expiry Calculation",
            "description": "Token lifespan check uses <= 0 instead of < 0, prematurely expiring valid tokens.",
            "source_reference": {
                "file_path": "src/auth/token.py",
                "start_line": 15,
                "end_line": 18,
                "revision": "git_rev_abc123",
                "symbol_name": "validate_token",
            },
            "evidence": "if remaining_seconds <= 0: raise TokenExpiredError()",
            "suggested_fix": "if remaining_seconds < 0: raise TokenExpiredError()",
            "confidence": "high",
            "is_uncertain": False,
            "is_new_in_change": True,
            "source_type": "STATIC",
            "rule_id": "CORR-OBO-002",
        },
        {
            "id": str(uuid.uuid4()),
            "category": "performance",
            "severity": "MEDIUM",
            "title": "N+1 Query in Repository Listing",
            "description": "Lazy loading relationship inside for-loop produces N additional roundtrips.",
            "source_reference": {
                "file_path": "src/repositories/service.py",
                "start_line": 88,
                "end_line": 95,
                "revision": "git_rev_abc123",
                "symbol_name": "list_with_files",
            },
            "evidence": "for repo in repos: print(repo.files)",
            "suggested_fix": "Add selectinload(Repository.files) to the query options.",
            "confidence": "medium",
            "is_uncertain": False,
            "is_new_in_change": False,
            "source_type": "AI",
            "rule_id": "PERF-NPLUS1-003",
        },
        {
            "id": str(uuid.uuid4()),
            "category": "reliability",
            "severity": "MEDIUM",
            "title": "Missing Exception Handler for Network Timeout",
            "description": "External HTTP call does not catch ConnectTimeout, crashing the worker.",
            "source_reference": {
                "file_path": "src/integrations/client.py",
                "start_line": 120,
                "end_line": 126,
                "revision": "git_rev_abc123",
                "symbol_name": "fetch_remote",
            },
            "evidence": "res = httpx.get(url, timeout=5.0)",
            "suggested_fix": "Wrap with try/except httpx.TimeoutException and retry.",
            "confidence": "high",
            "is_uncertain": False,
            "is_new_in_change": True,
            "source_type": "COMBINED",
            "rule_id": "REL-TIMEOUT-004",
        },
        {
            "id": str(uuid.uuid4()),
            "category": "maintainability",
            "severity": "LOW",
            "title": "Excessive Cyclomatic Complexity in Router",
            "description": "Function has cyclomatic complexity of 18, exceeding team standard of 10.",
            "source_reference": {
                "file_path": "src/api/routes.py",
                "start_line": 200,
                "end_line": 260,
                "revision": "git_rev_abc123",
                "symbol_name": "dispatch_request",
            },
            "evidence": "Function contains 12 nested if/elif branches.",
            "suggested_fix": "Refactor branching logic using strategy pattern or dictionary dispatch.",
            "confidence": "high",
            "is_uncertain": False,
            "is_new_in_change": True,
            "source_type": "STATIC",
            "rule_id": "MAINT-COMPLEXITY-005",
        },
    ]


# ---------------------------------------------------------------------------
# Unit & Persistence Tests (Om — Database & Persistence)
# ---------------------------------------------------------------------------


def test_save_completed_review_with_categorized_findings(db_session: Session) -> None:
    """Verify persisting a completed AI code review with all 5 categories and structured findings."""
    user, repo = _create_test_user_and_repo(db_session, "user-rev-cat", "repo-rev-cat")
    repo_layer = AnalysisRunRepository(db_session)

    findings = _sample_review_findings()
    report = {
        "summary": "Standalone AI code review identified 5 findings requiring attention.",
        "risk_level": "CRITICAL",
        "findings": findings,
        "total_findings": len(findings),
        "category_counts": {
            "security": 1,
            "correctness": 1,
            "performance": 1,
            "reliability": 1,
            "maintainability": 1,
        },
        "missing_context": ["Missing database migration history context."],
    }

    target = {
        "type": "file",
        "path": "src/auth/service.py",
        "start_line": 1,
        "end_line": 150,
    }

    run = repo_layer.save_review_run(
        repository_id=repo.id,
        user_id=user.id,
        target=target,
        report=report,
        source_revision="commit_sha_rev1",
        status=AnalysisRunStatus.COMPLETED.value,
    )

    assert run.id is not None
    assert run.repository_id == repo.id
    assert run.user_id == user.id
    assert run.feature_type == AnalysisFeature.REVIEW.value
    assert run.status == AnalysisRunStatus.COMPLETED.value
    assert run.target_path == "src/auth/service.py"
    assert run.source_revision == "commit_sha_rev1"
    assert run.findings_count == 5
    assert run.error_message is None
    assert run.completed_at is not None

    # Verify findings persisted in analysis_findings table
    retrieved_run = repo_layer.get_review_run(run.id, repository_id=repo.id)
    assert retrieved_run is not None
    assert len(retrieved_run.findings) == 5

    categories = {f.category for f in retrieved_run.findings}
    assert categories == {"security", "correctness", "performance", "reliability", "maintainability"}

    severities = {f.severity for f in retrieved_run.findings}
    assert severities == {"CRITICAL", "HIGH", "MEDIUM", "LOW"}

    # Verify concrete source location coordinates
    sec_finding = next(f for f in retrieved_run.findings if f.category == "security")
    assert sec_finding.file_path == "src/auth/service.py"
    assert sec_finding.start_line == 42
    assert sec_finding.end_line == 45
    assert sec_finding.symbol_name == "lookup_user"
    assert sec_finding.rule_id == "SEC-SQLI-001"
    assert sec_finding.is_new_in_change is True


def test_save_review_all_target_types_file_commit_pr_diff(db_session: Session) -> None:
    """Verify persisting review runs across all 4 target types: file, commit, PR, and diff."""
    user, repo = _create_test_user_and_repo(db_session, "user-targets", "repo-targets")
    repo_layer = AnalysisRunRepository(db_session)

    # 1. Target type: commit
    commit_run = repo_layer.save_review_run(
        repository_id=repo.id,
        review_target={"type": "commit", "commit_sha": "a1b2c3d4e5f67890"},
        report={"summary": "Commit review passed", "risk_level": "LOW", "findings": []},
        status=AnalysisRunStatus.COMPLETED.value,
    )
    assert commit_run.feature_type == "review"
    assert commit_run.source_revision == "a1b2c3d4e5f67890"
    assert "Commit a1b2c3d4" in commit_run.target_symbol

    # 2. Target type: PR
    pr_run = repo_layer.save_review_run(
        repository_id=repo.id,
        review_target={
            "type": "pr",
            "pr_number": 42,
            "base_revision": "main",
            "head_revision": "feature/auth-redesign",
        },
        report={"summary": "PR review passed", "risk_level": "LOW", "findings": []},
        status=AnalysisRunStatus.COMPLETED.value,
    )
    assert pr_run.feature_type == "review"
    assert pr_run.source_revision == "feature/auth-redesign"
    assert pr_run.target_symbol == "PR #42"

    # 3. Target type: diff
    diff_text = "--- a/file.py\n+++ b/file.py\n@@ -1,1 +1,2 @@\n+print('hello')\n"
    diff_run = repo_layer.save_review_run(
        repository_id=repo.id,
        review_target={
            "type": "diff",
            "diff": diff_text,
            "path": "file.py",
            "base_revision": "v1.0.0",
            "head_revision": "v1.1.0",
        },
        report={"summary": "Diff review complete", "risk_level": "LOW", "findings": []},
        status=AnalysisRunStatus.COMPLETED.value,
    )
    assert diff_run.feature_type == "review"
    assert diff_run.target_path == "file.py"
    assert diff_run.source_revision == "v1.1.0"


def test_ensure_newer_revision_does_not_overwrite_old_result(db_session: Session) -> None:
    """Critical Day 5 requirement: Ensure a review of a newer revision does not silently overwrite old results."""
    user, repo = _create_test_user_and_repo(db_session, "user-multi-rev", "repo-multi-rev")
    repo_layer = AnalysisRunRepository(db_session)

    target_file = "src/payment/gateway.py"

    # Revision 1: initial commit with 2 findings
    rev1_finding = {
        "category": "security",
        "severity": "HIGH",
        "title": "Plaintext API Key",
        "description": "Hardcoded secret in gateway client.",
        "source_reference": {"file_path": target_file, "start_line": 10, "end_line": 10},
        "evidence": "API_KEY = 'sk_live_123'",
    }
    run_rev1 = repo_layer.save_review_run(
        repository_id=repo.id,
        target_path=target_file,
        source_revision="commit_rev_111",
        findings=[rev1_finding],
        report={"summary": "Review for commit 111", "risk_level": "HIGH"},
        status=AnalysisRunStatus.COMPLETED.value,
    )

    # Revision 2: subsequent commit fixing security issue but introducing a performance issue
    rev2_finding = {
        "category": "performance",
        "severity": "LOW",
        "title": "Uncached Token Refresh",
        "description": "Token refreshed on every payment invocation.",
        "source_reference": {"file_path": target_file, "start_line": 25, "end_line": 30},
        "evidence": "self.refresh_token()",
    }
    run_rev2 = repo_layer.save_review_run(
        repository_id=repo.id,
        target_path=target_file,
        source_revision="commit_rev_222",
        findings=[rev2_finding],
        report={"summary": "Review for commit 222", "risk_level": "LOW"},
        status=AnalysisRunStatus.COMPLETED.value,
    )

    # 1. Verify two distinct run records exist in database
    assert run_rev1.id != run_rev2.id
    runs, total = repo_layer.list_review_runs(repo.id, target_path=target_file)
    assert total == 2
    assert len(runs) == 2

    # 2. Verify run_rev1 is completely intact with its original finding
    rev1_fetched = repo_layer.get_review_run(run_rev1.id, repository_id=repo.id)
    assert rev1_fetched is not None
    assert rev1_fetched.source_revision == "commit_rev_111"
    assert rev1_fetched.findings_count == 1
    assert rev1_fetched.findings[0].category == "security"
    assert rev1_fetched.findings[0].title == "Plaintext API Key"

    # 3. Verify run_rev2 is completely intact with its distinct finding
    rev2_fetched = repo_layer.get_review_run(run_rev2.id, repository_id=repo.id)
    assert rev2_fetched is not None
    assert rev2_fetched.source_revision == "commit_rev_222"
    assert rev2_fetched.findings_count == 1
    assert rev2_fetched.findings[0].category == "performance"
    assert rev2_fetched.findings[0].title == "Uncached Token Refresh"

    # 4. Verify querying by revision returns the exact corresponding run
    runs_rev1, count_rev1 = repo_layer.list_review_runs(repo.id, source_revision="commit_rev_111")
    assert count_rev1 == 1
    assert runs_rev1[0].id == run_rev1.id

    runs_rev2, count_rev2 = repo_layer.list_review_runs(repo.id, source_revision="commit_rev_222")
    assert count_rev2 == 1
    assert runs_rev2[0].id == run_rev2.id


def test_reopen_review_from_history_scenario_d(db_session: Session) -> None:
    """Scenario D Step 7: Reopen a review from persistent history with full fidelity."""
    user, repo = _create_test_user_and_repo(db_session, "user-reopen", "repo-reopen")
    repo_layer = AnalysisRunRepository(db_session)

    findings = _sample_review_findings()[:2]
    saved_run = repo_layer.save_review_run(
        repository_id=repo.id,
        user_id=user.id,
        target_path="src/reopen_test.py",
        source_revision="sha_reopen_456",
        findings=findings,
        report={
            "summary": "Reopenable review report with 2 findings.",
            "risk_level": "HIGH",
            "missing_context": ["Could not parse import 'external_dep'."],
        },
        status=AnalysisRunStatus.COMPLETED.value,
    )

    # Reopen from history
    reopened = repo_layer.reopen_review(saved_run.id, repository_id=repo.id)
    assert reopened is not None

    # Check top-level envelope fields
    assert reopened["run_id"] == str(saved_run.id)
    assert reopened["repository_id"] == str(repo.id)
    assert reopened["status"] == "COMPLETED"
    assert reopened["created_at"] is not None
    assert reopened["completed_at"] is not None
    assert reopened["error_message"] is None

    # Check target
    target = reopened["target"]
    assert target["path"] == "src/reopen_test.py"
    assert target["head_revision"] == "sha_reopen_456"

    # Check report contents
    report = reopened["report"]
    assert report["summary"] == "Reopenable review report with 2 findings."
    assert report["risk_level"] == "HIGH"
    assert report["total_findings"] == 2
    assert len(report["findings"]) == 2
    assert report["missing_context"] == ["Could not parse import 'external_dep'."]
    assert report["category_counts"]["security"] == 1
    assert report["category_counts"]["correctness"] == 1

    # Unauthorized reopening attempt fails (cross-repo boundary)
    other_repo_id = uuid.uuid4()
    assert repo_layer.reopen_review(saved_run.id, repository_id=other_repo_id) is None


def test_save_failed_review_distinct_from_zero_findings(db_session: Session) -> None:
    """Ensure failed reviews are persisted separately from successful zero-finding reviews."""
    user, repo = _create_test_user_and_repo(db_session, "user-failed-rev", "repo-failed-rev")
    repo_layer = AnalysisRunRepository(db_session)

    # 1. Persist failed review run
    failed_run = repo_layer.record_review_failure(
        repository_id=repo.id,
        error_message="GitHub token invalid or expired during PR diff retrieval.",
        target_path="src/broken.py",
        source_revision="bad_sha_000",
        user_id=user.id,
    )

    assert failed_run.status == AnalysisRunStatus.FAILED.value
    assert failed_run.error_message == "GitHub token invalid or expired during PR diff retrieval."
    assert failed_run.findings_count == 0

    reopened_failed = repo_layer.reopen_review(failed_run.id, repository_id=repo.id)
    assert reopened_failed is not None
    assert reopened_failed["status"] == "FAILED"
    assert reopened_failed["error_message"] == "GitHub token invalid or expired during PR diff retrieval."

    # 2. Persist clean successful review run with zero findings
    clean_run = repo_layer.save_review_run(
        repository_id=repo.id,
        user_id=user.id,
        target_path="src/perfect.py",
        source_revision="good_sha_111",
        findings=[],
        report={"summary": "Zero findings identified. Code is clean.", "risk_level": "NONE"},
        status=AnalysisRunStatus.COMPLETED.value,
    )

    assert clean_run.status == AnalysisRunStatus.COMPLETED.value
    assert clean_run.error_message is None
    assert clean_run.findings_count == 0

    reopened_clean = repo_layer.reopen_review(clean_run.id, repository_id=repo.id)
    assert reopened_clean is not None
    assert reopened_clean["status"] == "COMPLETED"
    assert reopened_clean["report"]["total_findings"] == 0
    assert reopened_clean["report"]["risk_level"] == "NONE"


def test_list_review_runs_filtering_and_pagination(db_session: Session) -> None:
    """Test filtering by status, target_path, source_revision, and pagination."""
    user, repo = _create_test_user_and_repo(db_session, "user-filter-rev", "repo-filter-rev")
    repo_layer = AnalysisRunRepository(db_session)

    # Seed 4 reviews
    repo_layer.save_review_run(
        repository_id=repo.id,
        target_path="src/a.py",
        source_revision="rev_1",
        status=AnalysisRunStatus.COMPLETED.value,
    )
    repo_layer.save_review_run(
        repository_id=repo.id,
        target_path="src/a.py",
        source_revision="rev_2",
        status=AnalysisRunStatus.COMPLETED.value,
    )
    repo_layer.save_review_run(
        repository_id=repo.id,
        target_path="src/b.py",
        source_revision="rev_1",
        status=AnalysisRunStatus.FAILED.value,
        error_message="Syntax failure",
    )
    repo_layer.save_review_run(
        repository_id=repo.id,
        target_path="src/b.py",
        source_revision="rev_2",
        status=AnalysisRunStatus.COMPLETED.value,
    )

    # Filter by target_path="src/a.py"
    runs, total = repo_layer.list_review_runs(repo.id, target_path="src/a.py")
    assert total == 2
    assert all(r.target_path == "src/a.py" for r in runs)

    # Filter by status="FAILED"
    failed_runs, failed_total = repo_layer.list_review_runs(repo.id, status="FAILED")
    assert failed_total == 1
    assert failed_runs[0].target_path == "src/b.py"

    # Pagination: limit 2, offset 0 -> 2 items, limit 2, offset 2 -> 2 items
    p1, t = repo_layer.list_review_runs(repo.id, limit=2, offset=0)
    assert t == 4
    assert len(p1) == 2

    p2, t = repo_layer.list_review_runs(repo.id, limit=2, offset=2)
    assert t == 4
    assert len(p2) == 2


def test_get_latest_review_and_duplicate_detection(db_session: Session) -> None:
    """Verify fetching latest review run and duplicate review detection."""
    user, repo = _create_test_user_and_repo(db_session, "user-latest-rev", "repo-latest-rev")
    repo_layer = AnalysisRunRepository(db_session)

    # Run 1
    repo_layer.save_review_run(
        repository_id=repo.id,
        target_path="src/cache.py",
        source_revision="sha_cache_1",
        status=AnalysisRunStatus.COMPLETED.value,
    )
    # Run 2 on same path, newer revision
    run2 = repo_layer.save_review_run(
        repository_id=repo.id,
        target_path="src/cache.py",
        source_revision="sha_cache_2",
        status=AnalysisRunStatus.COMPLETED.value,
    )

    latest = repo_layer.get_latest_review(repo.id, target_path="src/cache.py")
    assert latest is not None
    assert latest.id == run2.id
    assert latest.source_revision == "sha_cache_2"

    # Duplicate lookup
    dup = repo_layer.find_duplicate_review(
        repo.id, target_path="src/cache.py", source_revision="sha_cache_2"
    )
    assert dup is not None
    assert dup.id == run2.id


def test_delete_review_run(db_session: Session) -> None:
    """Verify deleting a review run cascades deletion to associated analysis_findings."""
    user, repo = _create_test_user_and_repo(db_session, "user-del-rev", "repo-del-rev")
    repo_layer = AnalysisRunRepository(db_session)

    findings = _sample_review_findings()[:2]
    run = repo_layer.save_review_run(
        repository_id=repo.id,
        target_path="src/delete_me.py",
        findings=findings,
        status=AnalysisRunStatus.COMPLETED.value,
    )

    run_id = run.id
    assert repo_layer.get_review_run(run_id, repository_id=repo.id) is not None

    # Delete
    deleted = repo_layer.delete_review_run(run_id, repository_id=repo.id)
    assert deleted is True

    # Verify run and cascaded findings no longer exist
    assert repo_layer.get_review_run(run_id, repository_id=repo.id) is None
    dangling_findings = (
        db_session.query(AnalysisFinding)
        .filter(AnalysisFinding.analysis_run_id == run_id)
        .all()
    )
    assert len(dangling_findings) == 0


def test_multi_tenant_repository_isolation(db_session: Session) -> None:
    """Verify strict multi-tenant boundary: Repository A's reviews are never accessible to Repository B."""
    user_a, repo_a = _create_test_user_and_repo(db_session, "user-iso-a", "repo-iso-a")
    user_b, repo_b = _create_test_user_and_repo(db_session, "user-iso-b", "repo-iso-b")
    repo_layer = AnalysisRunRepository(db_session)

    run_a = repo_layer.save_review_run(
        repository_id=repo_a.id,
        target_path="src/secret_a.py",
        source_revision="sha_a",
        status=AnalysisRunStatus.COMPLETED.value,
    )

    # 1. Querying Repo B for Repo A's run ID returns None
    assert repo_layer.get_review_run(run_a.id, repository_id=repo_b.id) is None
    assert repo_layer.reopen_review(run_a.id, repository_id=repo_b.id) is None

    # 2. Listing Repo B runs returns 0
    runs_b, total_b = repo_layer.list_review_runs(repo_b.id)
    assert total_b == 0
    assert len(runs_b) == 0

    # 3. Deleting from Repo B does not delete Repo A's run
    assert repo_layer.delete_review_run(run_a.id, repository_id=repo_b.id) is False
    assert repo_layer.get_review_run(run_a.id, repository_id=repo_a.id) is not None


def test_review_history_service_business_logic(db_session: Session) -> None:
    """Verify ReviewHistoryService methods and summary statistics."""
    user, repo = _create_test_user_and_repo(db_session, "user-svc-rev", "repo-svc-rev")
    service = ReviewHistoryService(session=db_session)

    findings = _sample_review_findings()

    # Save completed review via service
    completed_run = service.save_review(
        repository_id=repo.id,
        target_path="src/app.py",
        source_revision="sha_app_1",
        findings=findings,
        report={"summary": "Full review", "risk_level": "CRITICAL"},
        status=AnalysisRunStatus.COMPLETED.value,
    )
    assert completed_run.id is not None
    assert completed_run.findings_count == 5

    # Record failed review via service
    failed_run = service.record_failure(
        repository_id=repo.id,
        error_message="Model context length exceeded",
        target_path="src/large_file.py",
    )
    assert failed_run.status == "FAILED"

    # Summary statistics
    summary = service.get_review_summary(repo.id)
    assert summary["total_runs"] == 2
    assert summary["completed_runs"] == 1
    assert summary["failed_runs"] == 1
    assert summary["total_findings"] == 5
    assert summary["category_counts"]["security"] == 1
    assert summary["severity_counts"]["CRITICAL"] == 1

    # Reopen
    reopened = service.reopen_review(completed_run.id, repository_id=repo.id)
    assert reopened is not None
    assert reopened["report"]["risk_level"] == "CRITICAL"


def test_finding_deduplication_in_review(db_session: Session) -> None:
    """Verify identical duplicate findings within the same review are deduplicated."""
    user, repo = _create_test_user_and_repo(db_session, "user-dedup", "repo-dedup")
    repo_layer = AnalysisRunRepository(db_session)

    finding = {
        "category": "security",
        "severity": "HIGH",
        "title": "Insecure Deserialization",
        "description": "pickle.loads used on untrusted stream.",
        "source_reference": {"file_path": "src/loader.py", "start_line": 20, "end_line": 20},
        "evidence": "data = pickle.loads(stream.read())",
    }
    # Pass two identical findings
    run = repo_layer.save_review_run(
        repository_id=repo.id,
        target_path="src/loader.py",
        findings=[finding, finding],
        deduplicate_findings=True,
        status=AnalysisRunStatus.COMPLETED.value,
    )

    assert run.findings_count == 1
    retrieved = repo_layer.get_review_run(run.id, repository_id=repo.id)
    assert retrieved is not None
    assert len(retrieved.findings) == 1


def test_foreign_key_safety_with_synthetic_user(db_session: Session) -> None:
    """Verify saving a review run with an unpersisted synthetic user_id sets user_id=None safely."""
    user, repo = _create_test_user_and_repo(db_session, "user-synth-rev", "repo-synth-rev")
    repo_layer = AnalysisRunRepository(db_session)

    synthetic_user_id = uuid.uuid4()
    run = repo_layer.save_review_run(
        repository_id=repo.id,
        user_id=synthetic_user_id,
        target_path="src/safe.py",
        status=AnalysisRunStatus.COMPLETED.value,
    )

    assert run.id is not None
    assert run.user_id is None  # Coerced to None without FK crash


# ---------------------------------------------------------------------------
# API Integration Tests (POST /review -> DB persistence -> GET /analysis-runs)
# ---------------------------------------------------------------------------


def test_api_review_code_persistence_and_retrieval(
    client: TestClient,
    db_session: Session,
    test_user: User,
    auth_headers: dict[str, str],
) -> None:
    """Verify POST /review persists to DB and is retrievable via GET /analysis-runs."""
    installation = GitHubInstallation(
        id=uuid.uuid4(),
        user_id=test_user.id,
        installation_id=f"inst_{uuid.uuid4().hex[:8]}",
        account_login=test_user.login,
        permissions={"contents": "read"},
    )
    db_session.add(installation)
    db_session.flush()

    repo = Repository(
        id=uuid.uuid4(),
        user_id=test_user.id,
        installation_id=installation.id,
        github_repo_id=f"repo_{uuid.uuid4().hex[:8]}",
        owner=test_user.login,
        name="review-api-repo",
        default_branch="main",
        sync_status=SyncStatus.SYNCED,
    )
    db_session.add(repo)
    db_session.commit()
    db_session.refresh(repo)

    findings = _sample_review_findings()[:3]
    sample_report = {
        "summary": "API Code Review completed successfully with 3 findings.",
        "risk_level": "HIGH",
        "findings": findings,
        "total_findings": len(findings),
        "category_counts": {"security": 1, "correctness": 1, "performance": 1},
        "missing_context": [],
    }

    # Mock code review engine service
    class MockCodeReviewService:
        async def review(self, repository_id, payload, **kwargs):
            return {
                "run_id": str(uuid.uuid4()),
                "repository_id": str(repository_id),
                "status": "COMPLETED",
                "target": payload.target.model_dump(mode="json"),
                "report": sample_report,
            }

    app.state.code_review_service = MockCodeReviewService()
    app.state.review_history_service = ReviewHistoryService(session=db_session)

    try:
        payload = {
            "target": {
                "type": "file",
                "path": "src/api/auth.py",
            },
            "options": {
                "persist_run": True,
            },
            "include_static": True,
        }

        # 1. Execute review via API
        response = client.post(
            f"/api/v1/repositories/{repo.id}/review",
            json=payload,
            headers=auth_headers,
        )
        assert response.status_code == 200, response.text
        data = response.json()

        run_id = data["run_id"]
        assert data["status"] == "COMPLETED"
        assert data["report"]["total_findings"] == 3
        assert data["report"]["risk_level"] == "HIGH"

        # 2. List analysis runs filtered by feature_type=review
        list_res = client.get(
            f"/api/v1/repositories/{repo.id}/analysis-runs?feature_type=review",
            headers=auth_headers,
        )
        assert list_res.status_code == 200, list_res.text
        list_data = list_res.json()
        assert list_data["total"] >= 1
        run_summary = next(r for r in list_data["items"] if r["id"] == run_id)
        assert run_summary["feature_type"] == "review"
        assert run_summary["status"] == "COMPLETED"
        assert run_summary["findings_count"] == 3

        # 3. Retrieve detailed run via GET /api/v1/analysis-runs/{run_id}
        detail_res = client.get(
            f"/api/v1/analysis-runs/{run_id}",
            headers=auth_headers,
        )
        assert detail_res.status_code == 200, detail_res.text
        detail = detail_res.json()
        assert detail["id"] == run_id
        assert detail["feature_type"] == "review"
        assert detail["status"] == "COMPLETED"
        assert detail["findings_count"] == 3
        assert len(detail["findings"]) == 3
        assert detail["result_payload"]["report"]["risk_level"] == "HIGH"

    finally:
        app.state.code_review_service = None


def test_api_review_code_failure_recording(
    client: TestClient,
    db_session: Session,
    test_user: User,
    auth_headers: dict[str, str],
) -> None:
    """Verify that execution failures in POST /review are persisted as FAILED runs in history."""
    from app.core.errors import APIError, ErrorCode

    installation = GitHubInstallation(
        id=uuid.uuid4(),
        user_id=test_user.id,
        installation_id=f"inst_{uuid.uuid4().hex[:8]}",
        account_login=test_user.login,
        permissions={"contents": "read"},
    )
    db_session.add(installation)
    db_session.flush()

    repo = Repository(
        id=uuid.uuid4(),
        user_id=test_user.id,
        installation_id=installation.id,
        github_repo_id=f"repo_{uuid.uuid4().hex[:8]}",
        owner=test_user.login,
        name="review-fail-repo",
        default_branch="main",
        sync_status=SyncStatus.SYNCED,
    )
    db_session.add(repo)
    db_session.commit()
    db_session.refresh(repo)

    class FailingReviewService:
        async def review(self, *args, **kwargs):
            raise APIError(500, ErrorCode.ANALYSIS_FAILED, "Review LLM model timeout.")

    app.state.code_review_service = FailingReviewService()
    app.state.review_history_service = ReviewHistoryService(session=db_session)

    try:
        payload = {
            "target": {
                "type": "file",
                "path": "src/fail_test.py",
            },
            "options": {
                "persist_run": True,
            },
        }

        # Review call fails with 500
        res = client.post(
            f"/api/v1/repositories/{repo.id}/review",
            json=payload,
            headers=auth_headers,
        )
        assert res.status_code == 500

        # Verify failed run was recorded in DB history
        list_res = client.get(
            f"/api/v1/repositories/{repo.id}/analysis-runs?feature_type=review",
            headers=auth_headers,
        )
        assert list_res.status_code == 200
        items = list_res.json()["items"]
        assert len(items) >= 1
        failed_run = items[0]
        assert failed_run["status"] == "FAILED"
        assert failed_run["error_message"] == "Review LLM model timeout."
        assert failed_run["findings_count"] == 0

    finally:
        app.state.code_review_service = None
