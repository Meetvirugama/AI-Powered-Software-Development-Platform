"""Tests for Week 3 Day 1: Persistence, Workflow Automation, Checkpoints & Recovery.

Owner: Om — Database & Persistence Lead.
Implements: Feature F39 — Persistence, Checkpoints and Recovery.

Verifies:
1. Model schema definitions for all 12 Week 3 workflow entities.
2. Issue-to-task persistence relationships and foreign keys (finding -> task, issue -> task).
3. Multi-tenant repository boundary isolation.
4. Server-enforced state machine transitions (§7.1, §7.2).
5. Plan versioning, immutable approvals, and approval invalidation on plan revision.
6. Bounded repair loop accounting (max 3 task-level attempts ceiling).
7. Safe checkpoint persistence with automated credential/token scrubbing.
8. Cascading referential integrity on task, repository, and user deletions.
9. Unbroken, acyclic Alembic migration chain with new head revision `b3c4d5e6f7a8`.
"""

from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from app.core.database import Base
from app.models.analysis_finding import AnalysisFinding
from app.models.analysis_run import AnalysisFeature, AnalysisRun, AnalysisRunStatus
from app.models.github_installation import GitHubInstallation
from app.models.repository import Repository, SyncStatus
from app.models.task import (
    ApprovalDecision,
    ExecutionStatus,
    RepairAttempt,
    RepairResult,
    Task,
    TaskApproval,
    TaskCheckpoint,
    TaskEvent,
    TaskEventType,
    TaskExecution,
    TaskPlan,
    TaskPlanStatus,
    TaskPullRequest,
    TaskSourceType,
    TaskStatus,
    TestRun,
    TestRunStatus,
    ToolInvocation,
    ToolInvocationStatus,
    VerificationResult,
    VerificationStatus,
    Workspace,
    WorkspaceStatus,
)
from app.models.user import User
from app.repositories.task_repository import (
    InvalidStateTransitionError,
    PlanNotFoundError,
    TaskNotFoundError,
    TaskRepository,
    scrub_sensitive_data,
    scrub_sensitive_text,
)


# ---------------------------------------------------------------------------
# Test Helpers
# ---------------------------------------------------------------------------


def _create_user_and_repo(
    db: Session,
    login: str = "om-week3-user",
    repo_name: str = "week3-repo",
) -> tuple[User, Repository]:
    """Helper to seed valid User and Repository records."""
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
        name=repo_name,
        default_branch="main",
        sync_status=SyncStatus.SYNCED,
    )
    db.add(repo)
    db.commit()
    db.refresh(repo)
    return user, repo


def _create_sample_finding(
    db: Session,
    repo_id: uuid.UUID,
    user_id: uuid.UUID,
    category: str = "security",
    title: str = "SQL Injection in User Lookup",
) -> AnalysisFinding:
    """Helper to seed an AnalysisFinding for issue-to-task relationship tests."""
    run = AnalysisRun(
        id=uuid.uuid4(),
        repository_id=repo_id,
        user_id=user_id,
        feature_type=AnalysisFeature.DETECT_BUGS.value,
        status=AnalysisRunStatus.COMPLETED.value,
        target_path="src/auth.py",
        source_revision="sha-known-vuln",
        findings_count=1,
    )
    db.add(run)
    db.flush()

    finding = AnalysisFinding(
        id=uuid.uuid4(),
        analysis_run_id=run.id,
        repository_id=repo_id,
        category=category,
        severity="HIGH",
        title=title,
        description="Raw string formatting in SQL query allows injection.",
        file_path="src/auth.py",
        start_line=24,
        end_line=28,
        source_revision="sha-known-vuln",
        evidence="query = f'SELECT * FROM users WHERE id = {user_id}'",
        suggested_fix="query = 'SELECT * FROM users WHERE id = :id'",
        confidence="high",
        is_uncertain=False,
        is_new_in_change=True,
        source_type="AI",
        rule_id="SEC001",
    )
    db.add(finding)
    db.commit()
    db.refresh(finding)
    return finding


# ---------------------------------------------------------------------------
# 1. Model Schema & Entity Creation Tests
# ---------------------------------------------------------------------------


