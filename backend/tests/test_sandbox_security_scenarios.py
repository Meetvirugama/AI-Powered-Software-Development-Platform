"""Automated Security Attack Scenario Test Suite for Sandbox Isolation Architecture.

Owner: AI Platform Security Architecture — Issue #200 / F20
Reference: task.md §10.3 (Tests 1-12) & Docs/security/sandbox/09-security-testing.md
"""

from __future__ import annotations

import os
import shutil
import socket
import subprocess
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import httpx
import pytest

from app.core.config import settings
from sandbox.backend import SandboxBackend
from sandbox.command_runner import WorkspaceCommandRunner
from sandbox.container_backend import ContainerBackend
from sandbox.exceptions import (
    RunnerAuthenticationError,
    RunnerUnavailableError,
    SandboxConfigurationError,
    SandboxSecurityError,
    WorkspaceCommandError,
    WorkspaceError,
    WorkspacePathEscapeError,
)
from sandbox.factory import SandboxFactory
from sandbox.local_backend import LocalSubprocessBackend
from sandbox.path_guard import WorkspacePathGuard
from sandbox.runner_client import RunnerClient
from sandbox.two_phase_pipeline import TwoPhaseExecutionService


# ---------------------------------------------------------------------------
# Test 1: Host Secret Access
# ---------------------------------------------------------------------------
def test_security_scenario_1_host_secret_access_blocked(tmp_path, monkeypatch):
    """Test 1: Repository code / path traversal cannot access host secrets outside the workspace."""
    # Place a simulated host secret outside workspace root
    host_secret_dir = tmp_path / "host_secrets"
    host_secret_dir.mkdir(parents=True)
    secret_file = host_secret_dir / "platform_vault.env"
    secret_file.write_text("SUPER_SECRET_PLATFORM_KEY=secret_vault_99999\n")

    workspace_dir = tmp_path / "workspaces" / "task-101"
    workspace_dir.mkdir(parents=True)

    # 1. Path Guard must reject climbing out to secret_file
    with pytest.raises(WorkspacePathEscapeError):
        WorkspacePathGuard.resolve_within_workspace(
            workspace_root=workspace_dir,
            relative_path="../../host_secrets/platform_vault.env",
        )

    # 2. CommandRunner must sanitize environment stripping host secret
    monkeypatch.setenv("SUPER_SECRET_PLATFORM_KEY", "secret_vault_99999")
    clean_env = WorkspaceCommandRunner().sanitize_environment()
    assert "SUPER_SECRET_PLATFORM_KEY" not in clean_env
    assert clean_env.get("PIP_NO_INDEX") == "1"


# ---------------------------------------------------------------------------
# Test 2: Cross-Task Workspace Access
# ---------------------------------------------------------------------------
def test_security_scenario_2_cross_task_access_blocked(tmp_path):
    """Test 2: Task A cannot access or mutate Task B's workspace directory."""
    task_a_dir = tmp_path / "workspaces" / "task-A"
    task_b_dir = tmp_path / "workspaces" / "task-B"
    task_a_dir.mkdir(parents=True)
    task_b_dir.mkdir(parents=True)

    task_b_file = task_b_dir / "confidential_code.py"
    task_b_file.write_text("# Sensitive Task B code\n")

    # From Task A's root, attempting to traverse to Task B must fail closed
    with pytest.raises(WorkspacePathEscapeError):
        WorkspacePathGuard.resolve_within_workspace(
            workspace_root=task_a_dir,
            relative_path="../task-B/confidential_code.py",
        )


