"""Tests for Week 3 Day 2: Task Planning, Plan Versioning & Human Approval Persistence.

Owner: Om — Database & Persistence Lead.
Implements: Feature F32 — Task Planner and Human Approval & F39 — Persistence, Checkpoints and Recovery.

Verifies:
1. Task creation and persistence with full issue and requirement traceability.
2. Structured plan generation, versioning, and retrieval (latest and by version).
3. Plan listing returning all historical versions in ascending order.
4. Immutable plan approval strictly tied to specific plan version.
5. Plan rejection tied to specific version with feedback.
6. Error handling: approving non-existent plan versions raises PlanNotFoundError.
7. Plan revisions: invalidates previous approval, supersedes prior versions, resets task status to PENDING_APPROVAL.
8. Security gate: unapproved tasks cannot transition to EXECUTING.
9. Multi-tenant repository boundary isolation for plans and approvals.
10. Context gathering persistence (Week 2 intelligence context linked to task).
11. TaskHistoryService orchestration, session management, and app.state compatibility.
12. Ordered timeline event verification across planning and approval milestones.
13. Canonical to_dict() serialization envelopes conforming to Pydantic schemas.
14. Zero-credential persistence invariant in plan steps, problem statement, and feedback.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
import pytest
from sqlalchemy.orm import Session, sessionmaker

from app.core.database import Base
from app.models.analysis_finding import AnalysisFinding
from app.models.github_installation import GitHubInstallation
from app.models.repository import Repository, SyncStatus
from app.models.task import (
    ApprovalDecision,
    Task,
    TaskApproval,
    TaskCheckpoint,
    TaskEvent,
    TaskEventType,
    TaskPlan,
    TaskPlanStatus,
    TaskPullRequest,
    TaskSourceType,
    TaskStatus,
    Workspace,
)
from app.models.user import User
from app.repositories.task_repository import (
    InvalidStateTransitionError,
    PlanNotFoundError,
    TaskNotFoundError,
    TaskRepository,
)
from app.schemas.task import (
    TaskApprovalResponse,
    TaskPlanResponse,
    TaskResponse,
)
from app.services.task_history_service import TaskHistoryService


# ---------------------------------------------------------------------------
# Test Helpers
# ---------------------------------------------------------------------------


def _seed_user_and_repo(
    db: Session,
    login: str = "om-day2-user",
    repo_name: str = "day2-repo",
) -> tuple[User, Repository]:
    """Helper to seed valid User and Repository records for isolation testing."""
    user = User(
        id=uuid.uuid4(),
        github_id=f"gh_{uuid.uuid4().hex[:8]}",
        login=f"{login}_{uuid.uuid4().hex[:4]}",
        email=f"{login}@example.com",
    )
    db.add(user)
    db.flush()

    installation = GitHubInstallation(
        id=uuid.uuid4(),
        user_id=user.id,
        installation_id=f"inst_{uuid.uuid4().hex[:8]}",
        account_login=user.login,
        permissions={"contents": "write", "pull_requests": "write"},
    )
    db.add(installation)
    db.flush()

    repo = Repository(
        id=uuid.uuid4(),
        user_id=user.id,
        installation_id=installation.id,
        github_repo_id=f"repo_{uuid.uuid4().hex[:8]}",
        owner=user.login,
        name=f"{repo_name}-{uuid.uuid4().hex[:4]}",
        default_branch="main",
        sync_status=SyncStatus.SYNCED,
    )
    db.add(repo)
    db.commit()
    db.refresh(user)
    db.refresh(repo)
    return user, repo


# ---------------------------------------------------------------------------
# 1. Task Intake & Plan Versioning Tests
# ---------------------------------------------------------------------------


class TestTaskPlanningAndVersioning:
    """Verifies task creation, plan generation, and plan versioning."""

    def test_task_creation_and_persistence_from_issue_and_requirement(self, db_session: Session):
        """Task creation records source traceability and emits initial timeline event."""
        user, repo = _seed_user_and_repo(db_session, "user-intake")
        repo_layer = TaskRepository(db_session)

        # 1. Create from GitHub Issue
        issue_task = repo_layer.create_task(
            repository_id=repo.id,
            title="Fix authentication token refresh race condition",
            source_type=TaskSourceType.GITHUB_ISSUE,
            description="Race condition occurring in token manager during concurrent calls",
            source_id="42",
            source_metadata={"issue_number": 42, "labels": ["bug", "auth"]},
            user_id=user.id,
            base_revision="main",
        )
        assert issue_task.status == TaskStatus.CREATED.value
        assert issue_task.plan_version == 1
        assert issue_task.approved_plan_version is None
        assert issue_task.source_id == "42"

        # Verify initial event
        timeline = repo_layer.get_task_timeline(issue_task.id, repo.id)
        assert len(timeline) == 1
        assert timeline[0].event_type == TaskEventType.ISSUE_IMPORTED.value
        assert timeline[0].event_data["source_id"] == "42"

        # 2. Create from User Requirement
        req_task = repo_layer.create_task(
            repository_id=repo.id,
            title="Add health check memory usage metric",
            source_type=TaskSourceType.USER_REQUIREMENT,
            user_id=user.id,
        )
        assert req_task.source_type == TaskSourceType.USER_REQUIREMENT.value
        req_timeline = repo_layer.get_task_timeline(req_task.id, repo.id)
        assert req_timeline[0].event_type == TaskEventType.TASK_CREATED.value

    def test_plan_creation_advances_task_to_pending_approval(self, db_session: Session):
        """Saving a plan creates version 1, sets status PROPOSED, and advances task to PENDING_APPROVAL."""
        user, repo = _seed_user_and_repo(db_session, "user-plan-v1")
        repo_layer = TaskRepository(db_session)

        task = repo_layer.create_task(repo.id, "Plan creation test", user_id=user.id)
        assert task.status == TaskStatus.CREATED.value

        plan = repo_layer.save_plan(
            task_id=task.id,
            repository_id=repo.id,
            summary="Refactor validation engine",
            steps=[
                {"step_id": "step_1", "description": "Inspect validation boundaries", "expected_files": ["app/validation.py"]},
                {"step_id": "step_2", "description": "Add boundary check", "expected_files": ["app/validation.py"]},
            ],
            problem_statement="Input boundaries are not strictly enforced",
            expected_files=["app/validation.py"],
            tests_to_run=["pytest tests/test_validation.py"],
            validation_strategy="Run regression tests",
            risks=["Minor risk of rejecting borderline legacy payloads"],
        )

        assert plan.version == 1
        assert plan.status == TaskPlanStatus.PROPOSED.value
        assert len(plan.steps) == 2
        assert task.plan_version == 1
        assert task.status == TaskStatus.PENDING_APPROVAL.value

        # Verify timeline event
        timeline = repo_layer.get_task_timeline(task.id, repo.id)
        assert any(e.event_type == TaskEventType.PLAN_GENERATED.value for e in timeline)

    def test_get_plan_latest_and_by_specific_version(self, db_session: Session):
        """get_plan returns the latest version by default or a specific requested version."""
        user, repo = _seed_user_and_repo(db_session, "user-plan-get")
        repo_layer = TaskRepository(db_session)

        task = repo_layer.create_task(repo.id, "Multi-version plan", user_id=user.id)

        # Create Plan v1
        p1 = repo_layer.save_plan(task.id, repo.id, summary="Plan v1", steps=[{"step_id": "step_1"}])
        assert p1.version == 1

        # Create Plan v2
        p2 = repo_layer.save_plan(task.id, repo.id, summary="Plan v2", steps=[{"step_id": "step_1"}, {"step_id": "step_2"}])
        assert p2.version == 2

        # Fetch v1 specifically
        fetched_v1 = repo_layer.get_plan(task.id, repo.id, version=1)
        assert fetched_v1 is not None
        assert fetched_v1.version == 1
        assert fetched_v1.summary == "Plan v1"

        # Fetch v2 specifically
        fetched_v2 = repo_layer.get_plan(task.id, repo.id, version=2)
        assert fetched_v2 is not None
        assert fetched_v2.version == 2
        assert fetched_v2.summary == "Plan v2"

        # Fetch latest (version=None)
        latest = repo_layer.get_plan(task.id, repo.id, version=None)
        assert latest is not None
        assert latest.version == 2

    def test_list_plans_returns_all_versions_ordered(self, db_session: Session):
        """list_plans returns all plan versions for the task ordered ascending."""
        user, repo = _seed_user_and_repo(db_session, "user-plan-list")
        repo_layer = TaskRepository(db_session)

        task = repo_layer.create_task(repo.id, "Ordered plans test", user_id=user.id)

        repo_layer.save_plan(task.id, repo.id, summary="v1", steps=[{"step_id": "1"}])
        repo_layer.save_plan(task.id, repo.id, summary="v2", steps=[{"step_id": "2"}])
        repo_layer.save_plan(task.id, repo.id, summary="v3", steps=[{"step_id": "3"}])

        all_plans = repo_layer.list_plans(task.id, repo.id)
        assert len(all_plans) == 3
        assert [p.version for p in all_plans] == [1, 2, 3]


# ---------------------------------------------------------------------------
# 2. Plan Approval & Rejection Workflow Tests
# ---------------------------------------------------------------------------


class TestPlanApprovalWorkflow:
    """Verifies approval, rejection, and invalidation rules (§6 F32, §7.2)."""

    def test_approve_plan_tied_to_specific_version(self, db_session: Session):
        """Approving a plan binds approval record to specific plan version and marks task APPROVED."""
        user, repo = _seed_user_and_repo(db_session, "user-approve")
        repo_layer = TaskRepository(db_session)

        task = repo_layer.create_task(repo.id, "Approval test", user_id=user.id)
        plan = repo_layer.save_plan(task.id, repo.id, summary="Plan v1", steps=[{"step_id": "s1"}])

        approval = repo_layer.approve_plan(
            task_id=task.id,
            repository_id=repo.id,
            plan_version=1,
            user_id=user.id,
            feedback="Plan looks solid and low-risk",
        )

        assert approval.decision == ApprovalDecision.APPROVED.value
        assert approval.plan_version == 1
        assert approval.user_id == user.id
        assert approval.feedback == "Plan looks solid and low-risk"

        # Verify task state
        assert task.approved_plan_version == 1
        assert task.status == TaskStatus.APPROVED.value
        assert plan.status == TaskPlanStatus.APPROVED.value

        # Verify lookup
        latest_approval = repo_layer.get_approval(task.id, repo.id, plan_version=1)
        assert latest_approval is not None
        assert latest_approval.id == approval.id

    def test_reject_plan_tied_to_specific_version_with_feedback(self, db_session: Session):
        """Rejecting a plan records immutable rejection and sets task status to REJECTED."""
        user, repo = _seed_user_and_repo(db_session, "user-reject")
        repo_layer = TaskRepository(db_session)

        task = repo_layer.create_task(repo.id, "Rejection test", user_id=user.id)
        plan = repo_layer.save_plan(task.id, repo.id, summary="Plan v1", steps=[{"step_id": "s1"}])

        approval = repo_layer.reject_plan(
            task_id=task.id,
            repository_id=repo.id,
            plan_version=1,
            user_id=user.id,
            feedback="Missing database migration step and rollback test",
        )

        assert approval.decision == ApprovalDecision.REJECTED.value
        assert approval.plan_version == 1
        assert approval.feedback == "Missing database migration step and rollback test"

        # Task state
        assert task.status == TaskStatus.REJECTED.value
        assert task.approved_plan_version is None
        assert plan.status == TaskPlanStatus.REJECTED.value

        # Timeline event
        timeline = repo_layer.get_task_timeline(task.id, repo.id)
        reject_events = [e for e in timeline if e.event_type == TaskEventType.PLAN_REJECTED.value]
        assert len(reject_events) == 1
        assert reject_events[0].event_data["feedback"] == "Missing database migration step and rollback test"

    def test_approving_nonexistent_plan_version_raises_error(self, db_session: Session):
        """Attempting to approve a version that was never created raises PlanNotFoundError."""
        user, repo = _seed_user_and_repo(db_session, "user-missing-plan")
        repo_layer = TaskRepository(db_session)

        task = repo_layer.create_task(repo.id, "Missing plan test", user_id=user.id)
        repo_layer.save_plan(task.id, repo.id, summary="Plan v1", steps=[{"step_id": "s1"}])

        with pytest.raises(PlanNotFoundError) as exc_info:
            repo_layer.approve_plan(task.id, repo.id, plan_version=99, user_id=user.id)
        assert "Plan version 99 does not exist" in str(exc_info.value)

    def test_plan_revision_supersedes_prior_plans_and_resets_status(self, db_session: Session):
        """Plan revision supersedes prior plans, invalidates approval, and resets status to PENDING_APPROVAL."""
        user, repo = _seed_user_and_repo(db_session, "user-supersede")
        repo_layer = TaskRepository(db_session)

        task = repo_layer.create_task(repo.id, "Revision invalidation test", user_id=user.id)

        # Plan v1 approved
        p1 = repo_layer.save_plan(task.id, repo.id, summary="Plan v1", steps=[{"step_id": "1"}])
        repo_layer.approve_plan(task.id, repo.id, plan_version=1, user_id=user.id)
        assert task.status == TaskStatus.APPROVED.value
        assert task.approved_plan_version == 1

        # Now revise to Plan v2
        p2 = repo_layer.save_plan(task.id, repo.id, summary="Plan v2 with revision", steps=[{"step_id": "1"}, {"step_id": "2"}])

        assert p2.version == 2
        assert p2.status == TaskPlanStatus.PROPOSED.value

        # Crucial invariants
        assert p1.status == TaskPlanStatus.SUPERSEDED.value
        assert task.approved_plan_version is None
        assert task.status == TaskStatus.PENDING_APPROVAL.value
        assert task.plan_version == 2

    def test_rejected_plan_cannot_be_executed(self, db_session: Session):
        """An unapproved or rejected plan cannot transition directly to EXECUTING."""
        user, repo = _seed_user_and_repo(db_session, "user-rejected-exec")
        repo_layer = TaskRepository(db_session)

        task = repo_layer.create_task(repo.id, "Rejected execution guard", user_id=user.id)
        repo_layer.save_plan(task.id, repo.id, summary="Plan v1", steps=[{"step_id": "1"}])
        repo_layer.reject_plan(task.id, repo.id, plan_version=1, user_id=user.id)

        with pytest.raises(InvalidStateTransitionError):
            repo_layer.transition_status(task.id, repo.id, TaskStatus.EXECUTING)


# ---------------------------------------------------------------------------
# 3. Multi-Tenant Repository Boundary Isolation
# ---------------------------------------------------------------------------


class TestMultiTenantPlanIsolation:
    """Verifies that plan queries and approvals enforce strict repository boundaries."""

    def test_cross_repository_plan_access_blocked(self, db_session: Session):
        """Repo A's plan cannot be fetched or listed via Repo B."""
        user_a, repo_a = _seed_user_and_repo(db_session, "user-a", "repo-a")
        _, repo_b = _seed_user_and_repo(db_session, "user-b", "repo-b")
        repo_layer = TaskRepository(db_session)

        task_a = repo_layer.create_task(repo_a.id, "Task in Repo A", user_id=user_a.id)
        repo_layer.save_plan(task_a.id, repo_a.id, summary="Plan for Repo A", steps=[{"step_id": "1"}])

        # Attempt to get plan using repo_b
        with pytest.raises(TaskNotFoundError):
            repo_layer.get_plan(task_a.id, repo_b.id, version=1)

        with pytest.raises(TaskNotFoundError):
            repo_layer.list_plans(task_a.id, repo_b.id)

    def test_cross_repository_approval_blocked(self, db_session: Session):
        """User B cannot approve Repo A's plan using Repo B repository scope."""
        user_a, repo_a = _seed_user_and_repo(db_session, "user-a-app", "repo-a-app")
        user_b, repo_b = _seed_user_and_repo(db_session, "user-b-app", "repo-b-app")
        repo_layer = TaskRepository(db_session)

        task_a = repo_layer.create_task(repo_a.id, "Task in Repo A", user_id=user_a.id)
        repo_layer.save_plan(task_a.id, repo_a.id, summary="Plan for Repo A", steps=[{"step_id": "1"}])

        with pytest.raises(TaskNotFoundError):
            repo_layer.approve_plan(task_a.id, repo_b.id, plan_version=1, user_id=user_b.id)


