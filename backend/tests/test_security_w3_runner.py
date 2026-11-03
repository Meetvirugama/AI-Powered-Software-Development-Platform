"""Week 3 Day 4 security tests: test runner, command sandbox and bounded repair.

Owner: Sukun (Security). See Docs/security/week3_threat_model.md, section 6 (Day 4).

What these tests prove:
1. Commands are stopped at their timeout, and the timeout can never exceed the hard cap.
2. Huge output is cut down; secrets printed by tests are redacted.
3. Host secrets (GitHub token, JWT secret, DB URL, API keys) are not visible to tests.
4. Commands run inside the workspace folder, as an argument list (never through a shell).
5. The test runner refuses non-test executables, package installs, shell tricks and paths
   outside the workspace.
6. The repair budget (3 attempts) cannot be exceeded, repeated, or reset by a restart.
7. A repair patch cannot write to forbidden files or outside the workspace, even by
   naming them in target_files.
"""

from __future__ import annotations

import json
import textwrap
import time
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base, get_db
from app.core.security import create_access_token
from app.main import app as fastapi_app
from app.models.github_installation import GitHubInstallation
from app.models.repository import Repository, SyncStatus
from app.models.task import AgentTask
from app.models.user import User
from app.schemas.repair import RepairPatchPayload
from app.schemas.workspace import WorkspaceCreateRequest, WorkspaceTestExecutionRequest
from app.services.repair_service import RepairPatchValidator
from app.services.task_execution_orchestrator import TaskExecutionOrchestrator
from sandbox import command_runner as command_runner_module
from sandbox.command_runner import WorkspaceCommandRunner
from sandbox.constants import MAX_TIMEOUT_SECONDS
from sandbox.exceptions import (
    WorkspaceDuplicateRepairPatchError,
    WorkspaceError,
    WorkspaceRepairBudgetExhaustedError,
    WorkspaceStateError,
)
from sandbox.test_runner import WorkspaceTestRunner
from sandbox.workspace_manager import WorkspaceManager

USER_A_ID = UUID("41111111-1111-4111-a111-111111111111")
REPO_A_ID = UUID("4aaaaaaa-aaaa-4aaa-aaaa-aaaaaaaaaaaa")
INST_A_ID = UUID("4bbbbbbb-bbbb-4bbb-abbb-bbbbbbbbbbb1")

FAKE_GITHUB_TOKEN = "ghp_" + "Z9y8X7w6V5u4T3s2R1q0P9o8N7m6L5k4J3i2"
FAKE_AWS_KEY = "AKIA" + "ABCDEFGHIJKLMNOP"


def _write(root: Path, name: str, code: str) -> Path:
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(code), encoding="utf-8")
    return path


@pytest.fixture()
def sandbox_dir(tmp_path: Path) -> Path:
    root = tmp_path / "workspace"
    root.mkdir()
    return root


# ---------------------------------------------------------------------------
# 1. Timeouts
# ---------------------------------------------------------------------------

def test_command_is_stopped_at_timeout(sandbox_dir):
    _write(sandbox_dir, "slow.py", "import time\ntime.sleep(60)\n")
    runner = WorkspaceCommandRunner()

    started = time.perf_counter()
    result = runner.run_command(sandbox_dir, "python", ["slow.py"], timeout_seconds=1)
    elapsed = time.perf_counter() - started

    assert result.timed_out is True
    assert result.success is False
    assert elapsed < 20, f"command ran for {elapsed:.1f}s after a 1s timeout"


def test_timeout_is_capped_and_no_shell_is_used(sandbox_dir, monkeypatch):
    seen: dict = {}

    class FakePopen:
        def __init__(self, cmd, **kwargs):
            seen["cmd"] = cmd
            seen["kwargs"] = kwargs
            self.returncode = 0

        def wait(self, timeout=None):
            seen["timeout"] = timeout
            return 0

        def kill(self):
            pass

    monkeypatch.setattr(command_runner_module.subprocess, "Popen", FakePopen)
    runner = WorkspaceCommandRunner()
    runner.run_command(sandbox_dir, "pytest", ["-q"], timeout_seconds=99_999)

    assert seen["timeout"] <= MAX_TIMEOUT_SECONDS
    assert isinstance(seen["cmd"], list), "commands must be passed as an argument list"
    assert seen["kwargs"].get("shell") is not True
    assert Path(seen["kwargs"]["cwd"]).resolve() == sandbox_dir.resolve()


