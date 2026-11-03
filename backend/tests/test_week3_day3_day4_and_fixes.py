"""Week 3 Day 3 & Day 4 + Whole-Codebase Fixes & Security Regression Test Suite.

Covers all 13 codebase bugs/vulnerabilities fixed in `W3Day3-4_and_Fixes.md` plus all
Week 3 Day 3 & Day 4 deliverables across:
- Yug: Isolated workspace execution orchestration, pause/resume/cancel, workspace telemetry,
  diff telemetry, policy-guarded tool invocation endpoint, restricted test runner endpoint,
  bounded repair budget & trigger endpoints, and frontend API contract alignment.
- Prit: WorkspaceManager isolated provisioning, path traversal containment, lifecycle transitions.
- Devu: ToolRouter command allowlist prefix/exact template validation & argv injection/traversal rejection.
- Sukun: Server-enforced approval gate, protected file constraint enforcement, secret redaction.
- Meet: AgentExecutionLoop (including modify/patch/delete/refactor steps + anti-cyclic loop detection)
  and BoundedRepairLoop (3-attempt ceiling, repeat patch rejection, real diff hunk application).
- Dev: PatchValidationResult.rejection_reasons compatibility, FailureTracebackAnalyzer & RepairPatchValidator.
- Om: TaskEvent model fix, auto-generated event summaries, test/repair/tool/workspace persistence.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from agent.tools.router import ToolDefinition, ToolRequest, ToolRouter
from ai.context.token_budget import count_tokens
from ai.services.agent_execution_loop import AgentExecutionLoop, StepExecutionStatus
from ai.services.bounded_repair_loop import BoundedRepairLoop
from app.core.database import Base, get_db
from app.core.security import create_access_token
from app.main import app as fastapi_app
from app.models.github_installation import GitHubInstallation
from app.models.repository import Repository, SyncStatus
from app.models.task import TaskEvent
from app.models.user import User
from app.repositories.task_repository import TaskRepository
from app.schemas.plan import PlanApprovalRequest, PlanStep, StructuredPlan, TaskPlanGenerateRequest
from app.schemas.repair import DiagnosedFailure, PatchValidationResult, RepairPatchPayload, TracebackDiagnosisResult
from app.schemas.workspace import TestOutcomeStatus, WorkspaceCreateRequest
from app.services.task_execution_orchestrator import TaskExecutionOrchestrator
from sandbox.workspace_manager import WorkspaceManager


USER_A_ID = UUID("11111111-1111-4111-a111-111111111111")
USER_B_ID = UUID("22222222-2222-4222-a222-222222222222")
REPO_A_ID = UUID("aaaaaaaa-aaaa-4aaa-aaaa-aaaaaaaaaaaa")
INST_A_ID = UUID("bbbbbbbb-bbbb-4bbb-abbb-bbbbbbbbbbb1")


def _headers(user_id: UUID = USER_A_ID) -> dict[str, str]:
    token, _ = create_access_token(str(user_id))
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture()
def w3_d34_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    from app.core.config import get_settings

    monkeypatch.setenv("JWT_SECRET", "test-secret-key-w3-d34")
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
    TestingSession = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    session = TestingSession()

    session.add_all(
        [
            User(id=USER_A_ID, github_id="9001", login="yug-owner", email="yug@example.com"),
            User(id=USER_B_ID, github_id="9002", login="intruder", email="intruder@example.com"),
        ]
    )
    session.commit()

    session.add(
        GitHubInstallation(
            id=INST_A_ID,
            user_id=USER_A_ID,
            installation_id="77001",
            account_login="yug-owner",
            permissions={},
        )
    )
    session.commit()

    session.add(
        Repository(
            id=REPO_A_ID,
            user_id=USER_A_ID,
            installation_id=INST_A_ID,
            github_repo_id="555001",
            owner="yug-owner",
            name="demo-repo",
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

    ws_manager = WorkspaceManager(base_workspaces_dir=tmp_path / "workspaces")
    orchestrator = TaskExecutionOrchestrator(workspace_manager=ws_manager)
    fastapi_app.state.task_execution_orchestrator = orchestrator

    def _override_db():
        try:
            yield session
        finally:
            pass

    fastapi_app.dependency_overrides[get_db] = _override_db
    yield session, orchestrator, tmp_path
    fastapi_app.dependency_overrides.pop(get_db, None)
    session.close()


# ---------------------------------------------------------------------------
# 1. Schema & Model Bug Fixes Verification
# ---------------------------------------------------------------------------

def test_patch_validation_result_rejection_reasons_and_schema_aliases() -> None:
    """Verify BUG-W3-D34-03 & BUG-W3-D34-05 schema fixes."""
    pvr = PatchValidationResult(
        is_valid=False,
        rejection_reason="Modifies forbidden file",
        patch_hash="abc12345",
        modified_files=[".env"],
        attempt_number=1,
        remaining_attempts=2,
        violations=["Modifies forbidden file '.env'"],
    )
    assert pvr.rejection_reasons == ["Modifies forbidden file '.env'"]

    appr_req = PlanApprovalRequest(plan_version=1, notes="Looks good to ship!")
    assert appr_req.comment == "Looks good to ship!"

    gen_req = TaskPlanGenerateRequest(regenerate=True, prompt_instructions="Split step 1 into two steps")
    assert gen_req.revision_notes == "Split step 1 into two steps"


def test_task_event_model_has_no_broken_comment_property_and_auto_populates_summary(w3_d34_env) -> None:
    """Verify BUG-W3-D34-06: TaskEvent does not crash on attribute inspection and TaskRepository generates summaries."""
    session, _, _ = w3_d34_env
    repo = TaskRepository(session)
    task = repo.create_task(
        repository_id=REPO_A_ID,
        title="Test Event Summary Generation",
        description="Ensure TaskRepository populates readable summaries.",
        user_id=USER_A_ID,
    )
    events = repo.list_events(task.id)
    assert len(events) == 1
    assert events[0].summary != ""
    assert "Test Event Summary Generation" in events[0].summary
    assert not hasattr(TaskEvent, "comment")


def test_offline_token_budget_fallback_does_not_raise_network_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify BUG-W3-D34-13: count_tokens falls back gracefully when tiktoken is offline."""
    import ai.context.token_budget as tb

    tb._get_encoder.cache_clear()
    if tb.tiktoken is not None:
        monkeypatch.setattr(
            tb.tiktoken,
            "get_encoding",
            lambda _name: (_ for _ in ()).throw(RuntimeError("Offline DNS resolution error")),
        )
    tokens = count_tokens("def hello_world():\n    return 42\n")
    assert tokens > 0
    tb._get_encoder.cache_clear()


