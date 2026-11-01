"""Task Execution, Sandbox Tool Routing, Test Runner & Bounded Repair Orchestrator.

Owner: Yug & Meet & Sukun — Week 3 Day 3 & Day 4 Deliverable (Docs/week3.md §6 F33–F35 & §8 Day 3–4)
Responsibilities:
1. Provision and manage isolated task workspaces (`WorkspaceManager`) synchronized with PostgreSQL (`TaskRepository`).
2. Enforce human approval gates (`verify_execution_approval_gate`) before any workspace provisioning or step execution.
3. Route tool invocations through `ToolRouter` and `WorkspaceToolPolicyBridge` while recording audit logs (`ToolInvocation`).
4. Execute approved plan steps with anti-cyclic loop detection (`AgentExecutionLoop`).
5. Execute restricted test suites (`WorkspaceTestRunner`) and persist `TestRun` outcomes.
6. Run bounded self-repair cycles (`BoundedRepairLoop`, max 3 task-level attempts) and persist `RepairAttempt` records.
"""

from __future__ import annotations

import logging
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
from ai.services.bounded_repair_loop import BoundedRepairLoop, BoundedRepairOutcome
from app.core.errors import APIError, ErrorCode
from app.core.secret_redaction import redact, redact_obj
from app.models.task import (
    AgentTask,
    ExecutionStatus,
    RepairResult,
    TaskExecution,
    TaskStatus,
    TestRunStatus,
    ToolInvocationStatus,
    WorkspaceStatus as DBWorkspaceStatus,
)
from app.repositories.task_repository import TaskRepository
from app.schemas.repair import RepairPatchPayload
from app.schemas.workspace import (
    TestOutcomeStatus,
    WorkspaceCreateRequest,
    WorkspaceMetadata,
    WorkspaceRepairBudgetStatus,
    WorkspaceStartExecutionRequest,
    WorkspaceStatus,
    WorkspaceTestExecutionRequest,
    WorkspaceTestExecutionResult,
)
from app.services.git_branch import format_agent_branch_name
from sandbox.exceptions import (
    WorkspaceAuthorizationError,
    WorkspaceCommandTimeoutError,
    WorkspaceDuplicateRepairPatchError,
    WorkspaceError,
    WorkspacePathEscapeError,
    WorkspacePolicyViolationError,
    WorkspaceRepairBudgetExhaustedError,
    WorkspaceStaleApprovalError,
    WorkspaceStateError,
)
from sandbox.tool_policy_bridge import WorkspaceToolPolicyBridge, register_workspace_tools
from sandbox.workspace_manager import WorkspaceManager

logger = logging.getLogger(__name__)


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


