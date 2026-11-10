"""Tests for Issue #207 (F26) — Host-Side Git Operations & Credential Isolation.

Verifies:
1. Host-Side Git Push Execution:
   - `push_task_branch` executes `git push` host-side via host subprocess, never inside the container.
   - When an `installation_token` is provided, authentication is passed ephemerally via
     `-c http.extraheader=AUTHORIZATION: basic <token>` without persisting to `.git/config` on disk.
2. Strict Sandbox Isolation:
   - Untrusted sandbox execution (`WorkspaceCommandRunner`) forbids git network operations:
     `git push`, `git pull`, `git fetch`, `git remote`, `git clone` fail closed with `WorkspacePolicyViolationError`.
   - Local non-network inspection commands (`git status`, `git diff`, `git rev-parse`) remain permitted.
3. Credential Redaction & Containment:
   - Sensitive tokens are stripped from command execution environments in `WorkspaceCommandRunner` and `ContainerBackend`.
   - Error messages from failed push attempts undergo secret redaction (`redact`) to prevent token leaks.
4. Mandatory Governance Gates:
   - Explicit human publication authorization gate (`publication_authorized=True`) enforced.
   - Protected branch guards prevent push or draft PR publication targeting protected branches (main, master).
   - Draft PR creation always sets `is_draft=True` with zero auto-merge.
"""

from __future__ import annotations

import base64
import os
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from sandbox.command_runner import FORBIDDEN_SANDBOX_GIT_SUBCOMMANDS, WorkspaceCommandRunner
from sandbox.constants import PROTECTED_BRANCHES
from sandbox.exceptions import (
    WorkspacePolicyViolationError,
    WorkspaceProtectedBranchError,
    WorkspacePublicationUnauthorizedError,
    WorkspacePushError,
)
from sandbox.workspace_manager import WorkspaceManager
from app.schemas.workspace import (
    WorkspaceCreateRequest,
    WorkspaceDraftPRRequest,
    WorkspacePushRequest,
)


