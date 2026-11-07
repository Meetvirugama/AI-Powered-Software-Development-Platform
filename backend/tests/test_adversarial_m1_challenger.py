"""Adversarial and Stress-Testing Suite for Milestone M1.

Empirically challenges:
1. Approval Invalidation on Re-Plan (re-planning approved task blocks execute/tests/repair without re-approval)
2. Task State Machine Invariants (illegal jumps: PENDING_APPROVAL -> EXECUTING, CREATED -> PUBLISHING, terminal states)
3. Post-Verification Diff Immutability (workspace tampering blocks PR publication / branch push with HTTP 409 VERIFICATION_FAILED)
4. Missing / Empty Verification Diff Hash (blocks publication with HTTP 409 VERIFICATION_FAILED)
5. Multi-Tenant Task, Workspace, and Repository Isolation (cross-tenant access yields HTTP 404 / 403)
6. GitHub Installation Ownership Verification (cross-tenant hijacking via query param or direct repository upsert blocked)
7. GitHub Webhook Security (spoofed signatures, missing headers, whitespace secrets fail-closed, duplicate delivery deduplication, oversized payloads)
"""

from __future__ import annotations

import hashlib
import hmac
import json
import uuid
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool
from starlette.requests import Request

from app.api.v1.dependencies import get_owned_repository, get_owned_task
from app.core.config import get_settings
from app.core.database import Base, get_db
from app.core.errors import APIError, ErrorCode
from app.core.security import create_access_token
from app.main import app
from app.models.github_installation import GitHubInstallation
from app.models.repository import Repository, SyncStatus
from app.models.task import (
    Task,
    TaskApproval,
    TaskPlan,
    TaskPlanStatus,
    TaskSourceType,
    TaskStatus,
    VerificationResult as TaskVerificationResult,
    VerificationStatus,
    Workspace,
    WorkspaceStatus,
)
from app.models.user import User
from app.repositories.github_installation_repository import GitHubInstallationRepository
from app.repositories.task_repository import TaskNotFoundError, TaskRepository
from app.schemas.task import can_transition, VALID_TASK_TRANSITIONS
from app.services.task_execution_orchestrator import TaskExecutionOrchestrator
from sandbox.workspace_manager import WorkspaceManager, WorkspaceMetadata


# ---------------------------------------------------------------------------
# In-Memory SQLite Test Fixtures for High-Speed & Isolated Execution
# ---------------------------------------------------------------------------

@pytest.fixture()
def mem_db() -> Session:
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(engine, "connect")
    def _register_sqlite_hooks(dbapi_con, _):
        cursor = dbapi_con.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()
        dbapi_con.create_function("to_tsvector", 2, lambda cfg, txt: txt or "", deterministic=True)

    for table in Base.metadata.sorted_tables:
        if table.name == "code_chunks":
            continue
        table.create(bind=engine, checkfirst=True)

    TestingSession = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = TestingSession()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


class DummyRedisMemory:
    def __init__(self):
        self.store = {}

    def get(self, k: str):
        return self.store.get(k)

    def set(self, k: str, v: str, *args, **kwargs):
        nx = kwargs.get("nx", False)
        if nx and k in self.store:
            return False
        self.store[k] = str(v)
        return True

    def exists(self, k: str) -> int:
        return 1 if k in self.store else 0

    def delete(self, k: str) -> int:
        return 1 if self.store.pop(k, None) is not None else 0

    def pipeline(self):
        class _Pipe:
            def incr(self, _):
                pass
            def expire(self, *args):
                pass
            def execute(self):
                return [1, True]
        return _Pipe()


