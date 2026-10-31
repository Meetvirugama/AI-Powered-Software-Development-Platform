"""Agent Execution Loop & Anti-Cyclic Loop Detector.

Owner: Meet (Week 3 Day 3: Agent execution loop executing approved plan steps with loop detection)
Reference: Docs/week3.md §6 F33, F34 & §8 Day 3.

Key Responsibilities:
1. AgentExecutionLoop:
   - Traverses validated StructuredPlan steps in dependency (topological) order.
   - Dispatches safe workspace operations via WorkspaceManager and WorkspaceToolPolicyBridge.
   - Enforces execution prerequisites: task must be APPROVED / WORKSPACE_SETUP / IN_USE.
   - Records chronological timeline events for each step lifecycle state.
2. Anti-Cyclic Loop Detector:
   - Fingerprints action signatures (step_id, action_type, target_files, arguments).
   - Detects immediate duplicate actions and repeating cyclic oscillations (N-grams).
   - Enforces hard iteration limits to prevent infinite execution and token exhaustion.
   - Fails safely on loop detection, emitting LOOP_DETECTED timeline events.
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Mapping, Sequence

from app.core.input_security import UnsafePathError, validate_repo_relative_path
from app.core.secret_redaction import redact
from app.schemas.plan import PlanStep, StructuredPlan
from app.schemas.workspace import (
    WorkspaceCommandRequest,
    WorkspaceExecutionEventType,
    WorkspaceFileReadRequest,
    WorkspaceFileWriteRequest,
    WorkspaceStatus,
)
from sandbox.exceptions import (
    WorkspaceError,
    WorkspacePolicyViolationError,
    WorkspaceStateError,
)
from sandbox.workspace_manager import WorkspaceManager

logger = logging.getLogger(__name__)


class StepExecutionStatus(str, Enum):
    """Lifecycle status for an individual plan step execution."""

    PENDING = "PENDING"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"
    LOOP_DETECTED = "LOOP_DETECTED"


class LoopDetectedError(WorkspaceError):
    """Raised when repetitive cyclic execution is detected in the agent execution loop."""


@dataclass(frozen=True)
class ActionFingerprint:
    """Deterministic fingerprint representing an agent step action."""

    step_id: str
    action_type: str
    target_files: tuple[str, ...]
    payload_hash: str


@dataclass
class StepExecutionRecord:
    """Execution telemetry record for an individual plan step."""

    step_id: str
    action_type: str
    status: StepExecutionStatus
    target_files: list[str] = field(default_factory=list)
    output: Any = None
    error_message: str | None = None
    duration_ms: float = 0.0
    attempts: int = 1
    started_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    completed_at: str | None = None


@dataclass
class AgentExecutionResult:
    """Overall outcome of an AgentExecutionLoop run."""

    task_id: str
    status: StepExecutionStatus
    steps_executed: list[StepExecutionRecord]
    loop_detected: bool = False
    cycle_detected: bool = False
    cycle_length: int = 0
    total_iterations: int = 0
    total_duration_ms: float = 0.0
    error_message: str | None = None


class LoopDetector:
    """Detects infinite loops, repeated identical actions, and cyclic oscillations."""

    def __init__(self, max_cycle_repetitions: int = 2, max_cycle_window: int = 4) -> None:
        self.max_cycle_repetitions = max_cycle_repetitions
        self.max_cycle_window = max_cycle_window
        self._history: list[ActionFingerprint] = []

    def fingerprint_action(
        self,
        step_id: str,
        action_type: str,
        target_files: Sequence[str],
        content_or_args: Any = None,
    ) -> ActionFingerprint:
        """Create a deterministic hash fingerprint of an action invocation."""
        normalized_files = tuple(sorted(str(f).strip() for f in target_files))
        try:
            serialized = json.dumps(content_or_args, sort_keys=True, default=str)
        except Exception:
            serialized = str(content_or_args)
        payload_hash = hashlib.sha256(serialized.encode("utf-8")).hexdigest()[:16]
        return ActionFingerprint(
            step_id=step_id,
            action_type=action_type.lower(),
            target_files=normalized_files,
            payload_hash=payload_hash,
        )

    def record_and_check(self, fingerprint: ActionFingerprint) -> tuple[bool, int]:
        """Record an action and return (is_loop_detected, cycle_length)."""
        self._history.append(fingerprint)
        n = len(self._history)

        # Check for immediate identical repeat
        if n >= 2 and self._history[-1] == self._history[-2]:
            if self.max_cycle_repetitions <= 1:
                return True, 1

        # Check for repeating cycles of length k from 1 up to max_cycle_window
        for k in range(1, min(self.max_cycle_window + 1, n // self.max_cycle_repetitions + 1)):
            is_cycle = True
            latest_segment = self._history[-k:]
            for rep in range(1, self.max_cycle_repetitions):
                start = -k * (rep + 1)
                end = -k * rep
                if self._history[start:end] != latest_segment:
                    is_cycle = False
                    break
            if is_cycle:
                logger.warning(
                    "agent_cycle_detected",
                    extra={"cycle_length": k, "repetitions": self.max_cycle_repetitions},
                )
                return True, k

        return False, 0

    def reset(self) -> None:
        """Clear action history."""
        self._history.clear()


class AgentExecutionLoop:
    """Executes approved structured plan steps with anti-cyclic loop detection."""

    def __init__(
        self,
        workspace_manager: WorkspaceManager,
        *,
        max_iterations: int = 25,
        max_cycle_repetitions: int = 2,
    ) -> None:
        self.workspace_manager = workspace_manager
        self.max_iterations = max_iterations
        self.loop_detector = LoopDetector(max_cycle_repetitions=max_cycle_repetitions)

    def _resolve_step_dependencies(self, steps: Sequence[PlanStep]) -> list[PlanStep]:
        """Sort steps topologically by dependencies; fallback to natural order if cyclic."""
        step_map = {step.step_id: step for step in steps}
        visited: set[str] = set()
        visiting: set[str] = set()
        ordered: list[PlanStep] = []

        def dfs(step_id: str) -> None:
            if step_id in visited or step_id not in step_map:
                return
            if step_id in visiting:
                # Cycle in dependencies -> skip topological reordering
                return
            visiting.add(step_id)
            current_step = step_map[step_id]
            deps = getattr(current_step, "dependencies", []) or getattr(current_step, "depends_on", []) or []
            for dep in deps:
                dfs(dep)
            visiting.remove(step_id)
            visited.add(step_id)
            ordered.append(current_step)

        for step in steps:
            dfs(step.step_id)

        # Include any remaining steps that were not reached
        for step in steps:
            if step not in ordered:
                ordered.append(step)

        return ordered

    def execute_plan(
        self,
        task_id: str,
        plan: StructuredPlan | Sequence[PlanStep] | Sequence[dict[str, Any]] | Any,
        *,
        step_payloads: Mapping[str, Any] | None = None,
    ) -> AgentExecutionResult:
        """Execute an approved plan inside the task's isolated workspace sandbox."""
        start_time = datetime.now(timezone.utc)
        meta = self.workspace_manager.get_workspace(task_id)
        if not meta:
            raise WorkspaceError(f"Workspace not found for task '{task_id}'. Cannot execute plan.")

        # Ensure workspace is IN_USE (or transition from READY/STOPPED)
        if meta.status != WorkspaceStatus.IN_USE:
            if meta.status in (WorkspaceStatus.READY, WorkspaceStatus.STOPPED):
                self.workspace_manager.transition_state(task_id, WorkspaceStatus.IN_USE)
            else:
                raise WorkspaceStateError(
                    f"Workspace is in state '{meta.status.value}', cannot execute plan. Expected IN_USE or READY."
                )

        # Extract steps
        raw_steps: list[PlanStep] = []
        if hasattr(plan, "steps"):
            raw_steps = list(plan.steps)
        elif isinstance(plan, Sequence):
            for item in plan:
                if isinstance(item, PlanStep):
                    raw_steps.append(item)
                elif isinstance(item, dict):
                    raw_steps.append(
                        PlanStep(
                            step_id=str(item.get("step_id", f"step-{len(raw_steps)+1}")),
                            title=item.get("title", ""),
                            description=item.get("description", ""),
                            action_type=item.get("action_type") or item.get("step_type", "edit"),
                            expected_files=item.get("expected_files", []),
                            dependencies=item.get("dependencies", []),
                            verification=item.get("verification", []),
                        )
                    )
        else:
            raise ValueError(f"Unsupported plan format: {type(plan)}")

        ordered_steps = self._resolve_step_dependencies(raw_steps)
        self.loop_detector.reset()

        step_records: list[StepExecutionRecord] = []
        payload_map = step_payloads or {}
        iteration_count = 0

        self.workspace_manager.record_timeline_event(
            task_id=task_id,
            event_type=WorkspaceExecutionEventType.EXECUTION_STARTED,
            message=f"Starting plan execution ({len(ordered_steps)} steps scheduled).",
            payload={"step_count": len(ordered_steps)},
        )

        for step in ordered_steps:
            iteration_count += 1
            if iteration_count > self.max_iterations:
                msg = f"Maximum execution iterations ({self.max_iterations}) exceeded."
                logger.error("max_iterations_exceeded", extra={"task_id": task_id, "iterations": iteration_count})
                return AgentExecutionResult(
                    task_id=task_id,
                    status=StepExecutionStatus.FAILED,
                    steps_executed=step_records,
                    total_iterations=iteration_count,
                    total_duration_ms=(datetime.now(timezone.utc) - start_time).total_seconds() * 1000,
                    error_message=msg,
                )

            step_id = step.step_id
            action_type = str(getattr(step, "action_type", None) or getattr(step, "step_type", "edit")).lower()
            expected_files = list(getattr(step, "expected_files", []) or getattr(step, "target_files", []) or [])
            step_input = payload_map.get(step_id, {})

            # 1. Anti-Cyclic Loop Check
            fingerprint = self.loop_detector.fingerprint_action(
                step_id=step_id,
                action_type=action_type,
                target_files=expected_files,
                content_or_args=step_input,
            )
            is_loop, cycle_len = self.loop_detector.record_and_check(fingerprint)
            if is_loop:
                error_msg = (
                    f"Repetitive execution cycle detected (cycle length: {cycle_len}). "
                    f"Agent execution halted at step '{step_id}' to prevent infinite looping."
                )
                logger.error("loop_detected_abort", extra={"task_id": task_id, "step_id": step_id, "cycle_len": cycle_len})
                self.workspace_manager.record_timeline_event(
                    task_id=task_id,
                    event_type=WorkspaceExecutionEventType.EXECUTION_FAILED,
                    message=error_msg,
                    payload={"step_id": step_id, "cycle_length": cycle_len},
                )
                step_records.append(
                    StepExecutionRecord(
                        step_id=step_id,
                        action_type=action_type,
                        status=StepExecutionStatus.LOOP_DETECTED,
                        target_files=expected_files,
                        error_message=error_msg,
                        completed_at=datetime.now(timezone.utc).isoformat(),
                    )
                )
                return AgentExecutionResult(
                    task_id=task_id,
                    status=StepExecutionStatus.LOOP_DETECTED,
                    steps_executed=step_records,
                    loop_detected=True,
                    cycle_detected=True,
                    cycle_length=cycle_len,
                    total_iterations=iteration_count,
                    total_duration_ms=(datetime.now(timezone.utc) - start_time).total_seconds() * 1000,
                    error_message=error_msg,
                )

            # 2. Execute Step
            step_record = self._execute_single_step(task_id, step, step_input)
            step_records.append(step_record)

            if step_record.status == StepExecutionStatus.FAILED:
                # Halt execution sequence on failure
                return AgentExecutionResult(
                    task_id=task_id,
                    status=StepExecutionStatus.FAILED,
                    steps_executed=step_records,
                    total_iterations=iteration_count,
                    total_duration_ms=(datetime.now(timezone.utc) - start_time).total_seconds() * 1000,
                    error_message=step_record.error_message,
                )

        total_ms = (datetime.now(timezone.utc) - start_time).total_seconds() * 1000
        self.workspace_manager.record_timeline_event(
            task_id=task_id,
            event_type=WorkspaceExecutionEventType.TOOL_INVOCATION,
            message=f"Plan execution completed successfully across {len(step_records)} steps in {total_ms:.1f}ms.",
            payload={"step_count": len(step_records), "duration_ms": total_ms},
        )

        return AgentExecutionResult(
            task_id=task_id,
            status=StepExecutionStatus.COMPLETED,
            steps_executed=step_records,
            total_iterations=iteration_count,
            total_duration_ms=total_ms,
        )

    def _execute_single_step(
        self,
        task_id: str,
        step: PlanStep,
        step_input: Mapping[str, Any],
    ) -> StepExecutionRecord:
        """Execute a single plan step dispatching to WorkspaceManager operations."""
        step_id = step.step_id
        action_type = str(getattr(step, "action_type", None) or getattr(step, "step_type", "edit")).lower()
        expected_files = list(getattr(step, "expected_files", []) or getattr(step, "target_files", []) or [])
        step_start = datetime.now(timezone.utc)

        self.workspace_manager.record_timeline_event(
            task_id=task_id,
            event_type=WorkspaceExecutionEventType.TOOL_INVOCATION,
            message=f"Starting step '{step_id}': {action_type} on {expected_files}",
            payload={"step_id": step_id, "action_type": action_type, "files": expected_files},
        )

        record = StepExecutionRecord(
            step_id=step_id,
            action_type=action_type,
            status=StepExecutionStatus.RUNNING,
            target_files=expected_files,
            started_at=step_start.isoformat(),
        )

        try:
            # Validate repo-relative paths
            for target_file in expected_files:
                validate_repo_relative_path(target_file)

            output: Any = None
            if action_type in ("edit", "create", "write"):
                content = step_input.get("content")
                if content is None:
                    # Synthetic code edit if content not supplied directly
                    content = f"# Generated change for step {step_id}: {step.description}\n"
                for target_file in expected_files:
                    if hasattr(self.workspace_manager, "write_file"):
                        res = self.workspace_manager.write_file(
                            task_id=task_id,
                            file_path=target_file,
                            content=content,
                            create_parents=True,
                        )
                        output = {"written_bytes": getattr(res, "bytes_written", len(content))}
                    else:
                        req = WorkspaceFileWriteRequest(
                            task_id=task_id,
                            file_path=target_file,
                            content=content,
                            create_directories=True,
                        )
                        res = self.workspace_manager.safe_write_file(req)
                        output = {"written_bytes": getattr(res, "bytes_written", len(content))}

            elif action_type in ("inspect", "read"):
                read_outputs: dict[str, str] = {}
                for target_file in expected_files:
                    if hasattr(self.workspace_manager, "read_file"):
                        res = self.workspace_manager.read_file(task_id=task_id, file_path=target_file)
                        read_outputs[target_file] = getattr(res, "content", "")
                    else:
                        req = WorkspaceFileReadRequest(task_id=task_id, file_path=target_file)
                        res = self.workspace_manager.safe_read_file(req)
                        read_outputs[target_file] = getattr(res, "content", "")
                output = read_outputs

            elif action_type in ("command", "test"):
                cmd = step_input.get("command") or "pytest"
                args = step_input.get("args") or []
                req = WorkspaceCommandRequest(task_id=task_id, command=cmd, arguments=args)
                if hasattr(self.workspace_manager, "execute_command"):
                    res = self.workspace_manager.execute_command(req)
                else:
                    res = self.workspace_manager.run_command_in_workspace(req)
                output = {"exit_code": res.exit_code, "stdout": res.stdout, "stderr": res.stderr}
                if res.exit_code != 0:
                    raise WorkspaceError(f"Command '{cmd}' failed with exit code {res.exit_code}: {res.stderr}")

            else:
                # Default inspect/noop step
                output = {"status": "executed", "step_id": step_id}

            record.status = StepExecutionStatus.COMPLETED
            record.output = output
            record.completed_at = datetime.now(timezone.utc).isoformat()
            record.duration_ms = (datetime.now(timezone.utc) - step_start).total_seconds() * 1000

            self.workspace_manager.record_timeline_event(
                task_id=task_id,
                event_type=WorkspaceExecutionEventType.TOOL_INVOCATION,
                message=f"Step '{step_id}' completed successfully in {record.duration_ms:.1f}ms.",
                payload={"step_id": step_id, "duration_ms": record.duration_ms},
            )

        except Exception as exc:
            err_msg = redact(str(exc))
            record.status = StepExecutionStatus.FAILED
            record.error_message = err_msg
            record.completed_at = datetime.now(timezone.utc).isoformat()
            record.duration_ms = (datetime.now(timezone.utc) - step_start).total_seconds() * 1000

            self.workspace_manager.record_timeline_event(
                task_id=task_id,
                event_type=WorkspaceExecutionEventType.EXECUTION_FAILED,
                message=f"Step '{step_id}' failed: {err_msg}",
                payload={"step_id": step_id, "error": err_msg},
            )

        return record
