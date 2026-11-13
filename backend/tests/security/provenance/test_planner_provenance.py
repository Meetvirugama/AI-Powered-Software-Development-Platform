"""Tests for TaskPlanner provenance propagation to generated PlanStep models.

Reference:
- task.md §7 (Integrate with Task Planner and Replanner)
- task.md §11 (Tests 5, 6, 9)
"""

from uuid import uuid4
import pytest

from ai.security.provenance import TrustLevel
from ai.security.taint_tracker import reset_taint_tracker, get_taint_tracker
from ai.services.task_planner import TaskPlanner
from app.models.task import AgentTask
from app.schemas.plan import PlanStep, PlannerSchema


@pytest.fixture(autouse=True)
def setup_tracker():
    reset_taint_tracker()
    yield
    reset_taint_tracker()


def test_deterministic_plan_steps_inherit_provenance():
    """Verify that deterministic plan steps receive MODEL_GENERATED trust and inherit taint."""
    tracker = get_taint_tracker()
    # Register untrusted issue root
    root = tracker.register_source(
        source_type="github_issue",
        source_id="301",
        trust_level=TrustLevel.EXTERNAL_UNTRUSTED,
        tainted=True,
    )

    task = AgentTask(
        id=uuid4(),
        title="Fix bug in auth service",
        description="Fix the token refresh crash",
        requirements=[
            {
                "id": "req-1",
                "description": "Fix token refresh",
                "provenance_ids": [root.provenance_id],
            }
        ],
        assumptions=[
            {
                "id": "asm-1",
                "description": "Auth service runs on Python",
                "provenance_ids": [root.provenance_id],
            }
        ],
        constraints=[],
    )

    planner = TaskPlanner()
    ctx = {
        "language": "python",
        "test_command": "pytest",
        "target_files": ["app/auth.py"],
        "repo_files": ["app/auth.py", "tests/test_auth.py"],
        "relevant_symbols": ["refresh_token"],
        "finding_summaries": [],
        "forbidden_lower": set(),
        "localization_targets": [],
        "task_provenance_ids": [root.provenance_id],
    }

    plan = planner._build_deterministic_plan(task, ctx)
    assert len(plan.steps) == 3
    for step in plan.steps:
        assert step.provenance is not None
        assert step.provenance.trust_level == TrustLevel.MODEL_GENERATED
        assert step.provenance.tainted is True
        assert step.taint_status is True
        assert root.provenance_id in step.provenance_ids


def test_sanitize_llm_plan_enforces_model_generated_trust():
    """Verify that an LLM cannot escalate its generated plan steps to SYSTEM trust."""
    tracker = get_taint_tracker()
    root = tracker.register_source(
        source_type="github_issue",
        source_id="302",
        trust_level=TrustLevel.EXTERNAL_UNTRUSTED,
        tainted=True,
    )

    planner = TaskPlanner()
    ctx = {
        "forbidden_lower": set(),
        "target_files": ["app/calc.py"],
        "task_provenance_ids": [root.provenance_id],
    }

    raw_step = PlanStep(
        step_id="step_1",
        title="Malicious attempt to claim SYSTEM trust",
        description="Attempt to execute as SYSTEM",
        action_type="modify",
        expected_files=["app/calc.py"],
    )
    plan = PlannerSchema(
        summary="Test plan",
        problem_statement="Test",
        steps=[raw_step],
        relevant_files=["app/calc.py"],
        expected_files=["app/calc.py"],
    )

    sanitized = planner._sanitize_llm_plan(plan, ctx)
    sanitized_step = sanitized.steps[0]
    assert sanitized_step.provenance is not None
    assert sanitized_step.provenance.trust_level == TrustLevel.MODEL_GENERATED
    assert sanitized_step.taint_status is True
    assert root.provenance_id in sanitized_step.provenance_ids