@pytest.fixture()
def client_harness(mem_db: Session, monkeypatch, tmp_path: Path):
    dummy_redis = DummyRedisMemory()
    monkeypatch.setenv("JWT_SECRET", "adversarial-jwt-secret-m1-secure")
    monkeypatch.setenv("GITHUB_WEBHOOK_SECRET", "adversarial-webhook-secret-token")
    get_settings.cache_clear()

    async def _fake_get_redis_async():
        return dummy_redis

    monkeypatch.setattr("app.core.auth.get_redis", lambda: dummy_redis)
    monkeypatch.setattr("app.core.redis.get_redis", lambda: dummy_redis)
    monkeypatch.setattr("app.core.redis.get_redis_async", _fake_get_redis_async)
    monkeypatch.setattr("app.api.v1.github.get_redis_async", _fake_get_redis_async)

    ws_root = tmp_path / "workspaces"
    ws_root.mkdir(parents=True, exist_ok=True)
    wm = WorkspaceManager(base_workspaces_dir=ws_root)
    orchestrator = TaskExecutionOrchestrator(workspace_manager=wm)

    prev_orch = getattr(app.state, "task_execution_orchestrator", None)
    app.state.task_execution_orchestrator = orchestrator

    app.dependency_overrides[get_db] = lambda: mem_db
    try:
        with TestClient(app, raise_server_exceptions=False) as c:
            yield {
                "client": c,
                "db": mem_db,
                "orchestrator": orchestrator,
                "workspace_manager": wm,
                "redis": dummy_redis,
                "ws_root": ws_root,
            }
    finally:
        app.dependency_overrides.clear()
        app.state.task_execution_orchestrator = prev_orch
        get_settings.cache_clear()


def _make_user(db: Session, login: str) -> User:
    user = User(
        id=uuid.uuid4(),
        github_id=f"gh_{uuid.uuid4().hex[:8]}",
        login=login,
        email=f"{login}@example.org",
    )
    db.add(user)
    db.flush()
    return user


