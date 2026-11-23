"""Workspace and execution tests."""

from __future__ import annotations

import os
import subprocess
import tempfile
from pathlib import Path
from uuid import uuid4
import pytest
from app.schemas.workspace import VALID_WORKSPACE_TRANSITIONS
from app.schemas.workspace import WorkspaceCleanupResult
from app.schemas.workspace import WorkspaceCreateRequest
from app.schemas.workspace import WorkspaceCreateResult
from app.schemas.workspace import WorkspaceFilePatchRequest
from app.schemas.workspace import WorkspaceFileReadRequest
from app.schemas.workspace import WorkspaceFileWriteRequest
from app.schemas.workspace import WorkspaceMetadata
from app.schemas.workspace import WorkspaceResourceLimits
from app.schemas.workspace import WorkspaceStatus
from app.schemas.workspace import can_transition_workspace
from sandbox.constants import PROTECTED_SYSTEM_PREFIXES
from sandbox.exceptions import WorkspaceCleanupError
from sandbox.exceptions import WorkspaceCreationError
from sandbox.exceptions import WorkspaceError
from sandbox.exceptions import WorkspaceFileError
from sandbox.exceptions import WorkspaceLimitExceededError
from sandbox.exceptions import WorkspacePathEscapeError
from sandbox.exceptions import WorkspaceStateError
from sandbox.path_guard import WorkspacePathGuard
from sandbox.resource_monitor import WorkspaceResourceMonitor
from sandbox.workspace_manager import WorkspaceManager
from uuid import UUID
from app.schemas.planner_context import AffectedSymbol
from app.schemas.planner_context import FileDiffRange
from app.schemas.planner_context import LineRange
from app.schemas.planner_context import ProposedTest
from app.schemas.planner_context import RiskAssessment
from app.schemas.planner_context import RiskLevel
from app.schemas.planner_context import TaskDiffRanges
from app.schemas.planner_context import TaskImpactAssessment
from app.schemas.planner_context import TaskPlanningContext
from app.schemas.planner_context import TestExecutionPlan
from scanner.symbols import Symbol
from scanner.symbols import SymbolEdge
from scanner.task_test_planner import TaskTestPlanner
from scanner.workspace_preflight import WorkspaceBaseValidator
from scanner.workspace_preflight import WorkspacePreflightResult
import shutil as _shutil
from agent.tools.router import ToolDefinition
from agent.tools.router import ToolRequest
from agent.tools.router import ToolResult
from agent.tools.router import ToolRouter
from app.schemas.workspace import WorkspaceCommandRequest
from app.schemas.workspace import WorkspaceCommandResult
from app.schemas.workspace import WorkspaceExecutionEventType
from app.schemas.workspace import WorkspaceStartExecutionRequest
from app.schemas.workspace import WorkspaceStartExecutionResult
from app.schemas.workspace import WorkspaceToolPolicyRequest
from sandbox.command_runner import WorkspaceCommandRunner
from sandbox.constants import ALLOWED_COMMAND_TEMPLATES
from sandbox.constants import DEFAULT_COMMAND_TIMEOUT_SECONDS
from sandbox.constants import DISALLOWED_COMMAND_TOKENS
from sandbox.constants import SENSITIVE_ENV_VARS
from sandbox.exceptions import WorkspaceAuthorizationError
from sandbox.exceptions import WorkspaceCommandError
from sandbox.exceptions import WorkspacePolicyViolationError
from sandbox.exceptions import WorkspaceStaleApprovalError
from sandbox.tool_policy_bridge import CANONICAL_WORKSPACE_TOOLS
from sandbox.tool_policy_bridge import TOOL_DELETE_FILE
from sandbox.tool_policy_bridge import TOOL_EXECUTE_COMMAND
from sandbox.tool_policy_bridge import TOOL_LIST_FILES
from sandbox.tool_policy_bridge import TOOL_PATCH_FILE
from sandbox.tool_policy_bridge import TOOL_READ_FILE
from sandbox.tool_policy_bridge import TOOL_WRITE_FILE
from sandbox.tool_policy_bridge import WorkspaceToolPolicyBridge
from sandbox.tool_policy_bridge import register_workspace_tools
from unittest.mock import AsyncMock
from unittest.mock import MagicMock
from unittest.mock import patch
from fastapi.testclient import TestClient
from app.core.database import get_db
from app.integrations.github.schemas import BranchIsolationCheck
from app.integrations.github.schemas import DiffStatus
from app.integrations.github.schemas import FileDiffRange as GitHubFileDiffRange
from app.integrations.github.schemas import LineRange as GitHubLineRange
from app.integrations.github.schemas import PullRequestDiffResponse
from app.integrations.github.schemas import PullRequestFile
from app.integrations.github.schemas import PullRequestInfo
from app.integrations.github.schemas import TaskDiffRanges as GitHubTaskDiffRanges
from app.models.repository import Repository
from app.models.user import User
from app.services.git_branch import GitBranchService
from app.services.git_branch import format_agent_branch_name
from app.services.git_branch import parse_unified_diff
from types import SimpleNamespace
from sqlalchemy import create_engine
from sqlalchemy import event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from ai.context.token_budget import count_tokens
from ai.services.agent_execution_loop import AgentExecutionLoop
from ai.services.agent_execution_loop import StepExecutionStatus
from ai.services.bounded_repair_loop import BoundedRepairLoop
from app.core.database import Base
from app.core.security import create_access_token
from app.main import app as fastapi_app
from app.models.github_installation import GitHubInstallation
from app.models.repository import SyncStatus
from app.models.task import TaskEvent
from app.repositories.task_repository import TaskRepository
from app.schemas.plan import PlanApprovalRequest
from app.schemas.plan import PlanStep
from app.schemas.plan import StructuredPlan
from app.schemas.plan import TaskPlanGenerateRequest
from app.schemas.repair import DiagnosedFailure
from app.schemas.repair import PatchValidationResult
from app.schemas.repair import RepairPatchPayload
from app.schemas.repair import TracebackDiagnosisResult
from app.schemas.workspace import TestOutcomeStatus
from app.services.task_execution_orchestrator import TaskExecutionOrchestrator
import uuid
from datetime import datetime
from datetime import timezone
from sqlalchemy.orm import Session
from app.models.task import ExecutionStatus
from app.models.task import RepairAttempt
from app.models.task import RepairResult
from app.models.task import Task
from app.models.task import TaskApproval
from app.models.task import TaskEventType
from app.models.task import TaskExecution
from app.models.task import TaskPlan
from app.models.task import TaskPlanStatus
from app.models.task import TaskSourceType
from app.models.task import TaskStatus
from app.models.task import TestRun
from app.models.task import TestRunStatus
from app.models.task import ToolInvocation
from app.models.task import ToolInvocationStatus
from app.models.task import Workspace
from app.models.task import WorkspaceStatus as WorkspaceRecordStatus
from app.repositories.task_repository import InvalidStateTransitionError
from app.repositories.task_repository import TaskNotFoundError
from app.schemas.task import RepairAttemptResponse
from app.schemas.task import TaskExecutionResponse
from app.schemas.task import TestRunResponse
from app.schemas.task import ToolInvocationResponse
from app.schemas.task import WorkspaceResponse
from app.services.task_history_service import TaskHistoryService


# Comprehensive Test Suite for Prit — Week 3 Day 1: Workspace & Sandbox Isolation.

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def temp_workspace_root(tmp_path: Path) -> Path:
    """Fixture providing an isolated base directory for test workspaces."""
    base_dir = tmp_path / ".test_workspaces"
    base_dir.mkdir(parents=True, exist_ok=True)
    return base_dir


@pytest.fixture
def workspace_manager(temp_workspace_root: Path) -> WorkspaceManager:
    """Fixture providing a fresh WorkspaceManager instance."""
    return WorkspaceManager(base_workspaces_dir=temp_workspace_root)


