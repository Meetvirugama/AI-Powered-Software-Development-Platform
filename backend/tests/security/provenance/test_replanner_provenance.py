"""Tests for PlanReplanner provenance preservation during failure recovery.

Reference:
- task.md §7 (Plan Replanning Lineage)
- task.md §11 (Test 7: Replanning cannot erase taint)
"""

from uuid import uuid4
import pytest

from ai.context.task_context import TaskContextManifest
from ai.security.provenance import TrustLevel
from ai.security.taint_tracker import reset_taint_tracker, get_taint_tracker
from ai.services.plan_replanner import PlanReplanner
from app.models.task import AgentTask
from app.schemas.plan import PlanStep, StructuredPlan


@pytest.fixture(autouse=True)
def setup_tracker():
    reset_taint_tracker()
    yield
    reset_taint_tracker()


def test_replanning_cannot_erase_taint():
    """Verify that replanning preserves failed step lineage and does not clear taint."""
    tracker = get_taint_tracker()
    root = tracker.register_source(
        source_type="github_issue",
        source_id="401",
        trust_level=TrustLevel.EXTERNAL_UNTRUSTED,
        tainted=True,
    )

    failed_prov = tracker.propagate(
        parent_ids=[root.provenance_id],
        transformation="task_planner",
        trust_level=TrustLevel.MODEL_GENERATED,
    )

    failed_step = PlanStep(
        step_id="step_2",
        title="Apply bugfix",
        description="Modify src/service.py",
        action_type="modify",
        expected_files=["src/service.py"],
        provenance=failed_prov,
        provenance_ids=[failed_prov.provenance_id, root.provenance_id],
        taint_status=True,
    )

    step_1 = PlanStep(
        step_id="step_1",
        title="Inspect files",
        description="Read src/service.py",
        action_type="inspect",
        expected_files=["src/service.py"],
    )

    plan = StructuredPlan(
        task_id=str(uuid4()),
        summary="Initial development plan",
        steps=[step_1, failed_step],
        expected_files=["src/service.py"],
        base_commit_sha="abcdef1234567890abcdef1234567890abcdef12",
    )

    task = AgentTask(
        id=uuid4(),
        title="Fix bug",
        description="Fix the defect",
    )

    context = TaskContextManifest(
        snapshot_id="test_snap",
        commit_sha="abcdef1234567890abcdef1234567890abcdef12",
        target_files=["src/service.py"],
        test_command="pytest",
    )

    replanner = PlanReplanner()
    revised = replanner.replan_from_failure(
        task=task,
        original_plan=plan,
        failed_step_id="step_2",
        failure_reason="SyntaxError on line 42",
        completed_step_ids=["step_1"],
        context=context,
    )

    # Find the recovery step
    recovery_steps = [s for s in revised.steps if "recovery" in s.step_id]
    assert len(recovery_steps) == 1
    recovery_step = recovery_steps[0]

    # Must preserve taint and lineage
    assert recovery_step.provenance is not None
    assert recovery_step.provenance.tainted is True
    assert recovery_step.taint_status is True
    assert recovery_step.provenance.trust_level == TrustLevel.MODEL_GENERATED
    assert failed_prov.provenance_id in recovery_step.provenance_ids
    assert root.provenance_id in recovery_step.provenance_ids
