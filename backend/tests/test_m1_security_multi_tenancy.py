"""Security & Multi-Tenancy Tests for Milestone M1.

Covers:
1. GitHub Installation Linking Authorization & Cross-Tenant Reassignment Prevention
2. Multi-Tenant Task and Workspace Scoping (get_task, get_workspace, get_owned_task)
3. Repository Query Isolation in Lexical Retrieval (parameter binding & scoping)
4. GitHub Webhook Fail-Closed Security, Replay Protection & Size Boundaries
"""

from __future__ import annotations

import hashlib
import hmac
import json
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from starlette.requests import Request

from ai.retrieval.base import CodeChunk
from ai.retrieval.lexical import LexicalRetriever
from app.api.v1.dependencies import get_owned_task
from app.core.config import get_settings
from app.core.errors import APIError, ErrorCode
from app.core.security import create_access_token
from app.models.github_installation import GitHubInstallation
from app.models.repository import Repository, SyncStatus
from app.models.task import (
    Task,
    TaskSourceType,
    TaskStatus,
    Workspace,
    WorkspaceStatus,
)
from app.models.user import User
from app.repositories.github_installation_repository import GitHubInstallationRepository
from app.repositories.task_repository import TaskNotFoundError, TaskRepository


# ---------------------------------------------------------------------------
# Test Helpers & Fixtures
# ---------------------------------------------------------------------------

def _create_user(
    db,
    login: str = "tenant-user",
    github_id: str | None = None,
) -> User:
    user = User(
        id=uuid.uuid4(),
        github_id=github_id or f"gh_{uuid.uuid4().hex[:8]}",
        login=f"{login}_{uuid.uuid4().hex[:4]}",
        email=f"{login}_{uuid.uuid4().hex[:4]}@example.com",
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _create_repo(
    db,
    user: User,
    name: str = "tenant-repo",
) -> Repository:
    inst = GitHubInstallation(
        id=uuid.uuid4(),
        user_id=user.id,
        installation_id=f"inst_{uuid.uuid4().hex[:8]}",
        account_login=user.login,
        permissions={"contents": "read"},
    )
    db.add(inst)
    db.flush()

    repo = Repository(
        id=uuid.uuid4(),
        user_id=user.id,
        installation_id=inst.id,
        github_repo_id=f"repo_{uuid.uuid4().hex[:8]}",
        owner=user.login,
        name=name,
        default_branch="main",
        sync_status=SyncStatus.SYNCED,
    )
    db.add(repo)
    db.commit()
    db.refresh(repo)
    return repo


def _make_auth_header(user: User, monkeypatch) -> dict[str, str]:
    monkeypatch.setenv("JWT_SECRET", "test-secret-key-m1-security")
    get_settings.cache_clear()
    token, _ = create_access_token(user_id=str(user.id))
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# 1. GitHub Installation Linking Authorization
# ---------------------------------------------------------------------------

class TestGitHubInstallationAuth:
    """Verifies that GitHub installation linking cannot be hijacked across tenants."""

    def test_unverified_installation_query_param_rejected(
        self, client, db_session, monkeypatch
    ):
        """Passing an unverified installation_id in query params fails if account login does not match user."""
        attacker = _create_user(db_session, login="attacker_dev")
        headers = _make_auth_header(attacker, monkeypatch)

        # Configure mock github_service on app state
        mock_gh = MagicMock()
        mock_gh._app_auth_headers.return_value = {"Authorization": "Bearer gh-app-token"}
        client.app.state.github_service = mock_gh

        mock_resp = MagicMock()
        mock_resp.is_success = True
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "id": 99999,
            "target_id": 99999,
            "account": {"login": "victim_corp", "id": 99999},
            "permissions": {"contents": "read"},
        }

        with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = mock_resp
            res = client.get(
                "/api/v1/github/repositories?installation_id=99999",
                headers=headers,
            )

        assert res.status_code == 403
        data = res.json()
        assert data["error"]["code"] == "FORBIDDEN"
        assert "does not match the authenticated user" in data["error"]["message"]

    def test_cross_tenant_installation_link_rejected(
        self, client, db_session, monkeypatch
    ):
        """If an installation is already linked to Tenant A, Tenant B cannot link it."""
        victim = _create_user(db_session, login="victim_user")
        attacker = _create_user(db_session, login="attacker_user")
        headers = _make_auth_header(attacker, monkeypatch)

        # Seed installation owned by victim
        inst_repo = GitHubInstallationRepository(db_session)
        inst_repo.upsert(
            user_id=victim.id,
            installation_id="victim_shared_inst_123",
            account_login=victim.login,
            permissions={"contents": "read"},
        )

        res = client.get(
            "/api/v1/github/repositories?installation_id=victim_shared_inst_123",
            headers=headers,
        )

        assert res.status_code == 403
        data = res.json()
        assert data["error"]["code"] == "FORBIDDEN"
        assert "linked to another user account" in data["error"]["message"]

    def test_installation_repo_upsert_rejects_hijack(self, db_session):
        """GitHubInstallationRepository.upsert raises ValueError on cross-tenant reassignment."""
        victim = _create_user(db_session, login="victim_admin")
        attacker = _create_user(db_session, login="attacker_admin")
        inst_repo = GitHubInstallationRepository(db_session)

        inst_repo.upsert(
            user_id=victim.id,
            installation_id="hijack_target_456",
            account_login=victim.login,
            permissions={"pull_requests": "write"},
        )

        with pytest.raises(ValueError, match="is already linked to user"):
            inst_repo.upsert(
                user_id=attacker.id,
                installation_id="hijack_target_456",
                account_login=attacker.login,
                permissions={"pull_requests": "write"},
            )

    def test_verified_installation_link_succeeds(
        self, client, db_session, monkeypatch
    ):
        """When GitHub App API confirms ownership, installation is linked successfully."""
        legit_user = _create_user(db_session, login="legit_developer", github_id="88888")
        headers = _make_auth_header(legit_user, monkeypatch)

        mock_gh = MagicMock()
        mock_gh._app_auth_headers.return_value = {"Authorization": "Bearer gh-app-token"}
        client.app.state.github_service = mock_gh

        mock_resp = MagicMock()
        mock_resp.is_success = True
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "id": 88888,
            "target_id": 88888,
            "account": {"login": legit_user.login, "id": 88888},
            "permissions": {"contents": "write"},
        }

        with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = mock_resp
            res = client.get(
                "/api/v1/github/repositories?installation_id=88888",
                headers=headers,
            )

        assert res.status_code == 200
        inst = GitHubInstallationRepository(db_session).get_by_installation_id("88888")
        assert inst is not None
        assert inst.user_id == legit_user.id


