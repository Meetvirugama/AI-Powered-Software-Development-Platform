"""Tests for repository management endpoints with mock authentication."""

from __future__ import annotations

import uuid
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.github_installation import GitHubInstallation
from app.models.repository import Repository, SyncStatus
from app.models.repository_file import RepositoryFile
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


def test_get_repository_dependencies_empty(
    client: TestClient,
    db_session: Session,
    test_user: User,
    auth_headers: dict[str, str],
) -> None:
    installation = GitHubInstallation(
        id=uuid.uuid4(),
        user_id=test_user.id,
        installation_id="inst-dep-1",
        account_login=test_user.login,
        permissions={"contents": "read"},
    )
    db_session.add(installation)
    db_session.commit()

    repo = Repository(
        id=uuid.uuid4(),
        user_id=test_user.id,
        installation_id=installation.id,
        github_repo_id="gh-repo-dep-1",
        owner=test_user.login,
        name="test-dep-repo",
    )
    db_session.add(repo)
    db_session.commit()

    response = client.get(f"/api/v1/repositories/{repo.id}/dependencies", headers=auth_headers)
    assert response.status_code == 200
    assert response.json() == []


def test_get_repository_includes_stats(
    client: TestClient,
    db_session: Session,
    test_user: User,
    auth_headers: dict[str, str],
) -> None:
    installation = GitHubInstallation(
        id=uuid.uuid4(),
        user_id=test_user.id,
        installation_id="inst-stats-1",
        account_login=test_user.login,
        permissions={"contents": "read"},
    )
    db_session.add(installation)
    db_session.commit()

    repo = Repository(
        id=uuid.uuid4(),
        user_id=test_user.id,
        installation_id=installation.id,
        github_repo_id="gh-repo-stats-1",
        owner=test_user.login,
        name="test-stats-repo",
    )
    db_session.add(repo)
    db_session.commit()

    response = client.get(f"/api/v1/repositories/{repo.id}", headers=auth_headers)
    assert response.status_code == 200
    data = response.json()
    assert "file_count" in data
    assert "symbol_count" in data
    assert "chunk_count" in data


def test_delete_repository(
    client: TestClient,
    db_session: Session,
    test_user: User,
    auth_headers: dict[str, str],
) -> None:
    installation = GitHubInstallation(
        id=uuid.uuid4(),
        user_id=test_user.id,
        installation_id="inst-del-1",
        account_login=test_user.login,
        permissions={"contents": "read"},
    )
    db_session.add(installation)
    db_session.commit()

    repo = Repository(
        id=uuid.uuid4(),
        user_id=test_user.id,
        installation_id=installation.id,
        github_repo_id="gh-repo-del-1",
        owner=test_user.login,
        name="test-del-repo",
    )
    db_session.add(repo)
    db_session.commit()

    # Delete
    response = client.delete(f"/api/v1/repositories/{repo.id}", headers=auth_headers)
    assert response.status_code == 204

    # Verify 404 now
    response = client.get(f"/api/v1/repositories/{repo.id}", headers=auth_headers)
    assert response.status_code == 404


def test_list_files_pagination_and_filter(
    client: TestClient,
    db_session: Session,
    test_user: User,
    auth_headers: dict[str, str],
) -> None:
    """Verify list_files respects pagination parameters and path filtering."""
    installation = GitHubInstallation(
        id=uuid.uuid4(),
        user_id=test_user.id,
        installation_id="inst-files-1",
        account_login=test_user.login,
        permissions={"contents": "read"},
    )
    db_session.add(installation)
    db_session.commit()

    repo = Repository(
        id=uuid.uuid4(),
        user_id=test_user.id,
        installation_id=installation.id,
        github_repo_id="gh-repo-files-1",
        owner=test_user.login,
        name="test-files-repo",
    )
    db_session.add(repo)
    db_session.commit()

    # Add 15 files
    for i in range(15):
        prefix = "src" if i < 10 else "tests"
        f = RepositoryFile(
            id=uuid.uuid4(),
            repository_id=repo.id,
            path=f"{prefix}/file_{i}.py",
            language="Python",
            size_bytes=100,
            line_count=10,
            content_hash=f"hash_{i}",
        )
        db_session.add(f)
    db_session.commit()

    # Test page 1 with page_size=5
    res = client.get(f"/api/v1/repositories/{repo.id}/files?page=1&page_size=5", headers=auth_headers)
    assert res.status_code == 200
    data = res.json()
    assert data["total"] == 15
    assert len(data["items"]) == 5
    assert data["page"] == 1
    assert data["page_size"] == 5

    # Test page 2 with page_size=5
    res2 = client.get(f"/api/v1/repositories/{repo.id}/files?page=2&page_size=5", headers=auth_headers)
    assert res2.status_code == 200
    data2 = res2.json()
    assert len(data2["items"]) == 5
    # Ensure items on page 2 differ from page 1
    p1_paths = [x["path"] for x in data["items"]]
    p2_paths = [x["path"] for x in data2["items"]]
    assert not set(p1_paths).intersection(set(p2_paths))

    # Test filtering by path="tests"
    res_filter = client.get(f"/api/v1/repositories/{repo.id}/files?path=tests", headers=auth_headers)
    assert res_filter.status_code == 200
    data_filter = res_filter.json()
    assert data_filter["total"] == 5
    assert all("tests" in x["path"] for x in data_filter["items"])


def test_get_file_by_path(
    client: TestClient,
    db_session: Session,
    test_user: User,
    auth_headers: dict[str, str],
) -> None:
    """Verify lookup of a file by its exact path."""
    installation = GitHubInstallation(
        id=uuid.uuid4(),
        user_id=test_user.id,
        installation_id="inst-path-1",
        account_login=test_user.login,
        permissions={"contents": "read"},
    )
    db_session.add(installation)
    db_session.commit()

    repo = Repository(
        id=uuid.uuid4(),
        user_id=test_user.id,
        installation_id=installation.id,
        github_repo_id="gh-repo-path-1",
        owner=test_user.login,
        name="test-path-repo",
    )
    db_session.add(repo)
    db_session.commit()

    f = RepositoryFile(
        id=uuid.uuid4(),
        repository_id=repo.id,
        path="src/components/Header.tsx",
        language="TypeScript",
        size_bytes=250,
        line_count=20,
        content_hash="hash_header",
    )
    db_session.add(f)
    db_session.commit()

    # Exact lookup
    res = client.get(
        f"/api/v1/repositories/{repo.id}/files/by-path",
        params={"path": "src/components/Header.tsx"},
        headers=auth_headers,
    )
    assert res.status_code == 200
    file_data = res.json()
    assert file_data["path"] == "src/components/Header.tsx"
    assert file_data["language"] == "TypeScript"

    # Leading slash or ./ normalization
    res_normalized = client.get(
        f"/api/v1/repositories/{repo.id}/files/by-path",
        params={"path": "./src/components/Header.tsx"},
        headers=auth_headers,
    )
    assert res_normalized.status_code == 200
    assert res_normalized.json()["id"] == str(f.id)

    # Not found
    res_not_found = client.get(
        f"/api/v1/repositories/{repo.id}/files/by-path",
        params={"path": "does/not/exist.ts"},
        headers=auth_headers,
    )
    assert res_not_found.status_code == 404

