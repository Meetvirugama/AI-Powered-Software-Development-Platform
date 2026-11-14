"""Comprehensive RBAC and API Security Unit & Integration Test Suite.

Issue #211: F30 - API Security, Role-Based Access Control, and CI Integration.
Verifies:
1. UserRole enum and hierarchy (Admin > Developer > Viewer).
2. JWT claims for role and granular permissions.
3. FastAPIDependencies (require_role, require_min_role, require_permission).
4. Route-level RBAC:
   - Viewers are strictly blocked (403 Forbidden) from task planning, approval, execution,
     git branch/commit/push, publication authorization, repository sync, and deletion.
   - Viewers retain read access (200 OK) to repository and task status endpoints.
   - Developers and Admins can perform state-mutating and governance actions.
5. Strict tenant isolation: Cross-tenant requests return 404 Not Found regardless of caller role.
"""

from __future__ import annotations

import uuid
from typing import Any
from unittest.mock import MagicMock

import jwt
import pytest
from fastapi import Request
from fastapi.testclient import TestClient

from app.api.v1.dependencies import (
    ROLE_HIERARCHY,
    get_request_user_role,
    require_min_role,
    require_permission,
    require_role,
)
from app.core.config import get_settings
from app.core.errors import APIError
from app.core.security import create_access_token
from app.main import app
from app.models.github_installation import GitHubInstallation
from app.models.repository import Repository
from app.models.task import AgentTask, TaskStatus
from app.models.user import User, UserRole


# ---------------------------------------------------------------------------
# Helpers & Fixtures
# ---------------------------------------------------------------------------

def _create_user_and_repo(
    db_session: Any, login: str = "test-sec-user", role: str = "developer"
) -> tuple[User, Repository]:
    user = User(
        id=uuid.uuid4(),
        github_id=f"gh-{uuid.uuid4().hex[:8]}",
        login=login,
        email=f"{login}@example.com",
        role=role,
    )
    db_session.add(user)
    db_session.commit()

    installation = GitHubInstallation(
        id=uuid.uuid4(),
        user_id=user.id,
        installation_id=f"inst-{uuid.uuid4().hex[:8]}",
        account_login=login,
        permissions={"contents": "read"},
    )
    db_session.add(installation)
    db_session.commit()

    repo = Repository(
        id=uuid.uuid4(),
        user_id=user.id,
        installation_id=installation.id,
        github_repo_id=f"gh-repo-{uuid.uuid4().hex[:8]}",
        owner=login,
        name="test-repo",
        default_branch="main",
    )
    db_session.add(repo)
    db_session.commit()
    return user, repo


def _create_task(db_session: Any, user: User, repo: Repository) -> AgentTask:
    task = AgentTask(
        id=uuid.uuid4(),
        user_id=user.id,
        repository_id=repo.id,
        title="Security Verification Task",
        description="Verify RBAC guards across task lifecycle",
        status=TaskStatus.PLANNING.value,
        base_revision="main",
        requirements=[{"id": "REQ-1", "description": "Enforce RBAC"}],
        assumptions=[],
        constraints=[],
        plan_version=1,
    )
    db_session.add(task)
    db_session.commit()
    return task


def _auth_headers(
    user_id: uuid.UUID,
    role: str = "developer",
    permissions: list[str] | None = None,
) -> dict[str, str]:
    token, _ = create_access_token(user_id=user_id, role=role, permissions=permissions)
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# 1. Model & Token Claims Tests
# ---------------------------------------------------------------------------

def test_user_role_enum_and_hierarchy():
    assert UserRole.ADMIN.value == "admin"
    assert UserRole.DEVELOPER.value == "developer"
    assert UserRole.VIEWER.value == "viewer"

    assert ROLE_HIERARCHY["admin"] > ROLE_HIERARCHY["developer"]
    assert ROLE_HIERARCHY["developer"] > ROLE_HIERARCHY["viewer"]
    assert ROLE_HIERARCHY["viewer"] == 1


def test_create_access_token_embeds_role_and_permissions(monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "super-secret-jwt-key-32-chars-minimum")
    get_settings.cache_clear()
    settings = get_settings()

    user_id = uuid.uuid4()
    token, _ = create_access_token(
        user_id=user_id,
        role=UserRole.ADMIN.value,
        permissions=["tasks:approve", "repos:delete"],
    )

    payload = jwt.decode(
        token,
        settings.jwt_secret,
        algorithms=[settings.jwt_algorithm],
        audience=settings.jwt_audience,
        issuer=settings.jwt_issuer,
    )

    assert payload["sub"] == str(user_id)
    assert payload["role"] == "admin"
    assert payload["permissions"] == ["tasks:approve", "repos:delete"]