def _make_repo(db: Session, user: User, name: str = "target-repo") -> Repository:
    inst = GitHubInstallation(
        id=uuid.uuid4(),
        user_id=user.id,
        installation_id=f"inst_{uuid.uuid4().hex[:8]}",
        account_login=user.login,
        permissions={"issues": "write", "contents": "write"},
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
    return repo


def _auth_header(user: User) -> dict[str, str]:
    token, _ = create_access_token(str(user.id))
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# 1. Adversarial Re-Plan & Approval Invalidation Attacks
# ---------------------------------------------------------------------------

class TestAdversarialReplanAndApprovalInvalidation:
    """Stress-tests that revising an approved plan invalidates approval across all execution paths."""

    def test_replan_invalidates_approval_and_blocks_execution_endpoints(self, client_harness):
        client = client_harness["client"]
        db = client_harness["db"]

        user = _make_user(db, "dev-approval-tester")
        repo = _make_repo(db, user)
        headers = _auth_header(user)

        # 1. Create task
        create_resp = client.post(
            "/api/v1/tasks",
            json={
                "repository_id": str(repo.id),
                "title": "Fix security vulnerability",
                "description": "Remediate SQL injection",
                "source": {"type": "USER_PROMPT", "base_revision": "abc1234"},
                "requirements": [
                    {
                        "id": "r1",
                        "description": "Parameterize queries",
                        "category": "security",
                        "target_files": ["backend/db.py"],
                        "acceptance_criteria": ["Sanitize input"],
                    }
                ],
                "base_revision": "abc1234",
            },
            headers=headers,
        )
        assert create_resp.status_code == 201, create_resp.text
        task_id = create_resp.json()["task_id"]

        # 2. Generate Plan v1
        plan_resp = client.post(f"/api/v1/tasks/{task_id}/plan", json={}, headers=headers)
        assert plan_resp.status_code == 200, plan_resp.text
        assert plan_resp.json()["plan_version"] == 1
        assert plan_resp.json()["status"] == "PENDING_APPROVAL"

        # 3. Approve Plan v1
        approve_resp = client.post(
            f"/api/v1/tasks/{task_id}/approve",
            json={"plan_version": 1},
            headers=headers,
        )
        assert approve_resp.status_code == 200, approve_resp.text
        assert approve_resp.json()["status"] == "APPROVED"

        # Verify DB state: task is APPROVED, approved_plan_version == 1
        task_repo = TaskRepository(db)
        task_obj = task_repo.get_task(task_id)
        assert task_obj.status == TaskStatus.APPROVED.value
        assert task_obj.approved_plan_version == 1

        # 4. Adversary triggers re-plan (Plan v2)
        replan_resp = client.post(f"/api/v1/tasks/{task_id}/plan", json={}, headers=headers)
        assert replan_resp.status_code == 200, replan_resp.text
        assert replan_resp.json()["plan_version"] == 2

        # Invalidation check: task status must revert to PENDING_APPROVAL and approved_plan_version is None
        db.expire_all()
        task_obj = task_repo.get_task(task_id)
        assert task_obj.status == TaskStatus.PENDING_APPROVAL.value
        assert task_obj.approved_plan_version is None, "Approval was not cleared upon re-plan!"
        assert task_obj.plan_version == 2

        # 5. Attack Scenario: Attempt to execute without re-approving Plan v2
        exec_resp = client.post(f"/api/v1/tasks/{task_id}/execute", headers=headers)
        assert exec_resp.status_code in (403, 409), f"Expected 403/409, got {exec_resp.status_code}: {exec_resp.text}"
        assert exec_resp.json()["error"]["code"] in ("APPROVAL_REQUIRED", "INVALID_STATE_TRANSITION")

        # 6. Attack Scenario: Attempt to run tests without re-approving Plan v2
        tests_resp = client.post(f"/api/v1/tasks/{task_id}/tests", headers=headers)
        assert tests_resp.status_code in (403, 409), f"Expected 403/409, got {tests_resp.status_code}: {tests_resp.text}"
        assert tests_resp.json()["error"]["code"] in ("APPROVAL_REQUIRED", "INVALID_STATE_TRANSITION")

        # 7. Attack Scenario: Attempt to trigger repair without re-approving Plan v2
        repair_resp = client.post(f"/api/v1/tasks/{task_id}/repair", headers=headers)
        assert repair_resp.status_code in (403, 409), f"Expected 403/409, got {repair_resp.status_code}: {repair_resp.text}"
        assert repair_resp.json()["error"]["code"] in ("APPROVAL_REQUIRED", "INVALID_STATE_TRANSITION")

        # 8. Direct Orchestrator Attack: Call verify_execution_approval_gate directly
        with pytest.raises(APIError) as exc_info:
            task_repo.verify_execution_approval_gate(task_obj)
        assert exc_info.value.status_code == 403
        assert exc_info.value.code == ErrorCode.APPROVAL_REQUIRED


# ---------------------------------------------------------------------------
# 2. State Machine Invariants & Illegal State Jumps
# ---------------------------------------------------------------------------

class TestStateMachineInvariants:
    """Stress-tests legal and illegal state transitions across all 17 lifecycle states."""

    def test_illegal_direct_jumps_rejected(self, mem_db: Session):
        task_repo = TaskRepository(mem_db)
        user = _make_user(mem_db, "state-jump-user")
        repo = _make_repo(mem_db, user)

        task = task_repo.create_task(
            repository_id=repo.id,
            user_id=user.id,
            title="State Machine Test Task",
            source_type=TaskSourceType.DIRECT,
        )
        assert task.status == TaskStatus.CREATED.value

        # 1. CREATED -> PUBLISHING is illegal
        assert can_transition(TaskStatus.CREATED, TaskStatus.PUBLISHING) is False
        with pytest.raises(APIError) as exc:
            task_repo.transition_status(task, TaskStatus.PUBLISHING)
        assert exc.value.status_code == 409
        assert exc.value.code == ErrorCode.INVALID_STATE_TRANSITION

        # 2. CREATED -> EXECUTING is illegal
        assert can_transition(TaskStatus.CREATED, TaskStatus.EXECUTING) is False
        with pytest.raises(APIError) as exc:
            task_repo.transition_status(task, TaskStatus.EXECUTING)
        assert exc.value.status_code == 409

        # Move to PLANNING
        task_repo.transition_status(task, TaskStatus.PLANNING)
        assert task.status == TaskStatus.PLANNING.value

        # Move to PENDING_APPROVAL
        task_repo.transition_status(task, TaskStatus.PENDING_APPROVAL)
        assert task.status == TaskStatus.PENDING_APPROVAL.value

        # 3. PENDING_APPROVAL -> EXECUTING is strictly prohibited (Docs/week3.md §7.2)
        assert can_transition(TaskStatus.PENDING_APPROVAL, TaskStatus.EXECUTING) is False
        with pytest.raises(APIError) as exc:
            task_repo.transition_status(task, TaskStatus.EXECUTING)
        assert exc.value.status_code == 409
        assert exc.value.code == ErrorCode.INVALID_STATE_TRANSITION

        # 4. REJECTED -> EXECUTING is strictly prohibited
        task_repo.transition_status(task, TaskStatus.REJECTED)
        assert can_transition(TaskStatus.REJECTED, TaskStatus.EXECUTING) is False
        with pytest.raises(APIError) as exc:
            task_repo.transition_status(task, TaskStatus.EXECUTING)
        assert exc.value.status_code == 409

        # 5. CANCELLED is terminal: CANCELLED -> PLANNING or EXECUTING is illegal
        task_repo.transition_status(task, TaskStatus.CANCELLED)
        assert task.status == TaskStatus.CANCELLED.value
        assert can_transition(TaskStatus.CANCELLED, TaskStatus.PLANNING) is False
        assert can_transition(TaskStatus.CANCELLED, TaskStatus.EXECUTING) is False
        with pytest.raises(APIError) as exc:
            task_repo.transition_status(task, TaskStatus.PLANNING)
        assert exc.value.status_code == 409

        # 6. DRAFT_PR_CREATED is terminal: no forward transitions
        assert len(VALID_TASK_TRANSITIONS[TaskStatus.DRAFT_PR_CREATED]) == 0
        assert can_transition(TaskStatus.DRAFT_PR_CREATED, TaskStatus.EXECUTING) is False

    def test_blocked_and_cancelled_symmetrical_coverage(self):
        """Every non-terminal state must support transitioning to CANCELLED and BLOCKED."""
        non_terminal_states = [
            s for s in TaskStatus if s not in (TaskStatus.CANCELLED, TaskStatus.DRAFT_PR_CREATED)
        ]
        for s in non_terminal_states:
            allowed = VALID_TASK_TRANSITIONS.get(s, frozenset())
            assert TaskStatus.CANCELLED in allowed, f"State {s} missing transition to CANCELLED"
            assert TaskStatus.BLOCKED in allowed, f"State {s} missing transition to BLOCKED"


# ---------------------------------------------------------------------------
# 3. Post-Verification Diff Immutability & Tampering Defenses
# ---------------------------------------------------------------------------

class TestPostVerificationDiffImmutability:
    """Stress-tests that workspace tampering post-verification halts publication immediately."""

    def test_post_verification_mutation_blocks_branch_push_and_pr_publication(
        self, client_harness, tmp_path: Path
    ):
        db = client_harness["db"]
        orchestrator = client_harness["orchestrator"]
        wm = client_harness["workspace_manager"]

        user = _make_user(db, "immutability-victim")
        repo = _make_repo(db, user)
        task_repo = TaskRepository(db)

        task = task_repo.create_task(
            repository_id=repo.id,
            user_id=user.id,
            title="Tamper Detection Task",
            source_type=TaskSourceType.DIRECT,
            base_revision="abcdef0123456789abcdef0123456789abcdef01",
        )

        # Set up a real workspace on disk
        ws_dir = tmp_path / "workspaces" / f"ws-{task.id}"
        ws_dir.mkdir(parents=True, exist_ok=True)
        code_file = ws_dir / "service.py"
        code_file.write_text("def sanitize(x): return x.strip()\n")

        # Provision Workspace metadata
        meta = WorkspaceMetadata(
            workspace_id=f"ws-{task.id}",
            task_id=str(task.id),
            repository_id=str(repo.id),
            workspace_path=str(ws_dir),
            branch_name=f"agent/task-{task.id}",
            base_revision="abcdef0123456789abcdef0123456789abcdef01",
            status=WorkspaceStatus.READY.value,
        )
        wm._workspaces[str(task.id)] = meta
        task_repo.record_workspace(
            task_id=task.id,
            repository_id=repo.id,
            workspace_path=str(ws_dir),
            task_branch=f"agent/task-{task.id}",
            base_revision="abcdef0123456789abcdef0123456789abcdef01",
        )

        # Compute initial verification diff hash
        verified_hash = wm.compute_verification_diff_hash(str(task.id))
        meta.verification_diff_hash = verified_hash

        # Record PASSED verification record
        task_repo.record_verification_result(
            task_id=task.id,
            repository_id=repo.id,
            verified_revision="abcdef0123456789abcdef0123456789abcdef01",
            status=VerificationStatus.PASSED.value,
            blocking_findings=[],
        )

        # State is ready
        task.status = TaskStatus.READY_FOR_PUBLICATION.value
        db.commit()

        # Sanity check: verify immutability passes before tampering
        imm_check = wm.verify_diff_immutability(str(task.id))
        assert imm_check.is_immutable is True

        # ATTACK: Tamper with workspace after independent verification
        code_file.write_text("def sanitize(x): return x  # BACKDOOR INJECTED\n")

        # Verify immutability check fails
        tampered_check = wm.verify_diff_immutability(str(task.id))
        assert tampered_check.is_immutable is False
        assert "Workspace was modified after independent verification" in (tampered_check.error_message or "")

        # Push branch must raise HTTP 409 VERIFICATION_FAILED
        with pytest.raises(APIError) as exc_push:
            orchestrator.push_verified_branch(
                task,
                task_repo,
                actor_id=user.id,
                publication_authorized=True,
            )
        assert exc_push.value.status_code == 409
        assert exc_push.value.code == ErrorCode.VERIFICATION_FAILED
        assert "modified after independent verification" in exc_push.value.message

        # PR publication must raise HTTP 409 VERIFICATION_FAILED
        with pytest.raises(APIError) as exc_pr:
            orchestrator.publish_draft_pr(
                task,
                task_repo,
                actor_id=user.id,
                publication_authorized=True,
            )
        assert exc_pr.value.status_code == 409
        assert exc_pr.value.code == ErrorCode.VERIFICATION_FAILED


# ---------------------------------------------------------------------------
# 4. Missing or Unrecorded Verification Diff Hash Attacks
# ---------------------------------------------------------------------------

class TestMissingVerificationDiffHash:
    """Stress-tests rejection when verification_diff_hash is empty or missing."""

    def test_empty_or_none_diff_hash_fails_closed(self, client_harness, tmp_path: Path):
        db = client_harness["db"]
        orchestrator = client_harness["orchestrator"]
        wm = client_harness["workspace_manager"]

        user = _make_user(db, "missing-hash-user")
        repo = _make_repo(db, user)
        task_repo = TaskRepository(db)

        task = task_repo.create_task(
            repository_id=repo.id,
            user_id=user.id,
            title="Missing Hash Test Task",
            source_type=TaskSourceType.DIRECT,
        )

        ws_dir = tmp_path / "workspaces" / f"ws-{task.id}"
        ws_dir.mkdir(parents=True, exist_ok=True)
        meta = WorkspaceMetadata(
            workspace_id=f"ws-{task.id}",
            task_id=str(task.id),
            repository_id=str(repo.id),
            workspace_path=str(ws_dir),
            branch_name=f"agent/task-{task.id}",
            base_revision="abcdef0123456789abcdef0123456789abcdef01",
            verification_diff_hash="",  # Explicitly empty / missing
            status=WorkspaceStatus.READY.value,
        )
        wm._workspaces[str(task.id)] = meta

        # Record PASSED verification
        task_repo.record_verification_result(
            task_id=task.id,
            repository_id=repo.id,
            verified_revision="abcdef0123456789abcdef0123456789abcdef01",
            status=VerificationStatus.PASSED.value,
            blocking_findings=[],
        )

        # 1. verify_diff_immutability must return is_immutable=False
        res = wm.verify_diff_immutability(str(task.id), expected_diff_hash="")
        assert res.is_immutable is False
        assert "missing or unrecorded" in res.message

        # 2. _assert_verified_and_immutable_for_publication must raise 409 VERIFICATION_FAILED
        with pytest.raises(APIError) as exc:
            orchestrator._assert_verified_and_immutable_for_publication(task, task_repo, meta)
        assert exc.value.status_code == 409
        assert exc.value.code == ErrorCode.VERIFICATION_FAILED
        assert "Verification diff hash is missing or unrecorded" in exc.value.message


# ---------------------------------------------------------------------------
# 5. Multi-Tenant Task, Workspace, & Repository Isolation Attacks
# ---------------------------------------------------------------------------

class TestMultiTenantIsolationAttacks:
    """Stress-tests cross-tenant resource reads and mutations."""

    def test_tenant_b_cannot_access_or_mutate_tenant_a_task_and_workspace(
        self, client_harness
    ):
        client = client_harness["client"]
        db = client_harness["db"]

        tenant_a = _make_user(db, "tenant_alice")
        tenant_b = _make_user(db, "tenant_bob_attacker")
        repo_a = _make_repo(db, tenant_a, "alice-private-code")
        repo_b = _make_repo(db, tenant_b, "bob-scratch")

        headers_a = _auth_header(tenant_a)
        headers_b = _auth_header(tenant_b)

        # Tenant A creates task
        create_res = client.post(
            "/api/v1/tasks",
            json={
                "repository_id": str(repo_a.id),
                "title": "Secret Payroll Fix",
                "description": "Fix payroll database logic",
                "source": {"type": "USER_PROMPT", "base_revision": "abcdef012345"},
                "requirements": [
                    {
                        "id": "r1",
                        "description": "Ensure payroll calculation",
                        "category": "functional",
                        "target_files": ["payroll.py"],
                        "acceptance_criteria": ["Correct bonus"],
                    }
                ],
                "base_revision": "abcdef012345",
            },
            headers=headers_a,
        )
        assert create_res.status_code == 201
        task_a_id = create_res.json()["task_id"]

        # Attack 1: Tenant B tries to read Tenant A's task -> 404
        get_res = client.get(f"/api/v1/tasks/{task_a_id}", headers=headers_b)
        assert get_res.status_code == 404
        assert get_res.json()["error"]["code"] == "TASK_NOT_FOUND"

        # Attack 2: Tenant B tries to view Tenant A's workspace -> 404
        ws_res = client.get(f"/api/v1/tasks/{task_a_id}/workspace", headers=headers_b)
        assert ws_res.status_code == 404
        assert ws_res.json()["error"]["code"] == "TASK_NOT_FOUND"

        # Attack 3: Tenant B tries to plan Tenant A's task -> 404
        plan_res = client.post(f"/api/v1/tasks/{task_a_id}/plan", json={}, headers=headers_b)
        assert plan_res.status_code == 404

        # Attack 4: Tenant B tries to approve Tenant A's task -> 404
        approve_res = client.post(
            f"/api/v1/tasks/{task_a_id}/approve",
            json={"plan_version": 1},
            headers=headers_b,
        )
        assert approve_res.status_code == 404

        # Attack 5: Tenant B tries to cancel Tenant A's task -> 404
        cancel_res = client.post(f"/api/v1/tasks/{task_a_id}/cancel", headers=headers_b)
        assert cancel_res.status_code == 404

        # Attack 6: Tenant B tries to access Tenant A's repository -> 404
        repo_res = client.get(f"/api/v1/repositories/{repo_a.id}", headers=headers_b)
        assert repo_res.status_code == 404

        # Attack 7: Direct repository layer enforcement
        task_repo = TaskRepository(db)
        assert task_repo.get_task(task_a_id, user_id=tenant_b.id) is None
        assert task_repo.get_task(task_a_id, user_id=tenant_a.id) is not None

        with pytest.raises(TaskNotFoundError):
            task_repo.get_workspace(task_a_id, repo_a.id, user_id=tenant_b.id)

        assert task_repo.get_workspace_record(task_a_id, user_id=tenant_b.id) is None


# ---------------------------------------------------------------------------
# 6. GitHub Installation Hijacking & Direct Upsert Attacks
# ---------------------------------------------------------------------------

class TestGitHubInstallationHijackingAttacks:
    """Stress-tests that GitHub installations cannot be reassigned or stolen across tenants."""

    def test_installation_hijack_via_query_param_blocked(self, client_harness):
        client = client_harness["client"]
        db = client_harness["db"]

        victim = _make_user(db, "victim-corp")
        attacker = _make_user(db, "attacker-dev")
        attacker_headers = _auth_header(attacker)

        # Seed installation owned by victim
        inst_repo = GitHubInstallationRepository(db)
        inst_repo.upsert(
            user_id=victim.id,
            installation_id="shared_inst_778899",
            account_login=victim.login,
            permissions={"contents": "write"},
        )

        # Attacker tries to query repositories passing victim's installation_id
        res = client.get(
            "/api/v1/github/repositories?installation_id=shared_inst_778899",
            headers=attacker_headers,
        )
        assert res.status_code == 403
        data = res.json()
        assert data["error"]["code"] == "FORBIDDEN"
        assert "linked to another user" in data["error"]["message"]

    def test_direct_installation_repo_upsert_reassignment_raises_value_error(
        self, client_harness
    ):
        db = client_harness["db"]
        inst_repo = GitHubInstallationRepository(db)

        victim = _make_user(db, "victim-legit")
        attacker = _make_user(db, "attacker-hijacker")

        # Initial link by victim
        inst_repo.upsert(
            user_id=victim.id,
            installation_id="hardware_inst_5544",
            account_login=victim.login,
            permissions={"issues": "read"},
        )

        # Direct repository layer attack: attempt to overwrite user_id with attacker
        with pytest.raises(ValueError) as exc:
            inst_repo.upsert(
                user_id=attacker.id,
                installation_id="hardware_inst_5544",
                account_login=attacker.login,
                permissions={"issues": "admin"},
            )
        assert "is already linked to user" in str(exc.value)
        assert "cannot be reassigned" in str(exc.value)


# ---------------------------------------------------------------------------
# 7. GitHub Webhook Security & Spoofing Stress Tests
# ---------------------------------------------------------------------------

class TestGitHubWebhookSecurityStress:
    """Stress-tests HMAC signature enforcement, whitespace secrets, replay protection, and body limits."""

    def test_webhook_fails_closed_on_whitespace_secret(self, client_harness, monkeypatch):
        client = client_harness["client"]
        monkeypatch.setenv("GITHUB_WEBHOOK_SECRET", "   \t  \n  ")
        get_settings.cache_clear()

        payload = json.dumps({"action": "opened"}).encode("utf-8")
        res = client.post(
            "/api/v1/github/webhook",
            content=payload,
            headers={
                "X-Hub-Signature-256": "sha256=invalid",
                "X-GitHub-Event": "issues",
                "X-GitHub-Delivery": "delivery_ws_1",
            },
        )
        assert res.status_code == 503
        assert res.json()["error"]["code"] == "SERVICE_UNAVAILABLE"
        assert "not configured" in res.json()["error"]["message"]

    def test_webhook_rejects_missing_and_spoofed_signatures(self, client_harness):
        client = client_harness["client"]
        payload = json.dumps({"action": "ping"}).encode("utf-8")

        # 1. Missing signature
        res_missing = client.post(
            "/api/v1/github/webhook",
            content=payload,
            headers={"X-GitHub-Event": "ping"},
        )
        assert res_missing.status_code == 401
        assert res_missing.json()["error"]["code"] == "UNAUTHORIZED"

        # 2. Spoofed / forged signature
        res_spoofed = client.post(
            "/api/v1/github/webhook",
            content=payload,
            headers={
                "X-Hub-Signature-256": "sha256=" + "a" * 64,
                "X-GitHub-Event": "ping",
            },
        )
        assert res_spoofed.status_code == 401
        assert res_spoofed.json()["error"]["code"] == "UNAUTHORIZED"

    def test_webhook_deduplicates_replayed_delivery_id(self, client_harness):
        client = client_harness["client"]
        secret = "adversarial-webhook-secret-token"

        payload = json.dumps({"action": "opened", "issue": {"number": 42}}).encode("utf-8")
        sig = "sha256=" + hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).hexdigest()

        headers = {
            "X-Hub-Signature-256": sig,
            "X-GitHub-Event": "issues",
            "X-GitHub-Delivery": "replay_delivery_test_99",
        }

        # First delivery -> processed (or ignored if unsupported, but status is not duplicate)
        res1 = client.post("/api/v1/github/webhook", content=payload, headers=headers)
        assert res1.status_code in (200, 202)
        assert res1.json().get("status") != "duplicate_delivery_ignored"

        # Second delivery (replay attack with identical delivery ID) -> deduplicated
        res2 = client.post("/api/v1/github/webhook", content=payload, headers=headers)
        assert res2.status_code == 200
        assert res2.json().get("status") == "duplicate_delivery_ignored"
        assert res2.json().get("delivery_id") == "replay_delivery_test_99"

    def test_webhook_rejects_malformed_delivery_id(self, client_harness):
        client = client_harness["client"]
        secret = "adversarial-webhook-secret-token"

        payload = json.dumps({"action": "ping"}).encode("utf-8")
        sig = "sha256=" + hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).hexdigest()

        # Attacker injects malicious characters in delivery header
        malformed_headers = {
            "X-Hub-Signature-256": sig,
            "X-GitHub-Event": "ping",
            "X-GitHub-Delivery": "delivery'; DROP TABLE users; --",
        }
        res = client.post("/api/v1/github/webhook", content=payload, headers=malformed_headers)
        assert res.status_code == 400
        assert res.json()["error"]["code"] == "BAD_REQUEST"

    def test_webhook_rejects_oversized_payload(self, client_harness):
        client = client_harness["client"]
        oversized_body = b"x" * (5 * 1024 * 1024 + 1)  # 5MB + 1 byte
        res = client.post(
            "/api/v1/github/webhook",
            content=oversized_body,
            headers={"X-GitHub-Event": "ping"},
        )
        assert res.status_code == 413
        assert res.json()["error"]["code"] == "BAD_REQUEST"
