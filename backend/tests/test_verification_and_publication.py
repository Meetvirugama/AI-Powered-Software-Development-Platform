"""Verification and publication tests."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from unittest.mock import MagicMock
from unittest.mock import patch
from uuid import uuid4
import pytest
from agent.tools.router import ToolDefinition
from agent.tools.router import ToolRequest
from agent.tools.router import ToolResult
from agent.tools.router import ToolRouter
from app.schemas.workspace import FileChangeType
from app.schemas.workspace import WorkspaceCommitRequest
from app.schemas.workspace import WorkspaceCommitResult
from app.schemas.workspace import WorkspaceCreateRequest
from app.schemas.workspace import WorkspaceDraftPRResult
from app.schemas.workspace import WorkspaceExecutionEventType
from app.schemas.workspace import WorkspaceMetadata
from app.schemas.workspace import WorkspacePushRequest
from app.schemas.workspace import WorkspacePushResult
from app.schemas.workspace import WorkspaceResourceLimits
from app.schemas.workspace import WorkspaceStartExecutionRequest
from app.schemas.workspace import WorkspaceStatus
from sandbox.constants import CRITICAL_PROJECT_FILES
from sandbox.constants import PROTECTED_BRANCHES
from sandbox.diff_verifier import WorkspaceDiffVerifier
from sandbox.exceptions import WorkspaceCommitError
from sandbox.exceptions import WorkspaceDiffError
from sandbox.exceptions import WorkspaceDiffValidationError
from sandbox.exceptions import WorkspaceDraftPRError
from sandbox.exceptions import WorkspaceProtectedBranchError
from sandbox.exceptions import WorkspacePublicationUnauthorizedError
from sandbox.exceptions import WorkspacePushError
from sandbox.exceptions import WorkspaceSecretLeakDetectedError
from sandbox.tool_policy_bridge import TOOL_COMMIT_CHANGES
from sandbox.tool_policy_bridge import TOOL_CREATE_DRAFT_PR
from sandbox.tool_policy_bridge import TOOL_INSPECT_DIFF
from sandbox.tool_policy_bridge import TOOL_PUSH_BRANCH
from sandbox.tool_policy_bridge import TOOL_VALIDATE_DIFF
from sandbox.tool_policy_bridge import WorkspaceToolPolicyBridge
from sandbox.tool_policy_bridge import register_workspace_tools
from sandbox.workspace_manager import WorkspaceManager
from app.schemas.verification import VerificationCheckItem
from app.schemas.verification import VerificationContext
from app.schemas.verification import VerificationFinding
from app.schemas.verification import VerificationResult
from app.services.independent_verifier import IndependentVerifier
import asyncio
from unittest.mock import AsyncMock
from uuid import UUID
from fastapi.testclient import TestClient
from app.core.database import get_db
from app.core.errors import APIError
from app.core.errors import ErrorCode
from app.core.security import create_access_token
from app.integrations.github.schemas import PullRequestInfo
from app.main import app
from app.models.pull_request import PullRequest
from app.models.repository import Repository
from app.models.user import User
from app.repositories.pull_request_repository import PullRequestRepository
from app.schemas.task import RestrictedExecutionResult
from app.schemas.task import TaskConstraint
from app.schemas.task import TestCounts
from app.services.git_branch import GitBranchService
from app.services.git_branch import format_agent_branch_name
from app.integrations.github.client import GitHubAPIError
from app.integrations.github.client import GitHubClient
from app.integrations.github.service import GitHubService
import uuid
from typing import Any
from sqlalchemy.orm import Session
from app.models.analysis_finding import AnalysisFinding
from app.models.analysis_run import AnalysisFeature
from app.models.analysis_run import AnalysisRun
from app.models.analysis_run import AnalysisRunStatus
from app.models.github_installation import GitHubInstallation
from app.models.repository import SyncStatus
from app.models.task import ApprovalDecision
from app.models.task import ExecutionStatus
from app.models.task import RepairResult
from app.models.task import Task
from app.models.task import TaskApproval
from app.models.task import TaskEvent
from app.models.task import TaskEventType
from app.models.task import TaskExecution
from app.models.task import TaskPlan
from app.models.task import TaskPlanStatus
from app.models.task import TaskPullRequest
from app.models.task import TaskSourceType
from app.models.task import TaskStatus
from app.models.task import TestRun
from app.models.task import TestRunStatus
from app.models.task import VerificationResult as VerificationRecord
from app.models.task import VerificationStatus
from app.models.task import Workspace
from app.models.task import WorkspaceStatus as WorkspaceRecordStatus
from app.repositories.task_repository import InvalidStateTransitionError
from app.repositories.task_repository import PlanNotFoundError
from app.repositories.task_repository import TaskNotFoundError
from app.repositories.task_repository import TaskRepository
from app.schemas.task import PublicationAuthorizationRequest
from app.schemas.task import PublicationAuthorizationResponse
from app.schemas.task import TaskPullRequestResponse
from app.schemas.task import TaskTraceabilityResponse
from app.schemas.task import VerificationResultResponse
from app.services.task_history_service import TaskHistoryService


# Week 3 Day 5 Acceptance & Integration Test Suite.

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

    def test_draft_summary_lists_modified_files_and_custom_details(
        self, workspace_manager: WorkspaceManager, running_workspace: str,
    ):
        task_id = running_workspace
        workspace_manager.write_file(task_id, "src/main.py", "def hello(): return 'pr_ready'\n")
        summary = workspace_manager.format_draft_pr_summary(
            task_id=task_id,
            title="feat(core): implement workspace diff verifier",
            head_branch=f"feat/test-{task_id}",
            base_branch="main",
            diff_result=workspace_manager.get_workspace_diff(task_id),
            latest_test=None,
            custom_body="### Custom Developer Notes",
        )

        assert "Draft PR" in summary
        assert "Task ID" in summary
        assert "ADR-010" in summary
        assert "Automated merging is strictly prohibited" in summary
        assert "src/main.py" in summary
        assert "### Custom Developer Notes" in summary
        assert WorkspaceExecutionEventType.PR_CREATED not in {
            event.event_type for event in workspace_manager.get_execution_timeline(task_id)
        }


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

    def test_tool_cannot_authorize_draft_pr(
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
        assert pr_res.success is False
        assert "verified commit" in pr_res.error.lower()


# Unit tests for Week 3 Day 5 Independent Verification Engine & PR Summary Generator.

# ---------------------------------------------------------------------------
# Helper: Create a Clean, Valid VerificationContext for Testing
# ---------------------------------------------------------------------------

def _create_clean_context(
    task_id: str = "task_100",
    target_branch: str = "agent/task-100",
    base_revision: str = "abcdef0123456789",
    verified_revision: str = "1234567890abcdef",
    diff: str | None = None,
) -> VerificationContext:
    """Helper function to create a clean context where all 12 checks should pass.

    In simple words: This gives us a 'perfect' task setup so we can test happy path,
    or tweak one specific field to see if that individual check catches the error.
    """
    clean_diff = diff or """
