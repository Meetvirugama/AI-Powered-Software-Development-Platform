"""Restricted Subprocess Command Runner for Isolated Workspaces.

Owner: Prit Zania — Week 3 Day 3 Deliverable (Docs/week3.md §6 F33, F34, F35, §8 Day 3)
Reference: Docs/week3.md §6 (F33 Workspace, F34 Tool Policy, F35 Test Runner)

Key Capabilities:
1. Enforces an explicit allowlist of permitted commands (ALLOWED_COMMAND_TEMPLATES).
2. Rejects shell injection vectors (pipes, logical operators, metacharacters, null bytes).
3. Executes strictly within the target workspace directory root (cwd=workspace_path).
4. Sanitizes execution environment variables, stripping all host secrets and credentials.
5. Enforces hard timeout budgets (capped at MAX_TIMEOUT_SECONDS) and bounds output capture.
6. Redacts sensitive data from captured stdout and stderr.
"""

from __future__ import annotations

import logging
import os
import signal
import subprocess
import sys
import threading
import time
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from app.core.secret_redaction import redact
from app.schemas.workspace import WorkspaceCommandResult

from sandbox.constants import (
    ALLOWED_COMMAND_TEMPLATES,
    DEFAULT_COMMAND_TIMEOUT_SECONDS,
    DISALLOWED_COMMAND_TOKENS,
    MAX_COMMAND_OUTPUT_BYTES,
    MAX_TIMEOUT_SECONDS,
)
from sandbox.exceptions import (
    WorkspaceCommandError,
    WorkspacePolicyViolationError,
)

logger = logging.getLogger(__name__)


def kill_process_tree(pid: int, sig: int = signal.SIGKILL) -> None:
    """Terminate a process and all its child processes in its process group.

    Guarantees that when a subprocess times out, all background jobs,
    daemons, and descendant processes belonging to its process group are
    killed immediately, leaving zero orphaned processes.

    Handles ProcessLookupError and OSError gracefully if the process or
    process group leader has already exited.
    """
    if not pid or pid <= 0:
        return

    if sys.platform == "win32":
        try:
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(pid)],
                capture_output=True,
                check=False,
                timeout=5,
            )
        except Exception:
            pass
        return

    # POSIX systems (Linux / macOS):
    # Attempt to resolve the process group id
    try:
        pgid = os.getpgid(pid)
    except (ProcessLookupError, OSError):
        # If leader process has already exited, pgid is still the original pid
        pgid = pid

    # Kill entire process group
    try:
        os.killpg(pgid, sig)
    except (ProcessLookupError, OSError):
        pass

    # Ensure direct process is killed as fallback
    try:
        os.kill(pid, sig)
    except (ProcessLookupError, OSError):
        pass


def _drain_and_capture_stream(
    pipe: Any,
    max_bytes: int,
    result_holder: dict[str, Any],
) -> None:
    """Concurrently drain a subprocess pipe, bounding captured bytes to max_bytes.

    Prevents pipe deadlocks while strictly avoiding unbounded host disk or RAM
    consumption. Once max_bytes is reached, further incoming bytes are drained
    with mild throttling to allow runaway subprocesses to block on pipe buffers.
    """
    buffer = bytearray()
    truncated = False
    try:
        while True:
            chunk = pipe.read(65536 if truncated else 4096)
            if not chunk:
                break
            if len(buffer) < max_bytes:
                available = max_bytes - len(buffer)
                buffer.extend(chunk[:available])
                if len(chunk) > available:
                    truncated = True
            else:
                truncated = True
    except Exception:
        pass
    finally:
        try:
            pipe.close()
        except Exception:
            pass
    result_holder["data"] = bytes(buffer)
    result_holder["truncated"] = truncated