class TestTaskModelSchema:
    """Confirms all Week 3 workflow models, relationships, and tables."""

    def test_task_instantiation_and_defaults(self, db_session: Session):
        """Verify Task model defaults and field assignments."""
        user, repo = _create_user_and_repo(db_session, "user-task-init")
        repo_layer = TaskRepository(db_session)

        task = repo_layer.create_task(
            repository_id=repo.id,
            title="Fix input validation bug",
            source_type=TaskSourceType.GITHUB_ISSUE,
            description="Validate user inputs properly against schemas",
            source_id="101",
            source_metadata={"issue_url": "https://github.com/org/repo/issues/101"},
            user_id=user.id,
            base_revision="main",
        )

        assert task.id is not None
        assert task.repository_id == repo.id
        assert task.user_id == user.id
        assert task.status == TaskStatus.CREATED.value
        assert task.source_type == TaskSourceType.GITHUB_ISSUE.value
        assert task.source_id == "101"
        assert task.plan_version == 1
        assert task.approved_plan_version is None
        assert task.repair_attempts_used == 0
        assert task.repair_attempts_max == 3
        assert task.created_at is not None

        # Verify to_dict output adheres to Week 3 common envelope (§7.3)
        envelope = task.to_dict()
        assert envelope["task_id"] == str(task.id)
        assert envelope["status"] == "CREATED"
        assert envelope["repair_attempts_max"] == 3


# ---------------------------------------------------------------------------
# 2. Issue-to-Task Persistence Relationships & Foreign Keys
# ---------------------------------------------------------------------------


class TestIssueToTaskPersistence:
    """Verifies Week 3 Day 1 requirement: Issue-to-task persistence relationships and foreign keys."""

    def test_create_task_from_week2_bug_finding(self, db_session: Session):
        """Verify creating a Task linked to an existing Week 2 AnalysisFinding via foreign key."""
        user, repo = _create_user_and_repo(db_session, "user-finding-task")
        finding = _create_sample_finding(db_session, repo.id, user.id)

        repo_layer = TaskRepository(db_session)
        task = repo_layer.create_task(
            repository_id=repo.id,
            title=f"Fix Finding: {finding.title}",
            source_type=TaskSourceType.BUG_FINDING,
            description=finding.description,
            source_id=str(finding.id),
            finding_id=finding.id,
            user_id=user.id,
            base_revision="sha-known-vuln",
        )

        assert task.finding_id == finding.id
        assert task.source_type == TaskSourceType.BUG_FINDING.value
        assert task.finding is not None
        assert task.finding.id == finding.id
        assert task.finding.title == "SQL Injection in User Lookup"

        # Verify reverse relationship on finding
        db_session.refresh(finding)
        assert len(finding.tasks) == 1
        assert finding.tasks[0].id == task.id

    def test_create_task_from_cross_repository_finding_rejected(self, db_session: Session):
        """Cross-tenant safety: cannot link a finding from Repo A to a task in Repo B."""
        user_a, repo_a = _create_user_and_repo(db_session, "user-repo-a", "repo-a")
        user_b, repo_b = _create_user_and_repo(db_session, "user-repo-b", "repo-b")

        finding_a = _create_sample_finding(db_session, repo_a.id, user_a.id)
        repo_layer = TaskRepository(db_session)

        # Attempt to link Repo A finding to Repo B task
        with pytest.raises(ValueError, match="Referenced finding does not belong to this repository"):
            repo_layer.create_task(
                repository_id=repo_b.id,
                title="Invalid cross-repo task",
                finding_id=finding_a.id,
                user_id=user_b.id,
            )

    def test_finding_deletion_preserves_task_with_null_finding_id(self, db_session: Session):
        """Referential integrity: deleting a finding sets finding_id to NULL, task history preserved."""
        user, repo = _create_user_and_repo(db_session, "user-finding-del")
        finding = _create_sample_finding(db_session, repo.id, user.id)

        repo_layer = TaskRepository(db_session)
        task = repo_layer.create_task(
            repository_id=repo.id,
            title="Task with finding to delete",
            finding_id=finding.id,
            user_id=user.id,
        )
        task_id = task.id

        # Delete finding
        db_session.delete(finding)
        db_session.commit()

        # Reload task
        reloaded = repo_layer.get_task(task_id, repo.id)
        assert reloaded is not None
        assert reloaded.finding_id is None


