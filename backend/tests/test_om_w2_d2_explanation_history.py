"""Comprehensive test suite for Week 2 Day 2 (Persistent Explanation History).

Owner: Om — Database & Persistence.

Verifies all Day 2 deliverables and acceptance criteria from `Docs/week2.md` §6 & §12:
1. Store completed code explanation runs with rich analysis metadata
   (purpose, logic flow, key symbols, inputs/outputs, dependencies, limitations, sources).
2. Record repository, target file, target symbol, line range, and source revision.
3. Store failure status separately from successful output with descriptive error messages,
   preventing failed runs from masquerading as successful or empty results.
4. History retrieval using existing persistence conventions:
   - Scoped to authorized repository (multi-tenant repository isolation).
   - Ordered newest first (`created_at.desc()`).
   - Paginated (`offset`, `limit`) with accurate total counts.
   - Multi-criteria filtering by status, target_path, target_symbol, and source_revision.
5. Reopening past explanation runs from persistent history (Scenario A Step 7).
6. Traceability across code revisions (tracking explanations across Git commits).
7. `ExplanationHistoryService` business logic and session management.
8. End-to-end API integration: `POST /repositories/{id}/explain` -> persists run ->
   reopening via `GET /repositories/{id}/analysis-runs` and `GET /analysis-runs/{run_id}`.
9. Resilient foreign key handling when synthetic user tokens are supplied.
10. Repository cascade deletion cleaning up all associated explanation runs.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from app.core.database import Base
from app.main import app
from app.models.analysis_run import AnalysisFeature, AnalysisRun, AnalysisRunStatus
from app.models.code_chunk import CodeChunk
from app.models.code_symbol import CodeSymbol
from app.models.github_installation import GitHubInstallation
from app.models.repository import Repository, SyncStatus
from app.models.repository_file import RepositoryFile
from app.models.symbol_edge import SymbolEdge
from app.models.user import User
from app.repositories.analysis_run_repository import AnalysisRunRepository
from app.schemas.analysis import AnalysisSourceReference, AnalysisTarget, CodeExplanation, SymbolSummary
from app.services.explanation_history_service import ExplanationHistoryService


# ---------------------------------------------------------------------------
# Test Helpers & Seeders
# ---------------------------------------------------------------------------


def _create_test_user_and_repo(
    db: Session,
    login: str = "om-dev-user",
    repo_name: str = "explanation-suite-repo",
) -> tuple[User, Repository]:
    """Helper to seed valid User, Installation, and Repository records."""
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


def _sample_explanation_dict() -> dict:
    """Provide a full-fidelity explanation dictionary matching Dev's CodeExplanation schema."""
    return {
        "purpose": "Verifies JWT tokens and extracts authenticated user session claims.",
        "logic_flow": [
            "Extracts Authorization header and validates Bearer prefix.",
            "Decodes token payload using configured asymmetric public key.",
            "Verifies token expiration, audience, and issuer claims.",
            "Returns validated UserClaims dictionary or raises AuthenticationError.",
        ],
        "key_symbols": [
            {
                "name": "verify_token",
                "kind": "function",
                "role": "Decodes and cryptographically validates JWT token.",
                "start_line": 25,
                "end_line": 48,
            },
            {
                "name": "UserClaims",
                "kind": "class",
                "role": "Typed data structure encapsulating user ID, roles, and permissions.",
                "start_line": 10,
                "end_line": 22,
            },
        ],
        "inputs_and_outputs": (
            "Input: token (str), options (Optional[VerifyOptions]). "
            "Output: UserClaims instance. Raises: ExpiredSignatureError, InvalidTokenError."
        ),
        "dependencies": [
            "jwt.decode",
            "app.core.config.get_settings",
            "app.core.errors.AuthenticationError",
        ],
        "assumptions_and_limitations": [
            "Public key is rotated externally via JWKS endpoint.",
            "Token revocation list / blocklist lookup requires Redis cache connection.",
        ],
        "sources": [
            {
                "file_path": "backend/app/services/auth.py",
                "start_line": 25,
                "end_line": 48,
                "revision": "git-commit-hash-v1",
                "symbol_name": "verify_token",
            }
        ],
        "confidence": "high",
        "missing_context": [],
    }


