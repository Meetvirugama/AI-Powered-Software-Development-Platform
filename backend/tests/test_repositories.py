"""Tests for repository management endpoints with mock authentication."""

from __future__ import annotations

import uuid
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.github_installation import GitHubInstallation
from app.models.repository import Repository, SyncStatus
from app.models.user import User


def test_list_repositories_empty(client: TestClient, auth_headers: dict[str, str]) -> None:
    """Verify that a newly authenticated user with no connected repositories receives an empty list."""
    response = client.get("/api/v1/repositories", headers=auth_headers)

    assert response.status_code == 200
    assert response.json() == []


def test_get_nonexistent_repository_returns_404(client: TestClient, auth_headers: dict[str, str]) -> None:
    """Verify that requesting a repository that does not exist returns 404 REPOSITORY_NOT_FOUND."""
    random_repo_id = uuid.uuid4()
    response = client.get(f"/api/v1/repositories/{random_repo_id}", headers=auth_headers)

    assert response.status_code == 404
    data = response.json()
    assert "error" in data
    assert data["error"]["code"] == "REPOSITORY_NOT_FOUND"
    assert "Repository does not exist or you do not have access." in data["error"]["message"]


def test_get_repository_success_when_owned(
    client: TestClient,
    db_session: Session,
    test_user: User,
    auth_headers: dict[str, str],
) -> None:
    """Verify that an authenticated user can retrieve details for a repository they own."""
    # Create installation
    installation = GitHubInstallation(
        id=uuid.uuid4(),
        user_id=test_user.id,
        installation_id="inst-12345",
        account_login=test_user.login,
        permissions={"contents": "read"},
    )
    db_session.add(installation)
    db_session.commit()

    # Create repository owned by test_user
    repo = Repository(
        id=uuid.uuid4(),
        user_id=test_user.id,
        installation_id=installation.id,
        github_repo_id="gh-repo-555",
        owner=test_user.login,
        name="test-repo",
        default_branch="main",
        language="Python",
        sync_status=SyncStatus.NOT_SYNCED,
    )
    db_session.add(repo)
    db_session.commit()

    response = client.get(f"/api/v1/repositories/{repo.id}", headers=auth_headers)

    assert response.status_code == 200
    data = response.json()
    assert data["id"] == str(repo.id)
    assert data["name"] == "test-repo"
    assert data["owner"] == test_user.login
    assert data["full_name"] == f"{test_user.login}/test-repo"
    assert data["sync_status"] == SyncStatus.NOT_SYNCED.value


def test_list_repositories_is_scoped_to_user(
    client: TestClient,
    db_session: Session,
    test_user: User,
    auth_headers: dict[str, str],
) -> None:
    """Verify that listing repositories only returns repositories belonging to the requesting user."""
    # Another user with their own installation and repository
    other_user = User(
        id=uuid.uuid4(),
        github_id="gh-99999",
        login="other_user",
        email="other@example.com",
    )
    db_session.add(other_user)
    db_session.commit()

    other_installation = GitHubInstallation(
        id=uuid.uuid4(),
        user_id=other_user.id,
        installation_id="inst-99999",
        account_login=other_user.login,
        permissions={"contents": "read"},
    )
    db_session.add(other_installation)
    db_session.commit()

    other_repo = Repository(
        id=uuid.uuid4(),
        user_id=other_user.id,
        installation_id=other_installation.id,
        github_repo_id="gh-repo-999",
        owner=other_user.login,
        name="other-repo",
    )
    db_session.add(other_repo)
    db_session.commit()

    # When test_user lists repositories, other_user's repo should not appear
    response = client.get("/api/v1/repositories", headers=auth_headers)

    assert response.status_code == 200
    data = response.json()
    assert not any(r["id"] == str(other_repo.id) for r in data)
