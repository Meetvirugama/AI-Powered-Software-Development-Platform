"""Week 3 Day 6 security regression: publication, recovery and workflow endpoints.

Owner: Sukun (Security). See Docs/security/week3_security_report.md.

The Day 5-7 endpoints from #165 (branch, commit, push, authorize-publication, create-pr,
publish, recover, run-workflow, checkpoints, ...) are checked here for:
1. Ownership: another user always gets 404.
2. Approval: nothing runs or publishes before plan approval and publication authorization.
3. Git argument injection: branch / remote / file names cannot become git options
   (e.g. `--receive-pack=<cmd>`), through the API or the tool policy.
4. Recovery cannot jump a task forward to TESTING / VERIFYING / READY_FOR_PUBLICATION.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base, get_db
from app.core.errors import APIError
from app.core.security import create_access_token
from app.core.tool_api_policy import api_tool_policy_violation
from app.main import app as fastapi_app
from app.models.github_installation import GitHubInstallation
from app.models.repository import Repository, SyncStatus
from app.models.user import User
from app.services.task_execution_orchestrator import (
    DEFAULT_COMMAND_ALLOWLIST,
    TaskExecutionOrchestrator,
)
from sandbox.workspace_manager import WorkspaceManager

USER_A_ID = UUID("61111111-1111-4111-a111-111111111111")
USER_B_ID = UUID("62222222-2222-4222-a222-222222222222")
REPO_A_ID = UUID("6aaaaaaa-aaaa-4aaa-aaaa-aaaaaaaaaaaa")
INST_A_ID = UUID("6bbbbbbb-bbbb-4bbb-abbb-bbbbbbbbbbb1")
EXEC_TEMPLATES = DEFAULT_COMMAND_ALLOWLIST["execute_command"]

BAD_REFS = [
    "--receive-pack=touch /tmp/pwned",
    "--upload-pack=touch /tmp/pwned",
    "-f",
    "+agent/task-1",
    "agent/task-1:refs/heads/main",
    "agent/../main",
    "agent/task 1",
    "agent/task;id",
    "agent/@{-1}",
    "agent/task.lock",
]


# ---------------------------------------------------------------------------
# Fixture
# ---------------------------------------------------------------------------

def _headers(user_id: UUID) -> dict[str, str]:
    token, _ = create_access_token(str(user_id))
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture()
def api_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    from app.core.config import get_settings

    monkeypatch.setenv("JWT_SECRET", "test-secret-key-w3-sec-regression")
    get_settings.cache_clear()

    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(engine, "connect")
    def _sqlite_pragma(dbapi_conn, _rec) -> None:
        dbapi_conn.create_function("to_tsvector", 2, lambda _c, t: t or "", deterministic=True)
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA foreign_keys=ON")
        cur.close()

    import app.models  # noqa: F401

    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, autocommit=False, autoflush=False)()

    session.add_all(
        [
            User(id=USER_A_ID, github_id="96001", login="reg-owner", email="reg-owner@example.com"),
            User(id=USER_B_ID, github_id="96002", login="reg-intruder", email="reg-intruder@example.com"),
        ]
    )
    session.commit()
    session.add(
        GitHubInstallation(
            id=INST_A_ID, user_id=USER_A_ID, installation_id="96101", account_login="reg-owner", permissions={}
        )
    )
    session.commit()
    session.add(
        Repository(
            id=REPO_A_ID,
            user_id=USER_A_ID,
            installation_id=INST_A_ID,
            github_repo_id="96201",
            owner="reg-owner",
            name="reg-demo",
            default_branch="main",
            language="Python",
            sync_status=SyncStatus.SYNCED,
        )
    )
    session.commit()

    monkeypatch.setattr("app.core.auth.get_redis", lambda: SimpleNamespace(exists=lambda *_a, **_k: 0))
    monkeypatch.setattr(
        "app.core.rate_limit.get_rate_limit_store",
        lambda: SimpleNamespace(hit=lambda *_a, **_k: 1),
    )

    previous = getattr(fastapi_app.state, "task_execution_orchestrator", None)
    orchestrator = TaskExecutionOrchestrator(
        workspace_manager=WorkspaceManager(base_workspaces_dir=tmp_path / "workspaces")
    )
    fastapi_app.state.task_execution_orchestrator = orchestrator

    def _override_db():
        yield session

    fastapi_app.dependency_overrides[get_db] = _override_db
    client = TestClient(fastapi_app, raise_server_exceptions=False)
    try:
        yield SimpleNamespace(client=client, session=session, orchestrator=orchestrator, tmp=tmp_path)
    finally:
        fastapi_app.dependency_overrides.pop(get_db, None)
        fastapi_app.state.task_execution_orchestrator = previous
        session.close()
        engine.dispose()
        get_settings.cache_clear()


def _create_task(client: TestClient) -> str:
    resp = client.post(
        "/api/v1/tasks",
        headers=_headers(USER_A_ID),
        json={
            "repository_id": str(REPO_A_ID),
            "title": "Add discount helper",
            "description": "Add apply_discount in src/discount.py.",
            "source": {"type": "USER_PROMPT", "repository_id": str(REPO_A_ID), "base_revision": "a1b2c3d4"},
            "requirements": [
                {
                    "id": "req-1",
                    "description": "Create src/discount.py with apply_discount(price, pct).",
                    "category": "functional",
                    "target_files": ["src/discount.py"],
                    "acceptance_criteria": ["Returns discounted price."],
                }
            ],
            "assumptions": [],
            "constraints": [
                {
                    "id": "cst-1",
                    "description": "Never modify secrets file.",
                    "constraint_type": "protected_file",
                    "forbidden_files": ["config/secrets.yml"],
                    "forbidden_packages": [],
                }
            ],
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["task_id"]


def _approved_task(client: TestClient) -> str:
    task_id = _create_task(client)
    plan = client.post(f"/api/v1/tasks/{task_id}/plan", headers=_headers(USER_A_ID), json={})
    assert plan.status_code == 200, plan.text
    approve = client.post(
        f"/api/v1/tasks/{task_id}/approve",
        headers=_headers(USER_A_ID),
        json={"plan_version": plan.json()["plan_version"]},
    )
    assert approve.status_code == 200, approve.text
    return task_id


# ---------------------------------------------------------------------------
# 1. Ownership on every Day 5-7 route
# ---------------------------------------------------------------------------

DAY5_7_ROUTES = [
    ("post", "/verify", {}),
    ("get", "/verification", None),
    ("post", "/branch", {}),
    ("post", "/commit", {}),
    ("post", "/push", {"publication_authorized": True}),
    ("post", "/authorize-publication", {"head_sha": "a1b2c3d4e5f6a7b8"}),
    ("post", "/create-pr", {"publication_authorized": True}),
    ("post", "/publish", {"publication_authorized": True}),
    ("get", "/pull-request", None),
    ("get", "/traceability", None),
    ("get", "/stale-check", None),
    ("post", "/checkpoints", {"step_name": "intruder", "state_data": {}}),
    ("get", "/checkpoints", None),
    ("post", "/recover", {}),
    ("get", "/invariants", None),
    ("post", "/run-workflow", {"publication_authorized": True}),
]


@pytest.mark.parametrize("method,suffix,body", DAY5_7_ROUTES)
def test_other_user_gets_404_on_publication_routes(api_env, method, suffix, body):
    task_id = _approved_task(api_env.client)
    kwargs = {"headers": _headers(USER_B_ID)}
    if body is not None:
        kwargs["json"] = body
    resp = getattr(api_env.client, method)(f"/api/v1/tasks/{task_id}{suffix}", **kwargs)
    assert resp.status_code == 404, f"{method.upper()} {suffix} returned {resp.status_code}: {resp.text}"

    owner_view = api_env.client.get(f"/api/v1/tasks/{task_id}", headers=_headers(USER_A_ID))
    assert owner_view.json()["status"] == "APPROVED", "intruder request changed the owner's task"


# ---------------------------------------------------------------------------
# 2. Nothing publishes without approval / authorization
# ---------------------------------------------------------------------------

def test_push_and_pr_require_publication_authorization(api_env):
    task_id = _approved_task(api_env.client)
    for path in ("/push", "/create-pr", "/publish"):
        resp = api_env.client.post(f"/api/v1/tasks/{task_id}{path}", headers=_headers(USER_A_ID), json={})
        assert resp.status_code == 403, f"{path}: {resp.text}"
        assert resp.json()["error"]["code"] == "PUBLICATION_AUTHORIZATION_REQUIRED"


def test_publication_blocked_before_verification(api_env):
    task_id = _approved_task(api_env.client)
    for path in ("/push", "/create-pr", "/publish"):
        resp = api_env.client.post(
            f"/api/v1/tasks/{task_id}{path}",
            headers=_headers(USER_A_ID),
            json={"publication_authorized": True},
        )
        assert resp.status_code in (403, 409), f"{path}: {resp.status_code} {resp.text}"

    pr = api_env.client.get(f"/api/v1/tasks/{task_id}/pull-request", headers=_headers(USER_A_ID))
    assert pr.status_code != 200 or not pr.json().get("pr_url")


def test_workflow_and_branch_blocked_before_plan_approval(api_env):
    task_id = _create_task(api_env.client)
    for path, body in [
        ("/run-workflow", {"publication_authorized": True}),
        ("/branch", {}),
        ("/commit", {"message": "x"}),
    ]:
        resp = api_env.client.post(f"/api/v1/tasks/{task_id}{path}", headers=_headers(USER_A_ID), json=body)
        assert resp.status_code in (403, 409), f"{path}: {resp.status_code} {resp.text}"


# ---------------------------------------------------------------------------
# 3. Git argument injection through the API
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("bad", BAD_REFS)
def test_push_rejects_injected_branch_and_remote(api_env, bad):
    task_id = _approved_task(api_env.client)
    marker = Path("/tmp/pwned")
    existed = marker.exists()

    for body in (
        {"publication_authorized": True, "branch_name": bad},
        {"publication_authorized": True, "branch_name": "agent/task-1", "remote_name": bad},
    ):
        resp = api_env.client.post(f"/api/v1/tasks/{task_id}/push", headers=_headers(USER_A_ID), json=body)
        assert resp.status_code == 400, f"{body}: {resp.status_code} {resp.text}"

    assert marker.exists() == existed


@pytest.mark.parametrize("bad", BAD_REFS)
def test_branch_commit_and_pr_reject_injected_names(api_env, bad):
    task_id = _approved_task(api_env.client)
    for path, body in [
        ("/branch", {"branch_name": bad}),
        ("/commit", {"message": "x", "branch_name": bad}),
        ("/create-pr", {"publication_authorized": True, "head_branch": bad}),
        ("/create-pr", {"publication_authorized": True, "base_branch": bad}),
    ]:
        resp = api_env.client.post(f"/api/v1/tasks/{task_id}{path}", headers=_headers(USER_A_ID), json=body)
        assert resp.status_code == 400, f"{path} {body}: {resp.status_code} {resp.text}"


@pytest.mark.parametrize("bad_file", ["--chmod=+x", "-A", "../../etc/passwd", "/etc/passwd", "C:\\Windows\\x"])
def test_commit_rejects_unsafe_file_paths(api_env, bad_file):
    task_id = _approved_task(api_env.client)
    resp = api_env.client.post(
        f"/api/v1/tasks/{task_id}/commit",
        headers=_headers(USER_A_ID),
        json={"message": "x", "files": [bad_file]},
    )
    assert resp.status_code == 400, resp.text


def test_protected_branch_still_reported_as_policy_violation(api_env):
    task_id = _approved_task(api_env.client)
    resp = api_env.client.post(
        f"/api/v1/tasks/{task_id}/branch", headers=_headers(USER_A_ID), json={"branch_name": "main"}
    )
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "POLICY_VIOLATION"


# ---------------------------------------------------------------------------
# 4. Recovery cannot skip steps
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "target",
    ["WORKSPACE_SETUP", "EXECUTING", "TESTING", "VERIFYING", "READY_FOR_PUBLICATION", "PUBLISHING", "DRAFT_PR_CREATED"],
)
def test_recover_cannot_jump_forward(api_env, target):
    task_id = _approved_task(api_env.client)
    resp = api_env.client.post(
        f"/api/v1/tasks/{task_id}/recover", headers=_headers(USER_A_ID), json={"target_status": target}
    )
    assert resp.status_code in (400, 422), resp.text

    status_now = api_env.client.get(f"/api/v1/tasks/{task_id}", headers=_headers(USER_A_ID)).json()["status"]
    assert status_now == "APPROVED"


def test_recover_targets_are_limited_at_service_level():
    orchestrator = TaskExecutionOrchestrator.__new__(TaskExecutionOrchestrator)
    task = SimpleNamespace(status="TESTING")
    for target in ("READY_FOR_PUBLICATION", "VERIFYING", "TESTING", "EXECUTING", "not-a-status"):
        with pytest.raises(APIError) as exc_info:
            orchestrator.recover_interrupted_task(task=task, task_repo=MagicMock(), target_status=target)
        assert exc_info.value.status_code == 400


# ---------------------------------------------------------------------------
# 5. Tool policy covers git names too
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "tool,args",
    [
        ("check_stale_revision", {"base_branch": "--upload-pack=touch /tmp/pwned"}),
        ("commit_task_changes", {"message": "x", "branch_name": "--receive-pack=x"}),
        ("commit_task_changes", {"message": "x", "files": ["--chmod=+x"]}),
        ("commit_task_changes", {"message": "x", "files": ["../../etc/passwd"]}),
        ("inspect_git_diff", {"base_branch": "a;id"}),
    ],
)
def test_tool_policy_rejects_injected_git_names(tool, args):
    assert api_tool_policy_violation(tool, args, EXEC_TEMPLATES) is not None


@pytest.mark.parametrize(
    "tool,args",
    [
        ("check_stale_revision", {"base_branch": "main"}),
        ("commit_task_changes", {"message": "feat: x", "branch_name": "agent/task-1", "files": ["src/a.py"]}),
    ],
)
def test_tool_policy_allows_normal_git_names(tool, args):
    assert api_tool_policy_violation(tool, args, EXEC_TEMPLATES) is None