# ---------------------------------------------------------------------------
# 1. Store Completed Explanation with Full Analysis Metadata
# ---------------------------------------------------------------------------


def test_store_completed_explanation_metadata(db_session: Session) -> None:
    """Verify persisting a completed explanation run with all required metadata."""
    user, repo = _create_test_user_and_repo(db_session)
    repo_layer = AnalysisRunRepository(db_session)

    explanation_data = _sample_explanation_dict()
    run = repo_layer.save_explanation_run(
        repository_id=repo.id,
        user_id=user.id,
        target_path="backend/app/services/auth.py",
        target_symbol="verify_token",
        start_line=25,
        end_line=48,
        source_revision="git-commit-hash-v1",
        explanation=explanation_data,
        status="COMPLETED",
    )

    assert run.id is not None
    assert run.repository_id == repo.id
    assert run.user_id == user.id
    assert run.feature_type == "explain"
    assert run.status == "COMPLETED"
    assert run.target_path == "backend/app/services/auth.py"
    assert run.target_symbol == "verify_token"
    assert run.start_line == 25
    assert run.end_line == 48
    assert run.source_revision == "git-commit-hash-v1"
    assert run.findings_count == 0
    assert run.error_message is None
    assert run.completed_at is not None

    # Verify structured result payload
    payload = run.result_payload
    assert payload is not None
    assert payload["purpose"].startswith("Verifies JWT tokens")
    assert len(payload["logic_flow"]) == 4
    assert len(payload["key_symbols"]) == 2
    assert payload["key_symbols"][0]["name"] == "verify_token"
    assert payload["dependencies"][0] == "jwt.decode"
    assert payload["confidence"] == "high"

    # Fetch back by ID and verify eager-loaded attributes
    fetched = repo_layer.get_explanation_run(run.id, repo.id)
    assert fetched is not None
    assert fetched.id == run.id
    assert fetched.feature_type == "explain"
    assert fetched.result_payload["purpose"] == payload["purpose"]


# ---------------------------------------------------------------------------
# 2. Store Failure Status Separately from Successful Output
# ---------------------------------------------------------------------------


def test_store_failure_status_separately(db_session: Session) -> None:
    """Verify that failed explanation runs record FAILED status and error_message distinctly."""
    user, repo = _create_test_user_and_repo(db_session)
    repo_layer = AnalysisRunRepository(db_session)

    # 1. Record an explicit failure
    fail_run = repo_layer.record_explanation_failure(
        repository_id=repo.id,
        user_id=user.id,
        target_path="backend/app/services/broken.py",
        target_symbol="crash_func",
        start_line=1,
        end_line=20,
        source_revision="feat-branch-1",
        error_message="AI provider timeout: Gemini 1.5 Flash did not respond within 30s.",
    )

    assert fail_run.status == "FAILED"
    assert fail_run.error_message == "AI provider timeout: Gemini 1.5 Flash did not respond within 30s."
    assert fail_run.feature_type == "explain"
    assert fail_run.completed_at is not None
    assert fail_run.findings_count == 0
    # Must not contain a fabricated explanation payload
    assert fail_run.result_payload is None or "purpose" not in fail_run.result_payload

    # 2. Record a successful run in the same repo
    ok_run = repo_layer.save_explanation_run(
        repository_id=repo.id,
        user_id=user.id,
        target_path="backend/app/services/ok.py",
        explanation=_sample_explanation_dict(),
        status="COMPLETED",
    )

    # 3. Query filtered by COMPLETED -> returns only ok_run
    completed_runs, comp_total = repo_layer.list_explanation_runs(repo.id, status="COMPLETED")
    assert comp_total == 1
    assert completed_runs[0].id == ok_run.id

    # 4. Query filtered by FAILED -> returns only fail_run
    failed_runs, fail_total = repo_layer.list_explanation_runs(repo.id, status="FAILED")
    assert fail_total == 1
    assert failed_runs[0].id == fail_run.id
    assert failed_runs[0].error_message.startswith("AI provider timeout")


# ---------------------------------------------------------------------------
# 3. Multi-Tenant Repository Isolation
# ---------------------------------------------------------------------------


