"""Week 3 Day 5 Acceptance & Integration Test Suite.

Owner: Prit Zania — Week 3 Day 5 Deliverable (Docs/week3.md §6 F36, F37, §8 Day 5, line 635)
Reference:
- Docs/week3.md §6 (F36 Diff Verifier, F37 Git Integration & PR Preparation)
- Docs/week3.md §8 (Day 5 Code Changes, Git Push, and Draft PR)
- Docs/daily_tasks.md (line 635: Prit Diff verification against approved plan, push branch to remote, draft PR creation with task summary and diff stats)
- ADR-007 (Sandbox Isolation), ADR-010 (Mandatory Human Approval Gate, Draft PR Only, Zero Auto-Merge)

Verifies:
1. Unified and per-file diff extraction against base revisions.
2. Diff parsing into file stats (insertions, deletions, change types, hunks).
3. Diff verification enforcing task scope boundaries (unapproved file modifications rejected).
4. Deletion protection for critical project manifests (pyproject.toml, package.json, etc.).
5. Comprehensive secret leak scanning over diff additions (OpenAI, GitHub, AWS, private keys, generic tokens).
6. Protected branch guards preventing direct commits or pushes to main, master, develop, release, prod.
7. Mandatory publication authorization gate blocking push and PR creation without explicit human approval.
8. Clean git commits with sanitized commit messages and task metadata trailers.
9. Remote git push execution with credential redaction and error containment.
10. Draft PR creation guaranteeing is_draft=True, zero auto-merge, and structured Markdown task summary.
11. Workspace timeline event logging for diff inspection, validation, commit, push, and PR creation.
12. ToolRouter registration and policy dispatch for inspect_diff, validate_diff, commit_changes, push_branch, create_draft_pr.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from agent.tools.router import ToolDefinition, ToolRequest, ToolResult, ToolRouter
from app.schemas.workspace import (
    FileChangeType,
    WorkspaceCommitRequest,
    WorkspaceCommitResult,
    WorkspaceCreateRequest,
    WorkspaceDraftPRRequest,
    WorkspaceDraftPRResult,
    WorkspaceExecutionEventType,
    WorkspaceMetadata,
    WorkspacePushRequest,
    WorkspacePushResult,
    WorkspaceResourceLimits,
    WorkspaceStartExecutionRequest,
    WorkspaceStatus,
)
from sandbox.constants import CRITICAL_PROJECT_FILES, PROTECTED_BRANCHES
from sandbox.diff_verifier import WorkspaceDiffVerifier
from sandbox.exceptions import (
    WorkspaceCommitError,
    WorkspaceDiffError,
    WorkspaceDiffValidationError,
    WorkspaceDraftPRError,
    WorkspaceProtectedBranchError,
    WorkspacePublicationUnauthorizedError,
    WorkspacePushError,
    WorkspaceSecretLeakDetectedError,
)
from sandbox.tool_policy_bridge import (
    TOOL_COMMIT_CHANGES,
    TOOL_CREATE_DRAFT_PR,
    TOOL_INSPECT_DIFF,
    TOOL_PUSH_BRANCH,
    TOOL_VALIDATE_DIFF,
    WorkspaceToolPolicyBridge,
    register_workspace_tools,
)
from sandbox.workspace_manager import WorkspaceManager


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def temp_git_repo(tmp_path: Path) -> Path:
    """Create a minimal temporary git repository with initial commit."""
    repo_dir = tmp_path / "test_repo"
    repo_dir.mkdir(parents=True, exist_ok=True)

    subprocess.run(["git", "init"], cwd=repo_dir, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Prit Test"], cwd=repo_dir, check=True)
    subprocess.run(["git", "config", "user.email", "prit@test.local"], cwd=repo_dir, check=True)

    # Initial files
    (repo_dir / "README.md").write_text("# Test Repo\n", encoding="utf-8")
    (repo_dir / "pyproject.toml").write_text("[project]\nname = 'test'\nversion = '0.1.0'\n", encoding="utf-8")
    src_dir = repo_dir / "src"
    src_dir.mkdir(parents=True, exist_ok=True)
    (src_dir / "main.py").write_text("def hello():\n    return 'world'\n", encoding="utf-8")

    subprocess.run(["git", "add", "."], cwd=repo_dir, check=True)
    subprocess.run(["git", "commit", "-m", "Initial commit"], cwd=repo_dir, check=True)
    return repo_dir


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
def running_workspace(
    workspace_manager: WorkspaceManager,
    temp_git_repo: Path,
) -> str:
    """Create and start a running workspace in IN_USE status with real git commit."""
    proc = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=temp_git_repo,
        capture_output=True,
        text=True,
        check=True,
    )
    head_sha = proc.stdout.strip()

    task_id = f"task-{uuid4().hex[:8]}"
    create_req = WorkspaceCreateRequest(
        task_id=task_id,
        repository_id=str(uuid4()),
        base_revision=head_sha,
        repository_root=str(temp_git_repo),
        isolation_type="directory_copy",
    )
    workspace_manager.create_workspace(create_req)

    start_req = WorkspaceStartExecutionRequest(
        task_id=task_id,
        plan_version=1,
        approved_base_revision=head_sha,
        task_status="APPROVED",
    )
    start_res = workspace_manager.start_execution(start_req)
    assert start_res.success is True
    assert start_res.status == WorkspaceStatus.IN_USE
    return task_id


# ---------------------------------------------------------------------------
# Test Suite 1: WorkspaceDiffVerifier Core Functionality
# ---------------------------------------------------------------------------

class TestDiffVerifier:
    """Unit tests for WorkspaceDiffVerifier diff extraction, parsing, scoping, and secret detection."""

    def test_extract_diff_empty_when_no_changes(self, temp_git_repo: Path):
        verifier = WorkspaceDiffVerifier()
        result = verifier.extract_diff(temp_git_repo)
        assert result.is_empty is True
        assert result.total_files_changed == 0
        assert result.insertions == 0
        assert result.deletions == 0
        assert len(result.files) == 0

    def test_extract_diff_modified_files(self, temp_git_repo: Path):
        verifier = WorkspaceDiffVerifier()
        main_py = temp_git_repo / "src" / "main.py"
        main_py.write_text("def hello():\n    return 'new world'\n\ndef goodbye():\n    return 'bye'\n", encoding="utf-8")

        result = verifier.extract_diff(temp_git_repo)
        assert result.is_empty is False
        assert result.total_files_changed == 1
        assert result.insertions >= 2
        file_summary = result.files[0]
        assert file_summary.file_path == "src/main.py"
        assert file_summary.change_type == FileChangeType.MODIFIED
        assert len(file_summary.hunks) > 0

    def test_extract_diff_untracked_and_deleted_files(self, temp_git_repo: Path):
        verifier = WorkspaceDiffVerifier()
        # Add new file
        new_file = temp_git_repo / "src" / "utils.py"
        new_file.write_text("def util(): pass\n", encoding="utf-8")
        # Delete README
        (temp_git_repo / "README.md").unlink()

        result = verifier.extract_diff(temp_git_repo)
        assert result.total_files_changed == 2
        paths = {f.file_path for f in result.files}
        assert "src/utils.py" in paths
        assert "README.md" in paths

    def test_validate_diff_allowed_scope_success(self, temp_git_repo: Path):
        verifier = WorkspaceDiffVerifier()
        main_py = temp_git_repo / "src" / "main.py"
        main_py.write_text("def hello(): return 'ok'\n", encoding="utf-8")

        diff = verifier.extract_diff(temp_git_repo)
        val = verifier.validate_diff(diff, allowed_files=["src/main.py"])
        assert val.is_valid is True
        assert len(val.blocking_findings) == 0
        assert val.modified_files == ["src/main.py"]
        assert len(val.unapproved_files) == 0

    def test_validate_diff_unapproved_files_rejected(self, temp_git_repo: Path):
        verifier = WorkspaceDiffVerifier()
        main_py = temp_git_repo / "src" / "main.py"
        main_py.write_text("def hello(): return 'ok'\n", encoding="utf-8")
        new_file = temp_git_repo / "unapproved.py"
        new_file.write_text("evil = 1\n", encoding="utf-8")

        diff = verifier.extract_diff(temp_git_repo)
        val = verifier.validate_diff(diff, allowed_files=["src/main.py"])
        assert val.is_valid is False
        assert "unapproved.py" in val.unapproved_files
        assert any("outside the approved task plan scope" in msg for msg in val.blocking_findings)

    def test_validate_diff_critical_manifest_deletion_rejected(self, temp_git_repo: Path):
        verifier = WorkspaceDiffVerifier()
        (temp_git_repo / "pyproject.toml").unlink()

        diff = verifier.extract_diff(temp_git_repo)
        val = verifier.validate_diff(diff, allowed_files=["pyproject.toml"], allow_critical_deletions=False)
        assert val.is_valid is False
        assert "pyproject.toml" in val.deleted_critical_files
        assert any("critical project manifest" in msg.lower() for msg in val.blocking_findings)

    def test_validate_diff_critical_manifest_deletion_allowed_with_flag(self, temp_git_repo: Path):
        verifier = WorkspaceDiffVerifier()
        (temp_git_repo / "pyproject.toml").unlink()

        diff = verifier.extract_diff(temp_git_repo)
        val = verifier.validate_diff(diff, allowed_files=["pyproject.toml"], allow_critical_deletions=True)
        assert val.is_valid is True
        assert any("pyproject.toml" in w for w in val.warnings)

    def test_validate_diff_secret_leak_openai_key(self, temp_git_repo: Path):
        verifier = WorkspaceDiffVerifier()
        main_py = temp_git_repo / "src" / "main.py"
        main_py.write_text('OPENAI_KEY = "sk-abcdefghijklmnopqrstuvwxyz1234567890abcdef"\n', encoding="utf-8")

        diff = verifier.extract_diff(temp_git_repo)
        val = verifier.validate_diff(diff, allowed_files=["src/main.py"])
        assert val.is_valid is False
        assert len(val.secret_findings) >= 1
        finding = val.secret_findings[0]
        assert finding.secret_type == "OpenAI API Key"
        assert finding.file_path == "src/main.py"
        assert any("Credential leakage detected" in msg for msg in val.blocking_findings)

    def test_validate_diff_secret_leak_github_token(self, temp_git_repo: Path):
        verifier = WorkspaceDiffVerifier()
        main_py = temp_git_repo / "src" / "main.py"
        main_py.write_text('GITHUB_TOKEN = "ghp_1234567890abcdefghijklmnopqrstuvwxyz12"\n', encoding="utf-8")

        diff = verifier.extract_diff(temp_git_repo)
        val = verifier.validate_diff(diff, allowed_files=["src/main.py"])
        assert val.is_valid is False
        assert any(f.secret_type == "GitHub Token" for f in val.secret_findings)

    def test_validate_diff_secret_leak_aws_key(self, temp_git_repo: Path):
        verifier = WorkspaceDiffVerifier()
        main_py = temp_git_repo / "src" / "main.py"
        main_py.write_text('AWS_KEY = "AKIA1234567890123456"\n', encoding="utf-8")

        diff = verifier.extract_diff(temp_git_repo)
        val = verifier.validate_diff(diff, allowed_files=["src/main.py"])
        assert val.is_valid is False
        assert any(f.secret_type == "AWS Access Key ID" for f in val.secret_findings)

    def test_validate_diff_secret_leak_private_key(self, temp_git_repo: Path):
        verifier = WorkspaceDiffVerifier()
        main_py = temp_git_repo / "src" / "main.py"
        main_py.write_text('-----BEGIN RSA PRIVATE KEY-----\nMIIEowIBAAKCAQEA...\n', encoding="utf-8")

        diff = verifier.extract_diff(temp_git_repo)
        val = verifier.validate_diff(diff, allowed_files=["src/main.py"])
        assert val.is_valid is False
        assert any(f.secret_type == "RSA / EC Private Key" for f in val.secret_findings)


# ---------------------------------------------------------------------------
# Test Suite 2: WorkspaceManager Diff & Verification Integration
# ---------------------------------------------------------------------------

class TestWorkspaceManagerDiffIntegration:
    """Integration tests for WorkspaceManager diff inspection and verification."""

    def test_get_workspace_diff_emits_timeline_event(
        self,
        workspace_manager: WorkspaceManager,
        running_workspace: str,
    ):
        task_id = running_workspace
        # Make a change in the workspace
        workspace_manager.write_file(task_id, "src/main.py", "def hello(): return 'from_sandbox'\n")

        diff_res = workspace_manager.get_workspace_diff(task_id)
        assert diff_res.is_empty is False
        assert diff_res.total_files_changed == 1
        assert diff_res.files[0].file_path == "src/main.py"

        # Verify timeline event
        timeline = workspace_manager.get_execution_timeline(task_id)
        event_types = [e.event_type for e in timeline]
        assert WorkspaceExecutionEventType.DIFF_INSPECTED in event_types

    def test_validate_workspace_diff_success(
        self,
        workspace_manager: WorkspaceManager,
        running_workspace: str,
    ):
        task_id = running_workspace
        workspace_manager.write_file(task_id, "src/main.py", "def hello(): return 'clean'\n")

        val_res = workspace_manager.validate_workspace_diff(task_id, allowed_files=["src/main.py"])
        assert val_res.is_valid is True
        assert val_res.modified_files == ["src/main.py"]

        timeline = workspace_manager.get_execution_timeline(task_id)
        event_types = [e.event_type for e in timeline]
        assert WorkspaceExecutionEventType.DIFF_VALIDATED in event_types

    def test_validate_workspace_diff_failure_emits_event(
        self,
        workspace_manager: WorkspaceManager,
        running_workspace: str,
    ):
        task_id = running_workspace
        workspace_manager.write_file(task_id, "src/main.py", "def hello(): return 'clean'\n")
        workspace_manager.write_file(task_id, "unauthorized.txt", "rogue\n")

        val_res = workspace_manager.validate_workspace_diff(task_id, allowed_files=["src/main.py"])
        assert val_res.is_valid is False
        assert "unauthorized.txt" in val_res.unapproved_files

        timeline = workspace_manager.get_execution_timeline(task_id)
        event_types = [e.event_type for e in timeline]
        assert WorkspaceExecutionEventType.DIFF_VALIDATION_FAILED in event_types


# ---------------------------------------------------------------------------
# Test Suite 3: Commit Task Changes
# ---------------------------------------------------------------------------

class TestWorkspaceCommitChanges:
    """Tests for creating clean git commits with protected branch enforcement and metadata trailers."""

    def test_commit_task_changes_success(
        self,
        workspace_manager: WorkspaceManager,
        running_workspace: str,
    ):
        task_id = running_workspace
        workspace_manager.write_file(task_id, "src/main.py", "def hello(): return 'committed'\n")

        commit_req = WorkspaceCommitRequest(
            task_id=task_id,
            message="feat: update hello greeting",
            author_name="Prit Zania",
            author_email="prit@dau.ac.in",
        )
        res = workspace_manager.commit_task_changes(commit_req)

        assert res.success is True
        assert res.commit_sha != ""
        assert len(res.commit_sha) >= 7
        assert "src/main.py" in res.files_committed
        assert "Task-ID:" in res.message
        assert "Generated-By: AI-Platform-Sandbox" in res.message

        timeline = workspace_manager.get_execution_timeline(task_id)
        event_types = [e.event_type for e in timeline]
        assert WorkspaceExecutionEventType.CHANGES_COMMITTED in event_types

    def test_commit_rejects_protected_branch(
        self,
        workspace_manager: WorkspaceManager,
        running_workspace: str,
    ):
        task_id = running_workspace
        for branch in PROTECTED_BRANCHES:
            commit_req = WorkspaceCommitRequest(
                task_id=task_id,
                message="feat: illegal commit",
                branch_name=branch,
            )
            with pytest.raises(WorkspaceProtectedBranchError) as exc_info:
                workspace_manager.commit_task_changes(commit_req)
            assert branch in str(exc_info.value)

    def test_commit_redacts_tokens_in_message(
        self,
        workspace_manager: WorkspaceManager,
        running_workspace: str,
    ):
        task_id = running_workspace
        workspace_manager.write_file(task_id, "src/main.py", "def hello(): return 'redact'\n")

        commit_req = WorkspaceCommitRequest(
            task_id=task_id,
            message="fix: applied with token ghp_1234567890abcdefghijklmnopqrstuvwxyzAB in note",
        )
        res = workspace_manager.commit_task_changes(commit_req)
        assert res.success is True
        assert "ghp_1234567890abcdefghijklmnopqrstuvwxyzAB" not in res.message
        assert "[REDACTED]" in res.message


# ---------------------------------------------------------------------------
# Test Suite 4: Push Branch to Remote
# ---------------------------------------------------------------------------

class TestWorkspacePushBranch:
    """Tests for git push with publication authorization gate and protected branch guards."""

    def test_push_unauthorized_fails_gate(
        self,
        workspace_manager: WorkspaceManager,
        running_workspace: str,
    ):
        task_id = running_workspace
        push_req = WorkspacePushRequest(
            task_id=task_id,
            branch_name="feat/my-feature",
            publication_authorized=False,
        )
        with pytest.raises(WorkspacePublicationUnauthorizedError) as exc_info:
            workspace_manager.push_task_branch(push_req)
        assert "human authorization is required" in str(exc_info.value).lower()

        timeline = workspace_manager.get_execution_timeline(task_id)
        event_types = [e.event_type for e in timeline]
        assert WorkspaceExecutionEventType.PUBLICATION_FAILED in event_types

    def test_push_protected_branch_fails(
        self,
        workspace_manager: WorkspaceManager,
        running_workspace: str,
    ):
        task_id = running_workspace
        push_req = WorkspacePushRequest(
            task_id=task_id,
            branch_name="main",
            publication_authorized=True,
        )
        with pytest.raises(WorkspaceProtectedBranchError) as exc_info:
            workspace_manager.push_task_branch(push_req)
        assert "protected branch" in str(exc_info.value)

    def test_push_authorized_success_with_mocked_git(
        self,
        workspace_manager: WorkspaceManager,
        running_workspace: str,
    ):
        task_id = running_workspace
        workspace_manager.write_file(task_id, "src/main.py", "def hello(): return 'pushed'\n")
        workspace_manager.commit_task_changes(WorkspaceCommitRequest(task_id=task_id, message="commit before push"))

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="Everything up-to-date", stderr="")
            push_req = WorkspacePushRequest(
                task_id=task_id,
                branch_name=f"feat/test-{task_id}",
                remote_name="origin",
                publication_authorized=True,
            )
            res = workspace_manager.push_task_branch(push_req)

            assert res.success is True
            assert res.branch == f"feat/test-{task_id}"
            assert res.remote_name == "origin"

            timeline = workspace_manager.get_execution_timeline(task_id)
            event_types = [e.event_type for e in timeline]
            assert WorkspaceExecutionEventType.PUBLICATION_AUTHORIZED in event_types
            assert WorkspaceExecutionEventType.BRANCH_PUSHED in event_types

    def test_push_redacts_credentials_on_error(
        self,
        workspace_manager: WorkspaceManager,
        running_workspace: str,
    ):
        task_id = running_workspace
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = subprocess.CalledProcessError(
                returncode=128,
                cmd="git push",
                output="fatal: Authentication failed for https://x-access-token:ghp_secrettoken@github.com/repo.git",
            )
            push_req = WorkspacePushRequest(
                task_id=task_id,
                branch_name=f"feat/test-{task_id}",
                publication_authorized=True,
            )
            with pytest.raises(WorkspacePushError) as exc_info:
                workspace_manager.push_task_branch(push_req)
            assert "ghp_secrettoken" not in str(exc_info.value)
            assert "[REDACTED]" in str(exc_info.value)


# ---------------------------------------------------------------------------
# Test Suite 5: Draft PR Creation & Auto-Merge Guard
# ---------------------------------------------------------------------------

class TestDraftPRCreation:
    """Tests for draft PR synthesis, draft=True guarantee, and ADR-010 compliance."""

    def test_create_draft_pr_unauthorized_fails_gate(
        self,
        workspace_manager: WorkspaceManager,
        running_workspace: str,
    ):
        task_id = running_workspace
        pr_req = WorkspaceDraftPRRequest(
            task_id=task_id,
            title="feat: autonomous enhancement",
            head_branch=f"feat/test-{task_id}",
            publication_authorized=False,
        )
        with pytest.raises(WorkspacePublicationUnauthorizedError) as exc_info:
            workspace_manager.create_draft_pr(pr_req)
        assert "human authorization is required" in str(exc_info.value).lower()

    def test_create_draft_pr_protected_head_fails(
        self,
        workspace_manager: WorkspaceManager,
        running_workspace: str,
    ):
        task_id = running_workspace
        pr_req = WorkspaceDraftPRRequest(
            task_id=task_id,
            title="feat: autonomous enhancement",
            head_branch="main",
            publication_authorized=True,
        )
        with pytest.raises(WorkspaceProtectedBranchError) as exc_info:
            workspace_manager.create_draft_pr(pr_req)
        assert "protected branch" in str(exc_info.value)

    def test_create_draft_pr_always_draft_and_generates_summary(
        self,
        workspace_manager: WorkspaceManager,
        running_workspace: str,
    ):
        task_id = running_workspace
        workspace_manager.write_file(task_id, "src/main.py", "def hello(): return 'pr_ready'\n")

        pr_req = WorkspaceDraftPRRequest(
            task_id=task_id,
            title="feat(core): implement workspace diff verifier",
            head_branch=f"feat/test-{task_id}",
            base_branch="main",
            draft=True,
            repository_owner="Meetvirugama",
            repository_name="AI-Powered-Software-Development-Platform",
            publication_authorized=True,
        )
        pr_res = workspace_manager.create_draft_pr(pr_req)

        assert pr_res.success is True
        assert pr_res.is_draft is True  # ADR-010 invariant: strictly Draft PR
        assert pr_res.head_branch == f"feat/test-{task_id}"
        assert pr_res.base_branch == "main"
        assert pr_res.pr_number is not None
        assert "Meetvirugama/AI-Powered-Software-Development-Platform" in pr_res.pr_url

        # Check structured summary content
        summary = pr_res.summary
        assert "Draft PR" in summary
        assert "Task ID" in summary
        assert "ADR-010" in summary
        assert "Automated merging is strictly prohibited" in summary
        assert "src/main.py" in summary

        timeline = workspace_manager.get_execution_timeline(task_id)
        event_types = [e.event_type for e in timeline]
        assert WorkspaceExecutionEventType.PR_CREATED in event_types

    def test_create_draft_pr_custom_body_preserved(
        self,
        workspace_manager: WorkspaceManager,
        running_workspace: str,
    ):
        task_id = running_workspace
        pr_req = WorkspaceDraftPRRequest(
            task_id=task_id,
            title="feat: custom pr",
            head_branch=f"feat/test-{task_id}",
            body="### Custom Developer Notes\nAll tests verified.",
            publication_authorized=True,
        )
        pr_res = workspace_manager.create_draft_pr(pr_req)
        assert pr_res.success is True
        assert "### Custom Developer Notes" in pr_res.summary
        assert "Draft PR Notice" in pr_res.summary


# ---------------------------------------------------------------------------
# Test Suite 6: ToolRouter Policy Dispatch for Day 5 Tools
# ---------------------------------------------------------------------------

class TestToolRouterDay5Dispatch:
    """Verify ToolRouter registration and policy execution for Day 5 workspace tools."""

    def test_tool_router_registers_all_day5_tools(
        self,
        workspace_manager: WorkspaceManager,
    ):
        router = ToolRouter()
        bridge = register_workspace_tools(router, workspace_manager)
        registered_names = {t.name for t in router.get_tools()}

        assert TOOL_INSPECT_DIFF in registered_names
        assert TOOL_VALIDATE_DIFF in registered_names
        assert TOOL_COMMIT_CHANGES in registered_names
        assert TOOL_PUSH_BRANCH in registered_names
        assert TOOL_CREATE_DRAFT_PR in registered_names

    def test_tool_inspect_and_validate_diff_via_router(
        self,
        workspace_manager: WorkspaceManager,
        running_workspace: str,
    ):
        task_id = running_workspace
        router = ToolRouter()
        bridge = register_workspace_tools(router, workspace_manager)

        workspace_manager.write_file(task_id, "src/main.py", "def hello(): return 'router'\n")

        # 1. inspect_diff
        inspect_req = ToolRequest(
            tool_name=TOOL_INSPECT_DIFF,
            arguments={"task_id": task_id},
        )
        inspect_res = router.route(inspect_req, agent_state={"task_id": task_id}, policy_engine=bridge)
        assert inspect_res.success is True
        assert inspect_res.output["total_files_changed"] == 1

        # 2. validate_diff
        validate_req = ToolRequest(
            tool_name=TOOL_VALIDATE_DIFF,
            arguments={"task_id": task_id, "allowed_files": ["src/main.py"]},
        )
        val_res = router.route(validate_req, agent_state={"task_id": task_id}, policy_engine=bridge)
        assert val_res.success is True
        assert val_res.output["is_valid"] is True

    def test_tool_commit_changes_via_router(
        self,
        workspace_manager: WorkspaceManager,
        running_workspace: str,
    ):
        task_id = running_workspace
        router = ToolRouter()
        bridge = register_workspace_tools(router, workspace_manager)

        workspace_manager.write_file(task_id, "src/main.py", "def hello(): return 'router_commit'\n")

        commit_req = ToolRequest(
            tool_name=TOOL_COMMIT_CHANGES,
            arguments={"task_id": task_id, "message": "feat: router commit"},
        )
        commit_res = router.route(commit_req, agent_state={"task_id": task_id}, policy_engine=bridge)
        assert commit_res.success is True
        assert commit_res.output["commit_sha"] != ""

    def test_tool_push_branch_unauthorized_rejected_by_router(
        self,
        workspace_manager: WorkspaceManager,
        running_workspace: str,
    ):
        task_id = running_workspace
        router = ToolRouter()
        bridge = register_workspace_tools(router, workspace_manager)

        push_req = ToolRequest(
            tool_name=TOOL_PUSH_BRANCH,
            arguments={
                "task_id": task_id,
                "branch_name": f"feat/test-{task_id}",
                "publication_authorized": False,
            },
        )
        push_res = router.route(push_req, agent_state={"task_id": task_id}, policy_engine=bridge)
        assert push_res.success is False
        assert "publication authorization is required" in push_res.error.lower()

    def test_tool_create_draft_pr_authorized_success_via_router(
        self,
        workspace_manager: WorkspaceManager,
        running_workspace: str,
    ):
        task_id = running_workspace
        router = ToolRouter()
        bridge = register_workspace_tools(router, workspace_manager)

        pr_req = ToolRequest(
            tool_name=TOOL_CREATE_DRAFT_PR,
            arguments={
                "task_id": task_id,
                "title": "feat: dispatch draft pr",
                "head_branch": f"feat/test-{task_id}",
                "publication_authorized": True,
            },
        )
        pr_res = router.route(pr_req, agent_state={"task_id": task_id}, policy_engine=bridge)
        assert pr_res.success is True
        assert pr_res.output["is_draft"] is True
        assert pr_res.output["pr_number"] is not None
