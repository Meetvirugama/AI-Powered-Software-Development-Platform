"""Tests for new Review API endpoints: publication, feedback, and settings."""

import pytest
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4
from fastapi.testclient import TestClient

from app.core.database import get_db
from app.core.security import create_access_token
from app.main import app
from app.models.analysis_finding import AnalysisFinding
from app.models.analysis_run import AnalysisRun
from app.models.repository import Repository, SyncStatus
from app.models.github_installation import GitHubInstallation
from app.models.user import User


class FakeRedis:
    def exists(self, _: str) -> int:
        return 0

    async def exists_async(self, _: str) -> int:
        return 0


@pytest.fixture(autouse=True)
def mock_redis_auth(monkeypatch):
    fake_redis = FakeRedis()
    monkeypatch.setattr("app.core.auth.get_redis", lambda: fake_redis)
    monkeypatch.setattr("app.core.redis.get_redis", lambda: fake_redis)
    monkeypatch.setattr("app.core.auth.get_redis_async", AsyncMock(return_value=fake_redis))


@pytest.fixture
def test_repo(db_session, test_user):
    inst = GitHubInstallation(
        id=uuid4(),
        user_id=test_user.id,
        installation_id="inst_999",
        account_login="test-owner",
    )
    db_session.add(inst)
    db_session.commit()

    repo = Repository(
        id=uuid4(),
        user_id=test_user.id,
        installation_id=inst.id,
        github_repo_id="12345",
        owner="test-owner",
        name="test-repo",
        default_branch="main",
        sync_status=SyncStatus.SYNCED,
    )
    db_session.add(repo)
    db_session.commit()
    return repo


def test_review_settings_get_and_patch(db_session, test_user, test_repo, auth_headers):
    app.dependency_overrides[get_db] = lambda: db_session

    client = TestClient(app)

    # 1. GET settings
    res = client.get(
        f"/api/v1/repositories/{test_repo.id}/review/settings",
        headers=auth_headers,
    )
    assert res.status_code == 200
    data = res.json()
    assert data["repository_id"] == str(test_repo.id)
    assert data["pr_review_enabled"] is False

    # 2. PATCH settings
    res_patch = client.patch(
        f"/api/v1/repositories/{test_repo.id}/review/settings",
        json={"pr_review_enabled": True, "max_comments": 20},
        headers=auth_headers,
    )
    assert res_patch.status_code == 200
    data_patch = res_patch.json()
    assert data_patch["pr_review_enabled"] is True
    assert data_patch["max_comments"] == 20

    # Verify persisted in DB
    db_session.refresh(test_repo)
    assert test_repo.pr_review_enabled is True


def test_submit_finding_feedback(db_session, test_user, test_repo, auth_headers):
    app.dependency_overrides[get_db] = lambda: db_session

    # Create run and finding
    run = AnalysisRun(
        id=uuid4(),
        repository_id=test_repo.id,
        user_id=test_user.id,
        feature_type="review",
        status="COMPLETED",
    )
    db_session.add(run)
    finding = AnalysisFinding(
        id=uuid4(),
        analysis_run_id=run.id,
        repository_id=test_repo.id,
        category="security",
        severity="HIGH",
        title="Hardcoded API key",
        description="Found API key in source",
        file_path="src/config.py",
        evidence='API_KEY = "12345"',
    )
    db_session.add(finding)
    db_session.commit()

    client = TestClient(app)

    res = client.post(
        f"/api/v1/analysis-runs/{run.id}/findings/{finding.id}/feedback",
        json={"feedback_type": "useful", "comment": "Saved production breach!"},
        headers=auth_headers,
    )

    assert res.status_code == 200
    data = res.json()
    assert data["finding_id"] == str(finding.id)
    assert data["feedback_type"] == "useful"
    assert data["comment"] == "Saved production breach!"
    assert data["repository_stats"]["useful_count"] == 1
    assert data["repository_stats"]["acceptance_rate"] == 1.0


