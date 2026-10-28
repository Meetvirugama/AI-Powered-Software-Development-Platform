"""Comprehensive Test Suite for Prit — Week 3 Day 1: Workspace & Sandbox Isolation.

Owner: Prit Zania — Week 3 Day 1 Deliverable (Docs/week3.md §6 F33, §7, §8 Day 1)
Reference: Docs/week3.md §6 (F33 — Isolated Workspace and Repository Operations), ADR-007

Verifies:
1. WorkspaceStatus enum, state machine, and valid/invalid transition guards.
2. Canonical Pydantic schemas (WorkspaceMetadata, WorkspaceCreateRequest, WorkspaceResourceLimits).
3. WorkspacePathGuard directory confinement and deep traversal protection (.., \\, UNC, absolute, null bytes).
4. Sensitive credential and internal metadata protection (.git, .env, SSH keys).
5. WorkspaceManager lifecycle provisioning (.workspaces/task-<id>) and Git worktree / directory isolation.
6. Guarded sandboxed file operations (atomic read, write, patch, delete, list).
7. Resource monitoring and quota enforcement (file size caps, disk budgets, max files modified).
8. Safe, idempotent decommissioning and cleanup without collateral damage.
9. Cross-task boundary isolation and host platform repository protection.
"""

from __future__ import annotations

import os
import subprocess
import tempfile
from pathlib import Path
from uuid import uuid4

import pytest

from app.schemas.workspace import (
    VALID_WORKSPACE_TRANSITIONS,
    WorkspaceCleanupResult,
    WorkspaceCreateRequest,
    WorkspaceCreateResult,
    WorkspaceFilePatchRequest,
    WorkspaceFileReadRequest,
    WorkspaceFileWriteRequest,
    WorkspaceMetadata,
    WorkspaceResourceLimits,
    WorkspaceStatus,
    can_transition_workspace,
)
from sandbox.constants import PROTECTED_SYSTEM_PREFIXES
from sandbox.exceptions import (
    WorkspaceCleanupError,
    WorkspaceCreationError,
    WorkspaceError,
    WorkspaceFileError,
    WorkspaceLimitExceededError,
    WorkspacePathEscapeError,
    WorkspaceStateError,
)
from sandbox.path_guard import WorkspacePathGuard
from sandbox.resource_monitor import WorkspaceResourceMonitor
from sandbox.workspace_manager import WorkspaceManager


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