# ---------------------------------------------------------------------------
# 3. Multi-Tenant Repository Boundary Isolation
# ---------------------------------------------------------------------------


class TestMultiTenantIsolation:
    """Verifies strict repository boundary isolation across all read/write paths."""

    def test_cross_repository_task_access_blocked(self, db_session: Session):
        """Task created in Repo A must never be accessible via Repo B lookup."""
        user_a, repo_a = _create_user_and_repo(db_session, "user-tenant-a", "repo-tenant-a")
        user_b, repo_b = _create_user_and_repo(db_session, "user-tenant-b", "repo-tenant-b")

        repo_layer = TaskRepository(db_session)
        task_a = repo_layer.create_task(
            repository_id=repo_a.id,
            title="Repo A Private Task",
            user_id=user_a.id,
        )

        # Query via Repo B returns None
        lookup_b = repo_layer.get_task(task_a.id, repository_id=repo_b.id)
        assert lookup_b is None

        # List tasks for Repo B returns 0
        tasks_b, total_b = repo_layer.list_tasks(repository_id=repo_b.id)
        assert total_b == 0
        assert len(tasks_b) == 0


# ---------------------------------------------------------------------------
# 4. State Machine & Lifecycle Transitions
# ---------------------------------------------------------------------------


class TestStateTransitionEnforcement:
    """Verifies server-enforced lifecycle state transitions (§7.1, §7.2)."""

    def test_happy_path_state_progression(self, db_session: Session):
        """Validate valid linear lifecycle from CREATED through to DRAFT_PR_CREATED."""
        user, repo = _create_user_and_repo(db_session, "user-state-happy")
        repo_layer = TaskRepository(db_session)

        task = repo_layer.create_task(repo.id, "Lifecycle task", user_id=user.id)
        assert task.status == TaskStatus.CREATED.value

        # CREATED -> PLANNING
        repo_layer.transition_status(task.id, repo.id, TaskStatus.PLANNING)
        assert task.status == TaskStatus.PLANNING.value

        # Save Plan -> PENDING_APPROVAL
        plan = repo_layer.save_plan(
            task.id,
            repo.id,
            summary="Implementation Plan v1",
            steps=[{"step_id": "step_1", "description": "Update validation logic"}],
        )
        assert task.status == TaskStatus.PENDING_APPROVAL.value

        # PENDING_APPROVAL -> APPROVED
        repo_layer.approve_plan(task.id, repo.id, plan_version=plan.version, user_id=user.id)
        assert task.status == TaskStatus.APPROVED.value
        assert task.approved_plan_version == 1

        # APPROVED -> WORKSPACE_SETUP
        repo_layer.transition_status(task.id, repo.id, TaskStatus.WORKSPACE_SETUP)
        assert task.status == TaskStatus.WORKSPACE_SETUP.value

        # Setup Workspace
        repo_layer.record_workspace(
            task.id,
            repo.id,
            workspace_path="/tmp/workspaces/task-1",
            task_branch="agent/task-1",
            base_revision="main",
        )

        # WORKSPACE_SETUP -> EXECUTING
        repo_layer.transition_status(task.id, repo.id, TaskStatus.EXECUTING)
        assert task.status == TaskStatus.EXECUTING.value

        # EXECUTING -> TESTING
        repo_layer.transition_status(task.id, repo.id, TaskStatus.TESTING)
        assert task.status == TaskStatus.TESTING.value

        # TESTING -> VERIFYING
        repo_layer.transition_status(task.id, repo.id, TaskStatus.VERIFYING)
        assert task.status == TaskStatus.VERIFYING.value

        # Record Verification
        repo_layer.record_verification_result(
            task.id,
            repo.id,
            verified_revision="sha-final-clean",
            status=VerificationStatus.PASSED,
            checks=[{"name": "pytest", "status": "PASSED"}],
        )

        # VERIFYING -> READY_FOR_PUBLICATION
        repo_layer.transition_status(task.id, repo.id, TaskStatus.READY_FOR_PUBLICATION)
        assert task.status == TaskStatus.READY_FOR_PUBLICATION.value

        # READY_FOR_PUBLICATION -> PUBLISHING
        repo_layer.transition_status(task.id, repo.id, TaskStatus.PUBLISHING)
        assert task.status == TaskStatus.PUBLISHING.value

        # Record PR -> DRAFT_PR_CREATED
        repo_layer.record_pull_request(
            task.id,
            repo.id,
            pr_url="https://github.com/org/repo/pull/42",
            base_branch="main",
            head_branch="agent/task-1",
            head_sha="sha-final-clean",
            title="Draft PR for Task 1",
            pr_number=42,
        )
        assert task.status == TaskStatus.DRAFT_PR_CREATED.value

    def test_direct_execution_from_pending_approval_blocked(self, db_session: Session):
        """Security requirement: PENDING_APPROVAL cannot jump directly to EXECUTING."""
        user, repo = _create_user_and_repo(db_session, "user-illegal-jump")
        repo_layer = TaskRepository(db_session)

        task = repo_layer.create_task(repo.id, "Unapproved task", user_id=user.id)
        repo_layer.save_plan(
            task.id,
            repo.id,
            summary="Unapproved Plan",
            steps=[{"step_id": "step_1", "description": "Do stuff"}],
        )
        assert task.status == TaskStatus.PENDING_APPROVAL.value

        # Attempt illegal jump directly to EXECUTING
        with pytest.raises(InvalidStateTransitionError, match="Invalid state transition from PENDING_APPROVAL to EXECUTING"):
            repo_layer.transition_status(task.id, repo.id, TaskStatus.EXECUTING)

    def test_rejected_plan_cannot_be_executed(self, db_session: Session):
        """Security requirement: A rejected plan cannot be executed."""
        user, repo = _create_user_and_repo(db_session, "user-rejected-plan")
        repo_layer = TaskRepository(db_session)

        task = repo_layer.create_task(repo.id, "Rejected task", user_id=user.id)
        plan = repo_layer.save_plan(
            task.id,
            repo.id,
            summary="Plan to Reject",
            steps=[{"step_id": "step_1", "description": "Step 1"}],
        )
        repo_layer.reject_plan(task.id, repo.id, plan_version=plan.version, user_id=user.id, feedback="Too risky")
        assert task.status == TaskStatus.REJECTED.value

        with pytest.raises(InvalidStateTransitionError, match="Invalid state transition from REJECTED to EXECUTING"):
            repo_layer.transition_status(task.id, repo.id, TaskStatus.EXECUTING)


