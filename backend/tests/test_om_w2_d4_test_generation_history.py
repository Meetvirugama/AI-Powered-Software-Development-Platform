"""Comprehensive test suite for Week 2 Day 4 (Test Generation History & Persistence).

Owner: Om — Database & Persistence.

Verifies all Day 4 deliverables and acceptance criteria from `Docs/week2.md` §8 & §12 (Scenario C):
1. Persist generated-test runs and relevant metadata:
   - Saving test generation runs (`feature_type="generate_tests"`) with structured metadata.
   - Concrete target code coordinates (file_path, symbol, 1-indexed inclusive line range).
   - Source revision metadata (git commit SHA or branch name).
   - Structured result payload: detected_framework, proposed_test_path, covered_scenarios,
     assumptions_and_warnings, syntax_valid, validation_errors, and sources.
2. Large test output storage and retention:
   - Dedicated storage for large generated test files (`test_output` Text column / Postgres TOAST).
   - Retrieval of multi-thousand line generated test files without truncation or loss of fidelity.
3. Associate outputs with target and source revision:
   - Ensuring test outputs are strictly mapped to target path, symbol, and commit revision.
   - Tracking test runs across different source revisions.
4. Persist failed test generation runs:
   - Recording explicit failures (`status="FAILED"`, `error_message`), strictly preventing
     generation failures from masquerading as valid test suites.
5. Multi-framework support:
   - Seamless persistence across Python (`pytest`, `unittest`) and TypeScript/JavaScript (`jest`).
   - Filtering test runs by framework.
6. History retrieval, filtering, and pagination:
   - Multi-criteria filtering by status, target_path, target_symbol, framework, and source_revision.
   - Ordering newest first (`created_at.desc()`).
   - Accurate total counts and pagination.
7. Reopen test generation run from persistent history (Scenario C Step 7):
   - Reconstituting past test generation runs with full fidelity matching `TestGenerationResponse`.
8. Duplicate detection and latest run lookup:
   - Finding duplicate completed runs to prevent redundant AI runs.
   - Fetching latest completed run for a target.
9. Multi-tenant repository isolation:
   - Cross-repository access is strictly blocked; Repo A's test runs are never visible to Repo B.
10. `TestGenerationHistoryService` business logic and session management.
11. End-to-end API integration:
    - `POST /api/v1/repositories/{id}/generate-tests` -> persistence ->
    - Retrieval via `GET /api/v1/analysis-runs/{run_id}` ->
    - Listing via `GET /api/v1/repositories/{id}/analysis-runs?feature_type=generate_tests` (and alias `feature_type=tests`).
12. Failure recording on service errors.
13. Foreign key safety with synthetic/unpersisted user IDs.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.main import app
from app.models.analysis_run import AnalysisFeature, AnalysisRun, AnalysisRunStatus
from app.models.github_installation import GitHubInstallation
from app.models.repository import Repository, SyncStatus
from app.models.repository_file import RepositoryFile
from app.models.user import User
from app.repositories.analysis_run_repository import AnalysisRunRepository
from app.services.test_generation_history_service import TestGenerationHistoryService


# ---------------------------------------------------------------------------
# Test Helpers & Seeders
# ---------------------------------------------------------------------------


def _create_test_user_and_repo(
    db: Session,
    login: str = "om-test-gen-user",
    repo_name: str = "test-generation-suite-repo",
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


def _sample_test_result() -> dict:
    """Sample structured TestGenerationResult dictionary."""
    return {
        "detected_framework": "pytest",
        "proposed_test_path": "tests/test_calculator.py",
        "test_content": (
            "import pytest\n"
            "from src.calculator import add, divide\n\n"
            "def test_add_positive():\n"
            "    assert add(2, 3) == 5\n\n"
            "def test_divide_by_zero():\n"
            "    with pytest.raises(ValueError):\n"
            "        divide(10, 0)\n"
        ),
        "covered_scenarios": [
            {"name": "test_add_positive", "category": "normal", "description": "Verify normal addition"},
            {"name": "test_divide_by_zero", "category": "edge_case", "description": "Verify division by zero raises ValueError"},
            {"name": "test_negative_inputs", "category": "normal", "description": "Verify addition with negative integers"},
        ],
        "assumptions_and_warnings": [
            "Assumes calculator.py is in PYTHONPATH",
        ],
        "syntax_valid": True,
        "validation_errors": [],
        "sources": [
            {
                "file_path": "src/calculator.py",
                "start_line": 1,
                "end_line": 25,
                "revision": "git_commit_sha_1",
                "symbol_name": "add",
            }
        ],
    }


# ---------------------------------------------------------------------------
# 1. Test Generation Persistence & Revision Metadata Tests
# ---------------------------------------------------------------------------


def test_save_and_retrieve_test_generation_run(db_session: Session) -> None:
    """Verify persisting a completed test generation run with structured metadata and revision."""
    user, repo = _create_test_user_and_repo(db_session)
    repo_layer = AnalysisRunRepository(db_session)
    result_data = _sample_test_result()

    run = repo_layer.save_test_generation_run(
        repository_id=repo.id,
        user_id=user.id,
        target_path="src/calculator.py",
        target_symbol="add",
        start_line=1,
        end_line=25,
        source_revision="git_commit_sha_1",
        test_result=result_data,
        status="COMPLETED",
    )

    assert run.id is not None
    assert run.repository_id == repo.id
    assert run.feature_type == "generate_tests"
    assert run.status == "COMPLETED"
    assert run.source_revision == "git_commit_sha_1"
    assert run.target_path == "src/calculator.py"
    assert run.target_symbol == "add"
    assert run.start_line == 1
    assert run.end_line == 25
    assert run.error_message is None
    assert run.test_output == result_data["test_content"]
    assert run.result_payload is not None
    assert run.result_payload["detected_framework"] == "pytest"
    assert run.result_payload["proposed_test_path"] == "tests/test_calculator.py"
    assert len(run.result_payload["covered_scenarios"]) == 3

    # Fetch from repository layer
    fetched = repo_layer.get_test_generation_run(run.id, repository_id=repo.id)
    assert fetched is not None
    assert fetched.id == run.id
    assert fetched.test_output == result_data["test_content"]
    assert fetched.result_payload["syntax_valid"] is True


def test_large_test_output_storage_and_retrieval(db_session: Session) -> None:
    """Verify storing and retrieving large generated test files (Postgres TOAST / Text storage)."""
    user, repo = _create_test_user_and_repo(db_session)
    repo_layer = AnalysisRunRepository(db_session)

    # Generate a large multi-line test suite (> 50 KB / thousands of lines)
    test_lines = ["import pytest\n", "# Large generated test suite\n"]
    for i in range(1000):
        test_lines.append(
            f"def test_scenario_{i}():\n"
            f"    # Generated test scenario {i}\n"
            f"    expected = {i} * 2\n"
            f"    assert expected == {i * 2}\n\n"
        )
    large_test_content = "".join(test_lines)

    run = repo_layer.save_test_generation_run(
        repository_id=repo.id,
        user_id=user.id,
        target_path="src/data_processor.py",
        source_revision="sha_large_test_100",
        test_output=large_test_content,
        detected_framework="pytest",
        proposed_test_path="tests/test_data_processor.py",
        status="COMPLETED",
    )

    assert run.test_output == large_test_content
    assert len(run.test_output) > 30000

    # Retrieve and verify exact string fidelity
    fetched = repo_layer.get_test_generation_run(run.id, repository_id=repo.id)
    assert fetched is not None
    assert fetched.test_output == large_test_content
    assert len(fetched.test_output) == len(large_test_content)

    # Reopen and check fidelity in reconstituted output
    reopened = repo_layer.reopen_test_generation(run.id, repository_id=repo.id)
    assert reopened is not None
    assert reopened["test_output"] == large_test_content
    assert reopened["result"]["test_content"] == large_test_content


def test_associate_outputs_with_target_and_source_revision(db_session: Session) -> None:
    """Verify that test generation outputs are strictly associated with target and revision."""
    user, repo = _create_test_user_and_repo(db_session)
    repo_layer = AnalysisRunRepository(db_session)

    # Run on revision v1
    run_v1 = repo_layer.save_test_generation_run(
        repository_id=repo.id,
        user_id=user.id,
        target_path="src/auth.py",
        target_symbol="login",
        source_revision="commit_rev_v1",
        test_output="def test_v1(): assert True",
        detected_framework="pytest",
        proposed_test_path="tests/test_auth_v1.py",
    )

    # Run on revision v2
    run_v2 = repo_layer.save_test_generation_run(
        repository_id=repo.id,
        user_id=user.id,
        target_path="src/auth.py",
        target_symbol="login",
        source_revision="commit_rev_v2",
        test_output="def test_v2(): assert True",
        detected_framework="pytest",
        proposed_test_path="tests/test_auth_v2.py",
    )

    runs_v1, count_v1 = repo_layer.list_test_generation_runs(
        repo.id,
        target_path="src/auth.py",
        source_revision="commit_rev_v1",
    )
    assert count_v1 == 1
    assert runs_v1[0].id == run_v1.id
    assert runs_v1[0].test_output == "def test_v1(): assert True"

    runs_v2, count_v2 = repo_layer.list_test_generation_runs(
        repo.id,
        target_path="src/auth.py",
        source_revision="commit_rev_v2",
    )
    assert count_v2 == 1
    assert runs_v2[0].id == run_v2.id
    assert runs_v2[0].test_output == "def test_v2(): assert True"


def test_record_test_generation_failure(db_session: Session) -> None:
    """Verify that failed test generation runs are stored with status FAILED and error message."""
    user, repo = _create_test_user_and_repo(db_session)
    repo_layer = AnalysisRunRepository(db_session)

    run = repo_layer.record_test_generation_failure(
        repository_id=repo.id,
        user_id=user.id,
        target_path="src/complex_service.py",
        target_symbol="execute_batch",
        source_revision="sha_fail_1",
        error_message="Model context window exceeded during test generation.",
    )

    assert run.id is not None
    assert run.status == "FAILED"
    assert run.error_message == "Model context window exceeded during test generation."
    assert run.test_output is None
    assert run.result_payload == {
        "error": "Model context window exceeded during test generation.",
        "status": "FAILED",
    }

    # Verify query for failed runs
    runs, count = repo_layer.list_test_generation_runs(repo.id, status="FAILED")
    assert count >= 1
    assert any(r.id == run.id for r in runs)


def test_multi_framework_support(db_session: Session) -> None:
    """Verify persistence and filtering across pytest, unittest, and jest."""
    user, repo = _create_test_user_and_repo(db_session)
    repo_layer = AnalysisRunRepository(db_session)

    # 1. pytest
    run_pytest = repo_layer.save_test_generation_run(
        repository_id=repo.id,
        user_id=user.id,
        target_path="src/math.py",
        detected_framework="pytest",
        proposed_test_path="tests/test_math.py",
        test_output="def test_add(): assert 1 + 1 == 2",
    )

    # 2. unittest
    run_unittest = repo_layer.save_test_generation_run(
        repository_id=repo.id,
        user_id=user.id,
        target_path="src/math.py",
        detected_framework="unittest",
        proposed_test_path="tests/test_math_unittest.py",
        test_output="import unittest\nclass TestMath(unittest.TestCase): ...",
    )

    # 3. jest
    run_jest = repo_layer.save_test_generation_run(
        repository_id=repo.id,
        user_id=user.id,
        target_path="src/math.ts",
        detected_framework="jest",
        proposed_test_path="__tests__/math.test.ts",
        test_output="describe('math', () => { test('add', () => { expect(1+1).toBe(2); }); });",
    )

    # Verify filtering by framework
    runs_pytest, count_pytest = repo_layer.list_test_generation_runs(repo.id, framework="pytest")
    assert count_pytest >= 1
    assert any(r.id == run_pytest.id for r in runs_pytest)

    runs_unittest, count_unittest = repo_layer.list_test_generation_runs(repo.id, framework="unittest")
    assert count_unittest >= 1
    assert any(r.id == run_unittest.id for r in runs_unittest)

    runs_jest, count_jest = repo_layer.list_test_generation_runs(repo.id, framework="jest")
    assert count_jest >= 1
    assert any(r.id == run_jest.id for r in runs_jest)


def test_list_test_generation_runs_filtering_and_pagination(db_session: Session) -> None:
    """Verify pagination and multi-criteria filtering on test generation history."""
    user, repo = _create_test_user_and_repo(db_session)
    repo_layer = AnalysisRunRepository(db_session)

    created_ids = []
    for i in range(5):
        run = repo_layer.save_test_generation_run(
            repository_id=repo.id,
            user_id=user.id,
            target_path=f"src/module_{i}.py",
            source_revision=f"sha_{i}",
            detected_framework="pytest",
            proposed_test_path=f"tests/test_module_{i}.py",
            test_output=f"def test_{i}(): pass",
            status="COMPLETED" if i % 2 == 0 else "FAILED",
            error_message="Error" if i % 2 != 0 else None,
        )
        created_ids.append(run.id)

    # Page 1 (limit 2)
    p1, total = repo_layer.list_test_generation_runs(repo.id, offset=0, limit=2)
    assert total == 5
    assert len(p1) == 2

    # Page 2 (limit 2)
    p2, total2 = repo_layer.list_test_generation_runs(repo.id, offset=2, limit=2)
    assert total2 == 5
    assert len(p2) == 2

    # Page 3 (limit 2)
    p3, total3 = repo_layer.list_test_generation_runs(repo.id, offset=4, limit=2)
    assert total3 == 5
    assert len(p3) == 1

    # Verify no overlap across pages
    all_paged_ids = [r.id for r in p1] + [r.id for r in p2] + [r.id for r in p3]
    assert len(all_paged_ids) == 5
    assert len(set(all_paged_ids)) == 5

    # Filter by status COMPLETED
    completed, count_c = repo_layer.list_test_generation_runs(repo.id, status="COMPLETED")
    assert count_c == 3
    assert all(r.status == "COMPLETED" for r in completed)


def test_reopen_test_generation_scenario_c(db_session: Session) -> None:
    """Verify Scenario C Step 7: Reopening a past test generation run from persistent history."""
    user, repo = _create_test_user_and_repo(db_session)
    repo_layer = AnalysisRunRepository(db_session)
    result_data = _sample_test_result()

    run = repo_layer.save_test_generation_run(
        repository_id=repo.id,
        user_id=user.id,
        target_path="src/calculator.py",
        target_symbol="add",
        start_line=1,
        end_line=25,
        source_revision="head_commit_c",
        test_result=result_data,
        status="COMPLETED",
    )

    reopened = repo_layer.reopen_test_generation(run.id, repository_id=repo.id)
    assert reopened is not None
    assert reopened["run_id"] == str(run.id)
    assert reopened["repository_id"] == str(repo.id)
    assert reopened["status"] == "COMPLETED"
    assert reopened["revision"] == "head_commit_c"

    # Verify target coordinates
    target = reopened["target"]
    assert target["type"] == "symbol"
    assert target["path"] == "src/calculator.py"
    assert target["symbol"] == "add"
    assert target["start_line"] == 1
    assert target["end_line"] == 25
    assert target["revision"] == "head_commit_c"

    # Verify structured result
    res = reopened["result"]
    assert res["detected_framework"] == "pytest"
    assert res["proposed_test_path"] == "tests/test_calculator.py"
    assert res["test_content"] == result_data["test_content"]
    assert len(res["covered_scenarios"]) == 3
    assert res["syntax_valid"] is True
    assert len(res["sources"]) == 1

    # Verify dedicated test_output
    assert reopened["test_output"] == result_data["test_content"]


def test_get_latest_test_generation_and_duplicate_detection(db_session: Session) -> None:
    """Verify get_latest_test_generation and duplicate detection to avoid redundant runs."""
    user, repo = _create_test_user_and_repo(db_session)
    repo_layer = AnalysisRunRepository(db_session)

    run = repo_layer.save_test_generation_run(
        repository_id=repo.id,
        user_id=user.id,
        target_path="src/parser.py",
        target_symbol="tokenize",
        source_revision="rev_dup_1",
        detected_framework="pytest",
        proposed_test_path="tests/test_parser.py",
        test_output="def test_tokens(): pass",
    )

    latest = repo_layer.get_latest_test_generation(
        repo.id,
        target_path="src/parser.py",
        target_symbol="tokenize",
        source_revision="rev_dup_1",
    )
    assert latest is not None
    assert latest.id == run.id

    duplicate = repo_layer.find_duplicate_test_generation(
        repo.id,
        target_path="src/parser.py",
        target_symbol="tokenize",
        source_revision="rev_dup_1",
        framework="pytest",
    )
    assert duplicate is not None
    assert duplicate.id == run.id

    # Non-matching revision returns None
    assert (
        repo_layer.find_duplicate_test_generation(
            repo.id,
            target_path="src/parser.py",
            target_symbol="tokenize",
            source_revision="rev_different",
        )
        is None
    )


def test_delete_test_generation_run(db_session: Session) -> None:
    """Verify deleting a test generation run with repository boundary enforcement."""
    user, repo = _create_test_user_and_repo(db_session)
    repo_layer = AnalysisRunRepository(db_session)

    run = repo_layer.save_test_generation_run(
        repository_id=repo.id,
        user_id=user.id,
        target_path="src/temp.py",
        test_output="def test_temp(): pass",
    )

    # Deleting with non-matching repository fails
    other_repo_id = uuid.uuid4()
    assert repo_layer.delete_test_generation_run(run.id, repository_id=other_repo_id) is False

    # Deleting with correct repository succeeds
    assert repo_layer.delete_test_generation_run(run.id, repository_id=repo.id) is True
    assert repo_layer.get_test_generation_run(run.id, repository_id=repo.id) is None


def test_multi_tenant_repository_isolation(db_session: Session) -> None:
    """Verify that Repo A's test generation data is completely inaccessible to Repo B."""
    user_a, repo_a = _create_test_user_and_repo(db_session, login="user-a", repo_name="repo-a")
    user_b, repo_b = _create_test_user_and_repo(db_session, login="user-b", repo_name="repo-b")
    repo_layer = AnalysisRunRepository(db_session)

    run_a = repo_layer.save_test_generation_run(
        repository_id=repo_a.id,
        user_id=user_a.id,
        target_path="src/secret_logic.py",
        test_output="def test_secret(): pass",
    )

    # Repo B cannot fetch Repo A's run
    assert repo_layer.get_test_generation_run(run_a.id, repository_id=repo_b.id) is None
    assert repo_layer.reopen_test_generation(run_a.id, repository_id=repo_b.id) is None

    # Listing Repo B runs returns empty
    runs_b, total_b = repo_layer.list_test_generation_runs(repo_b.id)
    assert total_b == 0
    assert len(runs_b) == 0


