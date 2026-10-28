"""Cross-feature analysis run history lifecycle and tenant isolation tests (Week 2 Section 12 Item 6)."""

import uuid
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.security import create_access_token
from app.main import app
from app.models.analysis_finding import AnalysisFinding
from app.models.analysis_run import AnalysisFeature, AnalysisRun, AnalysisRunStatus
from app.models.github_installation import GitHubInstallation
from app.models.repository import Repository, SyncStatus
from app.models.repository_file import RepositoryFile
from app.models.user import User


@pytest.fixture
def test_setup(db_session: Session):
    # Create User 1 and Repository 1
    u1 = User(id=uuid.uuid4(), github_id="gh_1", email="user1@example.com", login="user1", avatar_url="")
    db_session.add(u1)
    db_session.flush()

    inst1 = GitHubInstallation(
        id=uuid.uuid4(),
        user_id=u1.id,
        installation_id="inst_111",
        account_login=u1.login,
        permissions={},
    )
    db_session.add(inst1)
    db_session.flush()

    repo1 = Repository(
        id=uuid.uuid4(),
        user_id=u1.id,
        installation_id=inst1.id,
        github_repo_id="10001",
        owner=u1.login,
        name="repo-one",
        default_branch="main",
        sync_status=SyncStatus.SYNCED,
    )
    db_session.add(repo1)

    file1 = RepositoryFile(
        id=uuid.uuid4(),
        repository_id=repo1.id,
        path="src/main.py",
        size_bytes=500,
        line_count=50,
        content_hash="h1",
        language="python",
    )
    db_session.add(file1)

    # Create User 2 and Repository 2
    u2 = User(id=uuid.uuid4(), github_id="gh_2", email="user2@example.com", login="user2", avatar_url="")
    db_session.add(u2)
    db_session.flush()

    inst2 = GitHubInstallation(
        id=uuid.uuid4(),
        user_id=u2.id,
        installation_id="inst_222",
        account_login=u2.login,
        permissions={},
    )
    db_session.add(inst2)
    db_session.flush()

    repo2 = Repository(
        id=uuid.uuid4(),
        user_id=u2.id,
        installation_id=inst2.id,
        github_repo_id="10002",
        owner=u2.login,
        name="repo-two",
        default_branch="main",
        sync_status=SyncStatus.SYNCED,
    )
    db_session.add(repo2)
    db_session.commit()

    token1, _ = create_access_token(str(u1.id))
    token2, _ = create_access_token(str(u2.id))

    return {
        "u1": u1,
        "token1": token1,
        "repo1": repo1,
        "file1": file1,
        "u2": u2,
        "token2": token2,
        "repo2": repo2,
    }