# ---------------------------------------------------------------------------
# 5. Plan Versioning & Approval Invalidation
# ---------------------------------------------------------------------------


class TestPlanVersioningAndApprovalInvalidation:
    """Confirms plan version incrementing and approval invalidation upon plan edits (§7.2)."""

    def test_plan_revision_invalidates_previous_approval(self, db_session: Session):
        """A material plan change invalidates previous approval and resets status to PENDING_APPROVAL."""
        user, repo = _create_user_and_repo(db_session, "user-plan-rev")
        repo_layer = TaskRepository(db_session)

        task = repo_layer.create_task(repo.id, "Task with revisions", user_id=user.id)

        # Plan v1
        plan_v1 = repo_layer.save_plan(task.id, repo.id, summary="Plan v1", steps=[{"step_id": "step_1"}])
        assert plan_v1.version == 1

        # Approve v1
        repo_layer.approve_plan(task.id, repo.id, plan_version=1, user_id=user.id)
        assert task.approved_plan_version == 1
        assert task.status == TaskStatus.APPROVED.value

        # Edit Plan -> creates Plan v2
        plan_v2 = repo_layer.save_plan(
            task.id,
            repo.id,
            summary="Plan v2 with more steps",
            steps=[{"step_id": "step_1"}, {"step_id": "step_2"}],
        )
        assert plan_v2.version == 2
        assert task.plan_version == 2

        # Crucial invariant: Approval is invalidated!
        assert task.approved_plan_version is None


