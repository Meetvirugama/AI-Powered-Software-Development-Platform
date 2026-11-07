"""Execution Recovery & Adaptive Re-planning Service.

Implements Phase 9 & 10: Adaptive Recovery from Checkpoints (task.md §10, test plan OPS-02, OPS-04, OPS-05).
Coordinates:
- Identifying last verified checkpoint.
- Preserving completed and verified requirements.
- Re-planning unexecuted/failed steps via PlanReplanner.
- Halting for approval when scope/risk expansion is detected.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from app.schemas.plan import StructuredPlan

from ai.services.execution_budget_manager import ExecutionBudgetManager
from ai.services.execution_checkpoint_manager import ExecutionCheckpointManager
from ai.services.plan_replanner import PlanReplanner

logger = logging.getLogger(__name__)


@dataclass
class RecoveryOutcome:
    """Result of an adaptive recovery attempt."""

    can_recover: bool
    action: str  # "RESUME_REPLANNED", "REQUIRES_APPROVAL", "FAIL_CLOSED"
    message: str
    replanned_plan: StructuredPlan | None = None
    requires_human_approval: bool = False
    preserved_step_ids: list[str] = field(default_factory=list)
    rolled_back_to_checkpoint_id: str | None = None


class ExecutionRecoveryService:
    """Coordinates bounded recovery with checkpoints and adaptive replanning."""

    def __init__(self, replanner: PlanReplanner | None = None) -> None:
        self.replanner = replanner or PlanReplanner()

    def handle_step_failure(
        self,
        task_id: str,
        failed_step_id: str,
        failure_reason: str,
        original_plan: StructuredPlan,
        checkpoint_manager: ExecutionCheckpointManager,
        budget_manager: ExecutionBudgetManager,
        scope_expansion_detected: bool = False,
        scope_expansion_details: str | None = None,
    ) -> RecoveryOutcome:
        """Evaluate failure, enforce bounds, and produce an adaptive replan if permitted."""
        # 1. Check budget and retry limits
        is_exhausted, budget_msg = budget_manager.is_budget_exhausted()
        if is_exhausted:
            logger.warning("Recovery aborted for task %s: %s", task_id, budget_msg)
            return RecoveryOutcome(
                can_recover=False,
                action="FAIL_CLOSED",
                message=f"Budget exhausted, cannot retry: {budget_msg}",
            )

        retries_used = budget_manager.budget.step_retries.get(failed_step_id, 0)
        if retries_used >= budget_manager.budget.max_retries_per_step:
            msg = f"Step '{failed_step_id}' exceeded max retries ({retries_used}/{budget_manager.budget.max_retries_per_step})."
            logger.warning("Recovery aborted for task %s: %s", task_id, msg)
            return RecoveryOutcome(
                can_recover=False,
                action="FAIL_CLOSED",
                message=msg,
            )

        # 2. Scope expansion guard (OPS-05: requires human approval)
        if scope_expansion_detected:
            msg = scope_expansion_details or f"Re-planning step '{failed_step_id}' introduces new files or high-risk scope expansion."
            logger.info("Task %s recovery paused: human approval required (%s)", task_id, msg)
            return RecoveryOutcome(
                can_recover=False,
                action="REQUIRES_APPROVAL",
                message=msg,
                requires_human_approval=True,
            )

        # 3. Locate last verified checkpoint (OPS-01, OPS-02)
        latest_ckpt = checkpoint_manager.get_latest_checkpoint(task_id)
        preserved_step_ids = list(latest_ckpt.completed_step_ids) if latest_ckpt else []
        ckpt_id = latest_ckpt.checkpoint_id if latest_ckpt else None

        # 4. Generate replanned plan targeting remaining work
        replanned = self.replanner.replan_from_checkpoint(
            original_plan=original_plan,
            failed_step_id=failed_step_id,
            failure_reason=failure_reason,
            last_verified_checkpoint=latest_ckpt,
        )

        logger.info(
            "Task %s adaptively replanned from checkpoint %s (preserved: %s, remaining steps: %d)",
            task_id,
            ckpt_id,
            preserved_step_ids,
            len(replanned.steps),
        )

        return RecoveryOutcome(
            can_recover=True,
            action="RESUME_REPLANNED",
            message=f"Successfully replanned remaining work from checkpoint '{ckpt_id or 'start'}'.",
            replanned_plan=replanned,
            requires_human_approval=False,
            preserved_step_ids=preserved_step_ids,
            rolled_back_to_checkpoint_id=ckpt_id,
        )

