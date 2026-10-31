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
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Mapping, Sequence

from app.core.secret_redaction import redact
from app.schemas.workspace import WorkspaceCommandResult
from sandbox.constants import (
    ALLOWED_COMMAND_TEMPLATES,
    DEFAULT_COMMAND_TIMEOUT_SECONDS,
    DISALLOWED_COMMAND_TOKENS,
    MAX_COMMAND_OUTPUT_BYTES,
    MAX_TIMEOUT_SECONDS,
    SENSITIVE_ENV_VARS,
)
from sandbox.exceptions import (
    WorkspaceCommandError,
    WorkspaceCommandTimeoutError,
    WorkspacePolicyViolationError,
)

logger = logging.getLogger(__name__)


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

        # Preserve only standard non-sensitive system variables
        safe_keys = {
            "PATH",
            "SYSTEMROOT",
            "SYSTEMDRIVE",
            "WINDIR",
            "TEMP",
            "TMP",
            "USERPROFILE",
            "HOMEPATH",
            "HOMEDRIVE",
            "LANG",
            "LC_ALL",
            "PYTHONPATH",
            "PYTHONUNBUFFERED",
            "NODE_ENV",
            "COMSPEC",
            "PATHEXT",
        }

        for k, v in os.environ.items():
            if k.upper() in safe_keys:
                env[k] = v

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

        exec_cmd = command
        if command == "python" and not shutil.which("python"):
            exec_cmd = shutil.which("python3") or sys.executable

        cmd_list = [exec_cmd, *args]

        try:
            with tempfile.TemporaryFile() as out_file, tempfile.TemporaryFile() as err_file:
                proc = subprocess.Popen(
                    cmd_list,
                    cwd=str(workspace_root.resolve()),
                    env=env,
                    stdout=out_file,
                    stderr=err_file,
                )
                try:
                    proc.wait(timeout=timeout)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait()
                    raise

                duration_ms = (time.perf_counter() - start_time) * 1000.0

                out_file.seek(0)
                raw_out = out_file.read(self._max_output_bytes + 1)
                is_out_truncated = len(raw_out) > self._max_output_bytes
                stdout = raw_out[: self._max_output_bytes].decode("utf-8", errors="ignore")
                if is_out_truncated:
                    stdout += "\n... [TRUNCATED: output exceeded size limit]"

                err_file.seek(0)
                raw_err = err_file.read(self._max_output_bytes + 1)
                is_err_truncated = len(raw_err) > self._max_output_bytes
                stderr = raw_err[: self._max_output_bytes].decode("utf-8", errors="ignore")
                if is_err_truncated:
                    stderr += "\n... [TRUNCATED: error output exceeded size limit]"

                # Redact secrets from output
                stdout_clean = redact(stdout)
                stderr_clean = redact(stderr)

                return WorkspaceCommandResult(
                    success=proc.returncode == 0,
                    command=command,
                    exit_code=proc.returncode,
                    stdout=stdout_clean,
                    stderr=stderr_clean,
                    duration_ms=duration_ms,
                    timed_out=False,
                )

        except subprocess.TimeoutExpired as exc:
            duration_ms = (time.perf_counter() - start_time) * 1000.0
            logger.warning(
                "workspace_command_timeout",
                extra={"command": command, "timeout": timeout, "duration_ms": duration_ms},
            )
            return WorkspaceCommandResult(
                success=False,
                command=command,
                exit_code=-1,
                stdout="",
                stderr=redact(f"Command execution timed out after {timeout} seconds."),
                duration_ms=duration_ms,
                timed_out=True,
                error=f"Timeout expired: exceeded {timeout}s budget.",
            )

        except Exception as exc:
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