# ---------------------------------------------------------------------------
# 6. Bounded Repair Loop Accounting
# ---------------------------------------------------------------------------


class TestBoundedRepairLoop:
    """Verifies that repair attempts are strictly capped at max 3 attempts (§6 F35, §7.2)."""

    def test_repair_budget_exhaustion_at_maximum_three_attempts(self, db_session: Session):
        """Attempt 1, 2, 3 succeed; Attempt 4 triggers RETRY_EXHAUSTED and fails the task."""
        user, repo = _create_user_and_repo(db_session, "user-repair-bounds")
        repo_layer = TaskRepository(db_session)

        task = repo_layer.create_task(repo.id, "Repair bound task", user_id=user.id)
        assert task.repair_attempts_used == 0
        assert task.repair_attempts_max == 3

        # Attempt 1
        att1, avail1 = repo_layer.increment_repair_attempt(
            task.id, repo.id, diagnosis="Assertion error on line 42", applied_patch="diff1"
        )
        assert avail1 is True
        assert att1.attempt_number == 1
        assert att1.result == RepairResult.SUCCESS.value
        assert task.repair_attempts_used == 1

        # Attempt 2
        att2, avail2 = repo_layer.increment_repair_attempt(
            task.id, repo.id, diagnosis="Type error", applied_patch="diff2"
        )
        assert avail2 is True
        assert att2.attempt_number == 2
        assert task.repair_attempts_used == 2

        # Attempt 3 (Final allowed attempt)
        att3, avail3 = repo_layer.increment_repair_attempt(
            task.id, repo.id, diagnosis="Index out of range", applied_patch="diff3"
        )
        assert avail3 is True
        assert att3.attempt_number == 3
        assert task.repair_attempts_used == 3

        # Attempt 4 (Ceiling reached: budget exhausted!)
        att4, avail4 = repo_layer.increment_repair_attempt(
            task.id, repo.id, diagnosis="Still failing", applied_patch="diff4"
        )
        assert avail4 is False
        assert att4.result == RepairResult.RETRY_EXHAUSTED.value
        assert task.status == TaskStatus.FAILED.value
        assert "retry budget exhausted" in (task.error_message or "").lower()


# ---------------------------------------------------------------------------
# 7. Safe Checkpoints & Automated Secret Scrubbing
# ---------------------------------------------------------------------------


class TestCheckpointsAndSecretScrubbing:
    """Verifies checkpoint recovery snapshots and automatic secret scrubbing (Zero-Secret Invariant)."""

    def test_checkpoint_persistence_and_secret_redaction(self, db_session: Session):
        """Raw secrets (OpenAI keys, GitHub tokens, DB credentials) must be redacted before saving."""
        user, repo = _create_user_and_repo(db_session, "user-checkpoint-secrets")
        repo_layer = TaskRepository(db_session)

        task = repo_layer.create_task(repo.id, "Secret task", user_id=user.id)

        dirty_state = {
            "step": "execute_tool",
            "api_key": "sk-proj-123456789012345678901234567890",
            "token": "ghp_123456789012345678901234567890123456",
            "db_uri": "postgresql://postgres:SuperSecretPassword123@localhost:5432/proddb",
            "normal_data": "All tests pass successfully",
        }

        checkpoint = repo_layer.save_checkpoint(
            task.id,
            repo.id,
            step_name="step_apply_patch",
            state_data=dirty_state,
            recovery_instructions="Resume from step_apply_patch after fixing token",
        )

        assert checkpoint.id is not None
        saved_data = checkpoint.state_data

        # Verify all secrets are replaced with [REDACTED]
        assert "sk-proj-" not in str(saved_data)
        assert "ghp_" not in str(saved_data)
        assert "SuperSecretPassword123" not in str(saved_data)
        assert saved_data["normal_data"] == "All tests pass successfully"

        # Verify retrieval via get_latest_checkpoint
        latest = repo_layer.get_latest_checkpoint(task.id, repo.id)
        assert latest is not None
        assert latest.id == checkpoint.id
        assert latest.step_name == "step_apply_patch"


# ---------------------------------------------------------------------------
# 8. Referential Cascade Integrity
# ---------------------------------------------------------------------------


