"""Abstract Sandbox Backend Interface for Isolated Untrusted Execution.

Owner: AI Platform Security Architecture — Issue #200 / F20
Reference: Docs/security/sandbox/03-target-architecture.md
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from app.schemas.workspace import WorkspaceCommandResult


class SandboxBackend(ABC):
    """Abstract interface defining the execution boundary for untrusted code."""

    @property
    @abstractmethod
    def backend_type(self) -> str:
        """Return the string identifier for this backend implementation."""

    @abstractmethod
    def create_workspace(
        self,
        task_id: str,
        base_repo_path: Path | None = None,
    ) -> Path:
        """Provision and initialize an isolated workspace directory.

        Args:
            task_id: Unique identifier for the task.
            base_repo_path: Optional path to local git repository base to branch/clone from.

        Returns:
            Resolved Path to the provisioned workspace directory.
        """

    @abstractmethod
    def execute(
        self,
        task_id: str,
        command: str,
        arguments: Sequence[str] | None = None,
        cwd: Path | None = None,
        timeout_seconds: int | None = None,
        custom_env: Mapping[str, str] | None = None,
        network_enabled: bool = False,
    ) -> WorkspaceCommandResult:
        """Execute an allowlisted command inside the isolated sandbox.

        Args:
            task_id: Unique identifier for the task sandbox.
            command: Command executable name.
            arguments: Command arguments.
            cwd: Working directory relative to or within the workspace.
            timeout_seconds: Timeout budget in seconds.
            custom_env: Optional environment variables.
            network_enabled: Whether external network egress is enabled (Phase A dependency install)
                             or disabled (Phase B offline testing).

        Returns:
            Structured WorkspaceCommandResult with exit code, outputs, and telemetry.
        """

    @abstractmethod
    def read_file(self, task_id: str, relative_path: str) -> str:
        """Read file contents safely from within the workspace sandbox."""

    @abstractmethod
    def write_file(self, task_id: str, relative_path: str, content: str) -> None:
        """Write file contents safely into the workspace sandbox."""

    @abstractmethod
    def get_diff(self, task_id: str) -> str:
        """Extract unified git diff from the workspace sandbox."""

    @abstractmethod
    def destroy_workspace(self, task_id: str) -> None:
        """Decommission the sandbox, terminating processes/containers and pruning disk resources."""

    @abstractmethod
    def get_status(self, task_id: str) -> dict[str, Any]:
        """Query sandbox status, state, and container health."""

    @abstractmethod
    def get_resource_usage(self, task_id: str) -> dict[str, Any]:
        """Retrieve CPU, RAM, disk, and process telemetry for the sandbox."""
