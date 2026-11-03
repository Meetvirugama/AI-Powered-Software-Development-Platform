"""Bounded Self-Repair Loop & Budget Manager.

Fulfills Week 3 Day 4 Deliverable (Docs/daily_tasks.md lines 637-641 & Docs/week3.md §6 F35).
Responsibilities:
- Manage the strict 3-attempt task repair ceiling across executions and worker restarts.
- Classify failure tracebacks and determine repair eligibility.
- Block repair on security-policy violations, infrastructure crashes, or budget exhaustion.
- Apply targeted workspace patches with path traversal confinement.
- Re-run permitted tests against the newly committed workspace revision.
- Preserve repair history and failure diagnoses.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal
from uuid import UUID

from app.core.errors import APIError, ErrorCode
from app.core.input_security import UnsafePathError, validate_repo_relative_path
from app.services.test_runner import RestrictedExecutionResult, RestrictedTestRunner

logger = logging.getLogger(__name__)

MAX_TASK_REPAIR_ATTEMPTS = 3


@dataclass
class RepairEligibility:
    """Eligibility evaluation for a self-repair attempt."""
    is_eligible: bool
    reason: str
    attempts_used: int
    attempts_remaining: int
    stop_workflow: bool = False


@dataclass
class RepairAttemptRecord:
    """Audit record of a single repair cycle."""
    attempt_number: int
    diagnosis: str
    target_file: str | None
    patch_applied: bool
    previous_revision: str | None
    new_revision: str | None
    test_result: RestrictedExecutionResult | None = None
    success: bool = False
    message: str = ""


class BoundedRepairManager:
    """Controls bounded repair execution and budget enforcement."""

    def __init__(self, test_runner: RestrictedTestRunner | None = None) -> None:
        self.runner = test_runner or RestrictedTestRunner()
        # In-memory tracking fallback per task (persistent layer can serialize this)
        self._task_budgets: dict[str, int] = {}
        self._history: dict[str, list[RepairAttemptRecord]] = {}

    def get_attempts_used(self, task_id: UUID | str) -> int:
        """Get the number of repair attempts already spent for this task."""
        return self._task_budgets.get(str(task_id), 0)

    def set_attempts_used(self, task_id: UUID | str, count: int) -> None:
        """Restore or persist the repair budget count."""
        self._task_budgets[str(task_id)] = max(0, count)

    def evaluate_eligibility(
        self,
        task_id: UUID | str,
        test_status: str,
        is_infrastructure_error: bool = False,
        has_security_violation: bool = False,
        explicit_attempts_used: int | None = None,
    ) -> RepairEligibility:
        """Determine whether another repair attempt is permitted for this task.

        Enforces:
        1. Max 3 repair attempts ceiling (Docs/week3.md §6 F35 retry policy).
        2. Immediate stop on security policy violations.
        3. Immediate stop on infrastructure / environment failures.
        4. Repair only when functional test failures exist and budget remains.
        """
        used = explicit_attempts_used if explicit_attempts_used is not None else self.get_attempts_used(task_id)
        remaining = max(0, MAX_TASK_REPAIR_ATTEMPTS - used)

        if has_security_violation:
            return RepairEligibility(
                is_eligible=False,
                reason="Security policy violation detected. Repair loop stopped immediately.",
                attempts_used=used,
                attempts_remaining=remaining,
                stop_workflow=True,
            )

        if is_infrastructure_error:
            return RepairEligibility(
                is_eligible=False,
                reason="Infrastructure or environment error. Automated code repair cannot resolve environment failures.",
                attempts_used=used,
                attempts_remaining=remaining,
                stop_workflow=True,
            )

        if used >= MAX_TASK_REPAIR_ATTEMPTS:
            return RepairEligibility(
                is_eligible=False,
                reason=f"Task repair budget exhausted ({used}/{MAX_TASK_REPAIR_ATTEMPTS} attempts used).",
                attempts_used=used,
                attempts_remaining=0,
                stop_workflow=True,
            )

        if test_status != "FAILED":
            return RepairEligibility(
                is_eligible=False,
                reason=f"Test status is '{test_status}'; repair is only applicable to 'FAILED' test runs.",
                attempts_used=used,
                attempts_remaining=remaining,
                stop_workflow=False,
            )

        return RepairEligibility(
            is_eligible=True,
            reason=f"Eligible for repair attempt {used + 1}/{MAX_TASK_REPAIR_ATTEMPTS}.",
            attempts_used=used,
            attempts_remaining=remaining,
            stop_workflow=False,
        )

    async def apply_workspace_patch(
        self,
        workspace_path: Path | str,
        target_file: str,
        new_content: str | None = None,
        patch_text: str | None = None,
    ) -> Path:
        """Apply a validated repair patch or file update confined to workspace.

        Guards against path traversal and symlink escapes.
        """
        from app.services.git_branch import _PROTECTED_SYSTEM_PREFIXES, _REPO_ROOT

        raw_ws_str = str(workspace_path or "").strip()
        if not raw_ws_str or "\x00" in raw_ws_str or ".." in raw_ws_str.replace("\\", "/").split("/"):
            raise APIError(400, ErrorCode.INVALID_REQUEST, "Unsafe workspace_path.")

        ws = Path(raw_ws_str).resolve()
        resolved_str = ws.as_posix()
        for prefix in _PROTECTED_SYSTEM_PREFIXES:
            if resolved_str == prefix or resolved_str.startswith(prefix + "/"):
                raise APIError(
                    400,
                    ErrorCode.INVALID_REQUEST,
                    f"Workspace path points to a protected system directory: {workspace_path}",
                )
        if ws in (_REPO_ROOT, _REPO_ROOT / "backend", _REPO_ROOT / "frontend"):
            raise APIError(
                400,
                ErrorCode.INVALID_REQUEST,
                "Refusing to apply repair patch directly against the host platform repository.",
            )
        if not ws.exists() or not ws.is_dir():
            raise APIError(400, ErrorCode.WORKSPACE_CREATION_FAILED, f"Workspace does not exist: {ws}")

        # Validate path safety
        try:
            rel_file = validate_repo_relative_path(target_file)
        except UnsafePathError as exc:
            raise APIError(400, ErrorCode.INVALID_REQUEST, f"Unsafe target file path: {exc}") from exc

        dest_file = (ws / rel_file).resolve()
        # Confinement check
        try:
            dest_file.relative_to(ws)
        except ValueError as exc:
            raise APIError(400, ErrorCode.INVALID_REQUEST, f"Path escape outside workspace: {dest_file}") from exc

        dest_file.parent.mkdir(parents=True, exist_ok=True)

        if new_content is not None:
            dest_file.write_text(new_content, encoding="utf-8")
        elif patch_text is not None:
            # Apply patch via git apply or direct file replacement
            proc = await asyncio.create_subprocess_exec(
                "git", "apply", "--ignore-whitespace", "-",
                cwd=str(ws),
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await proc.communicate(input=patch_text.encode("utf-8"))
            if proc.returncode != 0:
                raise APIError(
                    400,
                    ErrorCode.INVALID_REQUEST,
                    f"Failed to apply patch to {target_file}: {stderr.decode('utf-8', errors='replace')}",
                )
        else:
            raise APIError(400, ErrorCode.INVALID_REQUEST, "Either new_content or patch_text must be provided.")

        return dest_file

    async def execute_repair_attempt(
        self,
        task_id: UUID | str,
        workspace_path: Path | str,
        diagnosis: str,
        target_file: str,
        new_content: str | None = None,
        patch_text: str | None = None,
        test_command: list[str] | str = "pytest",
        current_attempts_used: int | None = None,
        timeout_seconds: float = 30.0,
    ) -> RepairAttemptRecord:
        """Perform a single bounded repair cycle: validate eligibility -> apply patch -> re-run tests."""
        from app.services.git_branch import _PROTECTED_SYSTEM_PREFIXES, _REPO_ROOT

        raw_ws_str = str(workspace_path or "").strip()
        if not raw_ws_str or "\x00" in raw_ws_str or ".." in raw_ws_str.replace("\\", "/").split("/"):
            raise APIError(400, ErrorCode.INVALID_REQUEST, "Unsafe workspace_path.")

        ws = Path(raw_ws_str).resolve()
        resolved_str = ws.as_posix()
        for prefix in _PROTECTED_SYSTEM_PREFIXES:
            if resolved_str == prefix or resolved_str.startswith(prefix + "/"):
                raise APIError(
                    400,
                    ErrorCode.INVALID_REQUEST,
                    f"Workspace path points to a protected system directory: {workspace_path}",
                )
        if ws in (_REPO_ROOT, _REPO_ROOT / "backend", _REPO_ROOT / "frontend"):
            raise APIError(
                400,
                ErrorCode.INVALID_REQUEST,
                "Refusing to execute repair attempt directly against the host platform repository.",
            )
        used = current_attempts_used if current_attempts_used is not None else self.get_attempts_used(task_id)

        eligibility = self.evaluate_eligibility(
            task_id=task_id,
            test_status="FAILED",
            explicit_attempts_used=used,
        )
        if not eligibility.is_eligible:
            raise APIError(
                400,
                ErrorCode.RETRY_BUDGET_EXHAUSTED if used >= MAX_TASK_REPAIR_ATTEMPTS else ErrorCode.POLICY_VIOLATION,
                eligibility.reason,
            )

        attempt_num = used + 1
        str_task = str(task_id)

        # Capture previous revision
        prev_rev: str | None = None
        if (ws / ".git").exists():
            p = await asyncio.create_subprocess_exec(
                "git", "rev-parse", "HEAD", cwd=str(ws),
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            )
            out, _ = await p.communicate()
            if p.returncode == 0:
                prev_rev = out.decode().strip()

        # Apply the fix
        await self.apply_workspace_patch(
            workspace_path=ws,
            target_file=target_file,
            new_content=new_content,
            patch_text=patch_text,
        )
        safe_rel_target = validate_repo_relative_path(target_file)

        # Stage and commit locally on the task branch
        new_rev = prev_rev
        if (ws / ".git").exists():
            add_proc = await asyncio.create_subprocess_exec(
                "git", "add", "--", safe_rel_target,
                cwd=str(ws),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await add_proc.communicate()

            c_proc = await asyncio.create_subprocess_exec(
                "git", "commit", "-m", f"fix(agent): auto-repair attempt {attempt_num} for task {task_id}",
                cwd=str(ws),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await c_proc.communicate()

            r_proc = await asyncio.create_subprocess_exec(
                "git", "rev-parse", "HEAD", cwd=str(ws),
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            )
            rout, _ = await r_proc.communicate()
            if r_proc.returncode == 0:
                new_rev = rout.decode().strip()

        # Update budget count
        self.set_attempts_used(str_task, attempt_num)

        # Re-run tests against new workspace revision
        test_result = await self.runner.run_tests(
            workspace_path=ws,
            command=test_command,
            timeout_seconds=timeout_seconds,
            workspace_revision=new_rev,
        )

        record = RepairAttemptRecord(
            attempt_number=attempt_num,
            diagnosis=diagnosis,
            target_file=safe_rel_target,
            patch_applied=True,
            previous_revision=prev_rev,
            new_revision=new_rev,
            test_result=test_result,
            success=(test_result.status == "PASSED"),
            message="Repair succeeded; tests passed." if test_result.status == "PASSED" else "Tests still failing after repair attempt.",
        )

        if str_task not in self._history:
            self._history[str_task] = []
        self._history[str_task].append(record)

        return record