def test_publish_review_endpoint(db_session, test_user, test_repo, auth_headers):
    app.dependency_overrides[get_db] = lambda: db_session

    # Mock GitHub Service on app.state
    mock_gh = AsyncMock()
    mock_gh.get_pull_request_detail.return_value = {"state": "open", "head": {"sha": "c0ffee"}}
    mock_gh.get_pull_request_files.return_value = [{"filename": "src/app.py", "patch": "@@ -1,2 +1,3 @@\n+x=1\n"}]
    mock_gh.create_pull_request_review.return_value = {"id": 12345}
    app.state.github_service = mock_gh

    # Create an analysis run with a finding on src/app.py line 2
    run = AnalysisRun(
        id=uuid4(),
        repository_id=test_repo.id,
        user_id=test_user.id,
        feature_type="review",
        status="COMPLETED",
        source_revision="c0ffee",
        result_payload={"report": {"findings": []}},
    )
    db_session.add(run)
    finding = AnalysisFinding(
        id=uuid4(),
        analysis_run_id=run.id,
        repository_id=test_repo.id,
        category="correctness",
        severity="HIGH",
        confidence="high",
        title="Syntax error",
        description="Invalid syntax",
        file_path="src/app.py",
        start_line=1,
        evidence="x=1 syntax error here",
    )
    db_session.add(finding)
    db_session.commit()

    client = TestClient(app)

    res = client.post(
        f"/api/v1/repositories/{test_repo.id}/review/publish",
        json={"run_id": str(run.id), "pr_number": 5, "commit_sha": "c0ffee", "force_publish": True},
        headers=auth_headers,
    )

    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "PUBLISHED"
    assert data["review_id"] == 12345
    assert data["pr_number"] == 5
    assert data["published_comments_count"] == 1

    # Verify installation_id passed to publication is resolved from GitHubInstallation (inst_999), not DB UUID
    call_kwargs = mock_gh.create_pull_request_review.call_args.kwargs
    assert call_kwargs["installation_id"] == "inst_999"


def test_submit_finding_feedback_idor_and_run_mismatch_rejected(db_session, test_user, test_repo, auth_headers):
    app.dependency_overrides[get_db] = lambda: db_session

    run1 = AnalysisRun(id=uuid4(), repository_id=test_repo.id, user_id=test_user.id, feature_type="review", status="COMPLETED")
    run2 = AnalysisRun(id=uuid4(), repository_id=test_repo.id, user_id=test_user.id, feature_type="review", status="COMPLETED")
    finding1 = AnalysisFinding(
        id=uuid4(),
        analysis_run_id=run1.id,
        repository_id=test_repo.id,
        category="security",
        severity="HIGH",
        title="Issue",
        description="Desc",
        file_path="src/a.py",
        evidence="evidence snippet",
    )
    db_session.add_all([run1, run2, finding1])
    db_session.commit()

    client = TestClient(app)

    # Mismatched run_id must return 404
    res_mismatch = client.post(
        f"/api/v1/analysis-runs/{run2.id}/findings/{finding1.id}/feedback",
        json={"feedback_type": "useful"},
        headers=auth_headers,
    )
    assert res_mismatch.status_code == 404

    # Other user accessing finding must return 404
    other_user = User(id=uuid4(), github_id="999888", login="other", email="other@example.com")
    db_session.add(other_user)
    db_session.commit()
    other_token, _ = create_access_token(user_id=str(other_user.id))
    other_headers = {"Authorization": f"Bearer {other_token}"}

    res_other = client.post(
        f"/api/v1/analysis-runs/{run1.id}/findings/{finding1.id}/feedback",
        json={"feedback_type": "useful"},
        headers=other_headers,
    )
    assert res_other.status_code == 404


def test_review_settings_persistence(db_session, test_user, test_repo, auth_headers):
    app.dependency_overrides[get_db] = lambda: db_session
    client = TestClient(app)

    # PATCH custom settings
    res_patch = client.patch(
        f"/api/v1/repositories/{test_repo.id}/review/settings",
        json={
            "min_confidence": "high",
            "max_comments": 25,
            "changed_lines_only": False,
        },
        headers=auth_headers,
    )
    assert res_patch.status_code == 200
    data = res_patch.json()
    assert data["min_confidence"] == "high"
    assert data["max_comments"] == 25
    assert data["changed_lines_only"] is False

    # GET settings must return the persisted custom settings
    res_get = client.get(
        f"/api/v1/repositories/{test_repo.id}/review/settings",
        headers=auth_headers,
    )
    assert res_get.status_code == 200
    data_get = res_get.json()
    assert data_get["min_confidence"] == "high"
    assert data_get["max_comments"] == 25
    assert data_get["changed_lines_only"] is False