def test_explanation_history_repository_isolation(db_session: Session) -> None:
    """Verify that Repo A's explanation history is strictly isolated from Repo B."""
    user_a, repo_a = _create_test_user_and_repo(db_session, "user-alpha", "repo-alpha")
    user_b, repo_b = _create_test_user_and_repo(db_session, "user-beta", "repo-beta")
    repo_layer = AnalysisRunRepository(db_session)

    run_a = repo_layer.save_explanation_run(
        repository_id=repo_a.id,
        user_id=user_a.id,
        target_path="src/alpha_secrets.py",
        explanation={"purpose": "Internal alpha encryption routine"},
    )
    run_b = repo_layer.save_explanation_run(
        repository_id=repo_b.id,
        user_id=user_b.id,
        target_path="src/beta_payroll.py",
        explanation={"purpose": "Internal beta payroll calculator"},
    )

    # Repo A listing should only show run_a
    items_a, total_a = repo_layer.list_explanation_runs(repo_a.id)
    assert total_a == 1
    assert items_a[0].id == run_a.id
    assert items_a[0].target_path == "src/alpha_secrets.py"

    # Repo B listing should only show run_b
    items_b, total_b = repo_layer.list_explanation_runs(repo_b.id)
    assert total_b == 1
    assert items_b[0].id == run_b.id
    assert items_b[0].target_path == "src/beta_payroll.py"

    # Cross-repository single-run lookup returns None
    assert repo_layer.get_explanation_run(run_a.id, repository_id=repo_b.id) is None
    assert repo_layer.get_explanation_run(run_b.id, repository_id=repo_a.id) is None

    # Cross-repository reopen returns None
    assert repo_layer.reopen_explanation(run_a.id, repository_id=repo_b.id) is None


# ---------------------------------------------------------------------------
# 4. Multi-Criteria Filtering & Pagination
# ---------------------------------------------------------------------------


def test_explanation_history_filtering_and_pagination(db_session: Session) -> None:
    """Verify filtering by target_path, target_symbol, source_revision, status, and pagination."""
    user, repo = _create_test_user_and_repo(db_session)
    repo_layer = AnalysisRunRepository(db_session)

    # Seed 5 distinct explanation runs
    r1 = repo_layer.save_explanation_run(
        repository_id=repo.id,
        target_path="src/auth.py",
        target_symbol="login",
        source_revision="rev-1",
        explanation={"purpose": "Login v1"},
    )
    r2 = repo_layer.save_explanation_run(
        repository_id=repo.id,
        target_path="src/auth.py",
        target_symbol="login",
        source_revision="rev-2",
        explanation={"purpose": "Login v2"},
    )
    r3 = repo_layer.save_explanation_run(
        repository_id=repo.id,
        target_path="src/auth.py",
        target_symbol="logout",
        source_revision="rev-2",
        explanation={"purpose": "Logout v2"},
    )
    r4 = repo_layer.record_explanation_failure(
        repository_id=repo.id,
        target_path="src/db.py",
        target_symbol="connect",
        source_revision="rev-2",
        error_message="DB connection error",
    )
    r5 = repo_layer.save_explanation_run(
        repository_id=repo.id,
        target_path="src/auth.py",
        target_symbol="login",
        source_revision="rev-3",
        explanation={"purpose": "Login v3"},
    )

    # Filter by target_path="src/auth.py" -> 4 runs
    auth_runs, auth_count = repo_layer.list_explanation_runs(repo.id, target_path="src/auth.py")
    assert auth_count == 4

    # Filter by target_path="src/auth.py" and target_symbol="login" -> 3 runs
    login_runs, login_count = repo_layer.list_explanation_runs(
        repo.id, target_path="src/auth.py", target_symbol="login"
    )
    assert login_count == 3

    # Filter by source_revision="rev-2" -> 3 runs (r2, r3, r4)
    rev2_runs, rev2_count = repo_layer.list_explanation_runs(repo.id, source_revision="rev-2")
    assert rev2_count == 3

    # Filter by source_revision="rev-2" AND status="COMPLETED" -> 2 runs (r2, r3)
    rev2_comp, rev2_comp_count = repo_layer.list_explanation_runs(
        repo.id, source_revision="rev-2", status="COMPLETED"
    )
    assert rev2_comp_count == 2

    # Test pagination: page 1 (limit 2), page 2 (limit 2), page 3 (limit 2)
    p1, total = repo_layer.list_explanation_runs(repo.id, offset=0, limit=2)
    assert total == 5
    assert len(p1) == 2
    assert p1[0].id == r5.id  # Newest first

    p2, total = repo_layer.list_explanation_runs(repo.id, offset=2, limit=2)
    assert len(p2) == 2
    assert p2[0].id == r3.id

    p3, total = repo_layer.list_explanation_runs(repo.id, offset=4, limit=2)
    assert len(p3) == 1
    assert p3[0].id == r1.id