# ---------------------------------------------------------------------------
# 4. Context Gathering & Zero-Credential Persistence
# ---------------------------------------------------------------------------


class TestContextAndSecretScrubbing:
    """Verifies context update persistence and recursive credential scrubbing."""

    def test_update_task_context_persists_and_scrubs(self, db_session: Session):
        """Context summary updates base revision and scrubs secrets."""
        user, repo = _seed_user_and_repo(db_session, "user-context")
        repo_layer = TaskRepository(db_session)

        task = repo_layer.create_task(repo.id, "Context test", user_id=user.id)
        assert task.context_summary is None

        # Add context with secret embedded
        raw_context = "Context info: API_KEY = sk-proj-1234567890abcdef1234567890 in auth module."
        updated_task = repo_layer.update_task_context(
            task_id=task.id,
            repository_id=repo.id,
            context_summary=raw_context,
            base_revision="feat/auth-v2",
        )

        assert updated_task.base_revision == "feat/auth-v2"
        assert "sk-proj-" not in updated_task.context_summary
        assert "[REDACTED]" in updated_task.context_summary

    def test_sensitive_data_scrubbed_in_plan_and_feedback(self, db_session: Session):
        """Plan problem statement, steps, and approval feedback have secrets scrubbed."""
        user, repo = _seed_user_and_repo(db_session, "user-scrub")
        repo_layer = TaskRepository(db_session)

        task = repo_layer.create_task(repo.id, "Secret scrub task", user_id=user.id)

        plan = repo_layer.save_plan(
            task_id=task.id,
            repository_id=repo.id,
            summary="Plan with credentials",
            problem_statement="Token ghp_111122223333444455556666777788889999 was leaked",
            steps=[{"step_id": "1", "notes": "Use Bearer eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.doNotLeakThis"}],
        )

        assert "ghp_" not in plan.problem_statement
        assert "[REDACTED]" in plan.problem_statement
        assert "eyJ" not in str(plan.steps)
        assert "[REDACTED]" in str(plan.steps)

        approval = repo_layer.approve_plan(
            task_id=task.id,
            repository_id=repo.id,
            plan_version=1,
            user_id=user.id,
            feedback="Approved using token ghp_999988887777666655554444333322221111",
        )
        assert "ghp_" not in approval.feedback
        assert "[REDACTED]" in approval.feedback