# ---------------------------------------------------------------------------
# Test 3: Network Exfiltration Blocking (--network=none)
# ---------------------------------------------------------------------------
def test_security_scenario_3_network_exfiltration_blocked(tmp_path, monkeypatch):
    """Test 3: Offline test phase enforces --network=none, preventing external socket connections."""
    backend = ContainerBackend(base_workspaces_dir=tmp_path, use_gvisor=False)
    backend.create_workspace("task-exfil-test")
    backend.write_file(
        "task-exfil-test",
        "exfil.py",
        "import socket\ns = socket.socket()\ns.connect(('1.1.1.1', 80))\n",
    )

    captured_cmds = []

    def mock_popen(cmd, **kwargs):
        captured_cmds.append(cmd)
        mock_proc = MagicMock()
        mock_proc.returncode = 1
        mock_proc.stdout = MagicMock()
        mock_proc.stdout.read.side_effect = [b"SocketError: Network is unreachable\n", b""]
        mock_proc.stderr = MagicMock()
        mock_proc.stderr.read.side_effect = [b""]
        mock_proc.wait.return_value = 1
        return mock_proc

    with patch("sandbox.container_backend.subprocess.Popen", side_effect=mock_popen):
        # Execute in Phase B offline mode
        res = backend.execute(
            task_id="task-exfil-test",
            command="python",
            arguments=["exfil.py"],
            network_enabled=False,
        )

    assert len(captured_cmds) == 1
    cmd = captured_cmds[0]
    # Enforces strict Docker network disconnection
    assert "--network=none" in cmd
    assert res.resource_metrics["network_isolated"] is True


# ---------------------------------------------------------------------------
# Test 4: CPU Exhaustion Protection
# ---------------------------------------------------------------------------
def test_security_scenario_4_cpu_exhaustion_limits(tmp_path, monkeypatch):
    """Test 4: High-CPU loops are bounded by --cpus limit and terminated on timeout."""
    monkeypatch.setattr("sandbox.container_backend.settings.sandbox_cpu_limit", 2.0)
    backend = ContainerBackend(base_workspaces_dir=tmp_path, use_gvisor=False)
    backend.create_workspace("task-cpu-loop")
    backend.write_file(
        "task-cpu-loop",
        "loop.py",
        "while True:\n    pass\n",
    )

    captured_cmds = []

    def mock_popen(cmd, **kwargs):
        captured_cmds.append(cmd)
        mock_proc = MagicMock()
        # Simulate timeout on infinite loop
        mock_proc.wait.side_effect = subprocess.TimeoutExpired(cmd, timeout=2)
        mock_proc.stdout = MagicMock()
        mock_proc.stdout.read.return_value = b""
        mock_proc.stderr = MagicMock()
        mock_proc.stderr.read.return_value = b""
        return mock_proc

    with patch("sandbox.container_backend.subprocess.Popen", side_effect=mock_popen):
        with patch("sandbox.container_backend.subprocess.run") as mock_run:
            res = backend.execute(
                task_id="task-cpu-loop",
                command="python",
                arguments=["loop.py"],
                timeout_seconds=2,
            )
            # Verify docker kill was dispatched
            assert any("docker" in call[0][0] and "kill" in call[0][0] for call in mock_run.call_args_list)

    assert res.timed_out is True
    assert res.success is False
    assert "--cpus=2.0" in captured_cmds[0]


# ---------------------------------------------------------------------------
# Test 5: Memory Exhaustion Protection
# ---------------------------------------------------------------------------
def test_security_scenario_5_memory_exhaustion_limit(tmp_path, monkeypatch):
    """Test 5: Container enforces memory limit (--memory=4g), preventing host OOM."""
    monkeypatch.setattr("sandbox.container_backend.settings.sandbox_memory_limit", "4g")
    backend = ContainerBackend(base_workspaces_dir=tmp_path, use_gvisor=False)
    backend.create_workspace("task-mem-bomb")

    captured_cmds = []

    def mock_popen(cmd, **kwargs):
        captured_cmds.append(cmd)
        mock_proc = MagicMock()
        mock_proc.returncode = 137  # Standard Linux OOM killer exit code (128 + 9)
        mock_proc.stdout = MagicMock()
        mock_proc.stdout.read.side_effect = [b"Killed\n", b""]
        mock_proc.stderr = MagicMock()
        mock_proc.stderr.read.side_effect = [b"MemoryError: Out of memory\n", b""]
        mock_proc.wait.return_value = 137
        return mock_proc

    with patch("sandbox.container_backend.subprocess.Popen", side_effect=mock_popen):
        res = backend.execute(
            task_id="task-mem-bomb",
            command="python",
            arguments=["-c", "x = bytearray(8 * 1024**3)"],
        )

    assert "--memory=4g" in captured_cmds[0]
    assert res.exit_code == 137
    assert res.success is False