# ---------------------------------------------------------------------------
# 2. Multi-Tenant Task and Workspace Scoping
# ---------------------------------------------------------------------------

class TestMultiTenantTaskAndWorkspaceScoping:
    """Verifies that direct task and workspace operations enforce strict user ownership."""

    def test_get_task_user_id_scoping(self, db_session):
        """TaskRepository.get_task returns None when queried with non-owner user_id."""
        user_a = _create_user(db_session, login="user_alpha")
        user_b = _create_user(db_session, login="user_beta")
        repo_a = _create_repo(db_session, user_a)
        task_repo = TaskRepository(db_session)

        task_a = task_repo.create_task(
            repository_id=repo_a.id,
            user_id=user_a.id,
            title="Tenant Alpha Task",
            source_type=TaskSourceType.DIRECT,
            description="Alpha private task",
        )

        # Scoped to owner -> found
        assert task_repo.get_task(task_a.id, user_id=user_a.id) is not None
        assert task_repo.get_task_for_user(task_a.id, user_id=user_a.id) is not None

        # Scoped to cross-tenant user -> None
        assert task_repo.get_task(task_a.id, user_id=user_b.id) is None
        assert task_repo.get_task_for_user(task_a.id, user_id=user_b.id) is None

    def test_get_owned_task_dependency_rejects_cross_tenant(self, db_session):
        """get_owned_task API dependency raises 404 TASK_NOT_FOUND on cross-tenant access."""
        user_a = _create_user(db_session, login="user_alpha_dep")
        user_b = _create_user(db_session, login="user_beta_dep")
        repo_a = _create_repo(db_session, user_a)
        task_repo = TaskRepository(db_session)

        task_a = task_repo.create_task(
            repository_id=repo_a.id,
            user_id=user_a.id,
            title="Tenant Alpha Secret Task",
            source_type=TaskSourceType.DIRECT,
        )

        # Tenant B request
        req_b = Request({"type": "http", "headers": [], "state": {}})
        req_b.state.user_id = str(user_b.id)

        with pytest.raises(APIError) as exc_info:
            get_owned_task(task_a.id, req_b, db_session)
        assert exc_info.value.status_code == 404
        assert exc_info.value.code == ErrorCode.TASK_NOT_FOUND

        # Tenant A request
        req_a = Request({"type": "http", "headers": [], "state": {}})
        req_a.state.user_id = str(user_a.id)

        owned_task, uid = get_owned_task(task_a.id, req_a, db_session)
        assert owned_task.id == task_a.id
        assert uid == user_a.id

    def test_get_task_workspace_endpoint_cross_tenant_returns_404(
        self, client, db_session, monkeypatch
    ):
        """GET /api/v1/tasks/{task_id}/workspace returns 404 when requested by non-owner."""
        user_a = _create_user(db_session, login="owner_alpha")
        user_b = _create_user(db_session, login="intruder_beta")
        repo_a = _create_repo(db_session, user_a)
        task_repo = TaskRepository(db_session)

        task_a = task_repo.create_task(
            repository_id=repo_a.id,
            user_id=user_a.id,
            title="Alpha Workspace Task",
            source_type=TaskSourceType.DIRECT,
        )

        headers_b = _make_auth_header(user_b, monkeypatch)
        res_b = client.get(f"/api/v1/tasks/{task_a.id}/workspace", headers=headers_b)
        assert res_b.status_code == 404
        assert res_b.json()["error"]["code"] == "TASK_NOT_FOUND"

        headers_a = _make_auth_header(user_a, monkeypatch)
        res_a = client.get(f"/api/v1/tasks/{task_a.id}/workspace", headers=headers_a)
        assert res_a.status_code == 200

    def test_task_repo_get_workspace_with_user_id_isolation(self, db_session):
        """TaskRepository.get_workspace and get_workspace_record enforce user_id isolation."""
        user_a = _create_user(db_session, login="ws_user_a")
        user_b = _create_user(db_session, login="ws_user_b")
        repo_a = _create_repo(db_session, user_a)
        task_repo = TaskRepository(db_session)

        task_a = task_repo.create_task(
            repository_id=repo_a.id,
            user_id=user_a.id,
            title="Isolated Workspace Task",
            source_type=TaskSourceType.DIRECT,
        )

        workspace_a = Workspace(
            id=uuid.uuid4(),
            task_id=task_a.id,
            workspace_path="/tmp/isolated_workspace_a",
            task_branch=f"agent/task-{task_a.id}",
            base_revision="main",
            status=WorkspaceStatus.READY.value,
        )
        db_session.add(workspace_a)
        db_session.commit()

        # Cross-tenant get_workspace raises TaskNotFoundError
        with pytest.raises(TaskNotFoundError):
            task_repo.get_workspace(task_a.id, repo_a.id, user_id=user_b.id)

        # Owner get_workspace returns workspace
        ws = task_repo.get_workspace(task_a.id, repo_a.id, user_id=user_a.id)
        assert ws is not None
        assert ws.id == workspace_a.id

        # Cross-tenant get_workspace_record returns None
        assert task_repo.get_workspace_record(task_a.id, user_id=user_b.id) is None
        assert task_repo.get_workspace_record(task_a.id, user_id=user_a.id) is not None


