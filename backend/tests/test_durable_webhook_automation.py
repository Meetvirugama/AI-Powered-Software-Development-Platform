"""Comprehensive automated test suite for Issue #182 — Durable GitHub Webhook Automation.

Tests:
1. Webhook endpoint security: HMAC-SHA256 verification, size ceilings, fail-closed on unset secret.
2. Fast acknowledgment and durable event persistence with HTTP 202 Accepted.
3. Delivery deduplication across Redis cache and PostgreSQL unique constraint.
4. Worker atomic claim (FOR UPDATE SKIP LOCKED), lease timeouts, exponential backoff, and dead-letter queue.
5. Safe administrative replay of failed and dead-letter events.
6. Push event automated sync: default branch filter, deleted branch filter, duplicate SHA skip, concurrency retry.
7. Installation event reconciliation: created, deleted (revocation with strict data preservation).
8. Installation repositories reconciliation: added, removed (revocation with strict data preservation).
9. Opt-in PR review automation: draft PR skip, stale head SHA abandonment, consolidated comment with event='COMMENT'.
10. Issues event synchronization: idempotent upsert, read-only safety guarantees.
11. Operational monitoring and repository automation settings management APIs.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.database import get_db
from app.main import app
from app.models.github_installation import GitHubInstallation
from app.models.repository import Repository, SyncStatus
from app.models.sync_job import SyncJob, SyncJobStatus
from app.models.task import GitHubIssue
from app.models.user import User
from app.models.webhook_event import GitHubWebhookEvent, WebhookEventStatus
from app.repositories.webhook_event_repository import WebhookEventRepository
from app.services.webhook_handlers import (
    InstallationEventHandler,
    InstallationRepositoriesEventHandler,
    IssuesEventHandler,
    PullRequestEventHandler,
    PushEventHandler,
    RetryableWebhookError,
    WebhookEventDispatcher,
)
from app.services.webhook_worker import (
    process_single_webhook_event,
    webhook_worker_run_once,
)


@pytest.fixture
def auth_user(db_session: Session) -> User:
    """Create an authorized test user."""
    uid = uuid.uuid4().hex[:8]
    user = User(
        id=uuid.uuid4(),
        github_id=f"gh_test_user_182_{uid}",
        login=f"testdev182_{uid}",
        email=f"dev182_{uid}@example.com",
    )
    db_session.add(user)
    db_session.commit()
    return user


@pytest.fixture
def test_installation(db_session: Session, auth_user: User) -> GitHubInstallation:
    """Create a linked GitHub installation."""
    inst = GitHubInstallation(
        id=uuid.uuid4(),
        user_id=auth_user.id,
        installation_id=f"inst_182_{uuid.uuid4().hex[:8]}",
        account_login=auth_user.login,
        permissions={"contents": "read", "pull_requests": "write"},
    )
    db_session.add(inst)
    db_session.commit()
    return inst


@pytest.fixture
def automation_auth_headers(auth_user: User, monkeypatch: pytest.MonkeyPatch) -> dict[str, str]:
    monkeypatch.setenv("JWT_SECRET", "test-jwt-secret-182-secure-random-key")
    get_settings.cache_clear()
    from app.core.security import create_access_token
    token, _ = create_access_token(str(auth_user.id))
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def test_repo(db_session: Session, auth_user: User, test_installation: GitHubInstallation) -> Repository:
    """Create a test repository linked to the installation."""
    repo = Repository(
        id=uuid.uuid4(),
        user_id=auth_user.id,
        installation_id=test_installation.id,
        github_repo_id=str(uuid.uuid4().int)[:10],
        owner=auth_user.login,
        name=f"test-repo-{uuid.uuid4().hex[:6]}",
        default_branch="main",
        sync_status=SyncStatus.SYNCED,
        auto_sync_enabled=True,
        pr_review_enabled=False,
        pr_review_drafts=False,
        last_indexed_commit_sha="commit_sha_initial",
    )
    db_session.add(repo)
    db_session.commit()
    return repo


def _sign_payload(body: bytes, secret: str = "test-webhook-secret-182") -> str:
    """Generate X-Hub-Signature-256 for a given payload."""
    return "sha256=" + hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()


# ── 1. Webhook Endpoint Security & Persistence Tests ─────────────────────────


class TestWebhookEndpointSecurity:
    """Validate HTTP endpoint signature validation, size limit, deduplication, and 202 acceptance."""

    def test_webhook_fails_closed_when_secret_unset(self, client: TestClient, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("GITHUB_WEBHOOK_SECRET", "")
        get_settings.cache_clear()

        res = client.post(
            "/api/v1/github/webhook",
            headers={"X-GitHub-Event": "ping"},
            content=b'{"zen": "keep it simple"}',
        )
        assert res.status_code == 503
        assert res.json()["error"]["code"] == "SERVICE_UNAVAILABLE"

    def test_webhook_rejects_missing_and_invalid_signatures(self, client: TestClient, monkeypatch: pytest.MonkeyPatch):
        secret = "test-webhook-secret-182"
        monkeypatch.setenv("GITHUB_WEBHOOK_SECRET", secret)
        get_settings.cache_clear()

        payload = b'{"zen": "hello"}'

        # Missing signature
        res_missing = client.post("/api/v1/github/webhook", content=payload, headers={"X-GitHub-Event": "ping"})
        assert res_missing.status_code == 401
        assert res_missing.json()["error"]["code"] == "UNAUTHORIZED"

        # Forged signature
        res_bad = client.post(
            "/api/v1/github/webhook",
            content=payload,
            headers={"X-GitHub-Event": "ping", "X-Hub-Signature-256": "sha256=invalidhex000000"},
        )
        assert res_bad.status_code == 401

    def test_webhook_rejects_oversized_payload(self, client: TestClient, monkeypatch: pytest.MonkeyPatch):
        secret = "test-webhook-secret-182"
        monkeypatch.setenv("GITHUB_WEBHOOK_SECRET", secret)
        get_settings.cache_clear()

        oversized = b"a" * (5 * 1024 * 1024 + 1)
        res = client.post(
            "/api/v1/github/webhook",
            content=oversized,
            headers={"X-GitHub-Event": "ping"},
        )
        assert res.status_code == 413
        assert res.json()["error"]["code"] == "BAD_REQUEST"

    def test_webhook_rejects_malformed_delivery_id(self, client: TestClient, monkeypatch: pytest.MonkeyPatch):
        secret = "test-webhook-secret-182"
        monkeypatch.setenv("GITHUB_WEBHOOK_SECRET", secret)
        get_settings.cache_clear()

        payload = b'{"zen": "test"}'
        sig = _sign_payload(payload, secret)

        res = client.post(
            "/api/v1/github/webhook",
            content=payload,
            headers={
                "X-GitHub-Event": "ping",
                "X-Hub-Signature-256": sig,
                "X-GitHub-Delivery": "delivery'; DROP TABLE users; --",
            },
        )
        assert res.status_code == 400
        assert res.json()["error"]["code"] == "BAD_REQUEST"

    def test_webhook_ping_pong(self, client: TestClient, monkeypatch: pytest.MonkeyPatch):
        secret = "test-webhook-secret-182"
        monkeypatch.setenv("GITHUB_WEBHOOK_SECRET", secret)
        get_settings.cache_clear()

        payload = b'{"zen": "responsive"}'
        sig = _sign_payload(payload, secret)

        res = client.post(
            "/api/v1/github/webhook",
            content=payload,
            headers={"X-GitHub-Event": "ping", "X-Hub-Signature-256": sig},
        )
        assert res.status_code == 200
        assert res.json() == {"status": "pong"}

    def test_webhook_supported_event_persisted_with_202(
        self, client: TestClient, db_session: Session, monkeypatch: pytest.MonkeyPatch
    ):
        secret = "test-webhook-secret-182"
        monkeypatch.setenv("GITHUB_WEBHOOK_SECRET", secret)
        get_settings.cache_clear()

        delivery_id = f"deliv_{uuid.uuid4().hex[:12]}"
        payload_dict = {
            "action": "opened",
            "issue": {"number": 101, "title": "Test bug", "state": "open"},
            "repository": {"id": 998877},
        }
        body = json.dumps(payload_dict).encode("utf-8")
        sig = _sign_payload(body, secret)

        res = client.post(
            "/api/v1/github/webhook",
            content=body,
            headers={
                "X-GitHub-Event": "issues",
                "X-GitHub-Delivery": delivery_id,
                "X-Hub-Signature-256": sig,
                "Content-Type": "application/json",
            },
        )
        assert res.status_code == 202
        data = res.json()
        assert data["status"] == "accepted"
        assert data["delivery_id"] == delivery_id
        assert data["event"] == "issues"
        assert data["action"] == "opened"
        assert "event_id" in data

        # Verify durable DB persistence
        event_repo = WebhookEventRepository(db_session)
        persisted = event_repo.get_by_delivery_id(delivery_id)
        assert persisted is not None
        assert persisted.status == WebhookEventStatus.PENDING
        assert persisted.event_type == "issues"
        assert persisted.action == "opened"
        assert persisted.attempts == 0

    def test_webhook_deduplication_via_redis_and_db(
        self, client: TestClient, db_session: Session, monkeypatch: pytest.MonkeyPatch
    ):
        secret = "test-webhook-secret-182"
        monkeypatch.setenv("GITHUB_WEBHOOK_SECRET", secret)
        get_settings.cache_clear()

        delivery_id = f"deliv_dedup_{uuid.uuid4().hex[:12]}"
        body = json.dumps({"action": "opened", "issue": {"number": 1}}).encode("utf-8")
        sig = _sign_payload(body, secret)
        headers = {
            "X-GitHub-Event": "issues",
            "X-GitHub-Delivery": delivery_id,
            "X-Hub-Signature-256": sig,
            "Content-Type": "application/json",
        }

        # 1. First delivery accepted (HTTP 202)
        res1 = client.post("/api/v1/github/webhook", content=body, headers=headers)
        assert res1.status_code == 202
        assert res1.json()["status"] == "accepted"

        # 2. Second delivery with identical delivery ID ignored (HTTP 200)
        res2 = client.post("/api/v1/github/webhook", content=body, headers=headers)
        assert res2.status_code == 200
        assert res2.json()["status"] == "duplicate_delivery_ignored"
        assert res2.json()["delivery_id"] == delivery_id


# ── 2. Event Repository & Queue Mechanics Tests ──────────────────────────────


class TestWebhookEventRepositoryMechanics:
    """Test atomic claims, lease expiration, retry backoff, and dead-letter queue."""

    def test_atomic_claim_and_lease(self, db_session: Session):
        repo = WebhookEventRepository(db_session)
        ev, created = repo.create_event(
            delivery_id=f"claim_test_{uuid.uuid4().hex[:8]}",
            event_type="push",
            payload={"ref": "refs/heads/main"},
        )
        assert created is True
        assert ev.status == WebhookEventStatus.PENDING

        # Claim the event
        claimed = repo.claim_next_event(lease_seconds=60)
        assert claimed is not None
        assert claimed.id == ev.id
        assert claimed.status == WebhookEventStatus.PROCESSING
        assert claimed.claimed_at is not None
        assert claimed.lease_expires_at is not None
        assert claimed.attempts == 1

        # Second concurrent claim should return None (no other pending event)
        claimed_second = repo.claim_next_event(lease_seconds=60)
        assert claimed_second is None

    def test_lease_expiration_allows_reclaim(self, db_session: Session):
        repo = WebhookEventRepository(db_session)
        ev, _ = repo.create_event(
            delivery_id=f"lease_exp_{uuid.uuid4().hex[:8]}",
            event_type="push",
            payload={"ref": "refs/heads/main"},
        )
        claimed = repo.claim_next_event(lease_seconds=10)
        assert claimed is not None

        # Simulate lease expiration in the past
        claimed.lease_expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        db_session.commit()

        # Next claim picks up the expired event
        reclaimed = repo.claim_next_event(lease_seconds=60)
        assert reclaimed is not None
        assert reclaimed.id == ev.id
        assert reclaimed.attempts == 2

    def test_mark_succeeded(self, db_session: Session):
        repo = WebhookEventRepository(db_session)
        ev, _ = repo.create_event(
            delivery_id=f"succ_{uuid.uuid4().hex[:8]}",
            event_type="push",
            payload={},
        )
        repo.claim_next_event()
        succ = repo.mark_succeeded(ev.id)
        assert succ.status == WebhookEventStatus.SUCCEEDED
        assert succ.processed_at is not None

    def test_mark_retry_with_exponential_backoff(self, db_session: Session):
        repo = WebhookEventRepository(db_session)
        ev, _ = repo.create_event(
            delivery_id=f"retry_{uuid.uuid4().hex[:8]}",
            event_type="push",
            payload={},
        )
        repo.claim_next_event()
        retried = repo.mark_retry(ev.id, error_message="Network glitch", base_backoff_seconds=2)
        assert retried.status == WebhookEventStatus.RETRY
        assert retried.last_error == "Network glitch"
        # available_at should be in the future
        now_utc = datetime.now(timezone.utc)
        avail = retried.available_at
        if avail.tzinfo is None:
            avail = avail.replace(tzinfo=timezone.utc)
        assert avail > now_utc

    def test_mark_dead_letter_and_replay(self, db_session: Session):
        repo = WebhookEventRepository(db_session)
        ev, _ = repo.create_event(
            delivery_id=f"dlq_{uuid.uuid4().hex[:8]}",
            event_type="push",
            payload={},
        )
        dlq = repo.mark_dead_letter(ev.id, error_message="Permanent schema error")
        assert dlq.status == WebhookEventStatus.DEAD_LETTER
        assert dlq.last_error == "Permanent schema error"

        # Replay event
        replayed = repo.replay_event(ev.id)
        assert replayed.status == WebhookEventStatus.PENDING
        assert replayed.attempts == 0
        assert replayed.last_error is None
        assert replayed.replay_count == 1

        # Cannot replay actively PROCESSING event
        repo.claim_next_event()
        with pytest.raises(ValueError, match="is actively PROCESSING"):
            repo.replay_event(ev.id)


# ── 3. Push Event Synchronization Tests ──────────────────────────────────────


class TestPushEventHandler:
    """Validate push branch filtering, deleted branch skip, auto-sync, duplicate SHA, and concurrency."""

    @pytest.mark.asyncio
    async def test_push_to_default_branch_executes_sync(self, db_session: Session, test_repo: Repository):
        handler = PushEventHandler()
        new_commit = "commit_sha_new_12345"
        event = GitHubWebhookEvent(
            id=uuid.uuid4(),
            delivery_id="push_deliv_1",
            event_type="push",
            available_at=datetime.now(timezone.utc),
            github_repo_id=test_repo.github_repo_id,
            payload={
                "ref": f"refs/heads/{test_repo.default_branch}",
                "after": new_commit,
                "repository": {"id": int(test_repo.github_repo_id)},
            },
        )
        db_session.add(event)
        db_session.commit()

        mock_gh = AsyncMock()
        with patch("app.services.sync_worker.process_sync_job", new_callable=AsyncMock) as mock_sync:
            result = await handler.handle(event, db_session, github_service=mock_gh)

        assert result["status"] == "push_synced"
        assert result["commit_sha"] == new_commit
        mock_sync.assert_awaited_once()

        db_session.refresh(test_repo)
        assert test_repo.last_indexed_commit_sha == new_commit
        assert test_repo.sync_status == SyncStatus.SYNCED
        assert test_repo.last_synced_at is not None

    @pytest.mark.asyncio
    async def test_push_to_non_default_branch_ignored(self, db_session: Session, test_repo: Repository):
        handler = PushEventHandler()
        event = GitHubWebhookEvent(
            id=uuid.uuid4(),
            delivery_id="push_deliv_feat",
            event_type="push",
            available_at=datetime.now(timezone.utc),
            github_repo_id=test_repo.github_repo_id,
            payload={
                "ref": "refs/heads/feature-branch",
                "after": "sha_feat_branch",
                "repository": {"id": int(test_repo.github_repo_id)},
            },
        )
        db_session.add(event)
        db_session.commit()

        result = await handler.handle(event, db_session)
        assert result["status"] == "ignored_non_default_branch"

    @pytest.mark.asyncio
    async def test_push_deleted_branch_ignored(self, db_session: Session, test_repo: Repository):
        handler = PushEventHandler()
        event = GitHubWebhookEvent(
            id=uuid.uuid4(),
            delivery_id="push_deliv_del",
            event_type="push",
            available_at=datetime.now(timezone.utc),
            github_repo_id=test_repo.github_repo_id,
            payload={
                "ref": "refs/heads/main",
                "deleted": True,
                "after": "0000000000000000000000000000000000000000",
                "repository": {"id": int(test_repo.github_repo_id)},
            },
        )
        db_session.add(event)
        db_session.commit()

        result = await handler.handle(event, db_session)
        assert result["status"] == "ignored_deleted_branch"

    @pytest.mark.asyncio
    async def test_push_auto_sync_disabled_ignored(self, db_session: Session, test_repo: Repository):
        test_repo.auto_sync_enabled = False
        db_session.commit()

        handler = PushEventHandler()
        event = GitHubWebhookEvent(
            id=uuid.uuid4(),
            delivery_id="push_deliv_disabled",
            event_type="push",
            available_at=datetime.now(timezone.utc),
            github_repo_id=test_repo.github_repo_id,
            payload={
                "ref": "refs/heads/main",
                "after": "new_sha_unwanted",
                "repository": {"id": int(test_repo.github_repo_id)},
            },
        )
        db_session.add(event)
        db_session.commit()

        result = await handler.handle(event, db_session)
        assert result["status"] == "ignored_auto_sync_disabled"

    @pytest.mark.asyncio
    async def test_push_already_indexed_sha_ignored(self, db_session: Session, test_repo: Repository):
        handler = PushEventHandler()
        event = GitHubWebhookEvent(
            id=uuid.uuid4(),
            delivery_id="push_deliv_dup",
            event_type="push",
            available_at=datetime.now(timezone.utc),
            github_repo_id=test_repo.github_repo_id,
            payload={
                "ref": "refs/heads/main",
                "after": test_repo.last_indexed_commit_sha,
                "repository": {"id": int(test_repo.github_repo_id)},
            },
        )
        db_session.add(event)
        db_session.commit()

        result = await handler.handle(event, db_session)
        assert result["status"] == "ignored_already_indexed"

    @pytest.mark.asyncio
    async def test_push_concurrency_raises_retryable_when_syncing(
        self, db_session: Session, test_repo: Repository
    ):
        test_repo.sync_status = SyncStatus.SYNCING
        db_session.commit()

        handler = PushEventHandler()
        event = GitHubWebhookEvent(
            id=uuid.uuid4(),
            delivery_id="push_deliv_concurrent",
            event_type="push",
            available_at=datetime.now(timezone.utc),
            github_repo_id=test_repo.github_repo_id,
            payload={
                "ref": "refs/heads/main",
                "after": "sha_brand_new",
                "repository": {"id": int(test_repo.github_repo_id)},
            },
        )
        db_session.add(event)
        db_session.commit()

        with pytest.raises(RetryableWebhookError, match="currently syncing"):
            await handler.handle(event, db_session)


# ── 4. Installation Reconciliation Tests ─────────────────────────────────────


class TestInstallationReconciliation:
    """Validate installation created, deleted (revocation with strict data preservation)."""

    @pytest.mark.asyncio
    async def test_installation_created_upserts(self, db_session: Session, auth_user: User):
        handler = InstallationEventHandler()
        event = GitHubWebhookEvent(
            id=uuid.uuid4(),
            delivery_id="inst_create_deliv",
            event_type="installation",
            action="created",
            available_at=datetime.now(timezone.utc),
            payload={
                "action": "created",
                "installation": {
                    "id": 554433,
                    "account": {"login": auth_user.login},
                    "permissions": {"issues": "write"},
                },
            },
        )
        result = await handler.handle(event, db_session)
        assert result["status"] == "installation_created"

        inst = db_session.scalar(
            select(GitHubInstallation).where(GitHubInstallation.installation_id == "554433")
        )
        assert inst is not None
        assert inst.user_id == auth_user.id
        assert inst.account_login == auth_user.login

    @pytest.mark.asyncio
    async def test_installation_deleted_revokes_and_preserves_data(
        self, db_session: Session, test_repo: Repository, test_installation: GitHubInstallation
    ):
        # Create an active sync job for the repo
        job = SyncJob(
            id=uuid.uuid4(),
            repository_id=test_repo.id,
            user_id=test_repo.user_id,
            status=SyncJobStatus.RUNNING,
        )
        db_session.add(job)
        db_session.commit()

        handler = InstallationEventHandler()
        event = GitHubWebhookEvent(
            id=uuid.uuid4(),
            delivery_id="inst_del_deliv",
            event_type="installation",
            action="deleted",
            available_at=datetime.now(timezone.utc),
            payload={
                "action": "deleted",
                "installation": {
                    "id": test_installation.installation_id,
                    "account": {"login": test_installation.account_login},
                },
            },
        )
        result = await handler.handle(event, db_session)
        assert result["status"] == "installation_revoked"
        assert result["repos_affected"] == 1

        db_session.refresh(test_repo)
        assert test_repo.sync_status == SyncStatus.FAILED
        db_session.refresh(job)
        assert job.status == SyncJobStatus.FAILED

        # Verify historical repository record is strictly preserved
        persisted_repo = db_session.get(Repository, test_repo.id)
        assert persisted_repo is not None


class TestInstallationRepositoriesEventHandler:
    """Validate repositories added and removed from installation."""

    @pytest.mark.asyncio
    async def test_repositories_added(self, db_session: Session, test_installation: GitHubInstallation):
        handler = InstallationRepositoriesEventHandler()
        event = GitHubWebhookEvent(
            id=uuid.uuid4(),
            delivery_id="inst_repos_add_deliv",
            event_type="installation_repositories",
            action="added",
            available_at=datetime.now(timezone.utc),
            payload={
                "action": "added",
                "installation": {"id": test_installation.installation_id},
                "repositories_added": [
                    {
                        "id": 112233,
                        "name": "brand-new-repo",
                        "full_name": f"{test_installation.account_login}/brand-new-repo",
                        "default_branch": "main",
                    }
                ],
            },
        )
        result = await handler.handle(event, db_session)
        assert result["status"] == "repositories_added"
        assert result["added_count"] == 1

        new_repo = db_session.scalar(
            select(Repository).where(Repository.github_repo_id == "112233")
        )
        assert new_repo is not None
        assert new_repo.name == "brand-new-repo"
        assert new_repo.auto_sync_enabled is True

    @pytest.mark.asyncio
    async def test_repositories_removed(
        self, db_session: Session, test_repo: Repository, test_installation: GitHubInstallation
    ):
        handler = InstallationRepositoriesEventHandler()
        event = GitHubWebhookEvent(
            id=uuid.uuid4(),
            delivery_id="inst_repos_rem_deliv",
            event_type="installation_repositories",
            action="removed",
            available_at=datetime.now(timezone.utc),
            payload={
                "action": "removed",
                "installation": {"id": test_installation.installation_id},
                "repositories_removed": [
                    {"id": int(test_repo.github_repo_id), "name": test_repo.name}
                ],
            },
        )
        result = await handler.handle(event, db_session)
        assert result["status"] == "repositories_removed"
        assert result["removed_count"] == 1

        db_session.refresh(test_repo)
        assert test_repo.sync_status == SyncStatus.FAILED
        # Repository row strictly preserved
        assert db_session.get(Repository, test_repo.id) is not None


# ── 5. Pull Request Code Review Automation Tests ─────────────────────────────


class TestPullRequestReviewAutomation:
    """Validate PR review opt-in, draft handling, stale head SHA abandonment, and review publishing."""

    @pytest.mark.asyncio
    async def test_pr_review_ignored_when_disabled(self, db_session: Session, test_repo: Repository):
        test_repo.pr_review_enabled = False
        db_session.commit()

        handler = PullRequestEventHandler()
        event = GitHubWebhookEvent(
            id=uuid.uuid4(),
            delivery_id="pr_rev_dis",
            event_type="pull_request",
            available_at=datetime.now(timezone.utc),
            action="opened",
            payload={
                "action": "opened",
                "pull_request": {"number": 12, "draft": False, "head": {"sha": "sha_pr_12"}},
                "repository": {"id": int(test_repo.github_repo_id)},
            },
        )
        result = await handler.handle(event, db_session)
        assert result["status"] == "ignored_pr_review_disabled"

    @pytest.mark.asyncio
    async def test_pr_review_draft_ignored_by_default(self, db_session: Session, test_repo: Repository):
        test_repo.pr_review_enabled = True
        test_repo.pr_review_drafts = False
        db_session.commit()

        handler = PullRequestEventHandler()
        event = GitHubWebhookEvent(
            id=uuid.uuid4(),
            delivery_id="pr_rev_draft",
            event_type="pull_request",
            available_at=datetime.now(timezone.utc),
            action="opened",
            payload={
                "action": "opened",
                "pull_request": {"number": 13, "draft": True, "head": {"sha": "sha_pr_13"}},
                "repository": {"id": int(test_repo.github_repo_id)},
            },
        )
        result = await handler.handle(event, db_session)
        assert result["status"] == "ignored_draft_pr"

    @pytest.mark.asyncio
    async def test_pr_review_abandoned_when_stale_head(self, db_session: Session, test_repo: Repository):
        test_repo.pr_review_enabled = True
        db_session.commit()

        mock_gh = AsyncMock()
        # GitHub returns newer head commit sha
        mock_pr_info = MagicMock()
        mock_pr_info.state = "open"
        mock_pr_info.head_commit_sha = "sha_newer_commit_999"
        mock_gh.get_pull_request_detail.return_value = mock_pr_info

        handler = PullRequestEventHandler()
        event = GitHubWebhookEvent(
            id=uuid.uuid4(),
            delivery_id="pr_stale_deliv",
            event_type="pull_request",
            available_at=datetime.now(timezone.utc),
            action="synchronize",
            payload={
                "action": "synchronize",
                "pull_request": {"number": 14, "draft": False, "head": {"sha": "sha_old_commit_111"}},
                "repository": {"id": int(test_repo.github_repo_id)},
            },
        )
        result = await handler.handle(event, db_session, github_service=mock_gh)
        assert result["status"] == "review_abandoned_stale_head"
        assert result["current_head"] == "sha_newer_commit_999"
        assert result["reviewed_head"] == "sha_old_commit_111"

    @pytest.mark.asyncio
    async def test_pr_review_publishes_consolidated_comment(
        self, db_session: Session, test_repo: Repository
    ):
        test_repo.pr_review_enabled = True
        db_session.commit()

        head_sha = "sha_approved_head_123"
        mock_gh = AsyncMock()
        mock_pr_info = MagicMock()
        mock_pr_info.state = "open"
        mock_pr_info.head_commit_sha = head_sha
        mock_gh.get_pull_request_detail.return_value = mock_pr_info
        mock_gh.create_pull_request_review = AsyncMock(return_value={"id": 888})

        handler = PullRequestEventHandler()
        event = GitHubWebhookEvent(
            id=uuid.uuid4(),
            delivery_id="pr_pub_deliv",
            event_type="pull_request",
            available_at=datetime.now(timezone.utc),
            action="opened",
            payload={
                "action": "opened",
                "pull_request": {"number": 15, "draft": False, "head": {"sha": head_sha}},
                "repository": {"id": int(test_repo.github_repo_id)},
            },
        )
        result = await handler.handle(event, db_session, github_service=mock_gh)
        assert result["status"] == "review_published"
        mock_gh.create_pull_request_review.assert_awaited_once()
        kwargs = mock_gh.create_pull_request_review.await_args.kwargs
        assert kwargs["event"] == "COMMENT"
        assert kwargs["pr_number"] == 15
        assert "Automated Code Review" in kwargs["body"]
        assert "Pull Request #15" in kwargs["body"]


# ── 6. Issues Event Synchronization Tests ────────────────────────────────────


class TestIssuesEventHandler:
    """Validate idempotent issue creation, edit updates, and read-only safety."""

    @pytest.mark.asyncio
    async def test_issues_upsert_creates_and_updates(self, db_session: Session, test_repo: Repository):
        handler = IssuesEventHandler()
        # 1. Create issue
        ev_open = GitHubWebhookEvent(
            id=uuid.uuid4(),
            delivery_id="issue_deliv_open",
            event_type="issues",
            available_at=datetime.now(timezone.utc),
            action="opened",
            payload={
                "action": "opened",
                "issue": {
                    "number": 42,
                    "title": "Bug in login flow",
                    "body": "Steps to reproduce...",
                    "state": "open",
                    "html_url": "https://github.com/testdev182/test-repo/issues/42",
                    "user": {"login": "reporter1"},
                    "labels": [{"name": "bug"}, {"name": "auth"}],
                },
                "repository": {"id": int(test_repo.github_repo_id)},
            },
        )
        res_open = await handler.handle(ev_open, db_session)
        assert res_open["status"] == "issue_upserted"
        assert res_open["issue_number"] == 42

        issue = db_session.scalar(
            select(GitHubIssue).where(
                GitHubIssue.repository_id == test_repo.id,
                GitHubIssue.issue_number == 42,
            )
        )
        assert issue is not None
        assert issue.title == "Bug in login flow"
        assert issue.state == "open"
        assert issue.labels == ["bug", "auth"]
        assert issue.author == "reporter1"

        # 2. Update issue (action="edited")
        ev_edit = GitHubWebhookEvent(
            id=uuid.uuid4(),
            delivery_id="issue_deliv_edit",
            event_type="issues",
            available_at=datetime.now(timezone.utc),
            action="edited",
            payload={
                "action": "edited",
                "issue": {
                    "number": 42,
                    "title": "Bug in login flow (Updated)",
                    "body": "Updated description",
                    "state": "closed",
                    "html_url": "https://github.com/testdev182/test-repo/issues/42",
                    "user": {"login": "reporter1"},
                    "labels": [{"name": "bug"}, {"name": "resolved"}],
                },
                "repository": {"id": int(test_repo.github_repo_id)},
            },
        )
        res_edit = await handler.handle(ev_edit, db_session)
        assert res_edit["status"] == "issue_upserted"

        db_session.refresh(issue)
        assert issue.title == "Bug in login flow (Updated)"
        assert issue.state == "closed"
        assert issue.labels == ["bug", "resolved"]


# ── 7. Operational Monitoring & Replay API Tests ─────────────────────────────


class TestWebhookOperationalApi:
    """Validate administrative event queries, detail inspection, and safe replay."""

    def test_list_and_filter_webhook_events(
        self, client: TestClient, db_session: Session, auth_user: User, automation_auth_headers: dict[str, str], test_repo: Repository, monkeypatch: pytest.MonkeyPatch
    ):
        monkeypatch.setattr("app.api.v1.github._request_user_id", lambda req: auth_user.id)

        repo = WebhookEventRepository(db_session)
        ev1, _ = repo.create_event(
            delivery_id="list_ev_1",
            event_type="push",
            repository_id=test_repo.id,
            payload={},
        )
        repo.mark_succeeded(ev1.id)

        ev2, _ = repo.create_event(
            delivery_id="list_ev_2",
            event_type="pull_request",
            repository_id=test_repo.id,
            payload={},
        )
        repo.mark_dead_letter(ev2.id, "Syntax error")

        # Query all
        res = client.get("/api/v1/github/events", headers=automation_auth_headers)
        assert res.status_code == 200
        data = res.json()
        assert data["total"] >= 2

        # Filter by status
        res_dlq = client.get("/api/v1/github/events?status=DEAD_LETTER", headers=automation_auth_headers)
        assert res_dlq.status_code == 200
        dlq_items = res_dlq.json()["items"]
        assert any(item["delivery_id"] == "list_ev_2" for item in dlq_items)

        # Filter by event_type
        res_push = client.get("/api/v1/github/events?event_type=push", headers=automation_auth_headers)
        assert res_push.status_code == 200
        push_items = res_push.json()["items"]
        assert any(item["delivery_id"] == "list_ev_1" for item in push_items)

    def test_get_event_detail(
        self, client: TestClient, db_session: Session, auth_user: User, automation_auth_headers: dict[str, str], test_repo: Repository, monkeypatch: pytest.MonkeyPatch
    ):
        monkeypatch.setattr("app.api.v1.github._request_user_id", lambda req: auth_user.id)

        repo = WebhookEventRepository(db_session)
        ev, _ = repo.create_event(
            delivery_id="detail_ev_1",
            event_type="issues",
            repository_id=test_repo.id,
            payload={"issue": {"number": 99}},
        )

        res = client.get(f"/api/v1/github/events/{ev.id}", headers=automation_auth_headers)
        assert res.status_code == 200
        data = res.json()
        assert data["id"] == str(ev.id)
        assert data["delivery_id"] == "detail_ev_1"
        assert data["event_type"] == "issues"

    def test_replay_dead_letter_event(
        self, client: TestClient, db_session: Session, auth_user: User, automation_auth_headers: dict[str, str], test_repo: Repository, monkeypatch: pytest.MonkeyPatch
    ):
        monkeypatch.setattr("app.api.v1.github._request_user_id", lambda req: auth_user.id)

        repo = WebhookEventRepository(db_session)
        ev, _ = repo.create_event(
            delivery_id="replay_api_ev",
            event_type="push",
            repository_id=test_repo.id,
            payload={},
        )
        repo.mark_dead_letter(ev.id, "Fatal network disconnect")

        res = client.post(f"/api/v1/github/events/{ev.id}/replay", headers=automation_auth_headers)
        assert res.status_code == 200
        data = res.json()
        assert data["status"] == "replayed"
        assert data["replay_count"] == 1

        db_session.refresh(ev)
        assert ev.status == WebhookEventStatus.PENDING
        assert ev.attempts == 0
        assert ev.last_error is None

    def test_get_and_patch_repository_automation_settings(
        self, client: TestClient, db_session: Session, auth_user: User, automation_auth_headers: dict[str, str], test_repo: Repository, monkeypatch: pytest.MonkeyPatch
    ):
        monkeypatch.setattr("app.api.v1.github._request_user_id", lambda req: auth_user.id)

        # 1. Get settings
        res = client.get(f"/api/v1/github/repositories/{test_repo.github_repo_id}/automation", headers=automation_auth_headers)
        assert res.status_code == 200
        data = res.json()
        assert data["auto_sync_enabled"] is True
        assert data["pr_review_enabled"] is False

        # 2. Patch settings
        res_patch = client.patch(
            f"/api/v1/github/repositories/{test_repo.github_repo_id}/automation",
            json={"pr_review_enabled": True, "pr_review_drafts": True, "auto_sync_enabled": False},
            headers=automation_auth_headers,
        )
        assert res_patch.status_code == 200
        patched_data = res_patch.json()
        assert patched_data["pr_review_enabled"] is True
        assert patched_data["pr_review_drafts"] is True
        assert patched_data["auto_sync_enabled"] is False

        db_session.refresh(test_repo)
        assert test_repo.pr_review_enabled is True
        assert test_repo.pr_review_drafts is True
        assert test_repo.auto_sync_enabled is False