# ---------------------------------------------------------------------------
# Test 6: Process Exhaustion Protection (Fork Bomb)
# ---------------------------------------------------------------------------
def test_security_scenario_6_process_exhaustion_limit(tmp_path, monkeypatch):
    """Test 6: Container enforces strict PID limit (--pids-limit=512) against fork-bombs."""
    monkeypatch.setattr("sandbox.container_backend.settings.sandbox_pid_limit", 512)
    backend = ContainerBackend(base_workspaces_dir=tmp_path, use_gvisor=False)
    backend.create_workspace("task-fork-bomb")
    backend.write_file(
        "task-fork-bomb",
        "fork_bomb.py",
        "import os\nfor _ in range(1000):\n    os.fork()\n",
    )

    captured_cmds = []

    def mock_popen(cmd, **kwargs):
        captured_cmds.append(cmd)
        mock_proc = MagicMock()
        mock_proc.returncode = 1
        mock_proc.stdout = MagicMock()
        mock_proc.stdout.read.side_effect = [b"", b""]
        mock_proc.stderr = MagicMock()
        mock_proc.stderr.read.side_effect = [b"BlockingIOError: [Errno 11] Resource temporarily unavailable\n", b""]
        mock_proc.wait.return_value = 1
        return mock_proc

    with patch("sandbox.container_backend.subprocess.Popen", side_effect=mock_popen):
        res = backend.execute(
            task_id="task-fork-bomb",
            command="python",
            arguments=["fork_bomb.py"],
        )

    assert "--pids-limit=512" in captured_cmds[0]
    assert res.success is False


# ---------------------------------------------------------------------------
# Test 7: Filesystem Writes & Read-Only Root Filesystem
# ---------------------------------------------------------------------------
def test_security_scenario_7_filesystem_isolation_and_readonly_root(tmp_path):
    """Test 7: Writable mounts are restricted to /workspace and tmpfs /tmp; rootfs is read-only."""
    backend = ContainerBackend(base_workspaces_dir=tmp_path, use_gvisor=False)
    backend.create_workspace("task-fs-test")
    backend.write_file(
        "task-fs-test",
        "write_usr.py",
        "open('/usr/test.txt', 'w').write('hack')\n",
    )

    captured_cmds = []

    def mock_popen(cmd, **kwargs):
        captured_cmds.append(cmd)
        mock_proc = MagicMock()
        mock_proc.returncode = 1
        mock_proc.stdout = MagicMock()
        mock_proc.stdout.read.side_effect = [b"", b""]
        mock_proc.stderr = MagicMock()
        mock_proc.stderr.read.side_effect = [b"Read-only file system: '/usr/test.txt'\n", b""]
        mock_proc.wait.return_value = 1
        return mock_proc

    with patch("sandbox.container_backend.subprocess.Popen", side_effect=mock_popen):
        res = backend.execute(
            task_id="task-fs-test",
            command="python",
            arguments=["write_usr.py"],
        )

    cmd = captured_cmds[0]
    assert "--read-only" in cmd
    assert any("/tmp:rw,noexec,nosuid" in c for c in cmd)
    assert res.success is False


