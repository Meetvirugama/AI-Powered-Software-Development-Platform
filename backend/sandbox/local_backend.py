"""Local Subprocess Sandbox Backend (Development Only).

Owner: AI Platform Security Architecture — Issue #200 / F20
Reference: Docs/security/sandbox/03-target-architecture.md

WARNING:
This backend executes commands as subprocesses on the host machine.
It is strictly permitted ONLY during local development (APP_ENV=development).
Execution in production (APP_ENV=production) is hard-blocked and fails closed.
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from app.core.config import PROJECT_ROOT, settings
from app.schemas.workspace import WorkspaceCommandResult

from sandbox.backend import SandboxBackend
from sandbox.command_runner import WorkspaceCommandRunner
from sandbox.constants import DEFAULT_WORKSPACE_SUBDIR
from sandbox.exceptions import (
    SandboxConfigurationError,
    SandboxSecurityError,
    WorkspaceError,
)
from sandbox.path_guard import WorkspacePathGuard
from sandbox.resource_monitor import WorkspaceResourceMonitor

logger = logging.getLogger(__name__)


class LocalSubprocessBackend(SandboxBackend):
    """Local development backend executing commands via WorkspaceCommandRunner."""

    def __init__(
        self,
        base_workspaces_dir: Path | None = None,
        command_runner: WorkspaceCommandRunner | None = None,
    ) -> None:
        self._enforce_environment_policy()
        self._base_dir = (
            base_workspaces_dir
            if base_workspaces_dir is not None
            else (PROJECT_ROOT / DEFAULT_WORKSPACE_SUBDIR).resolve()
        )
        self._command_runner = command_runner or WorkspaceCommandRunner()
        self._workspaces: dict[str, Path] = {}
        self._monitors: dict[str, WorkspaceResourceMonitor] = {}

    @property
    def backend_type(self) -> str:
        return "local"

    def _enforce_environment_policy(self) -> None:
        """Fail closed immediately if executed in a production environment."""
        app_env = getattr(settings, "app_env", "development").strip().lower()
        is_prod = getattr(settings, "is_production", False) or app_env in ("production", "prod")

        if is_prod:
            logger.critical(
                "security_violation_local_backend_in_production",
                extra={"app_env": app_env},
            )
            raise SandboxSecurityError(
                f"SECURITY POLICY VIOLATION: LocalSubprocessBackend is strictly forbidden "
                f"in production environments (APP_ENV='{app_env}'). "
                f"Untrusted repository code must execute inside ContainerBackend or RunnerClient."
            )

    def _resolve_task_root(self, task_id: str) -> Path:
        """Resolve and validate the workspace directory for a task."""
        self._enforce_environment_policy()
        clean_id = str(task_id).strip()
        if not clean_id or "/" in clean_id or "\\" in clean_id or ".." in clean_id:
            raise SandboxSecurityError(f"Invalid task_id format: '{task_id}'")

        if clean_id in self._workspaces:
            ws_path = self._workspaces[clean_id]
        else:
            ws_path = (self._base_dir / clean_id).resolve()
            self._workspaces[clean_id] = ws_path

        WorkspacePathGuard.validate_workspace_root(ws_path)
        return ws_path

    def create_workspace(
        self,
        task_id: str,
        base_repo_path: Path | None = None,
    ) -> Path:
        self._enforce_environment_policy()
        ws_path = self._resolve_task_root(task_id)
        ws_path.mkdir(parents=True, exist_ok=True)

        # Initialize resource monitor
        self._monitors[task_id] = WorkspaceResourceMonitor(workspace_root=ws_path)

        if base_repo_path and base_repo_path.exists():
            resolved_repo = base_repo_path.resolve()

            def _ignore_escaping_symlinks(src_dir: str, names: list[str]) -> set[str]:
                ignored: set[str] = set()
                for name in names:
                    p = Path(src_dir) / name
                    if p.is_symlink():
                        try:
                            target_res = p.resolve()
                            if not target_res.is_relative_to(resolved_repo):
                                logger.warning(
                                    "Skipping nested escaping symlink during workspace copy: %s -> %s",
                                    p,
                                    target_res,
                                )
                                ignored.add(name)
                        except Exception:
                            ignored.add(name)
                return ignored

            # Directory copy or worktree initialization (reject escaping symlinks)
            for item in base_repo_path.iterdir():
                if item.name == ".git":
                    continue
                if item.is_symlink():
                    try:
                        target_resolved = item.resolve()
                        if not target_resolved.is_relative_to(resolved_repo):
                            logger.warning(
                                "Skipping escaping symlink during workspace copy: %s -> %s",
                                item,
                                target_resolved,
                            )
                            continue
                    except Exception:
                        continue
                dest = ws_path / item.name
                if item.is_dir():
                    shutil.copytree(
                        item,
                        dest,
                        symlinks=True,
                        ignore=_ignore_escaping_symlinks,
                        dirs_exist_ok=True,
                    )
                else:
                    shutil.copy2(item, dest, follow_symlinks=False)

        return ws_path

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
        self._enforce_environment_policy()
        ws_path = self._resolve_task_root(task_id)
        exec_cwd = (cwd or ws_path).resolve()

        # Enforce that exec_cwd stays strictly inside the task workspace (prevent sibling-prefix bypass)
        WorkspacePathGuard.validate_workspace_root(ws_path)
        ws_resolved = ws_path.resolve()
        if exec_cwd != ws_resolved and not exec_cwd.is_relative_to(ws_resolved):
            raise SandboxSecurityError(
                f"Execution working directory '{exec_cwd}' escapes workspace root '{ws_path}'."
            )

        # Enforce resource monitoring disk check
        monitor = self._monitors.get(task_id)
        if monitor:
            monitor.check_disk_quota()

        res = self._command_runner.run_command(
            workspace_root=exec_cwd,
            command=command,
            arguments=arguments,
            timeout_seconds=timeout_seconds,
            custom_env=custom_env,
        )
        res.sandbox_status = "LOCAL_DEV_RUN"
        return res

    def read_file(self, task_id: str, relative_path: str) -> str:
        self._enforce_environment_policy()
        ws_path = self._resolve_task_root(task_id)
        safe_path = WorkspacePathGuard.resolve_within_workspace(ws_path, relative_path)
        if not safe_path.exists() or not safe_path.is_file():
            raise WorkspaceError(f"File not found: {relative_path}")
        return safe_path.read_text(encoding="utf-8", errors="replace")

    def write_file(self, task_id: str, relative_path: str, content: str) -> None:
        self._enforce_environment_policy()
        ws_path = self._resolve_task_root(task_id)
        safe_path = WorkspacePathGuard.resolve_within_workspace(ws_path, relative_path)

        monitor = self._monitors.get(task_id)
        encoded = content.encode("utf-8")
        if monitor:
            monitor.check_file_size(len(encoded), relative_path)
            monitor.check_disk_quota(len(encoded))
            monitor.record_file_modification(relative_path)

        safe_path.parent.mkdir(parents=True, exist_ok=True)
        safe_path.write_bytes(encoded)

    def get_diff(self, task_id: str) -> str:
        self._enforce_environment_policy()
        ws_path = self._resolve_task_root(task_id)
        if not (ws_path / ".git").exists() and not (ws_path / ".git").is_file():
            return ""

        try:
            proc = subprocess.run(
                ["git", "diff", "HEAD"],
                cwd=str(ws_path),
                capture_output=True,
                text=True,
                timeout=15,
                check=False,
            )
            return proc.stdout or ""
        except Exception as exc:
            logger.warning(f"Failed to extract diff: {exc}")
            return ""

    def destroy_workspace(self, task_id: str) -> None:
        self._enforce_environment_policy()
        clean_id = str(task_id).strip()
        self._monitors.pop(clean_id, None)

        if not clean_id or clean_id == ".":
            self._workspaces.pop(clean_id, None)
            return

        try:
            ws_path = self._resolve_task_root(clean_id)
        except SandboxSecurityError:
            self._workspaces.pop(clean_id, None)
            return

        self._workspaces.pop(clean_id, None)

        base_resolved = self._base_dir.resolve()
        ws_resolved = ws_path.resolve()
        if ws_resolved != base_resolved and ws_resolved.is_relative_to(base_resolved):
            if ws_resolved.exists() and ws_resolved.is_dir():
                try:
                    shutil.rmtree(ws_resolved, ignore_errors=True)
                except Exception as exc:
                    logger.warning(f"Error removing local workspace {ws_resolved}: {exc}")

    def get_status(self, task_id: str) -> dict[str, Any]:
        self._enforce_environment_policy()
        ws_path = self._resolve_task_root(task_id)
        exists = ws_path.exists() and ws_path.is_dir()
        return {
            "task_id": task_id,
            "backend": "local",
            "status": "READY" if exists else "NOT_FOUND",
            "workspace_path": str(ws_path) if exists else None,
            "environment": getattr(settings, "app_env", "development"),
        }

    def get_resource_usage(self, task_id: str) -> dict[str, Any]:
        self._enforce_environment_policy()
        monitor = self._monitors.get(task_id)
        disk_bytes = monitor.calculate_disk_usage() if monitor else 0
        return {
            "task_id": task_id,
            "disk_bytes": disk_bytes,
            "modified_files": monitor.modified_files_count if monitor else 0,
            "cpu_limit": "unbounded_host",
            "memory_limit": "unbounded_host",
        }
