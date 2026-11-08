"""Unit Tests for SandboxBackend, Factory, and Fail-Closed Security Policies.

Owner: AI Platform Security Architecture — Issue #200 / F20
"""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import httpx
import pytest

from app.core.config import Settings
from sandbox.backend import SandboxBackend
from sandbox.container_backend import ContainerBackend
from sandbox.exceptions import (
    RunnerAuthenticationError,
    RunnerUnavailableError,
    SandboxConfigurationError,
    SandboxSecurityError,
)
from sandbox.factory import SandboxFactory
from sandbox.local_backend import LocalSubprocessBackend
from sandbox.runner_client import RunnerClient


def test_sandbox_factory_local_in_dev(monkeypatch):
    """Verify that LocalSubprocessBackend is provisioned when in development."""
    monkeypatch.setattr("sandbox.factory.settings.app_env", "development")

    backend = SandboxFactory.get_backend("local")
    assert isinstance(backend, LocalSubprocessBackend)
    assert backend.backend_type == "local"


def test_sandbox_factory_rejects_local_in_production(monkeypatch):
    """Verify that requesting LocalSubprocessBackend in production hard-fails closed."""
    monkeypatch.setattr("sandbox.factory.settings.app_env", "production")

    with pytest.raises(SandboxSecurityError) as exc_info:
        SandboxFactory.get_backend("local")

    assert "LocalSubprocessBackend is strictly forbidden in production" in str(exc_info.value)


def test_sandbox_factory_rejects_unknown_backend(monkeypatch):
    """Verify that unrecognized backend names fail closed."""
    monkeypatch.setattr("sandbox.factory.settings.app_env", "development")

    with pytest.raises(SandboxConfigurationError) as exc_info:
        SandboxFactory.get_backend("unsupported_backend_xyz")

    assert "Unsupported or invalid sandbox backend type" in str(exc_info.value)


def test_local_backend_direct_instantiation_fails_in_production(monkeypatch):
    """Verify LocalSubprocessBackend constructor directly refuses production."""
    monkeypatch.setattr("sandbox.local_backend.settings.app_env", "production")

    with pytest.raises(SandboxSecurityError) as exc_info:
        LocalSubprocessBackend()

    assert "LocalSubprocessBackend is strictly forbidden in production" in str(exc_info.value)


def test_local_backend_workspace_operations(tmp_path, monkeypatch):
    """Verify basic workspace read, write, and execute in local development."""
    monkeypatch.setattr("sandbox.local_backend.settings.app_env", "development")

    backend = LocalSubprocessBackend(base_workspaces_dir=tmp_path)
    ws_path = backend.create_workspace("task-dev-1")
    assert ws_path.exists()

    # Write and read a file
    backend.write_file("task-dev-1", "hello.txt", "Hello Sandbox")
    assert backend.read_file("task-dev-1", "hello.txt") == "Hello Sandbox"

    # Status & usage
    status = backend.get_status("task-dev-1")
    assert status["status"] == "READY"
    assert status["backend"] == "local"

    # Cleanup
    backend.destroy_workspace("task-dev-1")
    assert not ws_path.exists()


def test_runner_client_mutual_auth_and_unavailable(monkeypatch):
    """Verify RunnerClient sets bearer token headers and fails closed on network outage."""
    client = RunnerClient(
        base_url="http://runner.internal:8080",
        auth_secret="super-secret-token-12345",
    )
    assert client.backend_type == "runner"
    assert client._client.headers.get("X-Runner-Token") == "super-secret-token-12345"
    assert client._client.headers.get("Authorization") == "Bearer super-secret-token-12345"

    # Mock connection failure: must raise RunnerUnavailableError, NEVER fallback to host subprocess
    with patch.object(client._client, "post", side_effect=httpx.ConnectError("Connection refused")):
        with pytest.raises(RunnerUnavailableError) as exc_info:
            client.create_workspace("task-999")
        assert "is unreachable" in str(exc_info.value)
        assert "no uncontained fallback is permitted" in str(exc_info.value)


def test_container_backend_builds_hardened_docker_command(tmp_path, monkeypatch):
    """Verify ContainerBackend constructs Docker CLI call with all required security flags."""
    monkeypatch.setattr("sandbox.container_backend.settings.sandbox_cpu_limit", 2.0)
    monkeypatch.setattr("sandbox.container_backend.settings.sandbox_memory_limit", "4g")
    monkeypatch.setattr("sandbox.container_backend.settings.sandbox_pid_limit", 512)
    monkeypatch.setattr("sandbox.container_backend.settings.sandbox_use_gvisor", False)

    backend = ContainerBackend(base_workspaces_dir=tmp_path, use_gvisor=False)
    backend.create_workspace("task-docker-1")

    captured_cmds = []

    def mock_popen(cmd, **kwargs):
        captured_cmds.append(cmd)
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stdout = MagicMock()
        mock_proc.stdout.read.side_effect = [b"test passed\n", b""]
        mock_proc.stderr = MagicMock()
        mock_proc.stderr.read.side_effect = [b""]
        mock_proc.wait.return_value = 0
        return mock_proc

    with patch("sandbox.container_backend.subprocess.Popen", side_effect=mock_popen):
        res = backend.execute(
            task_id="task-docker-1",
            command="pytest",
            arguments=["-v"],
            network_enabled=False,
        )
        assert res.success is True
        assert "test passed" in res.stdout

    assert len(captured_cmds) == 1
    cmd = captured_cmds[0]

    # Verify all strict isolation flags
    assert "--network=none" in cmd
    assert "--read-only" in cmd
    assert "--cap-drop=ALL" in cmd
    assert "--security-opt=no-new-privileges" in cmd
    assert "--cpus=2.0" in cmd
    assert "--memory=4g" in cmd
    assert "--pids-limit=512" in cmd
    assert any("/tmp:rw,noexec,nosuid" in c for c in cmd)
    assert any(":/workspace:rw" in c for c in cmd)