class TaskExecutionOrchestrator:
    """Coordinates database persistence, WorkspaceManager, ToolRouter, AgentExecutionLoop, and BoundedRepairLoop."""

    def __init__(
        self,
        workspace_manager: WorkspaceManager | None = None,
        tool_router: ToolRouter | None = None,
    ) -> None:
        self.workspace_manager = workspace_manager or WorkspaceManager()
        self.tool_router = tool_router or ToolRouter(command_allowlist=DEFAULT_COMMAND_ALLOWLIST)
        self.policy_bridge = self._ensure_tools_registered(self.tool_router, self.workspace_manager)
        self.execution_loop = AgentExecutionLoop(
            workspace_manager=self.workspace_manager,
            tool_router=self.tool_router,
        )
        self.repair_loop = BoundedRepairLoop(
            workspace_manager=self.workspace_manager,
            test_runner=self.workspace_manager.test_runner,
        )

    @staticmethod
    def _ensure_tools_registered(
        router: ToolRouter,
        workspace_manager: WorkspaceManager,
    ) -> WorkspaceToolPolicyBridge:
        existing_names = {t.name for t in router.get_tools()}
        if "read_file" not in existing_names:
            return register_workspace_tools(router, workspace_manager)
        return WorkspaceToolPolicyBridge(workspace_manager)

    def ensure_workspace_loaded(
        self,
        task: AgentTask,
        task_repo: TaskRepository,
    ) -> WorkspaceMetadata | None:
        """Ensure in-memory WorkspaceManager is synchronized with the database Workspace record if present."""
        task_id_str = str(task.id)
        meta = self.workspace_manager.get_workspace(task_id_str)
        if meta is not None:
            return meta

        db_ws = task_repo.get_workspace_record(task.id)
        if db_ws is None:
            return None

        branch_name = db_ws.task_branch or format_agent_branch_name(task.id)
        ws_path = Path(db_ws.workspace_path)
        if not ws_path.exists():
            ws_path.mkdir(parents=True, exist_ok=True)

        create_req = WorkspaceCreateRequest(
            task_id=task_id_str,
            repository_id=str(task.repository_id),
            base_revision=db_ws.base_revision or task.base_revision or "main",
            branch_name=branch_name,
            isolation_type="directory_copy",
        )
        meta = self.workspace_manager.create_workspace(create_req)
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
                meta = self.workspace_manager.create_workspace(create_req)

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
            approved_base_revision=base_rev,
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
        task_repo.verify_execution_approval_gate(task)
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

        inv_status = ToolInvocationStatus.COMPLETED if res.success else ToolInvocationStatus.BLOCKED
        task_repo.record_tool_invocation(
            task_id=task.id,
            repository_id=task.repository_id,
            tool_name=tool_name,
            arguments=arguments,
            status=inv_status,
            duration_ms=elapsed_ms,
            output_summary=redact(str(res.output if res.success else res.error)),
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
    ) -> WorkspaceTestExecutionResult:
        """Run restricted test suite inside the task workspace and persist TestRun in DB."""
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
        )
        result = self.workspace_manager.run_tests(test_req)

        db_status = TestRunStatus.PASSED.value
        if result.status == TestOutcomeStatus.TIMEOUT or result.timed_out:
            db_status = TestRunStatus.TIMED_OUT.value
        elif result.status in (TestOutcomeStatus.ERROR, TestOutcomeStatus.UNSUPPORTED_FRAMEWORK):
            db_status = TestRunStatus.ERROR.value
        elif result.status != TestOutcomeStatus.PASSED:
            db_status = TestRunStatus.FAILED.value

        cmd_str = f"{result.framework or 'pytest'} {test_path or ''}".strip()
        combined_output = f"{result.stdout}\n{result.stderr}".strip()
        task_repo.record_test_run(
            task_id=task.id,
            repository_id=task.repository_id,
            command=cmd_str,
            status=db_status,
            exit_code=0 if result.status == TestOutcomeStatus.PASSED else 1,
            duration_ms=int(result.duration_ms),
            tests_total=result.total_count,
            tests_passed=result.passed_count,
            tests_failed=result.failed_count,
            sanitized_output=combined_output[:10_000],
            target_revision=meta.base_revision,
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
        meta = self.ensure_workspace_loaded(task, task_repo)
        if meta is None:
            raise APIError(404, ErrorCode.NOT_FOUND, f"No workspace found for task '{task.id}'.")

        if meta.status == WorkspaceStatus.READY:
            self.workspace_manager.transition_state(str(task.id), WorkspaceStatus.IN_USE)

        if task.repair_attempts_used >= task.repair_attempts_max:
            task_repo.increment_repair_attempt(
                task_id=task.id,
                repository_id=task.repository_id,
                failure_classification="RETRY_BUDGET_EXHAUSTED",
                diagnosis="Maximum 3 repair attempts already exhausted.",
            )
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
        self.repair_loop.max_repair_attempts = remaining

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
                    target_files=files or ["src/main.py"],
                )
            return self.repair_loop._synthesize_patch(t_id, attempt_num, diag)

        outcome = self.repair_loop.run_repair_cycle(
            task_id=str(task.id),
            framework="pytest" if framework == "pytest" else "jest",
            test_path=test_path,
            patch_synthesizer=_custom_synthesizer if patch_diff else None,
            forbidden_files=forbidden_files,
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

            # Also record in WorkspaceManager's test_runner budget tracker if not already recorded
            try:
                self.workspace_manager.test_runner.record_repair_attempt(
                    task_id=str(task.id),
                    patch_summary=rec.patch_summary,
                    patch_content= f"{rec.patch_hash or rec.attempt_number}",
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

        return outcome


_default_orchestrator: TaskExecutionOrchestrator | None = None


def get_task_execution_orchestrator(app_state: Any = None) -> TaskExecutionOrchestrator:
    """Resolve the singleton TaskExecutionOrchestrator from app.state or module fallback."""
    global _default_orchestrator
    if app_state is not None:
        orch = getattr(app_state, "task_execution_orchestrator", None)
        if orch is not None:
            return orch
    if _default_orchestrator is None:
        _default_orchestrator = TaskExecutionOrchestrator()
    if app_state is not None:
        try:
            app_state.task_execution_orchestrator = _default_orchestrator
        except Exception:
            pass
    return _default_orchestrator