# ---------------------------------------------------------------------------
# 5. TaskHistoryService & Serialization Tests
# ---------------------------------------------------------------------------


class TestTaskHistoryServiceAndSerialization:
    """Verifies TaskHistoryService orchestration and to_dict() schema alignment."""

    def test_task_history_service_full_lifecycle(self, db_session: Session):
        """TaskHistoryService orchestrates task intake, planning, approval, and timeline querying."""
        user, repo = _seed_user_and_repo(db_session, "user-service")
        service = TaskHistoryService(session=db_session)

        # 1. Create task
        task = service.create_task(
            repository_id=repo.id,
            title="Service lifecycle task",
            user_id=user.id,
        )
        assert task.id is not None

        # 2. Update context
        service.update_task_context(task.id, repo.id, context_summary="Enriched with symbols")

        # 3. Save plan
        plan = service.save_plan(
            task_id=task.id,
            repository_id=repo.id,
            summary="Refactor auth",
            steps=[{"step_id": "1", "description": "Update JWT logic"}],
        )
        assert plan.version == 1

        # 4. List plans
        plans = service.list_plans(task.id, repo.id)
        assert len(plans) == 1

        # 5. Approve plan
        approval = service.approve_plan(task.id, repo.id, plan_version=1, user_id=user.id, feedback="Approved")
        assert approval.decision == "APPROVED"

        # 6. Check approvals
        approvals = service.list_approvals(task.id, repo.id)
        assert len(approvals) == 1

        # 7. Timeline
        timeline = service.get_task_timeline(task.id, repo.id)
        event_types = [e.event_type for e in timeline]
        assert (TaskEventType.TASK_CREATED.value in event_types or TaskEventType.ISSUE_IMPORTED.value in event_types)
        assert TaskEventType.PLAN_GENERATED.value in event_types
        assert TaskEventType.PLAN_APPROVED.value in event_types

    def test_model_to_dict_matches_pydantic_schemas(self, db_session: Session):
        """to_dict() outputs validate against Day 1 Pydantic response schemas."""
        user, repo = _seed_user_and_repo(db_session, "user-schemas")
        service = TaskHistoryService(session=db_session)

        task = service.create_task(repo.id, "Schema validation task", user_id=user.id)
        plan = service.save_plan(task.id, repo.id, summary="Plan 1", steps=[{"step_id": "1", "description": "Do work"}])
        approval = service.approve_plan(task.id, repo.id, plan_version=1, user_id=user.id)

        # Validate TaskResponse
        task_dict = task.to_dict()
        task_resp = TaskResponse.model_validate(task_dict)
        assert task_resp.task_id == str(task.id)
        assert task_resp.plan_version == 1

        # Validate TaskPlanResponse
        plan_dict = plan.to_dict()
        plan_resp = TaskPlanResponse.model_validate(plan_dict)
        assert plan_resp.plan_id == str(plan.id)
        assert plan_resp.version == 1

        # Validate TaskApprovalResponse
        approval_dict = approval.to_dict()
        approval_resp = TaskApprovalResponse.model_validate(approval_dict)
        assert approval_resp.approval_id == str(approval.id)
        assert approval_resp.decision == "APPROVED"