def test_timeout_also_stops_child_processes(sandbox_dir):
    marker = sandbox_dir / "child_survived.txt"
    _write(
        sandbox_dir,
        "spawner.py",
        f"""
        import subprocess, sys, time
        child_code = "import time, pathlib\\ntime.sleep(3)\\npathlib.Path({str(marker)!r}).write_text('alive')\\n"
        subprocess.Popen([sys.executable, "-c", child_code])
        time.sleep(60)
        """,
    )
    runner = WorkspaceCommandRunner()
    result = runner.run_command(sandbox_dir, "python", ["spawner.py"], timeout_seconds=1)
    assert result.timed_out is True

    time.sleep(5)
    assert not marker.exists(), "a child process kept running after the timeout"


# ---------------------------------------------------------------------------
# 2. Output size and secret redaction
# ---------------------------------------------------------------------------

def test_huge_output_is_truncated(sandbox_dir):
    _write(
        sandbox_dir,
        "noisy.py",
        "import sys\nsys.stdout.write('A' * 500000)\nsys.stderr.write('B' * 500000)\n",
    )
    runner = WorkspaceCommandRunner(max_output_bytes=2000)
    result = runner.run_command(sandbox_dir, "python", ["noisy.py"], timeout_seconds=30)

    assert len(result.stdout) < 2200
    assert len(result.stderr) < 2200
    assert "TRUNCATED" in result.stdout
    assert "TRUNCATED" in result.stderr


def test_secrets_printed_by_tests_are_redacted(sandbox_dir):
    _write(
        sandbox_dir,
        "leaky.py",
        f"""
        import sys
        print("github token: {FAKE_GITHUB_TOKEN}")
        print("aws key: {FAKE_AWS_KEY}")
        print("password = 'hunter2-super-secret'")
        sys.stderr.write("stderr token {FAKE_GITHUB_TOKEN}\\n")
        """,
    )
    result = WorkspaceCommandRunner().run_command(sandbox_dir, "python", ["leaky.py"], timeout_seconds=30)

    combined = result.stdout + result.stderr
    assert FAKE_GITHUB_TOKEN not in combined
    assert FAKE_AWS_KEY not in combined
    assert "hunter2-super-secret" not in combined


# ---------------------------------------------------------------------------
# 3. Environment and working directory
# ---------------------------------------------------------------------------

def test_host_secrets_are_not_visible_to_tests(sandbox_dir, monkeypatch):
    secret_vars = {
        "GITHUB_TOKEN": FAKE_GITHUB_TOKEN,
        "JWT_SECRET": "jwt-secret-value-123456",
        "DATABASE_URL": "postgresql://user:dbpass@db/app",
        "GROQ_API_KEY": "gsk_hostkeyvalue1234567890",
        "GEMINI_API_KEY": "gemini-host-key-123456",
        "MY_COMPANY_SECRET": "custom-secret-value-123456",
    }
    for key, value in secret_vars.items():
        monkeypatch.setenv(key, value)

    _write(
        sandbox_dir,
        "env_dump.py",
        "import json, os\nprint(json.dumps({'keys': sorted(os.environ), 'cwd': os.getcwd()}))\n",
    )
    result = WorkspaceCommandRunner().run_command(
        sandbox_dir,
        "python",
        ["env_dump.py"],
        timeout_seconds=30,
        custom_env={"LD_PRELOAD": "/tmp/evil.so", "GITHUB_TOKEN": "x"},
    )
    assert result.success is True, result.stderr

    dumped = json.loads(result.stdout.strip().splitlines()[-1])
    for key in [*secret_vars, "LD_PRELOAD"]:
        assert key not in dumped["keys"], f"{key} is visible to test code"
    assert Path(dumped["cwd"]).resolve() == sandbox_dir.resolve()
    for value in secret_vars.values():
        assert value not in result.stdout