def test_test_generation_history_service(db_session: Session) -> None:
    """Verify TestGenerationHistoryService business logic and session management."""
    user, repo = _create_test_user_and_repo(db_session)
    service = TestGenerationHistoryService(session=db_session)
    result_data = _sample_test_result()

    # 1. Save completed run
    run = service.save_test_generation(
        repository_id=repo.id,
        user_id=user.id,
        target_path="src/service_test.py",
        test_result=result_data,
        source_revision="sha_service_1",
    )
    assert run.id is not None
    assert run.status == "COMPLETED"

    # 2. Record failure
    fail_run = service.record_failure(
        repository_id=repo.id,
        target_path="src/failing.py",
        error_message="Syntax parse error",
    )
    assert fail_run.status == "FAILED"
    assert fail_run.error_message == "Syntax parse error"

    # 3. List history
    items, total = service.list_history(repo.id)
    assert total >= 2

    # 4. Get by ID
    fetched = service.get_run_by_id(run.id, repository_id=repo.id)
    assert fetched is not None
    assert fetched.id == run.id

    # 5. Reopen
    reopened = service.reopen_run(run.id, repository_id=repo.id)
    assert reopened is not None
    assert reopened["result"]["detected_framework"] == "pytest"

    # 6. Delete
    deleted = service.delete_run(run.id, repository_id=repo.id)
    assert deleted is True
    assert service.get_run_by_id(run.id, repository_id=repo.id) is None