# ---------------------------------------------------------------------------
# 3. Repository Query Isolation in Lexical Retrieval
# ---------------------------------------------------------------------------

class TestLexicalRetrievalScoping:
    """Verifies that LexicalRetriever binds repository_id parameter and avoids cross-repo leakage."""

    @pytest.mark.asyncio
    async def test_lexical_retriever_repository_scoping(self):
        """LexicalRetriever binds repository_id in parameterized SQL execution."""
        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.fetchall.return_value = []
        mock_db.execute.return_value = mock_result

        target_repo_id = uuid.uuid4()
        retriever = LexicalRetriever(db=mock_db)

        await retriever.retrieve("authentication credentials login", repository_id=target_repo_id)

        assert mock_db.execute.called, "DB execute must be called"
        call_args = mock_db.execute.call_args
        params = call_args[0][1]
        assert params["repository_id"] == str(target_repo_id), (
            f"Expected repository_id={target_repo_id} in query params, got {params}"
        )

    @pytest.mark.asyncio
    async def test_lexical_retriever_no_cross_repo_leakage(self):
        """Simulated query returns chunks only scoped to the requested repository."""
        target_repo_id = uuid.uuid4()
        row_target = SimpleNamespace(
            id=uuid.uuid4(),
            repository_id=target_repo_id,
            file_id=uuid.uuid4(),
            symbol_id=None,
            content="def authenticate_user(): pass",
            token_count=10,
            start_line=1,
            end_line=5,
            content_hash="hash1",
            file_path="auth/service.py",
            rank=0.8,
            normalised_rank=0.8,
        )

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.fetchall.return_value = [row_target]
        mock_db.execute.return_value = mock_result

        retriever = LexicalRetriever(db=mock_db)
        results = await retriever.retrieve("authenticate", repository_id=target_repo_id)

        assert len(results) == 1
        assert isinstance(results[0], CodeChunk)
        assert results[0].repository_id == target_repo_id
        assert results[0].file_path == "auth/service.py"


# ---------------------------------------------------------------------------
# 4. GitHub Webhook Fail-Closed Security & Replay Protection
# ---------------------------------------------------------------------------

