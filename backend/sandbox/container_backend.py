"""Production Container Sandbox Backend with Docker and gVisor Isolation.

Owner: AI Platform Security Architecture — Issue #200 / F20
Reference: Docs/security/sandbox/03-target-architecture.md, 05-container-isolation.md
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess
import threading
import time
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from app.core.config import PROJECT_ROOT, settings
from app.core.secret_redaction import redact
from app.schemas.workspace import WorkspaceCommandResult

from sandbox.backend import SandboxBackend
from sandbox.command_runner import WorkspaceCommandRunner
from sandbox.constants import (
    DEFAULT_WORKSPACE_SUBDIR,
    MAX_COMMAND_OUTPUT_BYTES,
    MAX_TIMEOUT_SECONDS,
)
from sandbox.exceptions import (
    SandboxConfigurationError,
    SandboxResourceLimitError,
    SandboxSecurityError,
    WorkspaceCommandError,
    WorkspaceError,
)
from sandbox.path_guard import WorkspacePathGuard
from sandbox.resource_monitor import WorkspaceResourceMonitor

logger = logging.getLogger(__name__)


class ContainerBackend(SandboxBackend):
    """Secure production backend executing untrusted workloads inside isolated containers."""

    def __init__(
        self,
        base_workspaces_dir: Path | None = None,
        default_image: str | None = None,
        use_gvisor: bool | None = None,
    ) -> None:
        self._base_dir = (
            base_workspaces_dir
            if base_workspaces_dir is not None
            else (PROJECT_ROOT / DEFAULT_WORKSPACE_SUBDIR).resolve()
        )
        self._default_image = default_image or getattr(settings, "sandbox_python_image", "python:3.12-slim")
        self._use_gvisor = (
            use_gvisor if use_gvisor is not None else getattr(settings, "sandbox_use_gvisor", True)
        )
        self._workspaces: dict[str, Path] = {}
        self._monitors: dict[str, WorkspaceResourceMonitor] = {}
        self._active_containers: dict[str, str] = {}
        self._command_runner = WorkspaceCommandRunner()
        self._gvisor_verified: bool = self._verify_gvisor_runtime()

    @property
    def backend_type(self) -> str:
        return "container"

    @property
    def gvisor_available(self) -> bool:
        """Indicate whether the gVisor runsc runtime is verified on the host."""
        return self._gvisor_verified

    def _verify_gvisor_runtime(self) -> bool:
        """Inspect docker daemon runtimes to verify if runsc is available."""
        if not self._use_gvisor:
            return False
        try:
            proc = subprocess.run(
                ["docker", "info", "--format", "{{json .Runtimes}}"],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
            if proc.returncode == 0 and "runsc" in (proc.stdout or ""):
                return True
        except Exception:
            pass
        return shutil.which("runsc") is not None

    def _resolve_task_root(self, task_id: str) -> Path:
        """Resolve and validate the workspace directory on the host."""
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
        ws_path = self._resolve_task_root(task_id)
        ws_path.mkdir(parents=True, exist_ok=True)

        self._monitors[task_id] = WorkspaceResourceMonitor(workspace_root=ws_path)

        if base_repo_path and base_repo_path.exists():
            resolved_repo = base_repo_path.resolve()
            for item in base_repo_path.iterdir():
                if item.name == ".git":
                    continue
                if item.is_symlink():
                    try:
                        target_resolved = item.resolve()
                        if not target_resolved.is_relative_to(resolved_repo):
                            logger.warning(
                                "Skipping escaping symlink during container workspace copy: %s -> %s",
                                item,
                                target_resolved,
                            )
                            continue
                    except Exception:
                        continue
                dest = ws_path / item.name
                if item.is_dir():
                    shutil.copytree(item, dest, symlinks=True, dirs_exist_ok=True)
                else:
                    shutil.copy2(item, dest, follow_symlinks=False)

        return ws_path

    def _resolve_image_for_command(self, command: str) -> str:
        """Select pinned container image according to command type."""
        cmd_lower = command.lower()
        if cmd_lower in ("npm", "npx", "node", "jest", "eslint", "biome"):
            return getattr(settings, "sandbox_node_image", "node:20-slim")
        return self._default_image

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
        start_time = time.perf_counter()
        args = list(arguments or [])
        clean_id = str(task_id).strip()

        # Validate command and arguments via policy
        self._command_runner.validate_command(command, args)

        # Ensure task workspace is registered to cwd if supplied from WorkspaceManager
        if cwd is not None and clean_id not in self._workspaces:
            resolved_cwd = Path(cwd).resolve()
            if resolved_cwd.is_dir() and (resolved_cwd.name == clean_id or resolved_cwd.is_relative_to(self._base_dir)):
                self._workspaces[clean_id] = resolved_cwd if resolved_cwd.name == clean_id else (self._base_dir / clean_id).resolve()

        ws_path = self._resolve_task_root(task_id)
        if not ws_path.exists() or not ws_path.is_dir():
            raise WorkspaceCommandError(f"Workspace directory not found: {ws_path}")

        # Check resource limits before execution
        monitor = self._monitors.get(task_id)
        if monitor:
            monitor.check_disk_quota()

        timeout = min(
            timeout_seconds or getattr(settings, "sandbox_default_timeout", 30),
            MAX_TIMEOUT_SECONDS,
        )

        image = self._resolve_image_for_command(command)
        container_name = f"sandbox-{task_id[:16]}-{int(time.time() * 1000) % 1000000}"
        self._active_containers[task_id] = container_name

        # Resolve container working directory relative to mounted /workspace
        container_workdir = "/workspace"
        if cwd is not None:
            resolved_cwd = Path(cwd).resolve()
            ws_resolved = ws_path.resolve()
            if resolved_cwd == ws_resolved or resolved_cwd.name == clean_id:
                container_workdir = "/workspace"
            elif resolved_cwd.is_relative_to(ws_resolved):
                rel = resolved_cwd.relative_to(ws_resolved)
                container_workdir = f"/workspace/{rel.as_posix()}" if str(rel) != "." else "/workspace"
            else:
                raise SandboxSecurityError(
                    f"Execution working directory '{resolved_cwd}' escapes workspace root '{ws_resolved}'."
                )

        # Construct Docker CLI command with full security profile
        docker_cmd: list[str] = [
            "docker",
            "run",
            "--name",
            container_name,
            "--rm",
            # Resource bounds (cgroups v2)
            f"--cpus={getattr(settings, 'sandbox_cpu_limit', 2.0)}",
            f"--memory={getattr(settings, 'sandbox_memory_limit', '4g')}",
            f"--pids-limit={getattr(settings, 'sandbox_pid_limit', 512)}",
            # Filesystem isolation
            "--read-only",
            "--tmpfs",
            "/tmp:rw,noexec,nosuid,size=512m",
            "-v",
            f"{ws_path}:/workspace:rw",
            "-w",
            container_workdir,
            # Security boundaries
            "--cap-drop=ALL",
            "--security-opt=no-new-privileges",
        ]

        # Non-root user if not disabled
        # Use UID 10001 (standard unprivileged sandbox UID) or default
        user_id = os.getuid() if hasattr(os, "getuid") and os.getuid() != 0 else 10001
        docker_cmd.extend(["--user", f"{user_id}:{user_id}"])

        # Network isolation: Phase B offline test execution uses --network=none
        if not network_enabled:
            docker_cmd.append("--network=none")

        # gVisor userspace kernel isolation
        if self._gvisor_verified:
            docker_cmd.append("--runtime=runsc")

        # Container environment isolation:
        # Do not forward host-specific values (PATH, HOME, TEMP, etc.) into the container.
        # Ensure writable container-local paths for HOME, TMPDIR, and package caches.
        container_env: dict[str, str] = {
            "HOME": "/tmp",
            "TMPDIR": "/tmp",
            "PYTHONUNBUFFERED": "1",
            "PIP_CACHE_DIR": "/tmp/.cache/pip",
            "PYTHONPATH": "/workspace/.deps:/workspace",
        }

        # Offline guards: only enforce for Phase B (network_enabled=False).
        # Phase A dependency installation (network_enabled=True) must NOT receive offline guards.
        if not network_enabled:
            container_env["PIP_NO_INDEX"] = "1"
            container_env["PIP_DISABLE_PIP_VERSION_CHECK"] = "1"
            container_env["NPM_CONFIG_OFFLINE"] = "true"

        # Safe custom environment overrides (preventing host path leaks and sensitive credential overrides)
        if custom_env:
            blocked_env_keys = {
                "PATH",
                "HOME",
                "TEMP",
                "TMP",
                "RUNNER_AUTH_SECRET",
                "DATABASE_URL",
                "REDIS_URL",
                "SECRET_KEY",
                "JWT_SECRET",
                "OPENAI_API_KEY",
                "ANTHROPIC_API_KEY",
                "GEMINI_API_KEY",
                "GEMINI_API_KEYS",
                "GROQ_API_KEY",
                "GROQ_API_KEYS",
                "GITHUB_TOKEN",
                "GITHUB_PRIVATE_KEY",
                "GITHUB_APP_PRIVATE_KEY",
                "GITHUB_WEBHOOK_SECRET",
                "GITHUB_CLIENT_SECRET",
                "LD_PRELOAD",
                "LD_LIBRARY_PATH",
                "DYLD_INSERT_LIBRARIES",
                "PYTHONINSPECT",
                "PYTHONSTARTUP",
            }
            for k, v in custom_env.items():
                k_upper = k.upper()
                if (
                    k_upper in blocked_env_keys
                    or k_upper.startswith("AWS_")
                    or k_upper.startswith("AZURE_")
                    or k_upper.startswith("GCP_")
                    or k_upper.startswith("GOOGLE_")
                ):
                    continue
                if k_upper == "PYTHONPATH":
                    container_env["PYTHONPATH"] = f"/workspace/.deps:/workspace:{v}"
                else:
                    container_env[k] = str(v)

        for k in sorted(container_env.keys()):
            docker_cmd.extend(["-e", f"{k}={container_env[k]}"])

        # Image and command entrypoint
        docker_cmd.append(image)

        if command in ("python", "python3"):
            docker_cmd.extend(["python", *args])
        elif command == "pytest":
            docker_cmd.extend(["python", "-m", "pytest", *args])
        else:
            docker_cmd.extend([command, *args])

        # Execution with process tracking and timeout
        timed_out = False
        duration_ms = 0.0
        try:
            proc = subprocess.Popen(
                docker_cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=False,
            )

            stdout_data = bytearray()
            stderr_data = bytearray()
            max_bytes = getattr(settings, "sandbox_output_limit_bytes", MAX_COMMAND_OUTPUT_BYTES)

            def drain_pipe(pipe: Any, target: bytearray) -> None:
                try:
                    while True:
                        chunk = pipe.read(4096)
                        if not chunk:
                            break
                        if len(target) < max_bytes:
                            target.extend(chunk[: max_bytes - len(target)])
                except Exception:
                    pass
                finally:
                    try:
                        pipe.close()
                    except Exception:
                        pass

            t_out = threading.Thread(target=drain_pipe, args=(proc.stdout, stdout_data), daemon=True)
            t_err = threading.Thread(target=drain_pipe, args=(proc.stderr, stderr_data), daemon=True)
            t_out.start()
            t_err.start()

            try:
                proc.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                timed_out = True
                # Kill container immediately
                subprocess.run(["docker", "kill", container_name], capture_output=True, check=False)
                try:
                    proc.kill()
                    proc.wait(timeout=2.0)
                except Exception:
                    pass

            t_out.join(timeout=1.0)
            t_err.join(timeout=1.0)

            duration_ms = (time.perf_counter() - start_time) * 1000.0

            raw_stdout = bytes(stdout_data).decode("utf-8", errors="replace")
            raw_stderr = bytes(stderr_data).decode("utf-8", errors="replace")

            if len(stdout_data) >= max_bytes:
                raw_stdout += "\n... [TRUNCATED: output exceeded size limit]"
            if len(stderr_data) >= max_bytes:
                raw_stderr += "\n... [TRUNCATED: error output exceeded size limit]"

            stdout_clean = redact(raw_stdout)
            stderr_clean = redact(raw_stderr)
            exit_code = -1 if timed_out else (proc.returncode or 0)

            status_label = "CONTAINER_GVISOR" if self._gvisor_verified else "CONTAINER_DOCKER"
            if timed_out:
                status_label += "_TIMED_OUT"

            return WorkspaceCommandResult(
                success=exit_code == 0 and not timed_out,
                command=command,
                exit_code=exit_code,
                stdout=stdout_clean,
                stderr=stderr_clean,
                duration_ms=duration_ms,
                timed_out=timed_out,
                error="Execution timed out" if timed_out else None,
                sandbox_status=status_label,
                resource_metrics={
                    "duration_ms": duration_ms,
                    "timed_out": timed_out,
                    "image": image,
                    "network_isolated": not network_enabled,
                    "runtime": "runsc" if self._gvisor_verified else "runc",
                },
            )

        except Exception as exc:
            # Cleanup container on failure
            subprocess.run(["docker", "rm", "-f", container_name], capture_output=True, check=False)
            duration_ms = (time.perf_counter() - start_time) * 1000.0
            logger.error("container_execution_error", extra={"task_id": task_id, "error": str(exc)})
            return WorkspaceCommandResult(
                success=False,
                command=command,
                exit_code=-1,
                stdout="",
                stderr=redact(str(exc)),
                duration_ms=duration_ms,
                timed_out=False,
                error=redact(f"Container execution error: {exc}"),
                sandbox_status="CONTAINER_ERROR",
            )
        finally:
            self._active_containers.pop(task_id, None)

    def read_file(self, task_id: str, relative_path: str) -> str:
        ws_path = self._resolve_task_root(task_id)
        safe_path = WorkspacePathGuard.resolve_within_workspace(ws_path, relative_path)
        if not safe_path.exists() or not safe_path.is_file():
            raise WorkspaceError(f"File not found: {relative_path}")
        return safe_path.read_text(encoding="utf-8", errors="replace")

    def write_file(self, task_id: str, relative_path: str, content: str) -> None:
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
            logger.warning(f"Failed to get diff for task {task_id}: {exc}")
            return ""

    def destroy_workspace(self, task_id: str) -> None:
        clean_id = str(task_id).strip()
        # Kill any active container for this task
        container_name = self._active_containers.pop(clean_id, None)
        if container_name:
            subprocess.run(["docker", "rm", "-f", container_name], capture_output=True, check=False)

        self._monitors.pop(clean_id, None)

        # Reject empty, ".", or invalid task IDs
        if not clean_id or clean_id == ".":
            self._workspaces.pop(clean_id, None)
            return

        try:
            ws_path = self._resolve_task_root(clean_id)
        except SandboxSecurityError:
            self._workspaces.pop(clean_id, None)
            return

        self._workspaces.pop(clean_id, None)

        # Containment check: verify path is strictly inside self._base_dir and NOT self._base_dir itself
        base_resolved = self._base_dir.resolve()
        ws_resolved = ws_path.resolve()
        if ws_resolved != base_resolved and ws_resolved.is_relative_to(base_resolved):
            if ws_resolved.exists() and ws_resolved.is_dir():
                shutil.rmtree(ws_resolved, ignore_errors=True)

    def get_status(self, task_id: str) -> dict[str, Any]:
        ws_path = self._resolve_task_root(task_id)
        active_container = self._active_containers.get(task_id)
        exists = ws_path.exists() and ws_path.is_dir()
        return {
            "task_id": task_id,
            "backend": "container",
            "status": "RUNNING" if active_container else ("READY" if exists else "NOT_FOUND"),
            "active_container": active_container,
            "workspace_path": str(ws_path) if exists else None,
            "gvisor_verified": self._gvisor_verified,
        }

    def get_resource_usage(self, task_id: str) -> dict[str, Any]:
        monitor = self._monitors.get(task_id)
        disk_bytes = monitor.calculate_disk_usage() if monitor else 0
        return {
            "task_id": task_id,
            "disk_bytes": disk_bytes,
            "modified_files": monitor.modified_files_count if monitor else 0,
            "cpu_limit": getattr(settings, "sandbox_cpu_limit", 2.0),
            "memory_limit": getattr(settings, "sandbox_memory_limit", "4g"),
            "pid_limit": getattr(settings, "sandbox_pid_limit", 512),
        }