# ---------------------------------------------------------------------------
# 5. Reopening Explanation from History (Scenario A Step 7)
# ---------------------------------------------------------------------------


def test_reopen_explanation_from_history(db_session: Session) -> None:
    """Verify Scenario A Step 7: Reopening a previous explanation run from persistent history."""
    user, repo = _create_test_user_and_repo(db_session)
    repo_layer = AnalysisRunRepository(db_session)

    original_explanation = _sample_explanation_dict()
    target_obj = AnalysisTarget(
        type="symbol",
        path="backend/app/services/auth.py",
        symbol="verify_token",
        start_line=25,
        end_line=48,
        revision="commit-sha-999",
    )

    saved_run = repo_layer.save_explanation_run(
        repository_id=repo.id,
        user_id=user.id,
        target=target_obj,
        explanation=original_explanation,
        status="COMPLETED",
    )

    # Reopen via reopen_explanation
    reopened = repo_layer.reopen_explanation(saved_run.id, repository_id=repo.id)
    assert reopened is not None
    assert reopened["run_id"] == str(saved_run.id)
    assert reopened["repository_id"] == str(repo.id)
    assert reopened["status"] == "COMPLETED"
    assert reopened["revision"] == "commit-sha-999"

    # Verify target coordinates match exactly
    assert reopened["target"]["path"] == "backend/app/services/auth.py"
    assert reopened["target"]["symbol"] == "verify_token"
    assert reopened["target"]["start_line"] == 25
    assert reopened["target"]["end_line"] == 48
    assert reopened["target"]["type"] == "symbol"

    # Verify structured explanation content
    assert reopened["explanation"]["purpose"] == original_explanation["purpose"]
    assert reopened["explanation"]["logic_flow"] == original_explanation["logic_flow"]
    assert reopened["explanation"]["confidence"] == "high"
    assert reopened["error_message"] is None

    # Test reopening failed run
    failed_run = repo_layer.record_explanation_failure(
        repository_id=repo.id,
        target_path="backend/app/services/auth.py",
        error_message="Validation error: invalid response schema",
    )
    reopened_failed = repo_layer.reopen_explanation(failed_run.id, repository_id=repo.id)
    assert reopened_failed is not None
    assert reopened_failed["status"] == "FAILED"
    assert reopened_failed["error_message"] == "Validation error: invalid response schema"


# ---------------------------------------------------------------------------
# 6. Traceability Across Code Revisions
# ---------------------------------------------------------------------------


def test_explanation_traceability_across_revisions(db_session: Session) -> None:
    """Verify that multiple explanations for the same code across revisions are tracked."""
    user, repo = _create_test_user_and_repo(db_session)
    repo_layer = AnalysisRunRepository(db_session)

    # Explanation 1: on branch v1.0
    r_v1 = repo_layer.save_explanation_run(
        repository_id=repo.id,
        target_path="src/calculator.py",
        target_symbol="calculate_tax",
        source_revision="v1.0.0",
        explanation={"purpose": "Calculates standard VAT at 15%"},
    )

    # Explanation 2: on branch v2.0
    r_v2 = repo_layer.save_explanation_run(
        repository_id=repo.id,
        target_path="src/calculator.py",
        target_symbol="calculate_tax",
        source_revision="v2.0.0",
        explanation={"purpose": "Calculates tiered VAT between 10% and 25%"},
    )

    # Query latest explanation
    latest = repo_layer.get_latest_explanation(
        repository_id=repo.id,
        target_path="src/calculator.py",
        target_symbol="calculate_tax",
    )
    assert latest is not None
    assert latest.id == r_v2.id
    assert latest.source_revision == "v2.0.0"
    assert "tiered VAT" in latest.result_payload["purpose"]

    # Query specific revision v1.0.0
    rev1 = repo_layer.get_latest_explanation(
        repository_id=repo.id,
        target_path="src/calculator.py",
        target_symbol="calculate_tax",
        source_revision="v1.0.0",
    )
    assert rev1 is not None
    assert rev1.id == r_v1.id
    assert "15%" in rev1.result_payload["purpose"]