class TestGitHubWebhookSecurity:
    """Verifies fail-closed behavior, HMAC verification, replay deduplication, and payload limits."""

    def test_webhook_fails_closed_on_whitespace_secret(self, client, monkeypatch):
        """Webhook endpoint returns 503 SERVICE_UNAVAILABLE when webhook secret is whitespace."""
        monkeypatch.setenv("GITHUB_WEBHOOK_SECRET", "   ")
        get_settings.cache_clear()

        res = client.post(
            "/api/v1/github/webhook",
            headers={"X-GitHub-Event": "ping"},
            json={"zen": "fail closed"},
        )
        assert res.status_code == 503
        data = res.json()
        assert data["error"]["code"] == "SERVICE_UNAVAILABLE"

    def test_webhook_rejects_invalid_hmac_signature(self, client, monkeypatch):
        """Webhook endpoint returns 401 UNAUTHORIZED when HMAC-SHA256 signature is invalid."""
        monkeypatch.setenv("GITHUB_WEBHOOK_SECRET", "valid-secret-key")
        get_settings.cache_clear()

        res = client.post(
            "/api/v1/github/webhook",
            headers={
                "X-GitHub-Event": "ping",
                "X-Hub-Signature-256": "sha256=invaliddeadbeef",
                "Content-Type": "application/json",
            },
            content=b'{"zen": "test"}',
        )
        assert res.status_code == 401
        data = res.json()
        assert data["error"]["code"] == "UNAUTHORIZED"

    def test_webhook_rejects_malformed_delivery_id(self, client, monkeypatch):
        """Webhook endpoint returns 400 BAD_REQUEST on invalid delivery ID format."""
        wh_key = "valid-secret-key"
        monkeypatch.setenv("GITHUB_WEBHOOK_SECRET", wh_key)
        get_settings.cache_clear()

        body = b'{"zen": "test"}'
        sig = "sha256=" + hmac.new(wh_key.encode("utf-8"), body, hashlib.sha256).hexdigest()

        res = client.post(
            "/api/v1/github/webhook",
            headers={
                "X-GitHub-Event": "ping",
                "X-Hub-Signature-256": sig,
                "X-GitHub-Delivery": "delivery_id_with_invalid;rm -rf",
                "Content-Type": "application/json",
            },
            content=body,
        )
        assert res.status_code == 400
        data = res.json()
        assert data["error"]["code"] == "BAD_REQUEST"

    def test_webhook_deduplicates_delivery_id_in_redis(
        self, client, fake_redis, monkeypatch
    ):
        """Subsequent webhook deliveries with the same delivery ID are deduplicated and ignored."""
        wh_key = "valid-secret-key"
        monkeypatch.setenv("GITHUB_WEBHOOK_SECRET", wh_key)
        get_settings.cache_clear()

        delivery_id = f"delivery-{uuid.uuid4().hex}"
        body = b'{"zen": "duplicate check"}'
        sig = "sha256=" + hmac.new(wh_key.encode("utf-8"), body, hashlib.sha256).hexdigest()

        headers = {
            "X-GitHub-Event": "ping",
            "X-Hub-Signature-256": sig,
            "X-GitHub-Delivery": delivery_id,
            "Content-Type": "application/json",
        }

        # Patch fake_redis.set to respect nx=True
        seen_keys = set()

        def custom_set(key, val, *args, **kwargs):
            if kwargs.get("nx"):
                if key in seen_keys:
                    return False
                seen_keys.add(key)
                return True
            seen_keys.add(key)
            return True

        monkeypatch.setattr(fake_redis, "set", custom_set)

        # 1. First delivery succeeds
        res_first = client.post("/api/v1/github/webhook", headers=headers, content=body)
        assert res_first.status_code == 200
        assert res_first.json()["status"] == "pong"

        # 2. Second delivery with identical delivery ID is ignored
        res_second = client.post("/api/v1/github/webhook", headers=headers, content=body)
        assert res_second.status_code == 200
        data = res_second.json()
        assert data["status"] == "duplicate_delivery_ignored"
        assert data["delivery_id"] == delivery_id

    def test_webhook_rejects_payload_exceeding_max_bytes(
        self, client, monkeypatch
    ):
        """Webhook payload exceeding 5MB returns 413 Payload Too Large / BAD_REQUEST."""
        wh_key = "valid-secret-key"
        monkeypatch.setenv("GITHUB_WEBHOOK_SECRET", wh_key)
        get_settings.cache_clear()

        oversized_body = b"x" * (5 * 1024 * 1024 + 1)

        res = client.post(
            "/api/v1/github/webhook",
            headers={"Content-Type": "application/json"},
            content=oversized_body,
        )
        assert res.status_code == 413
        data = res.json()
        assert data["error"]["code"] == "BAD_REQUEST"