def test_cross_feature_history_persistence_listing_and_isolation(
    client: TestClient,
    db_session: Session,
    test_setup: dict,
):
    token1 = test_setup["token1"]
    repo1 = test_setup["repo1"]
    u1 = test_setup["u1"]
    token2 = test_setup["token2"]
    repo2 = test_setup["repo2"]

    # 1. Seed historical runs across all 4 features for repo1
    features = [
        (AnalysisFeature.EXPLAIN, AnalysisRunStatus.COMPLETED, 0, None),
        (AnalysisFeature.DETECT_BUGS, AnalysisRunStatus.COMPLETED, 2, None),
        (AnalysisFeature.GENERATE_TESTS, AnalysisRunStatus.FAILED, 0, "Test generator model timeout"),
        (AnalysisFeature.REVIEW, AnalysisRunStatus.COMPLETED, 3, None),
    ]

    created_runs = []
    for feat, stat, f_count, err_msg in features:
        run = AnalysisRun(
            id=uuid.uuid4(),
            repository_id=repo1.id,
            user_id=u1.id,
            feature_type=feat,
            status=stat,
            target_path="src/main.py",
            source_revision="abc1234",
            findings_count=f_count,
            error_message=err_msg,
            result_payload={"summary": f"Result for {feat.value}"},
        )
        db_session.add(run)
        created_runs.append(run)

        # Seed AnalysisFinding rows for runs with findings
        for idx in range(f_count):
            finding = AnalysisFinding(
                id=uuid.uuid4(),
                analysis_run_id=run.id,
                repository_id=repo1.id,
                category="security" if feat == AnalysisFeature.DETECT_BUGS else "style",
                severity="HIGH" if idx == 0 else "MEDIUM",
                title=f"Sample finding {idx} for {feat.value}",
                description=f"Detailed description {idx}",
                file_path="src/main.py",
                start_line=1 + idx,
                end_line=2 + idx,
                evidence="Sample line evidence",
                suggested_fix="Fix line accordingly",
                confidence="high",
            )
            db_session.add(finding)
    db_session.commit()

    # 2. List analysis runs with token1 -> should see all 4
    res = client.get(
        f"/api/v1/repositories/{repo1.id}/analysis-runs",
        headers={"Authorization": f"Bearer {token1}"},
    )
    assert res.status_code == 200
    data = res.json()
    assert data["total"] == 4
    assert len(data["items"]) == 4

    # 3. Filter by feature_type=bugs
    res_bugs = client.get(
        f"/api/v1/repositories/{repo1.id}/analysis-runs?feature_type=bugs",
        headers={"Authorization": f"Bearer {token1}"},
    )
    assert res_bugs.status_code == 200
    bugs_data = res_bugs.json()
    assert bugs_data["total"] == 1
    assert bugs_data["items"][0]["feature_type"] == "detect_bugs"
    assert bugs_data["items"][0]["findings_count"] == 2

    # 4. Filter by status=FAILED
    res_failed = client.get(
        f"/api/v1/repositories/{repo1.id}/analysis-runs?status=FAILED",
        headers={"Authorization": f"Bearer {token1}"},
    )
    assert res_failed.status_code == 200
    failed_data = res_failed.json()
    assert failed_data["total"] == 1
    assert failed_data["items"][0]["feature_type"] == "generate_tests"
    assert failed_data["items"][0]["status"] == "FAILED"
    assert "timeout" in failed_data["items"][0]["error_message"]

    # 5. Reopen run details by UUID
    run_to_open = created_runs[1]  # detect_bugs run
    res_detail = client.get(
        f"/api/v1/analysis-runs/{run_to_open.id}",
        headers={"Authorization": f"Bearer {token1}"},
    )
    assert res_detail.status_code == 200
    detail = res_detail.json()
    assert detail["id"] == str(run_to_open.id)
    assert detail["feature_type"] == "detect_bugs"
    assert detail["status"] == "COMPLETED"
    assert detail["target_path"] == "src/main.py"
    assert detail["findings_count"] == 2

    # 6. Tenant Isolation: User 2 cannot access Repo 1 runs or list them
    res_u2_list = client.get(
        f"/api/v1/repositories/{repo1.id}/analysis-runs",
        headers={"Authorization": f"Bearer {token2}"},
    )
    assert res_u2_list.status_code == 404
    assert res_u2_list.json()["error"]["code"] == "REPOSITORY_NOT_FOUND"

    res_u2_detail = client.get(
        f"/api/v1/analysis-runs/{run_to_open.id}",
        headers={"Authorization": f"Bearer {token2}"},
    )
    assert res_u2_detail.status_code == 404

    # 7. Summary metrics endpoint
    res_summary = client.get(
        f"/api/v1/repositories/{repo1.id}/analysis-runs/summary",
        headers={"Authorization": f"Bearer {token1}"},
    )
    assert res_summary.status_code == 200
    summary = res_summary.json()
    assert summary["total_runs"] == 4
    assert summary["total_findings"] == 5  # 2 bugs + 3 review
    assert summary["by_status"]["COMPLETED"] == 3
    assert summary["by_status"]["FAILED"] == 1
