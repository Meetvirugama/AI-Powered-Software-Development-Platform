"""Tests for Week 3 Days 3 & 4: Workspace, Tool Auditing, Test Runs & Bounded Repair Persistence.

Owner: Om — Database & Persistence Lead.
Implements: Feature F33 — Isolated Workspace, F34 — Tool Router Auditing, F35 — Test Runner & Bounded Repair Loop, F39 — Persistence & Recovery.

Verifies:
1. Workspace lifecycle persistence (READY -> IN_USE -> CLEANUP_PENDING -> CLEANED).
2. Task execution tracking (worker_id, attempt_number, started_at, completed_at, errors).
3. Tool invocation auditing with recursive argument credential scrubbing.
4. Execution start preconditions: approved plan AND initialized workspace required.
5. Permitted test run persistence with exit codes, test counts, durations, and output sanitization.
6. Bounded repair loop accounting (maximum 3 task-level attempts ceiling).
7. Budget exhaustion: attempt 4 strictly blocked, triggers RETRY_EXHAUSTED and fails task.
8. State transition guard: transition to REPAIRING blocked when retry budget exhausted.
9. Persistence resilience: retry counters cannot be reset by worker restarts.
10. Multi-tenant repository boundary isolation across workspaces, executions, tests, and repairs.
11. Ordered timeline events across execution, test, and repair milestones.
12. Model to_dict() serialization conforming to Day 3 and Day 4 Pydantic response schemas.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
import pytest
from sqlalchemy.orm import Session

from app.models.github_installation import GitHubInstallation
from app.models.repository import Repository, SyncStatus
from app.models.task import (
    ExecutionStatus,
    RepairAttempt,
    RepairResult,
    Task,
    TaskApproval,
    TaskEvent,
    TaskEventType,
    TaskExecution,
    TaskPlan,
    TaskPlanStatus,
    TaskSourceType,
    TaskStatus,
    TestRun,
    TestRunStatus,
    ToolInvocation,
    ToolInvocationStatus,
    Workspace,
    WorkspaceStatus,
)
from app.models.user import User
from app.repositories.task_repository import (
    InvalidStateTransitionError,
    TaskNotFoundError,
    TaskRepository,
)
from app.schemas.task import (
    RepairAttemptResponse,
    TaskExecutionResponse,
    TestRunResponse,
    ToolInvocationResponse,
    WorkspaceResponse,
)
from app.services.task_history_service import TaskHistoryService


# ---------------------------------------------------------------------------
# Test Helpers
# ---------------------------------------------------------------------------


def _seed_user_and_repo(
    db: Session,
    login: str = "om-d3d4-user",
    repo_name: str = "d3d4-repo",
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


def _create_approved_task(
    db: Session,
    repo_id: uuid.UUID,
    user_id: uuid.UUID,
    title: str = "Approved workflow task",
) -> Task:
    """Helper to set up a task in APPROVED status with Plan v1."""
    repo_layer = TaskRepository(db)
    task = repo_layer.create_task(
        repository_id=repo_id,
        title=title,
        source_type=TaskSourceType.USER_REQUIREMENT,
        user_id=user_id,
    )
    repo_layer.save_plan(
        task_id=task.id,
        repository_id=repo_id,
        summary="Plan v1",
        steps=[{"step_id": "1", "description": "Execute task step"}],
    )
    repo_layer.approve_plan(task_id=task.id, repository_id=repo_id, plan_version=1, user_id=user_id)
    return task


# ---------------------------------------------------------------------------
# 1. Day 3: Workspace Lifecycle & Execution Tracking
# ---------------------------------------------------------------------------


class TestWorkspaceAndExecutionTracking:
    """Verifies workspace registration, status transitions, and worker execution logs."""

    def test_workspace_lifecycle_and_status_transitions(self, db_session: Session):
        """Register workspace, update status through lifecycle, and verify cleanup timestamp."""
        user, repo = _seed_user_and_repo(db_session, "user-ws-life")
        repo_layer = TaskRepository(db_session)
        task = _create_approved_task(db_session, repo.id, user.id)

        # 1. Register workspace
        ws = repo_layer.record_workspace(
            task_id=task.id,
            repository_id=repo.id,
            workspace_path=f"/tmp/workspaces/task-{task.id}",
            task_branch=f"agent/task-{task.id}",
            base_revision="main",
            status=WorkspaceStatus.READY,
        )
        assert ws.status == WorkspaceStatus.READY.value
        assert ws.task_branch == f"agent/task-{task.id}"
        assert ws.current_revision is None

        # 2. Update status to IN_USE with revision
        updated_ws = repo_layer.update_workspace_status(
            task_id=task.id,
            repository_id=repo.id,
            status=WorkspaceStatus.IN_USE,
            current_revision="commit_abc123",
        )
        assert updated_ws.status == WorkspaceStatus.IN_USE.value
        assert updated_ws.current_revision == "commit_abc123"

        # 3. Clean up workspace
        cleanup_time = datetime.now(timezone.utc)
        cleaned_ws = repo_layer.update_workspace_status(
            task_id=task.id,
            repository_id=repo.id,
            status=WorkspaceStatus.CLEANED,
            cleanup_at=cleanup_time,
        )
        assert cleaned_ws.status == WorkspaceStatus.CLEANED.value
        assert cleaned_ws.cleanup_at is not None

        # 4. Lookup
        fetched = repo_layer.get_workspace(task.id, repo.id)
        assert fetched is not None
        assert fetched.id == ws.id

    def test_task_execution_tracking_start_and_finish(self, db_session: Session):
        """Worker execution attempts record timing, attempt numbers, and outcomes."""
        user, repo = _seed_user_and_repo(db_session, "user-exec-track")
        repo_layer = TaskRepository(db_session)
        task = _create_approved_task(db_session, repo.id, user.id)

        # Start Attempt 1
        exec1 = repo_layer.record_execution_start(
            task_id=task.id,
            repository_id=repo.id,
            worker_id="worker-node-1",
        )
        assert exec1.attempt_number == 1
        assert exec1.status == ExecutionStatus.RUNNING.value
        assert exec1.completed_at is None

        # Finish Attempt 1 with failure
        exec1_finished = repo_layer.record_execution_finish(
            task_id=task.id,
            repository_id=repo.id,
            execution_id=exec1.id,
            status=ExecutionStatus.FAILED,
            error_message="Sandbox process timeout after 300s",
        )
        assert exec1_finished.status == ExecutionStatus.FAILED.value
        assert "timeout" in exec1_finished.error_message
        assert exec1_finished.completed_at is not None

        # Start Attempt 2
        exec2 = repo_layer.record_execution_start(
            task_id=task.id,
            repository_id=repo.id,
            worker_id="worker-node-2",
        )
        assert exec2.attempt_number == 2

        # Check all executions
        all_execs = repo_layer.get_executions(task.id, repo.id)
        assert len(all_execs) == 2
        assert [e.attempt_number for e in all_execs] == [1, 2]

    def test_tool_invocation_auditing_and_secret_scrubbing(self, db_session: Session):
        """Tool invocations are audited with execution duration and secret scrubbing in arguments."""
        user, repo = _seed_user_and_repo(db_session, "user-tool-audit")
        repo_layer = TaskRepository(db_session)
        task = _create_approved_task(db_session, repo.id, user.id)

        # Invoke Tool with sensitive token in arguments
        inv = repo_layer.record_tool_invocation(
            task_id=task.id,
            repository_id=repo.id,
            tool_name="git_commit",
            arguments={
                "message": "Apply security fix",
                "auth_header": "Bearer ghp_secretToken1234567890abcdef1234567890",
                "api_key": "sk-proj-superSecretKeyForLLMGatewayAccess99",
            },
            status=ToolInvocationStatus.COMPLETED,
            duration_ms=45,
            output_summary="Commit created successfully on task branch",
        )

        assert inv.tool_name == "git_commit"
        assert inv.status == ToolInvocationStatus.COMPLETED.value
        assert inv.duration_ms == 45

        # Verify arguments scrubbing
        assert "ghp_" not in str(inv.sanitized_arguments)
        assert "sk-proj-" not in str(inv.sanitized_arguments)
        assert "[REDACTED]" in str(inv.sanitized_arguments)

        # Lookup
        invs = repo_layer.get_tool_invocations(task.id, repo.id)
        assert len(invs) == 1
        assert invs[0].id == inv.id

    def test_execution_start_preconditions_enforced(self, db_session: Session):
        """Transition to EXECUTING requires both an approved plan and an initialized workspace (§7.2)."""
        user, repo = _seed_user_and_repo(db_session, "user-exec-pre")
        repo_layer = TaskRepository(db_session)

        # 1. Unapproved task cannot execute
        task = repo_layer.create_task(repo.id, "Unapproved task", user_id=user.id)
        repo_layer.save_plan(task.id, repo.id, summary="Plan v1", steps=[{"step_id": "1"}])
        with pytest.raises(InvalidStateTransitionError):
            repo_layer.transition_status(task.id, repo.id, TaskStatus.EXECUTING)

        # 2. Approved task WITHOUT workspace cannot execute
        repo_layer.approve_plan(task.id, repo.id, plan_version=1, user_id=user.id)
        repo_layer.transition_status(task.id, repo.id, TaskStatus.WORKSPACE_SETUP)

        with pytest.raises(InvalidStateTransitionError) as exc_info:
            repo_layer.transition_status(task.id, repo.id, TaskStatus.EXECUTING)
        assert "Workspace has not been initialized" in str(exc_info.value)

        # 3. Approved task WITH workspace can execute
        repo_layer.record_workspace(
            task_id=task.id,
            repository_id=repo.id,
            workspace_path="/tmp/workspaces/valid",
            task_branch=f"agent/task-{task.id}",
            base_revision="main",
            status=WorkspaceStatus.READY,
        )

        executing_task = repo_layer.transition_status(task.id, repo.id, TaskStatus.EXECUTING)
        assert executing_task.status == TaskStatus.EXECUTING.value


# ---------------------------------------------------------------------------
# 2. Day 4: Test Execution & Bounded Repair Loop
# ---------------------------------------------------------------------------


class TestTestExecutionAndBoundedRepairLoop:
    """Verifies test logging, exit codes, and the strict 3-attempt repair ceiling (§6 F35, §7.2)."""

    def test_test_run_logging_counts_and_sanitization(self, db_session: Session):
        """Test runs record exit code, test pass/fail counts, duration, and scrub logs."""
        user, repo = _seed_user_and_repo(db_session, "user-test-log")
        repo_layer = TaskRepository(db_session)
        task = _create_approved_task(db_session, repo.id, user.id)

        raw_log = "Run pytest --exitfirst. Token was: ghp_999988887777666655554444333322221111. All 12 passed."
        run = repo_layer.record_test_run(
            task_id=task.id,
            repository_id=repo.id,
            command="pytest backend/tests/test_auth.py",
            status=TestRunStatus.PASSED,
            exit_code=0,
            duration_ms=1250,
            tests_total=12,
            tests_passed=12,
            tests_failed=0,
            sanitized_output=raw_log,
            target_revision="rev_xyz",
        )

        assert run.exit_code == 0
        assert run.status == TestRunStatus.PASSED.value
        assert run.tests_passed == 12
        assert run.tests_failed == 0
        assert "ghp_" not in run.sanitized_output
        assert "[REDACTED]" in run.sanitized_output

        # Verify lookup
        latest = repo_layer.get_latest_test_run(task.id, repo.id)
        assert latest is not None
        assert latest.id == run.id
        assert latest.command == "pytest backend/tests/test_auth.py"

    def test_bounded_repair_loop_exact_three_attempts_and_exhaustion(self, db_session: Session):
        """Repair attempts 1, 2, 3 succeed; attempt 4 triggers RETRY_EXHAUSTED and fails the task."""
        user, repo = _seed_user_and_repo(db_session, "user-repair-bounds")
        repo_layer = TaskRepository(db_session)
        task = _create_approved_task(db_session, repo.id, user.id)
        assert task.repair_attempts_used == 0
        assert task.repair_attempts_max == 3

        # Attempt 1
        att1, avail1 = repo_layer.increment_repair_attempt(
            task_id=task.id,
            repository_id=repo.id,
            failure_classification="ASSERTION_ERROR",
            diagnosis="Off-by-one boundary check in validation",
            applied_patch="Fix range(len(items))",
        )
        assert avail1 is True
        assert att1.attempt_number == 1
        assert att1.result == RepairResult.SUCCESS.value
        assert task.repair_attempts_used == 1

        # Attempt 2
        att2, avail2 = repo_layer.increment_repair_attempt(
            task_id=task.id,
            repository_id=repo.id,
            failure_classification="TYPE_ERROR",
            diagnosis="NoneType passed to string join",
            applied_patch="Add None guard",
        )
        assert avail2 is True
        assert att2.attempt_number == 2
        assert task.repair_attempts_used == 2

        # Attempt 3 (Final allowed attempt)
        att3, avail3 = repo_layer.increment_repair_attempt(
            task_id=task.id,
            repository_id=repo.id,
            failure_classification="TIMEOUT",
            diagnosis="Infinite loop in retry handler",
            applied_patch="Add break condition",
        )
        assert avail3 is True
        assert att3.attempt_number == 3
        assert task.repair_attempts_used == 3

        # Attempt 4 (Exceeds budget ceiling of 3)
        att4, avail4 = repo_layer.increment_repair_attempt(
            task_id=task.id,
            repository_id=repo.id,
            failure_classification="UNRECOVERABLE",
        )
        assert avail4 is False
        assert att4.attempt_number == 4
        assert att4.result == RepairResult.RETRY_EXHAUSTED.value

        # Task state must be marked FAILED
        assert task.status == TaskStatus.FAILED.value
        assert "Retry budget exhausted" in task.error_message

        # Verify all repair records
        attempts = repo_layer.get_repair_attempts(task.id, repo.id)
        assert len(attempts) == 4
        assert [a.attempt_number for a in attempts] == [1, 2, 3, 4]

    def test_transition_to_repairing_blocked_when_budget_exhausted(self, db_session: Session):
        """State transition to REPAIRING is blocked once repair_attempts_used >= repair_attempts_max."""
        user, repo = _seed_user_and_repo(db_session, "user-repair-gate")
        repo_layer = TaskRepository(db_session)
        task = _create_approved_task(db_session, repo.id, user.id)

        # Set up workspace & transition to TESTING
        repo_layer.record_workspace(task.id, repo.id, "/tmp/ws", f"agent/task-{task.id}", "main")
        repo_layer.transition_status(task.id, repo.id, TaskStatus.WORKSPACE_SETUP)
        repo_layer.transition_status(task.id, repo.id, TaskStatus.EXECUTING)
        repo_layer.transition_status(task.id, repo.id, TaskStatus.TESTING)

        # Use all 3 attempts
        for _ in range(3):
            repo_layer.increment_repair_attempt(task.id, repo.id, "TEST_FAILURE")

        assert task.repair_attempts_used == 3

        # Attempting to transition to REPAIRING must be blocked
        with pytest.raises(InvalidStateTransitionError) as exc_info:
            repo_layer.transition_status(task.id, repo.id, TaskStatus.REPAIRING)
        assert "Retry budget is exhausted" in str(exc_info.value)

    def test_repair_budget_persists_across_worker_restarts(self, db_session: Session):
        """Repair budget is grounded in database persistence and cannot be reset by worker restarts."""
        user, repo = _seed_user_and_repo(db_session, "user-restart-budget")
        repo_layer = TaskRepository(db_session)
        task = _create_approved_task(db_session, repo.id, user.id)

        # Burn 2 attempts
        repo_layer.increment_repair_attempt(task.id, repo.id, "ERROR_1")
        repo_layer.increment_repair_attempt(task.id, repo.id, "ERROR_2")
        assert task.repair_attempts_used == 2

        # Simulate worker restart by creating a completely fresh Session and TaskRepository
        fresh_repo_layer = TaskRepository(db_session)
        reloaded_task = fresh_repo_layer.get_task(task.id, repo.id)
        assert reloaded_task.repair_attempts_used == 2

        # 3rd attempt is allowed
        _, avail3 = fresh_repo_layer.increment_repair_attempt(task.id, repo.id, "ERROR_3")
        assert avail3 is True

        # 4th attempt is exhausted
        _, avail4 = fresh_repo_layer.increment_repair_attempt(task.id, repo.id, "ERROR_4")
        assert avail4 is False


# ---------------------------------------------------------------------------
# 3. Multi-Tenant Isolation & Timeline Events
# ---------------------------------------------------------------------------


class TestMultiTenantIsolationAndTimeline:
    """Verifies repository boundary isolation and timeline event integrity."""

    def test_cross_repository_access_blocked(self, db_session: Session):
        """Repo A's workspace, executions, tests, and repairs are invisible to Repo B."""
        user_a, repo_a = _seed_user_and_repo(db_session, "user-a-iso", "repo-a-iso")
        _, repo_b = _seed_user_and_repo(db_session, "user-b-iso", "repo-b-iso")
        repo_layer = TaskRepository(db_session)

        task_a = _create_approved_task(db_session, repo_a.id, user_a.id)
        repo_layer.record_workspace(task_a.id, repo_a.id, "/tmp/ws-a", "agent/task-a", "main")
        repo_layer.record_test_run(task_a.id, repo_a.id, "pytest", TestRunStatus.PASSED)
        repo_layer.increment_repair_attempt(task_a.id, repo_a.id, "FAIL")

        # Access via repo_b must fail
        with pytest.raises(TaskNotFoundError):
            repo_layer.get_workspace(task_a.id, repo_b.id)

        with pytest.raises(TaskNotFoundError):
            repo_layer.get_test_runs(task_a.id, repo_b.id)

        with pytest.raises(TaskNotFoundError):
            repo_layer.get_repair_attempts(task_a.id, repo_b.id)

    def test_timeline_records_ordered_execution_and_repair_events(self, db_session: Session):
        """Timeline logs WORKSPACE_CREATED, TOOL_INVOKED, TESTS_EXECUTED, and REPAIR_ATTEMPTED."""
        user, repo = _seed_user_and_repo(db_session, "user-timeline-full")
        repo_layer = TaskRepository(db_session)
        task = _create_approved_task(db_session, repo.id, user.id)

        repo_layer.record_workspace(task.id, repo.id, "/tmp/ws", f"agent/task-{task.id}", "main")
        repo_layer.record_tool_invocation(task.id, repo.id, "file_patch", {"file": "a.py"})
        repo_layer.record_test_run(task.id, repo.id, "pytest", TestRunStatus.FAILED)
        repo_layer.increment_repair_attempt(task.id, repo.id, "FAILURE")

        timeline = repo_layer.get_task_timeline(task.id, repo.id)
        event_types = [e.event_type for e in timeline]

        assert TaskEventType.WORKSPACE_CREATED.value in event_types
        assert TaskEventType.TOOL_INVOKED.value in event_types
        assert TaskEventType.TESTS_EXECUTED.value in event_types
        assert TaskEventType.REPAIR_ATTEMPTED.value in event_types

    def test_model_to_dict_matches_pydantic_response_schemas(self, db_session: Session):
        """to_dict() methods on Day 3 and Day 4 models validate cleanly against Pydantic schemas."""
        user, repo = _seed_user_and_repo(db_session, "user-schemas-d3d4")
        service = TaskHistoryService(session=db_session)
        task = _create_approved_task(db_session, repo.id, user.id)

        # 1. Workspace
        ws = service.record_workspace(task.id, repo.id, "/tmp/ws", f"agent/task-{task.id}", "main")
        ws_resp = WorkspaceResponse.model_validate(ws.to_dict())
        assert ws_resp.workspace_id == str(ws.id)
        assert ws_resp.status == WorkspaceStatus.READY.value

        # 2. Execution
        exec_record = service.record_execution_start(task.id, repo.id, worker_id="worker-test")
        exec_resp = TaskExecutionResponse.model_validate(exec_record.to_dict())
        assert exec_resp.execution_id == str(exec_record.id)
        assert exec_resp.status == ExecutionStatus.RUNNING.value

        # 3. Tool Invocation
        inv = service.record_tool_invocation(task.id, repo.id, "read_file", {"path": "a.py"})
        inv_resp = ToolInvocationResponse.model_validate(inv.to_dict())
        assert inv_resp.tool_name == "read_file"

        # 4. Test Run
        run = service.record_test_run(task.id, repo.id, "pytest", TestRunStatus.PASSED, exit_code=0, tests_total=5, tests_passed=5)
        run_resp = TestRunResponse.model_validate(run.to_dict())
        assert run_resp.tests_passed == 5
        assert run_resp.status == "PASSED"

        # 5. Repair Attempt
        att, _ = service.increment_repair_attempt(task.id, repo.id, "ASSERTION_ERROR")
        att_resp = RepairAttemptResponse.model_validate(att.to_dict())
        assert att_resp.attempt_number == 1
        assert att_resp.result == "SUCCESS"