# ---------------------------------------------------------------------------
# 7. ExplanationHistoryService Session Management & Protocols
# ---------------------------------------------------------------------------


def test_explanation_history_service_methods(db_session: Session) -> None:
    """Verify ExplanationHistoryService methods and session factory lifecycle."""
    user, repo = _create_test_user_and_repo(db_session)
    service = ExplanationHistoryService(session=db_session)

    # 1. save_explanation
    run = service.save_explanation(
        repository_id=repo.id,
        user_id=user.id,
        target_path="src/user_service.py",
        target_symbol="get_profile",
        source_revision="master",
        explanation=_sample_explanation_dict(),
    )
    assert run.id is not None
    assert run.status == "COMPLETED"

    # 2. record_failure
    fail = service.record_failure(
        repository_id=repo.id,
        target_path="src/broken.py",
        error_message="Network timeout calling Groq API",
    )
    assert fail.status == "FAILED"

    # 3. list_history
    runs, count = service.list_history(repo.id)
    assert count == 2

    # 4. get_explanation
    fetched = service.get_explanation(run.id, repo.id)
    assert fetched is not None
    assert fetched.id == run.id

    # 5. reopen_explanation
    reopened = service.reopen_explanation(run.id, repo.id)
    assert reopened is not None
    assert reopened["status"] == "COMPLETED"
    assert reopened["target"]["path"] == "src/user_service.py"

    # 6. get_latest
    latest = service.get_latest(repo.id, "src/user_service.py", target_symbol="get_profile")
    assert latest is not None
    assert latest.id == run.id

    # 7. record_run protocol
    rec = {
        "id": str(uuid.uuid4()),
        "repository_id": str(repo.id),
        "user_id": str(user.id),
        "feature_type": "explain",
        "status": "COMPLETED",
        "target_path": "src/protocol.py",
        "source_revision": "head",
        "result_payload": {"purpose": "Protocol verification"},
    }
    rec_run = service.record_run(rec)
    assert rec_run.id == uuid.UUID(rec["id"])


# ---------------------------------------------------------------------------
# 8. End-to-End API Integration with DB Persistence & Reopening
# ---------------------------------------------------------------------------


def _seed_explainable_file(db: Session, repo: Repository) -> tuple[RepositoryFile, CodeSymbol]:
    file_row = RepositoryFile(
        id=uuid.uuid4(),
        repository_id=repo.id,
        path="src/auth_service.py",
        language="Python",
        size_bytes=1000,
        line_count=40,
        content_hash="hash123",
    )
    db.add(file_row)
    db.flush()

    sym = CodeSymbol(
        id=uuid.uuid4(),
        file_id=file_row.id,
        repository_id=repo.id,
        name="verify_jwt_token",
        kind="function",
        start_line=10,
        end_line=30,
        signature="def verify_jwt_token(token: str) -> dict:",
    )
    db.add(sym)

    chunk = CodeChunk(
        id=uuid.uuid4(),
        repository_id=repo.id,
        file_id=file_row.id,
        symbol_id=sym.id,
        content="def verify_jwt_token(token: str) -> dict:\n    return decode(token)\n",
        token_count=15,
        embedding=[0.0] * 768,
        start_line=10,
        end_line=30,
        content_hash="c_hash",
        chunk_metadata={"file_path": "src/auth_service.py"},
    )
    db.add(chunk)
    db.commit()
    return file_row, sym


