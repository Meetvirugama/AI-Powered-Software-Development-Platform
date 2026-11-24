"""Tests for persisted, SHA-bound publication authorization (TST-20, ISS-004).

Validates:
- Attempting to create a Draft PR without persisted publication authorization fails with 409 PUBLICATION_AUTHORIZATION_REQUIRED.
- Attempting to create a Draft PR with mismatched authorized HEAD SHA fails with 409 PUBLICATION_AUTHORIZATION_REQUIRED.
- Happy path: Independent verification -> authorize publication with head SHA -> create Draft PR succeeds.
"""

from pathlib import Path
from uuid import uuid4
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.security import create_access_token
from app.core.database import Base, get_db
from app.main import app
from app.models.task import Task as AgentTask, TaskStatus
from app.services.git_branch import format_agent_branch_name
from app.models.github_installation import GitHubInstallation
from app.models.repository import Repository, SyncStatus
from app.models.user import User
from app.repositories.task_repository import TaskRepository
from app.services.task_execution_orchestrator import TaskExecutionOrchestrator
from app.schemas.workspace import WorkspaceCreateRequest
from sandbox.workspace_manager import WorkspaceManager


@pytest.fixture()
def db_session() -> Session:
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(engine, "connect")
    def _register_sqlite_functions(dbapi_connection, _connection_record) -> None:
        dbapi_connection.create_function("to_tsvector", 2, lambda cfg, txt: txt or "", deterministic=True)

    Base.metadata.create_all(bind=engine)
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)