# ---------------------------------------------------------------------------
# Test 8: Docker Socket Prohibition
# ---------------------------------------------------------------------------
def test_security_scenario_8_docker_socket_not_mounted(tmp_path):
    """Test 8: Host Docker socket /var/run/docker.sock is never passed into the container."""
    backend = ContainerBackend(base_workspaces_dir=tmp_path, use_gvisor=False)
    backend.create_workspace("task-docker-sock-test")
    backend.write_file(
        "task-docker-sock-test",
        "check_sock.py",
        "import os\nassert not os.path.exists('/var/run/docker.sock')\n",
    )

    captured_cmds = []

    def mock_popen(cmd, **kwargs):
        captured_cmds.append(cmd)
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stdout = MagicMock()
        mock_proc.stdout.read.side_effect = [b"Docker socket not found\n", b""]
        mock_proc.stderr = MagicMock()
        mock_proc.stderr.read.side_effect = [b"", b""]
        mock_proc.wait.return_value = 0
        return mock_proc

    with patch("sandbox.container_backend.subprocess.Popen", side_effect=mock_popen):
        res = backend.execute(
            task_id="task-docker-sock-test",
            command="python",
            arguments=["check_sock.py"],
        )

    cmd = captured_cmds[0]
    # Verify no docker.sock bind mounts exist
    assert not any("docker.sock" in c for c in cmd)


# ---------------------------------------------------------------------------
# Test 9: Symbolic Link Path Traversal Rejection
# ---------------------------------------------------------------------------
def test_security_scenario_9_symlink_escape_rejection(tmp_path):
    """Test 9: Malicious symlinks pointing outside the workspace boundary are rejected."""
    outside_target = tmp_path / "outside_dir"
    outside_target.mkdir()
    outside_file = outside_target / "host_file.txt"
    outside_file.write_text("Confidential Host File")

    workspace = tmp_path / "workspaces" / "task-symlink"
    workspace.mkdir(parents=True)

    # Create symlink pointing outside
    symlink_path = workspace / "escape_link"
    try:
        symlink_path.symlink_to(outside_target)
    except OSError:
        pytest.skip("Symlink creation not permitted in current OS sandbox")

    # Path guard must detect that resolving this symlink escapes workspace root
    with pytest.raises(WorkspacePathEscapeError):
        WorkspacePathGuard.resolve_within_workspace(workspace, "escape_link/host_file.txt")


# ---------------------------------------------------------------------------
# Test 10: Malicious Repository Hooks & Conftest Isolation
# ---------------------------------------------------------------------------
def test_security_scenario_10_malicious_hooks_isolated(tmp_path, monkeypatch):
    """Test 10: Malicious pytest fixtures in conftest.py execute strictly inside the container."""
    monkeypatch.setattr("sandbox.container_backend.settings.sandbox_backend", "container")
    backend = ContainerBackend(base_workspaces_dir=tmp_path, use_gvisor=False)
    backend.create_workspace("task-malicious-conftest")

    # Write a malicious conftest.py
    conftest_content = (
        "import pytest, os\n"
        "@pytest.fixture(autouse=True)\n"
        "def steal_secrets():\n"
        "    return os.environ.get('GEMINI_API_KEY')\n"
    )
    backend.write_file("task-malicious-conftest", "tests/conftest.py", conftest_content)

    captured_cmds = []

    def mock_popen(cmd, **kwargs):
        captured_cmds.append(cmd)
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stdout = MagicMock()
        mock_proc.stdout.read.side_effect = [b"1 passed in 0.05s\n", b""]
        mock_proc.stderr = MagicMock()
        mock_proc.stderr.read.side_effect = [b"", b""]
        mock_proc.wait.return_value = 0
        return mock_proc

    with patch("sandbox.container_backend.subprocess.Popen", side_effect=mock_popen):
        res = backend.execute(
            task_id="task-malicious-conftest",
            command="pytest",
            arguments=["tests/conftest.py"],
            network_enabled=False,
        )

    cmd = captured_cmds[0]
    # Untrusted pytest executed inside container with --network=none and read-only rootfs
    assert cmd[0] == "docker"
    assert "--network=none" in cmd
    assert "--read-only" in cmd
    assert res.success is True