--- a/backend/app/auth.py
+++ b/backend/app/auth.py
@@ -10,3 +10,3 @@
-    if user is None:
+    if not user:
"""
    return VerificationContext(
        task_id=task_id,
        target_branch=target_branch,
        base_revision=base_revision,
        verified_revision=verified_revision,
        diff=clean_diff,
        task_title="Fix user authentication null check",
        task_description="Safely handle empty user record in auth route.",
        plan_approved=True,
        approved_plan_version=1,
        current_plan_version=1,
        allowed_files=["backend/app/auth.py"],
        forbidden_files=["backend/app/config.py", ".env.production"],
        tests_completed=True,
        tests_passed=True,
        test_revision=verified_revision,
        test_count=15,
        failed_test_count=0,
        static_analysis_completed=True,
        static_findings=[],
        ai_review_completed=True,
        ai_review_findings=[],
        tokens_used=1200,
        token_budget=50000,
        execution_time_s=14.5,
        timeout_s=300.0,
    )


# ---------------------------------------------------------------------------
# 1. Happy Path Test: Everything Passes Cleanly
# ---------------------------------------------------------------------------

def test_independent_verifier_happy_path_all_12_checks_pass():
    """Verify that when everything is clean and safe, verification returns PASS.

    Simple explanation:
    If tests pass, no secrets are leaked, files are allowed, and plan is approved,
    the overall verdict must be PASS and publication must be allowed.
    """
    verifier = IndependentVerifier()
    context = _create_clean_context()

    result = verifier.verify(context)

    # Make sure we got exactly 12 checks evaluated
    assert len(result.checks) == 12

    # In simple terms: Every single check should have passed
    for check in result.checks:
        assert check.status in ("PASSED", "COMPLETED"), f"Check {check.name} did not pass: {check.message}"

    # Verify overall verdict and publication eligibility
    assert result.status == "PASS"
    assert result.is_passing is True
    assert result.is_eligible_for_publication is True
    assert len(result.blocking_findings) == 0

    # Ensure PR markdown summary was generated with task details
    assert "## 🤖 Automated Implementation & Verification Report" in result.pr_summary
    assert "Fix user authentication null check" in result.pr_summary
    assert "agent/task-100" in result.pr_summary


# ---------------------------------------------------------------------------
# 2. Check 1: Plan Approval & Version Mismatch Tests
# ---------------------------------------------------------------------------

def test_check_fails_when_plan_is_unapproved():
    """Verify that a task with an unapproved plan is strictly blocked.

    Simple explanation:
    If someone tries to publish code before the plan was approved by a human,
    it must fail verification.
    """
    verifier = IndependentVerifier()
    context = _create_clean_context()
    context.plan_approved = False  # Not approved!

    result = verifier.verify(context)

    assert result.status == "FAIL"
    assert result.is_eligible_for_publication is False
    assert any(c.name == "plan_approval" and c.status == "FAILED" for c in result.checks)
    assert any("has not received mandatory human approval" in f.message for f in result.blocking_findings)


def test_check_fails_when_plan_version_mismatches():
    """Verify that if a plan was changed after approval, approval is invalidated.

    Simple explanation:
    If a human approved Plan Version 1, but the current plan is Version 2,
    the task cannot be published until Version 2 is reviewed and approved.
    """
    verifier = IndependentVerifier()
    context = _create_clean_context()
    context.approved_plan_version = 1
    context.current_plan_version = 2  # Plan changed to version 2!

    result = verifier.verify(context)

    assert result.status == "FAIL"
    assert any(c.name == "plan_approval" and c.status == "FAILED" for c in result.checks)
    assert any("Plan version mismatch" in f.message for f in result.blocking_findings)


# ---------------------------------------------------------------------------
# 3. Check 2 & 12: Git Commit & Branch Protection Tests
# ---------------------------------------------------------------------------

def test_check_fails_on_invalid_base_revision():
    """Verify that an invalid or blank base commit SHA fails verification.

    Simple explanation:
    We must have a real git commit SHA to know where this branch started.
    """
    verifier = IndependentVerifier()
    context = _create_clean_context()
    context.base_revision = "not-a-real-sha!"

    result = verifier.verify(context)

    assert result.status == "FAIL"
    assert any(c.name == "base_revision" and c.status == "FAILED" for c in result.checks)


def test_check_fails_when_target_branch_is_main():
    """Verify that pushing directly to 'main' or 'master' is strictly blocked.

    Simple explanation:
    Never push directly to main! The platform must always push to a feature branch.
    """
    verifier = IndependentVerifier()
    context = _create_clean_context(target_branch="main")

    result = verifier.verify(context)

    assert result.status == "FAIL"
    assert result.is_eligible_for_publication is False
    assert any(c.name == "branch_protection" and c.status == "FAILED" for c in result.checks)
    assert any("Direct push to protected branch" in f.message for f in result.blocking_findings)


# ---------------------------------------------------------------------------
# 4. Check 3 & 4: File Boundary and Constraint Tests
# ---------------------------------------------------------------------------

def test_check_fails_when_out_of_scope_file_is_modified():
    """Verify that modifying files outside the approved plan scope is blocked.

    Simple explanation:
    If the plan said 'edit auth.py', but the diff also edits 'payment.py',
    we block the PR because payment.py was never part of the approved plan.
    """
    bad_diff = """
--- a/backend/app/auth.py
+++ b/backend/app/auth.py
@@ -1 +1 @@
-pass
+return True
--- a/backend/app/unapproved_file.py
+++ b/backend/app/unapproved_file.py
@@ -1 +1 @@
-pass
+hack()
"""
    verifier = IndependentVerifier()
    context = _create_clean_context(diff=bad_diff)
    context.allowed_files = ["backend/app/auth.py"]

    result = verifier.verify(context)

    assert result.status == "FAIL"
    assert any(c.name == "permitted_files" and c.status == "FAILED" for c in result.checks)
    assert any("outside approved plan" in f.message for f in result.blocking_findings)


def test_check_fails_when_forbidden_file_is_modified():
    """Verify that touching protected files (like production configs) is blocked.

    Simple explanation:
    Files like '.env.production' or 'backend/app/config.py' are forbidden.
    If the agent modified one of them, fail with a CRITICAL security blocker!
    """
    forbidden_diff = """
--- a/backend/app/config.py
+++ b/backend/app/config.py
@@ -1 +1 @@
-DEBUG = False
+DEBUG = True
"""
    verifier = IndependentVerifier()
    context = _create_clean_context(diff=forbidden_diff)
    context.forbidden_files = ["backend/app/config.py"]

    result = verifier.verify(context)

    assert result.status == "FAIL"
    assert any(c.name == "no_forbidden_files" and c.status == "FAILED" for c in result.checks)
    assert any("Forbidden file" in f.message for f in result.blocking_findings)


# ---------------------------------------------------------------------------
# 5. Check 5: Diff Traversal & Size Checks
# ---------------------------------------------------------------------------

def test_check_fails_on_empty_diff():
    """Verify that an empty diff cannot be published.

    Simple explanation:
    If there are no code changes, you cannot open a pull request.
    """
    verifier = IndependentVerifier()
    context = _create_clean_context(diff="   ")

    result = verifier.verify(context)

    assert result.status == "FAIL"
    assert any(c.name == "clean_diff" and c.status == "FAILED" for c in result.checks)


def test_check_fails_on_path_traversal_in_diff():
    """Verify that relative path traversal ('../../') in diff headers is blocked.

    Simple explanation:
    Attackers try to use '../../etc/passwd' to write files outside the workspace.
    This check detects that and blocks the attack.
    """
    traversal_diff = """