# ---------------------------------------------------------------------------
# 4. Test runner request validation
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "command,arguments,test_path",
    [
        ("bash", [], None),
        ("sh", ["-c", "id"], None),
        ("curl", ["https://evil.example"], None),
        ("npm", ["install", "evil-package"], None),
        ("npm", ["add", "evil-package"], None),
        ("python", ["-m", "pip", "install", "evil"], None),
        ("pytest", ["tests;", "rm", "-rf", "/"], None),
        ("pytest", ["$(id)"], None),
        ("pytest", ["tests", "|", "sh"], None),
        ("pytest", [], "../../etc"),
        ("pytest", [], "/etc/passwd"),
        ("pytest", [], ".git/hooks"),
    ],
)
def test_test_runner_refuses_unsafe_requests(sandbox_dir, command, arguments, test_path):
    with pytest.raises(WorkspaceError):
        WorkspaceTestRunner().validate_test_request(sandbox_dir, command, arguments, test_path)


def test_test_runner_accepts_normal_request(sandbox_dir):
    _write(sandbox_dir, "tests/test_ok.py", "def test_ok():\n    assert True\n")
    WorkspaceTestRunner().validate_test_request(sandbox_dir, "pytest", ["-q"], "tests/test_ok.py")


def test_tests_cannot_run_when_workspace_not_in_use(tmp_path):
    manager = WorkspaceManager(base_workspaces_dir=tmp_path / "ws")
    manager.create_workspace(
        WorkspaceCreateRequest(
            task_id="task-runner-ready",
            repository_id=str(REPO_A_ID),
            base_revision="a1b2c3d",
            isolation_type="directory_copy",
        )
    )
    with pytest.raises(WorkspaceStateError):
        manager.run_tests(WorkspaceTestExecutionRequest(task_id="task-runner-ready", framework="pytest"))


# ---------------------------------------------------------------------------
# 5. Repair budget
# ---------------------------------------------------------------------------

def test_repair_budget_stops_at_three_attempts():
    runner = WorkspaceTestRunner()
    for attempt in range(3):
        runner.record_repair_attempt("task-budget", patch_summary=f"fix {attempt}", patch_content=f"diff {attempt}")

    status = runner.get_repair_budget_status("task-budget")
    assert status.repair_attempts_used == 3
    assert status.is_budget_exhausted is True
    assert runner.can_attempt_repair("task-budget") is False

    with pytest.raises(WorkspaceRepairBudgetExhaustedError):
        runner.record_repair_attempt("task-budget", patch_summary="fix 4", patch_content="diff 4")
    assert runner.get_repair_budget_status("task-budget").repair_attempts_used == 3


def test_identical_repair_patch_is_rejected():
    runner = WorkspaceTestRunner()
    runner.record_repair_attempt("task-dup", patch_summary="fix", patch_content="same diff")
    with pytest.raises(WorkspaceDuplicateRepairPatchError):
        runner.record_repair_attempt("task-dup", patch_summary="fix again", patch_content="same diff")


def test_repair_budget_is_per_task():
    runner = WorkspaceTestRunner()
    for attempt in range(3):
        runner.record_repair_attempt("task-a", patch_summary=f"a {attempt}", patch_content=f"a {attempt}")
    assert runner.can_attempt_repair("task-b") is True
    assert runner.can_attempt_repair("task-a") is False


# ---------------------------------------------------------------------------
# 6. Repair patch validation (forbidden files and paths)
# ---------------------------------------------------------------------------

_SAFE_DIFF = """--- a/src/discount.py
+++ b/src/discount.py
@@ -1,2 +1,2 @@
-def apply_discount(p, pct):
+def apply_discount(p, pct):  # fixed
"""


