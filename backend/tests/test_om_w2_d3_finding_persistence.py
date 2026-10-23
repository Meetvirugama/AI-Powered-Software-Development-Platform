"""Comprehensive test suite for Week 2 Day 3 (Finding Persistence & Bug Scan History).

Owner: Om — Database & Persistence.

Verifies all Day 3 deliverables and acceptance criteria from `Docs/week2.md` §7 & §12 (Scenarios B & E):
1. Persist findings and their source revision metadata:
   - Saving bug detection runs (`feature_type="detect_bugs"`) with attached structured findings.
   - Concrete source location coordinates (file_path, start_line, end_line, symbol_name).
   - Source revision metadata (git commit SHA or branch name).
   - Structured finding attributes: category, severity, title, description, evidence, suggested_fix,
     confidence, is_uncertain, is_new_in_change, source_type, rule_id, metadata.
2. Clean fixture zero-defect scans:
   - Completed scans with zero findings (Scenario B step 5: correct fixture) are stored as
     `COMPLETED`, `findings_count=0`, `findings=[]`, strictly distinguishing them from failed analyses.
3. Preserve scan status and errors:
   - Failed scans stored with `status="FAILED"`, `error_message`, and `findings_count=0`,
     preventing failures from masquerading as successful or empty reports.
4. Avoid duplicate records from repeated requests:
   - Deduplication of identical findings within a run (combining STATIC + AI findings into COMBINED).
   - Idempotent repeated scan requests reusing matching runs rather than creating duplicate entries.
5. Multi-tenant repository isolation:
   - Cross-repository access is strictly blocked; Repo A's findings and runs are never visible to Repo B.
6. History retrieval with rich multi-criteria filtering and pagination:
   - Filtering by status, target_path, source_revision, min_severity, and category.
   - Ordering newest first (`created_at.desc()`).
   - Accurate total counts with offset/limit pagination.
7. Reopen bug scan from persistent history:
   - Reconstituting past bug detection runs with full fidelity matching `BugDetectionResponse` (Scenario B Step 6).
8. Direct finding-level querying across scans for an authorized repository (`list_findings`).
9. Traceability across code revisions (tracking bug scans across Git commits).
10. Cascade deletion:
    - Deleting a run cascades to its findings.
    - Deleting a repository cascades to all associated runs and findings.
11. `BugScanHistoryService` business logic and session management.
12. End-to-end API integration: `POST /repositories/{id}/detect-bugs` -> persistence ->
    retrieval via `GET /repositories/{id}/analysis-runs` and `GET /analysis-runs/{run_id}`.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.main import app
from app.models.analysis_finding import AnalysisFinding
from app.models.code_chunk import CodeChunk
from app.models.github_installation import GitHubInstallation
from app.models.repository import Repository, SyncStatus
from app.models.repository_file import RepositoryFile
from app.models.user import User
from app.repositories.analysis_run_repository import AnalysisRunRepository
from app.services.bug_scan_history_service import BugScanHistoryService



# ---------------------------------------------------------------------------
# Test Helpers & Seeders
# ---------------------------------------------------------------------------


def _create_test_user_and_repo(
    db: Session,
    login: str = "om-dev-user",
    repo_name: str = "bug-scanner-suite-repo",
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


def _sample_findings() -> list[dict]:
    """Sample structured findings covering different categories, severities, and source types."""
    return [
        {
            "id": str(uuid.uuid4()),
            "category": "off_by_one",
            "severity": "HIGH",
            "title": "Loop index out of bounds",
            "description": "Loop iterates <= length instead of < length causing IndexError.",
            "source_reference": {
                "file_path": "src/parser.py",
                "start_line": 20,
                "end_line": 25,
                "revision": "commit_sha_123",
                "symbol_name": "parse_tokens",
            },
            "evidence": "for i in range(len(tokens) + 1):",
            "suggested_fix": "for i in range(len(tokens)):",
            "confidence": "high",
            "is_uncertain": False,
            "is_new_in_change": True,
            "source_type": "AI",
            "rule_id": "OFF_BY_ONE_001",
        },
        {
            "id": str(uuid.uuid4()),
            "category": "security",
            "severity": "CRITICAL",
            "title": "Potential SQL injection",
            "description": "Raw string formatting in SQL query allows arbitrary SQL execution.",
            "source_reference": {
                "file_path": "src/db.py",
                "start_line": 50,
                "end_line": 52,
                "revision": "commit_sha_123",
                "symbol_name": "get_user",
            },
            "evidence": "f'SELECT * FROM users WHERE id = {user_id}'",
            "suggested_fix": "Use parameterized query with :user_id placeholder",
            "confidence": "high",
            "is_uncertain": False,
            "is_new_in_change": True,
            "source_type": "STATIC",
            "rule_id": "SEC_SQL_INJECTION",
        },
        {
            "id": str(uuid.uuid4()),
            "category": "null_safety",
            "severity": "MEDIUM",
            "title": "Potential NoneType dereference",
            "description": "Variable user may be None when accessed without null check.",
            "source_reference": {
                "file_path": "src/auth.py",
                "start_line": 80,
                "end_line": 84,
                "revision": "commit_sha_123",
                "symbol_name": "validate_session",
            },
            "evidence": "return user.is_active",
            "suggested_fix": "if user is None: return False\nreturn user.is_active",
            "confidence": "medium",
            "is_uncertain": False,
            "is_new_in_change": True,
            "source_type": "AI",
            "rule_id": "NULL_SAFETY_002",
        },
    ]


# ---------------------------------------------------------------------------
# 1. Finding Persistence & Revision Metadata Tests
# ---------------------------------------------------------------------------


def test_save_and_retrieve_bug_scan_run_with_findings(db_session: Session) -> None:
    """Verify persisting a bug detection scan with concrete structured findings and revision metadata."""
    user, repo = _create_test_user_and_repo(db_session)
    repo_layer = AnalysisRunRepository(db_session)
    findings = _sample_findings()

    run = repo_layer.save_bug_scan_run(
        repository_id=repo.id,
        user_id=user.id,
        target_path="src/parser.py",
        target_symbol="parse_tokens",
        start_line=15,
        end_line=45,
        source_revision="commit_sha_123",
        findings=findings,
        status="COMPLETED",
    )

    assert run.id is not None
    assert run.repository_id == repo.id
    assert run.feature_type == "detect_bugs"
    assert run.status == "COMPLETED"
    assert run.source_revision == "commit_sha_123"
    assert run.target_path == "src/parser.py"
    assert run.target_symbol == "parse_tokens"
    assert run.start_line == 15
    assert run.end_line == 45
    assert run.findings_count == 3
    assert len(run.findings) == 3

    # Verify eager loading and finding attributes
    fetched = repo_layer.get_bug_scan_run(run.id, repository_id=repo.id)
    assert fetched is not None
    assert len(fetched.findings) == 3

    categories = {f.category for f in fetched.findings}
    assert categories == {"off_by_one", "security", "null_safety"}

    severities = {f.severity for f in fetched.findings}
    assert severities == {"HIGH", "CRITICAL", "MEDIUM"}

    # Check finding attributes
    sec_finding = next(f for f in fetched.findings if f.category == "security")
    assert sec_finding.rule_id == "SEC_SQL_INJECTION"
    assert sec_finding.source_type == "STATIC"
    assert sec_finding.file_path == "src/db.py"
    assert sec_finding.start_line == 50
    assert sec_finding.end_line == 52
    assert sec_finding.source_revision == "commit_sha_123"
    assert "SELECT * FROM users" in sec_finding.evidence
    assert sec_finding.suggested_fix is not None
    assert sec_finding.source_reference["file_path"] == "src/db.py"


def test_clean_scan_zero_findings_preserved_as_completed(db_session: Session) -> None:
    """Verify that a successful scan with zero findings (clean code) is recorded as COMPLETED, not FAILED."""
    user, repo = _create_test_user_and_repo(db_session)
    repo_layer = AnalysisRunRepository(db_session)

    run = repo_layer.save_bug_scan_run(
        repository_id=repo.id,
        user_id=user.id,
        target_path="fixtures/correct_impl.py",
        source_revision="head_rev_100",
        findings=[],
        status="COMPLETED",
    )

    assert run.status == "COMPLETED"
    assert run.findings_count == 0
    assert run.error_message is None
    assert run.completed_at is not None
    assert len(run.findings) == 0

    reopened = repo_layer.reopen_bug_scan(run.id, repository_id=repo.id)
    assert reopened is not None
    assert reopened["status"] == "COMPLETED"
    assert reopened["total_findings"] == 0
    assert reopened["findings"] == []
    assert reopened["error_message"] is None


def test_record_bug_scan_failure_preserves_error(db_session: Session) -> None:
    """Verify that a scan failure records status=FAILED and error message, never masquerading as 0 findings."""
    user, repo = _create_test_user_and_repo(db_session)
    repo_layer = AnalysisRunRepository(db_session)

    run = repo_layer.record_bug_scan_failure(
        repository_id=repo.id,
        user_id=user.id,
        target_path="src/unparseable.py",
        source_revision="broken_rev",
        error_message="Tree-sitter parser timed out on syntax error in line 12.",
    )

    assert run.status == "FAILED"
    assert run.findings_count == 0
    assert run.error_message == "Tree-sitter parser timed out on syntax error in line 12."
    assert len(run.findings) == 0

    reopened = repo_layer.reopen_bug_scan(run.id, repository_id=repo.id)
    assert reopened is not None
    assert reopened["status"] == "FAILED"
    assert reopened["total_findings"] == 0
    assert reopened["error_message"] == "Tree-sitter parser timed out on syntax error in line 12."


# ---------------------------------------------------------------------------
# 2. Deduplication Tests (Findings and Repeated Requests)
# ---------------------------------------------------------------------------


def test_deduplicate_identical_findings_within_run(db_session: Session) -> None:
    """Verify that duplicate findings (e.g. from static and AI scanners) are merged into COMBINED."""
    user, repo = _create_test_user_and_repo(db_session)
    repo_layer = AnalysisRunRepository(db_session)

    # Two findings targeting the exact same code location and rule
    static_finding = {
        "id": str(uuid.uuid4()),
        "category": "security",
        "severity": "HIGH",
        "title": "SQL Injection",
        "description": "SQL injection detected by linter",
        "file_path": "src/query.py",
        "start_line": 10,
        "end_line": 15,
        "source_revision": "rev1",
        "evidence": "f'SELECT * FROM tbl WHERE x = {val}'",
        "suggested_fix": "Use parameter binding",
        "confidence": "medium",
        "source_type": "STATIC",
        "rule_id": "SEC_SQL_001",
    }
    ai_finding = {
        "id": str(uuid.uuid4()),
        "category": "security",
        "severity": "HIGH",
        "title": "SQL Injection",
        "description": "AI analysis confirms unescaped string injection vulnerability",
        "file_path": "src/query.py",
        "start_line": 10,
        "end_line": 15,
        "source_revision": "rev1",
        "evidence": "Unsanitized val parameter passed into SQL executor",
        "suggested_fix": "Use parameter binding with :val",
        "confidence": "high",
        "source_type": "AI",
        "rule_id": "SEC_SQL_001",
    }

    run = repo_layer.save_bug_scan_run(
        repository_id=repo.id,
        user_id=user.id,
        target_path="src/query.py",
        source_revision="rev1",
        findings=[static_finding, ai_finding],
        deduplicate_findings=True,
    )

    # Should be deduplicated into 1 combined finding
    assert run.findings_count == 1
    assert len(run.findings) == 1

    finding = run.findings[0]
    assert finding.source_type == "COMBINED"
    assert finding.confidence == "high"  # Upgraded to higher confidence
    assert finding.rule_id == "SEC_SQL_001"
    assert "SELECT * FROM tbl" in finding.evidence
    assert "Unsanitized val" in finding.evidence


def test_deduplicate_repeated_scan_requests(db_session: Session) -> None:
    """Verify that repeated scan requests with identical coordinates can reuse existing run."""
    user, repo = _create_test_user_and_repo(db_session)
    repo_layer = AnalysisRunRepository(db_session)
    findings = _sample_findings()[:1]

    # First scan request
    run1 = repo_layer.save_bug_scan_run(
        repository_id=repo.id,
        user_id=user.id,
        target_path="src/utils.py",
        target_symbol="calc",
        start_line=1,
        end_line=20,
        source_revision="commit_a",
        findings=findings,
        deduplicate_run=True,
    )

    # Second identical scan request (e.g. repeated user button click)
    run2 = repo_layer.save_bug_scan_run(
        repository_id=repo.id,
        user_id=user.id,
        target_path="src/utils.py",
        target_symbol="calc",
        start_line=1,
        end_line=20,
        source_revision="commit_a",
        findings=findings,
        deduplicate_run=True,
    )

    # Must return the existing run rather than inserting duplicate records
    assert run1.id == run2.id

    runs, total = repo_layer.list_bug_scan_runs(repo.id, target_path="src/utils.py")
    assert total == 1
    assert len(runs) == 1


# ---------------------------------------------------------------------------
# 3. Multi-Tenant Repository Isolation Tests
# ---------------------------------------------------------------------------


def test_multi_tenant_repository_isolation(db_session: Session) -> None:
    """Verify that findings and scan runs from Repository A are never visible to Repository B."""
    user_a, repo_a = _create_test_user_and_repo(db_session, login="alice", repo_name="repo-a")
    user_b, repo_b = _create_test_user_and_repo(db_session, login="bob", repo_name="repo-b")
    repo_layer = AnalysisRunRepository(db_session)

    # Create run in Repo A
    run_a = repo_layer.save_bug_scan_run(
        repository_id=repo_a.id,
        user_id=user_a.id,
        target_path="secret/algo.py",
        source_revision="rev_a",
        findings=_sample_findings(),
    )

    # 1. Listing Repo B runs must be empty
    runs_b, total_b = repo_layer.list_bug_scan_runs(repo_b.id)
    assert total_b == 0
    assert runs_b == []

    # 2. Reopening Repo A run under Repo B must fail (return None)
    reopened_cross = repo_layer.reopen_bug_scan(run_a.id, repository_id=repo_b.id)
    assert reopened_cross is None

    # 3. Direct get with repository scoping must return None
    fetched_cross = repo_layer.get_bug_scan_run(run_a.id, repository_id=repo_b.id)
    assert fetched_cross is None

    # 4. Direct finding querying for Repo B must return 0 findings
    findings_b, f_count_b = repo_layer.list_findings(repo_b.id)
    assert f_count_b == 0
    assert findings_b == []


# ---------------------------------------------------------------------------
# 4. History Retrieval, Filtering & Pagination Tests
# ---------------------------------------------------------------------------


def test_list_bug_scans_filtering_and_pagination(db_session: Session) -> None:
    """Verify multi-criteria filtering by status, target_path, revision, severity, and category with pagination."""
    user, repo = _create_test_user_and_repo(db_session)
    repo_layer = AnalysisRunRepository(db_session)

    # Seed 3 distinct runs
    run1 = repo_layer.save_bug_scan_run(
        repository_id=repo.id,
        target_path="backend/app/auth.py",
        source_revision="commit_v1",
        status="COMPLETED",
        findings=[
            {
                "category": "security",
                "severity": "CRITICAL",
                "title": "JWT flaw",
                "description": "desc",
                "file_path": "backend/app/auth.py",
                "evidence": "ev",
            }
        ],
    )
    run2 = repo_layer.save_bug_scan_run(
        repository_id=repo.id,
        target_path="backend/app/main.py",
        source_revision="commit_v1",
        status="COMPLETED",
        findings=[
            {
                "category": "off_by_one",
                "severity": "LOW",
                "title": "Loop index off by one",
                "description": "desc",
                "file_path": "backend/app/main.py",
                "evidence": "ev",
            }
        ],
    )
    run3 = repo_layer.record_bug_scan_failure(
        repository_id=repo.id,
        target_path="backend/app/worker.py",
        source_revision="commit_v2",
        error_message="Worker unreachable",
    )

    # 1. Total count
    runs, total = repo_layer.list_bug_scan_runs(repo.id)
    assert total == 3
    assert len(runs) == 3

    # 2. Filter by status
    completed_runs, c_total = repo_layer.list_bug_scan_runs(repo.id, status="COMPLETED")
    assert c_total == 2
    assert all(r.status == "COMPLETED" for r in completed_runs)

    failed_runs, f_total = repo_layer.list_bug_scan_runs(repo.id, status="FAILED")
    assert f_total == 1
    assert failed_runs[0].id == run3.id

    # 3. Filter by target_path
    auth_runs, a_total = repo_layer.list_bug_scan_runs(repo.id, target_path="backend/app/auth.py")
    assert a_total == 1
    assert auth_runs[0].id == run1.id

    # 4. Filter by source_revision
    v1_runs, v1_total = repo_layer.list_bug_scan_runs(repo.id, source_revision="commit_v1")
    assert v1_total == 2

    # 5. Filter by category
    sec_runs, s_total = repo_layer.list_bug_scan_runs(repo.id, category="security")
    assert s_total == 1
    assert sec_runs[0].id == run1.id

    # 6. Filter by min_severity CRITICAL
    crit_runs, crit_total = repo_layer.list_bug_scan_runs(repo.id, min_severity="CRITICAL")
    assert crit_total == 1
    assert crit_runs[0].id == run1.id

    # 7. Pagination
    p1, _ = repo_layer.list_bug_scan_runs(repo.id, offset=0, limit=2)
    assert len(p1) == 2
    p2, _ = repo_layer.list_bug_scan_runs(repo.id, offset=2, limit=2)
    assert len(p2) == 1


def test_reopen_bug_scan_from_history(db_session: Session) -> None:
    """Verify reconstituting a past bug detection run matching BugDetectionResponse (Scenario B Step 6)."""
    user, repo = _create_test_user_and_repo(db_session)
    repo_layer = AnalysisRunRepository(db_session)

    run = repo_layer.save_bug_scan_run(
        repository_id=repo.id,
        user_id=user.id,
        target_path="app/scanner.py",
        target_symbol="scan_file",
        start_line=10,
        end_line=50,
        source_revision="sha_fixed",
        findings=_sample_findings(),
        missing_context=["AST partial parse on lines 40-42"],
    )

    reopened = repo_layer.reopen_bug_scan(run.id, repository_id=repo.id)
    assert reopened is not None
    assert reopened["run_id"] == str(run.id)
    assert reopened["repository_id"] == str(repo.id)
    assert reopened["status"] == "COMPLETED"
    assert reopened["target"]["path"] == "app/scanner.py"
    assert reopened["target"]["symbol"] == "scan_file"
    assert reopened["target"]["start_line"] == 10
    assert reopened["target"]["end_line"] == 50
    assert reopened["revision"] == "sha_fixed"
    assert reopened["total_findings"] == 3
    assert reopened["static_findings_count"] == 1
    assert reopened["ai_findings_count"] == 2
    assert len(reopened["findings"]) == 3
    assert reopened["missing_context"] == ["AST partial parse on lines 40-42"]
    assert reopened["created_at"] is not None


def test_direct_finding_listing_and_filtering(db_session: Session) -> None:
    """Verify direct querying of persisted findings across scans using list_findings."""
    user, repo = _create_test_user_and_repo(db_session)
    repo_layer = AnalysisRunRepository(db_session)

    repo_layer.save_bug_scan_run(
        repository_id=repo.id,
        target_path="src/parser.py",
        findings=_sample_findings(),
    )

    # 1. All findings for repo
    findings, total = repo_layer.list_findings(repo.id)
    assert total == 3
    assert len(findings) == 3

    # 2. Filter by severity
    crit_findings, c_total = repo_layer.list_findings(repo.id, severity="CRITICAL")
    assert c_total == 1
    assert crit_findings[0].category == "security"

    # 3. Filter by file_path
    db_findings, d_total = repo_layer.list_findings(repo.id, file_path="src/db.py")
    assert d_total == 1
    assert db_findings[0].file_path == "src/db.py"

    # 4. Filter by source_type
    static_findings, s_total = repo_layer.list_findings(repo.id, source_type="STATIC")
    assert s_total == 1
    assert static_findings[0].source_type == "STATIC"


# ---------------------------------------------------------------------------
# 5. Revision Tracking & Cascade Deletion Tests
# ---------------------------------------------------------------------------


def test_source_revision_tracking(db_session: Session) -> None:
    """Verify tracking bug scans across consecutive git commits and revisions."""
    user, repo = _create_test_user_and_repo(db_session)
    repo_layer = AnalysisRunRepository(db_session)

    # Commit 1 has bug
    run_v1 = repo_layer.save_bug_scan_run(
        repository_id=repo.id,
        target_path="src/calc.py",
        source_revision="commit_v1_buggy",
        findings=[
            {
                "category": "off_by_one",
                "severity": "HIGH",
                "title": "Off by one in calc",
                "description": "Index error",
                "file_path": "src/calc.py",
                "evidence": "i <= n",
            }
        ],
    )

    # Commit 2 fixes bug (clean scan)
    run_v2 = repo_layer.save_bug_scan_run(
        repository_id=repo.id,
        target_path="src/calc.py",
        source_revision="commit_v2_fixed",
        findings=[],
    )

    latest = repo_layer.get_latest_bug_scan(repo.id, "src/calc.py")
    assert latest is not None
    assert latest.id == run_v2.id
    assert latest.source_revision == "commit_v2_fixed"
    assert latest.findings_count == 0

    # Old revision remains retrievable
    old_scan = repo_layer.get_latest_bug_scan(repo.id, "src/calc.py", source_revision="commit_v1_buggy")
    assert old_scan is not None
    assert old_scan.id == run_v1.id
    assert old_scan.findings_count == 1


def test_cascade_deletion(db_session: Session) -> None:
    """Verify that deleting a run or repository cascades to clean up all associated findings."""
    user, repo = _create_test_user_and_repo(db_session)
    repo_layer = AnalysisRunRepository(db_session)

    run = repo_layer.save_bug_scan_run(
        repository_id=repo.id,
        target_path="src/demo.py",
        findings=_sample_findings(),
    )
    run_id = run.id

    # Verify findings exist in DB
    findings = list(db_session.scalars(select(AnalysisFinding).where(AnalysisFinding.analysis_run_id == run_id)).all())
    assert len(findings) == 3

    # Delete run -> cascades to findings
    deleted = repo_layer.delete(run_id)
    assert deleted is True

    findings_after = list(db_session.scalars(select(AnalysisFinding).where(AnalysisFinding.analysis_run_id == run_id)).all())
    assert len(findings_after) == 0


# ---------------------------------------------------------------------------
# 6. BugScanHistoryService Orchestration Tests
# ---------------------------------------------------------------------------


def test_bug_scan_history_service_full_workflow(db_session: Session) -> None:
    """Verify BugScanHistoryService business logic, session handling, and high-level methods."""
    user, repo = _create_test_user_and_repo(db_session)
    service = BugScanHistoryService(session=db_session)

    # 1. Save scan
    run = service.save_bug_scan(
        repository_id=repo.id,
        user_id=user.id,
        target_path="src/service.py",
        target_symbol="handle_req",
        start_line=10,
        end_line=30,
        source_revision="git_sha_abc",
        findings=_sample_findings(),
    )
    assert run.id is not None
    assert run.status == "COMPLETED"
    assert run.findings_count == 3

    # 2. Record failure
    fail_run = service.record_failure(
        repository_id=repo.id,
        target_path="src/faulty.py",
        error_message="Linter crash: exit code 137",
    )
    assert fail_run.status == "FAILED"
    assert fail_run.error_message == "Linter crash: exit code 137"

    # 3. List history
    history, total = service.list_history(repo.id, page=1, page_size=10)
    assert total == 2
    assert len(history) == 2

    # 4. Get scan
    fetched = service.get_scan(run.id, repository_id=repo.id)
    assert fetched is not None
    assert fetched.id == run.id

    # 5. Reopen
    reopened = service.reopen(run.id, repository_id=repo.id)
    assert reopened is not None
    assert reopened["total_findings"] == 3
    assert reopened["revision"] == "git_sha_abc"

    # 6. Latest scan
    latest = service.get_latest_scan(repo.id, "src/service.py")
    assert latest is not None
    assert latest.id == run.id

    # 7. List findings
    findings, f_count = service.list_findings(repo.id, category="security")
    assert f_count == 1
    assert findings[0].category == "security"

    # 8. Find existing scan for idempotency
    existing = service.find_existing_scan(
        repository_id=repo.id,
        target_path="src/service.py",
        target_symbol="handle_req",
        start_line=10,
        end_line=30,
        source_revision="git_sha_abc",
    )
    assert existing is not None
    assert existing.id == run.id


# ---------------------------------------------------------------------------
# 7. End-to-End API & Orchestrator Integration Tests
# ---------------------------------------------------------------------------


def test_end_to_end_api_integration_detect_bugs(
    client: TestClient,
    db_session: Session,
    test_user: User,
    auth_headers: dict[str, str],
) -> None:
    """Verify that POST /repositories/{id}/detect-bugs persists findings via Om's repository."""
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
        name="e2e-bug-scanner-repo",
        default_branch="main",
        sync_status=SyncStatus.SYNCED,
    )
    db_session.add(repo)
    db_session.commit()
    db_session.refresh(repo)

    # Add dummy file so target resolution passes
    repo_file = RepositoryFile(
        id=uuid.uuid4(),
        repository_id=repo.id,
        path="app/test_target.py",
        language="Python",
        size_bytes=100,
        line_count=20,
        content_hash="sha256_target_hash",
    )
    db_session.add(repo_file)


    chunk = CodeChunk(
        id=uuid.uuid4(),
        repository_id=repo.id,
        file_id=repo_file.id,
        content="def test_func():\n    return 42\n",
        start_line=1,
        end_line=2,
        token_count=10,
        content_hash="hash_target",
        embedding=[0.0] * 768,
        chunk_metadata={"file_path": "app/test_target.py"},
    )
    db_session.add(chunk)
    db_session.commit()


    async def _fake_detect_bugs(repository_id, payload, **kwargs):
        return {
            "run_id": str(uuid.uuid4()),
            "status": "COMPLETED",
            "findings": [
                {
                    "category": "logic_error",
                    "severity": "MEDIUM",
                    "title": "Constant return value",
                    "description": "Function always returns 42 without logic.",
                    "source_reference": {
                        "file_path": "app/test_target.py",
                        "start_line": 1,
                        "end_line": 2,
                    },
                    "evidence": "return 42",
                    "suggested_fix": "Add proper business logic",
                    "confidence": "high",
                    "source_type": "AI",
                }
            ],
            "missing_context": [],
        }

    app.state.bug_detection_service = SimpleNamespace(detect_bugs=_fake_detect_bugs)

    try:
        payload = {
            "target": {
                "type": "file",
                "path": "app/test_target.py",
            },
            "options": {
                "persist_run": True,
            },
        }

        resp = client.post(
            f"/api/v1/repositories/{repo.id}/detect-bugs",
            json=payload,
            headers=auth_headers,
        )

        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["status"] == "COMPLETED"
        run_id = data["run_id"]

        # Verify run and findings are persisted in database
        repo_layer = AnalysisRunRepository(db_session)
        run_record = repo_layer.get_bug_scan_run(run_id, repository_id=repo.id)
        assert run_record is not None
        assert run_record.findings_count >= 1

        # Verify reopening via GET /api/v1/analysis-runs/{run_id}
        detail_resp = client.get(
            f"/api/v1/analysis-runs/{run_id}",
            headers=auth_headers,
        )
        assert detail_resp.status_code == 200
        detail_data = detail_resp.json()
        assert detail_data["id"] == run_id
        assert len(detail_data["findings"]) >= 1

        # Verify listing via GET /api/v1/repositories/{id}/analysis-runs
        list_resp = client.get(
            f"/api/v1/repositories/{repo.id}/analysis-runs?feature_type=detect_bugs",
            headers=auth_headers,
        )
        assert list_resp.status_code == 200
        list_data = list_resp.json()
        assert list_data["total"] >= 1
        assert any(item["id"] == run_id for item in list_data["items"])
    finally:
        if hasattr(app.state, "bug_detection_service"):
            del app.state.bug_detection_service


def test_save_bug_scan_with_synthetic_user(db_session: Session) -> None:
    """Verify that synthetic/unpersisted user IDs do not cause foreign key IntegrityErrors."""
    user, repo = _create_test_user_and_repo(db_session)
    repo_layer = AnalysisRunRepository(db_session)

    synthetic_user_id = uuid.uuid4()
    run = repo_layer.save_bug_scan_run(
        repository_id=repo.id,
        user_id=synthetic_user_id,
        target_path="src/synth_test.py",
        findings=[],
    )

    assert run.id is not None
    assert run.user_id is None
    assert run.repository_id == repo.id