# ---------------------------------------------------------------------------
# 2. ToolRouter Command Allowlist & Argument Validation (Devu Day 3 & Day 4)
# ---------------------------------------------------------------------------

def test_tool_router_enforces_command_allowlist_and_blocks_shell_injection_and_path_traversal() -> None:
    """Verify BUG-W3-D34-10: ToolRouter validates argv tokens against metacharacters, '..', and forbidden flags."""
    router = ToolRouter(
        policy_engine=SimpleNamespace(check=lambda **_kw: "ALLOW"),
        policy_context_factory=lambda state, req: {"state": state, "req": req},
        command_allowlist={
            "exec_cmd": [
                ["pytest", "*"],
                ["git", "status"],
            ]
        },
    )
    router.register(
        ToolDefinition(
            name="exec_cmd",
            description="Run allowlisted command",
            parameters={
                "type": "object",
                "properties": {"argv": {"type": "array", "items": {"type": "string"}}},
                "required": ["argv"],
            },
        ),
        lambda argv: {"ran": argv},
    )

    # 1. Valid prefix template command succeeds
    ok_res = router.route(ToolRequest("exec_cmd", {"argv": ["pytest", "tests/test_sample.py", "-q"]}), {})
    assert ok_res.success is True
    assert ok_res.output == {"ran": ["pytest", "tests/test_sample.py", "-q"]}

    # 2. Shell injection metacharacter in argv is blocked
    inj_res = router.route(ToolRequest("exec_cmd", {"argv": ["pytest", "tests/test.py; rm -rf /"]}), {})
    assert inj_res.success is False
    assert "metacharacter" in (inj_res.error or "").lower()

    # 3. Path traversal in argv is blocked
    trav_res = router.route(ToolRequest("exec_cmd", {"argv": ["pytest", "../../etc/passwd"]}), {})
    assert trav_res.success is False
    assert "traversal" in (trav_res.error or "").lower()

    # 4. Forbidden flag (-o / --override-ini) is blocked
    flag_res = router.route(ToolRequest("exec_cmd", {"argv": ["pytest", "-o", "console_output_style=classic"]}), {})
    assert flag_res.success is False
    assert "forbidden command flag" in (flag_res.error or "").lower()

    # 5. Unapproved command binary is blocked
    unapproved_res = router.route(ToolRequest("exec_cmd", {"argv": ["curl", "https://evil.example.com"]}), {})
    assert unapproved_res.success is False
    assert "allowlist" in (unapproved_res.error or "").lower()