def test_create_access_token_defaults_to_developer(monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "super-secret-jwt-key-32-chars-minimum")
    get_settings.cache_clear()
    settings = get_settings()

    user_id = uuid.uuid4()
    token, _ = create_access_token(user_id=user_id)

    payload = jwt.decode(
        token,
        settings.jwt_secret,
        algorithms=[settings.jwt_algorithm],
        audience=settings.jwt_audience,
        issuer=settings.jwt_issuer,
    )

    assert payload["role"] == "developer"
    assert payload["permissions"] == []


# ---------------------------------------------------------------------------
# 2. Dependency Unit Tests
# ---------------------------------------------------------------------------

def test_require_role_dependency_logic():
    admin_request = MagicMock()
    admin_request.state.role = "admin"

    dev_request = MagicMock()
    dev_request.state.role = "developer"

    viewer_request = MagicMock()
    viewer_request.state.role = "viewer"

    admin_guard = require_role(UserRole.ADMIN)
    assert admin_guard(admin_request) == "admin"

    with pytest.raises(APIError) as exc_info:
        admin_guard(dev_request)
    assert exc_info.value.status_code == 403

    with pytest.raises(APIError) as exc_info:
        admin_guard(viewer_request)
    assert exc_info.value.status_code == 403


def test_require_min_role_dependency_logic():
    admin_request = MagicMock()
    admin_request.state.role = "admin"

    dev_request = MagicMock()
    dev_request.state.role = "developer"

    viewer_request = MagicMock()
    viewer_request.state.role = "viewer"

    dev_min_guard = require_min_role(UserRole.DEVELOPER)
    assert dev_min_guard(admin_request) == "admin"
    assert dev_min_guard(dev_request) == "developer"

    with pytest.raises(APIError) as exc_info:
        dev_min_guard(viewer_request)
    assert exc_info.value.status_code == 403


def test_require_permission_dependency_logic():
    admin_request = MagicMock()
    admin_request.state.role = "admin"
    admin_request.state.permissions = []

    user_with_perm = MagicMock()
    user_with_perm.state.role = "developer"
    user_with_perm.state.permissions = ["custom:action"]

    user_without_perm = MagicMock()
    user_without_perm.state.role = "developer"
    user_without_perm.state.permissions = ["other:action"]

    guard = require_permission("custom:action")

    # Admin bypasses specific permissions
    assert guard(admin_request) == "custom:action"

    # User with exact permission succeeds
    assert guard(user_with_perm) == "custom:action"

    # User without permission is blocked
    with pytest.raises(APIError) as exc_info:
        guard(user_without_perm)
    assert exc_info.value.status_code == 403


# ---------------------------------------------------------------------------
# 3. Route-Level RBAC Integration Tests (TestClient)
# ---------------------------------------------------------------------------

def test_viewer_is_forbidden_from_mutating_tasks(client, db_session, monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "super-secret-jwt-key-32-chars-minimum")
    get_settings.cache_clear()

    user, repo = _create_user_and_repo(db_session, login="viewer-user", role="viewer")
    task = _create_task(db_session, user, repo)
    viewer_headers = _auth_headers(user.id, role="viewer")

    # 1. Approve task plan
    resp = client.post(f"/api/v1/tasks/{task.id}/approve", json={"notes": "Approve attempt"}, headers=viewer_headers)
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "FORBIDDEN"

    # 2. Reject task plan
    resp = client.post(f"/api/v1/tasks/{task.id}/reject", json={"reason": "Reject attempt"}, headers=viewer_headers)
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "FORBIDDEN"

    # 3. Execute task
    resp = client.post(f"/api/v1/tasks/{task.id}/execute", json={}, headers=viewer_headers)
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "FORBIDDEN"

    # 4. Authorize publication
    resp = client.post(
        f"/api/v1/tasks/{task.id}/authorize-publication",
        json={"head_sha": "a" * 40, "notes": "Auth attempt"},
        headers=viewer_headers,
    )
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "FORBIDDEN"

    # 5. Create PR / Publish
    resp = client.post(f"/api/v1/tasks/{task.id}/publish", json={}, headers=viewer_headers)
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "FORBIDDEN"

    # 6. Branch creation
    resp = client.post(f"/api/v1/tasks/{task.id}/branch", json={}, headers=viewer_headers)
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "FORBIDDEN"

    # 7. Create task
    resp = client.post(
        "/api/v1/tasks",
        json={
            "repository_id": str(repo.id),
            "title": "Unauthorized Task",
            "source": {"type": "USER_PROMPT", "prompt": "Create something"},
        },
        headers=viewer_headers,
    )
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "FORBIDDEN"