# ---------------------------------------------------------------------------
# Test 11: Timeout and Process Tree Termination
# ---------------------------------------------------------------------------
def test_security_scenario_11_timeout_kills_container(tmp_path):
    """Test 11: Exceeding command timeout triggers docker kill on the specific container."""
    backend = ContainerBackend(base_workspaces_dir=tmp_path, use_gvisor=False)
    backend.create_workspace("task-timeout-test")
    backend.write_file(
        "task-timeout-test",
        "sleep_long.py",
        "import time\ntime.sleep(100)\n",
    )

    killed_containers = []

    def mock_popen(cmd, **kwargs):
        mock_proc = MagicMock()
        mock_proc.wait.side_effect = subprocess.TimeoutExpired(cmd, timeout=1)
        mock_proc.stdout = MagicMock()
        mock_proc.stdout.read.return_value = b""
        mock_proc.stderr = MagicMock()
        mock_proc.stderr.read.return_value = b""
        return mock_proc

    def mock_run(cmd, **kwargs):
        if len(cmd) >= 3 and cmd[0] == "docker" and cmd[1] == "kill":
            killed_containers.append(cmd[2])
        return MagicMock(returncode=0)

    with patch("sandbox.container_backend.subprocess.Popen", side_effect=mock_popen):
        with patch("sandbox.container_backend.subprocess.run", side_effect=mock_run):
            res = backend.execute(
                task_id="task-timeout-test",
                command="python",
                arguments=["sleep_long.py"],
                timeout_seconds=1,
            )

    assert res.timed_out is True
    assert res.success is False
    assert len(killed_containers) == 1
    assert "sandbox-task-time" in killed_containers[0]


# ---------------------------------------------------------------------------
# Test 12: Runner Outage and Production Fail-Closed
# ---------------------------------------------------------------------------
def test_security_scenario_12_runner_outage_fails_closed_no_fallback(monkeypatch):
    """Test 12: In production, runner outage raises RunnerUnavailableError with NO host fallback."""
    monkeypatch.setattr("sandbox.factory.settings.app_env", "production")
    monkeypatch.setattr("sandbox.factory.settings.sandbox_backend", "runner")
    monkeypatch.setattr("sandbox.factory.settings.runner_base_url", "https://runner.prod.internal:8080")
    monkeypatch.setattr("sandbox.factory.settings.runner_auth_secret", "prod-secret-token-32-chars-long!")

    backend = SandboxFactory.get_backend()
    assert isinstance(backend, RunnerClient)

    # When runner is down, execute must raise RunnerUnavailableError, NEVER run subprocess locally
    with patch.object(backend._client, "post", side_effect=httpx.ConnectError("Service Unavailable")):
        with pytest.raises(RunnerUnavailableError) as exc_info:
            backend.execute(
                task_id="task-outage-test",
                command="pytest",
            )
        assert "is unreachable" in str(exc_info.value)
        assert "no uncontained fallback is permitted" in str(exc_info.value)


# ---------------------------------------------------------------------------
# Two-Phase Pipeline Verification
# ---------------------------------------------------------------------------
def test_two_phase_pipeline_execution(tmp_path):
    """Verify that TwoPhaseExecutionService coordinates Phase A install and Phase B offline testing."""
    ws = tmp_path / "workspaces" / "task-two-phase"
    ws.mkdir(parents=True)
    (ws / "requirements.txt").write_text("pytest>=8.0.0\n")

    backend = MagicMock(spec=SandboxBackend)
    backend.execute.return_value = MagicMock(success=True, model_dump=lambda: {"success": True})

    res = TwoPhaseExecutionService.run_two_phase_pipeline(
        task_id="task-two-phase",
        backend=backend,
        workspace_path=ws,
        test_command="pytest",
        test_arguments=["-q"],
        install_deps=True,
    )

    assert res["task_id"] == "task-two-phase"
    assert res["overall_success"] is True

    # Verify calls: Phase A had network_enabled=True, Phase B had network_enabled=False
    calls = backend.execute.call_args_list
    assert len(calls) == 2
    # Call 1 (pip install): network_enabled=True
    assert calls[0].kwargs["network_enabled"] is True
    # Call 2 (pytest offline): network_enabled=False
    assert calls[1].kwargs["network_enabled"] is False