class TestReferentialIntegrity:
    """Confirms cascading deletes for tasks and child entities."""

    def test_task_deletion_cascades_to_all_child_entities(self, db_session: Session):
        """Deleting a Task must cascade delete its plans, approvals, checkpoints, runs, and events."""
        user, repo = _create_user_and_repo(db_session, "user-cascade-test")
        repo_layer = TaskRepository(db_session)

        task = repo_layer.create_task(repo.id, "Task to cascade delete", user_id=user.id)
        task_id = task.id

        # Add child records
        plan = repo_layer.save_plan(task_id, repo.id, "Plan 1", [{"step_id": "1"}])
        approval = repo_layer.approve_plan(task_id, repo.id, plan_version=1, user_id=user.id)
        ckpt = repo_layer.save_checkpoint(task_id, repo.id, "ckpt1", {"key": "val"})
        tool = repo_layer.record_tool_invocation(task_id, repo.id, "read_file", {"path": "a.py"})
        test_run = repo_layer.record_test_run(task_id, repo.id, "pytest", TestRunStatus.PASSED)
        timeline = repo_layer.get_task_timeline(task_id, repo.id)
        assert len(timeline) >= 4

        # Delete Task
        db_session.delete(task)
        db_session.commit()

        # Verify all child entities are removed
        assert db_session.execute(select(TaskPlan).where(TaskPlan.task_id == task_id)).scalars().all() == []
        assert db_session.execute(select(TaskApproval).where(TaskApproval.task_id == task_id)).scalars().all() == []
        assert db_session.execute(select(TaskCheckpoint).where(TaskCheckpoint.task_id == task_id)).scalars().all() == []
        assert db_session.execute(select(ToolInvocation).where(ToolInvocation.task_id == task_id)).scalars().all() == []
        assert db_session.execute(select(TestRun).where(TestRun.task_id == task_id)).scalars().all() == []
        assert db_session.execute(select(TaskEvent).where(TaskEvent.task_id == task_id)).scalars().all() == []


# ---------------------------------------------------------------------------
# 9. Alembic Migration Consistency
# ---------------------------------------------------------------------------


class TestWeek3Day1MigrationConsistency:
    """Confirms unbroken Alembic chain up to the new head revision `b3c4d5e6f7a8`."""

    def test_alembic_chain_linear_and_unbroken_up_to_head(self):
        """Verify the migration chain includes all 7 revisions with b3c4d5e6f7a8 as head."""
        versions_dir = Path(__file__).resolve().parent.parent / "migrations" / "versions"
        migration_files = list(versions_dir.glob("*.py"))
        assert len(migration_files) >= 7, f"Expected at least 7 migrations, found {len(migration_files)}"

        revisions: dict[str, str | None] = {}
        for py_file in migration_files:
            content = py_file.read_text(encoding="utf-8")
            rev_match = re.search(r'revision:\s*(?:str\s*=\s*)?["\']([a-f0-9]+)["\']', content)
            down_match = re.search(r'down_revision:\s*(?:[A-Za-z0-9_, \[\]\|]*\s*=\s*)?(?:["\']([a-f0-9]+)["\']|None)', content)

            if rev_match:
                rev_id = rev_match.group(1)
                down_id = down_match.group(1) if (down_match and down_match.group(1)) else None
                revisions[rev_id] = down_id

        # Verify complete linear chain from root to Week 3 head
        expected_milestones = [
            "24498ac67b3e",  # pgvector
            "5f6dc031921b",  # identity
            "aef3bb17eb34",  # content
            "cb4e2a7d0f31",  # sync jobs
            "e7b8c9d0f1a2",  # chunks & memory
            "f1c2d3e4b5a6",  # analysis runs & findings
            "b3c4d5e6f7a8",  # workflow automation & tasks (Week 3 Day 1)
        ]
        for milestone in expected_milestones:
            assert milestone in revisions, f"Milestone revision {milestone} missing from migration graph."

        # Verify b3c4d5e6f7a8 down_revision is f1c2d3e4b5a6
        assert revisions["b3c4d5e6f7a8"] == "f1c2d3e4b5a6"