@pytest.fixture()
def sandbox_orchestrator(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TaskExecutionOrchestrator:
    ws_root = tmp_path / ".workspaces"
    ws_root.mkdir(parents=True, exist_ok=True)
    wm = WorkspaceManager(base_workspaces_dir=ws_root)
    orch = TaskExecutionOrchestrator(workspace_manager=wm)
    monkeypatch.setattr(app.state, "task_execution_orchestrator", orch, raising=False)
    return orch


@pytest.fixture()
def client(
    db_session: Session,
    sandbox_orchestrator: TaskExecutionOrchestrator,
    monkeypatch: pytest.MonkeyPatch,
    local_task_publication,
) -> TestClient:
    from app.core.rate_limit import InMemoryRateLimitStore

    store = InMemoryRateLimitStore()

    async def _not_blocklisted(_jti: str) -> bool:
        return False

    monkeypatch.setattr("app.core.auth._is_token_blocklisted_async", _not_blocklisted)
    monkeypatch.setattr("app.core.rate_limit.get_rate_limit_store", lambda: store)

    def _override_get_db():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = _override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def _seed_verified_task(
    db: Session,
    sandbox_orchestrator: TaskExecutionOrchestrator,
    base_revision: str,
    record_verified_commit,
) -> tuple[User, Repository, AgentTask, str, str]:
    user = User(
        id=uuid4(),
        github_id="987654",
        login="pub-auth-tester",
        email="pubauth@example.com",
        role="developer",
    )
    db.add(user)
    db.flush()

    inst = GitHubInstallation(
        id=uuid4(),
        installation_id="887766",
        account_login="pub-auth-org",
        user_id=user.id,
    )
    db.add(inst)
    db.flush()

    repo = Repository(
        id=uuid4(),
        github_repo_id="776655",
        owner="Meetvirugama",
        name="AI-Powered-Software-Development-Platform",
        default_branch="main",
        installation_id=inst.id,
        user_id=user.id,
        sync_status=SyncStatus.SYNCED,
    )
    db.add(repo)
    db.flush()

    token, _ = create_access_token(user.id, role="developer")
    task_repo = TaskRepository(db)

    task = AgentTask(
        id=uuid4(),
        repository_id=repo.id,
        user_id=user.id,
        title="Implement secure discount clamping",
        description="Clamp discount to prevent negative totals",
        status=TaskStatus.READY_FOR_PUBLICATION.value,
        base_revision=base_revision,
        plan_version=1,
        approved_plan_version=1,
    )
    db.add(task)
    db.commit()

    # Provision workspace
    ws_meta = sandbox_orchestrator.workspace_manager.create_workspace(
        WorkspaceCreateRequest(
            task_id=str(task.id),
            repository_id=str(repo.id),
            base_revision=task.base_revision,
            branch_name=format_agent_branch_name(task.id),
        ),
        repository_url=f"https://github.com/{repo.owner}/{repo.name}.git",
        installation_token="fixture-token",
    )
    ws_path = Path(ws_meta.workspace_path)
    (ws_path / "src").mkdir(parents=True, exist_ok=True)
    (ws_path / "src" / "payment.py").write_text(
        "def calculate_discounted_total(p: float, d: float) -> float:\n    return max(0.0, p - max(0.0, d))\n",
        encoding="utf-8",
    )
    (ws_path / "tests").mkdir(parents=True, exist_ok=True)
    (ws_path / "tests" / "test_payment.py").write_text(
        "from src.payment import calculate_discounted_total\ndef test_calc():\n    assert calculate_discounted_total(100, 150) == 0.0\n",
        encoding="utf-8",
    )

    verified_rev = record_verified_commit(sandbox_orchestrator.workspace_manager, task_repo, task)

    from app.models.task import Workspace, WorkspaceStatus as DBWorkspaceStatus

    db_ws = Workspace(
        task_id=task.id,
        workspace_path=str(ws_path),
        task_branch=ws_meta.branch_name,
        base_revision=task.base_revision,
        current_revision=verified_rev,
        status=DBWorkspaceStatus.READY.value,
    )
    db.add(db_ws)
    db.commit()

    return user, repo, task, token, verified_rev


def test_create_pr_without_persisted_authorization_fails(
    client: TestClient,
    db_session: Session,
    sandbox_orchestrator: TaskExecutionOrchestrator,
    local_task_base_revision,
    record_verified_commit,
) -> None:
    """TST-20: create-pr without prior POST /authorize-publication fails with 409."""
    _user, repo, task, token, verified_rev = _seed_verified_task(
        db_session, sandbox_orchestrator, local_task_base_revision, record_verified_commit,
    )
    headers = {"Authorization": f"Bearer {token}"}

    # Attempt to create PR without calling /authorize-publication
    resp = client.post(
        f"/api/v1/tasks/{task.id}/create-pr",
        headers=headers,
        json={"publication_authorized": True},
    )
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "PUBLICATION_AUTHORIZATION_REQUIRED"
    assert "authorize this verified commit" in resp.json()["error"]["message"].lower()


def test_authorize_publication_with_mismatched_head_sha_fails(
    client: TestClient,
    db_session: Session,
    sandbox_orchestrator: TaskExecutionOrchestrator,
    local_task_base_revision,
    record_verified_commit,
) -> None:
    """TST-20: POST /authorize-publication fails if head_sha does not match verified revision."""
    _user, repo, task, token, verified_rev = _seed_verified_task(
        db_session, sandbox_orchestrator, local_task_base_revision, record_verified_commit,
    )
    headers = {"Authorization": f"Bearer {token}"}

    # Authorize with a mismatched head sha
    auth_resp = client.post(
        f"/api/v1/tasks/{task.id}/authorize-publication",
        headers=headers,
        json={"head_sha": "3333333333333333333333333333333333333333", "notes": "Mismatched authorization"},
    )
    assert auth_resp.status_code == 409


def test_create_pr_with_stale_authorized_sha_fails(
    client: TestClient,
    db_session: Session,
    sandbox_orchestrator: TaskExecutionOrchestrator,
    local_task_base_revision,
    record_verified_commit,
) -> None:
    """TST-20: create-pr fails with 409 PUBLICATION_AUTHORIZATION_REQUIRED if authorized SHA doesn't match new verified revision."""
    _user, repo, task, token, verified_rev = _seed_verified_task(
        db_session, sandbox_orchestrator, local_task_base_revision, record_verified_commit,
    )
    headers = {"Authorization": f"Bearer {token}"}
    task_repo = TaskRepository(db_session)

    # 1. Authorize publication with current verified_rev
    auth_resp = client.post(
        f"/api/v1/tasks/{task.id}/authorize-publication",
        headers=headers,
        json={"head_sha": verified_rev, "notes": "Initial authorization"},
    )
    assert auth_resp.status_code == 200

    # 2. Re-record verification with a new revision (e.g. after code changes)
    manager = sandbox_orchestrator.workspace_manager
    payment = manager.get_workspace_path(str(task.id)) / "src" / "payment.py"
    payment.write_text(payment.read_text(encoding="utf-8") + "\n# Follow-up revision\n", encoding="utf-8")
    assert record_verified_commit(manager, task_repo, task) != verified_rev

    # 3. Attempt to create PR with the old authorization still recorded
    resp = client.post(
        f"/api/v1/tasks/{task.id}/create-pr",
        headers=headers,
        json={"publication_authorized": True},
    )
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "PUBLICATION_AUTHORIZATION_REQUIRED"


def test_create_pr_happy_path_with_valid_authorization(
    client: TestClient,
    db_session: Session,
    sandbox_orchestrator: TaskExecutionOrchestrator,
    local_task_base_revision,
    record_verified_commit,
) -> None:
    """TST-20: create-pr succeeds when preceded by valid SHA-bound publication authorization."""
    _user, repo, task, token, verified_rev = _seed_verified_task(
        db_session, sandbox_orchestrator, local_task_base_revision, record_verified_commit,
    )
    headers = {"Authorization": f"Bearer {token}"}

    # Authorize publication with the exact verified_revision
    auth_resp = client.post(
        f"/api/v1/tasks/{task.id}/authorize-publication",
        headers=headers,
        json={"head_sha": verified_rev, "notes": "Approved for publication"},
    )
    assert auth_resp.status_code == 200

    # Create Draft PR
    resp = client.post(
        f"/api/v1/tasks/{task.id}/create-pr",
        headers=headers,
        json={"publication_authorized": True, "title": "feat: discount clamp fix"},
    )
    assert resp.status_code == 200
    pr_data = resp.json()
    assert pr_data["is_draft"] is True
    assert pr_data["title"] == "feat: discount clamp fix"
    assert pr_data["task_id"] == str(task.id)