# ---------------------------------------------------------------------------
# 2. End-to-End API Integration Tests
# ---------------------------------------------------------------------------


def test_api_generate_tests_persistence_and_retrieval(
    client: TestClient,
    db_session: Session,
    test_user: User,
    auth_headers: dict[str, str],
) -> None:
    """Verify API POST /generate-tests persists to DB and is retrievable via GET /analysis-runs."""
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
        name="test-generation-api-repo",
        default_branch="main",
        sync_status=SyncStatus.SYNCED,
    )
    db_session.add(repo)
    db_session.commit()
    db_session.refresh(repo)

    # Seed an indexed file in repository_files
    repo_file = RepositoryFile(
        id=uuid.uuid4(),
        repository_id=repo.id,
        path="src/tested_file.py",
        language="python",
        size_bytes=1024,
        line_count=40,
        content_hash="abc_hash_1",
    )
    db_session.add(repo_file)
    db_session.commit()

    sample_res = _sample_test_result()

    # Create mock test generation service
    class MockTestGenerationService:
        async def generate_tests(self, repository_id, payload, **kwargs):
            return {
                "run_id": str(uuid.uuid4()),
                "repository_id": str(repository_id),
                "status": "COMPLETED",
                "target": payload.target.model_dump(mode="json"),
                "revision": "test_head_rev",
                "result": sample_res,
            }

    app.state.test_generation_service = MockTestGenerationService()
    app.state.test_generation_history_service = TestGenerationHistoryService(session=db_session)

    try:
        payload = {
            "target": {
                "type": "file",
                "path": "src/tested_file.py",
                "revision": "test_head_rev",
            },
            "framework": "pytest",
            "options": {
                "persist_run": True,
            },
        }

        resp = client.post(
            f"/api/v1/repositories/{repo.id}/generate-tests",
            json=payload,
            headers=auth_headers,
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        run_id = data["run_id"]
        assert data["status"] == "COMPLETED"
        assert data["result"]["detected_framework"] == "pytest"
        assert data["result"]["proposed_test_path"] == "tests/test_calculator.py"

        # Verify run is persisted in the database
        repo_layer = AnalysisRunRepository(db_session)
        run_record = repo_layer.get_test_generation_run(run_id, repository_id=repo.id)
        assert run_record is not None
        assert run_record.status == "COMPLETED"
        assert run_record.test_output == sample_res["test_content"]

        # Verify reopening via GET /api/v1/analysis-runs/{run_id}
        detail_resp = client.get(
            f"/api/v1/analysis-runs/{run_id}",
            headers=auth_headers,
        )
        assert detail_resp.status_code == 200
        detail_data = detail_resp.json()
        assert detail_data["id"] == run_id
        assert detail_data["feature_type"] == "generate_tests"
        assert detail_data["test_output"] == sample_res["test_content"]
        assert detail_data["result_payload"]["result"]["detected_framework"] == "pytest"

        # Verify listing via GET /api/v1/repositories/{id}/analysis-runs?feature_type=generate_tests
        list_resp = client.get(
            f"/api/v1/repositories/{repo.id}/analysis-runs?feature_type=generate_tests",
            headers=auth_headers,
        )
        assert list_resp.status_code == 200
        list_data = list_resp.json()
        assert list_data["total"] >= 1
        assert any(item["id"] == run_id for item in list_data["items"])

        # Verify listing via GET with alias feature_type=tests resolves to generate_tests
        list_alias_resp = client.get(
            f"/api/v1/repositories/{repo.id}/analysis-runs?feature_type=tests",
            headers=auth_headers,
        )
        assert list_alias_resp.status_code == 200
        assert list_alias_resp.json()["total"] >= 1
        assert any(item["id"] == run_id for item in list_alias_resp.json()["items"])
    finally:
        if hasattr(app.state, "test_generation_service"):
            del app.state.test_generation_service


def test_api_generate_tests_failure_recording(
    client: TestClient,
    db_session: Session,
    test_user: User,
    auth_headers: dict[str, str],
) -> None:
    """Verify that service exceptions during generate-tests record a failed run in persistence."""
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
        name="test-generation-failure-repo",
        default_branch="main",
        sync_status=SyncStatus.SYNCED,
    )
    db_session.add(repo)
    db_session.commit()
    db_session.refresh(repo)

    # Seed an indexed file
    repo_file = RepositoryFile(
        id=uuid.uuid4(),
        repository_id=repo.id,
        path="src/failing_target.py",
        language="python",
        size_bytes=512,
        line_count=20,
        content_hash="fail_hash_1",
    )
    db_session.add(repo_file)
    db_session.commit()

    class FailingTestGenerationService:
        async def generate_tests(self, *args, **kwargs):
            from app.core.errors import APIError, ErrorCode
            raise APIError(500, ErrorCode.ANALYSIS_FAILED, "LLM timeout during test generation")

    app.state.test_generation_service = FailingTestGenerationService()
    app.state.test_generation_history_service = TestGenerationHistoryService(session=db_session)

    try:
        payload = {
            "target": {
                "type": "file",
                "path": "src/failing_target.py",
            },
            "options": {"persist_run": True},
        }

        resp = client.post(
            f"/api/v1/repositories/{repo.id}/generate-tests",
            json=payload,
            headers=auth_headers,
        )
        assert resp.status_code == 500

        # Verify that a FAILED run was recorded in the database
        repo_layer = AnalysisRunRepository(db_session)
        failed_runs, count = repo_layer.list_test_generation_runs(
            repo.id,
            target_path="src/failing_target.py",
            status="FAILED",
        )
        assert count >= 1
        assert failed_runs[0].status == "FAILED"
        assert "LLM timeout" in (failed_runs[0].error_message or "")
    finally:
        if hasattr(app.state, "test_generation_service"):
            del app.state.test_generation_service


def test_save_test_generation_with_synthetic_user(db_session: Session) -> None:
    """Verify that synthetic/unpersisted user IDs do not cause foreign key IntegrityErrors."""
    user, repo = _create_test_user_and_repo(db_session)
    repo_layer = AnalysisRunRepository(db_session)

    synthetic_user_id = uuid.uuid4()
    run = repo_layer.save_test_generation_run(
        repository_id=repo.id,
        user_id=synthetic_user_id,
        target_path="src/synth_test.py",
        test_output="def test_synth(): pass",
    )

    assert run.id is not None
    assert run.user_id is None
    assert run.repository_id == repo.id
    assert run.test_output == "def test_synth(): pass"
