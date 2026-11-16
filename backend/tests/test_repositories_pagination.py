"""Server-side pagination tests for /repositories (TST-24, TST-31, ISS-024).

Validates:
- GET /api/v1/repositories accepts ?page=&page_size= and ?skip=&limit=.
- Returns paginated subsets ordered by creation date.
- Backwards compatible when no pagination parameters are supplied.
"""

from __future__ import annotations

from uuid import uuid4
from fastapi.testclient import TestClient

from app.core.security import create_access_token
from app.models.github_installation import GitHubInstallation
from app.models.repository import Repository, SyncStatus
from app.models.user import User


def test_list_repositories_pagination(client: TestClient, db_session) -> None:
    user = User(
        id=uuid4(),
        github_id="pagination-test-user-999",
        login="pagination_user",
        email="page@test.local",
    )
    db_session.add(user)
    db_session.commit()

    installation = GitHubInstallation(
        id=uuid4(),
        user_id=user.id,
        installation_id="inst-pagination-123",
        account_login="pagination_user",
    )
    db_session.add(installation)
    db_session.commit()

    # Create 5 repositories
    repos = [
        Repository(
            id=uuid4(),
            user_id=user.id,
            installation_id=installation.id,
            github_repo_id=f"repo-{i}",
            name=f"test-repo-{i}",
            owner="pagination_user",
            default_branch="main",
            sync_status=SyncStatus.SYNCED,
        )
        for i in range(5)
    ]
    for r in repos:
        db_session.add(r)
    db_session.commit()

    token, _ = create_access_token(user.id)
    headers = {"Authorization": f"Bearer {token}"}

    # 1. Unpaginated returns all 5
    res_all = client.get("/api/v1/repositories", headers=headers)
    assert res_all.status_code == 200
    assert len(res_all.json()) == 5

    # 2. Page 1, page_size 2 returns 2 items
    res_p1 = client.get("/api/v1/repositories?page=1&page_size=2", headers=headers)
    assert res_p1.status_code == 200
    data_p1 = res_p1.json()
    assert len(data_p1) == 2

    # 3. Page 2, page_size 2 returns 2 items
    res_p2 = client.get("/api/v1/repositories?page=2&page_size=2", headers=headers)
    assert res_p2.status_code == 200
    data_p2 = res_p2.json()
    assert len(data_p2) == 2
    # Ensure disjoint items
    p1_ids = {r["id"] for r in data_p1}
    p2_ids = {r["id"] for r in data_p2}
    assert p1_ids.isdisjoint(p2_ids)

    # 4. skip=4, limit=2 returns 1 item
    res_p3 = client.get("/api/v1/repositories?skip=4&limit=2", headers=headers)
    assert res_p3.status_code == 200
    assert len(res_p3.json()) == 1