--- a/../../etc/shadow
+++ b/../../etc/shadow
@@ -1 +1 @@
-root
+hacked
"""
    verifier = IndependentVerifier()
    context = _create_clean_context(diff=traversal_diff)

    result = verifier.verify(context)

    assert result.status == "FAIL"
    assert any(c.name == "clean_diff" and c.status == "FAILED" for c in result.checks)


# ---------------------------------------------------------------------------
# 6. Check 6 & 7: Test Execution and Stale Test Synchronization Tests
# ---------------------------------------------------------------------------

def test_check_inconclusive_when_tests_were_not_run():
    """Docs/week3.md §6: Never mark an unavailable check as passed.

    Simple explanation:
    If the test runner didn't execute, we cannot claim that verification passed.
    Status must be INCONCLUSIVE or REQUIRES_HUMAN_REVIEW, never PASS.
    """
    verifier = IndependentVerifier()
    context = _create_clean_context()
    context.tests_completed = False  # Tests never ran!

    result = verifier.verify(context)

    assert result.status in ("INCONCLUSIVE", "REQUIRES_HUMAN_REVIEW")
    assert result.is_passing is False
    assert any(c.name == "required_tests" and c.status == "UNAVAILABLE" for c in result.checks)


def test_check_fails_when_tests_have_failures():
    """Verify that if automated tests failed, verification fails.

    Simple explanation:
    If 2 tests failed during test execution, you cannot publish broken code.
    """
    verifier = IndependentVerifier()
    context = _create_clean_context()
    context.tests_passed = False
    context.failed_test_count = 2

    result = verifier.verify(context)

    assert result.status == "FAIL"
    assert any(c.name == "required_tests" and c.status == "FAILED" for c in result.checks)
    assert any("failed with 2 failing test(s)" in f.message for f in result.blocking_findings)


def test_check_fails_when_test_results_are_stale():
    """Docs/week3.md §6: Test results must correspond to the final diff.

    Simple explanation:
    If tests were run on commit 'abc', but the candidate commit is 'def',
    the tests are stale and cannot verify the current code.
    """
    verifier = IndependentVerifier()
    context = _create_clean_context()
    context.test_revision = "1111111111111111"
    context.verified_revision = "2222222222222222"

    result = verifier.verify(context)

    assert result.status == "FAIL"
    assert any(c.name == "test_diff_sync" and c.status == "FAILED" for c in result.checks)
    assert any("does not match verified revision" in f.message for f in result.blocking_findings)


# ---------------------------------------------------------------------------
# 7. Check 11: Secret & Credential Leakage Scan Tests
# ---------------------------------------------------------------------------

def test_check_fails_when_diff_contains_hardcoded_secrets():
    """Verify that candidate code containing real API keys or tokens is blocked.

    Simple explanation:
    If an AI agent accidentally writes an OpenAI or GitHub API key into the code,
    our secret scanner catches it and stops the PR before credentials leak to GitHub!
    """
    secret_diff = """
