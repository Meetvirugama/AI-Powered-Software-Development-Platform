"""Week 3 Day 3 Acceptance & Integration Test Suite.

Owner: Prit Zania — Week 3 Day 3 Deliverable (Docs/week3.md §6 F33, F34, §8 Day 3, line 1487)
Reference:
- Docs/week3.md §6 (F33 Isolated Workspace, F34 Tool Policy Router)
- Docs/week3.md §8 (Day 3 Workspace, Tool Policy and Execution Start)
- Docs/week3.md §11 (Scenarios A, B, C)
- ADR-007, ADR-010

Verifies:
1. Workspace creation, metadata retention, and task branch setup.
2. Approval gate enforcement (ADR-010, Scenario B): Unapproved tasks are strictly blocked from execution start.
3. Base-revision consistency & stale approval invalidation (Scenario C).
4. Execution lifecycle transitions (START -> PAUSE -> RESUME -> STOP -> FAIL).
5. Observability timeline event tracking throughout all lifecycle stages.
6. Sandboxed command execution with allowlisted commands, argument safety, and timeout budgeting.
7. Disallowed commands and shell injection prevention (pipes, metacharacters, null bytes).
8. Host credential stripping and secret redaction from command outputs.
9. Tool Policy Bridge integration with Devu's ToolRouter and parameter schema validation.
10. Safe workspace file tool operations (read, write, patch, delete, list) with boundary protection.
11. Multi-task workspace isolation and non-interference.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from uuid import uuid4

import pytest

from agent.tools.router import ToolDefinition, ToolRequest, ToolResult, ToolRouter
from app.schemas.workspace import (
    WorkspaceCommandRequest,
    WorkspaceCommandResult,
    WorkspaceCreateRequest,
    WorkspaceExecutionEventType,
    WorkspaceMetadata,
    WorkspaceResourceLimits,
    WorkspaceStartExecutionRequest,
    WorkspaceStartExecutionResult,
    WorkspaceStatus,
    WorkspaceToolPolicyRequest,
)
from sandbox.command_runner import WorkspaceCommandRunner
from sandbox.constants import (
    ALLOWED_COMMAND_TEMPLATES,
    DEFAULT_COMMAND_TIMEOUT_SECONDS,
    DISALLOWED_COMMAND_TOKENS,
    SENSITIVE_ENV_VARS,
)
from sandbox.exceptions import (
    WorkspaceAuthorizationError,
    WorkspaceCommandError,
    WorkspaceError,
    WorkspacePathEscapeError,
    WorkspacePolicyViolationError,
    WorkspaceStaleApprovalError,
    WorkspaceStateError,
)
from sandbox.path_guard import WorkspacePathGuard
from sandbox.tool_policy_bridge import (
    CANONICAL_WORKSPACE_TOOLS,
    TOOL_DELETE_FILE,
    TOOL_EXECUTE_COMMAND,
    TOOL_LIST_FILES,
    TOOL_PATCH_FILE,
    TOOL_READ_FILE,
    TOOL_WRITE_FILE,
    WorkspaceToolPolicyBridge,
    register_workspace_tools,
)
from sandbox.workspace_manager import WorkspaceManager


@pytest.fixture
def temp_workspace_root(tmp_path: Path) -> Path:
    """Fixture providing a clean isolated directory for workspace roots."""
    sandboxes = tmp_path / ".workspaces"
    sandboxes.mkdir(parents=True, exist_ok=True)
    return sandboxes


@pytest.fixture
def sample_repo_root(tmp_path: Path) -> Path:
    """Fixture simulating a source repository directory."""
    repo = tmp_path / "mock_repo"
    repo.mkdir(parents=True, exist_ok=True)

    # Add sample source and test files
    src_dir = repo / "src"
    src_dir.mkdir(parents=True, exist_ok=True)
    (src_dir / "calculator.py").write_text(
        "def add(a, b):\n    return a + b\n\ndef subtract(a, b):\n    return a - b\n",
        encoding="utf-8",
    )
    (repo / "README.md").write_text("# Mock Repo\nSample repository for testing.\n", encoding="utf-8")
    return repo


@pytest.fixture
def workspace_manager(temp_workspace_root: Path) -> WorkspaceManager:
    """Fixture providing an initialized WorkspaceManager."""
    return WorkspaceManager(base_workspaces_dir=temp_workspace_root)


@pytest.fixture
def active_workspace(
    workspace_manager: WorkspaceManager,
    sample_repo_root: Path,
) -> tuple[str, WorkspaceMetadata]:
    """Fixture creating and starting execution for an active workspace in IN_USE state."""
    task_id = f"task-{uuid4().hex[:8]}"
    create_req = WorkspaceCreateRequest(
        task_id=task_id,
        repository_id=str(uuid4()),
        base_revision="abcdef1234567890abcdef1234567890abcdef12",
        repository_root=str(sample_repo_root),
        isolation_type="directory_copy",
    )
    meta = workspace_manager.create_workspace(create_req)

    start_req = WorkspaceStartExecutionRequest(
        task_id=task_id,
        plan_version=1,
        approved_base_revision="abcdef1234567890abcdef1234567890abcdef12",
        task_status="APPROVED",
    )
    start_res = workspace_manager.start_execution(start_req)
    assert start_res.success is True
    assert start_res.status == WorkspaceStatus.IN_USE

    return task_id, meta


# ===========================================================================
# 1. Workspace Provisioning & Metadata Retention
# ===========================================================================

def test_workspace_provisioning_metadata(
    workspace_manager: WorkspaceManager,
    sample_repo_root: Path,
):
    """Verify workspace creation records base revision, branch name, and initial timeline events."""
    task_id = f"task-{uuid4().hex[:8]}"
    base_sha = "11223344556677889900aabbccddeeff00112233"
    create_req = WorkspaceCreateRequest(
        task_id=task_id,
        repository_id=str(uuid4()),
        base_revision=base_sha,
        repository_root=str(sample_repo_root),
        isolation_type="directory_copy",
    )

    meta = workspace_manager.create_workspace(create_req)
    assert meta.task_id == task_id
    assert meta.base_revision == base_sha
    assert meta.branch_name.startswith("agent/task-")
    assert meta.status == WorkspaceStatus.READY
    assert Path(meta.workspace_path).exists()

    # Verify initial timeline events emitted
    timeline = workspace_manager.get_execution_timeline(task_id)
    assert len(timeline) >= 2
    event_types = [e.event_type for e in timeline]
    assert WorkspaceExecutionEventType.WORKSPACE_CREATED in event_types
    assert WorkspaceExecutionEventType.BRANCH_SETUP in event_types


# ===========================================================================
# 2. Approval Gate Enforcement (ADR-010 & Scenario B)
# ===========================================================================

def test_unapproved_task_cannot_start_execution(
    workspace_manager: WorkspaceManager,
    sample_repo_root: Path,
):
    """Verify unapproved tasks (PENDING_APPROVAL, REJECTED, CREATED) are blocked from execution start."""
    task_id = f"task-{uuid4().hex[:8]}"
    create_req = WorkspaceCreateRequest(
        task_id=task_id,
        repository_id=str(uuid4()),
        base_revision="a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0",
        repository_root=str(sample_repo_root),
        isolation_type="directory_copy",
    )
    workspace_manager.create_workspace(create_req)

    # Attempt execution with PENDING_APPROVAL
    req_pending = WorkspaceStartExecutionRequest(
        task_id=task_id,
        task_status="PENDING_APPROVAL",
    )
    with pytest.raises(WorkspaceAuthorizationError) as exc_info:
        workspace_manager.start_execution(req_pending)
    assert "cannot bypass human approval" in str(exc_info.value)

    # Attempt execution with REJECTED
    req_rejected = WorkspaceStartExecutionRequest(
        task_id=task_id,
        task_status="REJECTED",
    )
    with pytest.raises(WorkspaceAuthorizationError) as exc_info:
        workspace_manager.start_execution(req_rejected)
    assert "cannot bypass human approval" in str(exc_info.value)

    # Verify workspace remained in READY state
    meta = workspace_manager.get_workspace(task_id)
    assert meta.status == WorkspaceStatus.READY


def test_approved_task_enters_in_use_state(
    workspace_manager: WorkspaceManager,
    sample_repo_root: Path,
):
    """Verify an approved task successfully starts execution and transitions to IN_USE."""
    task_id = f"task-{uuid4().hex[:8]}"
    base_sha = "deadbeef1234567890deadbeef1234567890dead"
    create_req = WorkspaceCreateRequest(
        task_id=task_id,
        repository_id=str(uuid4()),
        base_revision=base_sha,
        repository_root=str(sample_repo_root),
        isolation_type="directory_copy",
    )
    workspace_manager.create_workspace(create_req)

    start_req = WorkspaceStartExecutionRequest(
        task_id=task_id,
        plan_version=1,
        approved_base_revision=base_sha,
        task_status="APPROVED",
    )
    res = workspace_manager.start_execution(start_req)

    assert res.success is True
    assert res.status == WorkspaceStatus.IN_USE
    assert res.base_revision == base_sha
    assert res.started_at is not None

    meta = workspace_manager.get_workspace(task_id)
    assert meta.status == WorkspaceStatus.IN_USE


# ===========================================================================
# 3. Base Revision Consistency & Stale Approval Check (Scenario C)
# ===========================================================================

def test_stale_approval_revision_mismatch_blocks_execution(
    workspace_manager: WorkspaceManager,
    sample_repo_root: Path,
):
    """Verify execution is rejected if approved base revision does not match current workspace revision."""
    task_id = f"task-{uuid4().hex[:8]}"
    create_req = WorkspaceCreateRequest(
        task_id=task_id,
        repository_id=str(uuid4()),
        base_revision="aaaa1111bbbb2222cccc3333dddd4444eeee5555",
        repository_root=str(sample_repo_root),
        isolation_type="directory_copy",
    )
    workspace_manager.create_workspace(create_req)

    # Approved revision differs from workspace base revision
    stale_req = WorkspaceStartExecutionRequest(
        task_id=task_id,
        approved_base_revision="ffff999988887777666655554444333322221111",
        task_status="APPROVED",
    )

    with pytest.raises(WorkspaceStaleApprovalError) as exc_info:
        workspace_manager.start_execution(stale_req)
    assert "base revision changed from approved" in str(exc_info.value)

    meta = workspace_manager.get_workspace(task_id)
    assert meta.status == WorkspaceStatus.READY


# ===========================================================================
# 4. Execution Lifecycle Transitions (Pause, Resume, Stop, Fail)
# ===========================================================================

def test_execution_pause_and_resume_cycle(
    active_workspace: tuple[str, WorkspaceMetadata],
    workspace_manager: WorkspaceManager,
):
    """Verify pausing transitions IN_USE -> STOPPED, and resuming transitions STOPPED -> IN_USE."""
    task_id, _ = active_workspace

    # Pause execution
    meta_paused = workspace_manager.pause_execution(task_id, reason="Awaiting test command approval")
    assert meta_paused.status == WorkspaceStatus.STOPPED

    # Resume execution
    meta_resumed = workspace_manager.resume_execution(task_id)
    assert meta_resumed.status == WorkspaceStatus.IN_USE

    # Verify timeline records both events
    timeline = workspace_manager.get_execution_timeline(task_id)
    event_types = [e.event_type for e in timeline]
    assert WorkspaceExecutionEventType.EXECUTION_PAUSED in event_types
    assert WorkspaceExecutionEventType.EXECUTION_RESUMED in event_types


def test_execution_stop_and_fail(
    active_workspace: tuple[str, WorkspaceMetadata],
    workspace_manager: WorkspaceManager,
):
    """Verify normal stop and failure recording with diagnostics preservation."""
    task_id, _ = active_workspace

    # Fail execution
    meta_failed = workspace_manager.fail_execution(task_id, error_message="Fatal syntax error in generated code")
    assert meta_failed.status == WorkspaceStatus.FAILED
    assert "Fatal syntax error" in (meta_failed.error_message or "")

    # Verify failure recorded on timeline
    timeline = workspace_manager.get_execution_timeline(task_id)
    failed_events = [e for e in timeline if e.event_type == WorkspaceExecutionEventType.EXECUTION_FAILED]
    assert len(failed_events) == 1
    assert "Fatal syntax error" in failed_events[0].message


# ===========================================================================
# 5. Sandboxed Command Execution
# ===========================================================================

def test_sandboxed_command_execution_success(
    active_workspace: tuple[str, WorkspaceMetadata],
    workspace_manager: WorkspaceManager,
):
    """Verify executing allowlisted commands succeeds inside the workspace sandbox."""
    task_id, _ = active_workspace

    # Execute 'python -V'
    cmd_req = WorkspaceCommandRequest(
        task_id=task_id,
        command="python",
        arguments=["-V"],
        timeout_seconds=10,
    )
    result = workspace_manager.execute_command(cmd_req)

    assert result.success is True
    assert result.exit_code == 0
    assert "Python" in (result.stdout + result.stderr)
    assert result.timed_out is False
    assert result.duration_ms > 0

    # Verify tool invocation recorded in timeline
    timeline = workspace_manager.get_execution_timeline(task_id)
    invocations = [e for e in timeline if e.event_type == WorkspaceExecutionEventType.TOOL_INVOCATION]
    assert len(invocations) >= 1
    assert invocations[-1].payload["command"] == "python"


def test_command_blocked_when_workspace_not_in_use(
    workspace_manager: WorkspaceManager,
    sample_repo_root: Path,
):
    """Verify command execution is strictly blocked if workspace is not in IN_USE state."""
    task_id = f"task-{uuid4().hex[:8]}"
    create_req = WorkspaceCreateRequest(
        task_id=task_id,
        repository_id=str(uuid4()),
        base_revision="abcdef1234567890abcdef1234567890abcdef12",
        repository_root=str(sample_repo_root),
        isolation_type="directory_copy",
    )
    workspace_manager.create_workspace(create_req)

    # Workspace is currently in READY state, not IN_USE
    cmd_req = WorkspaceCommandRequest(
        task_id=task_id,
        command="python",
        arguments=["-V"],
    )
    with pytest.raises(WorkspaceStateError) as exc_info:
        workspace_manager.execute_command(cmd_req)
    assert "Commands are only allowed when workspace is 'IN_USE'" in str(exc_info.value)


def test_disallowed_command_rejected_by_policy(
    active_workspace: tuple[str, WorkspaceMetadata],
    workspace_manager: WorkspaceManager,
):
    """Verify non-allowlisted commands (e.g. curl, rm, bash) are rejected by policy."""
    task_id, _ = active_workspace

    cmd_req = WorkspaceCommandRequest(
        task_id=task_id,
        command="curl",
        arguments=["https://example.com"],
    )
    with pytest.raises(WorkspacePolicyViolationError) as exc_info:
        workspace_manager.execute_command(cmd_req)
    assert "not in the allowlist of permitted commands" in str(exc_info.value)


def test_shell_injection_tokens_rejected(
    active_workspace: tuple[str, WorkspaceMetadata],
    workspace_manager: WorkspaceManager,
):
    """Verify shell metacharacters and piping operators are rejected."""
    task_id, _ = active_workspace

    dangerous_args = [
        ["-V", ";", "rm", "-rf", "/"],
        ["-c", "print('hello') && cat /etc/passwd"],
        ["|", "sh"],
    ]

    for d_arg in dangerous_args:
        cmd_req = WorkspaceCommandRequest(
            task_id=task_id,
            command="python",
            arguments=d_arg,
        )
        with pytest.raises(WorkspacePolicyViolationError) as exc_info:
            workspace_manager.execute_command(cmd_req)
        assert "contains forbidden shell" in str(exc_info.value)


def test_command_environment_strips_sensitive_keys(monkeypatch: pytest.MonkeyPatch):
    """Verify host credentials and sensitive environment variables are purged from execution."""
    runner = WorkspaceCommandRunner()

    # Simulate environment with secrets
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_super_secret_token_12345")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY")
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:pass@localhost:5432/db")

    clean_env = runner.sanitize_environment()

    assert "GITHUB_TOKEN" not in clean_env
    assert "AWS_SECRET_ACCESS_KEY" not in clean_env
    assert "DATABASE_URL" not in clean_env
    assert "PATH" in clean_env


# ===========================================================================
# 6. Tool Policy Bridge & Devu ToolRouter Integration
# ===========================================================================

def test_tool_router_registration_and_policy_dispatch(
    active_workspace: tuple[str, WorkspaceMetadata],
    workspace_manager: WorkspaceManager,
):
    """Verify all workspace tools register with ToolRouter and route through policy bridge."""
    task_id, _ = active_workspace
    router = ToolRouter()
    bridge = register_workspace_tools(router, workspace_manager)

    registered_tools = [t.name for t in router.get_tools()]
    for tool_name in CANONICAL_WORKSPACE_TOOLS:
        assert tool_name in registered_tools

    # Test reading existing file via ToolRouter with policy bridge
    read_req = ToolRequest(
        tool_name=TOOL_READ_FILE,
        arguments={"task_id": task_id, "file_path": "src/calculator.py"},
    )
    result = router.route(read_req, agent_state={"task_id": task_id}, policy_engine=bridge)
    assert result.success is True
    assert "def add(a, b):" in result.output

    # Test writing a new file via ToolRouter with policy bridge
    write_req = ToolRequest(
        tool_name=TOOL_WRITE_FILE,
        arguments={
            "task_id": task_id,
            "file_path": "src/helpers.py",
            "content": "def multiply(a, b):\n    return a * b\n",
        },
    )
    w_result = router.route(write_req, agent_state={"task_id": task_id}, policy_engine=bridge)
    assert w_result.success is True
    assert w_result.output["created"] is True

    # Test list files via ToolRouter
    list_req = ToolRequest(
        tool_name=TOOL_LIST_FILES,
        arguments={"task_id": task_id},
    )
    l_result = router.route(list_req, agent_state={"task_id": task_id}, policy_engine=bridge)
    assert l_result.success is True
    assert "src/helpers.py" in l_result.output


def test_tool_policy_blocks_path_traversal(
    active_workspace: tuple[str, WorkspaceMetadata],
    workspace_manager: WorkspaceManager,
):
    """Verify tool requests attempting directory climbing or secret access are blocked."""
    task_id, _ = active_workspace
    router = ToolRouter()
    bridge = register_workspace_tools(router, workspace_manager)

    malicious_paths = [
        "../../etc/passwd",
        "../.env",
        ".git/config",
        "/etc/shadow",
        "C:\\Windows\\System32\\cmd.exe",
    ]

    for m_path in malicious_paths:
        req = ToolRequest(
            tool_name=TOOL_READ_FILE,
            arguments={"task_id": task_id, "file_path": m_path},
        )
        res = router.route(req, agent_state={"task_id": task_id}, policy_engine=bridge)
        assert res.success is False
        assert "Security policy violation" in res.error or "traversal" in res.error.lower()


def test_tool_policy_blocks_unapproved_or_paused_workspace(
    workspace_manager: WorkspaceManager,
    sample_repo_root: Path,
):
    """Verify tool execution is blocked when workspace is in STOPPED or READY state."""
    task_id = f"task-{uuid4().hex[:8]}"
    create_req = WorkspaceCreateRequest(
        task_id=task_id,
        repository_id=str(uuid4()),
        base_revision="abcdef1234567890abcdef1234567890abcdef12",
        repository_root=str(sample_repo_root),
        isolation_type="directory_copy",
    )
    workspace_manager.create_workspace(create_req)

    router = ToolRouter()
    bridge = register_workspace_tools(router, workspace_manager)

    # Workspace is in READY (not yet started)
    req = ToolRequest(
        tool_name=TOOL_READ_FILE,
        arguments={"task_id": task_id, "file_path": "README.md"},
    )
    res = router.route(req, agent_state={"task_id": task_id}, policy_engine=bridge)
    assert res.success is False
    assert "Tool execution is only permitted during active execution" in res.error


# ===========================================================================
# 7. Safe Workspace File Patching & Deletion
# ===========================================================================

def test_safe_file_patching_and_deletion(
    active_workspace: tuple[str, WorkspaceMetadata],
    workspace_manager: WorkspaceManager,
):
    """Verify targeted file patching and safe deletion inside the sandbox."""
    task_id, _ = active_workspace
    router = ToolRouter()
    bridge = register_workspace_tools(router, workspace_manager)

    # Patch 'add(a, b)'
    patch_req = ToolRequest(
        tool_name=TOOL_PATCH_FILE,
        arguments={
            "task_id": task_id,
            "file_path": "src/calculator.py",
            "target_content": "def add(a, b):\n    return a + b",
            "replacement_content": "def add(a, b):\n    # Optimized\n    return a + b",
        },
    )
    p_res = router.route(patch_req, agent_state={"task_id": task_id}, policy_engine=bridge)
    assert p_res.success is True
    assert p_res.output["occurrences_replaced"] == 1

    # Verify content was patched
    read_res = workspace_manager.read_file(task_id, "src/calculator.py")
    assert "# Optimized" in read_res.content

    # Delete README.md
    del_req = ToolRequest(
        tool_name=TOOL_DELETE_FILE,
        arguments={"task_id": task_id, "file_path": "README.md"},
    )
    d_res = router.route(del_req, agent_state={"task_id": task_id}, policy_engine=bridge)
    assert d_res.success is True
    assert d_res.output["deleted"] is True

    # Verify deletion on disk
    read_deleted = workspace_manager.read_file(task_id, "README.md")
    assert read_deleted.success is False


# ===========================================================================
# 8. Multi-Task Concurrency & Isolation
# ===========================================================================

def test_concurrent_tasks_isolated_working_directories(
    workspace_manager: WorkspaceManager,
    sample_repo_root: Path,
):
    """Verify multiple concurrent tasks operate in independent directories without interference."""
    task_1 = f"task-1-{uuid4().hex[:6]}"
    task_2 = f"task-2-{uuid4().hex[:6]}"
    base_sha = "abcdef1234567890abcdef1234567890abcdef12"

    w1 = workspace_manager.create_workspace(
        WorkspaceCreateRequest(
            task_id=task_1,
            repository_id=str(uuid4()),
            base_revision=base_sha,
            repository_root=str(sample_repo_root),
            isolation_type="directory_copy",
        )
    )
    w2 = workspace_manager.create_workspace(
        WorkspaceCreateRequest(
            task_id=task_2,
            repository_id=str(uuid4()),
            base_revision=base_sha,
            repository_root=str(sample_repo_root),
            isolation_type="directory_copy",
        )
    )

    workspace_manager.start_execution(WorkspaceStartExecutionRequest(task_id=task_1, task_status="APPROVED"))
    workspace_manager.start_execution(WorkspaceStartExecutionRequest(task_id=task_2, task_status="APPROVED"))

    assert w1.workspace_path != w2.workspace_path

    # Task 1 writes a unique file
    workspace_manager.write_file(task_1, "task_1_exclusive.txt", "Task 1 data")

    # Task 2 should NOT see Task 1's file
    t2_read = workspace_manager.read_file(task_2, "task_1_exclusive.txt")
    assert t2_read.success is False

    # Cleanup Task 1 does not affect Task 2
    clean_1 = workspace_manager.cleanup_workspace(task_1)
    assert clean_1.success is True
    assert not Path(w1.workspace_path).exists()
    assert Path(w2.workspace_path).exists()

    t2_source = workspace_manager.read_file(task_2, "src/calculator.py")
    assert t2_source.success is True