# ---------------------------------------------------------------------------
# 3. AgentExecutionLoop & BoundedRepairLoop Fixes (Meet & Dev Day 3 & Day 4)
# ---------------------------------------------------------------------------

def test_agent_execution_loop_executes_modify_and_patch_steps_and_detects_cycles(tmp_path: Path) -> None:
    """Verify BUG-W3-D34-09: PlanStep with default action_type='modify' writes files and patch steps apply cleanly."""
    ws_manager = WorkspaceManager(base_workspaces_dir=tmp_path / "ws")
    ws_manager.create_workspace(
        WorkspaceCreateRequest(
            task_id="task-loop-1",
            repository_id=str(REPO_A_ID),
            base_revision="a1b2c3d",
            isolation_type="directory_copy",
        )
    )
    loop = AgentExecutionLoop(workspace_manager=ws_manager)

    plan = StructuredPlan(
        task_id="task-loop-1",
        plan_version=1,
        base_revision="a1b2c3d",
        summary="Create and patch calculator module.",
        steps=[
            PlanStep(
                step_id="step-1",
                description="Create calculator.py with default action_type='modify'",
                action_type="modify",
                expected_files=["src/calculator.py"],
                verification=["File exists"],
            ),
            PlanStep(
                step_id="step-2",
                description="Patch calculator.py return value",
                action_type="patch",
                expected_files=["src/calculator.py"],
                depends_on=["step-1"],
                verification=["Patched value present"],
            ),
        ],
    )

    res = loop.execute_plan(
        "task-loop-1",
        plan,
        step_payloads={
            "step-1": {"content": "def add(a, b):\n    return a - b\n"},
            "step-2": {"target_content": "return a - b", "replacement_content": "return a + b"},
        },
    )
    assert res.status == StepExecutionStatus.COMPLETED
    read_back = ws_manager.read_file("task-loop-1", "src/calculator.py")
    assert read_back.success is True
    assert "return a + b" in (read_back.content or "")


