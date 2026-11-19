"""backend/tests/test_intent_router_and_plan_critic.py

Comprehensive tests for Universal AI Prompt-to-PR Phase 2:
- IntentRouter (Intent classification, Ambiguity detection, Layer inference)
- PlanCritic (Adversarial plan verification, safety boundaries, test & migration checks)
"""

from __future__ import annotations

import pytest

from ai.services.intent_router import IntentRouter, TaskIntent
from ai.services.plan_critic import CriticSeverity, PlanCritic
from ai.services.task_requirement_discovery import DiscoveredTaskRequirement
from app.schemas.plan import LocalizationTarget, PlanStep, StructuredPlan


# ═══════════════════════════════════════════════════════════════════════════
# 1. Intent Router Tests
# ═══════════════════════════════════════════════════════════════════════════

class TestIntentRouter:
    """Verifies natural-language prompt classification, ambiguity detection, and routing."""

    def test_classify_security_fix_intent(self):
        router = IntentRouter()
        res = router.classify_intent("Fix critical SQL injection vulnerability and sanitize user input in auth route")
        assert res.primary_intent == TaskIntent.SECURITY_FIX
        assert "security" in res.affected_layers
        assert not res.is_ambiguous
        assert res.confidence >= 0.80

    def test_classify_bug_fix_intent(self):
        router = IntentRouter()
        res = router.classify_intent("Fix crash and traceback when repository has no commit history")
        assert res.primary_intent == TaskIntent.BUG_FIX
        assert not res.is_ambiguous

    def test_classify_performance_intent(self):
        router = IntentRouter()
        res = router.classify_intent("Optimize query latency and slow throughput in repository search API")
        assert res.primary_intent == TaskIntent.PERFORMANCE
        assert not res.is_ambiguous

    def test_classify_database_intent(self):
        router = IntentRouter()
        res = router.classify_intent("Add status column to tasks table and create Alembic database migration")
        assert res.primary_intent == TaskIntent.DATABASE
        assert "database" in res.affected_layers
        assert not res.is_ambiguous

    def test_classify_frontend_intent(self):
        router = IntentRouter()
        res = router.classify_intent("Create a React modal component with Tailwind styling for user settings")
        assert res.primary_intent == TaskIntent.FRONTEND
        assert "frontend" in res.affected_layers

    def test_classify_new_feature_intent(self):
        router = IntentRouter()
        res = router.classify_intent("Add webhook integration support for GitHub issue events")
        assert res.primary_intent == TaskIntent.NEW_FEATURE

    def test_detect_ambiguous_short_prompt(self):
        router = IntentRouter()
        res = router.classify_intent("make it better")
        assert res.is_ambiguous is True
        assert res.ambiguity_reason is not None
        assert len(res.suggested_clarifications) > 0

    def test_detect_ambiguous_generic_help_prompt(self):
        router = IntentRouter()
        res = router.classify_intent("please help improve my code")
        assert res.is_ambiguous is True
        assert len(res.suggested_clarifications) > 0

    def test_cross_cutting_mixed_intents(self):
        router = IntentRouter()
        res = router.classify_intent("Fix auth bug and build frontend UI dialog with new database table migration")
        assert len(res.affected_layers) >= 3
        assert "frontend" in res.affected_layers
        assert "database" in res.affected_layers
        assert res.complexity_score >= 0.6


# ═══════════════════════════════════════════════════════════════════════════
# 2. Plan Critic Tests
# ═══════════════════════════════════════════════════════════════════════════