def test_e2e_explain_api_persistence_and_reopen(
    client, db_session: Session, test_user: User, auth_headers: dict[str, str]
) -> None:
    """Verify that calling POST /explain persists the run to SQLite/Postgres DB and allows reopening."""
    # Seed repository belonging to test_user
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
        name="e2e-explain-repo",
        default_branch="main",
        sync_status=SyncStatus.SYNCED,
    )
    db_session.add(repo)
    db_session.commit()
    db_session.refresh(repo)

    _seed_explainable_file(db_session, repo)

    fake_explanation = _sample_explanation_dict()

    async def _fake_explain(repository_id, payload, **kwargs):
        return fake_explanation

    app.state.explanation_service = SimpleNamespace(explain=_fake_explain)

    try:
        # 1. Trigger code explanation via API
        res = client.post(
            f"/api/v1/repositories/{repo.id}/explain",
            headers=auth_headers,
            json={
                "target": {
                    "type": "symbol",
                    "path": "src/auth_service.py",
                    "symbol": "verify_jwt_token",
                }
            },
        )
        assert res.status_code == 200, res.text
        data = res.json()
        run_id = data["run_id"]
        assert data["status"] == "COMPLETED"

        # 2. Verify directly from Database through AnalysisRunRepository
        repo_layer = AnalysisRunRepository(db_session)
        db_run = repo_layer.get_explanation_run(run_id, repo.id)
        assert db_run is not None
        assert db_run.status == "COMPLETED"
        assert db_run.target_path == "src/auth_service.py"
        assert db_run.target_symbol == "verify_jwt_token"
        assert db_run.start_line == 10
        assert db_run.end_line == 30

        # 3. Reopen via GET /repositories/{id}/analysis-runs
        list_res = client.get(
            f"/api/v1/repositories/{repo.id}/analysis-runs?feature_type=explain",
            headers=auth_headers,
        )
        assert list_res.status_code == 200
        items = list_res.json()["items"]
        assert any(item["id"] == run_id for item in items)

        # 4. Reopen via GET /analysis-runs/{run_id}
        detail_res = client.get(f"/api/v1/analysis-runs/{run_id}", headers=auth_headers)
        assert detail_res.status_code == 200
        detail = detail_res.json()
        assert detail["id"] == run_id
        assert detail["status"] == "COMPLETED"
        assert detail["result_payload"]["explanation"]["purpose"].startswith("Verifies JWT")

    finally:
        if hasattr(app.state, "explanation_service"):
            del app.state.explanation_service


# ---------------------------------------------------------------------------
# 9. Synthetic User Foreign Key Resilience
# ---------------------------------------------------------------------------


def test_save_explanation_with_synthetic_user(db_session: Session) -> None:
    """Verify that synthetic/unpersisted user IDs do not cause foreign key IntegrityErrors."""
    user, repo = _create_test_user_and_repo(db_session)
    repo_layer = AnalysisRunRepository(db_session)

    synthetic_user_id = uuid.uuid4()  # Not in users table
    run = repo_layer.save_explanation_run(
        repository_id=repo.id,
        user_id=synthetic_user_id,
        target_path="src/test.py",
        explanation={"purpose": "Synthetic user test"},
    )

    assert run.id is not None
    # user_id safely converted to None to avoid FK constraint crash
    assert run.user_id is None
    assert run.repository_id == repo.id


# ---------------------------------------------------------------------------
# 10. Cascade Deletion Cleans Up Explanation History
# ---------------------------------------------------------------------------


def test_explanation_history_cascade_delete(db_session: Session) -> None:
    """Verify that deleting a repository cascades and cleans up all associated explanation runs."""
    from app.repositories.repository_repository import RepositoryRepository

    user, repo = _create_test_user_and_repo(db_session)
    repo_layer = AnalysisRunRepository(db_session)
    repo_repo = RepositoryRepository(db_session)

    run = repo_layer.save_explanation_run(
        repository_id=repo.id,
        target_path="src/to_delete.py",
        explanation={"purpose": "Cascade delete test"},
    )

    # Verify run exists
    assert repo_layer.get_by_id(run.id) is not None

    # Delete repository via RepositoryRepository (or delete_by_repository)
    repo_repo.delete(repo.id)

    # Verify run is cascade deleted
    assert repo_layer.get_by_id(run.id) is None