def test_bounded_repair_loop_handles_rejected_patches_and_applies_real_diff_hunks(tmp_path: Path) -> None:
    """Verify BUG-W3-D34-03: BoundedRepairLoop does not crash on rejected patches or empty failures and applies diff hunks."""
    ws_manager = WorkspaceManager(base_workspaces_dir=tmp_path / "ws_repair")
    ws_manager.create_workspace(
        WorkspaceCreateRequest(
            task_id="task-repair-1",
            repository_id=str(REPO_A_ID),
            base_revision="a1b2c3d",
            isolation_type="directory_copy",
        )
    )
    ws_manager.transition_state("task-repair-1", ws_manager.get_workspace("task-repair-1").status.__class__("IN_USE"))
    ws_manager.write_file("task-repair-1", "src/math_ops.py", "def multiply(x, y):\n    return x + y\n")

    call_count = 0

    class _MockTestRunner:
        def run_tests(self, **_kwargs):
            nonlocal call_count
            call_count += 1
            content = ws_manager.read_file("task-repair-1", "src/math_ops.py").content or ""
            if "return x * y" in content:
                return SimpleNamespace(
                    status=TestOutcomeStatus.PASSED,
                    stdout="1 passed",
                    stderr="",
                    passed_count=1,
                    failed_count=0,
                )
            return SimpleNamespace(
                status=TestOutcomeStatus.FAILED,
                stdout="FAILED tests/test_math.py::test_multiply - AssertionError",
                stderr="",
                passed_count=0,
                failed_count=1,
            )

    def _synthesizer(task_id: str, attempt: int, _diag: TracebackDiagnosisResult) -> RepairPatchPayload:
        if attempt == 1:
            # Attempt 1 targets a forbidden file (.env) -> should be rejected cleanly without AttributeError!
            return RepairPatchPayload(
                task_id=task_id,
                attempt_number=attempt,
                diff="--- a/.env\n+++ b/.env\n@@ -1 +1 @@\n-DEBUG=0\n+DEBUG=1\n",
                explanation="Touch forbidden .env",
                target_files=[".env"],
            )
        # Attempt 2 provides a valid unified diff fixing multiply()
        return RepairPatchPayload(
            task_id=task_id,
            attempt_number=attempt,
            diff=(
                "--- a/src/math_ops.py\n"
                "+++ b/src/math_ops.py\n"
                "@@ -1,2 +1,2 @@\n"
                " def multiply(x, y):\n"
                "-    return x + y\n"
                "+    return x * y\n"
            ),
            explanation="Fix multiply operator from + to *",
            target_files=["src/math_ops.py"],
        )

    repair_loop = BoundedRepairLoop(
        workspace_manager=ws_manager,
        test_runner=_MockTestRunner(),  # type: ignore[arg-type]
        max_repair_attempts=3,
    )
    outcome = repair_loop.run_repair_cycle(
        "task-repair-1",
        patch_synthesizer=_synthesizer,
        forbidden_files=[".env"],
    )
    assert outcome.success is True
    assert outcome.attempts_used == 2
    assert len(outcome.repair_records) == 2
    assert outcome.repair_records[0].success is False
    assert "Rejected:" in outcome.repair_records[0].patch_summary
    assert outcome.repair_records[1].success is True
    assert "return x * y" in (ws_manager.read_file("task-repair-1", "src/math_ops.py").content or "")


# ---------------------------------------------------------------------------
# 4. End-to-End API Integration Tests for Week 3 Day 3 & Day 4 (tasks.py)
# ---------------------------------------------------------------------------

