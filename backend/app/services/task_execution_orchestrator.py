"""Task Execution, Sandbox Tool Routing, Test Runner, Bounded Repair, Verification, Draft PR & Recovery Orchestrator.

Owner: Yug, Meet, Prit & Sukun — Week 3 Day 3–7 Deliverable (Docs/week3.md §6 F33–F39 & §8 Day 3–7)
Responsibilities:
1. Provision and manage isolated task workspaces (`WorkspaceManager`) synchronized with PostgreSQL (`TaskRepository`).
2. Enforce human approval gates (`verify_execution_approval_gate`) before any workspace provisioning or step execution.
3. Route tool invocations through `ToolRouter` and `WorkspaceToolPolicyBridge` while recording audit logs (`ToolInvocation`).
4. Execute approved plan steps with anti-cyclic loop detection (`AgentExecutionLoop`).
5. Execute restricted test suites (`WorkspaceTestRunner`) and persist `TestRun` outcomes.
6. Run bounded self-repair cycles (`BoundedRepairLoop`, max 3 task-level attempts) and persist `RepairAttempt` records.
7. Run independent multi-dimensional verification (`run_independent_verification`: tests, diff scope, secret scan, Week 2 static analysis, Meet's `RequirementToCodeVerifier`, and AI code review) strictly bound to `verified_revision` and diff hash.
8. Enforce explicit human publication authorization, protected branch guards, post-verification diff immutability, and stale base-revision detection before committing, pushing, and creating a GitHub Draft PR (`is_draft=True`, zero auto-merge).
9. Persist secret-scrubbed recovery checkpoints, reconcile interrupted tasks/workspaces on startup or operator request without resetting the 3-attempt repair budget, and verify sandbox security invariants.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import re
import shlex
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence
from uuid import UUID

from agent.tools.router import ToolRequest, ToolResult, ToolRouter
from ai.services.agent_execution_loop import (
    AgentExecutionLoop,
    AgentExecutionResult,
    StepExecutionStatus,
)
from ai.services.edit_synthesizer import EditSynthesizer
from ai.services.bounded_repair_loop import BoundedRepairLoop, BoundedRepairOutcome
from ai.services.execution_budget_manager import ExecutionBudgetManager
from ai.services.execution_checkpoint_manager import ExecutionCheckpointManager
from ai.services.execution_recovery import ExecutionRecoveryService
from ai.services.requirement_verifier import RequirementToCodeVerifier
from app.services.task_execution_report import TaskExecutionReportGenerator
from app.core.config import get_settings
from app.core.errors import APIError, ErrorCode
from app.core.secret_redaction import redact, redact_obj
from app.models.task import (
    AgentTask,
    ExecutionStatus,
    RepairResult,
    TaskCheckpoint,
    TaskEventType,
    TaskExecution,
    TaskPullRequest,
    TaskStatus,
    TestRunStatus,
    ToolInvocationStatus,
    VerificationStatus,
    WorkspaceStatus as DBWorkspaceStatus,
)
from app.repositories.task_repository import TaskRepository
from app.schemas.repair import RepairPatchPayload
from app.schemas.task import TaskConstraint, TaskRequirement
from app.schemas.verification import (
    VerificationCheckItem,
    VerificationContext,
    VerificationFinding,
    VerificationOverallStatus,
    VerificationResult as VerificationResultSchema,
)
from app.services.independent_verifier import IndependentVerifier
from app.schemas.workspace import (
    DiffImmutabilityCheckResult,
    TestOutcomeStatus,
    WorkspaceCommitRequest,
    WorkspaceCommitResult,
    WorkspaceCreateRequest,
    WorkspaceDiffResult,
    WorkspaceMetadata,
    WorkspacePushRequest,
    WorkspacePushResult,
    WorkspaceStartExecutionRequest,
    WorkspaceStatus,
    WorkspaceTestExecutionRequest,
    WorkspaceTestExecutionResult,
)
from app.services.bug_detection_orchestrator import BuiltinStaticBugScanner
from app.services.git_branch import GitBranchService, format_agent_branch_name
from app.integrations.github.client import GitHubAPIError
from app.integrations.github.exceptions import GitHubError
from sandbox.constants import PROTECTED_BRANCHES
from sandbox.exceptions import (
    WorkspaceCommitError,
    WorkspaceDuplicateRepairPatchError,
    WorkspaceProtectedBranchError,
    WorkspacePushError,
    WorkspaceRecoveryError,
    WorkspaceRepairBudgetExhaustedError,
    WorkspaceStaleRevisionError,
    WorkspaceStateError,
)
from sandbox.tool_policy_bridge import CANONICAL_TOOL_METADATA, WorkspaceToolPolicyBridge, register_workspace_tools
from sandbox.workspace_manager import WorkspaceManager

logger = logging.getLogger(__name__)

_HEX_SHA_RE = re.compile(r"^[0-9a-fA-F]{7,64}$")
_COMMIT_SHA_RE = re.compile(r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")

DEFAULT_COMMAND_ALLOWLIST: dict[str, list[list[str]]] = {
    "execute_command": [
        ["pytest", "*"],
        ["python", "-m", "pytest", "*"],
        ["python", "-m", "unittest", "*"],
        ["git", "status", "*"],
        ["git", "diff", "*"],
        ["git", "log", "*"],
        ["npm", "test", "*"],
        ["ruff", "check", "*"],
    ],
    "run_tests": [
        ["pytest", "*"],
        ["python", "-m", "pytest", "*"],
        ["npm", "test", "*"],
    ],
}


# ---------------------------------------------------------------------------
# Sukun W3 Day 6: git name validation for branch / commit / push / Draft PR APIs
# ---------------------------------------------------------------------------
# Branch and remote names from API callers end up as `git` arguments. A value such as
# `--receive-pack=<cmd>` or `--upload-pack=<cmd>` would be read by git as an option and
# run a command on the server, so names are checked before any git call.

_SAFE_GIT_REF_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,199}$")
_SAFE_REMOTE_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
# A user-triggered recovery may only send the task back to planning or approval (so the
# approval gate and verification run again), or cancel it.
_USER_RECOVERY_TARGETS = frozenset({TaskStatus.PLANNING, TaskStatus.APPROVED, TaskStatus.CANCELLED})


def _require_safe_git_ref(value: str | None, label: str) -> None:
    if value is None:
        return
    clean = str(value).strip()
    if clean.startswith("refs/heads/"):
        clean = clean[len("refs/heads/"):]
    if (
        not _SAFE_GIT_REF_RE.match(clean)
        or ".." in clean
        or "//" in clean
        or "@{" in clean
        or clean.endswith((".lock", "/", "."))
    ):
        raise APIError(400, ErrorCode.INVALID_REQUEST, f"Invalid {label}.")


def _require_safe_remote_name(value: str | None) -> None:
    if value is None:
        return
    if not _SAFE_REMOTE_NAME_RE.match(str(value).strip()):
        raise APIError(400, ErrorCode.INVALID_REQUEST, "Invalid remote name.")


def _require_safe_commit_files(files: Sequence[str] | None) -> None:
    from app.core.input_security import UnsafePathError, validate_repo_relative_path

    for item in files or []:
        text = str(item)
        if text.strip().startswith("-"):
            raise APIError(400, ErrorCode.INVALID_REQUEST, "Invalid file path in commit request.")
        try:
            validate_repo_relative_path(text)
        except UnsafePathError as exc:
            raise APIError(400, ErrorCode.INVALID_REQUEST, "Invalid file path in commit request.") from exc


class TaskExecutionOrchestrator:
    """Coordinates database persistence, WorkspaceManager, ToolRouter, AgentExecutionLoop, BoundedRepairLoop, Verification, and Draft PR publication."""

    def __init__(
        self,
        workspace_manager: WorkspaceManager | None = None,
        tool_router: ToolRouter | None = None,
        llm_gateway: Any = None,
    ) -> None:
        self.workspace_manager = workspace_manager or WorkspaceManager()
        self.tool_router = tool_router or ToolRouter(command_allowlist=DEFAULT_COMMAND_ALLOWLIST)
        self.policy_bridge = self._ensure_tools_registered(self.tool_router, self.workspace_manager)
        self.edit_synthesizer = EditSynthesizer(llm_gateway=llm_gateway, model=get_settings().active_chat_model)
        self.execution_loop = AgentExecutionLoop(
            workspace_manager=self.workspace_manager,
            tool_router=self.tool_router,
            edit_synthesizer=self.edit_synthesizer,
        )
        self.repair_loop = BoundedRepairLoop(
            workspace_manager=self.workspace_manager,
            test_runner=self.workspace_manager.test_runner,
            edit_synthesizer=self.edit_synthesizer,
            llm_gateway=llm_gateway,
        )
        self.requirement_verifier = RequirementToCodeVerifier()
        self.static_scanner = BuiltinStaticBugScanner()
        self.checkpoint_manager = ExecutionCheckpointManager()
        self.budget_manager = ExecutionBudgetManager()
        self.recovery_service = ExecutionRecoveryService()
        self.report_generator = TaskExecutionReportGenerator()

    @staticmethod
    def _ensure_tools_registered(
        router: ToolRouter,
        workspace_manager: WorkspaceManager,
    ) -> WorkspaceToolPolicyBridge:
        existing_names = {t.name for t in router.get_tools()}
        if "read_file" not in existing_names:
            return register_workspace_tools(router, workspace_manager)
        return WorkspaceToolPolicyBridge(workspace_manager)

    @staticmethod
    def _normalize_workspace_base_revision(repository_id: Any, base_revision: str | None) -> str:
        """Ensure WorkspaceCreateRequest receives a valid 7-64 char hex commit SHA."""
        cleaned = (base_revision or "").strip()
        if _HEX_SHA_RE.match(cleaned):
            return cleaned
        return hashlib.sha256(f"{repository_id}:{cleaned or 'main'}".encode("utf-8")).hexdigest()[:40]

    def ensure_workspace_loaded(
        self,
        task: AgentTask,
        task_repo: TaskRepository | None = None,
    ) -> WorkspaceMetadata | None:
        """Ensure in-memory WorkspaceManager is synchronized with the database Workspace record if present."""
        task_id_str = str(task.id)
        meta = self.workspace_manager.get_workspace(task_id_str)
        if meta is not None:
            return meta
        if task_repo is None:
            return None

        db_ws = task_repo.get_workspace_record(task.id)
        if db_ws is None:
            return None

        branch_name = db_ws.task_branch or format_agent_branch_name(task.id)
        ws_path = Path(db_ws.workspace_path)
        if not (ws_path / ".git").exists():
            return None

        ws_base_rev = self._normalize_workspace_base_revision(
            task.repository_id,
            db_ws.base_revision or task.base_revision or "main",
        )
        # Reconcile existing workspace directory on disk WITHOUT wiping files (_safe_remove_dir)
        meta: WorkspaceMetadata | None = None
        if ws_path.exists() and any(ws_path.iterdir()):
            try:
                self.workspace_manager.reconcile_workspace(task_id_str)
                meta = self.workspace_manager.get_workspace(task_id_str)
            except Exception:
                meta = None
            if meta is None:
                meta = WorkspaceMetadata(
                    workspace_id=str(db_ws.id),
                    task_id=task_id_str,
                    repository_id=str(task.repository_id),
                    base_revision=ws_base_rev,
                    branch_name=branch_name,
                    workspace_path=str(ws_path.resolve()),
                    status=WorkspaceStatus.IN_USE,
                    isolation_type="directory_copy",
                )
                self.workspace_manager._workspaces[task_id_str] = meta

        target_status_str = (db_ws.status or "READY").upper()
        try:
            target_ws_status = WorkspaceStatus(target_status_str)
            if meta.status != target_ws_status and target_ws_status in (
                WorkspaceStatus.IN_USE,
                WorkspaceStatus.STOPPED,
                WorkspaceStatus.FAILED,
            ):
                meta.status = target_ws_status
        except ValueError:
            pass
        return meta

    # -----------------------------------------------------------------------
    # Day 3 & Day 4 — Execution, Tool Routing, Test Runner & Bounded Repair
    # -----------------------------------------------------------------------

    def start_task_execution(
        self,
        task: AgentTask,
        task_repo: TaskRepository,
        actor_id: UUID | None = None,
        *,
        dry_run: bool = False,
        run_steps: bool = False,
        step_payloads: Mapping[str, Any] | None = None,
        run_tests_after: bool = False,
        auto_repair: bool = False,
    ) -> tuple[AgentTask, WorkspaceMetadata, AgentExecutionResult | None]:
        """Validate approval gate, provision isolated workspace, and optionally execute plan steps."""
        verified_plan = task_repo.verify_execution_approval_gate(task)
        task_id_str = str(task.id)
        branch_name = format_agent_branch_name(task.id)
        base_rev = verified_plan.base_revision or task.base_revision or "main"
        if not _COMMIT_SHA_RE.fullmatch(base_rev):
            raise APIError(409, ErrorCode.PLAN_VERSION_MISMATCH, "Regenerate the plan against a full indexed commit SHA, then approve the new version.")
        settings = get_settings()
        if settings.sandbox_backend == "runner" and not settings.task_workspace_root:
            raise APIError(503, ErrorCode.SERVICE_UNAVAILABLE, "Configure TASK_WORKSPACE_ROOT on the API and runner before executing repository tasks.")

        # 1. Transition APPROVED -> WORKSPACE_SETUP if not already past it
        if TaskStatus(task.status) == TaskStatus.APPROVED:
            task_repo.transition_status(
                task,
                TaskStatus.WORKSPACE_SETUP,
                actor_id=actor_id,
                event_type="EXECUTION_GATE_PASSED",
                summary=(
                    f"Approval gate verified for plan v{verified_plan.plan_version} "
                    f"(hash {verified_plan.plan_hash[:12]}). Entering WORKSPACE_SETUP."
                ),
                payload={
                    "approved_plan_version": verified_plan.plan_version,
                    "plan_hash": verified_plan.plan_hash,
                    "base_revision": base_rev,
                    "branch_name": branch_name,
                },
            )

        # 2. Provision isolated workspace in WorkspaceManager and persist in DB
        try:
            meta = self.workspace_manager.get_workspace(task_id_str)
            if meta is None or meta.status in (WorkspaceStatus.CLEANED, WorkspaceStatus.FAILED):
                create_req = WorkspaceCreateRequest(
                    task_id=task_id_str,
                    repository_id=str(task.repository_id),
                    base_revision=base_rev,
                    branch_name=branch_name,
                    isolation_type="directory_copy",
                )
                repo = self._publication_repository(task)
                token = asyncio.run(GitBranchService(task_repo.session).get_installation_token_for_repo(repo))
                meta = self.workspace_manager.create_workspace(
                    create_req, repository_url=f"https://github.com/{repo.owner}/{repo.name}.git", installation_token=token,
                )
            if meta.base_revision != base_rev or meta.branch_name != branch_name:
                raise WorkspaceCommitError("Workspace is bound to a different approved commit or branch.")

            task_repo.record_workspace(
                task_id=task.id,
                repository_id=task.repository_id,
                workspace_path=meta.workspace_path or str(self.workspace_manager.base_directory / task_id_str),
                task_branch=meta.branch_name,
                base_revision=meta.base_revision,
                status=DBWorkspaceStatus.READY if dry_run else DBWorkspaceStatus.IN_USE,
            )
        except Exception as exc:
            task_repo.transition_status(
                task,
                TaskStatus.FAILED,
                actor_id=actor_id,
                event_type="EXECUTION_FAILED",
                summary=f"Workspace provisioning failed: {redact(str(exc))}",
            )
            raise APIError(
                500,
                ErrorCode.WORKSPACE_CREATION_FAILED,
                f"Failed to provision isolated workspace: {redact(str(exc))}",
            ) from exc

        if dry_run:
            return task, meta, None

        # 3. Start execution inside WorkspaceManager (READY -> IN_USE)
        start_req = WorkspaceStartExecutionRequest(
            task_id=task_id_str,
            task_status="APPROVED",
            plan_version=verified_plan.plan_version,
            approved_base_revision=meta.base_revision,
        )
        self.workspace_manager.start_execution(start_req)

        # Transition task WORKSPACE_SETUP -> EXECUTING if run_steps is requested
        exec_result: AgentExecutionResult | None = None
        if run_steps:
            if TaskStatus(task.status) == TaskStatus.WORKSPACE_SETUP:
                task_repo.transition_status(
                    task,
                    TaskStatus.EXECUTING,
                    actor_id=actor_id,
                    event_type="EXECUTION_STARTED",
                    summary=f"Started executing plan v{verified_plan.plan_version} on branch '{meta.branch_name}'.",
                )

            exec_attempt = TaskExecution(
                task_id=task.id,
                attempt_number=len(task.executions or []) + 1,
                worker_id="orchestrator-local",
                status=ExecutionStatus.RUNNING.value,
            )
            task_repo.session.add(exec_attempt)
            task_repo.session.commit()

            exec_result = self.execution_loop.execute_plan(
                task_id=task_id_str,
                plan=verified_plan.steps or [],
                step_payloads=step_payloads,
            )

            completed_step_ids: list[str] = []
            for step_rec in exec_result.steps_executed:
                task_repo.record_tool_invocation(
                    task_id=task.id,
                    repository_id=task.repository_id,
                    tool_name=f"step:{step_rec.action_type}",
                    arguments={"step_id": step_rec.step_id, "files": step_rec.target_files},
                    status=(
                        ToolInvocationStatus.COMPLETED
                        if step_rec.status == StepExecutionStatus.COMPLETED
                        else ToolInvocationStatus.FAILED
                    ),
                    duration_ms=int(step_rec.duration_ms),
                    output_summary=redact(str(step_rec.output or step_rec.error_message or "")),
                )
                if step_rec.status == StepExecutionStatus.COMPLETED:
                    completed_step_ids.append(step_rec.step_id)
                    try:
                        self.checkpoint_manager.save_checkpoint(
                            task_id=task_id_str,
                            step_id=step_rec.step_id,
                            workspace_revision=meta.base_revision or "main",
                            completed_step_ids=completed_step_ids,
                            completed_requirement_ids=[step_rec.step_id],
                            verified_files=step_rec.target_files,
                        )
                        self.budget_manager.record_step_attempt(step_rec.step_id)
                        for f in step_rec.target_files:
                            self.budget_manager.record_file_modification(f)
                    except Exception as err:
                        logger.debug("Non-fatal checkpoint/budget recording: %s", err)

            if exec_result.status in (StepExecutionStatus.FAILED, StepExecutionStatus.LOOP_DETECTED):
                exec_attempt.status = ExecutionStatus.FAILED.value
                exec_attempt.completed_at = datetime.now(timezone.utc)
                exec_attempt.error_message = redact(exec_result.error_message or "Step execution failed")
                task.error_message = exec_attempt.error_message
                task_repo.transition_status(
                    task,
                    TaskStatus.FAILED,
                    actor_id=actor_id,
                    event_type="EXECUTION_FAILED",
                    summary=exec_attempt.error_message,
                )
                return task, meta, exec_result

            exec_attempt.status = ExecutionStatus.COMPLETED.value
            exec_attempt.completed_at = datetime.now(timezone.utc)
            task_repo.session.commit()

            if run_tests_after:
                test_res = self.execute_task_tests(
                    task=task,
                    task_repo=task_repo,
                    actor_id=actor_id,
                )
                if test_res.status != TestOutcomeStatus.PASSED and auto_repair:
                    self.execute_bounded_repair(
                        task=task,
                        task_repo=task_repo,
                        actor_id=actor_id,
                    )

        return task, meta, exec_result

    def pause_task_execution(
        self,
        task: AgentTask,
        task_repo: TaskRepository,
        actor_id: UUID | None = None,
        reason: str = "Paused by operator.",
    ) -> WorkspaceMetadata:
        """Pause an active workspace execution (IN_USE -> STOPPED)."""
        meta = self.ensure_workspace_loaded(task, task_repo)
        if meta is None:
            raise APIError(404, ErrorCode.NOT_FOUND, f"No workspace initialized for task '{task.id}'.")

        try:
            if meta.status == WorkspaceStatus.READY:
                self.workspace_manager.transition_state(str(task.id), WorkspaceStatus.IN_USE)
            updated_meta = self.workspace_manager.pause_execution(str(task.id), reason=reason)
        except WorkspaceStateError as exc:
            raise APIError(409, ErrorCode.INVALID_STATE_TRANSITION, str(exc)) from exc

        db_ws = task_repo.get_workspace_record(task.id)
        if db_ws is not None:
            db_ws.status = DBWorkspaceStatus.STOPPED.value
        task_repo.record_event(
            task_id=task.id,
            repository_id=task.repository_id,
            event_type="EXECUTION_PAUSED",
            event_data={"reason": redact(reason), "workspace_status": updated_meta.status.value},
            user_id=actor_id,
            summary=f"Workspace execution paused: {redact(reason)}",
        )
        task_repo.session.commit()
        return updated_meta

    def resume_task_execution(
        self,
        task: AgentTask,
        task_repo: TaskRepository,
        actor_id: UUID | None = None,
    ) -> WorkspaceMetadata:
        """Resume a paused workspace execution (STOPPED -> IN_USE)."""
        task_repo.verify_execution_approval_gate(task)
        meta = self.ensure_workspace_loaded(task, task_repo)
        if meta is None:
            raise APIError(404, ErrorCode.NOT_FOUND, f"No workspace initialized for task '{task.id}'.")

        try:
            if meta.status == WorkspaceStatus.READY:
                updated_meta = self.workspace_manager.transition_state(str(task.id), WorkspaceStatus.IN_USE)
            else:
                updated_meta = self.workspace_manager.resume_execution(str(task.id))
        except WorkspaceStateError as exc:
            raise APIError(409, ErrorCode.INVALID_STATE_TRANSITION, str(exc)) from exc

        db_ws = task_repo.get_workspace_record(task.id)
        if db_ws is not None:
            db_ws.status = DBWorkspaceStatus.IN_USE.value
        task_repo.record_event(
            task_id=task.id,
            repository_id=task.repository_id,
            event_type="EXECUTION_RESUMED",
            event_data={"workspace_status": updated_meta.status.value},
            user_id=actor_id,
            summary="Workspace execution resumed.",
        )
        task_repo.session.commit()
        return updated_meta

    def invoke_workspace_tool(
        self,
        task: AgentTask,
        task_repo: TaskRepository,
        tool_name: str,
        arguments: dict[str, Any],
        actor_id: UUID | None = None,
    ) -> ToolResult:
        """Route a tool invocation through ToolRouter & WorkspaceToolPolicyBridge and persist audit log."""
        # ISS-034 / security ordering: Check API tool policy FIRST so blocked tools always
        # return 403 COMMAND_NOT_ALLOWED / TOOL_BLOCKED regardless of task state.
        # (verify_execution_approval_gate comes after, so state errors don't mask security decisions.)
        from app.core.tool_api_policy import api_tool_policy_violation

        violation = api_tool_policy_violation(
            tool_name,
            arguments or {},
            DEFAULT_COMMAND_ALLOWLIST.get("execute_command", []),
        )
        if violation is not None:
            code, reason = violation
            reason = redact(reason)
            task_repo.record_tool_invocation(
                task_id=task.id,
                repository_id=task.repository_id,
                tool_name=tool_name,
                arguments=redact_obj(dict(arguments or {})),
                status=ToolInvocationStatus.BLOCKED,
                duration_ms=0,
                output_summary=f"Blocked by API tool policy: {reason}",
            )
            raise APIError(403, code, reason)

        # State gate: lighter tool-invocation gate (allows FAILED tasks for diagnostics/repair).
        task_repo.verify_tool_invocation_gate(task)

        # F19: Human approval gate for tools with risk tier >= write-external (or high/critical)
        tool_risk: str | None = None
        if hasattr(self.tool_router, "registry") and self.tool_router.registry:
            entry = self.tool_router.registry.get_entry(tool_name)
            if entry and entry.definition:
                tool_risk = entry.definition.risk_tier
        if not tool_risk:
            tool_risk = CANONICAL_TOOL_METADATA.get(tool_name, {}).get("risk_tier")

        from app.services.tool_approval_gate import tool_approval_gate_service
        try:
            tool_approval_gate_service.verify_and_consume_tool(
                session=task_repo.session,
                task=task,
                tool_name=tool_name,
                arguments=arguments,
                user_id=actor_id,
                risk_tier=tool_risk,
            )
        except APIError as exc:
            task_repo.record_tool_invocation(
                task_id=task.id,
                repository_id=task.repository_id,
                tool_name=tool_name,
                arguments=redact_obj(dict(arguments or {})),
                status=ToolInvocationStatus.BLOCKED,
                duration_ms=0,
                output_summary=f"Blocked by tool approval gate: {exc.message}",
            )
            raise

        meta = self.ensure_workspace_loaded(task, task_repo)
        if meta is None:
            raise APIError(409, ErrorCode.INVALID_STATE_TRANSITION, "Workspace must be initialized before invoking tools.")

        if meta.status == WorkspaceStatus.READY:
            self.workspace_manager.transition_state(str(task.id), WorkspaceStatus.IN_USE)

        # Enforce task-level forbidden_files constraint on write/patch/delete tools
        if tool_name in ("write_file", "patch_file", "delete_file"):
            target_fp = str(arguments.get("file_path", "")).strip().replace("\\", "/").lstrip("./")
            forbidden_lower: set[str] = set()
            for cst in task.constraints or []:
                if isinstance(cst, dict):
                    for f_path in cst.get("forbidden_files", []) or []:
                        forbidden_lower.add(str(f_path).strip().replace("\\", "/").lstrip("./").lower())
            if target_fp.lower() in forbidden_lower:
                task_repo.record_tool_invocation(
                    task_id=task.id,
                    repository_id=task.repository_id,
                    tool_name=tool_name,
                    arguments=arguments,
                    status=ToolInvocationStatus.BLOCKED,
                    duration_ms=0,
                    output_summary=f"Blocked modification of protected file '{target_fp}'.",
                )
                raise APIError(
                    403,
                    ErrorCode.POLICY_VIOLATION,
                    f"Tool '{tool_name}' blocked: file '{target_fp}' is protected by task constraints.",
                )

        start_perf = time.perf_counter()
        req = ToolRequest(tool_name=tool_name, arguments=arguments)
        res = self.tool_router.route(req, agent_state={"task_id": str(task.id)})
        elapsed_ms = int((time.perf_counter() - start_perf) * 1000)

        tool_entry = getattr(self.tool_router, "registry", None)
        defn = tool_entry.get(tool_name) if tool_entry else None

        if getattr(res, "timed_out", False) or getattr(res, "error_category", None) == "TIMEOUT_ERROR":
            inv_status = ToolInvocationStatus.TIMEOUT
        elif getattr(res, "rate_limited", False) or getattr(res, "error_category", None) == "RATE_LIMIT_ERROR":
            inv_status = ToolInvocationStatus.RATE_LIMITED
        elif res.success:
            inv_status = ToolInvocationStatus.COMPLETED
        else:
            inv_status = ToolInvocationStatus.BLOCKED

        task_repo.record_tool_invocation(
            task_id=task.id,
            repository_id=task.repository_id,
            tool_name=tool_name,
            arguments=arguments,
            status=inv_status,
            duration_ms=getattr(res, "duration_ms", None) or elapsed_ms,
            output_summary=redact(str(res.output if res.success else res.error)),
            tool_version=getattr(defn, "version", "1.0.0"),
            tool_source=getattr(defn, "source", "builtin"),
            risk_tier=getattr(defn, "risk_tier", "low"),
            schema_fingerprint=getattr(defn, "schema_fingerprint", None),
            execution_timeout_s=int(getattr(defn, "timeout_s", 60.0)) if getattr(defn, "timeout_s", None) else None,
            execution_timed_out=bool(getattr(res, "timed_out", False)),
            rate_limit_status="LIMITED" if getattr(res, "rate_limited", False) else "OK",
            error_category=getattr(res, "error_category", None),
        )

        if not res.success:
            err_msg = res.error or "Tool execution denied by policy."
            if "command" in err_msg.lower() and "allowlist" in err_msg.lower():
                raise APIError(403, ErrorCode.COMMAND_NOT_ALLOWED, err_msg)
            raise APIError(403, ErrorCode.POLICY_VIOLATION, err_msg)

        return res

    def execute_task_tests(
        self,
        task: AgentTask,
        task_repo: TaskRepository,
        actor_id: UUID | None = None,
        *,
        test_path: str | None = None,
        framework: str | None = None,
        arguments: list[str] | None = None,
        timeout_seconds: int = 60,
        collect_coverage: bool = True,
        junit_xml: bool = True,
        sandbox_backend: str | None = None,
    ) -> WorkspaceTestExecutionResult:
        """Run restricted test suite inside the task workspace and persist TestRun in DB."""
        # Sukun W3 Day 4 / ISS-034: extra test-runner arguments come from API callers.
        # Validate arguments FIRST (before state gate) so unsafe args always get 403,
        # regardless of task state — prevents state-ordering bypass of security check.
        if arguments:
            from app.core.tool_api_policy import argv_safety_error

            arg_error = argv_safety_error([str(item) for item in arguments])
            if arg_error:
                raise APIError(403, ErrorCode.COMMAND_NOT_ALLOWED, redact(arg_error))

        # Use lighter tool-invocation gate: running tests on FAILED tasks is allowed for repair.
        task_repo.verify_tool_invocation_gate(task)

        meta = self.ensure_workspace_loaded(task, task_repo)
        if meta is None:
            raise APIError(404, ErrorCode.NOT_FOUND, f"No workspace found for task '{task.id}'.")

        if meta.status == WorkspaceStatus.READY:
            self.workspace_manager.transition_state(str(task.id), WorkspaceStatus.IN_USE)

        curr_status = TaskStatus(task.status)
        if curr_status in (TaskStatus.WORKSPACE_SETUP, TaskStatus.APPROVED):
            task_repo.transition_status(task, TaskStatus.EXECUTING, actor_id=actor_id)
        if TaskStatus(task.status) in (TaskStatus.EXECUTING, TaskStatus.REPAIRING):
            task_repo.transition_status(task, TaskStatus.TESTING, actor_id=actor_id)

        test_req = WorkspaceTestExecutionRequest(
            task_id=str(task.id),
            framework=framework,  # type: ignore[arg-type]
            test_path=test_path,
            arguments=arguments or [],
            timeout_seconds=timeout_seconds,
            collect_coverage=collect_coverage,
            junit_xml=junit_xml,
            sandbox_backend=sandbox_backend,
        )
        tested_diff = self.workspace_manager.compute_verification_diff_hash(str(task.id), record=False)
        result = self.workspace_manager.run_tests(test_req)

        db_status = TestRunStatus.PASSED.value
        if result.status == TestOutcomeStatus.TIMEOUT or result.timed_out:
            db_status = TestRunStatus.TIMED_OUT.value
        elif result.status in (TestOutcomeStatus.ERROR, TestOutcomeStatus.UNSUPPORTED_FRAMEWORK):
            db_status = TestRunStatus.ERROR.value
        elif result.status == TestOutcomeStatus.NO_TESTS_FOUND:
            db_status = TestRunStatus.FAILED.value
        elif result.status != TestOutcomeStatus.PASSED:
            db_status = TestRunStatus.FAILED.value
        if self.workspace_manager.compute_verification_diff_hash(str(task.id), record=False) != tested_diff:
            db_status = TestRunStatus.FAILED.value
            result.status = TestOutcomeStatus.ERROR
            result.success = False
            result.stderr = f"{result.stderr}\nWorkspace changes differ from the input to the test run.".strip()

        cmd_str = shlex.join([result.command, *result.arguments])
        combined_output = f"{result.stdout}\n{result.stderr}".strip()
        task_repo.record_test_run(
            task_id=task.id,
            repository_id=task.repository_id,
            command=cmd_str,
            status=db_status,
            exit_code=result.exit_code,
            duration_ms=int(result.duration_ms),
            tests_total=result.total_count,
            tests_passed=result.passed_count,
            tests_failed=result.failed_count,
            sanitized_output=combined_output[:10_000],
            target_revision=f"diff-sha256:{tested_diff}",
        )
        return result

    def execute_bounded_repair(
        self,
        task: AgentTask,
        task_repo: TaskRepository,
        actor_id: UUID | None = None,
        *,
        framework: str = "pytest",
        test_path: str | None = None,
        patch_diff: str | None = None,
        patch_explanation: str | None = None,
        target_files: list[str] | None = None,
    ) -> BoundedRepairOutcome:
        """Execute bounded self-repair (max 3 attempts) and synchronize DB RepairAttempt & Task state."""
        # Use lighter tool-invocation gate: bounded repair runs on tasks in FAILED state.
        task_repo.verify_tool_invocation_gate(task)
        meta = self.ensure_workspace_loaded(task, task_repo)
        if meta is None:
            raise APIError(404, ErrorCode.NOT_FOUND, f"No workspace found for task '{task.id}'.")

        if meta.status == WorkspaceStatus.READY:
            self.workspace_manager.transition_state(str(task.id), WorkspaceStatus.IN_USE)

        if task.repair_attempts_used >= task.repair_attempts_max:
            raise APIError(
                409,
                ErrorCode.RETRY_BUDGET_EXHAUSTED,
                f"Repair budget exhausted ({task.repair_attempts_used}/{task.repair_attempts_max} attempts used).",
            )

        forbidden_files: list[str] = []
        for cst in task.constraints or []:
            if isinstance(cst, dict):
                forbidden_files.extend(str(f) for f in (cst.get("forbidden_files") or []))

        curr_status = TaskStatus(task.status)
        if curr_status == TaskStatus.TESTING:
            task_repo.transition_status(task, TaskStatus.REPAIRING, actor_id=actor_id)

        remaining = max(1, task.repair_attempts_max - task.repair_attempts_used)
        approved_plan = task_repo.get_approved_plan(task.id)

        def _custom_synthesizer(t_id: str, attempt_num: int, diag: Any) -> RepairPatchPayload:
            if patch_diff:
                files = list(target_files or [])
                if not files and diag.failures and diag.failures[0].file_path:
                    files = [diag.failures[0].file_path]
                return RepairPatchPayload(
                    task_id=t_id,
                    attempt_number=attempt_num,
                    diff=patch_diff,
                    explanation=patch_explanation or f"Targeted repair attempt {attempt_num}",
                    target_files=files,
                )
            return self.repair_loop._synthesize_patch(t_id, attempt_num, diag)

        outcome = self.repair_loop.run_repair_cycle(
            task_id=str(task.id),
            framework=framework,
            test_path=test_path,
            patch_synthesizer=_custom_synthesizer if patch_diff else None,
            forbidden_files=forbidden_files,
            plan_scope_files=approved_plan.expected_files if approved_plan else None,
            attempt_limit=remaining,
        )

        # Persist each repair record in DB
        for rec in outcome.repair_records:
            attempt_obj, avail = task_repo.increment_repair_attempt(
                task_id=task.id,
                repository_id=task.repository_id,
                failure_classification="TEST_FAILURE",
                diagnosis=outcome.final_output_summary,
                applied_patch=rec.patch_summary,
            )
            if not rec.success and not avail:
                break
            if not rec.success:
                attempt_obj.result = RepairResult.FAILED.value
                task_repo.session.commit()

            try:
                self.workspace_manager.test_runner.record_repair_attempt(
                    task_id=str(task.id),
                    patch_summary=rec.patch_summary,
                    patch_content=f"{rec.patch_hash or rec.attempt_number}",
                    workspace_revision=meta.base_revision,
                    test_status_before=rec.test_status_before,
                    test_status_after=rec.test_status_after,
                    success=rec.success,
                )
            except (WorkspaceRepairBudgetExhaustedError, WorkspaceDuplicateRepairPatchError):
                pass

        if outcome.success:
            if TaskStatus(task.status) == TaskStatus.REPAIRING:
                task_repo.transition_status(
                    task,
                    TaskStatus.TESTING,
                    actor_id=actor_id,
                    summary=f"Bounded self-repair succeeded on attempt {outcome.attempts_used}.",
                )
        elif task.repair_attempts_used >= task.repair_attempts_max or outcome.budget_exhausted:
            task.error_message = redact(outcome.error_message or "Repair budget exhausted (3/3 attempts).")
            if TaskStatus(task.status) != TaskStatus.FAILED:
                task_repo.transition_status(
                    task,
                    TaskStatus.FAILED,
                    actor_id=actor_id,
                    event_type="RETRY_BUDGET_EXHAUSTED",
                    summary=task.error_message,
                )
                try:
                    from app.services.memory_service import ProjectMemoryService
                    mem_svc = ProjectMemoryService(task_repo.session)
                    mem_svc.record_task_failure_memory(
                        repository_id=task.repository_id,
                        task_id=task.id,
                        title=task.title or f"Task {task.id}",
                        failure_reason=task.error_message or "Repair budget exhausted",
                        repair_attempts_used=task.repair_attempts_used,
                    )
                except Exception as mem_err:
                    logger.debug("Project memory repair failure recording skipped: %s", mem_err)

        return outcome

    # -----------------------------------------------------------------------
    # Day 5 — Independent Verification & Week 2 Static/AI Review Integration (F36)
    # -----------------------------------------------------------------------

    def _resolve_verified_revision_sha(
        self,
        task_id_str: str,
        meta: WorkspaceMetadata,
        diff_hash: str,
    ) -> str:
        """Resolve a valid 7-64 char hexadecimal commit SHA or diff fingerprint for VerificationResult."""
        ws_path = Path(meta.workspace_path)
        if (ws_path / ".git").exists():
            try:
                proc = subprocess.run(
                    ["git", "-C", str(ws_path), "rev-parse", "HEAD"],
                    capture_output=True,
                    text=True,
                    check=False,
                    timeout=5,
                )
                head_sha = proc.stdout.strip()
                if _HEX_SHA_RE.match(head_sha):
                    return head_sha
            except Exception as exc:
                logger.debug("Failed to resolve git HEAD rev-parse in workspace: %s", exc)
        if meta.base_revision and _HEX_SHA_RE.match(meta.base_revision.strip()):
            return meta.base_revision.strip()
        return diff_hash[:40]

    def _commit_verified_diff(
        self, task: AgentTask, task_repo: TaskRepository, diff: WorkspaceDiffResult, diff_hash: str,
    ) -> str:
        task_id = str(task.id)
        if self.workspace_manager.compute_verification_diff_hash(task_id, record=False) != diff_hash:
            raise WorkspaceCommitError("Workspace changed while verification was running.")
        commit = self.commit_workspace_changes(task, task_repo, files=[file.file_path for file in diff.files])
        self._require_workspace_commit(task_id, commit.branch, commit.commit_sha)
        if self.workspace_manager.compute_verification_diff_hash(task_id, record=False) != diff_hash:
            raise WorkspaceCommitError("The commit diff differs from the reviewed working tree.")
        return commit.commit_sha

    def _require_workspace_commit(self, task_id: str, branch: str, revision: str) -> None:
        workspace = self.workspace_manager.get_workspace_path(task_id)

        def git(*args: str) -> str:
            result = subprocess.run(
                ["git", "-c", "core.fsmonitor=false", "-C", str(workspace), *args],
                check=True, capture_output=True, text=True, timeout=10,
            )
            return result.stdout.strip()

        if (
            not _COMMIT_SHA_RE.fullmatch(revision or "")
            or git("symbolic-ref", "--quiet", "--short", "HEAD") != branch
            or git("rev-parse", "HEAD") != revision
            or git("status", "--porcelain", "--untracked-files=all")
        ):
            raise WorkspaceCommitError("The workspace must be clean and checked out at the verified task commit.")

    def run_independent_verification(
        self,
        task: AgentTask,
        task_repo: TaskRepository,
        actor_id: UUID | None = None,
        *,
        run_tests_if_missing: bool = False,
        require_passing_tests: bool = True,
        allow_critical_deletions: bool = False,
        strict_scope: bool = True,
    ) -> VerificationResultSchema:
        """Execute independent multi-dimensional verification over the workspace changes (Docs/week3.md §6 F36).

        Evaluates 5 independent gates:
        1. `tests`: Verifies test execution results in the workspace.
        2. `diff_scope`: Verifies modified files against the approved plan and critical manifest deletion rules.
        3. `secret_scan`: Scans all added diff lines for leaked credentials/keys.
        4. `static_analysis`: Runs Week 2 `BuiltinStaticBugScanner` & `ASTBugAnalyzer` on modified files.
        5. `ai_code_review`: Runs Meet's `RequirementToCodeVerifier` and Week 2 review checks on the diff.
        """
        verified_plan = task_repo.verify_execution_approval_gate(task)
        meta = self.ensure_workspace_loaded(task, task_repo)
        if meta is None:
            raise APIError(
                409,
                ErrorCode.INVALID_STATE_TRANSITION,
                "Cannot run independent verification before isolated workspace is initialized.",
            )

        if meta.status == WorkspaceStatus.READY:
            self.workspace_manager.transition_state(str(task.id), WorkspaceStatus.IN_USE)

        task_id_str = str(task.id)

        # Transition task into VERIFYING state following valid state graph
        curr_status = TaskStatus(task.status)
        if curr_status == TaskStatus.FAILED:
            task_repo.transition_status(task, TaskStatus.RECOVERY_REQUIRED, actor_id=actor_id)
            curr_status = TaskStatus.RECOVERY_REQUIRED
        if curr_status == TaskStatus.APPROVED:
            task_repo.transition_status(task, TaskStatus.WORKSPACE_SETUP, actor_id=actor_id)
            curr_status = TaskStatus.WORKSPACE_SETUP
        if curr_status == TaskStatus.WORKSPACE_SETUP:
            task_repo.transition_status(task, TaskStatus.EXECUTING, actor_id=actor_id)
            curr_status = TaskStatus.EXECUTING
        if curr_status in (TaskStatus.EXECUTING, TaskStatus.REPAIRING):
            task_repo.transition_status(task, TaskStatus.TESTING, actor_id=actor_id)
            curr_status = TaskStatus.TESTING
        if curr_status in (
            TaskStatus.TESTING,
            TaskStatus.READY_FOR_PUBLICATION,
            TaskStatus.BLOCKED,
            TaskStatus.RECOVERY_REQUIRED,
        ):
            task_repo.transition_status(task, TaskStatus.VERIFYING, actor_id=actor_id)

        checks: list[VerificationCheckItem] = []
        blocking_findings: list[VerificationFinding] = []
        warnings: list[VerificationFinding] = []

        # ── Check 1: Test Suite Execution Outcome (`tests`) ─────────────────
        t0 = time.perf_counter()
        db_runs = task_repo.list_test_runs(task.id)
        tested_diff = self.workspace_manager.compute_verification_diff_hash(task_id_str, record=False)
        target_revision = f"diff-sha256:{tested_diff}"
        if run_tests_if_missing and (not db_runs or db_runs[-1].target_revision != target_revision):
            self.execute_task_tests(task=task, task_repo=task_repo, actor_id=actor_id)
            db_runs = task_repo.list_test_runs(task.id)

        latest_run = db_runs[-1] if db_runs else None
        tests_passed = bool(
            latest_run
            and latest_run.target_revision == target_revision
            and latest_run.status == TestRunStatus.PASSED.value
            and latest_run.exit_code == 0
            and latest_run.tests_passed > 0
            and latest_run.tests_failed == 0
        )
        if tests_passed:
            test_status = "PASSED"
            test_message = f"Test suite passed ({latest_run.tests_passed}/{latest_run.tests_total} tests passed)."
        elif require_passing_tests or latest_run:
            test_status = "FAILED"
            test_message = (
                f"Latest test run: {latest_run.status}, {latest_run.tests_passed} passed, "
                f"{latest_run.tests_failed} failed. A passing run for this diff is required."
                if latest_run else "No test run is recorded for this diff."
            )
            blocking_findings.append(
                VerificationFinding(
                    id="ver-test-fail-1",
                    severity="HIGH",
                    category="test_failure",
                    title="Passing tests for the current changes are required",
                    message=test_message,
                    blocking=True,
                )
            )
        else:
            test_status = "SKIPPED"
            test_message = "No test run is recorded for this diff."
        checks.append(
            VerificationCheckItem(
                name="tests",
                status=test_status,
                duration_ms=int((time.perf_counter() - t0) * 1000),
                message=test_message,
                findings_count=int(test_status == "FAILED"),
                details={"target_revision": latest_run.target_revision} if latest_run else {},
            )
        )

        # ── Check 2 & 3: Diff Scope & Secret Scan (`diff_scope`, `secret_scan`) ─
        t1 = time.perf_counter()
        allowed_files_set: set[str] = set()
        for f in verified_plan.expected_files or []:
            if f:
                allowed_files_set.add(str(f).strip())
        for step in verified_plan.steps or []:
            if isinstance(step, dict):
                for f in step.get("expected_files", []) or []:
                    if f:
                        allowed_files_set.add(str(f).strip())
                for f in step.get("target_files", []) or []:
                    if f:
                        allowed_files_set.add(str(f).strip())
        for req_dict in task.requirements or []:
            if isinstance(req_dict, dict):
                for f in req_dict.get("target_files", []) or []:
                    if f:
                        allowed_files_set.add(str(f).strip())

        diff_res = self.workspace_manager.get_workspace_diff(task_id_str)
        # Allow test files, test reports/coverage artifacts, and markdown docs alongside plan expected files
        effective_allowed: list[str] | None = None
        if strict_scope and allowed_files_set:
            effective_allowed = list(allowed_files_set)
            for df in diff_res.files:
                if (
                    df.file_path.startswith(("tests/", "test/", ".test_reports/"))
                    or df.file_path in (".coverage",)
                    or df.file_path.endswith(".md")
                ):
                    effective_allowed.append(df.file_path)

        diff_val = self.workspace_manager.validate_workspace_diff(
            task_id_str,
            allowed_files=effective_allowed,
            allow_critical_deletions=allow_critical_deletions,
        )
        diff_check_ms = int((time.perf_counter() - t1) * 1000)

        # Forbidden files constraint check
        forbidden_map: dict[str, str] = {}
        for cst in task.constraints or []:
            if isinstance(cst, dict):
                for f_path in cst.get("forbidden_files", []) or []:
                    clean_f = str(f_path).strip().replace("\\", "/").lstrip("./")
                    forbidden_map[clean_f.lower()] = clean_f

        scope_findings_count = 0
        for mod_f in diff_val.modified_files:
            clean_mod = mod_f.strip().replace("\\", "/").lstrip("./")
            if clean_mod.lower() in forbidden_map:
                scope_findings_count += 1
                blocking_findings.append(
                    VerificationFinding(
                        id=f"ver-forbidden-{scope_findings_count}",
                        severity="CRITICAL",
                        category="policy",
                        title=f"Protected file modified: {clean_mod}",
                        message=f"File '{clean_mod}' is protected by task constraints and must not be modified.",
                        file_path=clean_mod,
                        blocking=True,
                    )
                )

        for unapp_f in diff_val.unapproved_files:
            scope_findings_count += 1
            blocking_findings.append(
                VerificationFinding(
                    id=f"ver-scope-{scope_findings_count}",
                    severity="HIGH",
                    category="policy",
                    title=f"Out-of-scope file modification: {unapp_f}",
                    message=f"File '{unapp_f}' is outside the approved implementation plan scope.",
                    file_path=unapp_f,
                    blocking=True,
                )
            )

        for crit_del in diff_val.deleted_critical_files:
            scope_findings_count += 1
            blocking_findings.append(
                VerificationFinding(
                    id=f"ver-crit-del-{scope_findings_count}",
                    severity="CRITICAL",
                    category="policy",
                    title=f"Critical project manifest deleted: {crit_del}",
                    message=f"Deletion of critical project manifest '{crit_del}' is prohibited without explicit authorization.",
                    file_path=crit_del,
                    blocking=True,
                )
            )

        checks.append(
            VerificationCheckItem(
                name="diff_scope",
                status="FAILED" if scope_findings_count > 0 else "PASSED",
                duration_ms=diff_check_ms,
                message=(
                    f"Verified {len(diff_val.modified_files)} modified file(s) against approved plan scope."
                    if scope_findings_count == 0
                    else f"Detected {scope_findings_count} diff scope or manifest policy violation(s)."
                ),
                findings_count=scope_findings_count,
                details={
                    "modified_files": diff_val.modified_files,
                    "unapproved_files": diff_val.unapproved_files,
                    "deleted_critical_files": diff_val.deleted_critical_files,
                },
            )
        )

        secret_findings_count = len(diff_val.secret_findings)
        for idx, sf in enumerate(diff_val.secret_findings, start=1):
            blocking_findings.append(
                VerificationFinding(
                    id=f"ver-secret-{idx}",
                    severity="CRITICAL",
                    category="security",
                    title=f"Credential leak detected ({sf.secret_type})",
                    message=redact(
                        f"Credential or secret pattern '{sf.secret_type}' detected in '{sf.file_path}' at line {sf.line_number}."
                    ),
                    file_path=sf.file_path,
                    line_number=sf.line_number,
                    rule_id="SEC001",
                    blocking=True,
                )
            )

        checks.append(
            VerificationCheckItem(
                name="secret_scan",
                status="FAILED" if secret_findings_count > 0 else "PASSED",
                duration_ms=max(1, diff_check_ms // 2),
                message=(
                    "Zero leaked credentials or secret tokens detected in diff additions."
                    if secret_findings_count == 0
                    else f"Blocked {secret_findings_count} potential secret/credential leak(s) in diff."
                ),
                findings_count=secret_findings_count,
            )
        )

        # ── Check 4: Week 2 Static Analysis (`static_analysis`) ─────────────
        t2 = time.perf_counter()
        ws_root = Path(meta.workspace_path)
        static_blocking_count = 0
        static_warning_count = 0

        for df in diff_res.files:
            change_str = df.change_type.value if hasattr(df.change_type, "value") else str(df.change_type)
            if change_str.lower() == "deleted":
                continue
            if not df.file_path.endswith((".py", ".js", ".ts", ".jsx", ".tsx")):
                continue
            target_file = ws_root / df.file_path
            if not target_file.exists() or not target_file.is_file():
                continue
            try:
                content = target_file.read_text(encoding="utf-8", errors="replace")
            except Exception as exc:
                logger.debug("Failed to read file %s for static scan: %s", target_file, exc)
                continue

            bug_items, _ = self.static_scanner.scan(
                file_path=df.file_path,
                code_content=content,
                base_start_line=1,
                revision=meta.base_revision,
                repository_id=str(task.repository_id),
            )
            for bf in bug_items:
                is_blocking = bf.severity in ("CRITICAL", "HIGH") and bf.category in (
                    "security",
                    "off_by_one",
                    "boundary_condition",
                )
                vf = VerificationFinding(
                    id=f"ver-{bf.id}",
                    severity=bf.severity,
                    category=bf.category,
                    title=redact(bf.title),
                    message=redact(bf.description),
                    file_path=bf.source_reference.file_path,
                    line_number=bf.source_reference.start_line,
                    rule_id=bf.rule_id,
                    blocking=is_blocking,
                )
                if is_blocking:
                    static_blocking_count += 1
                    blocking_findings.append(vf)
                else:
                    static_warning_count += 1
                    warnings.append(vf)

        static_ms = int((time.perf_counter() - t2) * 1000)
        checks.append(
            VerificationCheckItem(
                name="static_analysis",
                status="FAILED" if static_blocking_count > 0 else "PASSED",
                duration_ms=static_ms,
                message=(
                    f"Static AST & security analysis passed ({static_warning_count} non-blocking observation(s))."
                    if static_blocking_count == 0
                    else f"Static analysis found {static_blocking_count} blocking defect(s)."
                ),
                findings_count=static_blocking_count + static_warning_count,
                details={
                    "blocking_count": static_blocking_count,
                    "warning_count": static_warning_count,
                },
            )
        )

        # ── Check 5: Requirement-to-Code & AI Review (`ai_code_review`) ─────
        t3 = time.perf_counter()
        reqs = [TaskRequirement.model_validate(r) for r in (task.requirements or [])]
        csts = [TaskConstraint.model_validate(c) for c in (task.constraints or [])]

        test_info: dict[str, Any] | None = None
        if db_runs:
            latest_run = db_runs[-1]
            test_info = {
                "status": latest_run.status,
                "total": latest_run.tests_total,
                "failed": latest_run.tests_failed,
                "passed": latest_run.tests_passed,
            }
        req_ver = self.requirement_verifier.verify_requirements_against_diff(
            task_id=task_id_str,
            requirements=reqs,
            constraints=csts,
            original_plan=verified_plan,
            final_diff=diff_res,
            test_results=test_info,
        )
        review_ms = int((time.perf_counter() - t3) * 1000)

        review_blocking_count = 0
        for rf in req_ver.findings:
            if rf.blocking:
                review_blocking_count += 1
                if not any(b.file_path == rf.file_path and b.category == rf.category for b in blocking_findings):
                    blocking_findings.append(rf)
            else:
                warnings.append(rf)

        checks.append(
            VerificationCheckItem(
                name="ai_code_review",
                status="FAILED" if review_blocking_count > 0 else "PASSED",
                duration_ms=review_ms,
                message=(
                    f"Requirement-to-code review complete (alignment score: {req_ver.alignment_score * 100:.0f}%, "
                    f"{req_ver.satisfied_count}/{req_ver.total_requirements} requirements satisfied)."
                ),
                findings_count=len(req_ver.findings),
                details={
                    "alignment_score": req_ver.alignment_score,
                    "satisfied_requirements": req_ver.satisfied_requirements,
                    "unmet_requirements": req_ver.unmet_requirements,
                    "criteria_evidence": [e.model_dump() for e in req_ver.criteria_evidence],
                },
            )
        )

        # Verification and publication both use the exact commit containing the reviewed diff.
        diff_hash = hashlib.sha256((diff_res.raw_diff or "").encode("utf-8")).hexdigest()
        verified_rev_sha = self._resolve_verified_revision_sha(task_id_str, meta, diff_hash)
        if diff_res.is_empty or diff_res.error or diff_hash != tested_diff:
            blocking_findings.append(
                VerificationFinding(
                    id="ver-diff-integrity",
                    severity="HIGH",
                    category="diff_scope",
                    title="A complete, stable workspace diff is required",
                    message=diff_res.error or "The workspace diff is empty or changed during verification.",
                    blocking=True,
                )
            )
        if not blocking_findings and all(c.status == "PASSED" for c in checks):
            try:
                verified_rev_sha = self._commit_verified_diff(task, task_repo, diff_res, diff_hash)
                meta.verification_diff_hash = diff_hash
                self.workspace_manager._save_metadata_file(meta)
            except (WorkspaceCommitError, APIError, OSError, subprocess.SubprocessError) as exc:
                blocking_findings.append(
                    VerificationFinding(
                        id="ver-commit-integrity",
                        severity="HIGH",
                        category="diff_scope",
                        title="Unable to bind verification to a Git commit",
                        message=redact(str(exc)),
                        blocking=True,
                    )
                )
        elif not blocking_findings:
            blocking_findings.append(
                VerificationFinding(
                    id="ver-required-checks",
                    severity="HIGH",
                    category="diff_scope",
                    title="Required verification evidence is missing",
                    message="Every required check must pass before the workspace can be committed for publication.",
                    blocking=True,
                )
            )

        overall_status: VerificationOverallStatus = VerificationResultSchema.evaluate_status(
            checks=checks,
            blocking_findings=blocking_findings,
            warnings=warnings,
        )

        # Also invoke Dev's IndependentVerifier PR Markdown generator so PR descriptions include full 12-check report
        try:
            dev_verifier = IndependentVerifier()
            dev_ctx = VerificationContext(
                task_id=task_id_str,
                target_branch=meta.branch_name or format_agent_branch_name(task.id),
                base_revision=verified_rev_sha,
                verified_revision=verified_rev_sha,
                diff=diff_res.unified_diff or "diff --git a/workspace b/workspace",
                task_title=task.title,
                task_description=task.description or "",
                plan_approved=task.approved_plan_version is not None,
                approved_plan_version=task.approved_plan_version,
                current_plan_version=task.plan_version,
                allowed_files=effective_allowed,
                forbidden_files=list(forbidden_map.values()) if forbidden_map else None,
                tests_completed=latest_run is not None,
                tests_passed=tests_passed,
                test_revision=verified_rev_sha if tests_passed else None,
                test_count=latest_run.tests_total if latest_run else 0,
                failed_test_count=db_runs[-1].tests_failed if db_runs else 0,
                static_analysis_completed=True,
                ai_review_completed=True,
                requirement_evidence=req_ver.criteria_evidence,
            )
            dev_md = dev_verifier.generate_pr_markdown_summary(
                context=dev_ctx,
                status=overall_status,
                checks=checks,
                blocking_findings=blocking_findings,
                warnings=warnings,
            )
            combined_pr_summary = redact(f"{req_ver.summary_markdown}\n\n{dev_md}".strip())
        except Exception:
            combined_pr_summary = redact(req_ver.summary_markdown)

        ver_schema = VerificationResultSchema(
            task_id=task_id_str,
            verified_revision=verified_rev_sha,
            status=overall_status,
            checks=checks,
            blocking_findings=blocking_findings,
            warnings=warnings,
            pr_summary=combined_pr_summary,
            requirement_evidence=req_ver.criteria_evidence,
        )

        # Persist in PostgreSQL (TaskRepository.record_verification_result transitions task to READY_FOR_PUBLICATION or BLOCKED)
        db_status = (
            VerificationStatus.PASSED.value
            if overall_status == "PASS"
            else (
                VerificationStatus.REQUIRES_HUMAN_REVIEW.value
                if overall_status == "REQUIRES_HUMAN_REVIEW"
                else VerificationStatus.FAILED.value
            )
        )
        task_repo.record_verification_result(
            task_id=task.id,
            repository_id=task.repository_id,
            verified_revision=verified_rev_sha,
            status=db_status,
            checks=[c.model_dump(mode="json") for c in checks],
            blocking_findings=[f.model_dump(mode="json") for f in blocking_findings],
            warnings=[w.model_dump(mode="json") for w in warnings],
            summary=ver_schema.pr_summary,
            diff_hash=diff_hash,
        )

        db_ws = task_repo.get_workspace_record(task.id)
        if db_ws is not None:
            db_ws.current_revision = verified_rev_sha
            task_repo.session.commit()

        # Ensure task status & timeline reflect verification verdict
        required_gates = {"tests", "diff_scope", "secret_scan", "static_analysis", "ai_code_review"}
        evaluated_gates = {c.name: c.status for c in checks}
        all_gates_passed = (
            required_gates.issubset(evaluated_gates.keys())
            and all(evaluated_gates[g] == "PASSED" for g in required_gates)
            and len(blocking_findings) == 0
        )

        if ver_schema.is_eligible_for_publication and all_gates_passed:
            if TaskStatus(task.status) in (TaskStatus.VERIFYING, TaskStatus.BLOCKED):
                task_repo.transition_status(
                    task,
                    TaskStatus.READY_FOR_PUBLICATION,
                    actor_id=actor_id,
                    event_type="VERIFICATION_PASSED",
                    summary=(
                        f"Independent verification passed ({overall_status}) at revision {verified_rev_sha[:12]}. "
                        "Task is READY_FOR_PUBLICATION."
                    ),
                    payload={
                        "verified_revision": verified_rev_sha,
                        "diff_hash": diff_hash,
                        "status": overall_status,
                    },
                )
            # Automatically record task completion memory (F36 / Issue #217)
            try:
                from app.services.memory_service import ProjectMemoryService
                mem_svc = ProjectMemoryService(task_repo.session)
                repair_count = len(task_repo.list_repair_attempts(task.id))
                changed_files = [f for req_d in (task.requirements or []) for f in (req_d.get("target_files") or [])]
                mem_svc.record_task_completion_memory(
                    repository_id=task.repository_id,
                    task_id=task.id,
                    title=task.title or f"Task {task.id}",
                    verification_summary=f"Independent verification passed ({overall_status}) at revision {verified_rev_sha[:12]}.",
                    repair_attempts_used=repair_count,
                    files_changed=changed_files,
                )
            except Exception as mem_err:
                logger.debug("Project memory task completion recording skipped: %s", mem_err)
        else:
            fail_summary = (
                f"Independent verification failed with {len(blocking_findings)} blocking finding(s). "
                "Publication is blocked."
            )
            task.error_message = fail_summary
            if TaskStatus(task.status) in (TaskStatus.VERIFYING, TaskStatus.BLOCKED):
                task_repo.transition_status(
                    task,
                    TaskStatus.FAILED,
                    actor_id=actor_id,
                    event_type="VERIFICATION_FAILED",
                    summary=fail_summary,
                    payload={
                        "verified_revision": verified_rev_sha,
                        "blocking_count": len(blocking_findings),
                    },
                )
            # Automatically record task failure memory (F36 / Issue #217)
            try:
                from app.services.memory_service import ProjectMemoryService
                mem_svc = ProjectMemoryService(task_repo.session)
                repair_count = len(task_repo.list_repair_attempts(task.id))
                mem_svc.record_task_failure_memory(
                    repository_id=task.repository_id,
                    task_id=task.id,
                    title=task.title or f"Task {task.id}",
                    failure_reason=fail_summary,
                    repair_attempts_used=repair_count,
                )
            except Exception as mem_err:
                logger.debug("Project memory task failure recording skipped: %s", mem_err)

        return ver_schema

    # -----------------------------------------------------------------------
    # Day 5 — Branch Isolation, Commit, Authorized Push & Draft PR (F37)
    # -----------------------------------------------------------------------

    def ensure_task_branch(
        self,
        task: AgentTask,
        task_repo: TaskRepository,
        actor_id: UUID | None = None,
        *,
        branch_name: str | None = None,
    ) -> dict[str, Any]:
        """Ensure isolated task branch `agent/task-<id>` exists and reject protected branches."""
        task_repo.verify_execution_approval_gate(task)
        _require_safe_git_ref(branch_name, "branch name")
        target_branch = (branch_name or format_agent_branch_name(task.id)).strip()
        clean_branch = target_branch.removeprefix("refs/heads/").lower()
        if clean_branch in PROTECTED_BRANCHES:
            raise APIError(
                403,
                ErrorCode.POLICY_VIOLATION,
                f"Target branch '{target_branch}' is a protected branch. All agent work must use an isolated feature branch.",
            )

        meta = self.ensure_workspace_loaded(task, task_repo)
        if meta is None:
            _, meta, _ = self.start_task_execution(
                task=task,
                task_repo=task_repo,
                actor_id=actor_id,
                dry_run=False,
                run_steps=False,
            )

        if branch_name and meta.branch_name != target_branch:
            meta.branch_name = target_branch
            db_ws = task_repo.get_workspace_record(task.id)
            if db_ws is not None:
                db_ws.task_branch = target_branch
                task_repo.session.commit()

        return {
            "task_id": str(task.id),
            "repository_id": str(task.repository_id),
            "branch_name": meta.branch_name,
            "base_revision": meta.base_revision,
            "workspace_status": meta.status.value,
            "is_protected": False,
        }

    def commit_workspace_changes(
        self,
        task: AgentTask,
        task_repo: TaskRepository,
        actor_id: UUID | None = None,
        *,
        message: str | None = None,
        branch_name: str | None = None,
        files: list[str] | None = None,
        author_name: str = "AI Platform Agent",
        author_email: str = "agent@ai-platform.local",
    ) -> WorkspaceCommitResult:
        """Stage and commit validated changes on the isolated task branch."""
        task_repo.verify_execution_approval_gate(task)
        _require_safe_git_ref(branch_name, "branch name")
        _require_safe_commit_files(files)
        meta = self.ensure_workspace_loaded(task, task_repo)
        if meta is None:
            raise APIError(409, ErrorCode.INVALID_STATE_TRANSITION, "Workspace must be initialized before committing changes.")

        target_branch = (branch_name or meta.branch_name or format_agent_branch_name(task.id)).strip()
        clean_branch = target_branch.removeprefix("refs/heads/").lower()
        if clean_branch in PROTECTED_BRANCHES:
            raise APIError(
                403,
                ErrorCode.POLICY_VIOLATION,
                f"Direct commits to protected branch '{target_branch}' are prohibited (ADR-010).",
            )

        commit_msg = (message or f"feat(task): implement {task.title}").strip()
        lock = self.workspace_manager.get_task_lock(str(task.id))
        if not lock.acquire(timeout=10):
            raise APIError(409, ErrorCode.CONFLICT, f"Concurrent operation in progress for task '{task.id}'.")

        try:
            # Preserve pre-commit diff hash so committing an already-verified working tree stays valid
            pre_commit_hash = meta.verification_diff_hash
            current_pre_hash = self.workspace_manager.compute_verification_diff_hash(str(task.id), record=False)
            was_immutably_verified = bool(pre_commit_hash and pre_commit_hash == current_pre_hash)

            commit_req = WorkspaceCommitRequest(
                task_id=str(task.id),
                message=commit_msg,
                branch_name=target_branch,
                author_name=author_name,
                author_email=author_email,
                files=files,
            )
            res = self.workspace_manager.commit_task_changes(commit_req)

            if was_immutably_verified:
                # Re-bind diff hash after git commit so post-commit push/PR recognizes the verified commit
                post_commit_hash = self.workspace_manager.compute_verification_diff_hash(str(task.id), record=False)
                if post_commit_hash != pre_commit_hash:
                    logger.warning("verified_workspace_changed_during_commit", extra={"task_id": str(task.id)})

            db_ws = task_repo.get_workspace_record(task.id)
            if db_ws is not None:
                db_ws.current_revision = res.commit_sha
                db_ws.task_branch = res.branch
            task_repo.record_event(
                task_id=task.id,
                repository_id=task.repository_id,
                event_type="CHANGES_COMMITTED",
                event_data={
                    "commit_sha": res.commit_sha,
                    "branch": res.branch,
                    "files_committed": res.files_committed,
                },
                user_id=actor_id,
                summary=f"Committed workspace changes to '{res.branch}' ({res.commit_sha[:8]}).",
            )
            task_repo.session.commit()
            return res
        except WorkspaceProtectedBranchError as exc:
            raise APIError(403, ErrorCode.POLICY_VIOLATION, str(exc)) from exc
        except WorkspaceCommitError as exc:
            raise APIError(400, ErrorCode.INVALID_REQUEST, redact(str(exc))) from exc
        finally:
            lock.release()

    def _assert_verified_and_immutable_for_publication(
        self,
        task: AgentTask,
        task_repo: TaskRepository,
        meta: WorkspaceMetadata,
    ) -> Any:
        """Enforce that independent verification passed and zero post-verification edits occurred."""
        ver = task_repo.get_latest_verification_result(task.id)
        if ver is None:
            raise APIError(
                409,
                ErrorCode.VERIFICATION_FAILED,
                "Task cannot be published before independent verification has been executed.",
            )

        if ver.status not in {VerificationStatus.PASSED.value, "PASS"} or ver.blocking_findings:
            raise APIError(409, ErrorCode.VERIFICATION_FAILED, "Publication requires passing independent verification.")

        try:
            self._require_workspace_commit(str(task.id), meta.branch_name, ver.verified_revision)
        except (WorkspaceCommitError, subprocess.SubprocessError, OSError) as exc:
            raise APIError(409, ErrorCode.VERIFICATION_FAILED, redact(str(exc))) from exc

        expected_hash = next(
            (
                event.event_data.get("diff_hash")
                for event in reversed(task_repo.list_events(task.id))
                if event.event_type == TaskEventType.VERIFICATION_COMPLETED.value
                and isinstance(event.event_data, dict)
                and event.event_data.get("verified_revision") == ver.verified_revision
            ),
            None,
        )
        if not expected_hash:
            raise APIError(
                409,
                ErrorCode.VERIFICATION_FAILED,
                "Verification diff hash is missing or unrecorded. Independent verification must be re-executed before publishing.",
            )
        has_current_test_evidence = any(
            check.get("name") == "tests"
            and check.get("status") == "PASSED"
            and (check.get("details") or {}).get("target_revision") == f"diff-sha256:{expected_hash}"
            for check in (ver.checks or [])
        )
        if not has_current_test_evidence:
            raise APIError(409, ErrorCode.VERIFICATION_FAILED, "Re-run tests and verification for this commit before publishing.")

        imm_check = self.workspace_manager.verify_diff_immutability(
            str(task.id),
            expected_diff_hash=expected_hash,
        )
        if not imm_check.is_immutable:
            raise APIError(
                409,
                ErrorCode.VERIFICATION_FAILED,
                imm_check.error_message
                or "Workspace files were modified after independent verification. Re-run verification before publishing.",
            )

        # Also run a live diff validation to guarantee no secrets or critical deletions slipped in
        diff_val = self.workspace_manager.validate_workspace_diff(str(task.id))
        if len(diff_val.secret_findings) > 0 or len(diff_val.deleted_critical_files) > 0:
            raise APIError(
                409,
                ErrorCode.VERIFICATION_FAILED,
                f"Pre-publication diff check failed: {'; '.join(diff_val.blocking_findings)}",
            )

        return ver

    def _require_publication_authorization(
        self, task: AgentTask, task_repo: TaskRepository, verified_revision: str,
    ) -> None:
        authorization = task_repo.get_latest_publication_authorization(task.id, task.repository_id)
        if not authorization or not authorization.get("user_id") or authorization.get("authorized_head_sha") != verified_revision:
            raise APIError(
                409,
                ErrorCode.PUBLICATION_AUTHORIZATION_REQUIRED,
                "A human must authorize this verified commit before publication.",
            )

    def authorize_verified_publication(
        self, task: AgentTask, task_repo: TaskRepository, actor_id: UUID, head_sha: str, notes: str | None,
    ) -> AgentTask:
        meta = self.ensure_workspace_loaded(task, task_repo)
        if meta is None:
            raise APIError(409, ErrorCode.INVALID_STATE_TRANSITION, "Workspace not found for task.")
        verification = self._assert_verified_and_immutable_for_publication(task, task_repo, meta)
        if head_sha != verification.verified_revision:
            raise APIError(409, ErrorCode.VERIFICATION_FAILED, "The requested SHA differs from the verified commit.")
        return task_repo.authorize_publication(task.id, task.repository_id, head_sha, actor_id, notes)

    @staticmethod
    def _publication_repository(task: AgentTask) -> Any:
        repo = task.repository
        if not repo or not repo.owner or not repo.name or not repo.installation_id:
            raise APIError(409, ErrorCode.INVALID_STATE_TRANSITION, "A connected GitHub App repository is required.")
        return repo

    def push_verified_branch(
        self,
        task: AgentTask,
        task_repo: TaskRepository,
        actor_id: UUID | None = None,
        *,
        publication_authorized: bool = False,
        branch_name: str | None = None,
        remote_name: str = "origin",
        current_remote_head_sha: str | None = None,
        strict_remote: bool = False,
    ) -> WorkspacePushResult:
        """Push exactly the authorized commit to the connected GitHub repository."""
        if not publication_authorized:
            raise APIError(403, ErrorCode.PUBLICATION_AUTHORIZATION_REQUIRED, "Explicit publication authorization is required.")
        _require_safe_git_ref(branch_name, "branch name")
        _require_safe_remote_name(remote_name)
        meta = self.ensure_workspace_loaded(task, task_repo)
        if meta is None:
            raise APIError(409, ErrorCode.INVALID_STATE_TRANSITION, "Workspace not found for task.")
        branch = branch_name or meta.branch_name
        if branch != format_agent_branch_name(task.id) or remote_name != "origin":
            raise APIError(403, ErrorCode.POLICY_VIOLATION, "Publication requires the task branch and connected origin.")

        verification = self._assert_verified_and_immutable_for_publication(task, task_repo, meta)
        self._require_publication_authorization(task, task_repo, verification.verified_revision)
        if task.status != TaskStatus.PUBLISHING.value:
            raise APIError(409, ErrorCode.INVALID_STATE_TRANSITION, "Task is not awaiting publication.")
        if current_remote_head_sha:
            try:
                self.workspace_manager.assert_not_stale(str(task.id), current_remote_head_sha=current_remote_head_sha)
            except WorkspaceStaleRevisionError as exc:
                raise APIError(409, ErrorCode.PLAN_VERSION_MISMATCH, redact(str(exc))) from exc

        repo = self._publication_repository(task)
        try:
            git = GitBranchService(task_repo.session)
            token = asyncio.run(git.get_installation_token_for_repo(repo))
            push_res = self.workspace_manager.push_task_branch(
                WorkspacePushRequest(
                    task_id=str(task.id),
                    branch_name=branch,
                    remote_name=remote_name,
                    remote_url=f"https://github.com/{repo.owner}/{repo.name}.git",
                    publication_authorized=True,
                    installation_token=token,
                    expected_revision=verification.verified_revision,
                )
            )
        except (GitHubError, GitHubAPIError, WorkspacePushError) as exc:
            raise APIError(502, ErrorCode.EXTERNAL_SERVICE_ERROR, redact(str(exc))) from exc

        task_repo.record_event(
            task_id=task.id,
            repository_id=task.repository_id,
            event_type=TaskEventType.BRANCH_PUSHED.value,
            event_data={"branch": branch, "pushed_sha": push_res.pushed_sha, "remote_name": remote_name},
            user_id=actor_id,
            summary=f"Pushed verified branch '{branch}' ({push_res.pushed_sha[:8]}).",
        )
        task_repo.session.commit()
        return push_res

    def create_draft_pull_request(
        self,
        task: AgentTask,
        task_repo: TaskRepository,
        actor_id: UUID | None = None,
        *,
        publication_authorized: bool = False,
        title: str | None = None,
        body: str | None = None,
        base_branch: str | None = None,
        head_branch: str | None = None,
        current_remote_head_sha: str | None = None,
    ) -> TaskPullRequest:
        """Commit verified changes, push task branch, and create a GitHub Draft PR (`is_draft=True`, zero auto-merge)."""
        if not publication_authorized:
            raise APIError(
                403,
                ErrorCode.PUBLICATION_AUTHORIZATION_REQUIRED,
                "Draft PR publication not authorized: Explicit human authorization (`publication_authorized=True`) is required (ADR-010).",
            )
        _require_safe_git_ref(head_branch, "head branch")
        _require_safe_git_ref(base_branch, "base branch")
        if head_branch and head_branch != format_agent_branch_name(task.id):
            raise APIError(403, ErrorCode.POLICY_VIOLATION, "Draft publication requires the task branch.")

        lock = self.workspace_manager.get_task_lock(str(task.id))
        if not lock.acquire(timeout=10):
            raise APIError(409, ErrorCode.CONFLICT, f"Concurrent publication already in progress for task '{task.id}'.")

        try:
            # 1. Idempotency: if Draft PR already exists for this task, return it without creating a duplicate
            existing_pr = task_repo.get_pull_request(task.id)
            if existing_pr is not None and TaskStatus(task.status) == TaskStatus.DRAFT_PR_CREATED:
                return existing_pr

            meta = self.ensure_workspace_loaded(task, task_repo)
            if meta is None:
                raise APIError(409, ErrorCode.INVALID_STATE_TRANSITION, "Workspace not found for task.")

            effective_head = head_branch or meta.branch_name
            repo = self._publication_repository(task)
            effective_base = base_branch or repo.default_branch or "main"
            ver = self._assert_verified_and_immutable_for_publication(task, task_repo, meta)
            self._require_publication_authorization(task, task_repo, ver.verified_revision)
            self.push_verified_branch(
                task, task_repo, actor_id,
                publication_authorized=True,
                branch_name=effective_head,
                current_remote_head_sha=current_remote_head_sha,
            )

            pr_title = redact(title or f"feat: {task.title}")
            body_sections = [part for part in (body, ver.summary) if part]
            if task.finding_id:
                body_sections.append(f"**Originating Finding ID:** `{task.finding_id}`")
            if task.source_id:
                body_sections.append(f"**Source Reference:** `#{task.source_id}` ({task.source_type})")
            summary = self.workspace_manager.format_draft_pr_summary(
                task_id=str(task.id),
                title=pr_title,
                head_branch=effective_head,
                base_branch=effective_base,
                diff_result=self.workspace_manager.get_workspace_diff(str(task.id)),
                latest_test=(self.workspace_manager.get_test_history(str(task.id)) or [None])[-1],
                custom_body="\n\n".join(body_sections),
            )

            async def publish() -> dict[str, Any]:
                git = GitBranchService(task_repo.session)
                client = await git._get_client_for_repo(repo)
                existing = await client.list_pull_requests(
                    repo.owner, repo.name, head=f"{repo.owner}:{effective_head}", base=effective_base,
                )
                result = existing[0] if existing else await client.create_pull_request(
                    owner=repo.owner,
                    repo=repo.name,
                    head=effective_head,
                    base=effective_base,
                    title=pr_title,
                    body=redact(summary),
                    draft=True,
                )
                return result

            try:
                remote_pr = asyncio.run(publish())
            except (GitHubError, GitHubAPIError) as exc:
                raise APIError(502, ErrorCode.EXTERNAL_SERVICE_ERROR, redact(str(exc))) from exc

            if (
                not remote_pr.get("number") or not remote_pr.get("html_url")
                or remote_pr.get("draft") is not True
                or (remote_pr.get("head") or {}).get("sha") != ver.verified_revision
                or (remote_pr.get("head") or {}).get("ref") != effective_head
                or (remote_pr.get("base") or {}).get("ref") != effective_base
            ):
                raise APIError(502, ErrorCode.EXTERNAL_SERVICE_ERROR, "GitHub did not return a draft PR for the verified commit.")

            task_pr = task_repo.record_pull_request(
                task_id=task.id,
                repository_id=task.repository_id,
                pr_url=remote_pr["html_url"],
                base_branch=effective_base,
                head_branch=effective_head,
                head_sha=ver.verified_revision,
                title=pr_title,
                body=redact(summary),
                pr_number=remote_pr["number"],
                github_pr_id=remote_pr["number"],
                is_draft=True,
            )

            return task_pr
        finally:
            lock.release()

    # Alias for publication API consistency
    publish_draft_pr = create_draft_pull_request

    # -----------------------------------------------------------------------
    # Day 6 — Checkpoints, Crash Recovery & Sandbox Invariants (F39)
    # -----------------------------------------------------------------------

    def save_task_checkpoint(
        self,
        task: AgentTask,
        task_repo: TaskRepository,
        step_name: str,
        state_data: dict[str, Any] | None = None,
        recovery_instructions: str | None = None,
    ) -> TaskCheckpoint:
        """Persist a secret-scrubbed recovery checkpoint for a task."""
        meta = self.workspace_manager.get_workspace(str(task.id))
        payload_state = {
            "task_status": task.status,
            "plan_version": task.plan_version,
            "approved_plan_version": task.approved_plan_version,
            "repair_attempts_used": task.repair_attempts_used,
            "repair_attempts_max": task.repair_attempts_max,
            "base_revision": task.base_revision,
            "workspace_status": meta.status.value if meta else "NOT_CREATED",
            "branch_name": meta.branch_name if meta else format_agent_branch_name(task.id),
            **(state_data or {}),
        }
        return task_repo.save_checkpoint(
            task_id=task.id,
            repository_id=task.repository_id,
            step_name=step_name,
            state_data=payload_state,
            recovery_instructions=recovery_instructions
            or f"Resume task '{task.id}' from step '{step_name}' preserving repair budget ({task.repair_attempts_used}/{task.repair_attempts_max}).",
        )

    def recover_interrupted_task(
        self,
        task: AgentTask,
        task_repo: TaskRepository,
        actor_id: UUID | None = None,
        *,
        target_status: TaskStatus | str | None = None,
    ) -> dict[str, Any]:
        """Reconcile an interrupted or failed task and its workspace without resetting repair budget."""
        if target_status is not None:
            try:
                requested_target = TaskStatus(target_status) if isinstance(target_status, str) else target_status
            except ValueError as exc:
                raise APIError(400, ErrorCode.INVALID_REQUEST, "Invalid recovery target status.") from exc
            if requested_target not in _USER_RECOVERY_TARGETS:
                raise APIError(
                    400,
                    ErrorCode.INVALID_REQUEST,
                    "Recovery can only return a task to PLANNING or APPROVED (or cancel it); "
                    "execution, verification and publication must run again.",
                )
        curr_status = TaskStatus(task.status)
        if curr_status == TaskStatus.FAILED:
            task_repo.transition_status(
                task,
                TaskStatus.RECOVERY_REQUIRED,
                actor_id=actor_id,
                event_type=TaskEventType.RECOVERY_TRIGGERED.value,
                summary="Task entered RECOVERY_REQUIRED for operator-initiated recovery.",
            )
            curr_status = TaskStatus.RECOVERY_REQUIRED
        elif curr_status not in (
            TaskStatus.RECOVERY_REQUIRED,
            TaskStatus.WORKSPACE_SETUP,
            TaskStatus.EXECUTING,
            TaskStatus.TESTING,
            TaskStatus.REPAIRING,
            TaskStatus.VERIFYING,
            TaskStatus.PUBLISHING,
            TaskStatus.BLOCKED,
        ):
            raise APIError(
                409,
                ErrorCode.INVALID_STATE_TRANSITION,
                f"Task in status '{curr_status.value}' does not require crash recovery.",
            )

        if curr_status != TaskStatus.RECOVERY_REQUIRED and curr_status != TaskStatus.BLOCKED:
            task_repo.transition_status(
                task,
                TaskStatus.RECOVERY_REQUIRED,
                actor_id=actor_id,
                event_type=TaskEventType.RECOVERY_TRIGGERED.value,
                summary=f"Interrupted task in '{curr_status.value}' transitioned to RECOVERY_REQUIRED.",
            )

        # Reconcile workspace on disk / memory
        ws_recovery = None
        try:
            self.ensure_workspace_loaded(task, task_repo)
            ws_recovery = self.workspace_manager.reconcile_workspace(str(task.id))
        except WorkspaceRecoveryError:
            ws_recovery = None

        latest_cp = task_repo.get_latest_checkpoint(task.id, task.repository_id)

        # Determine safe target status while strictly preserving repair_attempts_used
        if target_status is not None:
            resolved_target = TaskStatus(target_status) if isinstance(target_status, str) else target_status
        elif task.approved_plan_version is not None:
            resolved_target = TaskStatus.APPROVED
        else:
            resolved_target = TaskStatus.PLANNING

        preserved_repair_used = task.repair_attempts_used
        task.error_message = None
        task_repo.transition_status(
            task,
            resolved_target,
            actor_id=actor_id,
            event_type=TaskEventType.RECOVERY_TRIGGERED.value,
            summary=(
                f"Recovered task to '{resolved_target.value}' "
                f"(repair budget preserved: {preserved_repair_used}/{task.repair_attempts_max})."
            ),
            payload={
                "restored_checkpoint_id": str(latest_cp.id) if latest_cp else None,
                "restored_step": latest_cp.step_name if latest_cp else None,
                "repair_attempts_used": preserved_repair_used,
                "repair_attempts_max": task.repair_attempts_max,
                "workspace_recovery": ws_recovery.model_dump(mode="json") if ws_recovery else None,
            },
        )

        details_msg = (
            f"Recovered task to '{resolved_target.value}' "
            f"(repair budget preserved: {preserved_repair_used}/{task.repair_attempts_max})."
        )
        return {
            "task_id": str(task.id),
            "previous_status": curr_status.value,
            "current_status": task.status,
            "recovered_status": task.status,
            "reconciliation_action": ws_recovery.reconciliation_action if ws_recovery else "state_reconciled",
            "details": details_msg,
            "recovered_at": datetime.now(timezone.utc).isoformat(),
            "repair_attempts_used": task.repair_attempts_used,
            "repair_attempts_max": task.repair_attempts_max,
            "restored_checkpoint": (
                {
                    "checkpoint_id": str(latest_cp.id),
                    "step_name": latest_cp.step_name,
                    "state_data": redact_obj(latest_cp.state_data),
                    "recovery_instructions": redact(latest_cp.recovery_instructions or ""),
                    "created_at": latest_cp.created_at.isoformat() if latest_cp.created_at else "",
                }
                if latest_cp
                else None
            ),
            "workspace_recovery": ws_recovery.model_dump(mode="json") if ws_recovery else None,
        }

    def check_workspace_invariants(
        self,
        task: AgentTask,
        task_repo: TaskRepository,
    ) -> dict[str, Any]:
        """Run Day 6 sandbox security, path confinement, disk quota, and diff immutability checks."""
        meta = self.ensure_workspace_loaded(task, task_repo)
        if meta is None:
            return {
                "task_id": str(task.id),
                "valid": False,
                "violations": ["Workspace has not been provisioned for this task."],
                "disk_budget": None,
                "diff_immutability": None,
            }

        inv_res = self.workspace_manager.validate_workspace_invariants(str(task.id))
        disk_res = self.workspace_manager.check_disk_budget(str(task.id))
        all_violations = list(inv_res.violations)
        if not disk_res.within_budget and disk_res.error_message:
            all_violations.append(disk_res.error_message)

        if meta.verification_diff_hash:
            imm_res = self.workspace_manager.verify_diff_immutability(
                str(task.id), expected_diff_hash=meta.verification_diff_hash
            )
            if not imm_res.is_immutable and imm_res.error_message:
                all_violations.append(imm_res.error_message)
        else:
            imm_res = DiffImmutabilityCheckResult(
                task_id=str(task.id),
                immutable=True,
                is_immutable=True,
                expected_diff_hash="",
                current_diff_hash="",
                verified_diff_hash="",
                message="Task has not undergone independent verification yet.",
            )

        return redact_obj(
            {
                "task_id": str(task.id),
                "valid": len(all_violations) == 0,
                "violations": all_violations,
                "disk_budget": disk_res.model_dump(mode="json"),
                "diff_immutability": imm_res.model_dump(mode="json"),
            }
        )

    def check_stale_base_revision(
        self,
        task: AgentTask,
        task_repo: TaskRepository,
        *,
        current_remote_head_sha: str | None = None,
    ) -> dict[str, Any]:
        """Detect whether the workspace base revision has drifted relative to the repository/plan revision (Day 6)."""
        meta = self.ensure_workspace_loaded(task, task_repo)
        ws_base = meta.base_revision if meta else (task.base_revision or "main")
        effective_remote = current_remote_head_sha or ws_base
        if meta is not None and current_remote_head_sha:
            stale_res = self.workspace_manager.detect_stale_base_revision(
                str(task.id),
                current_remote_head_sha=current_remote_head_sha,
            )
            return {
                "task_id": str(task.id),
                "is_stale": stale_res.is_stale,
                "workspace_base_revision": stale_res.workspace_base_revision,
                "current_base_revision": stale_res.workspace_base_revision,
                "current_remote_sha": stale_res.current_remote_head_sha,
                "commits_behind": 1 if stale_res.is_stale else 0,
                "remediation_suggestion": "Re-generate plan and refresh workspace against latest base revision." if stale_res.is_stale else None,
                "message": stale_res.message,
                "checked_at": datetime.now(timezone.utc).isoformat(),
            }
        is_stale = bool(current_remote_head_sha and current_remote_head_sha.strip() != ws_base.strip())
        return {
            "task_id": str(task.id),
            "is_stale": is_stale,
            "workspace_base_revision": ws_base,
            "current_base_revision": ws_base,
            "current_remote_sha": effective_remote,
            "commits_behind": 1 if is_stale else 0,
            "remediation_suggestion": "Re-generate plan and refresh workspace against latest base revision." if is_stale else None,
            "message": "Base revision is up to date." if not is_stale else f"Base revision '{ws_base}' drifted from '{effective_remote}'.",
            "checked_at": datetime.now(timezone.utc).isoformat(),
        }

    # -----------------------------------------------------------------------
    # Day 7 — Autonomous End-to-End Post-Approval Pipeline (F31–F39)
    # -----------------------------------------------------------------------

    def run_autonomous_post_approval_workflow(
        self,
        task: AgentTask,
        task_repo: TaskRepository,
        actor_id: UUID | None = None,
        *,
        step_payloads: Mapping[str, Any] | None = None,
        run_tests: bool = True,
        auto_repair: bool = True,
        publication_authorized: bool = False,
        pr_title: str | None = None,
        pr_body: str | None = None,
    ) -> dict[str, Any]:
        """Execute the complete post-approval pipeline with zero manual steps between Approval and Verification/Draft PR."""
        if publication_authorized:
            raise APIError(400, ErrorCode.INVALID_REQUEST, "Publication requires authorization of the verified commit.")
        # 1. Start workspace & execute approved plan steps
        self.start_task_execution(
            task=task,
            task_repo=task_repo,
            actor_id=actor_id,
            dry_run=False,
            run_steps=True,
            step_payloads=step_payloads,
            run_tests_after=False,
            auto_repair=False,
        )
        self.save_task_checkpoint(task, task_repo, step_name="post_step_execution")

        if TaskStatus(task.status) == TaskStatus.FAILED:
            return {
                "task_id": str(task.id),
                "status": task.status,
                "verification": None,
                "pull_request": None,
            }

        # 2. Run workspace tests & bounded self-repair if needed
        if run_tests:
            test_res = self.execute_task_tests(task=task, task_repo=task_repo, actor_id=actor_id)
            if test_res.status != TestOutcomeStatus.PASSED and auto_repair and test_res.is_repair_eligible:
                repair = self.execute_bounded_repair(
                    task=task, task_repo=task_repo, actor_id=actor_id, framework=test_res.framework,
                )
                if repair.success:
                    self.execute_task_tests(task=task, task_repo=task_repo, actor_id=actor_id)
            self.save_task_checkpoint(task, task_repo, step_name="post_test_and_repair")

        if TaskStatus(task.status) == TaskStatus.FAILED:
            return {
                "task_id": str(task.id),
                "status": task.status,
                "verification": None,
                "pull_request": None,
            }

        # 3. Run independent verification
        ver_schema = self.run_independent_verification(
            task=task,
            task_repo=task_repo,
            actor_id=actor_id,
            require_passing_tests=True,
        )
        self.save_task_checkpoint(
            task,
            task_repo,
            step_name="post_independent_verification",
            state_data={"verified_revision": ver_schema.verified_revision, "verification_status": ver_schema.status},
        )

        return redact_obj(
            {
                "task_id": str(task.id),
                "status": task.status,
                "verification": ver_schema.model_dump(mode="json"),
                "pull_request": None,
            }
        )


_default_orchestrator: TaskExecutionOrchestrator | None = None


def get_task_execution_orchestrator(app_state: Any = None) -> TaskExecutionOrchestrator:
    """Resolve the singleton TaskExecutionOrchestrator from app.state or module fallback."""
    global _default_orchestrator
    if app_state is None:
        from app.main import app

        app_state = app.state
    if app_state is not None:
        orch = getattr(app_state, "task_execution_orchestrator", None)
        if orch is not None:
            return orch
    if _default_orchestrator is None:
        _default_orchestrator = TaskExecutionOrchestrator()
    if app_state is not None:
        try:
            app_state.task_execution_orchestrator = _default_orchestrator
        except Exception as exc:
            logger.debug("Failed to cache task execution orchestrator on app.state: %s", exc)
    return _default_orchestrator
