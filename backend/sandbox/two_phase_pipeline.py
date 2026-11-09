"""Two-Phase Dependency Installation and Offline Test Execution Pipeline.

Owner: AI Platform Security Architecture — Issue #200 / F20
Reference: Docs/security/sandbox/06-dependency-installation.md
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from app.schemas.workspace import WorkspaceCommandResult

from sandbox.backend import SandboxBackend
from sandbox.exceptions import (
    WorkspaceCommandError,
    WorkspaceTestExecutionError,
)

logger = logging.getLogger(__name__)


class TwoPhaseExecutionService:
    """Orchestrates Phase A (controlled dependency installation) and Phase B (offline execution)."""

    PYTHON_MANIFESTS: tuple[str, ...] = (
        "requirements.txt",
        "requirements-dev.txt",
        "pyproject.toml",
        "setup.py",
        "Pipfile",
    )

    NODE_MANIFESTS: tuple[str, ...] = (
        "package.json",
        "package-lock.json",
    )

    @classmethod
    def detect_manifests(cls, workspace_path: Path) -> dict[str, Any]:
        """Detect presence of package manifests within the workspace directory."""
        if not workspace_path.exists() or not workspace_path.is_dir():
            return {
                "has_python": False,
                "python_manifests": [],
                "has_node": False,
                "node_manifests": [],
            }

        found_py: list[str] = [
            m for m in cls.PYTHON_MANIFESTS if (workspace_path / m).is_file()
        ]
        found_node: list[str] = [
            m for m in cls.NODE_MANIFESTS if (workspace_path / m).is_file()
        ]

        return {
            "has_python": len(found_py) > 0,
            "python_manifests": found_py,
            "has_node": len(found_node) > 0,
            "node_manifests": found_node,
        }

    @classmethod
    def install_dependencies(
        cls,
        task_id: str,
        backend: SandboxBackend,
        workspace_path: Path,
        timeout_seconds: int = 120,
    ) -> list[WorkspaceCommandResult]:
        """Phase A: Install dependencies inside the sandbox with controlled network access.

        Executes strictly within the sandbox container (never on the API host).
        """
        manifests = cls.detect_manifests(workspace_path)
        results: list[WorkspaceCommandResult] = []

        # Target directory for installed dependencies inside the task workspace:
        # In container/runner backends, the workspace is mounted at /workspace.
        # Installing to /workspace/.deps ensures packages persist across ephemeral containers
        # and are discoverable via PYTHONPATH in Phase B.
        deps_dir = (
            "/workspace/.deps"
            if getattr(backend, "backend_type", "") in ("container", "runner")
            else str((workspace_path / ".deps").resolve())
        )

        # 1. Python dependencies
        if manifests["has_python"]:
            if (workspace_path / "requirements.txt").is_file():
                logger.info(f"Phase A: Installing Python requirements for task '{task_id}' into {deps_dir}")
                res = backend.execute(
                    task_id=task_id,
                    command="python",
                    arguments=["-m", "pip", "install", "--target", deps_dir, "--no-cache-dir", "-r", "requirements.txt"],
                    timeout_seconds=timeout_seconds,
                    network_enabled=True,
                )
                res.sandbox_status = "PHASE_A_DEPENDENCY_INSTALL"
                results.append(res)
            elif (workspace_path / "pyproject.toml").is_file():
                logger.info(f"Phase A: Installing pyproject dependencies for task '{task_id}' into {deps_dir}")
                res = backend.execute(
                    task_id=task_id,
                    command="python",
                    arguments=["-m", "pip", "install", "--target", deps_dir, "--no-cache-dir", "."],
                    timeout_seconds=timeout_seconds,
                    network_enabled=True,
                )
                res.sandbox_status = "PHASE_A_DEPENDENCY_INSTALL"
                results.append(res)

        # 2. Node.js dependencies
        if manifests["has_node"]:
            logger.info(f"Phase A: Installing Node dependencies for task '{task_id}'")
            res = backend.execute(
                task_id=task_id,
                command="npm",
                arguments=["install", "--prefer-offline", "--no-audit", "--no-fund"],
                timeout_seconds=timeout_seconds,
                network_enabled=True,
            )
            res.sandbox_status = "PHASE_A_DEPENDENCY_INSTALL"
            results.append(res)

        return results

    @classmethod
    def execute_offline_tests(
        cls,
        task_id: str,
        backend: SandboxBackend,
        command: str = "pytest",
        arguments: Sequence[str] | None = None,
        timeout_seconds: int = 60,
    ) -> WorkspaceCommandResult:
        """Phase B: Execute test suite strictly without network egress (--network=none)."""
        logger.info(
            f"Phase B: Executing offline tests for task '{task_id}' with command '{command}'"
        )
        res = backend.execute(
            task_id=task_id,
            command=command,
            arguments=arguments,
            timeout_seconds=timeout_seconds,
            network_enabled=False,  # Enforces --network=none in container
        )
        res.sandbox_status = "PHASE_B_OFFLINE_EXECUTION"
        return res

    @classmethod
    def run_two_phase_pipeline(
        cls,
        task_id: str,
        backend: SandboxBackend,
        workspace_path: Path,
        test_command: str = "pytest",
        test_arguments: Sequence[str] | None = None,
        install_deps: bool = True,
        install_timeout: int = 120,
        test_timeout: int = 60,
    ) -> dict[str, Any]:
        """Coordinate full two-phase workflow: Phase A install -> Phase B offline test."""
        install_results: list[WorkspaceCommandResult] = []
        if install_deps:
            install_results = cls.install_dependencies(
                task_id=task_id,
                backend=backend,
                workspace_path=workspace_path,
                timeout_seconds=install_timeout,
            )

        # Check if any install step failed critically
        install_failed = any(not r.success for r in install_results)
        if install_failed:
            logger.warning(f"Phase A dependency installation encountered errors for task '{task_id}'")

        # Phase B: Offline execution
        test_result = cls.execute_offline_tests(
            task_id=task_id,
            backend=backend,
            command=test_command,
            arguments=test_arguments,
            timeout_seconds=test_timeout,
        )

        return {
            "task_id": task_id,
            "phase_a_install_results": [r.model_dump() for r in install_results],
            "phase_a_success": not install_failed,
            "phase_b_test_result": test_result.model_dump(),
            "overall_success": test_result.success,
        }