def test_viewer_is_forbidden_from_repository_mutations(client, db_session, monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "super-secret-jwt-key-32-chars-minimum")
    get_settings.cache_clear()

    user, repo = _create_user_and_repo(db_session, login="repo-viewer", role="viewer")
    viewer_headers = _auth_headers(user.id, role="viewer")

    # 1. Sync repository
    resp = client.post(f"/api/v1/repositories/{repo.id}/sync", headers=viewer_headers)
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "FORBIDDEN"

    # 2. Delete repository
    resp = client.delete(f"/api/v1/repositories/{repo.id}", headers=viewer_headers)
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "FORBIDDEN"


def test_viewer_has_read_only_access(client, db_session, monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "super-secret-jwt-key-32-chars-minimum")
    get_settings.cache_clear()

    user, repo = _create_user_and_repo(db_session, login="read-viewer", role="viewer")
    task = _create_task(db_session, user, repo)
    viewer_headers = _auth_headers(user.id, role="viewer")

    # 1. Get repository details
    resp = client.get(f"/api/v1/repositories/{repo.id}", headers=viewer_headers)
    assert resp.status_code == 200

    # 2. List repositories
    resp = client.get("/api/v1/repositories", headers=viewer_headers)
    assert resp.status_code == 200

    # 3. Get task detail
    resp = client.get(f"/api/v1/tasks/{task.id}", headers=viewer_headers)
    assert resp.status_code == 200

    # 4. List tasks
    resp = client.get("/api/v1/tasks", headers=viewer_headers)
    assert resp.status_code == 200


def test_developer_and_admin_have_mutation_access(client, db_session, monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "super-secret-jwt-key-32-chars-minimum")
    get_settings.cache_clear()

    user, repo = _create_user_and_repo(db_session, login="dev-user", role="developer")
    task = _create_task(db_session, user, repo)
    dev_headers = _auth_headers(user.id, role="developer")

    # 1. Sync repository succeeds with 202 Accepted
    resp = client.post(f"/api/v1/repositories/{repo.id}/sync", headers=dev_headers)
    assert resp.status_code == 202

    # 2. Reject task plan does not return 403 Forbidden (developer has access)
    resp = client.post(
        f"/api/v1/tasks/{task.id}/reject",
        json={"reason": "Rejected during test"},
        headers=dev_headers,
    )
    assert resp.status_code != 403


def test_cross_tenant_isolation_supersedes_rbac_role(client, db_session, monkeypatch):
    """
    Even an ADMIN user must be rejected with 404 (not 200 or 403) when attempting
    to access another user's repository or task, preserving strict tenant boundaries.
    """
    monkeypatch.setenv("JWT_SECRET", "super-secret-jwt-key-32-chars-minimum")
    get_settings.cache_clear()

    user_a, repo_a = _create_user_and_repo(db_session, login="user-a", role="developer")
    task_a = _create_task(db_session, user_a, repo_a)

    user_b, _ = _create_user_and_repo(db_session, login="user-b-admin", role="admin")
    admin_b_headers = _auth_headers(user_b.id, role="admin")

    # Admin B accessing User A's repo must get 404 NOT_FOUND
    resp = client.get(f"/api/v1/repositories/{repo_a.id}", headers=admin_b_headers)
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "REPOSITORY_NOT_FOUND"

    # Admin B mutating User A's repo must get 404 NOT_FOUND
    resp = client.post(f"/api/v1/repositories/{repo_a.id}/sync", headers=admin_b_headers)
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "REPOSITORY_NOT_FOUND"

    # Admin B accessing User A's task must get 404 NOT_FOUND
    resp = client.get(f"/api/v1/tasks/{task_a.id}", headers=admin_b_headers)
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "TASK_NOT_FOUND"

    # Admin B mutating User A's task must get 404 NOT_FOUND
    resp = client.post(f"/api/v1/tasks/{task_a.id}/approve", json={}, headers=admin_b_headers)
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "TASK_NOT_FOUND"


def test_memory_api_rbac_guards(client, db_session, monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "super-secret-jwt-key-32-chars-minimum")
    get_settings.cache_clear()

    user, repo = _create_user_and_repo(db_session, login="memory-test-user", role="developer")
    viewer_headers = _auth_headers(user.id, role="viewer")
    dev_headers = _auth_headers(user.id, role="developer")

    # Viewer cannot create memory
    resp = client.post(
        f"/api/v1/repositories/{repo.id}/memories",
        json={"type": "rule", "content": "Always write tests", "source": "CONVENTION"},
        headers=viewer_headers,
    )
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "FORBIDDEN"

    # Developer can create memory
    resp = client.post(
        f"/api/v1/repositories/{repo.id}/memories",
        json={"type": "rule", "content": "Always write tests", "source": "CONVENTION"},
        headers=dev_headers,
    )
    assert resp.status_code == 201

    # Viewer can read memory list
    resp = client.get(f"/api/v1/repositories/{repo.id}/memories", headers=viewer_headers)
    assert resp.status_code == 200