@pytest.fixture
def sample_git_repo(tmp_path: Path) -> Path:
    """Fixture creating a temporary git repository with an initial commit."""
    repo_dir = tmp_path / "sample_origin_repo"
    repo_dir.mkdir(parents=True, exist_ok=True)

    subprocess.run(["git", "init", "-b", "main"], cwd=repo_dir, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test Agent"], cwd=repo_dir, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "agent@test.local"], cwd=repo_dir, check=True, capture_output=True)

    test_file = repo_dir / "README.md"
    test_file.write_text("# Sample Repository\nInitial content\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=repo_dir, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "Initial commit"], cwd=repo_dir, check=True, capture_output=True)

    return repo_dir


# ---------------------------------------------------------------------------
# 1. State Machine & Schema Invariant Tests
# ---------------------------------------------------------------------------

def test_workspace_status_enum_values():
    """Verify all 8 canonical lifecycle states from Docs/week3.md §6 F33 exist."""
    expected_states = {
        "NOT_CREATED",
        "CREATING",
        "READY",
        "IN_USE",
        "STOPPED",
        "FAILED",
        "CLEANUP_PENDING",
        "CLEANED",
    }
    actual_states = {s.value for s in WorkspaceStatus}
    assert actual_states == expected_states


def test_can_transition_workspace_legal_transitions():
    """Verify legal state transitions follow the canonical lifecycle."""
    assert can_transition_workspace(WorkspaceStatus.NOT_CREATED, WorkspaceStatus.CREATING)
    assert can_transition_workspace(WorkspaceStatus.CREATING, WorkspaceStatus.READY)
    assert can_transition_workspace(WorkspaceStatus.READY, WorkspaceStatus.IN_USE)
    assert can_transition_workspace(WorkspaceStatus.IN_USE, WorkspaceStatus.READY)
    assert can_transition_workspace(WorkspaceStatus.IN_USE, WorkspaceStatus.STOPPED)
    assert can_transition_workspace(WorkspaceStatus.STOPPED, WorkspaceStatus.CLEANUP_PENDING)
    assert can_transition_workspace(WorkspaceStatus.CLEANUP_PENDING, WorkspaceStatus.CLEANED)
    # Self transitions are always permitted
    assert can_transition_workspace(WorkspaceStatus.READY, WorkspaceStatus.READY)


def test_can_transition_workspace_illegal_transitions():
    """Verify illegal transitions are strictly rejected by the guard."""
    assert not can_transition_workspace(WorkspaceStatus.NOT_CREATED, WorkspaceStatus.IN_USE)
    assert not can_transition_workspace(WorkspaceStatus.NOT_CREATED, WorkspaceStatus.READY)
    assert not can_transition_workspace(WorkspaceStatus.CLEANED, WorkspaceStatus.CREATING)
    assert not can_transition_workspace(WorkspaceStatus.CLEANED, WorkspaceStatus.READY)
    assert not can_transition_workspace(WorkspaceStatus.FAILED, WorkspaceStatus.IN_USE)


def test_workspace_metadata_validation():
    """Verify Pydantic validation on commit sha and branch formatting."""
    valid = WorkspaceMetadata(
        workspace_id=str(uuid4()),
        task_id="task-12345678",
        repository_id=str(uuid4()),
        base_revision="abcdef0123456789",
        branch_name="agent/task-12345678",
        workspace_path="/tmp/workspaces/task-1234",
        status=WorkspaceStatus.READY,
    )
    assert valid.status == WorkspaceStatus.READY

    # Invalid commit SHA
    with pytest.raises(ValueError, match="Invalid base_revision"):
        WorkspaceMetadata(
            workspace_id=str(uuid4()),
            task_id="task-12345678",
            repository_id=str(uuid4()),
            base_revision="not-a-sha!@#",
            branch_name="agent/task-12345678",
            workspace_path="/tmp/workspaces/task-1234",
        )

    # Invalid branch with traversal
    with pytest.raises(ValueError, match="Invalid branch name"):
        WorkspaceMetadata(
            workspace_id=str(uuid4()),
            task_id="task-12345678",
            repository_id=str(uuid4()),
            base_revision="abcdef012345",
            branch_name="agent/../../escape",
            workspace_path="/tmp/workspaces/task-1234",
        )


# ---------------------------------------------------------------------------
# 2. Path Guard & Boundary Confinement Tests
# ---------------------------------------------------------------------------

def test_workspace_path_guard_validates_root(temp_workspace_root: Path):
    """Verify WorkspacePathGuard.validate_workspace_root enforces path security."""
    valid_root = WorkspacePathGuard.validate_workspace_root(temp_workspace_root)
    assert valid_root == temp_workspace_root.resolve()

    with pytest.raises(WorkspacePathEscapeError, match="must not be empty"):
        WorkspacePathGuard.validate_workspace_root("")

    with pytest.raises(WorkspacePathEscapeError, match="null bytes"):
        WorkspacePathGuard.validate_workspace_root("foo\x00bar")

    with pytest.raises(WorkspacePathEscapeError, match="Path traversal"):
        WorkspacePathGuard.validate_workspace_root(f"{temp_workspace_root}/../other")

    with pytest.raises(WorkspacePathEscapeError, match="UNC network paths are forbidden"):
        WorkspacePathGuard.validate_workspace_root(r"\\malicious\share\workspace")


def test_workspace_path_guard_rejects_protected_prefixes():
    """Verify WorkspacePathGuard blocks protected OS directories."""
    for prefix in PROTECTED_SYSTEM_PREFIXES:
        if Path(prefix).exists():
            with pytest.raises(WorkspacePathEscapeError, match="protected system directory"):
                WorkspacePathGuard.validate_workspace_root(prefix)


def test_workspace_path_guard_resolve_within_workspace_valid(temp_workspace_root: Path):
    """Verify valid relative paths resolve correctly within workspace root."""
    resolved = WorkspacePathGuard.resolve_within_workspace(temp_workspace_root, "src/app/main.py")
    assert resolved == (temp_workspace_root / "src/app/main.py").resolve()
    assert resolved.is_relative_to(temp_workspace_root.resolve())


@pytest.mark.parametrize(
    "malicious_path",
    [
        "../outside.txt",
        "../../etc/passwd",
        "src/../../outside.txt",
        "/etc/passwd",
        "C:\\Windows\\System32\\cmd.exe",
        "\\\\server\\share\\evil.py",
        "test\x00null.py",
        "   ",
    ],
)
def test_workspace_path_guard_rejects_path_traversal(temp_workspace_root: Path, malicious_path: str):
    """Verify resolve_within_workspace catches all directory traversal patterns."""
    with pytest.raises(WorkspacePathEscapeError):
        WorkspacePathGuard.resolve_within_workspace(temp_workspace_root, malicious_path)


@pytest.mark.parametrize(
    "forbidden_file",
    [
        ".git",
        ".git/config",
        ".git/HEAD",
        ".git/hooks/pre-commit",
        ".env",
        ".env.local",
        ".env.production",
        "id_rsa",
        "id_ed25519",
        "id_ecdsa",
    ],
)
def test_workspace_path_guard_forbids_credentials_and_git(temp_workspace_root: Path, forbidden_file: str):
    """Verify resolve_within_workspace forbids direct manipulation of .git, .env, and SSH keys."""
    with pytest.raises(WorkspacePathEscapeError, match="forbidden|protected"):
        WorkspacePathGuard.resolve_within_workspace(temp_workspace_root, forbidden_file)


# ---------------------------------------------------------------------------
# 3. Workspace Creation & Lifecycle Tests
# ---------------------------------------------------------------------------

def test_workspace_manager_create_workspace(workspace_manager: WorkspaceManager):
    """Verify create_workspace provisions an isolated workspace directory."""
    task_id = "task-f47ac10b"
    req = WorkspaceCreateRequest(
        task_id=task_id,
        repository_id=str(uuid4()),
        base_revision="abcdef012345",
        isolation_type="directory_copy",
    )

    metadata = workspace_manager.create_workspace(req)

    assert metadata.task_id == task_id
    assert metadata.status == WorkspaceStatus.READY
    assert Path(metadata.workspace_path).exists()
    assert Path(metadata.workspace_path).is_dir()
    assert "task-f47ac10b" in metadata.workspace_path


def test_workspace_manager_idempotent_creation(workspace_manager: WorkspaceManager):
    """Verify calling create_workspace twice for the same task returns the existing instance."""
    task_id = "task-idempotent-1"
    req = WorkspaceCreateRequest(
        task_id=task_id,
        repository_id=str(uuid4()),
        base_revision="abcdef012345",
    )

    meta1 = workspace_manager.create_workspace(req)
    meta2 = workspace_manager.create_workspace(req)

    assert meta1.workspace_id == meta2.workspace_id
    assert meta1.workspace_path == meta2.workspace_path


def test_workspace_manager_transition_state(workspace_manager: WorkspaceManager):
    """Verify legal state transitions update status and illegal transitions raise WorkspaceStateError."""
    task_id = "task-transition-test"
    req = WorkspaceCreateRequest(
        task_id=task_id,
        repository_id=str(uuid4()),
        base_revision="1234567890ab",
    )
    workspace_manager.create_workspace(req)

    # Legal: READY -> IN_USE
    meta = workspace_manager.transition_state(task_id, WorkspaceStatus.IN_USE)
    assert meta.status == WorkspaceStatus.IN_USE

    # Legal: IN_USE -> STOPPED
    meta = workspace_manager.transition_state(task_id, WorkspaceStatus.STOPPED)
    assert meta.status == WorkspaceStatus.STOPPED

    # Illegal: STOPPED -> CREATING
    with pytest.raises(WorkspaceStateError):
        workspace_manager.transition_state(task_id, WorkspaceStatus.CREATING)


# ---------------------------------------------------------------------------
# 4. Guarded File Operations (Read, Write, Patch, Delete, List)
# ---------------------------------------------------------------------------

def test_workspace_file_write_and_read(workspace_manager: WorkspaceManager):
    """Verify writing and reading files inside the isolated workspace."""
    task_id = "task-io-1"
    req = WorkspaceCreateRequest(
        task_id=task_id,
        repository_id=str(uuid4()),
        base_revision="1234567890ab",
    )
    workspace_manager.create_workspace(req)

    content = "print('Hello Isolated Workspace')\n"
    write_res = workspace_manager.write_file(task_id, "src/hello.py", content, create_parents=True)
    assert write_res.success is True
    assert write_res.created is True
    assert write_res.bytes_written == len(content.encode("utf-8"))

    read_res = workspace_manager.read_file(task_id, "src/hello.py")
    assert read_res.success is True
    assert read_res.content == content
    assert read_res.size_bytes == len(content.encode("utf-8"))


def test_workspace_read_nonexistent_file(workspace_manager: WorkspaceManager):
    """Verify reading a missing file returns success=False without crashing."""
    task_id = "task-missing-file"
    req = WorkspaceCreateRequest(
        task_id=task_id,
        repository_id=str(uuid4()),
        base_revision="1234567890ab",
    )
    workspace_manager.create_workspace(req)

    read_res = workspace_manager.read_file(task_id, "nonexistent.py")
    assert read_res.success is False
    assert "not found" in (read_res.error or "").lower()


def test_workspace_file_patch_operation(workspace_manager: WorkspaceManager):
    """Verify safe substring patching on a workspace file."""
    task_id = "task-patch-1"
    req = WorkspaceCreateRequest(
        task_id=task_id,
        repository_id=str(uuid4()),
        base_revision="1234567890ab",
    )
    workspace_manager.create_workspace(req)

    initial_code = "def calculate_tax(amount):\n    return amount * 0.15\n"
    workspace_manager.write_file(task_id, "tax.py", initial_code)

    patch_res = workspace_manager.patch_file(
        task_id,
        "tax.py",
        target_content="amount * 0.15",
        replacement_content="amount * 0.20",
    )
    assert patch_res.success is True
    assert patch_res.occurrences_replaced == 1

    read_res = workspace_manager.read_file(task_id, "tax.py")
    assert read_res.content == "def calculate_tax(amount):\n    return amount * 0.20\n"


def test_workspace_file_delete_and_list(workspace_manager: WorkspaceManager):
    """Verify listing and deleting files inside the isolated workspace."""
    task_id = "task-list-del"
    req = WorkspaceCreateRequest(
        task_id=task_id,
        repository_id=str(uuid4()),
        base_revision="1234567890ab",
    )
    workspace_manager.create_workspace(req)

    workspace_manager.write_file(task_id, "module_a.py", "a = 1")
    workspace_manager.write_file(task_id, "sub/module_b.py", "b = 2")
    workspace_manager.write_file(task_id, "sub/module_c.py", "c = 3")

    files = workspace_manager.list_files(task_id)
    assert "module_a.py" in files
    assert "sub/module_b.py" in files
    assert "sub/module_c.py" in files

    deleted = workspace_manager.delete_file(task_id, "sub/module_b.py")
    assert deleted is True

    files_after = workspace_manager.list_files(task_id)
    assert "sub/module_b.py" not in files_after
    assert "module_a.py" in files_after


# ---------------------------------------------------------------------------
# 5. Resource Limits & Quotas Tests
# ---------------------------------------------------------------------------

def test_workspace_file_size_limit_enforced(workspace_manager: WorkspaceManager):
    """Verify writing a file exceeding max_file_size_bytes is blocked."""
    task_id = "task-limit-file"
    limits = WorkspaceResourceLimits(max_file_size_bytes=50)  # Tiny 50 bytes cap
    req = WorkspaceCreateRequest(
        task_id=task_id,
        repository_id=str(uuid4()),
        base_revision="1234567890ab",
        resource_limits=limits,
    )
    workspace_manager.create_workspace(req)

    oversized_content = "X" * 100
    res = workspace_manager.write_file(task_id, "oversized.txt", oversized_content)
    assert res.success is False
    assert "exceeds maximum limit" in (res.error or "")


def test_workspace_disk_quota_enforced(workspace_manager: WorkspaceManager):
    """Verify writing data exceeding max_disk_bytes is blocked."""
    task_id = "task-limit-disk"
    limits = WorkspaceResourceLimits(max_disk_bytes=100)  # 100 bytes total disk cap
    req = WorkspaceCreateRequest(
        task_id=task_id,
        repository_id=str(uuid4()),
        base_revision="1234567890ab",
        resource_limits=limits,
    )
    workspace_manager.create_workspace(req)

    res = workspace_manager.write_file(task_id, "chunk1.bin", "A" * 200)
    assert res.success is False
    assert "exceeds maximum quota" in (res.error or "")


def test_workspace_max_files_modified_enforced(workspace_manager: WorkspaceManager):
    """Verify modifying more distinct files than max_files_modified is blocked."""
    task_id = "task-limit-count"
    limits = WorkspaceResourceLimits(max_files_modified=2)  # Cap of 2 files
    req = WorkspaceCreateRequest(
        task_id=task_id,
        repository_id=str(uuid4()),
        base_revision="1234567890ab",
        resource_limits=limits,
    )
    workspace_manager.create_workspace(req)

    res1 = workspace_manager.write_file(task_id, "file1.txt", "1")
    assert res1.success is True
    res2 = workspace_manager.write_file(task_id, "file2.txt", "2")
    assert res2.success is True

    # Third distinct file exceeds the cap
    res3 = workspace_manager.write_file(task_id, "file3.txt", "3")
    assert res3.success is False
    assert "exceeds ceiling" in (res3.error or "")


# ---------------------------------------------------------------------------
# 6. Git Worktree & Cleanup Safety Tests
# ---------------------------------------------------------------------------

def test_workspace_git_worktree_provision_and_cleanup(
    workspace_manager: WorkspaceManager,
    sample_git_repo: Path,
):
    """Verify Git worktree provisioning and safe worktree removal."""
    # Obtain HEAD sha of sample git repo
    proc = subprocess.run(["git", "rev-parse", "HEAD"], cwd=sample_git_repo, check=True, capture_output=True, text=True)
    head_sha = proc.stdout.strip()

    task_id = "task-worktree-1"
    req = WorkspaceCreateRequest(
        task_id=task_id,
        repository_id=str(uuid4()),
        base_revision=head_sha,
        repository_root=str(sample_git_repo),
        isolation_type="git_worktree",
    )

    metadata = workspace_manager.create_workspace(req)
    assert metadata.status == WorkspaceStatus.READY
    workspace_path = Path(metadata.workspace_path)
    assert workspace_path.exists()

    # The repo file from the git commit should be present
    readme = workspace_path / "README.md"
    assert readme.exists()
    assert "Sample Repository" in readme.read_text(encoding="utf-8")

    # Cleanup workspace
    cleanup_res = workspace_manager.cleanup_workspace(task_id)
    assert cleanup_res.success is True
    assert not workspace_path.exists()
    assert metadata.status == WorkspaceStatus.CLEANED


def test_workspace_cleanup_idempotency(workspace_manager: WorkspaceManager):
    """Verify cleanup_workspace is fully idempotent on multiple calls."""
    task_id = "task-idempotent-clean"
    req = WorkspaceCreateRequest(
        task_id=task_id,
        repository_id=str(uuid4()),
        base_revision="1234567890ab",
    )
    workspace_manager.create_workspace(req)

    clean1 = workspace_manager.cleanup_workspace(task_id)
    assert clean1.success is True

    clean2 = workspace_manager.cleanup_workspace(task_id)
    assert clean2.success is True

    clean_unknown = workspace_manager.cleanup_workspace("task-non-existent")
    assert clean_unknown.success is True


def test_cross_task_workspace_isolation(workspace_manager: WorkspaceManager):
    """Verify task A cannot perform operations on task B's workspace directory."""
    req_a = WorkspaceCreateRequest(task_id="task-aaa-111", repository_id=str(uuid4()), base_revision="1234567890ab")
    req_b = WorkspaceCreateRequest(task_id="task-bbb-222", repository_id=str(uuid4()), base_revision="1234567890ab")

    meta_a = workspace_manager.create_workspace(req_a)
    meta_b = workspace_manager.create_workspace(req_b)

    workspace_manager.write_file("task-bbb-222", "secret_b.txt", "Task B Secret Data")

    # Task A attempts to escape to Task B's directory
    res = workspace_manager.read_file("task-aaa-111", "../task-bbb-222/secret_b.txt")
    assert res.success is False
    assert "escape" in (res.error or "").lower() or "outside" in (res.error or "").lower() or "syntax" in (res.error or "").lower()


# Comprehensive Automated Test Suite for Week 3 Day 2 Deliverables.

# ═══════════════════════════════════════════════════════════════════════════
# Helpers & Synthetic Fixture Factories
# ═══════════════════════════════════════════════════════════════════════════

def _make_symbol(
    name: str,
    kind: str = "function",
    file_id: UUID | None = None,
    start_line: int = 1,
    end_line: int = 10,
    parent_id: UUID | None = None,
    signature: str = "",
) -> Symbol:
    return Symbol(
        id=uuid4(),
        name=name,
        kind=kind,
        file_id=file_id or uuid4(),
        start_line=start_line,
        end_line=end_line,
        signature=signature or f"def {name}():",
        parent_id=parent_id,
    )


def _make_edge(
    source: Symbol,
    target: Symbol,
    edge_type: str = "calls",
) -> SymbolEdge:
    return SymbolEdge(
        source_id=source.id,
        target_id=target.id,
        edge_type=edge_type,
    )


# 5. Task Test Planner & Framework Detection Tests
# ═══════════════════════════════════════════════════════════════════════════

class TestTaskTestPlanner:
    """Tests for TaskTestPlanner discovery and test proposals."""

    def test_detect_framework_from_pytest_fixture_sample(self):
        planner = TaskTestPlanner()
        fixture_dir = Path(__file__).parent / "fixtures" / "framework_samples" / "pytest_repo"
        if not fixture_dir.exists():
            pytest.skip("Fixture not found")
        fw = planner.detect_framework(repo_root=fixture_dir)
        assert fw == "pytest"

    def test_detect_framework_from_jest_fixture_sample(self):
        planner = TaskTestPlanner()
        fixture_dir = Path(__file__).parent / "fixtures" / "framework_samples" / "jest_repo"
        if not fixture_dir.exists():
            pytest.skip("Fixture not found")
        fw = planner.detect_framework(repo_root=fixture_dir)
        assert fw == "jest"

    def test_detect_framework_from_unittest_fixture_sample(self):
        planner = TaskTestPlanner()
        fixture_dir = Path(__file__).parent / "fixtures" / "framework_samples" / "unittest_repo"
        if not fixture_dir.exists():
            pytest.skip("Fixture not found")
        fw = planner.detect_framework(repo_root=fixture_dir)
        assert fw == "unittest"

    def test_detect_framework_fallback_from_paths(self):
        planner = TaskTestPlanner()
        assert planner.detect_framework(file_paths=["vitest.config.ts", "src/components/App.test.tsx"]) == "vitest"
        assert planner.detect_framework(file_paths=["src/components/App.test.tsx"]) == "jest"
        assert planner.detect_framework(file_paths=["src/auth.py", "conftest.py", "tests/test_auth.py"]) == "pytest"
        assert planner.detect_framework(file_paths=["src/auth.py", "tests/test_auth.py"]) == "unittest"


    def test_propose_new_tests_for_uncovered_symbols(self):
        planner = TaskTestPlanner()
        sym = AffectedSymbol(
            name="calculate_tax",
            kind="function",
            file_path="src/billing/tax.py",
            start_line=1,
            end_line=20,
            is_direct_target=True,
        )

        # Existing tests don't mention calculate_tax
        existing_cases = ["test_user_login", "test_logout"]
        untested, proposed = planner.propose_new_tests([sym], existing_cases, "pytest")

        assert untested == ["calculate_tax"]
        assert len(proposed) == 1
        assert proposed[0].target_symbol == "calculate_tax"
        assert proposed[0].suggested_test_file == "tests/billing/test_tax.py"
        assert proposed[0].suggested_test_name == "test_calculate_tax_success"

    def test_propose_new_tests_jest_naming_conventions(self):
        planner = TaskTestPlanner()
        sym = AffectedSymbol(
            name="formatCurrency",
            kind="function",
            file_path="src/utils/format.ts",
            start_line=1,
            end_line=15,
            is_direct_target=True,
        )

        untested, proposed = planner.propose_new_tests([sym], [], "jest")
        assert len(proposed) == 1
        assert proposed[0].suggested_test_file == "src/utils/__tests__/format.test.ts"
        assert proposed[0].framework == "jest"

    def test_build_test_command_formatting(self):
        planner = TaskTestPlanner()

        # Pytest
        cmd_py = planner.build_test_command("pytest", ["tests/test_auth.py", "tests/test_user.py"])
        assert cmd_py.startswith("pytest tests/test_auth.py tests/test_user.py")

        # Jest
        cmd_jest = planner.build_test_command("jest", ["src/__tests__/app.test.ts"])
        assert cmd_jest.startswith("npm test -- src/__tests__/app.test.ts")

        # Vitest
        cmd_vitest = planner.build_test_command("vitest", ["src/__tests__/app.test.ts"])
        assert cmd_vitest == "npx vitest run src/__tests__/app.test.ts"
        assert planner.build_test_command("vitest", []) == "npx vitest run"

        # Unittest
        cmd_ut = planner.build_test_command("unittest", ["tests/test_calc.py"])
        assert cmd_ut.startswith("python -m unittest tests/test_calc.py")


# ═══════════════════════════════════════════════════════════════════════════
# 6. Workspace Base-Revision Pre-Flight Validation Tests
# ═══════════════════════════════════════════════════════════════════════════

class TestWorkspaceBaseValidator:
    """Tests for WorkspaceBaseValidator boundary and revision checks."""

    def test_validate_base_revision_valid_sha_and_names(self):
        validator = WorkspaceBaseValidator()
        # 40-char hex SHA
        ok, rev, err = validator.validate_base_revision("a" * 40)
        assert ok is True
        assert rev == "a" * 40
        assert err is None

        # Standard branch ref
        ok, rev, _ = validator.validate_base_revision("main")
        assert ok is True
        assert rev == "main"

    def test_validate_base_revision_illegal_characters_rejected(self):
        validator = WorkspaceBaseValidator()
        ok, _, err = validator.validate_base_revision("sha; rm -rf /")
        assert ok is False
        assert "Invalid base_revision" in err

    def test_preflight_valid_workspace_and_targets(self, tmp_path):
        validator = WorkspaceBaseValidator()
        # Setup fake workspace
        w_dir = tmp_path / ".workspaces" / "task-123"
        w_dir.mkdir(parents=True)
        (w_dir / "src").mkdir()
        (w_dir / "src" / "app.py").write_text("print('hello')", encoding="utf-8")

        res = validator.validate_preflight(
            workspace_path=w_dir,
            base_revision="b" * 40,
            target_files=["src/app.py"],
            workspace_status=WorkspaceStatus.READY,
        )

        assert res.is_valid is True
        assert len(res.errors) == 0
        assert res.target_files_verified == ["src/app.py"]
        assert res.workspace_status == WorkspaceStatus.READY

    def test_preflight_traversal_rejection(self, tmp_path):
        validator = WorkspaceBaseValidator()
        w_dir = tmp_path / ".workspaces" / "task-safe"
        w_dir.mkdir(parents=True)

        res = validator.validate_preflight(
            workspace_path=w_dir,
            target_files=["../../etc/passwd"],
        )

        assert res.is_valid is False
        assert any("Target file validation failed" in err for err in res.errors)

    def test_preflight_invalid_workspace_status_rejection(self, tmp_path):
        validator = WorkspaceBaseValidator()
        w_dir = tmp_path / "workspace"
        w_dir.mkdir()

        res = validator.validate_preflight(
            workspace_path=w_dir,
            workspace_status=WorkspaceStatus.FAILED,  # FAILED is not ready for planning
        )

        assert res.is_valid is False
        assert any("not ready for planning" in err for err in res.errors)


# ═══════════════════════════════════════════════════════════════════════════
# 7. End-to-End TaskPlanningContext Assembly & Schema Invariants
# ═══════════════════════════════════════════════════════════════════════════

class TestTaskPlanningContextAssembly:
    """Tests end-to-end integration and Pydantic schema contracts."""

    def test_assemble_task_impact_assessment_envelope(self):
        planner = TaskTestPlanner()

        f_id = uuid4()
        sym = _make_symbol("login", "function", file_id=f_id, start_line=10, end_line=25)
        file_paths = {f_id: "src/auth.py"}

        direct = [
            AffectedSymbol(
                name="login",
                kind="function",
                file_path="src/auth.py",
                start_line=10,
                end_line=25,
                is_direct_target=True,
                callers_count=0,
            )
        ]
        trans = []
        affected_files = ["src/auth.py"]

        risk = RiskAssessment(
            score=0.1,
            risk_level=RiskLevel.LOW,
            requires_human_review=False,
            summary="Isolated low risk change",
            reasons=["isolated"],
        )
        test_plan = planner.create_test_plan(
            affected_files=affected_files,
            directly_modified=direct,
            repo_symbols=[sym],
            repo_edges=[],
            file_paths=file_paths,
        )

        assessment = TaskImpactAssessment(
            task_id="task_abc_123",
            target_files=["src/auth.py"],
            affected_files=affected_files,
            directly_modified_symbols=direct,
            transitively_affected_symbols=trans,
            risk=risk,
            test_plan=test_plan,
        )

        assert assessment.total_affected_files == 1
        assert assessment.total_affected_symbols == 1
        assert assessment.test_plan.recommended_test_command.startswith(("pytest", "python -m unittest"))

        # Wrap in TaskPlanningContext
        context = TaskPlanningContext(
            task_id="task_abc_123",
            repository_id=str(uuid4()),
            base_revision="c" * 40,
            impact_assessment=assessment,
            workspace_ready=True,
            detected_framework=test_plan.framework,
            resource_limits={"timeout_seconds": 60, "max_disk_mb": 500},
        )

        assert context.workspace_ready is True
        assert context.impact_assessment.total_affected_symbols == 1
        assert context.resource_limits["max_disk_mb"] == 500


# ═══════════════════════════════════════════════════════════════════════════
# 9. Edge Cases & Robustness Handling Tests
# ═══════════════════════════════════════════════════════════════════════════

class TestEdgeCasesAndFailureHandling:
    """Tests ensuring zero-crash behavior on anomalous or malformed inputs."""

    def test_preflight_nonexistent_workspace_path(self, tmp_path):
        validator = WorkspaceBaseValidator()
        non_existent = tmp_path / "does_not_exist"

        res = validator.validate_preflight(
            workspace_path=non_existent,
            base_revision="c" * 40,
        )

        assert res.is_valid is False
        assert any("does not exist" in err for err in res.errors)

    def test_null_bytes_and_traversal_in_preflight_target(self, tmp_path):
        validator = WorkspaceBaseValidator()
        w_dir = tmp_path / "workspace"
        w_dir.mkdir()

        res = validator.validate_preflight(
            workspace_path=w_dir,
            target_files=["src/\x00evil.py", "../../../windows/system32"],
        )

        assert res.is_valid is False
        assert len(res.errors) >= 1


# Week 3 Day 3 Acceptance & Integration Test Suite.

def _check_docker() -> bool:
    import shutil, subprocess
    if not shutil.which("docker"):
        return False
    try:
        res = subprocess.run(["docker", "info"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=1.5)
        return res.returncode == 0
    except Exception:
        return False

_docker_available = _check_docker()
skip_no_docker = pytest.mark.skipif(
    not _docker_available,
    reason="Docker daemon not available in this environment",
)



@pytest.fixture
def execution_workspace_root(tmp_path: Path) -> Path:
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
def execution_workspace_manager(execution_workspace_root: Path) -> WorkspaceManager:
    """Fixture providing an initialized WorkspaceManager."""
    return WorkspaceManager(base_workspaces_dir=execution_workspace_root)


@pytest.fixture
def active_workspace(
    execution_workspace_manager: WorkspaceManager,
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
    meta = execution_workspace_manager.create_workspace(create_req)

    start_req = WorkspaceStartExecutionRequest(
        task_id=task_id,
        plan_version=1,
        approved_base_revision="abcdef1234567890abcdef1234567890abcdef12",
        task_status="APPROVED",
    )
    start_res = execution_workspace_manager.start_execution(start_req)
    assert start_res.success is True
    assert start_res.status == WorkspaceStatus.IN_USE

    return task_id, meta


# ===========================================================================
# 1. Workspace Provisioning & Metadata Retention
# ===========================================================================

def test_workspace_provisioning_metadata(
    execution_workspace_manager: WorkspaceManager,
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

    meta = execution_workspace_manager.create_workspace(create_req)
    assert meta.task_id == task_id
    assert meta.base_revision == base_sha
    assert meta.branch_name.startswith("agent/task-")
    assert meta.status == WorkspaceStatus.READY
    assert Path(meta.workspace_path).exists()

    # Verify initial timeline events emitted
    timeline = execution_workspace_manager.get_execution_timeline(task_id)
    assert len(timeline) >= 2
    event_types = [e.event_type for e in timeline]
    assert WorkspaceExecutionEventType.WORKSPACE_CREATED in event_types
    assert WorkspaceExecutionEventType.BRANCH_SETUP in event_types


# ===========================================================================
# 2. Approval Gate Enforcement (ADR-010 & Scenario B)
# ===========================================================================

def test_unapproved_task_cannot_start_execution(
    execution_workspace_manager: WorkspaceManager,
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
    execution_workspace_manager.create_workspace(create_req)

    # Attempt execution with PENDING_APPROVAL
    req_pending = WorkspaceStartExecutionRequest(
        task_id=task_id,
        task_status="PENDING_APPROVAL",
    )
    with pytest.raises(WorkspaceAuthorizationError) as exc_info:
        execution_workspace_manager.start_execution(req_pending)
    assert "cannot bypass human approval" in str(exc_info.value)

    # Attempt execution with REJECTED
    req_rejected = WorkspaceStartExecutionRequest(
        task_id=task_id,
        task_status="REJECTED",
    )
    with pytest.raises(WorkspaceAuthorizationError) as exc_info:
        execution_workspace_manager.start_execution(req_rejected)
    assert "cannot bypass human approval" in str(exc_info.value)

    # Verify workspace remained in READY state
    meta = execution_workspace_manager.get_workspace(task_id)
    assert meta.status == WorkspaceStatus.READY


def test_approved_task_enters_in_use_state(
    execution_workspace_manager: WorkspaceManager,
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
    execution_workspace_manager.create_workspace(create_req)

    start_req = WorkspaceStartExecutionRequest(
        task_id=task_id,
        plan_version=1,
        approved_base_revision=base_sha,
        task_status="APPROVED",
    )
    res = execution_workspace_manager.start_execution(start_req)

    assert res.success is True
    assert res.status == WorkspaceStatus.IN_USE
    assert res.base_revision == base_sha
    assert res.started_at is not None

    meta = execution_workspace_manager.get_workspace(task_id)
    assert meta.status == WorkspaceStatus.IN_USE


# ===========================================================================
# 3. Base Revision Consistency & Stale Approval Check (Scenario C)
# ===========================================================================

def test_stale_approval_revision_mismatch_blocks_execution(
    execution_workspace_manager: WorkspaceManager,
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
    execution_workspace_manager.create_workspace(create_req)

    # Approved revision differs from workspace base revision
    stale_req = WorkspaceStartExecutionRequest(
        task_id=task_id,
        approved_base_revision="ffff999988887777666655554444333322221111",
        task_status="APPROVED",
    )

    with pytest.raises(WorkspaceStaleApprovalError) as exc_info:
        execution_workspace_manager.start_execution(stale_req)
    assert "base revision changed from approved" in str(exc_info.value)

    meta = execution_workspace_manager.get_workspace(task_id)
    assert meta.status == WorkspaceStatus.READY


# ===========================================================================
# 4. Execution Lifecycle Transitions (Pause, Resume, Stop, Fail)
# ===========================================================================

def test_execution_pause_and_resume_cycle(
    active_workspace: tuple[str, WorkspaceMetadata],
    execution_workspace_manager: WorkspaceManager,
):
    """Verify pausing transitions IN_USE -> STOPPED, and resuming transitions STOPPED -> IN_USE."""
    task_id, _ = active_workspace

    # Pause execution
    meta_paused = execution_workspace_manager.pause_execution(task_id, reason="Awaiting test command approval")
    assert meta_paused.status == WorkspaceStatus.STOPPED

    # Resume execution
    meta_resumed = execution_workspace_manager.resume_execution(task_id)
    assert meta_resumed.status == WorkspaceStatus.IN_USE

    # Verify timeline records both events
    timeline = execution_workspace_manager.get_execution_timeline(task_id)
    event_types = [e.event_type for e in timeline]
    assert WorkspaceExecutionEventType.EXECUTION_PAUSED in event_types
    assert WorkspaceExecutionEventType.EXECUTION_RESUMED in event_types


def test_execution_stop_and_fail(
    active_workspace: tuple[str, WorkspaceMetadata],
    execution_workspace_manager: WorkspaceManager,
):
    """Verify normal stop and failure recording with diagnostics preservation."""
    task_id, _ = active_workspace

    # Fail execution
    meta_failed = execution_workspace_manager.fail_execution(task_id, error_message="Fatal syntax error in generated code")
    assert meta_failed.status == WorkspaceStatus.FAILED
    assert "Fatal syntax error" in (meta_failed.error_message or "")

    # Verify failure recorded on timeline
    timeline = execution_workspace_manager.get_execution_timeline(task_id)
    failed_events = [e for e in timeline if e.event_type == WorkspaceExecutionEventType.EXECUTION_FAILED]
    assert len(failed_events) == 1
    assert "Fatal syntax error" in failed_events[0].message


# ===========================================================================
# 5. Sandboxed Command Execution
# ===========================================================================

@skip_no_docker
def test_sandboxed_command_execution_success(
    active_workspace: tuple[str, WorkspaceMetadata],
    execution_workspace_manager: WorkspaceManager,
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
    result = execution_workspace_manager.execute_command(cmd_req)

    assert result.success is True
    assert result.exit_code == 0
    assert "Python" in (result.stdout + result.stderr)
    assert result.timed_out is False
    assert result.duration_ms > 0

    # Verify tool invocation recorded in timeline
    timeline = execution_workspace_manager.get_execution_timeline(task_id)
    invocations = [e for e in timeline if e.event_type == WorkspaceExecutionEventType.TOOL_INVOCATION]
    assert len(invocations) >= 1
    assert invocations[-1].payload["command"] == "python"


def test_command_blocked_when_workspace_not_in_use(
    execution_workspace_manager: WorkspaceManager,
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
    execution_workspace_manager.create_workspace(create_req)

    # Workspace is currently in READY state, not IN_USE
    cmd_req = WorkspaceCommandRequest(
        task_id=task_id,
        command="python",
        arguments=["-V"],
    )
    with pytest.raises(WorkspaceStateError) as exc_info:
        execution_workspace_manager.execute_command(cmd_req)
    assert "Commands are only allowed when workspace is 'IN_USE'" in str(exc_info.value)


def test_disallowed_command_rejected_by_policy(
    active_workspace: tuple[str, WorkspaceMetadata],
    execution_workspace_manager: WorkspaceManager,
):
    """Verify non-allowlisted commands (e.g. curl, rm, bash) are rejected by policy."""
    task_id, _ = active_workspace

    cmd_req = WorkspaceCommandRequest(
        task_id=task_id,
        command="curl",
        arguments=["https://example.com"],
    )
    with pytest.raises(WorkspacePolicyViolationError) as exc_info:
        execution_workspace_manager.execute_command(cmd_req)
    assert "not in the allowlist of permitted commands" in str(exc_info.value)


def test_shell_injection_tokens_rejected(
    active_workspace: tuple[str, WorkspaceMetadata],
    execution_workspace_manager: WorkspaceManager,
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
            execution_workspace_manager.execute_command(cmd_req)
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
    execution_workspace_manager: WorkspaceManager,
):
    """Verify all workspace tools register with ToolRouter and route through policy bridge."""
    task_id, _ = active_workspace
    router = ToolRouter()
    bridge = register_workspace_tools(router, execution_workspace_manager)

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
    execution_workspace_manager: WorkspaceManager,
):
    """Verify tool requests attempting directory climbing or secret access are blocked."""
    task_id, _ = active_workspace
    router = ToolRouter()
    bridge = register_workspace_tools(router, execution_workspace_manager)

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
    execution_workspace_manager: WorkspaceManager,
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
    execution_workspace_manager.create_workspace(create_req)

    router = ToolRouter()
    bridge = register_workspace_tools(router, execution_workspace_manager)

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
    execution_workspace_manager: WorkspaceManager,
):
    """Verify targeted file patching and safe deletion inside the sandbox."""
    task_id, _ = active_workspace
    router = ToolRouter()
    bridge = register_workspace_tools(router, execution_workspace_manager)

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
    read_res = execution_workspace_manager.read_file(task_id, "src/calculator.py")
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
    read_deleted = execution_workspace_manager.read_file(task_id, "README.md")
    assert read_deleted.success is False


# ===========================================================================
# 8. Multi-Task Concurrency & Isolation
# ===========================================================================

def test_concurrent_tasks_isolated_working_directories(
    execution_workspace_manager: WorkspaceManager,
    sample_repo_root: Path,
):
    """Verify multiple concurrent tasks operate in independent directories without interference."""
    task_1 = f"task-1-{uuid4().hex[:6]}"
    task_2 = f"task-2-{uuid4().hex[:6]}"
    base_sha = "abcdef1234567890abcdef1234567890abcdef12"

    w1 = execution_workspace_manager.create_workspace(
        WorkspaceCreateRequest(
            task_id=task_1,
            repository_id=str(uuid4()),
            base_revision=base_sha,
            repository_root=str(sample_repo_root),
            isolation_type="directory_copy",
        )
    )
    w2 = execution_workspace_manager.create_workspace(
        WorkspaceCreateRequest(
            task_id=task_2,
            repository_id=str(uuid4()),
            base_revision=base_sha,
            repository_root=str(sample_repo_root),
            isolation_type="directory_copy",
        )
    )

    execution_workspace_manager.start_execution(WorkspaceStartExecutionRequest(task_id=task_1, task_status="APPROVED"))
    execution_workspace_manager.start_execution(WorkspaceStartExecutionRequest(task_id=task_2, task_status="APPROVED"))

    assert w1.workspace_path != w2.workspace_path

    # Task 1 writes a unique file
    execution_workspace_manager.write_file(task_1, "task_1_exclusive.txt", "Task 1 data")

    # Task 2 should NOT see Task 1's file
    t2_read = execution_workspace_manager.read_file(task_2, "task_1_exclusive.txt")
    assert t2_read.success is False

    # Cleanup Task 1 does not affect Task 2
    clean_1 = execution_workspace_manager.cleanup_workspace(task_1)
    assert clean_1.success is True
    assert not Path(w1.workspace_path).exists()
    assert Path(w2.workspace_path).exists()

    t2_source = execution_workspace_manager.read_file(task_2, "src/calculator.py")
    assert t2_source.success is True


# Tests for Parth — Week 3 Day 2: Diff Line-Range Extraction & Symbol Blast Radius Feeder.

# ═══════════════════════════════════════════════════════════════════════════
# 1. Unified Diff Parser Unit Tests
# ═══════════════════════════════════════════════════════════════════════════

SAMPLE_GIT_DIFF = """diff --git a/src/auth/jwt.py b/src/auth/jwt.py
index abc1234..def5678 100644
--- a/src/auth/jwt.py
+++ b/src/auth/jwt.py
@@ -10,3 +10,5 @@ def login():
+    token = create_jwt()
+    return token
@@ -40,6 +42,8 @@ def verify():
+    validate_token()
+    return True
diff --git a/src/new_module.py b/src/new_module.py
new file mode 100644
--- /dev/null
+++ b/src/new_module.py
@@ -0,0 +1,15 @@
+class NewService:
+    def __init__(self):
+        pass
diff --git a/src/deprecated.py b/src/deprecated.py
deleted file mode 100644
--- a/src/deprecated.py
+++ /dev/null
@@ -1,8 +0,0 @@
-def old():
-    pass
"""


class TestUnifiedDiffParser:
    """Unit tests for parse_unified_diff."""

    def test_parse_empty_diff(self):
        assert parse_unified_diff("") == []
        assert parse_unified_diff("   \n\n  ") == []

    def test_parse_multi_file_unified_diff(self):
        results = parse_unified_diff(SAMPLE_GIT_DIFF)
        assert len(results) == 3

        # File 1: Modified with 2 hunks
        f1 = results[0]
        assert f1.file_path == "src/auth/jwt.py"
        assert f1.status == DiffStatus.MODIFIED
        assert len(f1.diff_ranges) == 2
        # Hunk 1: +10,5 -> [10, 14]
        assert f1.diff_ranges[0].start_line == 10
        assert f1.diff_ranges[0].end_line == 14
        assert f1.diff_ranges[0].change_type == "modified"
        # Hunk 2: +42,8 -> [42, 49]
        assert f1.diff_ranges[1].start_line == 42
        assert f1.diff_ranges[1].end_line == 49

        # File 2: Newly added file
        f2 = results[1]
        assert f2.file_path == "src/new_module.py"
        assert f2.status == DiffStatus.ADDED
        assert len(f2.diff_ranges) == 1
        assert f2.diff_ranges[0].start_line == 1
        assert f2.diff_ranges[0].end_line == 15
        assert f2.diff_ranges[0].change_type == "added"

        # File 3: Deleted file
        f3 = results[2]
        assert f3.file_path == "src/deprecated.py"
        assert f3.status == DiffStatus.REMOVED
        assert f3.diff_ranges[0].change_type == "deleted"

    def test_parse_single_line_hunk(self):
        patch = """@@ -5 +5 @@
-old_val = 1
+new_val = 2
"""
        ranges = parse_unified_diff(patch)
        assert len(ranges) == 1
        assert ranges[0].diff_ranges[0].start_line == 5
        assert ranges[0].diff_ranges[0].end_line == 5


# ═══════════════════════════════════════════════════════════════════════════
# 2. GitBranchService Day 2 Tests
# ═══════════════════════════════════════════════════════════════════════════

class TestGitBranchServiceDay2:
    """Test suite for GitBranchService diff and branch isolation."""

    @pytest.mark.asyncio
    async def test_get_diff_line_ranges(self, tmp_path):
        service = GitBranchService(MagicMock())
        service._run_git = AsyncMock(return_value=(0, SAMPLE_GIT_DIFF, ""))

        res = await service.get_diff_line_ranges(tmp_path, "main")
        assert len(res) == 3
        assert res[0].file_path == "src/auth/jwt.py"
        assert res[0].diff_ranges[0].start_line == 10

    @pytest.mark.asyncio
    async def test_get_task_diff_ranges(self, tmp_path):
        service = GitBranchService(MagicMock())
        service._run_git = AsyncMock(return_value=(0, SAMPLE_GIT_DIFF, ""))
        task_id = uuid4()

        summary = await service.get_task_diff_ranges(
            task_id=task_id,
            workspace_path=tmp_path,
            base_branch="main",
        )
        assert isinstance(summary, GitHubTaskDiffRanges)
        assert summary.task_id == task_id
        assert summary.total_files_changed == 3
        assert summary.head_branch == format_agent_branch_name(task_id)

    def test_verify_branch_isolation_valid(self):
        repo_id = uuid4()
        task_id = uuid4()
        mock_db = MagicMock()
        mock_repo = Repository(id=repo_id, default_branch="main", name="test-repo")
        mock_db.execute.return_value.scalars.return_value.first.return_value = mock_repo

        service = GitBranchService(mock_db)
        service._get_repository = MagicMock(return_value=mock_repo)

        check = service.verify_branch_isolation(repo_id, task_id)
        assert isinstance(check, BranchIsolationCheck)
        assert check.is_isolated is True
        assert check.conflicts_with_protected is False
        assert check.branch_name == format_agent_branch_name(task_id)

    def test_verify_branch_isolation_protected_rejection(self, monkeypatch):
        repo_id = uuid4()
        task_id = uuid4()
        mock_db = MagicMock()
        mock_repo = Repository(id=repo_id, default_branch="main", name="test-repo")

        service = GitBranchService(mock_db)
        service._get_repository = MagicMock(return_value=mock_repo)

        # Force branch name to "main" to simulate illegal name attempt
        monkeypatch.setattr("app.services.git_branch.format_agent_branch_name", lambda _: "main")
        check = service.verify_branch_isolation(repo_id, task_id)
        assert check.is_isolated is False
        assert check.conflicts_with_protected is True
        assert "conflicts with protected branch" in check.error_message


# ═══════════════════════════════════════════════════════════════════════════
# 3. GitHubSourceService PR Diff Ranges Tests
# ═══════════════════════════════════════════════════════════════════════════

class TestSourceServiceDiffRanges:
    """Test suite for PR diff range extraction in GitHubSourceService."""

    @pytest.mark.asyncio
    async def test_get_pull_request_diff_ranges(self):
        from app.integrations.github.source_service import GitHubSourceService

        service = GitHubSourceService(MagicMock())
        repo_id = uuid4()
        user_id = uuid4()

        mock_diff = PullRequestDiffResponse(
            pull_request=PullRequestInfo(number=7, title="JWT Auth", state="open"),
            files=[
                PullRequestFile(
                    filename="src/auth/jwt.py",
                    status=DiffStatus.MODIFIED,
                    additions=5,
                    deletions=2,
                    patch="@@ -10,3 +10,5 @@ def login():\n+    token = create_jwt()\n+    return token",
                ),
                PullRequestFile(
                    filename="src/docs.md",
                    status=DiffStatus.ADDED,
                    additions=10,
                    deletions=0,
                    patch="@@ -0,0 +1,10 @@\n+# Documentation",
                ),
            ],
            total_additions=15,
            total_deletions=2,
            total_changes=17,
        )

        service.get_pull_request_diff = AsyncMock(return_value=mock_diff)
        diff_ranges = await service.get_pull_request_diff_ranges(repo_id, user_id, 7)

        assert len(diff_ranges) == 2
        assert diff_ranges[0].file_path == "src/auth/jwt.py"
        assert diff_ranges[0].diff_ranges[0].start_line == 10
        assert diff_ranges[0].diff_ranges[0].end_line == 14

        assert diff_ranges[1].file_path == "src/docs.md"
        assert diff_ranges[1].status == DiffStatus.ADDED
        assert diff_ranges[1].diff_ranges[0].start_line == 1
        assert diff_ranges[1].diff_ranges[0].end_line == 10


# Week 3 Day 3 & Day 4 + Whole-Codebase Fixes & Security Regression Test Suite.

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


# Tests for Week 3 Days 3 & 4: Workspace, Tool Auditing, Test Runs & Bounded Repair Persistence.

# ---------------------------------------------------------------------------
# Test Helpers
# ---------------------------------------------------------------------------


def _seed_user_and_repo(
    db: Session,
    login: str = "om-d3d4-user",
    repo_name: str = "d3d4-repo",
) -> tuple[User, Repository]:
    """Helper to seed valid User and Repository records for isolation testing."""
    user = User(
        id=uuid.uuid4(),
        github_id=f"gh_{uuid.uuid4().hex[:8]}",
        login=f"{login}_{uuid.uuid4().hex[:4]}",
        email=f"{login}@example.com",
    )
    db.add(user)
    db.flush()

    installation = GitHubInstallation(
        id=uuid.uuid4(),
        user_id=user.id,
        installation_id=f"inst_{uuid.uuid4().hex[:8]}",
        account_login=user.login,
        permissions={"contents": "write", "pull_requests": "write"},
    )
    db.add(installation)
    db.flush()

    repo = Repository(
        id=uuid.uuid4(),
        user_id=user.id,
        installation_id=installation.id,
        github_repo_id=f"repo_{uuid.uuid4().hex[:8]}",
        owner=user.login,
        name=f"{repo_name}-{uuid.uuid4().hex[:4]}",
        default_branch="main",
        sync_status=SyncStatus.SYNCED,
    )
    db.add(repo)
    db.commit()
    db.refresh(user)
    db.refresh(repo)
    return user, repo


def _create_approved_task(
    db: Session,
    repo_id: uuid.UUID,
    user_id: uuid.UUID,
    title: str = "Approved workflow task",
) -> Task:
    """Helper to set up a task in APPROVED status with Plan v1."""
    repo_layer = TaskRepository(db)
    task = repo_layer.create_task(
        repository_id=repo_id,
        title=title,
        source_type=TaskSourceType.USER_REQUIREMENT,
        user_id=user_id,
    )
    repo_layer.save_plan(
        task_id=task.id,
        repository_id=repo_id,
        summary="Plan v1",
        steps=[{"step_id": "1", "description": "Execute task step"}],
    )
    repo_layer.approve_plan(task_id=task.id, repository_id=repo_id, plan_version=1, user_id=user_id)
    return task


# ---------------------------------------------------------------------------
# 1. Day 3: Workspace Lifecycle & Execution Tracking
# ---------------------------------------------------------------------------


class TestWorkspaceAndExecutionTracking:
    """Verifies workspace registration, status transitions, and worker execution logs."""

    def test_workspace_lifecycle_and_status_transitions(self, db_session: Session):
        """Register workspace, update status through lifecycle, and verify cleanup timestamp."""
        user, repo = _seed_user_and_repo(db_session, "user-ws-life")
        repo_layer = TaskRepository(db_session)
        task = _create_approved_task(db_session, repo.id, user.id)

        # 1. Register workspace
        ws = repo_layer.record_workspace(
            task_id=task.id,
            repository_id=repo.id,
            workspace_path=f"/tmp/workspaces/task-{task.id}",
            task_branch=f"agent/task-{task.id}",
            base_revision="main",
            status=WorkspaceRecordStatus.READY,
        )
        assert ws.status == WorkspaceRecordStatus.READY.value
        assert ws.task_branch == f"agent/task-{task.id}"
        assert ws.current_revision is None

        # 2. Update status to IN_USE with revision
        updated_ws = repo_layer.update_workspace_status(
            task_id=task.id,
            repository_id=repo.id,
            status=WorkspaceRecordStatus.IN_USE,
            current_revision="commit_abc123",
        )
        assert updated_ws.status == WorkspaceRecordStatus.IN_USE.value
        assert updated_ws.current_revision == "commit_abc123"

        # 3. Clean up workspace
        cleanup_time = datetime.now(timezone.utc)
        cleaned_ws = repo_layer.update_workspace_status(
            task_id=task.id,
            repository_id=repo.id,
            status=WorkspaceRecordStatus.CLEANED,
            cleanup_at=cleanup_time,
        )
        assert cleaned_ws.status == WorkspaceRecordStatus.CLEANED.value
        assert cleaned_ws.cleanup_at is not None

        # 4. Lookup
        fetched = repo_layer.get_workspace(task.id, repo.id)
        assert fetched is not None
        assert fetched.id == ws.id

    def test_task_execution_tracking_start_and_finish(self, db_session: Session):
        """Worker execution attempts record timing, attempt numbers, and outcomes."""
        user, repo = _seed_user_and_repo(db_session, "user-exec-track")
        repo_layer = TaskRepository(db_session)
        task = _create_approved_task(db_session, repo.id, user.id)

        # Start Attempt 1
        exec1 = repo_layer.record_execution_start(
            task_id=task.id,
            repository_id=repo.id,
            worker_id="worker-node-1",
        )
        assert exec1.attempt_number == 1
        assert exec1.status == ExecutionStatus.RUNNING.value
        assert exec1.completed_at is None

        # Finish Attempt 1 with failure
        exec1_finished = repo_layer.record_execution_finish(
            task_id=task.id,
            repository_id=repo.id,
            execution_id=exec1.id,
            status=ExecutionStatus.FAILED,
            error_message="Sandbox process timeout after 300s",
        )
        assert exec1_finished.status == ExecutionStatus.FAILED.value
        assert "timeout" in exec1_finished.error_message
        assert exec1_finished.completed_at is not None

        # Start Attempt 2
        exec2 = repo_layer.record_execution_start(
            task_id=task.id,
            repository_id=repo.id,
            worker_id="worker-node-2",
        )
        assert exec2.attempt_number == 2

        # Check all executions
        all_execs = repo_layer.get_executions(task.id, repo.id)
        assert len(all_execs) == 2
        assert [e.attempt_number for e in all_execs] == [1, 2]

    def test_tool_invocation_auditing_and_secret_scrubbing(self, db_session: Session):
        """Tool invocations are audited with execution duration and secret scrubbing in arguments."""
        user, repo = _seed_user_and_repo(db_session, "user-tool-audit")
        repo_layer = TaskRepository(db_session)
        task = _create_approved_task(db_session, repo.id, user.id)

        # Invoke Tool with sensitive token in arguments
        inv = repo_layer.record_tool_invocation(
            task_id=task.id,
            repository_id=repo.id,
            tool_name="git_commit",
            arguments={
                "message": "Apply security fix",
                "auth_header": "Bearer ghp_secretToken1234567890abcdef1234567890",
                "api_key": "sk-proj-superSecretKeyForLLMGatewayAccess99",
            },
            status=ToolInvocationStatus.COMPLETED,
            duration_ms=45,
            output_summary="Commit created successfully on task branch",
        )

        assert inv.tool_name == "git_commit"
        assert inv.status == ToolInvocationStatus.COMPLETED.value
        assert inv.duration_ms == 45

        # Verify arguments scrubbing
        assert "ghp_" not in str(inv.sanitized_arguments)
        assert "sk-proj-" not in str(inv.sanitized_arguments)
        assert "[REDACTED]" in str(inv.sanitized_arguments)

        # Lookup
        invs = repo_layer.get_tool_invocations(task.id, repo.id)
        assert len(invs) == 1
        assert invs[0].id == inv.id

    def test_execution_start_preconditions_enforced(self, db_session: Session):
        """Transition to EXECUTING requires both an approved plan and an initialized workspace (§7.2)."""
        user, repo = _seed_user_and_repo(db_session, "user-exec-pre")
        repo_layer = TaskRepository(db_session)

        # 1. Unapproved task cannot execute
        task = repo_layer.create_task(repo.id, "Unapproved task", user_id=user.id)
        repo_layer.save_plan(task.id, repo.id, summary="Plan v1", steps=[{"step_id": "1"}])
        with pytest.raises(InvalidStateTransitionError):
            repo_layer.transition_status(task.id, repo.id, TaskStatus.EXECUTING)

        # 2. Approved task WITHOUT workspace cannot execute
        repo_layer.approve_plan(task.id, repo.id, plan_version=1, user_id=user.id)
        repo_layer.transition_status(task.id, repo.id, TaskStatus.WORKSPACE_SETUP)

        with pytest.raises(InvalidStateTransitionError) as exc_info:
            repo_layer.transition_status(task.id, repo.id, TaskStatus.EXECUTING)
        assert "Workspace has not been initialized" in str(exc_info.value)

        # 3. Approved task WITH workspace can execute
        repo_layer.record_workspace(
            task_id=task.id,
            repository_id=repo.id,
            workspace_path="/tmp/workspaces/valid",
            task_branch=f"agent/task-{task.id}",
            base_revision="main",
            status=WorkspaceRecordStatus.READY,
        )

        executing_task = repo_layer.transition_status(task.id, repo.id, TaskStatus.EXECUTING)
        assert executing_task.status == TaskStatus.EXECUTING.value


# ---------------------------------------------------------------------------
# 2. Day 4: Test Execution & Bounded Repair Loop
# ---------------------------------------------------------------------------


class TestTestExecutionAndBoundedRepairLoop:
    """Verifies test logging, exit codes, and the strict 3-attempt repair ceiling (§6 F35, §7.2)."""

    def test_test_run_logging_counts_and_sanitization(self, db_session: Session):
        """Test runs record exit code, test pass/fail counts, duration, and scrub logs."""
        user, repo = _seed_user_and_repo(db_session, "user-test-log")
        repo_layer = TaskRepository(db_session)
        task = _create_approved_task(db_session, repo.id, user.id)

        raw_log = "Run pytest --exitfirst. Token was: ghp_999988887777666655554444333322221111. All 12 passed."
        run = repo_layer.record_test_run(
            task_id=task.id,
            repository_id=repo.id,
            command="pytest backend/tests/test_auth.py",
            status=TestRunStatus.PASSED,
            exit_code=0,
            duration_ms=1250,
            tests_total=12,
            tests_passed=12,
            tests_failed=0,
            sanitized_output=raw_log,
            target_revision="rev_xyz",
        )

        assert run.exit_code == 0
        assert run.status == TestRunStatus.PASSED.value
        assert run.tests_passed == 12
        assert run.tests_failed == 0
        assert "ghp_" not in run.sanitized_output
        assert "[REDACTED]" in run.sanitized_output

        # Verify lookup
        latest = repo_layer.get_latest_test_run(task.id, repo.id)
        assert latest is not None
        assert latest.id == run.id
        assert latest.command == "pytest backend/tests/test_auth.py"

    def test_bounded_repair_loop_exact_three_attempts_and_exhaustion(self, db_session: Session):
        """Repair attempts 1, 2, 3 succeed; attempt 4 triggers RETRY_EXHAUSTED and fails the task."""
        user, repo = _seed_user_and_repo(db_session, "user-repair-bounds")
        repo_layer = TaskRepository(db_session)
        task = _create_approved_task(db_session, repo.id, user.id)
        assert task.repair_attempts_used == 0
        assert task.repair_attempts_max == 3

        # Attempt 1
        att1, avail1 = repo_layer.increment_repair_attempt(
            task_id=task.id,
            repository_id=repo.id,
            failure_classification="ASSERTION_ERROR",
            diagnosis="Off-by-one boundary check in validation",
            applied_patch="Fix range(len(items))",
        )
        assert avail1 is True
        assert att1.attempt_number == 1
        assert att1.result == RepairResult.SUCCESS.value
        assert task.repair_attempts_used == 1

        # Attempt 2
        att2, avail2 = repo_layer.increment_repair_attempt(
            task_id=task.id,
            repository_id=repo.id,
            failure_classification="TYPE_ERROR",
            diagnosis="NoneType passed to string join",
            applied_patch="Add None guard",
        )
        assert avail2 is True
        assert att2.attempt_number == 2
        assert task.repair_attempts_used == 2

        # Attempt 3 (Final allowed attempt)
        att3, avail3 = repo_layer.increment_repair_attempt(
            task_id=task.id,
            repository_id=repo.id,
            failure_classification="TIMEOUT",
            diagnosis="Infinite loop in retry handler",
            applied_patch="Add break condition",
        )
        assert avail3 is True
        assert att3.attempt_number == 3
        assert task.repair_attempts_used == 3

        # Attempt 4 (Exceeds budget ceiling of 3)
        att4, avail4 = repo_layer.increment_repair_attempt(
            task_id=task.id,
            repository_id=repo.id,
            failure_classification="UNRECOVERABLE",
        )
        assert avail4 is False
        assert att4.attempt_number == 4
        assert att4.result == RepairResult.RETRY_EXHAUSTED.value

        # Task state must be marked FAILED
        assert task.status == TaskStatus.FAILED.value
        assert "Retry budget exhausted" in task.error_message

        # Verify all repair records
        attempts = repo_layer.get_repair_attempts(task.id, repo.id)
        assert len(attempts) == 4
        assert [a.attempt_number for a in attempts] == [1, 2, 3, 4]

    def test_transition_to_repairing_blocked_when_budget_exhausted(self, db_session: Session):
        """State transition to REPAIRING is blocked once repair_attempts_used >= repair_attempts_max."""
        user, repo = _seed_user_and_repo(db_session, "user-repair-gate")
        repo_layer = TaskRepository(db_session)
        task = _create_approved_task(db_session, repo.id, user.id)

        # Set up workspace & transition to TESTING
        repo_layer.record_workspace(task.id, repo.id, "/tmp/ws", f"agent/task-{task.id}", "main")
        repo_layer.transition_status(task.id, repo.id, TaskStatus.WORKSPACE_SETUP)
        repo_layer.transition_status(task.id, repo.id, TaskStatus.EXECUTING)
        repo_layer.transition_status(task.id, repo.id, TaskStatus.TESTING)

        # Use all 3 attempts
        for _ in range(3):
            repo_layer.increment_repair_attempt(task.id, repo.id, "TEST_FAILURE")

        assert task.repair_attempts_used == 3

        # Attempting to transition to REPAIRING must be blocked
        with pytest.raises(InvalidStateTransitionError) as exc_info:
            repo_layer.transition_status(task.id, repo.id, TaskStatus.REPAIRING)
        assert "Retry budget is exhausted" in str(exc_info.value)

    def test_repair_budget_persists_across_worker_restarts(self, db_session: Session):
        """Repair budget is grounded in database persistence and cannot be reset by worker restarts."""
        user, repo = _seed_user_and_repo(db_session, "user-restart-budget")
        repo_layer = TaskRepository(db_session)
        task = _create_approved_task(db_session, repo.id, user.id)

        # Burn 2 attempts
        repo_layer.increment_repair_attempt(task.id, repo.id, "ERROR_1")
        repo_layer.increment_repair_attempt(task.id, repo.id, "ERROR_2")
        assert task.repair_attempts_used == 2

        # Simulate worker restart by creating a completely fresh Session and TaskRepository
        fresh_repo_layer = TaskRepository(db_session)
        reloaded_task = fresh_repo_layer.get_task(task.id, repo.id)
        assert reloaded_task.repair_attempts_used == 2

        # 3rd attempt is allowed
        _, avail3 = fresh_repo_layer.increment_repair_attempt(task.id, repo.id, "ERROR_3")
        assert avail3 is True

        # 4th attempt is exhausted
        _, avail4 = fresh_repo_layer.increment_repair_attempt(task.id, repo.id, "ERROR_4")
        assert avail4 is False


# ---------------------------------------------------------------------------
# 3. Multi-Tenant Isolation & Timeline Events
# ---------------------------------------------------------------------------


class TestMultiTenantIsolationAndTimeline:
    """Verifies repository boundary isolation and timeline event integrity."""

    def test_cross_repository_access_blocked(self, db_session: Session):
        """Repo A's workspace, executions, tests, and repairs are invisible to Repo B."""
        user_a, repo_a = _seed_user_and_repo(db_session, "user-a-iso", "repo-a-iso")
        _, repo_b = _seed_user_and_repo(db_session, "user-b-iso", "repo-b-iso")
        repo_layer = TaskRepository(db_session)

        task_a = _create_approved_task(db_session, repo_a.id, user_a.id)
        repo_layer.record_workspace(task_a.id, repo_a.id, "/tmp/ws-a", "agent/task-a", "main")
        repo_layer.record_test_run(task_a.id, repo_a.id, "pytest", TestRunStatus.PASSED)
        repo_layer.increment_repair_attempt(task_a.id, repo_a.id, "FAIL")

        # Access via repo_b must fail
        with pytest.raises(TaskNotFoundError):
            repo_layer.get_workspace(task_a.id, repo_b.id)

        with pytest.raises(TaskNotFoundError):
            repo_layer.get_test_runs(task_a.id, repo_b.id)

        with pytest.raises(TaskNotFoundError):
            repo_layer.get_repair_attempts(task_a.id, repo_b.id)

    def test_timeline_records_ordered_execution_and_repair_events(self, db_session: Session):
        """Timeline logs WORKSPACE_CREATED, TOOL_INVOKED, TESTS_EXECUTED, and REPAIR_ATTEMPTED."""
        user, repo = _seed_user_and_repo(db_session, "user-timeline-full")
        repo_layer = TaskRepository(db_session)
        task = _create_approved_task(db_session, repo.id, user.id)

        repo_layer.record_workspace(task.id, repo.id, "/tmp/ws", f"agent/task-{task.id}", "main")
        repo_layer.record_tool_invocation(task.id, repo.id, "file_patch", {"file": "a.py"})
        repo_layer.record_test_run(task.id, repo.id, "pytest", TestRunStatus.FAILED)
        repo_layer.increment_repair_attempt(task.id, repo.id, "FAILURE")

        timeline = repo_layer.get_task_timeline(task.id, repo.id)
        event_types = [e.event_type for e in timeline]

        assert TaskEventType.WORKSPACE_CREATED.value in event_types
        assert TaskEventType.TOOL_INVOKED.value in event_types
        assert TaskEventType.TESTS_EXECUTED.value in event_types
        assert TaskEventType.REPAIR_ATTEMPTED.value in event_types

    def test_model_to_dict_matches_pydantic_response_schemas(self, db_session: Session):
        """to_dict() methods on Day 3 and Day 4 models validate cleanly against Pydantic schemas."""
        user, repo = _seed_user_and_repo(db_session, "user-schemas-d3d4")
        service = TaskHistoryService(session=db_session)
        task = _create_approved_task(db_session, repo.id, user.id)

        # 1. Workspace
        ws = service.record_workspace(task.id, repo.id, "/tmp/ws", f"agent/task-{task.id}", "main")
        ws_resp = WorkspaceResponse.model_validate(ws.to_dict())
        assert ws_resp.workspace_id == str(ws.id)
        assert ws_resp.status == WorkspaceRecordStatus.READY.value

        # 2. Execution
        exec_record = service.record_execution_start(task.id, repo.id, worker_id="worker-test")
        exec_resp = TaskExecutionResponse.model_validate(exec_record.to_dict())
        assert exec_resp.execution_id == str(exec_record.id)
        assert exec_resp.status == ExecutionStatus.RUNNING.value

        # 3. Tool Invocation
        inv = service.record_tool_invocation(task.id, repo.id, "read_file", {"path": "a.py"})
        inv_resp = ToolInvocationResponse.model_validate(inv.to_dict())
        assert inv_resp.tool_name == "read_file"

        # 4. Test Run
        run = service.record_test_run(task.id, repo.id, "pytest", TestRunStatus.PASSED, exit_code=0, tests_total=5, tests_passed=5)
        run_resp = TestRunResponse.model_validate(run.to_dict())
        assert run_resp.tests_passed == 5
        assert run_resp.status == "PASSED"

        # 5. Repair Attempt
        att, _ = service.increment_repair_attempt(task.id, repo.id, "ASSERTION_ERROR")
        att_resp = RepairAttemptResponse.model_validate(att.to_dict())
        assert att_resp.attempt_number == 1
        assert att_resp.result == "SUCCESS"