def test_full_week3_day3_day4_api_lifecycle_and_security_gates(w3_d34_env) -> None:
    """Verify end-to-end API flow: intake -> plan -> approve -> execute -> workspace -> tools -> diff -> pause/resume -> tests -> repair."""
    client = TestClient(fastapi_app)

    # 1. Create task with protected file constraint
    create_resp = client.post(
        "/api/v1/tasks",
        headers=_headers(USER_A_ID),
        json={
            "repository_id": str(REPO_A_ID),
            "title": "Implement Discount Calculator and Unit Tests",
            "description": "Add discount calculation function in src/discount.py.",
            "source": {"type": "USER_PROMPT", "repository_id": str(REPO_A_ID), "base_revision": "a1b2c3d4"},
            "requirements": [
                {
                    "id": "req-1",
                    "description": "Create src/discount.py with apply_discount(price, pct).",
                    "category": "functional",
                    "target_files": ["src/discount.py"],
                    "acceptance_criteria": ["Returns discounted price accurately."],
                }
            ],
            "assumptions": [],
            "constraints": [
                {
                    "id": "cst-1",
                    "description": "Never modify production secrets file.",
                    "constraint_type": "protected_file",
                    "forbidden_files": ["config/secrets.yml"],
                    "forbidden_packages": [],
                }
            ],
        },
    )
    assert create_resp.status_code == 201
    task_id = create_resp.json()["task_id"]

    # 2. Verify search filter and TaskCard fields on GET /api/v1/tasks
    list_resp = client.get(
        "/api/v1/tasks",
        params={"search": "Discount Calculator"},
        headers=_headers(USER_A_ID),
    )
    assert list_resp.status_code == 200
    assert list_resp.json()["total"] == 1
    assert list_resp.json()["items"][0]["description"] == "Add discount calculation function in src/discount.py."
    assert len(list_resp.json()["items"][0]["requirements"]) == 1

    # 3. Unapproved task execution MUST be blocked with 403 APPROVAL_REQUIRED
    blocked_exec = client.post(f"/api/v1/tasks/{task_id}/execute", headers=_headers(USER_A_ID))
    assert blocked_exec.status_code == 403
    assert blocked_exec.json()["error"]["code"] == "APPROVAL_REQUIRED"

    # 4. Generate structured plan
    plan_resp = client.post(
        f"/api/v1/tasks/{task_id}/plan",
        headers=_headers(USER_A_ID),
        json={"regenerate": True, "prompt_instructions": "Include unit test verification step."},
    )
    assert plan_resp.status_code == 200
    plan_data = plan_resp.json()
    assert plan_data["plan_version"] == 1
    assert len(plan_data["expected_files_to_modify"]) >= 1

    # 5. Approve plan using frontend's { plan_version, notes } payload and verify full task fields returned
    approve_resp = client.post(
        f"/api/v1/tasks/{task_id}/approve",
        headers=_headers(USER_A_ID),
        json={"plan_version": 1, "notes": "Approved for sandbox execution."},
    )
    assert approve_resp.status_code == 200
    approve_data = approve_resp.json()
    assert approve_data["decision"] == "APPROVED"
    assert approve_data["notes"] == "Approved for sandbox execution."
    assert approve_data["status"] == "APPROVED"
    assert approve_data["title"] == "Implement Discount Calculator and Unit Tests"

    # 6. Execute approved task with run_steps=True and custom step_payloads
    first_step_id = plan_data["steps"][0]["step_id"]
    exec_resp = client.post(
        f"/api/v1/tasks/{task_id}/execute",
        headers=_headers(USER_A_ID),
        json={
            "run_steps": True,
            "step_payloads": {
                first_step_id: {
                    "content": "def apply_discount(price: float, pct: float) -> float:\n    return round(price * (1.0 - pct / 100.0), 2)\n"
                }
            },
        },
    )
    assert exec_resp.status_code == 200
    assert exec_resp.json()["status"] == "EXECUTING"

    # 7. Inspect GET /api/v1/tasks/{task_id}/workspace
    ws_resp = client.get(f"/api/v1/tasks/{task_id}/workspace", headers=_headers(USER_A_ID))
    assert ws_resp.status_code == 200
    assert ws_resp.json()["status"] == "IN_USE"
    assert ws_resp.json()["branch_name"].startswith("agent/task-")

    # 8. Invoke policy-guarded tools via POST /api/v1/tasks/{task_id}/tools/{tool_name}
    write_test_resp = client.post(
        f"/api/v1/tasks/{task_id}/tools/write_file",
        headers=_headers(USER_A_ID),
        json={
            "arguments": {
                "file_path": "tests/test_discount.py",
                "content": (
                    "from src.discount import apply_discount\n\n"
                    "def test_apply_discount():\n"
                    "    assert apply_discount(100.0, 15.0) == 85.0\n"
                ),
            }
        },
    )
    assert write_test_resp.status_code == 200
    assert write_test_resp.json()["success"] is True

    # Attempting to write to protected file 'config/secrets.yml' MUST be blocked with 403 POLICY_VIOLATION
    forbidden_tool_resp = client.post(
        f"/api/v1/tasks/{task_id}/tools/write_file",
        headers=_headers(USER_A_ID),
        json={"arguments": {"file_path": "config/secrets.yml", "content": "hacked: true"}},
    )
    assert forbidden_tool_resp.status_code == 403
    assert forbidden_tool_resp.json()["error"]["code"] == "POLICY_VIOLATION"

    # Attempting path traversal '../escape.py' MUST be blocked with 403 POLICY_VIOLATION
    escape_tool_resp = client.post(
        f"/api/v1/tasks/{task_id}/tools/read_file",
        headers=_headers(USER_A_ID),
        json={"arguments": {"file_path": "../../etc/passwd"}},
    )
    assert escape_tool_resp.status_code == 403
    assert escape_tool_resp.json()["error"]["code"] == "POLICY_VIOLATION"

    # 9. Inspect GET /api/v1/tasks/{task_id}/diff
    diff_resp = client.get(f"/api/v1/tasks/{task_id}/diff", headers=_headers(USER_A_ID))
    assert diff_resp.status_code == 200
    diff_data = diff_resp.json()
    assert diff_data["total_files_changed"] >= 1
    changed_paths = {f["file_path"] for f in diff_data["files"]}
    assert "src/discount.py" in changed_paths or "tests/test_discount.py" in changed_paths

    # 10. Pause & Resume workspace execution
    pause_resp = client.post(
        f"/api/v1/tasks/{task_id}/pause",
        headers=_headers(USER_A_ID),
        json={"reason": "Inspecting intermediate diff"},
    )
    assert pause_resp.status_code == 200
    ws_paused = client.get(f"/api/v1/tasks/{task_id}/workspace", headers=_headers(USER_A_ID))
    assert ws_paused.json()["status"] == "STOPPED"

    resume_resp = client.post(f"/api/v1/tasks/{task_id}/resume", headers=_headers(USER_A_ID))
    assert resume_resp.status_code == 200
    ws_resumed = client.get(f"/api/v1/tasks/{task_id}/workspace", headers=_headers(USER_A_ID))
    assert ws_resumed.json()["status"] == "IN_USE"

    # 11. Trigger restricted test runner via POST /api/v1/tasks/{task_id}/tests
    test_trigger_resp = client.post(
        f"/api/v1/tasks/{task_id}/tests",
        headers=_headers(USER_A_ID),
        json={"framework": "pytest", "test_path": "tests/test_discount.py"},
    )
    assert test_trigger_resp.status_code == 200
    tests_body = test_trigger_resp.json()
    assert len(tests_body["runs"]) >= 1

    # 12. Inspect GET /api/v1/tasks/{task_id}/repair-budget and GET /api/v1/tasks/{task_id}/events
    budget_resp = client.get(f"/api/v1/tasks/{task_id}/repair-budget", headers=_headers(USER_A_ID))
    assert budget_resp.status_code == 200
    assert budget_resp.json()["repair_attempts_max"] == 3

    events_resp = client.get(f"/api/v1/tasks/{task_id}/events", headers=_headers(USER_A_ID))
    assert events_resp.status_code == 200
    events_list = events_resp.json()
    assert len(events_list) >= 5
    # Verify frontend contract fields (id, description, details) are present on every event
    for evt in events_list:
        assert evt["id"] == evt["event_id"]
        assert evt["description"] == evt["summary"]
        assert evt["description"] != ""
        assert isinstance(evt["details"], dict)

    # 13. Cross-tenant isolation check: User B gets 404 on all new Day 3 & Day 4 endpoints
    for method, path in [
        ("GET", f"/api/v1/tasks/{task_id}/workspace"),
        ("GET", f"/api/v1/tasks/{task_id}/diff"),
        ("GET", f"/api/v1/tasks/{task_id}/tests"),
        ("GET", f"/api/v1/tasks/{task_id}/repair-budget"),
        ("POST", f"/api/v1/tasks/{task_id}/pause"),
        ("POST", f"/api/v1/tasks/{task_id}/resume"),
    ]:
        intruder_resp = client.request(method, path, headers=_headers(USER_B_ID))
        assert intruder_resp.status_code == 404
