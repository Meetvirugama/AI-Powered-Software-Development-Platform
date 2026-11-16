"""Security test for Git Push credential isolation (TST-06, ISS-019).

Validates:
- Installation token is passed strictly via process environment (GIT_CONFIG_*),
  never exposed in command line argv where other processes could inspect it via ps / procfs.
"""

from pathlib import Path
from unittest.mock import MagicMock, patch

from app.schemas.workspace import WorkspaceCreateRequest, WorkspacePushRequest
from sandbox.workspace_manager import WorkspaceManager


def test_push_task_branch_never_exposes_token_in_argv(tmp_path: Path) -> None:
    """TST-06: Token must not appear in subprocess argv when executing git push."""
    wm = WorkspaceManager(base_workspaces_dir=tmp_path / "workspaces")
    task_id = "test-task-cred-isolation"

    # Create workspace
    wm.create_workspace(
        WorkspaceCreateRequest(
            task_id=task_id,
            repository_id="repo-1",
            base_revision="1234567",
        )
    )

    secret_token = "ghs_SuperSecretGitHubToken9876543210"

    mock_proc = MagicMock()
    mock_proc.returncode = 0
    mock_proc.stdout = "Branch pushed successfully"
    mock_proc.stderr = ""

    captured_cmds = []
    captured_envs = []

    def fake_subprocess_run(cmd, *args, **kwargs):
        captured_cmds.append(list(cmd))
        captured_envs.append(dict(kwargs.get("env") or {}))
        return mock_proc

    with patch("sandbox.workspace_manager.subprocess.run", side_effect=fake_subprocess_run):
        req = WorkspacePushRequest(
            task_id=task_id,
            branch_name="agent/feature-branch",
            remote_name="origin",
            publication_authorized=True,
            installation_token=secret_token,
        )
        res = wm.push_task_branch(req)
        assert res.success is True

    assert len(captured_cmds) >= 1
    push_cmd = next(c for c in captured_cmds if "push" in c)
    push_index = captured_cmds.index(push_cmd)
    push_env = captured_envs[push_index]

    # Verify no part of the token appears in any argv element of any subprocess command
    for cmd in captured_cmds:
        for arg in cmd:
            assert secret_token not in str(arg), f"Security violation: Secret token leaked in argv: {arg}"
            assert "x-access-token" not in str(arg)

    # Verify token is safely configured via GIT_CONFIG_* environment variables
    assert push_env.get("GIT_CONFIG_COUNT") == "1"
    assert push_env.get("GIT_CONFIG_KEY_0") == "http.extraheader"
    assert "AUTHORIZATION: basic" in push_env.get("GIT_CONFIG_VALUE_0", "")