@pytest.mark.parametrize(
    "target_files",
    [
        ["config/secrets.yml"],
        ["Config/Secrets.yml"],
        ["./config/secrets.yml"],
        ["../../outside.py"],
        ["/etc/passwd"],
        ["src/discount.py", "config/secrets.yml"],
    ],
)
def test_repair_patch_cannot_target_forbidden_or_outside_files(target_files):
    payload = RepairPatchPayload(
        task_id="task-patch",
        attempt_number=1,
        diff=_SAFE_DIFF,
        explanation="fix",
        target_files=target_files,
    )
    result = RepairPatchValidator().validate_patch(payload, forbidden_files=["config/secrets.yml"])
    assert result.is_valid is False, f"target_files={target_files} was accepted"


@pytest.mark.parametrize("forbidden_path", ["config/secrets.yml", "CONFIG/SECRETS.YML"])
def test_repair_patch_diff_on_forbidden_file_is_rejected_case_insensitive(forbidden_path):
    diff = _SAFE_DIFF.replace("src/discount.py", forbidden_path)
    payload = RepairPatchPayload(task_id="task-patch", attempt_number=1, diff=diff, explanation="fix")
    result = RepairPatchValidator().validate_patch(payload, forbidden_files=["config/secrets.yml"])
    assert result.is_valid is False


def test_repair_patch_normal_target_is_accepted():
    payload = RepairPatchPayload(
        task_id="task-patch",
        attempt_number=1,
        diff=_SAFE_DIFF,
        explanation="fix",
        target_files=["src/discount.py"],
    )
    result = RepairPatchValidator().validate_patch(payload, forbidden_files=["config/secrets.yml"])
    assert result.is_valid is True, result.violations


def test_repair_patch_with_secret_is_rejected():
    diff = _SAFE_DIFF.replace("# fixed", f"# token {FAKE_GITHUB_TOKEN}")
    payload = RepairPatchPayload(task_id="task-patch", attempt_number=1, diff=diff, explanation="fix")
    assert RepairPatchValidator().validate_patch(payload).is_valid is False


# ---------------------------------------------------------------------------
# 7. End to end through the API
# ---------------------------------------------------------------------------

