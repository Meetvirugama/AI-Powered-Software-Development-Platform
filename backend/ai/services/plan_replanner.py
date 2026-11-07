"""Adaptive Plan Replanner — Bounded Failure Recovery and Graph Rerouting.

Owner: Meet & Dev (task.md §3, §5 A, §6 Item 7).
Re-plans remaining steps from the last verified checkpoint when a step fails,
instead of restarting the entire plan or repeating previously verified actions.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from typing import TYPE_CHECKING, Any

from app.core.secret_redaction import redact
from app.models.task import AgentTask
from app.schemas.plan import (
    PlanDependencyGraph,
    PlanStep,
    StructuredPlan,
)

from ai.context.task_context import TaskContextManifest

if TYPE_CHECKING:
    from ai.llm.client import LLMGateway

logger = logging.getLogger(__name__)


class PlanReplanner:
    """Computes targeted recovery plans from verified execution checkpoints."""

    def __init__(self, llm_gateway: LLMGateway | None = None) -> None:
        self._gateway = llm_gateway

    def replan_from_failure(
        self,
        task: AgentTask,
        original_plan: StructuredPlan,
        failed_step_id: str,
        failure_reason: str,
        completed_step_ids: Sequence[str],
        context: TaskContextManifest,
        max_recovery_attempts: int = 2,
    ) -> StructuredPlan:
        """Construct a revised plan retaining verified steps and splicing targeted repair steps."""
        step_map = {s.step_id: s for s in original_plan.steps}
        failed_step = step_map.get(failed_step_id)

        # Check if the failed step defined an explicit recovery transition
        custom_recovery_id = None
        if failed_step:
            for tr in getattr(failed_step, "transitions", []) or []:
                if tr.outcome in ("failure", "blocked", "timeout") and tr.recovery_step_id:
                    custom_recovery_id = tr.recovery_step_id
                    break

        new_steps: list[PlanStep] = []

        # 1. Retain already completed steps
        for sid in completed_step_ids:
            if sid in step_map:
                new_steps.append(step_map[sid])

        # 2. Insert targeted recovery step for the failed action
        recovery_step_id = custom_recovery_id or f"recovery_{failed_step_id}"
        failed_desc = getattr(failed_step, "description", "") if failed_step else "execution step"
        failed_files = getattr(failed_step, "expected_files", []) if failed_step else context.target_files

        recovery_step = PlanStep(
            step_id=recovery_step_id,
            title=f"Repair and recover: {getattr(failed_step, 'title', failed_step_id)}",
            description=(
                f"Diagnose and resolve failure in '{failed_step_id}' ({redact(failure_reason[:150])}). "
                f"Re-apply fix for: {failed_desc}"
            ),
            action_type="modify",
            expected_files=list(failed_files),
            target_symbols=getattr(failed_step, "target_symbols", []) if failed_step else [],
            depends_on=[sid for sid in completed_step_ids if sid != failed_step_id],
            tests_to_run=getattr(failed_step, "tests_to_run", []) or [context.test_command],
            verification=[f"Resolution of failure verified: {redact(failure_reason[:80])}"],
        )
        new_steps.append(recovery_step)

        # 3. Append remaining steps from original plan, updating their dependencies
        for step in original_plan.steps:
            if step.step_id not in completed_step_ids and step.step_id != failed_step_id:
                # Update dependencies so that if it depended on failed_step_id, it now depends on recovery_step_id
                updated_deps = [
                    recovery_step_id if dep == failed_step_id else dep
                    for dep in (step.dependencies or step.depends_on)
                ]
                updated_step = step.model_copy(
                    update={
                        "depends_on": updated_deps,
                        "dependencies": updated_deps,
                    }
                )
                new_steps.append(updated_step)

        # Validate new DAG
        graph = PlanDependencyGraph(new_steps)
        graph.validate()

        # Build revised plan
        revised_plan = original_plan.model_copy(
            update={
                "plan_version": (original_plan.plan_version or 1) + 1,
                "summary": f"{original_plan.summary} (Recovered from {failed_step_id} failure)",
                "steps": new_steps,
            }
        )
        return revised_plan

    def replan_from_checkpoint(
        self,
        original_plan: StructuredPlan,
        failed_step_id: str | None = None,
        failure_reason: str = "Execution error",
        last_verified_checkpoint: Any = None,
        additional_requirements: Sequence[Any] | None = None,
    ) -> StructuredPlan:
        """Convenience method to replan directly using an ExecutionCheckpoint."""
        completed_step_ids = []
        if last_verified_checkpoint:
            completed_step_ids = list(getattr(last_verified_checkpoint, "completed_step_ids", []) or [])

        step_id_to_recover = failed_step_id
        if not step_id_to_recover:
            for s in original_plan.steps:
                if s.step_id not in completed_step_ids:
                    step_id_to_recover = s.step_id
                    break
        if not step_id_to_recover:
            step_id_to_recover = original_plan.steps[0].step_id if original_plan.steps else "step-recovery"

        context = TaskContextManifest(
            snapshot_id="replan_snapshot",
            commit_sha=getattr(last_verified_checkpoint, "workspace_revision", "head"),
            target_files=list(original_plan.expected_files_to_modify or []),
        )
        dummy_task = AgentTask(
            title=original_plan.summary or "Recovery Task",
            description=original_plan.problem_statement or "Re-planning from failure",
        )
        return self.replan_from_failure(
            task=dummy_task,
            original_plan=original_plan,
            failed_step_id=step_id_to_recover,
            failure_reason=failure_reason,
            completed_step_ids=completed_step_ids,
            context=context,
        )