class WorkspaceCommandRunner:
    """Safely executes allowlisted commands inside an isolated task workspace."""

    def __init__(
        self,
        allowed_commands: Sequence[str] | None = None,
        disallowed_tokens: Sequence[str] | None = None,
        max_output_bytes: int = MAX_COMMAND_OUTPUT_BYTES,
        default_timeout_seconds: int = DEFAULT_COMMAND_TIMEOUT_SECONDS,
    ) -> None:
        self._allowed_commands = frozenset(
            cmd.lower() for cmd in (allowed_commands or ALLOWED_COMMAND_TEMPLATES)
        )
        self._disallowed_tokens = tuple(disallowed_tokens or DISALLOWED_COMMAND_TOKENS)
        self._max_output_bytes = max_output_bytes
        self._default_timeout_seconds = default_timeout_seconds

    def validate_command(self, command: str, arguments: Sequence[str] | None = None) -> None:
        """Validate command executable and arguments against security policies.

        Raises:
            WorkspacePolicyViolationError: If command is not allowlisted or contains unsafe tokens.
        """
        raw_cmd = (command or "").strip()
        if not raw_cmd:
            raise WorkspacePolicyViolationError("Command executable name cannot be empty.")

        # Check for null bytes or control characters
        if "\x00" in raw_cmd:
            raise WorkspacePolicyViolationError("Command executable cannot contain null bytes.")

        # Check for path separators (bare executable name only)
        if "/" in raw_cmd or "\\" in raw_cmd:
            raise WorkspacePolicyViolationError("Command must be a bare executable name, not a path.")

        # Extract base executable name (strip any leading path or extension)
        base_exec = Path(raw_cmd).stem.lower()
        if base_exec not in self._allowed_commands and raw_cmd.lower() not in self._allowed_commands:
            raise WorkspacePolicyViolationError(
                f"Command '{raw_cmd}' is not in the allowlist of permitted commands. "
                f"Permitted: {sorted(self._allowed_commands)}"
            )

        # Check disallowed shell tokens in command
        for token in self._disallowed_tokens:
            if token in raw_cmd:
                raise WorkspacePolicyViolationError(
                    f"Command contains forbidden shell metacharacter or operator: '{token}'"
                )

        # Check arguments for disallowed tokens
        if arguments:
            for arg in arguments:
                arg_str = str(arg)
                if "\x00" in arg_str:
                    raise WorkspacePolicyViolationError("Argument contains null byte.")
                for token in self._disallowed_tokens:
                    if token in arg_str:
                        raise WorkspacePolicyViolationError(
                            f"Argument '{arg_str}' contains forbidden shell operator or token: '{token}'"
                        )

    def sanitize_environment(
        self,
        custom_env: Mapping[str, str] | None = None,
    ) -> dict[str, str]:
        """Produce a clean environment dictionary stripped of host credentials and sensitive keys."""
        env: dict[str, str] = {}

        # Preserve only standard non-sensitive system variables (never host PYTHONPATH - B3)
        safe_keys = {
            "PATH",
            "SYSTEMROOT",
            "SYSTEMDRIVE",
            "WINDIR",
            "TEMP",
            "TMP",
            "APPDATA",
            "LOCALAPPDATA",
            "HOME",
            "USERPROFILE",
            "HOMEPATH",
            "HOMEDRIVE",
            "LANG",
            "LC_ALL",
            "PYTHONUNBUFFERED",
            "NODE_ENV",
            "COMSPEC",
            "PATHEXT",
        }

        for k, v in os.environ.items():
            if k.upper() in safe_keys:
                env[k] = v

        # Enforce offline package/network environment guards inside workspace runner (B3)
        env["PIP_NO_INDEX"] = "1"
        env["PIP_DISABLE_PIP_VERSION_CHECK"] = "1"
        env["NPM_CONFIG_OFFLINE"] = "true"
        env["NO_PROXY"] = "*"
        env["no_proxy"] = "*"

        # Add / override custom env vars (sanitizing values against safe overridable keys)
        if custom_env:
            overridable = {"NODE_ENV", "LANG", "LC_ALL", "PYTHONUNBUFFERED"}
            for ck, cv in custom_env.items():
                if ck.upper() in overridable:
                    env[ck] = str(cv)

        return env

    def run_command(
        self,
        workspace_root: Path,
        command: str,
        arguments: Sequence[str] | None = None,
        timeout_seconds: int | None = None,
        custom_env: Mapping[str, str] | None = None,
    ) -> WorkspaceCommandResult:
        """Execute an allowlisted command strictly inside the workspace sandbox."""
        start_time = time.perf_counter()
        args = list(arguments or [])

        # Validate command and arguments
        self.validate_command(command, args)

        if not workspace_root.exists() or not workspace_root.is_dir():
            raise WorkspaceCommandError(
                f"Workspace root directory does not exist or is not a directory: {workspace_root}"
            )

        timeout = min(
            timeout_seconds or self._default_timeout_seconds,
            MAX_TIMEOUT_SECONDS,
        )

        env = self.sanitize_environment(custom_env)
        ws_str = str(workspace_root.resolve())
        env["PYTHONPATH"] = f"{ws_str}{os.pathsep}."
        venv_bin = str(Path(sys.executable).parent)
        curr_path = env.get("PATH", "")
        if venv_bin and venv_bin not in curr_path.split(os.pathsep):
            env["PATH"] = f"{venv_bin}{os.pathsep}{curr_path}" if curr_path else venv_bin

        exec_cmd = command
        if command in ("python", "python3"):
            exec_cmd = sys.executable

        cmd_list = [exec_cmd, *args]
        if command == "pytest":
            cmd_list = [sys.executable, "-m", "pytest", *args]

        try:
            popen_kwargs: dict[str, Any] = {
                "cwd": str(workspace_root.resolve()),
                "env": env,
                "stdout": subprocess.PIPE,
                "stderr": subprocess.PIPE,
            }
            if os.name == "posix":
                popen_kwargs["start_new_session"] = True

            proc = subprocess.Popen(cmd_list, **popen_kwargs)

            stdout_holder: dict[str, Any] = {"data": b"", "truncated": False}
            stderr_holder: dict[str, Any] = {"data": b"", "truncated": False}
            t_out = None
            t_err = None

            if getattr(proc, "stdout", None) is not None:
                t_out = threading.Thread(
                    target=_drain_and_capture_stream,
                    args=(proc.stdout, self._max_output_bytes, stdout_holder),
                    daemon=True,
                )
                t_out.start()

            if getattr(proc, "stderr", None) is not None:
                t_err = threading.Thread(
                    target=_drain_and_capture_stream,
                    args=(proc.stderr, self._max_output_bytes, stderr_holder),
                    daemon=True,
                )
                t_err.start()

            try:
                proc.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                pid = getattr(proc, "pid", None)
                if pid:
                    kill_process_tree(pid)
                else:
                    if hasattr(proc, "kill"):
                        proc.kill()
                try:
                    proc.wait(timeout=1.0)
                except Exception:
                    pass
                raise
            finally:
                if t_out is not None and t_out.is_alive():
                    t_out.join(timeout=2.0)
                if t_err is not None and t_err.is_alive():
                    t_err.join(timeout=2.0)

            duration_ms = (time.perf_counter() - start_time) * 1000.0

            raw_out = stdout_holder.get("data", b"")
            is_out_truncated = stdout_holder.get("truncated", False)
            stdout = raw_out.decode("utf-8", errors="ignore")
            if is_out_truncated:
                stdout += "\n... [TRUNCATED: output exceeded size limit]"

            raw_err = stderr_holder.get("data", b"")
            is_err_truncated = stderr_holder.get("truncated", False)
            stderr = raw_err.decode("utf-8", errors="ignore")
            if is_err_truncated:
                stderr += "\n... [TRUNCATED: error output exceeded size limit]"

            # Redact secrets from output
            stdout_clean = redact(stdout)
            stderr_clean = redact(stderr)

            retcode = getattr(proc, "returncode", 0)
            return WorkspaceCommandResult(
                success=retcode == 0,
                command=command,
                exit_code=retcode,
                stdout=stdout_clean,
                stderr=stderr_clean,
                duration_ms=duration_ms,
                timed_out=False,
            )

        except subprocess.TimeoutExpired:
            duration_ms = (time.perf_counter() - start_time) * 1000.0
            logger.warning(
                "workspace_command_timeout",
                extra={"command": command, "timeout": timeout, "duration_ms": duration_ms},
            )
            raw_out = stdout_holder.get("data", b"") if "stdout_holder" in locals() else b""
            stdout_clean = redact(raw_out.decode("utf-8", errors="ignore"))
            return WorkspaceCommandResult(
                success=False,
                command=command,
                exit_code=-1,
                stdout=stdout_clean,
                stderr=redact(f"Command execution timed out after {timeout} seconds."),
                duration_ms=duration_ms,
                timed_out=True,
                error=f"Timeout expired: exceeded {timeout}s budget.",
            )

        except Exception as exc:
            if "proc" in locals() and proc is not None:
                pid = getattr(proc, "pid", None)
                if pid:
                    kill_process_tree(pid)
            duration_ms = (time.perf_counter() - start_time) * 1000.0
            logger.error("workspace_command_failed", extra={"command": command, "error": str(exc)})
            return WorkspaceCommandResult(
                success=False,
                command=command,
                exit_code=-1,
                stdout="",
                stderr=redact(str(exc)),
                duration_ms=duration_ms,
                timed_out=False,
                error=redact(f"Command execution error: {exc}"),
            )

    def execute_raw_command(
        self,
        command_list: Sequence[str],
        cwd: Path,
        timeout_seconds: int = 30,
    ) -> RawCommandResult:
        """Direct subprocess execution for internal git management operations."""
        proc = subprocess.run(
            list(command_list),
            cwd=str(cwd),
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout_seconds,
        )
        return RawCommandResult(
            exit_code=proc.returncode,
            stdout=proc.stdout or "",
            stderr=proc.stderr or "",
            returncode=proc.returncode,
        )


class RawCommandResult:
    """Lightweight result object for raw command execution."""

    def __init__(self, exit_code: int, stdout: str, stderr: str, returncode: int = 0):
        self.exit_code = exit_code
        self.stdout = stdout
        self.stderr = stderr
        self.returncode = returncode or exit_code