def _headers(user_id: UUID) -> dict[str, str]:
    token, _ = create_access_token(str(user_id))
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture()
def api_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    from app.core.config import get_settings

    monkeypatch.setenv("JWT_SECRET", "test-secret-key-w3-sec-runner")
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

    session.add(User(id=USER_A_ID, github_id="94001", login="runner-owner", email="runner-owner@example.com"))
    session.commit()
    session.add(
        GitHubInstallation(
            id=INST_A_ID, user_id=USER_A_ID, installation_id="94101", account_login="runner-owner", permissions={}
        )
    )
    session.commit()
    session.add(
        Repository(
            id=REPO_A_ID,
            user_id=USER_A_ID,
            installation_id=INST_A_ID,
            github_repo_id="94201",
            owner="runner-owner",
            name="runner-demo",
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


def _running_task(client: TestClient) -> str:
    """Create, plan, approve and start a task so its workspace is IN_USE."""
    create = client.post(
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
    assert create.status_code == 201, create.text
    task_id = create.json()["task_id"]

    plan = client.post(f"/api/v1/tasks/{task_id}/plan", headers=_headers(USER_A_ID), json={})
    assert plan.status_code == 200, plan.text
    plan_data = plan.json()

    approve = client.post(
        f"/api/v1/tasks/{task_id}/approve",
        headers=_headers(USER_A_ID),
        json={"plan_version": plan_data["plan_version"]},
    )
    assert approve.status_code == 200, approve.text

    first_step = plan_data["steps"][0]["step_id"]
    execute = client.post(
        f"/api/v1/tasks/{task_id}/execute",
        headers=_headers(USER_A_ID),
        json={
            "run_steps": True,
            "step_payloads": {first_step: {"content": "def apply_discount(p, pct):\n    return p\n"}},
        },
    )
    assert execute.status_code == 200, execute.text
    return task_id


def test_api_test_output_secrets_are_redacted(api_env):
    task_id = _running_task(api_env.client)
    manager = api_env.orchestrator.workspace_manager
    write = manager.write_file(
        task_id,
        "tests/test_leak.py",
        f'TOKEN = "{FAKE_GITHUB_TOKEN}"\n\n'
        "def test_leak():\n"
        '    print("token", TOKEN)\n'
        '    assert False, f"leaked {TOKEN}"\n',
    )
    assert write.success is True

    resp = api_env.client.post(
        f"/api/v1/tasks/{task_id}/tests",
        headers=_headers(USER_A_ID),
        json={"framework": "pytest", "test_path": "tests/test_leak.py"},
    )
    assert resp.status_code == 200, resp.text
    assert FAKE_GITHUB_TOKEN not in resp.text

    for path in ("/tests", "/events"):
        later = api_env.client.get(f"/api/v1/tasks/{task_id}{path}", headers=_headers(USER_A_ID))
        assert later.status_code == 200
        assert FAKE_GITHUB_TOKEN not in later.text


def test_api_slow_tests_are_stopped_by_timeout(api_env):
    task_id = _running_task(api_env.client)
    api_env.orchestrator.workspace_manager.write_file(
        task_id,
        "tests/test_slow.py",
        "import time\n\ndef test_slow():\n    time.sleep(60)\n",
    )

    started = time.perf_counter()
    resp = api_env.client.post(
        f"/api/v1/tasks/{task_id}/tests",
        headers=_headers(USER_A_ID),
        json={"framework": "pytest", "test_path": "tests/test_slow.py", "timeout_seconds": 2},
    )
    elapsed = time.perf_counter() - started

    assert resp.status_code == 200, resp.text
    assert elapsed < 30, f"tests ran for {elapsed:.1f}s with a 2s timeout"
    assert resp.json()["status"] != "PASSED"


def test_api_repair_budget_cannot_be_exceeded_or_reset_by_restart(api_env):
    task_id = _running_task(api_env.client)

    task = api_env.session.get(AgentTask, UUID(task_id))
    task.repair_attempts_used = task.repair_attempts_max
    api_env.session.commit()

    first = api_env.client.post(f"/api/v1/tasks/{task_id}/repair", headers=_headers(USER_A_ID), json={})
    assert first.status_code == 409, first.text
    assert first.json()["error"]["code"] == "RETRY_BUDGET_EXHAUSTED"

    # Simulate a server restart: a brand-new orchestrator with empty in-memory state.
    fastapi_app.state.task_execution_orchestrator = TaskExecutionOrchestrator(
        workspace_manager=WorkspaceManager(base_workspaces_dir=api_env.tmp / "workspaces-after-restart")
    )
    second = api_env.client.post(f"/api/v1/tasks/{task_id}/repair", headers=_headers(USER_A_ID), json={})
    # Either the workspace is gone (404) or the budget is still enforced (409); never a new repair.
    assert second.status_code in (404, 409), second.text

    budget = api_env.client.get(f"/api/v1/tasks/{task_id}/repair-budget", headers=_headers(USER_A_ID))
    assert budget.status_code == 200
    assert budget.json()["is_budget_exhausted"] is True


@pytest.mark.parametrize(
    "target_files",
    [["config/secrets.yml"], ["Config/Secrets.yml"], ["../../outside.py"]],
)
def test_api_repair_cannot_write_forbidden_or_outside_files(api_env, target_files):
    task_id = _running_task(api_env.client)
    manager = api_env.orchestrator.workspace_manager
    root = manager.get_workspace_path(task_id)
    manager.write_file(
        task_id,
        "tests/test_discount.py",
        "from src.discount import apply_discount\n\n"
        "def test_discount():\n"
        "    assert apply_discount(100, 10) == 90\n",
    )

    resp = api_env.client.post(
        f"/api/v1/tasks/{task_id}/repair",
        headers=_headers(USER_A_ID),
        json={
            "framework": "pytest",
            "test_path": "tests/test_discount.py",
            "patch_diff": _SAFE_DIFF.replace("# fixed", "\n+    return 'pwned: true'"),
            "patch_explanation": "malicious repair",
            "target_files": target_files,
        },
    )
    del resp  # the call may succeed or fail; what matters is which files exist afterwards

    assert not (root / "config" / "secrets.yml").exists()
    assert not (root / "Config" / "Secrets.yml").exists()
    assert not (root.parent / "outside.py").exists()
    assert not (root.parent.parent / "outside.py").exists()
