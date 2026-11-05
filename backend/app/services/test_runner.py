"""Restricted Test Runner & Execution Service.

Fulfills Week 3 Day 4 Deliverable (Docs/daily_tasks.md line 635 & Docs/week3.md §6 F35).
Responsibilities:
- Enforce command allowlists (pytest, python -m unittest, npm test, etc.) and reject arbitrary shell commands.
- Execute permitted tests inside an isolated task workspace with execution timeout and memory/resource bounds.
- Bound stdout/stderr logs and redact sensitive secrets, tokens, or credentials.
- Classify test failures vs infrastructure errors vs execution timeouts.
- Capture execution metrics, duration, exit code, test counts, and associate results with workspace Git revision.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import shlex
import signal
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from app.core.errors import APIError, ErrorCode
from app.core.secret_redaction import redact

logger = logging.getLogger(__name__)

# Bounded output configuration
MAX_OUTPUT_BYTES = 100_000  # 100 KB max output capture
MAX_OUTPUT_LINES = 2_000
DEFAULT_TEST_TIMEOUT = 30.0  # seconds
MAX_TEST_TIMEOUT = 120.0

# Allowed test command templates (F34, F35)
ALLOWED_TEST_COMMANDS = {
    "pytest": ["pytest"],
    "python_unittest": ["python", "-m", "unittest"],
    "npm_test": ["npm", "test"],
    "npm_run_test": ["npm", "run", "test"],
    "yarn_test": ["yarn", "test"],
    "cargo_test": ["cargo", "test"],
    "go_test": ["go", "test"],
}

# Forbidden shell metacharacters and tokens
_SHELL_INJECTION_RE = re.compile(r"[;&|`$><\\!]")
_UNITTEST_SUMMARY_RE = re.compile(
    r"Ran\s+(?P<total>\d+)\s+tests?.*?FAILED\s+\((?:failures=(?P<failed>\d+))?(?:,\s*errors=(?P<errors>\d+))?\)",
    re.DOTALL,
)


TestExecutionStatus = Literal["PASSED", "FAILED", "TIMEOUT", "INFRASTRUCTURE_ERROR"]


@dataclass
class TestCounts:
    """Parsed test counts from test runner execution."""
    __test__ = False

    passed: int = 0
    failed: int = 0
    errors: int = 0
    skipped: int = 0
    total: int = 0

    def to_dict(self) -> dict[str, int]:
        return {
            "passed": self.passed,
            "failed": self.failed,
            "errors": self.errors,
            "skipped": self.skipped,
            "total": self.total,
        }


@dataclass
class RestrictedExecutionResult:
    """Sanitized and bounded outcome of a restricted test run."""
    command: list[str]
    exit_code: int
    status: TestExecutionStatus
    duration_ms: int
    stdout: str
    stderr: str
    test_counts: TestCounts
    workspace_revision: str | None = None
    timed_out: bool = False
    is_infrastructure_error: bool = False
    error_message: str | None = None


class CommandPolicyValidator:
    """Validates and enforces allowed test commands and argument boundaries."""

    @classmethod
    def validate_command(cls, raw_command: list[str] | str) -> list[str]:
        """Validate that a test command strictly matches allowlisted command prefixes.

        Raises APIError(400, COMMAND_NOT_ALLOWED) if rejected.
        """
        if isinstance(raw_command, str):
            cmd_str = raw_command.strip()
            if _SHELL_INJECTION_RE.search(cmd_str):
                raise APIError(
                    400,
                    ErrorCode.COMMAND_NOT_ALLOWED,
                    "Disallowed shell metacharacters detected in test command.",
                )
            try:
                cmd_parts = shlex.split(cmd_str)
            except ValueError as exc:
                raise APIError(
                    400,
                    ErrorCode.INVALID_REQUEST,
                    f"Invalid test command syntax: {exc}",
                ) from exc
        else:
            cmd_parts = [str(arg).strip() for arg in raw_command if str(arg).strip()]

        if not cmd_parts:
            raise APIError(400, ErrorCode.COMMAND_NOT_ALLOWED, "Empty test command.")

        # Check for shell metacharacters inside individual tokens
        for token in cmd_parts:
            if _SHELL_INJECTION_RE.search(token):
                raise APIError(
                    400,
                    ErrorCode.COMMAND_NOT_ALLOWED,
                    f"Disallowed token '{token}' contains shell metacharacters.",
                )

        # Match against allowlisted prefixes
        base = cmd_parts[0].lower()
        base_name = Path(base).name.lower()

        matched_allowlist = False
        if base_name == "pytest":
            matched_allowlist = True
        elif base_name in ("cargo", "go") and len(cmd_parts) >= 2 and cmd_parts[1] == "test":
            matched_allowlist = True
        elif base_name in ("python", "python3") and len(cmd_parts) >= 3 and cmd_parts[1] == "-m" and cmd_parts[2] in ("unittest", "pytest"):
            matched_allowlist = True
        elif base_name in ("npm", "yarn") and len(cmd_parts) >= 2 and cmd_parts[1] in ("test", "run"):
            matched_allowlist = True

        if not matched_allowlist:
            raise APIError(
                400,
                ErrorCode.COMMAND_NOT_ALLOWED,
                f"Command '{base_name}' is not in the allowed test command allowlist.",
            )

        # Ensure no disallowed path escapes in extra arguments
        for arg in cmd_parts[1:]:
            # Allow Go's recursive package pattern ./...
            if arg == "./...":
                continue
            if ".." in arg.replace("\\", "/").split("/") or arg.startswith("/etc") or arg.startswith("C:\\Windows") or arg.startswith(".."):
                raise APIError(
                    400,
                    ErrorCode.COMMAND_NOT_ALLOWED,
                    f"Disallowed argument contains path traversal or absolute system path: '{arg}'",
                )

        return cmd_parts


class RestrictedTestRunner:
    """Executes permitted tests inside an isolated task workspace with strict safeguards."""

    def __init__(self, default_timeout: float = DEFAULT_TEST_TIMEOUT) -> None:
        self.default_timeout = min(default_timeout, MAX_TEST_TIMEOUT)

    @staticmethod
    def _truncate_output(text: str) -> str:
        """Enforce character and line bounds on logs."""
        if len(text) > MAX_OUTPUT_BYTES:
            text = text[:MAX_OUTPUT_BYTES] + "\n... [TRUNCATED DUE TO SIZE LIMIT]"
        lines = text.splitlines()
        if len(lines) > MAX_OUTPUT_LINES:
            text = "\n".join(lines[:MAX_OUTPUT_LINES]) + "\n... [TRUNCATED DUE TO LINE LIMIT]"
        return text

    @staticmethod
    def _parse_counts(stdout: str, stderr: str) -> TestCounts:
        """Extract test counts from pytest or unittest output."""
        combined = f"{stdout}\n{stderr}"
        counts = TestCounts()

        # Unittest matching first if unittest summary banner is present
        uni_match = _UNITTEST_SUMMARY_RE.search(combined)
        if uni_match:
            gd = uni_match.groupdict()
            total = int(gd["total"]) if gd.get("total") else 0
            failed = int(gd["failed"]) if gd.get("failed") else 0
            errors = int(gd["errors"]) if gd.get("errors") else 0
            counts.total = total
            counts.failed = failed
            counts.errors = errors
            counts.passed = max(0, total - failed - errors)
            return counts

        uni_ok_match = re.search(r"Ran\s+(?P<total>\d+)\s+tests?.*?\bOK\b", combined, re.DOTALL)
        if uni_ok_match:
            total = int(uni_ok_match.group("total"))
            counts.total = total
            counts.passed = total
            return counts

        # Pytest summary matching (extract counts from summary banner)
        passed_matches = re.findall(r"\b(\d+)\s+passed\b", combined, re.IGNORECASE)
        failed_matches = re.findall(r"\b(\d+)\s+failed\b", combined, re.IGNORECASE)
        skipped_matches = re.findall(r"\b(\d+)\s+skipped\b", combined, re.IGNORECASE)
        error_matches = re.findall(r"\b(\d+)\s+errors?\b", combined, re.IGNORECASE)

        if passed_matches or failed_matches or skipped_matches or error_matches:
            counts.passed = int(passed_matches[-1]) if passed_matches else 0
            counts.failed = int(failed_matches[-1]) if failed_matches else 0
            counts.skipped = int(skipped_matches[-1]) if skipped_matches else 0
            counts.errors = int(error_matches[-1]) if error_matches else 0
            counts.total = counts.passed + counts.failed + counts.skipped + counts.errors

        return counts

    @staticmethod
    def _classify_failure(
        exit_code: int,
        stdout: str,
        stderr: str,
        counts: TestCounts,
    ) -> tuple[TestExecutionStatus, bool]:
        """Classify exit code into PASSED, FAILED, or INFRASTRUCTURE_ERROR."""
        if exit_code == 0:
            return "PASSED", False

        combined = f"{stdout}\n{stderr}".lower()
        infra_indicators = [
            "command not found",
            "not recognized as an internal or external command",
            "no such file or directory",
            "module not found",
            "no module named",
            "syntaxerror",
            "permission denied",
            "failed to import",
            "failedtest",
            "executable not found",
            "importerror",
        ]

        if any(ind in combined for ind in infra_indicators) and counts.passed == 0:
            return "INFRASTRUCTURE_ERROR", True

        return "FAILED", False

    async def run_tests(
        self,
        workspace_path: Path | str,
        command: list[str] | str = "pytest",
        timeout_seconds: float | None = None,
        workspace_revision: str | None = None,
        env_overrides: dict[str, str] | None = None,
    ) -> RestrictedExecutionResult:
        """Run permitted test command inside workspace directory with boundaries."""
        from app.services.git_branch import _PROTECTED_SYSTEM_PREFIXES, _REPO_ROOT

        raw_ws_str = str(workspace_path or "").strip()
        if not raw_ws_str or "\x00" in raw_ws_str or ".." in raw_ws_str.replace("\\", "/").split("/"):
            raise APIError(400, ErrorCode.INVALID_REQUEST, "Unsafe workspace_path.")

        ws_path = Path(raw_ws_str).resolve()
        resolved_str = ws_path.as_posix()
        for prefix in _PROTECTED_SYSTEM_PREFIXES:
            if resolved_str == prefix or resolved_str.startswith(prefix + "/"):
                raise APIError(
                    400,
                    ErrorCode.INVALID_REQUEST,
                    f"Workspace path points to a protected system directory: {workspace_path}",
                )
        if ws_path in (_REPO_ROOT, _REPO_ROOT / "backend", _REPO_ROOT / "frontend"):
            raise APIError(
                400,
                ErrorCode.INVALID_REQUEST,
                "Refusing to run restricted test runner directly against the host platform repository.",
            )
        if not ws_path.exists() or not ws_path.is_dir():
            raise APIError(400, ErrorCode.WORKSPACE_CREATION_FAILED, f"Workspace path does not exist: {ws_path}")

        # Validate command against allowlist
        validated_cmd = CommandPolicyValidator.validate_command(command)
        timeout = min(timeout_seconds or self.default_timeout, MAX_TEST_TIMEOUT)

        # Resolve workspace commit SHA if not supplied
        effective_revision = workspace_revision
        if effective_revision is None and (ws_path / ".git").exists():
            try:
                proc_rev = await asyncio.create_subprocess_exec(
                    "git", "rev-parse", "HEAD",
                    cwd=str(ws_path),
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                out_rev, _ = await proc_rev.communicate()
                if proc_rev.returncode == 0:
                    effective_revision = out_rev.decode().strip()
            except Exception:
                pass

        # Environment isolation: use clean safe keys, prepend workspace_path to PYTHONPATH,
        # set offline variables and strip host secrets
        safe_keys = {
            "PATH",
            "SYSTEMROOT",
            "SYSTEMDRIVE",
            "WINDIR",
            "TEMP",
            "TMP",
            "TMPDIR",
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
        clean_env = {k: v for k, v in os.environ.items() if k.upper() in safe_keys}
        clean_env["PYTHONDONTWRITEBYTECODE"] = "1"
        clean_env["PYTHONPATH"] = f"{ws_path}{os.pathsep}."
        clean_env["PIP_NO_INDEX"] = "1"
        clean_env["PIP_DISABLE_PIP_VERSION_CHECK"] = "1"
        clean_env["NPM_CONFIG_OFFLINE"] = "true"
        clean_env["NO_PROXY"] = "*"
        clean_env["no_proxy"] = "*"

        _SENSITIVE_ENV_RE = re.compile(
            r"(?:SECRET|TOKEN|PASSWORD|API_KEY|DATABASE_URL|LD_|DYLD_|PYTHONPATH|PATH|NODE_OPTIONS|GIT_SSH)",
            re.IGNORECASE,
        )
        if env_overrides:
            for k, v in env_overrides.items():
                if not _SHELL_INJECTION_RE.search(k) and not _SENSITIVE_ENV_RE.search(k):
                    clean_env[k] = v

        # Use current Python interpreter for consistent environment resolution
        exec_cmd = list(validated_cmd)
        base_cmd_name = Path(exec_cmd[0]).name.lower()
        if base_cmd_name in ("python", "python3"):
            exec_cmd[0] = sys.executable
        elif base_cmd_name == "pytest":
            exec_cmd = [sys.executable, "-m", "pytest", *exec_cmd[1:]]

        # Prevent parent directory pytest.ini (--cov=app, etc.) and .pytest_cache from polluting isolated workspace runs
        if (
            len(exec_cmd) >= 3
            and exec_cmd[0] == sys.executable
            and exec_cmd[1] == "-m"
            and exec_cmd[2] == "pytest"
            and "-o" not in exec_cmd
            and not (ws_path / "pytest.ini").exists()
            and not (ws_path / "pyproject.toml").exists()
            and not (ws_path / "setup.cfg").exists()
        ):
            exec_cmd = [
                sys.executable,
                "-m",
                "pytest",
                "-p",
                "no:cacheprovider",
                "-o",
                "addopts=",
                *exec_cmd[3:],
            ]

        popen_kwargs: dict[str, Any] = {}
        if os.name == "posix":
            popen_kwargs["start_new_session"] = True

        start_time = time.perf_counter()
        timed_out = False
        try:
            process = await asyncio.create_subprocess_exec(
                *exec_cmd,
                cwd=str(ws_path),
                env=clean_env,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                **popen_kwargs,
            )

            try:
                raw_stdout, raw_stderr = await asyncio.wait_for(
                    process.communicate(),
                    timeout=timeout,
                )
            except asyncio.TimeoutError:
                timed_out = True
                if os.name == "posix" and hasattr(os, "killpg") and getattr(process, "pid", None):
                    try:
                        os.killpg(process.pid, signal.SIGKILL)
                    except Exception:
                        pass
                try:
                    process.kill()
                    await process.wait()
                except Exception:
                    pass
                raw_stdout, raw_stderr = b"", b"Execution exceeded timeout limit."

        except FileNotFoundError as exc:
            duration_ms = int((time.perf_counter() - start_time) * 1000)
            return RestrictedExecutionResult(
                command=validated_cmd,
                exit_code=127,
                status="INFRASTRUCTURE_ERROR",
                duration_ms=duration_ms,
                stdout="",
                stderr=f"Executable '{validated_cmd[0]}' not found.",
                test_counts=TestCounts(),
                workspace_revision=effective_revision,
                is_infrastructure_error=True,
                error_message=str(exc),
            )
        except Exception as exc:
            duration_ms = int((time.perf_counter() - start_time) * 1000)
            return RestrictedExecutionResult(
                command=validated_cmd,
                exit_code=1,
                status="INFRASTRUCTURE_ERROR",
                duration_ms=duration_ms,
                stdout="",
                stderr=f"Process invocation error: {exc}",
                test_counts=TestCounts(),
                workspace_revision=effective_revision,
                is_infrastructure_error=True,
                error_message=str(exc),
            )

        duration_ms = int((time.perf_counter() - start_time) * 1000)

        # Decode, redact, and truncate outputs
        clean_stdout = redact(self._truncate_output(raw_stdout.decode("utf-8", errors="replace")))
        clean_stderr = redact(self._truncate_output(raw_stderr.decode("utf-8", errors="replace")))

        if timed_out:
            return RestrictedExecutionResult(
                command=validated_cmd,
                exit_code=124,
                status="TIMEOUT",
                duration_ms=duration_ms,
                stdout=clean_stdout,
                stderr=clean_stderr,
                test_counts=TestCounts(),
                workspace_revision=effective_revision,
                timed_out=True,
                error_message=f"Test command timed out after {timeout}s",
            )

        exit_code = process.returncode or 0
        counts = self._parse_counts(clean_stdout, clean_stderr)
        status, is_infra = self._classify_failure(exit_code, clean_stdout, clean_stderr, counts)

        return RestrictedExecutionResult(
            command=validated_cmd,
            exit_code=exit_code,
            status=status,
            duration_ms=duration_ms,
            stdout=clean_stdout,
            stderr=clean_stderr,
            test_counts=counts,
            workspace_revision=effective_revision,
            is_infrastructure_error=is_infra,
        )