class TestPlanCritic:
    """Verifies adversarial plan review: requirement coverage, tests, safety, and DAG validation."""

    def test_approve_valid_comprehensive_plan(self):
        critic = PlanCritic()
        plan = StructuredPlan(
            task_id="task-100",
            plan_version=1,
            base_revision="abc1234",
            summary="Valid plan with tests and implementation",
            steps=[
                PlanStep(
                    step_id="step_1",
                    title="Inspect code",
                    description="Inspect existing endpoints",
                    action_type="inspect",
                    expected_files=["backend/app/api/v1/users.py"],
                    depends_on=[],
                ),
                PlanStep(
                    step_id="step_2",
                    title="Run tests",
                    description="Run pytest suite",
                    action_type="test",
                    expected_files=["tests/test_users.py"],
                    depends_on=["step_1"],
                ),
            ],
            tests_to_run=["pytest tests/test_users.py"],
            expected_files=["backend/app/api/v1/users.py", "tests/test_users.py"],
        )
        review = critic.review_plan(plan)
        assert review.is_approved is True
        assert review.blocking_count == 0
        assert review.score >= 0.90

    def test_reject_empty_plan(self):
        critic = PlanCritic()
        # Create a plan with empty steps via bypass or check empty handling
        plan = StructuredPlan.model_construct(
            task_id="task-empty",
            plan_version=1,
            base_revision="abc1234",
            summary="Empty plan",
            steps=[],
            tests_to_run=[],
            expected_files=[],
        )
        review = critic.review_plan(plan)
        assert review.is_approved is False
        assert review.blocking_count >= 1
        assert any(i.category == "invalid_targets" for i in review.issues)

    def test_reject_plan_targeting_forbidden_secret_files(self):
        critic = PlanCritic()
        plan = StructuredPlan(
            task_id="task-forbidden",
            plan_version=1,
            base_revision="abc1234",
            summary="Plan touching .env",
            steps=[
                PlanStep(
                    step_id="step_1",
                    title="Update credentials",
                    description="Write secrets",
                    action_type="modify",
                    expected_files=[".env"],
                    depends_on=[],
                ),
            ],
            tests_to_run=["pytest tests/"],
            expected_files=[".env"],
        )
        review = critic.review_plan(plan)
        assert review.is_approved is False
        assert review.blocking_count >= 1
        assert any(i.category == "security_risk" and i.severity == CriticSeverity.BLOCKING for i in review.issues)

    def test_reject_plan_with_dag_cycles(self):
        critic = PlanCritic()
        plan = StructuredPlan.model_construct(
            task_id="task-cyclic",
            plan_version=1,
            base_revision="abc1234",
            summary="Cyclic plan",
            steps=[
                PlanStep(
                    step_id="step_1",
                    title="Step 1",
                    description="Step 1",
                    action_type="modify",
                    expected_files=["file1.py"],
                    depends_on=["step_2"],
                ),
                PlanStep(
                    step_id="step_2",
                    title="Step 2",
                    description="Step 2",
                    action_type="modify",
                    expected_files=["file2.py"],
                    depends_on=["step_1"],
                ),
            ],
            tests_to_run=["pytest"],
            expected_files=["file1.py", "file2.py"],
        )
        review = critic.review_plan(plan)
        assert review.is_approved is False
        assert review.blocking_count >= 1
        assert any(i.category == "dependency_cycle" for i in review.issues)

    def test_warn_missing_tests(self):
        critic = PlanCritic()
        plan = StructuredPlan(
            task_id="task-notests",
            plan_version=1,
            base_revision="abc1234",
            summary="Plan with no tests",
            steps=[
                PlanStep(
                    step_id="step_1",
                    title="Modify code",
                    description="Update billing logic",
                    action_type="modify",
                    expected_files=["backend/app/billing.py"],
                    depends_on=[],
                ),
            ],
            tests_to_run=[],
            expected_files=["backend/app/billing.py"],
        )
        review = critic.review_plan(plan)
        assert review.warning_count >= 1
        assert any(i.category == "missing_tests" for i in review.issues)

    def test_warn_missing_db_migration_when_models_changed(self):
        critic = PlanCritic()
        plan = StructuredPlan(
            task_id="task-db-nomigration",
            plan_version=1,
            base_revision="abc1234",
            summary="Plan modifying models without migration",
            steps=[
                PlanStep(
                    step_id="step_1",
                    title="Update model",
                    description="Add column to SQLAlchemy models",
                    action_type="modify",
                    expected_files=["backend/app/models/user.py"],
                    depends_on=[],
                ),
            ],
            tests_to_run=["pytest tests/"],
            expected_files=["backend/app/models/user.py"],
        )
        review = critic.review_plan(plan)
        assert any(i.category == "database_migration" for i in review.issues)

    def test_block_uncovered_critical_requirement(self):
        critic = PlanCritic()
        reqs = [
            DiscoveredTaskRequirement(
                requirement_id="REQ-CRIT-1",
                description="Sanitize input against XSS attacks",
                category="security",
                priority="CRITICAL",
                affected_files=["backend/app/auth.py"],
            ),
        ]
        plan = StructuredPlan(
            task_id="task-req-missing",
            plan_version=1,
            base_revision="abc1234",
            summary="Plan omitting critical requirement",
            steps=[
                PlanStep(
                    step_id="step_1",
                    title="Unrelated change",
                    description="Update landing page styling",
                    action_type="modify",
                    expected_files=["frontend/src/landing.tsx"],
                    requirement_ids=[],
                    depends_on=[],
                ),
            ],
            tests_to_run=["npm test"],
            expected_files=["frontend/src/landing.tsx"],
        )
        review = critic.review_plan(plan, requirements=reqs)
        assert review.is_approved is False
        assert review.blocking_count >= 1
        assert any(i.category == "requirement_coverage" and i.severity == CriticSeverity.BLOCKING for i in review.issues)