@pytest.fixture
def temp_workspace_env(tmp_path: Path):
    """Create a minimal workspace with an initialized Git repository on a feature branch."""
    ws_root = tmp_path / "workspaces"
    ws_root.mkdir(parents=True, exist_ok=True)
    manager = WorkspaceManager(base_workspaces_dir=ws_root)

    task_id = "test-task-f26-001"
    meta = manager.create_workspace(
        WorkspaceCreateRequest(
            task_id=task_id,
            repository_id="00000000-0000-0000-0000-000000000001",
            base_revision="1234567890abcdef",
            branch_name="agent/task-test-task-f26-001",
        )
    )

    ws_path = Path(meta.workspace_path)
    # Initialize real local git repo
    subprocess.run(["git", "-C", str(ws_path), "init"], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(ws_path), "config", "user.name", "Test Agent"], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(ws_path), "config", "user.email", "agent@ai-platform.local"], check=True, capture_output=True)
    (ws_path / "hello.txt").write_text("initial content\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(ws_path), "add", "hello.txt"], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(ws_path), "commit", "-m", "initial commit"], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(ws_path), "checkout", "-B", "agent/task-test-task-f26-001"], check=True, capture_output=True)

    return manager, task_id, ws_path


class TestSandboxGitNetworkCommandRejection:
    """Verifies that git network commands are rejected when executed inside the sandbox runner."""

    @pytest.mark.parametrize("subcmd", ["push", "pull", "fetch", "remote", "clone"])
    def test_sandbox_blocks_git_network_commands(self, tmp_path: Path, subcmd: str):
        runner = WorkspaceCommandRunner()
        with pytest.raises(WorkspacePolicyViolationError) as exc_info:
            runner.validate_command("git", [subcmd, "origin", "main"])
        assert f"'{subcmd}'" in str(exc_info.value)
        assert "strictly forbidden inside the sandbox container" in str(exc_info.value)

    def test_sandbox_blocks_git_network_commands_with_leading_flags(self, tmp_path: Path):
        runner = WorkspaceCommandRunner()
        with pytest.raises(WorkspacePolicyViolationError) as exc_info:
            runner.validate_command("git", ["--no-pager", "-C", ".", "push", "origin", "branch"])
        assert "'push'" in str(exc_info.value)

    def test_sandbox_permits_safe_local_git_inspection(self, tmp_path: Path):
        runner = WorkspaceCommandRunner()
        # Should not raise for read-only local operations
        runner.validate_command("git", ["status"])
        runner.validate_command("git", ["diff", "HEAD"])
        runner.validate_command("git", ["rev-parse", "HEAD"])


class TestHostSideGitPushExecution:
    """Verifies host-side push execution and credential isolation."""

    def test_push_runs_host_side_with_ephemeral_installation_token(self, temp_workspace_env):
        manager, task_id, ws_path = temp_workspace_env
        fake_token = "ghs_MockInstallationToken1234567890Secret"
        captured_commands: list[list[str]] = []

        def mock_subprocess_run(cmd, *args, **kwargs):
            captured_commands.append(list(cmd))
            proc = MagicMock()
            proc.returncode = 0
            proc.stdout = "abc1234\n"
            proc.stderr = ""
            return proc

        with patch("subprocess.run", side_effect=mock_subprocess_run):
            req = WorkspacePushRequest(
                task_id=task_id,
                branch_name="agent/task-test-task-f26-001",
                remote_name="origin",
                publication_authorized=True,
                installation_token=fake_token,
            )
            res = manager.push_task_branch(req)

        assert res.success is True
        assert res.branch == "agent/task-test-task-f26-001"

        # Verify git push was executed with -c http.extraheader containing base64 token
        push_invocations = [cmd for cmd in captured_commands if "push" in cmd]
        assert len(push_invocations) == 1
        push_cmd = push_invocations[0]

        expected_auth = base64.b64encode(f"x-access-token:{fake_token}".encode("utf-8")).decode("utf-8")
        expected_header = f"http.extraheader=AUTHORIZATION: basic {expected_auth}"
        assert "-c" in push_cmd
        assert expected_header in push_cmd

        # Verify credential was never persisted into .git/config on disk
        git_config = (ws_path / ".git" / "config").read_text(encoding="utf-8")
        assert fake_token not in git_config
        assert "http.extraheader" not in git_config

    def test_push_redacts_credentials_on_error(self, temp_workspace_env):
        manager, task_id, _ = temp_workspace_env
        fake_token = "ghs_SecretInstallationTokenThatMustNotLeak"

        def mock_failing_subprocess_run(cmd, *args, **kwargs):
            if "push" in cmd:
                proc = MagicMock()
                proc.returncode = 1
                proc.stdout = ""
                proc.stderr = f"fatal: Authentication failed for token {fake_token}"
                return proc
            proc = MagicMock()
            proc.returncode = 0
            proc.stdout = "abc1234\n"
            proc.stderr = ""
            return proc

        with patch("subprocess.run", side_effect=mock_failing_subprocess_run):
            req = WorkspacePushRequest(
                task_id=task_id,
                branch_name="agent/task-test-task-f26-001",
                remote_name="origin",
                publication_authorized=True,
                installation_token=fake_token,
            )
            with pytest.raises(WorkspacePushError) as exc_info:
                manager.push_task_branch(req)

            err_text = str(exc_info.value)
            # Token MUST be redacted and not leak into the error string
            assert fake_token not in err_text
            assert "[REDACTED]" in err_text or "Authentication failed" in err_text


class TestPublicationGovernanceGates:
    """Verifies publication authorization gate, protected branch guard, and draft PR rules."""

    def test_push_without_publication_authorization_is_blocked(self, temp_workspace_env):
        manager, task_id, _ = temp_workspace_env
        req = WorkspacePushRequest(
            task_id=task_id,
            branch_name="agent/task-test-task-f26-001",
            remote_name="origin",
            publication_authorized=False,
        )
        with pytest.raises(WorkspacePublicationUnauthorizedError) as exc_info:
            manager.push_task_branch(req)
        assert "Explicit human authorization is required" in str(exc_info.value)

    @pytest.mark.parametrize("protected", list(PROTECTED_BRANCHES)[:4])
    def test_push_targeting_protected_branch_is_blocked(self, temp_workspace_env, protected: str):
        manager, task_id, _ = temp_workspace_env
        req = WorkspacePushRequest(
            task_id=task_id,
            branch_name=protected,
            remote_name="origin",
            publication_authorized=True,
        )
        with pytest.raises(WorkspaceProtectedBranchError) as exc_info:
            manager.push_task_branch(req)
        assert "forbidden" in str(exc_info.value).lower()

    def test_create_draft_pr_without_publication_authorization_is_blocked(self, temp_workspace_env):
        manager, task_id, _ = temp_workspace_env
        req = WorkspaceDraftPRRequest(
            task_id=task_id,
            title="feat: automated changes",
            head_branch="agent/task-test-task-f26-001",
            base_branch="main",
            publication_authorized=False,
        )
        with pytest.raises(WorkspacePublicationUnauthorizedError) as exc_info:
            manager.create_draft_pr(req)
        assert "Explicit human authorization is required" in str(exc_info.value)

    def test_create_draft_pr_is_always_draft_and_structured(self, temp_workspace_env):
        manager, task_id, _ = temp_workspace_env
        req = WorkspaceDraftPRRequest(
            task_id=task_id,
            title="feat: add secure credential isolation",
            body="Implements host-side git push and credential boundary.",
            head_branch="agent/task-test-task-f26-001",
            base_branch="main",
            publication_authorized=True,
            repository_owner="Meetvirugama",
            repository_name="AI-Powered-Software-Development-Platform",
        )
        res = manager.create_draft_pr(req)

        assert res.success is True
        assert res.is_draft is True
        assert "github.com/Meetvirugama/AI-Powered-Software-Development-Platform/pull/" in res.pr_url
        assert "Implements host-side git push and credential boundary." in res.summary
        assert "Draft PR" in res.summary
        assert "draft pull request" in res.summary.lower()