--- a/backend/app/auth.py
+++ b/backend/app/auth.py
@@ -10,1 +10,1 @@
-api_key = None
+api_key = "sk-proj-abc1234567890abcdef1234567890abcdef123456"
"""
    verifier = IndependentVerifier()
    context = _create_clean_context(diff=secret_diff)

    result = verifier.verify(context)

    assert result.status == "FAIL"
    assert any(c.name == "secret_scan" and c.status == "FAILED" for c in result.checks)
    assert any("Hardcoded secret detected" in f.message for f in result.blocking_findings)


# ---------------------------------------------------------------------------
# 8. Markdown PR Summary Content Tests
# ---------------------------------------------------------------------------

def test_pr_markdown_summary_contains_all_checklist_items():
    """Verify that the generated PR summary has all required sections and tables.

    Simple explanation:
    Check that the generated Markdown contains the title, verification checklist table,
    and the human review reminder.
    """
    verifier = IndependentVerifier()
    context = _create_clean_context()

    result = verifier.verify(context)
    summary = result.pr_summary

    assert "### 📌 Task Overview" in summary
    assert "### 🛡️ Independent Verification Gates (12 Checks)" in summary
    assert "### 📂 Files Modified" in summary
    assert "Human Review Notice" in summary
    assert "`backend/app/auth.py`" in summary


# Comprehensive tests for Week 3 Day 5: Independent Verification, Code Review & Draft PR.

os.environ["JWT_SECRET"] = "test-jwt-secret-for-week3-day5-pr-tests-12345"




@pytest.fixture
def temp_workspace(tmp_path: Path) -> Path:
    """Create a temporary initialized Git repository workspace."""
    ws = tmp_path / "test_workspace"
    ws.mkdir()
    subprocess.run(["git", "init"], cwd=ws, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test Agent"], cwd=ws, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "agent@test.local"], cwd=ws, check=True, capture_output=True)

    init_file = ws / "main.py"
    init_file.write_text("print('hello world')\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=ws, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "Initial commit"], cwd=ws, check=True, capture_output=True)
    return ws


# ===========================================================================
# 1. Independent Verification Checks Tests (F36)
# ===========================================================================

class TestIndependentVerifier:
    def test_happy_path_verification(self):
        """Passing tests, isolated branch, clean diff, and approved plan pass verification."""
        verifier = IndependentVerifier()
        task_id = uuid4()
        revision = "a" * 40

        test_result = RestrictedExecutionResult(
            command=["pytest"],
            exit_code=0,
            status="PASSED",
            duration_ms=120,
            stdout="3 passed",
            stderr="",
            test_counts=TestCounts(passed=3, total=3),
            workspace_revision=revision,
        )

        result = verifier.verify_task_revision(
            task_id=task_id,
            workspace_revision=revision,
            test_result=test_result,
            branch_name=f"agent/task-{str(task_id)[:8]}",
            diff_text="diff --git a/main.py b/main.py\n+print('improved')\n",
            changed_files=["main.py"],
            has_approved_plan=True,
            base_revision_matches=True,
        )

        assert result.status == "PASS"
        assert len(result.blocking_findings) == 0
        assert any(c.name == "tests" and c.status == "PASSED" for c in result.checks)
        assert any(c.name == "branch_isolation" and c.status == "PASSED" for c in result.checks)
        assert any(c.name == "secret_scan" and c.status == "PASSED" for c in result.checks)
        assert "DRAFT" in result.pr_summary

    def test_secret_in_diff_blocks_verification(self):
        """Proposed diff containing an API token produces a CRITICAL blocking finding and fails verification."""
        verifier = IndependentVerifier()
        task_id = uuid4()
        revision = "b" * 40

        test_result = RestrictedExecutionResult(
            command=["pytest"],
            exit_code=0,
            status="PASSED",
            duration_ms=100,
            stdout="1 passed",
            stderr="",
            test_counts=TestCounts(passed=1, total=1),
            workspace_revision=revision,
        )

        leaked_diff = "diff --git a/config.py b/config.py\n+github_pat_11ABCD12345678901234567890\n"

        result = verifier.verify_task_revision(
            task_id=task_id,
            workspace_revision=revision,
            test_result=test_result,
            branch_name=f"agent/task-{str(task_id)[:8]}",
            diff_text=leaked_diff,
            changed_files=["config.py"],
            has_approved_plan=True,
        )

        assert result.status == "FAIL"
        assert len(result.blocking_findings) > 0
        assert any(f.severity == "CRITICAL" and f.category == "security" for f in result.blocking_findings)

    def test_forbidden_file_violation_blocks_verification(self):
        """Modifying a file listed in task constraints produces a blocking finding."""
        verifier = IndependentVerifier()
        task_id = uuid4()
        revision = "c" * 40

        test_result = RestrictedExecutionResult(
            command=["pytest"],
            exit_code=0,
            status="PASSED",
            duration_ms=100,
            stdout="1 passed",
            stderr="",
            test_counts=TestCounts(passed=1, total=1),
            workspace_revision=revision,
        )

        constraint = TaskConstraint(
            id="cst-1",
            description="Do not touch migrations or security configs",
            constraint_type="protected_file",
            forbidden_files=["alembic/env.py", "backend/app/core/security.py"],
        )

        result = verifier.verify_task_revision(
            task_id=task_id,
            workspace_revision=revision,
            test_result=test_result,
            branch_name=f"agent/task-{str(task_id)[:8]}",
            changed_files=["alembic/env.py"],
            constraints=[constraint],
        )

        assert result.status == "FAIL"
        assert any(f.category == "policy" and "forbidden" in f.message for f in result.blocking_findings)

    def test_revision_mismatch_blocks_verification(self):
        """If test results were evaluated on an older commit than current workspace HEAD, verification fails."""
        verifier = IndependentVerifier()
        task_id = uuid4()
        head_rev = "1" * 40
        older_rev = "2" * 40

        test_result = RestrictedExecutionResult(
            command=["pytest"],
            exit_code=0,
            status="PASSED",
            duration_ms=100,
            stdout="1 passed",
            stderr="",
            test_counts=TestCounts(passed=1, total=1),
            workspace_revision=older_rev,
        )

        result = verifier.verify_task_revision(
            task_id=task_id,
            workspace_revision=head_rev,
            test_result=test_result,
            branch_name=f"agent/task-{str(task_id)[:8]}",
        )

        assert result.status == "FAIL"
        assert any(c.name == "revision_correspondence" and c.status == "FAILED" for c in result.checks)

    def test_protected_branch_violation_blocks_verification(self):
        """Trying to verify changes on main/master directly violates Rule 563."""
        verifier = IndependentVerifier()
        task_id = uuid4()
        rev = "3" * 40

        result = verifier.verify_task_revision(
            task_id=task_id,
            workspace_revision=rev,
            test_result=None,
            branch_name="main",
        )

        assert result.status == "FAIL"
        assert any(c.name == "branch_isolation" and c.status == "FAILED" for c in result.checks)


# ===========================================================================
# 2. Publication Authorization Gate Tests (F37)
# ===========================================================================

class TestPublicationAuthorizationGate:
    @pytest.mark.asyncio
    async def test_publication_without_authorization_rejected(self, temp_workspace: Path):
        """publish_task_draft_pr strictly requires publication_authorized=True."""
        mock_db = MagicMock()
        service = GitBranchService(mock_db)

        with pytest.raises(APIError) as exc_info:
            await service.publish_task_draft_pr(
                repository_id=uuid4(),
                task_id=uuid4(),
                workspace_path=temp_workspace,
                publication_authorized=False,
            )
        assert exc_info.value.status_code == 403
        assert exc_info.value.code == ErrorCode.PUBLICATION_AUTHORIZATION_REQUIRED

    @pytest.mark.asyncio
    async def test_publication_of_failing_verification_rejected(self, temp_workspace: Path):
        """Cannot publish a task if verification failed or has blocking findings."""
        mock_db = MagicMock()
        service = GitBranchService(mock_db)

        failing_verification = MagicMock()
        failing_verification.status = "FAIL"
        failing_verification.blocking_findings = [MagicMock()]

        with pytest.raises(APIError) as exc_info:
            await service.publish_task_draft_pr(
                repository_id=uuid4(),
                task_id=uuid4(),
                workspace_path=temp_workspace,
                publication_authorized=True,
                verification_result=failing_verification,
            )
        assert exc_info.value.status_code == 400
        assert exc_info.value.code == ErrorCode.VERIFICATION_FAILED

    @pytest.mark.asyncio
    async def test_successful_draft_pr_publication_and_persistence(self, temp_workspace: Path):
        """Authorized publication creates Draft PR on GitHub and persists metadata."""
        mock_db = MagicMock()
        repo_id = uuid4()
        task_id = uuid4()
        user_id = uuid4()

        repo = Repository(
            id=repo_id,
            user_id=user_id,
            name="test-repo",
            owner="test-owner",
            default_branch="main",
            installation_id=uuid4(),
        )

        mock_db.execute.return_value.scalar_one_or_none.return_value = repo

        service = GitBranchService(mock_db)
        # Mock repository loading and GitHub client
        service._get_repository = MagicMock(return_value=repo)
        mock_client = AsyncMock()
        mock_client.create_branch = AsyncMock()
        mock_client.create_pull_request = AsyncMock(return_value={
            "number": 42,
            "html_url": "https://github.com/test-owner/test-repo/pull/42",
            "created_at": "2026-10-30T12:00:00Z",
            "draft": True,
        })
        service._get_client_for_repo = AsyncMock(return_value=mock_client)
        service.branch_exists = AsyncMock(return_value=False)

        with patch.object(PullRequestRepository, "get_by_task_id", return_value=None), \
             patch.object(PullRequestRepository, "create_or_update"):
            pr_info = await service.publish_task_draft_pr(
            repository_id=repo_id,
            task_id=task_id,
            workspace_path=temp_workspace,
            publication_authorized=True,
            pr_title="feat: implement feature x",
            user_id=user_id,
        )

            assert pr_info.number == 42
            assert pr_info.draft is True
            assert pr_info.head_ref == format_agent_branch_name(task_id)
            assert mock_client.create_pull_request.called
            # Check call arguments
            call_kwargs = mock_client.create_pull_request.call_args[1]
            assert call_kwargs["draft"] is True
            assert call_kwargs["head"] == format_agent_branch_name(task_id)

    @pytest.mark.asyncio
    async def test_idempotent_publication_avoids_duplicate_pr(self, temp_workspace: Path):
        """If PR was already created for this task, returns existing PR without calling GitHub API."""
        mock_db = MagicMock()
        repo_id = uuid4()
        task_id = uuid4()

        existing_pr = PullRequest(
            task_id=task_id,
            repository_id=repo_id,
            branch=format_agent_branch_name(task_id),
            base_branch="main",
            commit_message="feat: already created",
            test_summary="Passed",
            verification_summary="Verified",
            status="created",
            pr_number=99,
            pr_url="https://github.com/test-owner/test-repo/pull/99",
        )

        with patch.object(PullRequestRepository, "get_by_task_id", return_value=existing_pr):
            service = GitBranchService(mock_db)
            service._get_client_for_repo = AsyncMock()

            pr_info = await service.publish_task_draft_pr(
                repository_id=repo_id,
                task_id=task_id,
                workspace_path=temp_workspace,
                publication_authorized=True,
            )

            assert pr_info.number == 99
            assert pr_info.draft is True
            assert not service._get_client_for_repo.called


# Tests for Parth — Week 3 Day 1: Interface Publishing & GitHub Integration Hardening.

# ═══════════════════════════════════════════════════════════════════════════
# 1. GitHubClient Unit Tests (PR Creation, Issues, Rate Limiting)
# ═══════════════════════════════════════════════════════════════════════════

class TestGitHubClientWeek3:
    """Test suite for new GitHubClient operations."""

    @pytest.mark.asyncio
    async def test_create_pull_request_draft_default(self):
        client = GitHubClient("token-123")
        client._request = AsyncMock(return_value={"id": 1, "number": 42, "title": "Test PR", "draft": True})

        res = await client.create_pull_request(
            owner="acme",
            repo="platform",
            head="agent/task-f47ac10b",
            base="main",
            title="feat: Add JWT Service",
            body="PR Description",
            draft=True,
        )

        assert res["number"] == 42
        client._request.assert_called_once_with(
            "POST",
            "/repos/acme/platform/pulls",
            json_body={
                "title": "feat: Add JWT Service",
                "head": "agent/task-f47ac10b",
                "base": "main",
                "body": "PR Description",
                "draft": True,
            },
        )

    @pytest.mark.asyncio
    async def test_update_pull_request(self):
        client = GitHubClient("token-123")
        client._request = AsyncMock(return_value={"id": 1, "number": 42, "body": "Updated summary"})

        res = await client.update_pull_request(
            owner="acme",
            repo="platform",
            pr_number=42,
            body="Updated summary",
        )

        assert res["number"] == 42
        client._request.assert_called_once_with(
            "PATCH",
            "/repos/acme/platform/pulls/42",
            json_body={"body": "Updated summary"},
        )

    @pytest.mark.asyncio
    async def test_create_issue_from_finding(self):
        client = GitHubClient("token-123")
        client._request = AsyncMock(return_value={"id": 99, "number": 12, "title": "Security finding"})

        res = await client.create_issue(
            owner="acme",
            repo="platform",
            title="Security finding: Hardcoded secret",
            body="Review found JWT_SECRET in auth.ts",
            labels=["security", "ai-finding"],
        )

        assert res["number"] == 12
        client._request.assert_called_once_with(
            "POST",
            "/repos/acme/platform/issues",
            json_body={
                "title": "Security finding: Hardcoded secret",
                "body": "Review found JWT_SECRET in auth.ts",
                "labels": ["security", "ai-finding"],
            },
        )

    @pytest.mark.asyncio
    async def test_get_issue(self):
        client = GitHubClient("token-123")
        client._request = AsyncMock(return_value={"number": 12, "state": "open"})

        res = await client.get_issue("acme", "platform", 12)
        assert res["number"] == 12
        client._request.assert_called_once_with("GET", "/repos/acme/platform/issues/12")


# ═══════════════════════════════════════════════════════════════════════════
# 2. GitHubService Interface & Safety Tests
# ═══════════════════════════════════════════════════════════════════════════

class TestGitHubServiceWeek3:
    """Test suite for high-level GitHubService published interface."""

    @pytest.fixture
    def mock_db(self):
        return MagicMock()

    @pytest.mark.asyncio
    async def test_push_branch_to_main_rejected(self, mock_db):
        """Direct push to main or master is strictly rejected (Rule 563)."""
        service = GitHubService(mock_db)

        with pytest.raises(APIError) as exc_info:
            await service.push_branch(
                installation_id="inst-1",
                owner="acme",
                repo="platform",
                local_branch="agent/task-1",
                remote_branch="main",
            )
        assert exc_info.value.status_code == 400
        assert "Direct push to default branch" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_create_pull_request_service_facade(self, mock_db):
        """Calls client.create_pull_request and returns typed PullRequestInfo."""
        service = GitHubService(mock_db)
        mock_raw_pr = {
            "id": 100,
            "number": 5,
            "title": "feat: JWT",
            "state": "open",
            "draft": True,
            "html_url": "https://github.com/acme/platform/pull/5",
            "head": {"ref": "agent/task-f47ac10b", "sha": "abc123"},
            "base": {"ref": "main", "sha": "c0ffee"},
            "created_at": "2026-10-27T10:00:00Z",
        }

        with patch("app.integrations.github.service.GitHubClient") as mock_client_cls:
            mock_client = MagicMock()
            mock_client.create_pull_request = AsyncMock(return_value=mock_raw_pr)
            mock_client_cls.return_value = mock_client

            pr_info = await service.create_pull_request(
                owner="acme",
                repo="platform",
                head="agent/task-f47ac10b",
                base="main",
                title="feat: JWT",
                body="PR Body",
                draft=True,
            )

            assert isinstance(pr_info, PullRequestInfo)
            assert pr_info.number == 5
            assert pr_info.title == "feat: JWT"
            assert pr_info.draft is True

    @pytest.mark.asyncio
    async def test_create_issue_from_finding_service_facade(self, mock_db):
        """Calls client.create_issue with ai-finding label."""
        service = GitHubService(mock_db)
        mock_issue = {"number": 101, "title": "Missing validation"}

        with patch("app.integrations.github.service.GitHubClient") as mock_client_cls:
            mock_client = MagicMock()
            mock_client.create_issue = AsyncMock(return_value=mock_issue)
            mock_client_cls.return_value = mock_client

            res = await service.create_issue_from_finding(
                owner="acme",
                repo="platform",
                title="Missing validation",
                body="SQL injection potential",
            )

            assert res["number"] == 101
            mock_client.create_issue.assert_called_once_with(
                owner="acme",
                repo="platform",
                title="Missing validation",
                body="SQL injection potential",
                labels=["ai-finding"],
                assignees=None,
            )


# Tests for Om's Week 3 Day 5 Persistence Deliverables.

# ---------------------------------------------------------------------------
# Test Helpers
# ---------------------------------------------------------------------------

def _seed_user_and_repo(
    db_session: Session,
    login: str = "om-d5-user",
    repo_name: str = "d5-repo",
) -> tuple[User, Repository]:
    """Helper to seed isolated tenant user and repository using standard conftest db."""
    user = User(
        id=uuid.uuid4(),
        github_id=abs(hash(f"{login}_{uuid.uuid4().hex[:4]}")) % 1000000,
        login=f"{login}_{uuid.uuid4().hex[:4]}",
        email=f"{login}@example.com",
    )
    db_session.add(user)
    db_session.flush()

    installation = GitHubInstallation(
        id=uuid.uuid4(),
        user_id=user.id,
        installation_id=f"inst_{uuid.uuid4().hex[:8]}",
        account_login=user.login,
        permissions={"contents": "write", "pull_requests": "write"},
    )
    db_session.add(installation)
    db_session.flush()

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
    db_session.add(repo)
    db_session.commit()
    db_session.refresh(user)
    db_session.refresh(repo)
    return user, repo


def _seed_approved_task_with_workspace(
    db_session: Session,
    repo_id: uuid.UUID,
    user_id: uuid.UUID,
    base_rev: str = "main",
) -> tuple[Task, TaskPlan, Workspace]:
    """Helper to seed task through approval and workspace setup."""
    repo = TaskRepository(db_session)
    task = repo.create_task(
        repository_id=repo_id,
        title="Implement secure token rotation",
        source_type=TaskSourceType.GITHUB_ISSUE,
        user_id=user_id,
        base_revision=base_rev,
    )
    plan = repo.save_plan(
        task_id=task.id,
        repository_id=repo_id,
        summary="Security rotation plan",
        steps=[{"step": 1, "description": "Update token generator"}],
        expected_files=["app/core/tokens.py"],
        base_revision=base_rev,
    )
    repo.approve_plan(
        task_id=task.id,
        repository_id=repo_id,
        plan_version=plan.version,
        user_id=user_id,
    )
    ws = repo.record_workspace(
        task_id=task.id,
        repository_id=repo_id,
        task_branch=f"agent/task-{task.id}",
        base_revision=base_rev,
        workspace_path=f"/tmp/workspaces/{task.id}",
    )
    return task, plan, ws


# ===========================================================================
# 1. Independent Verification Persistence & State Transitions (§6 F36)
# ===========================================================================

class TestIndependentVerificationPersistence:
    """Verifies multi-dimensional verification result logging and state gating."""

    def test_record_and_get_verification_results(self, db_session: Session) -> None:
        user, repo = _seed_user_and_repo(db_session, "ver-1")
        repository = TaskRepository(db_session)
        task, plan, ws = _seed_approved_task_with_workspace(db_session, repo.id, user.id)

        # Move to EXECUTING -> TESTING
        ex = repository.record_execution_start(task.id, repo.id, worker_id="worker-01")
        repository.record_execution_finish(task.id, repo.id, execution_id=ex.id, status=ExecutionStatus.COMPLETED)
        repository.record_test_run(task.id, repo.id, command="pytest", status=TestRunStatus.PASSED)

        checks = [
            {"name": "tests", "status": "PASSED"},
            {"name": "static_analysis", "status": "PASSED"},
            {"name": "ai_code_review", "status": "COMPLETED"},
            {"name": "secret_scan", "status": "PASSED"},
        ]
        ver = repository.record_verification_result(
            task_id=task.id,
            repository_id=repo.id,
            verified_revision="git-commit-abc123",
            status=VerificationStatus.PASSED,
            checks=checks,
            summary="All 4 checks passed with token ghp_secretKey1234567890123456789012345678",
        )

        assert ver.id is not None
        assert ver.verified_revision == "git-commit-abc123"
        assert ver.status == "PASSED"
        assert len(ver.checks) == 4
        assert "ghp_" not in ver.summary
        assert "[REDACTED]" in ver.summary

        # Query all and latest
        results = repository.get_verification_results(task.id, repo.id)
        assert len(results) == 1
        assert results[0].id == ver.id

        latest = repository.get_latest_verification_result(task.id, repo.id)
        assert latest is not None
        assert latest.id == ver.id

    def test_passing_verification_advances_task_to_ready_for_publication(self, db_session: Session) -> None:
        user, repo = _seed_user_and_repo(db_session, "ver-2")
        repository = TaskRepository(db_session)
        task, plan, ws = _seed_approved_task_with_workspace(db_session, repo.id, user.id)

        ex = repository.record_execution_start(task.id, repo.id, worker_id="worker-02")
        repository.record_execution_finish(task.id, repo.id, execution_id=ex.id, status=ExecutionStatus.COMPLETED)

        # Passing verification with zero blocking findings
        repository.record_verification_result(
            task_id=task.id,
            repository_id=repo.id,
            verified_revision="rev-ok-123",
            status=VerificationStatus.PASSED,
            blocking_findings=[],
            summary="Clean verification",
        )

        refreshed_task = repository.get_task(task.id, repo.id)
        assert refreshed_task.status == TaskStatus.READY_FOR_PUBLICATION.value

    def test_blocking_findings_transitions_task_to_blocked(self, db_session: Session) -> None:
        user, repo = _seed_user_and_repo(db_session, "ver-3")
        repository = TaskRepository(db_session)
        task, plan, ws = _seed_approved_task_with_workspace(db_session, repo.id, user.id)

        ex = repository.record_execution_start(task.id, repo.id, worker_id="worker-03")
        repository.record_execution_finish(task.id, repo.id, execution_id=ex.id, status=ExecutionStatus.COMPLETED)

        # Verification with blocking security finding
        blocking = [
            {"id": "SEC-01", "rule": "SQL_INJECTION", "severity": "HIGH", "file": "app/db.py"}
        ]
        repository.record_verification_result(
            task_id=task.id,
            repository_id=repo.id,
            verified_revision="rev-bad-456",
            status=VerificationStatus.PASSED,  # Even if status is passed, blocking findings block publication!
            blocking_findings=blocking,
            summary="Found security violation",
        )

        refreshed_task = repository.get_task(task.id, repo.id)
        assert refreshed_task.status == TaskStatus.BLOCKED.value

    def test_failed_verification_status_transitions_task_to_blocked(self, db_session: Session) -> None:
        user, repo = _seed_user_and_repo(db_session, "ver-4")
        repository = TaskRepository(db_session)
        task, plan, ws = _seed_approved_task_with_workspace(db_session, repo.id, user.id)

        ex = repository.record_execution_start(task.id, repo.id, worker_id="worker-04")
        repository.record_execution_finish(task.id, repo.id, execution_id=ex.id, status=ExecutionStatus.COMPLETED)

        repository.record_verification_result(
            task_id=task.id,
            repository_id=repo.id,
            verified_revision="rev-failed-789",
            status=VerificationStatus.FAILED,
            summary="Static checks failed",
        )

        refreshed_task = repository.get_task(task.id, repo.id)
        assert refreshed_task.status == TaskStatus.BLOCKED.value

    def test_verification_on_terminal_task_rejected(self, db_session: Session) -> None:
        user, repo = _seed_user_and_repo(db_session, "ver-5")
        repository = TaskRepository(db_session)
        task = repository.create_task(repo.id, "Terminal task")
        task.status = TaskStatus.FAILED.value
        db_session.commit()

        with pytest.raises(InvalidStateTransitionError, match="terminal status"):
            repository.record_verification_result(
                task_id=task.id,
                repository_id=repo.id,
                verified_revision="rev-xyz",
                status=VerificationStatus.PASSED,
            )


# ===========================================================================
# 2. Publication Authorization Gate (§6 F37)
# ===========================================================================

class TestPublicationAuthorizationTraceability:
    """Verifies that publishing requires explicit human authorization and passing verification."""

    def test_authorize_publication_success_and_state_transition(self, db_session: Session) -> None:
        user, repo = _seed_user_and_repo(db_session, "pub-1")
        repository = TaskRepository(db_session)
        task, plan, ws = _seed_approved_task_with_workspace(db_session, repo.id, user.id)

        ex = repository.record_execution_start(task.id, repo.id, worker_id="worker-01")
        repository.record_execution_finish(task.id, repo.id, execution_id=ex.id, status=ExecutionStatus.COMPLETED)
        repository.record_verification_result(
            task_id=task.id,
            repository_id=repo.id,
            verified_revision="head-sha-777",
            status=VerificationStatus.PASSED,
            blocking_findings=[],
            summary="Verification passed without blockers",
        )

        # Task is now in READY_FOR_PUBLICATION
        assert task.status == TaskStatus.READY_FOR_PUBLICATION.value

        # Authorize publication
        updated_task = repository.authorize_publication(
            task_id=task.id,
            repository_id=repo.id,
            head_sha="head-sha-777",
            user_id=user.id,
            notes="Ready for PR with key sk-groqSecretKey1234567890123456",
        )

        assert updated_task.status == TaskStatus.PUBLISHING.value

        # Verify timeline event
        timeline = repository.get_task_timeline(task.id, repo.id)
        auth_events = [ev for ev in timeline if ev.event_type == TaskEventType.PUBLICATION_AUTHORIZED.value]
        assert len(auth_events) == 1
        assert auth_events[0].event_data["authorized_head_sha"] == "head-sha-777"
        assert "sk-" not in auth_events[0].event_data["notes"]
        assert "[REDACTED]" in auth_events[0].event_data["notes"]

    def test_authorize_publication_rejected_when_not_in_ready_status(self, db_session: Session) -> None:
        user, repo = _seed_user_and_repo(db_session, "pub-2")
        repository = TaskRepository(db_session)
        task = repository.create_task(repo.id, "Unverified task")
        task.status = TaskStatus.EXECUTING.value
        db_session.commit()

        with pytest.raises(InvalidStateTransitionError, match="requires READY_FOR_PUBLICATION"):
            repository.authorize_publication(task.id, repo.id, head_sha="some-sha")

    def test_authorize_publication_rejected_on_revision_mismatch(self, db_session: Session) -> None:
        user, repo = _seed_user_and_repo(db_session, "pub-3")
        repository = TaskRepository(db_session)
        task, plan, ws = _seed_approved_task_with_workspace(db_session, repo.id, user.id)

        ex = repository.record_execution_start(task.id, repo.id, worker_id="worker-01")
        repository.record_execution_finish(task.id, repo.id, execution_id=ex.id, status=ExecutionStatus.COMPLETED)
        repository.record_verification_result(
            task_id=task.id,
            repository_id=repo.id,
            verified_revision="verified-sha-111",
            status=VerificationStatus.PASSED,
        )

        # Attempt to authorize different revision
        with pytest.raises(InvalidStateTransitionError, match="does not match latest verified revision"):
            repository.authorize_publication(task.id, repo.id, head_sha="different-sha-222")

    def test_authorize_publication_rejected_if_verification_had_blocking_findings(self, db_session: Session) -> None:
        user, repo = _seed_user_and_repo(db_session, "pub-4")
        repository = TaskRepository(db_session)
        task, plan, ws = _seed_approved_task_with_workspace(db_session, repo.id, user.id)

        ex = repository.record_execution_start(task.id, repo.id, worker_id="worker-01")
        repository.record_execution_finish(task.id, repo.id, execution_id=ex.id, status=ExecutionStatus.COMPLETED)
        repository.record_verification_result(
            task_id=task.id,
            repository_id=repo.id,
            verified_revision="sha-blocked",
            status=VerificationStatus.PASSED,
            blocking_findings=[{"id": "CRIT-01", "msg": "Vulnerability detected"}],
        )

        # Task is BLOCKED, not READY_FOR_PUBLICATION
        with pytest.raises(InvalidStateTransitionError):
            repository.authorize_publication(task.id, repo.id, head_sha="sha-blocked")


# ===========================================================================
# 3. Pull Request Persistence & Idempotency (§6 F37)
# ===========================================================================

class TestPullRequestPersistence:
    """Verifies PR metadata persistence, state transitions, and retry idempotency."""

    def test_record_pull_request_advances_task_to_draft_pr_created(self, db_session: Session) -> None:
        user, repo = _seed_user_and_repo(db_session, "pr-1")
        repository = TaskRepository(db_session)
        task, plan, ws = _seed_approved_task_with_workspace(db_session, repo.id, user.id)

        ex = repository.record_execution_start(task.id, repo.id, worker_id="worker-01")
        repository.record_execution_finish(task.id, repo.id, execution_id=ex.id, status=ExecutionStatus.COMPLETED)
        repository.record_verification_result(
            task.id, repo.id, "sha-999", VerificationStatus.PASSED, blocking_findings=[]
        )
        repository.authorize_publication(task.id, repo.id, head_sha="sha-999", user_id=user.id)

        pr = repository.record_pull_request(
            task_id=task.id,
            repository_id=repo.id,
            pr_url="https://github.com/octocat/sample-repo/pull/42",
            base_branch="main",
            head_branch="agent/task-123",
            head_sha="sha-999",
            title="Fix authentication token refresh",
            body="Generated PR description with sk-apiKey12345678901234567890",
            pr_number=42,
            is_draft=True,
        )

        assert pr.id is not None
        assert pr.pr_number == 42
        assert pr.is_draft is True
        assert "sk-" not in pr.body
        assert "[REDACTED]" in pr.body

        # Verify task transitioned to DRAFT_PR_CREATED
        refreshed_task = repository.get_task(task.id, repo.id)
        assert refreshed_task.status == TaskStatus.DRAFT_PR_CREATED.value

        # Verify query method
        fetched_pr = repository.get_pull_request(task.id, repo.id)
        assert fetched_pr is not None
        assert fetched_pr.id == pr.id
        assert fetched_pr.pr_url == "https://github.com/octocat/sample-repo/pull/42"

    def test_record_pull_request_blocked_without_publication_authorization(self, db_session: Session) -> None:
        user, repo = _seed_user_and_repo(db_session, "pr-2")
        repository = TaskRepository(db_session)
        task = repository.create_task(repo.id, "Task not yet published")
        task.status = TaskStatus.EXECUTING.value
        db_session.commit()

        with pytest.raises(InvalidStateTransitionError, match="Publication authorization is required"):
            repository.record_pull_request(
                task_id=task.id,
                repository_id=repo.id,
                pr_url="https://github.com/org/repo/pull/99",
                base_branch="main",
                head_branch="agent/task-unauthorized",
                head_sha="sha-unauth",
                title="Unauthorized PR",
            )

    def test_record_pull_request_is_idempotent_on_retries(self, db_session: Session) -> None:
        user, repo = _seed_user_and_repo(db_session, "pr-3")
        repository = TaskRepository(db_session)
        task, plan, ws = _seed_approved_task_with_workspace(db_session, repo.id, user.id)

        ex = repository.record_execution_start(task.id, repo.id, worker_id="worker-01")
        repository.record_execution_finish(task.id, repo.id, execution_id=ex.id, status=ExecutionStatus.COMPLETED)
        repository.record_verification_result(task.id, repo.id, "sha-idem", VerificationStatus.PASSED)
        repository.authorize_publication(task.id, repo.id, head_sha="sha-idem")

        # Initial PR creation
        pr1 = repository.record_pull_request(
            task_id=task.id,
            repository_id=repo.id,
            pr_url="https://github.com/org/repo/pull/10",
            base_branch="main",
            head_branch="agent/task-idem",
            head_sha="sha-idem",
            title="Initial draft title",
            pr_number=10,
        )

        # Retry with updated title / details (e.g. network retry after draft PR created)
        pr2 = repository.record_pull_request(
            task_id=task.id,
            repository_id=repo.id,
            pr_url="https://github.com/org/repo/pull/10",
            base_branch="main",
            head_branch="agent/task-idem",
            head_sha="sha-idem",
            title="Updated draft title on retry",
            pr_number=10,
        )

        assert pr1.id == pr2.id
        assert pr2.title == "Updated draft title on retry"


# ===========================================================================
# 4. End-to-End Traceability Graph (§6 F39, Day 5 Deliverable)
# ===========================================================================

class TestEndToEndTraceability:
    """Verifies complete traceability graph: Finding -> Issue/Task -> Plan -> Workspace -> Execution -> Test -> Repair -> Verification -> PR."""

    def test_end_to_end_traceability_graph_complete(self, db_session: Session) -> None:
        user, repo = _seed_user_and_repo(db_session, "trace-1")
        repository = TaskRepository(db_session)

        # 1. Seed Week 2 Finding
        analysis_run = AnalysisRun(
            id=uuid.uuid4(),
            repository_id=repo.id,
            feature_type=AnalysisFeature.DETECT_BUGS.value,
            status=AnalysisRunStatus.COMPLETED.value,
            target_path="backend/app/auth.py",
            source_revision="base-commit-000",
        )
        db_session.add(analysis_run)
        db_session.flush()

        finding = AnalysisFinding(
            id=uuid.uuid4(),
            analysis_run_id=analysis_run.id,
            repository_id=repo.id,
            category="SECURITY",
            severity="HIGH",
            title="Hardcoded credential leak in auth.py",
            description="Found sensitive credential reference",
            evidence="const token = 'sk-test'",
            file_path="backend/app/auth.py",
            start_line=45,
            end_line=48,
        )
        db_session.add(finding)
        db_session.flush()

        # 2. Create Task linked to Finding
        task = repository.create_task(
            repository_id=repo.id,
            title="Fix credential leak in auth.py",
            source_type=TaskSourceType.BUG_FINDING,
            finding_id=finding.id,
            user_id=user.id,
            base_revision="base-commit-000",
        )

        # 3. Plan & Approve
        plan = repository.save_plan(
            task_id=task.id,
            repository_id=repo.id,
            summary="Remediate credential leak",
            steps=[{"step": 1, "action": "Move credential to env"}],
            expected_files=["backend/app/auth.py"],
            base_revision="base-commit-000",
        )
        repository.approve_plan(task.id, repo.id, plan_version=plan.version, user_id=user.id)

        # 4. Workspace
        ws = repository.record_workspace(
            task_id=task.id,
            repository_id=repo.id,
            task_branch=f"agent/task-{task.id}",
            base_revision="base-commit-000",
            workspace_path=f"/tmp/workspaces/{task.id}",
        )

        # 5. Execution
        exec_start = repository.record_execution_start(task.id, repo.id, worker_id="worker-e2e")
        exec_finish = repository.record_execution_finish(task.id, repo.id, execution_id=exec_start.id, status=ExecutionStatus.COMPLETED)

        # 6. Test Run
        test_run = repository.record_test_run(
            task_id=task.id,
            repository_id=repo.id,
            command="pytest backend/tests/test_auth.py",
            status=TestRunStatus.PASSED,
            tests_total=5,
            tests_passed=5,
            tests_failed=0,
            target_revision="rev-final-999",
        )

        # 7. Verification
        ver = repository.record_verification_result(
            task_id=task.id,
            repository_id=repo.id,
            verified_revision="rev-final-999",
            status=VerificationStatus.PASSED,
            checks=[{"name": "tests", "status": "PASSED"}],
            blocking_findings=[],
            summary="All independent verification checks passed",
        )

        # 8. Publication Authorization
        repository.authorize_publication(task.id, repo.id, head_sha="rev-final-999", user_id=user.id)

        # 9. Draft PR
        pr = repository.record_pull_request(
            task_id=task.id,
            repository_id=repo.id,
            pr_url="https://github.com/org/repo/pull/88",
            base_branch="main",
            head_branch=f"agent/task-{task.id}",
            head_sha="rev-final-999",
            title="[Draft] Remediate credential leak in auth.py",
            pr_number=88,
        )

        # 10. Query Traceability Graph
        trace = repository.get_task_traceability(task.id, repo.id)

        assert trace["task"]["task_id"] == str(task.id)
        assert trace["task"]["status"] == TaskStatus.DRAFT_PR_CREATED.value

        # Finding linkage
        assert trace["finding"] is not None
        assert trace["finding"]["finding_id"] == str(finding.id)
        assert trace["finding"]["severity"] == "HIGH"

        # Plan linkage
        assert trace["latest_plan"] is not None
        assert trace["latest_plan"]["version"] == 1

        # Approval linkage
        assert trace["latest_approval"] is not None
        assert trace["latest_approval"]["decision"] == ApprovalDecision.APPROVED.value

        # Workspace linkage
        assert trace["workspace"] is not None
        assert trace["workspace"]["task_branch"] == f"agent/task-{task.id}"

        # Execution linkage
        assert trace["latest_execution"] is not None
        assert trace["latest_execution"]["worker_id"] == "worker-e2e"

        # Test Run linkage
        assert trace["latest_test_run"] is not None
        assert trace["latest_test_run"]["tests_passed"] == 5

        # Verification linkage
        assert trace["latest_verification"] is not None
        assert trace["latest_verification"]["verified_revision"] == "rev-final-999"

        # Pull Request linkage
        assert trace["pull_request"] is not None
        assert trace["pull_request"]["pr_number"] == 88

        # Timeline linkage
        assert len(trace["timeline"]) >= 7

        # Overall traceability status
        assert trace["traceability_status"] == "COMPLETE"


# ===========================================================================
# 5. Multi-Tenant Isolation & Security
# ===========================================================================

class TestMultiTenantDay5Isolation:
    """Verifies that verification, pull request, and traceability are repository-isolated."""

    def test_cross_repository_verification_and_pr_access_blocked(self, db_session: Session) -> None:
        user1, repo1 = _seed_user_and_repo(db_session, "iso-1")
        user2, repo2 = _seed_user_and_repo(db_session, "iso-2")
        repository = TaskRepository(db_session)

        task1, plan1, ws1 = _seed_approved_task_with_workspace(db_session, repo1.id, user1.id)
        ex = repository.record_execution_start(task1.id, repo1.id, worker_id="w1")
        repository.record_execution_finish(task1.id, repo1.id, execution_id=ex.id, status=ExecutionStatus.COMPLETED)
        repository.record_verification_result(task1.id, repo1.id, "sha-iso", VerificationStatus.PASSED)
        repository.authorize_publication(task1.id, repo1.id, head_sha="sha-iso")
        repository.record_pull_request(
            task_id=task1.id,
            repository_id=repo1.id,
            pr_url="https://github.com/org/repo1/pull/1",
            base_branch="main",
            head_branch="agent/task-1",
            head_sha="sha-iso",
            title="Repo 1 PR",
        )

        # Attempt to access Repo 1 artifacts via Repo 2
        with pytest.raises(TaskNotFoundError):
            repository.get_verification_results(task1.id, repo2.id)

        with pytest.raises(TaskNotFoundError):
            repository.get_pull_request(task1.id, repo2.id)

        with pytest.raises(TaskNotFoundError):
            repository.authorize_publication(task1.id, repo2.id, head_sha="sha-iso")

        with pytest.raises(TaskNotFoundError):
            repository.get_task_traceability(task1.id, repo2.id)


# ===========================================================================
# 6. Pydantic Response Schema Conformity
# ===========================================================================

class TestDay5PydanticSchemaConformity:
    """Verifies that model to_dict() envelopes match Day 5 Pydantic response models."""

    def test_model_to_dict_matches_pydantic_day5_response_schemas(self, db_session: Session) -> None:
        user, repo = _seed_user_and_repo(db_session, "schema-1")
        repository = TaskRepository(db_session)
        task, plan, ws = _seed_approved_task_with_workspace(db_session, repo.id, user.id)

        ex = repository.record_execution_start(task.id, repo.id, worker_id="w-schema")
        repository.record_execution_finish(task.id, repo.id, execution_id=ex.id, status=ExecutionStatus.COMPLETED)

        ver = repository.record_verification_result(
            task.id, repo.id, "sha-pydantic", VerificationStatus.PASSED, summary="Verified"
        )
        ver_dict = ver.to_dict()
        ver_pydantic = VerificationResultResponse.model_validate(ver_dict)
        assert ver_pydantic.verified_revision == "sha-pydantic"

        repository.authorize_publication(task.id, repo.id, head_sha="sha-pydantic", user_id=user.id)

        pr = repository.record_pull_request(
            task.id, repo.id, "https://github.com/octo/repo/pull/5", "main", "agent/task", "sha-pydantic", "PR title", pr_number=5
        )
        pr_dict = pr.to_dict()
        pr_pydantic = TaskPullRequestResponse.model_validate(pr_dict)
        assert pr_pydantic.pr_number == 5

        # Traceability response schema validation
        trace = repository.get_task_traceability(task.id, repo.id)
        trace_pydantic = TaskTraceabilityResponse.model_validate(trace)
        assert trace_pydantic.traceability_status == "COMPLETE"
        assert trace_pydantic.pull_request.pr_url == "https://github.com/octo/repo/pull/5"
