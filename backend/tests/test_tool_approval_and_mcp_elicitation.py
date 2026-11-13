"""Comprehensive Security Test Suite for Tool Approval Gate and MCP Elicitation.

Part of F19 — Human approval gate (Issue #199).
Tests:
1. ADR-010 Plan approval regression (version & hash binding preserved).
2. Tool risk tier classification and safe-deny default.
3. Deterministic canonical argument hashing and key-order invariance.
4. Tool approval lifecycle: request, approve, atomic single-use consumption, replay protection.
5. Rejection and expiration TTL enforcement.
6. Secret redaction invariant in database, responses, and audit logs.
7. Orchestrator interception of high-risk tools and automatic pending request provisioning.
8. MCP Form Elicitation: schema validation, valid response, invalid response rejection, duplicate/session protection.
9. MCP URL Elicitation: scheme enforcement, SSRF prevention, confirmation/cancellation.
10. MCP non-equivalence guarantee (elicitation does not authorize tool execution).
11. Full HTTP REST API endpoints for tool approvals and MCP elicitations.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from agent.tools.models import (
    APPROVAL_REQUIRED_THRESHOLD,
    RISK_TIER_WEIGHTS,
    ToolDefinition,
    ToolRequest,
    is_approval_required,
)
from agent.tools.router import ToolRouter
from app.core.database import Base, get_db
from app.core.errors import APIError, ErrorCode
from app.core.security import create_access_token
from app.main import app as fastapi_app
from app.models.github_installation import GitHubInstallation
from app.models.repository import Repository, SyncStatus
from app.models.task import (
    AgentTask,
    TaskApproval,
    TaskPlan,
    TaskStatus,
    ToolInvocation,
    ToolInvocationStatus,
)
from app.models.user import User
from app.repositories.task_repository import TaskRepository
from app.schemas.plan import PlanApprovalRequest, PlanStep, StructuredPlan
from app.schemas.task import TaskPlanCreateRequest
from app.services.mcp_elicitation_service import (
    MCPElicitationService,
    mcp_elicitation_service,
    validate_mcp_form_response,
    validate_mcp_form_schema,
    validate_mcp_url,
)
from app.services.task_execution_orchestrator import TaskExecutionOrchestrator
from app.services.tool_approval_gate import (
    ToolApprovalGateService,
    canonicalize_tool_arguments,
    compute_argument_hash,
    tool_approval_gate_service,
)
from sandbox.workspace_manager import WorkspaceManager

USER_A_ID = UUID("11111111-1111-4111-a111-111111111111")
USER_B_ID = UUID("22222222-2222-4222-a222-222222222222")
REPO_A_ID = UUID("aaaaaaaa-aaaa-4aaa-aaaa-aaaaaaaaaaaa")
INST_A_ID = UUID("bbbbbbbb-bbbb-4bbb-abbb-bbbbbbbbbbb1")


def _headers(user_id: UUID = USER_A_ID) -> dict[str, str]:
    token, _ = create_access_token(str(user_id))
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture()
def gate_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    from app.core.config import get_settings

    monkeypatch.setenv("JWT_SECRET", "test-secret-key-gate-199")
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
            User(id=USER_A_ID, github_id="9001", login="security-lead", email="sec@example.com"),
            User(id=USER_B_ID, github_id="9002", login="attacker", email="attacker@example.com"),
        ]
    )
    session.commit()

    session.add(
        GitHubInstallation(
            id=INST_A_ID,
            user_id=USER_A_ID,
            installation_id="77001",
            account_login="security-lead",
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
            owner="security-lead",
            name="secure-repo",
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


def _create_approved_task(session, title="Test Task", plan_version=1) -> tuple[AgentTask, TaskPlan]:
    repo = TaskRepository(session)
    task = repo.create_task(
        repository_id=REPO_A_ID,
        title=title,
        description="Testing approval gate",
        user_id=USER_A_ID,
    )
    plan_record = repo.save_plan(
        task=task,
        repository_id=REPO_A_ID,
        summary="Plan for execution",
        steps=[{"step_id": "step-1", "name": "Step 1", "description": "Executes safely"}],
        expected_files=[],
    )
    repo.approve_plan(task=task, approver_id=USER_A_ID, plan_version=plan_record.plan_version)
    session.commit()
    session.refresh(task)
    session.refresh(plan_record)
    return task, plan_record


# ---------------------------------------------------------------------------
# 1. ADR-010 Plan Approval Regression Tests
# ---------------------------------------------------------------------------

def test_adr010_plan_approval_gate_regression(gate_env) -> None:
    """Verify that ADR-010 plan approval verification remains strictly enforced."""
    session, orchestrator, _ = gate_env
    task, plan = _create_approved_task(session)
    repo = TaskRepository(session)

    # Verification passes when plan is approved with matching version and hash
    repo.verify_execution_approval_gate(task)

    # Corrupt the plan hash in database
    plan.plan_hash = "tampered_hash_123"
    session.commit()

    with pytest.raises(APIError) as exc_info:
        repo.verify_execution_approval_gate(task)
    assert exc_info.value.status_code == 409
    assert exc_info.value.code == ErrorCode.PLAN_VERSION_MISMATCH


# ---------------------------------------------------------------------------
# 2. Risk Tier Classification & Evaluation Tests
# ---------------------------------------------------------------------------

def test_risk_tier_classification_and_evaluation() -> None:
    """Verify risk tier weighting and approval threshold policy."""
    # Low / Read-only (< 30) do not require approval
    assert is_approval_required("read-only") is False
    assert is_approval_required("low") is False
    assert is_approval_required("local-write") is False
    assert is_approval_required("medium") is False

    # High / Write-external / Critical (>= 30) require human approval
    assert is_approval_required("write-external") is True
    assert is_approval_required("high") is True
    assert is_approval_required("critical") is True

    # Unknown or missing risk tier must safe-deny (require approval)
    assert is_approval_required(None) is True
    assert is_approval_required("") is True
    assert is_approval_required("unknown-tier") is True


# ---------------------------------------------------------------------------
# 3. Canonical Argument Hashing & Key-Order Invariance Tests
# ---------------------------------------------------------------------------

def test_canonical_argument_hashing_invariance_and_mutation() -> None:
    """Verify deterministic canonical serialization and tamper detection."""
    args1 = {"remote": "origin", "branch": "feature/sec", "force": False}
    args2 = {"force": False, "branch": "feature/sec", "remote": "origin"}

    hash1 = compute_argument_hash(args1)
    hash2 = compute_argument_hash(args2)

    # Invariant: Key order does not alter the digest
    assert hash1 == hash2
    assert len(hash1) == 64

    # Any argument mutation produces a distinct hash
    args_mutated = {"remote": "origin", "branch": "main", "force": False}
    hash_mutated = compute_argument_hash(args_mutated)
    assert hash_mutated != hash1

    # Empty and None arguments produce valid deterministic hashes
    assert compute_argument_hash(None) == compute_argument_hash({})


# ---------------------------------------------------------------------------
# 4. Tool Approval Lifecycle & Single-Use Consumption Tests
# ---------------------------------------------------------------------------

def test_tool_approval_lifecycle_and_single_use_consumption(gate_env) -> None:
    """Verify tool approval request, approval, consumption, and replay rejection."""
    session, _, _ = gate_env
    task, _ = _create_approved_task(session)
    gate = ToolApprovalGateService()

    tool_args = {"branch_name": "feat/my-tool", "remote_name": "origin"}

    # 1. Request tool approval
    approval = gate.request_tool_approval(
        session=session,
        task=task,
        tool_name="push_task_branch",
        arguments=tool_args,
        user_id=USER_A_ID,
        risk_tier="critical",
    )
    assert approval.status == "pending"
    assert approval.decision == "PENDING"
    assert approval.approval_type == "tool"
    assert approval.tool_name == "push_task_branch"
    assert approval.argument_hash == compute_argument_hash(tool_args)

    # 2. Approve the request
    approved = gate.approve_tool(
        session=session,
        task_id=task.id,
        approval_id=approval.id,
        user_id=USER_A_ID,
        feedback="LGTM, authorized to push",
    )
    assert approved.status == "approved"
    assert approved.decision == "APPROVED"
    assert approved.feedback == "LGTM, authorized to push"

    # 3. Verify and consume the tool approval (single-use guarantee)
    consumed = gate.verify_and_consume_tool(
        session=session,
        task=task,
        tool_name="push_task_branch",
        arguments=tool_args,
        user_id=USER_A_ID,
        risk_tier="critical",
    )
    assert consumed is not None
    assert consumed.status == "consumed"
    assert consumed.decision == "CONSUMED"
    assert consumed.consumed_at is not None

    # 4. Immediate replay attempt must fail (approval already consumed)
    with pytest.raises(APIError) as exc_info:
        gate.verify_and_consume_tool(
            session=session,
            task=task,
            tool_name="push_task_branch",
            arguments=tool_args,
            user_id=USER_A_ID,
            risk_tier="critical",
        )
    assert exc_info.value.status_code == 403
    assert exc_info.value.code == ErrorCode.APPROVAL_REQUIRED


# ---------------------------------------------------------------------------
# 5. Tool Approval Rejection & Expiration Tests
# ---------------------------------------------------------------------------

def test_tool_approval_rejection_and_expiration(gate_env) -> None:
    """Verify rejection state machine and TTL expiration."""
    session, _, _ = gate_env
    task, _ = _create_approved_task(session)
    gate = ToolApprovalGateService()

    tool_args = {"command": "rm -rf /tmp/test"}

    # Test Rejection
    approval = gate.request_tool_approval(
        session=session,
        task=task,
        tool_name="execute_command",
        arguments=tool_args,
        user_id=USER_A_ID,
        risk_tier="high",
    )
    rejected = gate.reject_tool(
        session=session,
        task_id=task.id,
        approval_id=approval.id,
        user_id=USER_A_ID,
        reason="Dangerous command denied",
    )
    assert rejected.status == "rejected"
    assert rejected.decision == "REJECTED"

    # Test Expiration on approve
    approval2 = gate.request_tool_approval(
        session=session,
        task=task,
        tool_name="delete_file",
        arguments={"file_path": "legacy.py"},
        user_id=USER_A_ID,
        risk_tier="high",
        expires_in_seconds=-1,  # immediate expiration
    )
    with pytest.raises(APIError) as exc_info:
        gate.approve_tool(session=session, task_id=task.id, approval_id=approval2.id, user_id=USER_A_ID)
    assert exc_info.value.status_code == 410
    assert exc_info.value.code == ErrorCode.APPROVAL_EXPIRED

    # Test Expiration on consume
    approval3 = gate.request_tool_approval(
        session=session,
        task=task,
        tool_name="execute_command",
        arguments={"argv": ["echo", "test"]},
        user_id=USER_A_ID,
        risk_tier="high",
        expires_in_seconds=3600,
    )
    gate.approve_tool(session=session, task_id=task.id, approval_id=approval3.id, user_id=USER_A_ID)
    # Manually expire the approved record
    approval3.expires_at = datetime.now(timezone.utc) - timedelta(seconds=60)
    session.commit()

    with pytest.raises(APIError) as exc_info2:
        gate.verify_and_consume_tool(
            session=session,
            task=task,
            tool_name="execute_command",
            arguments={"argv": ["echo", "test"]},
            user_id=USER_A_ID,
            risk_tier="high",
        )
    assert exc_info2.value.status_code == 410
    assert exc_info2.value.code == ErrorCode.APPROVAL_EXPIRED


# ---------------------------------------------------------------------------
# 6. Secret Redaction Invariant Tests
# ---------------------------------------------------------------------------

def test_secret_redaction_invariant_in_arguments(gate_env) -> None:
    """Verify raw secrets are masked in database records while hash binds original input."""
    session, _, _ = gate_env
    task, _ = _create_approved_task(session)
    gate = ToolApprovalGateService()

    raw_token = "ghp_123456789012345678901234567890123456"
    args_with_secret = {
        "remote_url": f"https://x-access-token:{raw_token}@github.com/org/repo.git",
        "api_key": "sk-abcdefghijklmnopqrstuvwxyz0123456789",
        "safe_param": "main",
    }

    approval = gate.request_tool_approval(
        session=session,
        task=task,
        tool_name="push_task_branch",
        arguments=args_with_secret,
        user_id=USER_A_ID,
        risk_tier="critical",
    )

    # 1. Raw secret is absent from stored sanitized_arguments
    sanitized = approval.sanitized_arguments
    assert raw_token not in str(sanitized)
    assert "sk-abcdefghijklmnopqrstuvwxyz0123456789" not in str(sanitized)
    assert "[REDACTED]" in str(sanitized)

    # 2. Argument hash cryptographically binds the original input
    expected_hash = compute_argument_hash(args_with_secret)
    assert approval.argument_hash == expected_hash


# ---------------------------------------------------------------------------
# 7. Orchestrator Interception of High-Risk Tools
# ---------------------------------------------------------------------------

def test_orchestrator_blocks_unapproved_high_risk_tool(gate_env) -> None:
    """Verify orchestrator blocks unapproved critical tools and auto-creates pending requests."""
    session, orchestrator, _ = gate_env
    task, _ = _create_approved_task(session)
    repo = TaskRepository(session)

    # Tool with risk_tier high (delete_file) without approval
    with pytest.raises(APIError) as exc_info:
        orchestrator.invoke_workspace_tool(
            task=task,
            task_repo=repo,
            tool_name="delete_file",
            arguments={"file_path": "legacy.py"},
            actor_id=USER_A_ID,
        )
    assert exc_info.value.status_code == 403
    assert exc_info.value.code == ErrorCode.APPROVAL_REQUIRED

    # Verify a pending approval request was automatically provisioned
    pending = session.execute(
        select(TaskApproval).where(
            TaskApproval.task_id == task.id,
            TaskApproval.approval_type == "tool",
            TaskApproval.tool_name == "delete_file",
            TaskApproval.status == "pending",
        )
    ).scalars().first()
    assert pending is not None

    # Verify blocked invocation recorded in audit log
    invocations = session.execute(
        select(ToolInvocation).where(
            ToolInvocation.task_id == task.id,
            ToolInvocation.tool_name == "delete_file",
        )
    ).scalars().all()
    assert len(invocations) >= 1
    assert invocations[0].status == ToolInvocationStatus.BLOCKED


# ---------------------------------------------------------------------------
# 8. MCP Form Elicitation Tests (MCP Spec 2025-11-25)
# ---------------------------------------------------------------------------

def test_mcp_form_elicitation_lifecycle(gate_env) -> None:
    """Verify MCP Form elicitation request, validation, response, and session boundary."""
    session, _, _ = gate_env
    task, _ = _create_approved_task(session)
    mcp = MCPElicitationService()

    schema = {
        "type": "object",
        "properties": {
            "deployment_env": {"type": "string"},
            "confirm_migration": {"type": "boolean"},
        },
        "required": ["deployment_env", "confirm_migration"],
    }

    # 1. Request Form Elicitation
    el = mcp.request_form_elicitation(
        session=session,
        task=task,
        session_id="session-mcp-42",
        prompt="Please specify target environment",
        schema=schema,
        user_id=USER_A_ID,
    )
    assert el.approval_type == "mcp_elicitation"
    assert el.elicitation_type == "form"
    assert el.status == "pending"

    # 2. Reject response from mismatched session
    with pytest.raises(APIError) as exc_info:
        mcp.submit_response(
            session=session,
            task_id=task.id,
            elicitation_id=el.id,
            session_id="session-intruder",
            action="submit",
            data={"deployment_env": "prod", "confirm_migration": True},
        )
    assert exc_info.value.status_code == 403

    # 3. Reject response violating schema (missing required field)
    with pytest.raises(APIError) as exc_info:
        mcp.submit_response(
            session=session,
            task_id=task.id,
            elicitation_id=el.id,
            session_id="session-mcp-42",
            action="submit",
            data={"deployment_env": "staging"},  # missing confirm_migration
        )
    assert exc_info.value.status_code == 400

    # 4. Submit valid response
    valid_resp = mcp.submit_response(
        session=session,
        task_id=task.id,
        elicitation_id=el.id,
        session_id="session-mcp-42",
        action="submit",
        data={"deployment_env": "staging", "confirm_migration": True},
        user_id=USER_A_ID,
    )
    assert valid_resp.status == "consumed"
    assert valid_resp.decision == "APPROVED"
    assert valid_resp.elicitation_response == {"deployment_env": "staging", "confirm_migration": True}

    # 5. Reject duplicate response (conflict)
    with pytest.raises(APIError) as exc_info:
        mcp.submit_response(
            session=session,
            task_id=task.id,
            elicitation_id=el.id,
            session_id="session-mcp-42",
            action="submit",
            data={"deployment_env": "staging", "confirm_migration": True},
        )
    assert exc_info.value.status_code == 409


# ---------------------------------------------------------------------------
# 9. MCP URL Elicitation & SSRF Prevention Tests
# ---------------------------------------------------------------------------

def test_mcp_url_elicitation_security(gate_env) -> None:
    """Verify URL validation, scheme enforcement, and SSRF prevention."""
    session, _, _ = gate_env
    task, _ = _create_approved_task(session)
    mcp = MCPElicitationService()

    # Valid HTTPS URL accepted
    url_el = mcp.request_url_elicitation(
        session=session,
        task=task,
        session_id="session-oauth",
        url="https://auth.example.com/oauth/authorize?client_id=123",
        purpose="Authorize GitHub integration",
        user_id=USER_A_ID,
    )
    assert url_el.elicitation_type == "url"
    assert url_el.status == "pending"

    # Malicious schemes rejected
    for bad_url in (
        "javascript:alert(1)",
        "data:text/html,<script>alert(1)</script>",
        "file:///etc/passwd",
        "ftp://example.com/file",
        "http://external-site.com",  # plain HTTP not allowed externally
    ):
        with pytest.raises(APIError) as exc_info:
            validate_mcp_url(bad_url)
        assert exc_info.value.code == ErrorCode.MCP_SECURITY_VIOLATION

    # SSRF / Cloud Metadata blocked
    for ssrf_url in (
        "https://169.254.169.254/latest/meta-data/",
        "https://metadata.google.internal/computeMetadata/v1/",
    ):
        with pytest.raises(APIError) as exc_info:
            validate_mcp_url(ssrf_url)
        assert exc_info.value.code == ErrorCode.MCP_SECURITY_VIOLATION


# ---------------------------------------------------------------------------
# 10. Non-Equivalence Guarantee (Elicitation != Tool Approval)
# ---------------------------------------------------------------------------

def test_mcp_elicitation_does_not_authorize_tool_execution(gate_env) -> None:
    """Verify non-equivalence: an approved elicitation does not bypass tool approval gate."""
    session, orchestrator, _ = gate_env
    task, _ = _create_approved_task(session)
    repo = TaskRepository(session)
    mcp = MCPElicitationService()

    # Create and complete an MCP elicitation
    el = mcp.request_url_elicitation(
        session=session,
        task=task,
        session_id="session-non-equiv",
        url="https://auth.example.com/login",
        purpose="Login",
        user_id=USER_A_ID,
    )
    mcp.submit_response(
        session=session,
        task_id=task.id,
        elicitation_id=el.id,
        session_id="session-non-equiv",
        action="confirm",
    )

    # Tool invocation with high risk tier STILL blocked despite completed elicitation
    with pytest.raises(APIError) as exc_info:
        orchestrator.invoke_workspace_tool(
            task=task,
            task_repo=repo,
            tool_name="delete_file",
            arguments={"file_path": "legacy.py"},
            actor_id=USER_A_ID,
        )
    assert exc_info.value.code == ErrorCode.APPROVAL_REQUIRED


# ---------------------------------------------------------------------------
# 11. Full HTTP REST API Endpoint Tests
# ---------------------------------------------------------------------------

def test_api_tool_approval_and_mcp_elicitation_endpoints(gate_env) -> None:
    """Test REST API routes for tool approval and MCP elicitation."""
    session, _, _ = gate_env
    task, _ = _create_approved_task(session)
    client = TestClient(fastapi_app)
    headers = _headers(USER_A_ID)

    # 1. POST /tasks/{id}/tool-approvals/request
    req_resp = client.post(
        f"/api/v1/tasks/{task.id}/tool-approvals/request",
        headers=headers,
        json={
            "tool_name": "create_draft_pr",
            "arguments": {"title": "My PR", "head_branch": "feat/1"},
            "risk_tier": "critical",
        },
    )
    assert req_resp.status_code == 200
    approval_data = req_resp.json()
    approval_id = approval_data["id"]
    assert approval_data["tool_name"] == "create_draft_pr"
    assert approval_data["status"] == "pending"

    # 2. GET /tasks/{id}/tool-approvals
    list_resp = client.get(f"/api/v1/tasks/{task.id}/tool-approvals", headers=headers)
    assert list_resp.status_code == 200
    assert len(list_resp.json()) >= 1

    # 3. POST /tasks/{id}/tool-approvals/{id}/approve
    approve_resp = client.post(
        f"/api/v1/tasks/{task.id}/tool-approvals/{approval_id}/approve",
        headers=headers,
        json={"feedback": "Approved by reviewer"},
    )
    assert approve_resp.status_code == 200
    assert approve_resp.json()["status"] == "approved"

    # 4. POST /tasks/{id}/mcp/elicitations/request
    mcp_req = client.post(
        f"/api/v1/tasks/{task.id}/mcp/elicitations/request",
        headers=headers,
        json={
            "session_id": "api-session-1",
            "elicitation_type": "url",
            "url": "https://api.github.com/docs",
            "purpose": "Review API documentation",
        },
    )
    assert mcp_req.status_code == 200
    elicitation_id = mcp_req.json()["id"]

    # 5. GET /tasks/{id}/mcp/elicitations
    mcp_list = client.get(f"/api/v1/tasks/{task.id}/mcp/elicitations", headers=headers)
    assert mcp_list.status_code == 200
    assert len(mcp_list.json()) >= 1

    # 6. POST /tasks/{id}/mcp/elicitations/{id}/respond
    mcp_resp = client.post(
        f"/api/v1/tasks/{task.id}/mcp/elicitations/{elicitation_id}/respond",
        headers=headers,
        json={"session_id": "api-session-1", "action": "confirm"},
    )
    assert mcp_resp.status_code == 200
    assert mcp_resp.json()["status"] == "consumed"

    # 7. GET /tasks/{id}/approvals (unified list)
    all_approvals = client.get(f"/api/v1/tasks/{task.id}/approvals", headers=headers)
    assert all_approvals.status_code == 200
    types = {a["approval_type"] for a in all_approvals.json()}
    assert "plan" in types or "tool" in types
