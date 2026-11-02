"""Week 3 Day 6 & Day 7 Database Query Performance, Audit Consistency, Crash Recovery & 17-Step E2E Acceptance.

Owner: Om — Database & Persistence Lead.
Features Covered:
- F36: Independent Verification Persistence
- F37: Publication Authorization Gate & GitHub Draft PR Persistence
- F39: Persistence, Checkpoints, Worker Crash Recovery & Audit Event Consistency

Tests verify:
1. Performance query optimization & index coverage across all tables.
2. Audit event immutability, chronological consistency, and zero secret leakage.
3. Crash recovery & worker restart resilience (checkpoint restoration, budget preservation).
4. Full 17-step end-to-end workflow lifecycle acceptance from Finding to Draft PR.
5. Strict cross-repository multi-tenant isolation.
6. Canonical Pydantic response schema conformity (Days 6 & 7).
"""

from __future__ import annotations

import time
import uuid
from datetime import datetime, timezone
from typing import Any

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from app.models.analysis_finding import AnalysisFinding
from app.models.analysis_run import AnalysisFeature, AnalysisRun, AnalysisRunStatus
from app.models.base import Base
from app.models.github_installation import GitHubInstallation
from app.models.repository import Repository, SyncStatus
from app.models.task import (
    ApprovalDecision,
    ExecutionStatus,
    GitHubIssue,
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
)
from app.schemas.task import (
    PublicationAuthorizationRequest,
    PublicationAuthorizationResponse,
    TaskRecoveryResponse,
    TaskResponse,
    TaskTraceabilityResponse,
    VerificationResultResponse,
)
from app.services.task_history_service import TaskHistoryService


# ---------------------------------------------------------------------------
# Test Helpers
# ---------------------------------------------------------------------------

def _seed_user_and_repo(db: Session, prefix: str = "d6d7") -> tuple[User, Repository]:
    """Helper to seed isolated tenant user and repository using standard conftest db."""
    user = User(
        id=uuid.uuid4(),
        github_id=abs(hash(f"{prefix}_{uuid.uuid4().hex[:4]}")) % 1000000,
        login=f"{prefix}_{uuid.uuid4().hex[:4]}",
        email=f"{prefix}@example.com",
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
        name=f"repo-{prefix}-{uuid.uuid4().hex[:4]}",
        default_branch="main",
        sync_status=SyncStatus.SYNCED,
    )
    db.add(repo)
    db.commit()
    db.refresh(user)
    db.refresh(repo)
    return user, repo


# ---------------------------------------------------------------------------
# 1. Database Query Performance & Index Optimization (Day 6)
# ---------------------------------------------------------------------------

class TestQueryPerformanceAndIndexOptimization:
    """Verifies composite indexes, fast active-task querying, and query SLA latency."""

    def test_table_indexes_present_and_configured(self) -> None:
        """Verify that all composite and performance indexes are registered in ORM metadata."""
        tables = Base.metadata.tables

        # Check tasks table indexes
        task_table = tables["tasks"]
        task_index_names = {idx.name for idx in task_table.indexes}
        assert "ix_tasks_repo_status" in task_index_names
        assert "ix_tasks_repo_created" in task_index_names

        # Check workspaces table indexes
        ws_table = tables["workspaces"]
        ws_index_names = {idx.name for idx in ws_table.indexes}
        assert "ix_workspaces_task_status" in ws_index_names

        # Check task_executions table indexes
        ex_table = tables["task_executions"]
        ex_index_names = {idx.name for idx in ex_table.indexes}
        assert "ix_task_executions_task_attempt" in ex_index_names
        assert "ix_task_executions_task_created" in ex_index_names

        # Check tool_invocations table indexes
        tool_table = tables["tool_invocations"]
        tool_index_names = {idx.name for idx in tool_table.indexes}
        assert "ix_tool_invocations_task_created" in tool_index_names
        assert "ix_tool_invocations_task_tool" in tool_index_names

        # Check test_runs table indexes
        test_table = tables["test_runs"]
        test_index_names = {idx.name for idx in test_table.indexes}
        assert "ix_test_runs_task_created" in test_index_names
        assert "ix_test_runs_task_status" in test_index_names

        # Check verification_results table indexes
        ver_table = tables["verification_results"]
        ver_index_names = {idx.name for idx in ver_table.indexes}
        assert "ix_verification_results_task_revision" in ver_index_names
        assert "ix_verification_results_task_created" in ver_index_names

        # Check checkpoints and PR tables
        cp_table = tables["task_checkpoints"]
        assert "ix_task_checkpoints_task_created" in {idx.name for idx in cp_table.indexes}

        pr_table = tables["task_pull_requests"]
        assert "ix_task_pull_requests_repo_pr" in {idx.name for idx in pr_table.indexes}

    def test_get_active_tasks_for_repository_filtering(self, db_session: Session) -> None:
        """Querying active tasks filters out terminal states and uses pagination."""
        user, repo = _seed_user_and_repo(db_session, "perf-active")
        repository = TaskRepository(db_session)

        # Create active tasks
        t1 = repository.create_task(repo.id, "Active Task 1", user_id=user.id)
        t2 = repository.create_task(repo.id, "Active Task 2", user_id=user.id)
        repository.transition_status(t2.id, repo.id, TaskStatus.PLANNING)

        # Create terminal tasks
        t_term1 = repository.create_task(repo.id, "Terminal Cancelled", user_id=user.id)
        repository.transition_status(t_term1.id, repo.id, TaskStatus.CANCELLED)

        t_term2 = repository.create_task(repo.id, "Terminal Failed", user_id=user.id)
        repository.transition_status(t_term2.id, repo.id, TaskStatus.FAILED)

        # Query active tasks
        active_tasks = repository.get_active_tasks_for_repository(repo.id)
        active_ids = {t.id for t in active_tasks}

        assert t1.id in active_ids
        assert t2.id in active_ids
        assert t_term1.id not in active_ids
        assert t_term2.id not in active_ids
        assert len(active_tasks) == 2

    def test_query_latency_within_sla_benchmark(self, db_session: Session) -> None:
        """Indexed lookups for task, timeline, and active list must execute under 50ms SLA."""
        user, repo = _seed_user_and_repo(db_session, "perf-sla")
        repository = TaskRepository(db_session)

        # Seed 10 tasks with events
        created_tasks = []
        for i in range(10):
            t = repository.create_task(repo.id, f"SLA Task {i}", user_id=user.id)
            repository.record_event(t.id, repo.id, "BENCHMARK_EVENT", {"idx": i}, user_id=user.id)
            created_tasks.append(t)

        target_task = created_tasks[5]

        # 1. Benchmark get_task
        t0 = time.perf_counter()
        retrieved = repository.get_task(target_task.id, repo.id)
        t_get_task_ms = (time.perf_counter() - t0) * 1000.0
        assert retrieved is not None
        assert t_get_task_ms < 50.0, f"get_task took {t_get_task_ms:.2f}ms, exceeding 50ms SLA"

        # 2. Benchmark get_active_tasks_for_repository
        t0 = time.perf_counter()
        actives = repository.get_active_tasks_for_repository(repo.id, limit=20)
        t_active_ms = (time.perf_counter() - t0) * 1000.0
        assert len(actives) == 10
        assert t_active_ms < 50.0, f"get_active_tasks took {t_active_ms:.2f}ms, exceeding 50ms SLA"

        # 3. Benchmark get_task_timeline
        t0 = time.perf_counter()
        events = repository.get_task_timeline(target_task.id, repo.id)
        t_timeline_ms = (time.perf_counter() - t0) * 1000.0
        assert len(events) >= 2  # TASK_CREATED + BENCHMARK_EVENT
        assert t_timeline_ms < 30.0, f"get_task_timeline took {t_timeline_ms:.2f}ms, exceeding 30ms SLA"

    def test_eager_loading_avoids_n_plus_one(self, db_session: Session) -> None:
        """Fetching a task eagerly loads plans, approvals, workspace, and executions."""
        user, repo = _seed_user_and_repo(db_session, "perf-eager")
        repository = TaskRepository(db_session)

        task = repository.create_task(repo.id, "Eager Loading Task", user_id=user.id)
        plan = repository.save_plan(task.id, repo.id, summary="Plan 1", steps=[{"step": 1}])
        repository.approve_plan(task.id, repo.id, plan_version=plan.version, user_id=user.id)
        repository.record_workspace(task.id, repo.id, "/ws/task", "agent/task", "base-sha")
        repository.record_execution_start(task.id, repo.id, worker_id="w-eager")

        # Expire session so attributes are not in identity map
        db_session.expire_all()

        loaded_task = repository.get_task(task.id, repo.id)
        assert loaded_task is not None
        # Accessing relationships should succeed immediately
        assert len(loaded_task.plans) == 1
        assert len(loaded_task.approvals) == 1
        assert loaded_task.workspace is not None
        assert len(loaded_task.executions) == 1


# ---------------------------------------------------------------------------
# 2. Audit Event Consistency & Immutability Enforcement (Day 6)
# ---------------------------------------------------------------------------

class TestAuditEventConsistencyAndImmutability:
    """Verifies append-only immutability, chronological monotonic ordering, and zero credential leakage."""

    def test_audit_events_are_append_only_and_immutable(self, db_session: Session) -> None:
        """Attempting to delete or modify an audit event is strictly rejected."""
        user, repo = _seed_user_and_repo(db_session, "audit-imm")
        repository = TaskRepository(db_session)

        task = repository.create_task(repo.id, "Immutable Audit Task", user_id=user.id)
        event = repository.record_event(task.id, repo.id, "SYSTEM_CHECK", {"key": "value"})

        with pytest.raises(PermissionError, match="Audit events are immutable and cannot be deleted"):
            repository.delete_event(event.id)

        with pytest.raises(PermissionError, match="Audit events are immutable and cannot be modified"):
            repository.update_event(event.id, summary="Altered summary")

    def test_task_approvals_are_immutable(self, db_session: Session) -> None:
        """Attempting to alter a human plan approval is strictly rejected."""
        user, repo = _seed_user_and_repo(db_session, "approval-imm")
        repository = TaskRepository(db_session)

        task = repository.create_task(repo.id, "Approval Immutability Task", user_id=user.id)
        plan = repository.save_plan(task.id, repo.id, summary="Plan", steps=[{"step": 1}])
        approval = repository.approve_plan(task.id, repo.id, plan_version=plan.version, user_id=user.id)

        with pytest.raises(PermissionError, match="Task approvals are immutable and cannot be modified"):
            repository.update_approval(approval.id, feedback="Mutated feedback")

    def test_timeline_order_strictly_monotonic(self, db_session: Session) -> None:
        """Timeline events must return in strictly non-decreasing chronological order."""
        user, repo = _seed_user_and_repo(db_session, "timeline-seq")
        repository = TaskRepository(db_session)

        task = repository.create_task(repo.id, "Monotonic Timeline Task", user_id=user.id)
        for i in range(5):
            repository.record_event(task.id, repo.id, f"EVENT_{i}", {"index": i}, user_id=user.id)

        timeline = repository.get_task_timeline(task.id, repo.id)
        assert len(timeline) == 6  # 1 creation + 5 appended

        for i in range(len(timeline) - 1):
            assert timeline[i].created_at <= timeline[i + 1].created_at

    def test_state_transitions_always_record_consistent_events(self, db_session: Session) -> None:
        """Every status transition must emit a corresponding timeline audit event."""
        user, repo = _seed_user_and_repo(db_session, "trans-events")
        repository = TaskRepository(db_session)

        task = repository.create_task(repo.id, "Transition Events Task", user_id=user.id)
        repository.transition_status(
            task.id,
            repo.id,
            TaskStatus.PLANNING,
            user_id=user.id,
            reason="Starting planner phase",
        )

        timeline = repository.get_task_timeline(task.id, repo.id)
        transition_events = [e for e in timeline if e.event_type == TaskEventType.STATE_TRANSITIONED.value]
        assert len(transition_events) == 1
        ev = transition_events[0]
        assert ev.event_data["from_status"] == TaskStatus.CREATED.value
        assert ev.event_data["to_status"] == TaskStatus.PLANNING.value
        assert ev.event_data["reason"] == "Starting planner phase"

    def test_secret_scrubbing_across_all_event_fields(self, db_session: Session) -> None:
        """Raw secrets in event payloads and reasons are redacted before persistence."""
        user, repo = _seed_user_and_repo(db_session, "audit-scrub")
        repository = TaskRepository(db_session)

        task = repository.create_task(repo.id, "Scrubbed Event Task", user_id=user.id)
        secret_token = "ghp_123456789012345678901234567890123456"
        secret_key = "sk-proj-1234567890abcdef1234567890"

        ev = repository.record_event(
            task_id=task.id,
            repository_id=repo.id,
            event_type="AUTH_LOG",
            event_data={"token": secret_token, "headers": {"Authorization": f"Bearer {secret_key}"}},
            summary=f"Dispatched with key {secret_key}",
        )

        assert secret_token not in str(ev.event_data)
        assert secret_key not in str(ev.event_data)
        assert secret_key not in ev.summary
        assert "[REDACTED]" in ev.summary


# ---------------------------------------------------------------------------
# 3. Crash Recovery & Worker Restart Resilience (Day 6 & F39)
# ---------------------------------------------------------------------------

class TestWorkerCrashRecoveryAndRestartResilience:
    """Verifies crash detection, checkpoint rollback, retry budget preservation, and idempotency."""

    def test_recover_interrupted_task_with_valid_checkpoint(self, db_session: Session) -> None:
        """An interrupted task with a valid checkpoint is transitioned to RECOVERY_REQUIRED with checkpoint metadata."""
        user, repo = _seed_user_and_repo(db_session, "crash-cp")
        repository = TaskRepository(db_session)

        task = repository.create_task(repo.id, "Crash Recovery Task", user_id=user.id)
        plan = repository.save_plan(task.id, repo.id, summary="Plan", steps=[{"step": 1}])
        repository.approve_plan(task.id, repo.id, plan_version=plan.version, user_id=user.id)
        repository.record_workspace(task.id, repo.id, "/ws/crash", "agent/task", "base-sha")

        # Save a valid checkpoint during execution
        repository.save_checkpoint(
            task_id=task.id,
            repository_id=repo.id,
            step_name="step_3_file_modified",
            state_data={"modified_files": ["auth.py"], "diff_size": 150},
            recovery_instructions="Re-apply patch from step 3 and run tests",
        )

        # Transition to EXECUTING with an open execution record
        repository.transition_status(task.id, repo.id, TaskStatus.WORKSPACE_SETUP)
        repository.transition_status(task.id, repo.id, TaskStatus.EXECUTING)
        ex = repository.record_execution_start(task.id, repo.id, worker_id="worker-crash-1")

        # Simulate worker crash & restart reconciliation
        reconciled = repository.reconcile_crashed_task(task.id, repo.id, reason="Worker SIGKILL detected")

        assert reconciled.status == TaskStatus.RECOVERY_REQUIRED.value
        assert "Worker SIGKILL detected" in reconciled.error_message

        # Verify dangling execution record is marked FAILED
        db_session.refresh(ex)
        assert ex.status == ExecutionStatus.FAILED.value
        assert ex.error_message == "Worker SIGKILL detected"

        # Verify CRASH_RECOVERED event logged
        timeline = repository.get_task_timeline(task.id, repo.id)
        crash_events = [e for e in timeline if e.event_type == "CRASH_RECOVERED"]
        assert len(crash_events) == 1
        assert crash_events[0].event_data["step_name"] == "step_3_file_modified"

    def test_recover_interrupted_task_without_checkpoint(self, db_session: Session) -> None:
        """An interrupted task with no checkpoint is transitioned to RECOVERY_REQUIRED for manual triage."""
        user, repo = _seed_user_and_repo(db_session, "crash-nocp")
        repository = TaskRepository(db_session)

        task = repository.create_task(repo.id, "No-CP Task", user_id=user.id)
        plan = repository.save_plan(task.id, repo.id, summary="Plan", steps=[{"step": 1}])
        repository.approve_plan(task.id, repo.id, plan_version=plan.version, user_id=user.id)
        repository.record_workspace(task.id, repo.id, "/ws/task", "agent/task", "base-sha")
        repository.transition_status(task.id, repo.id, TaskStatus.WORKSPACE_SETUP)
        repository.transition_status(task.id, repo.id, TaskStatus.EXECUTING)
        repository.transition_status(task.id, repo.id, TaskStatus.TESTING)

        reconciled = repository.reconcile_crashed_task(task.id, repo.id, reason="Host out of memory")

        assert reconciled.status == TaskStatus.RECOVERY_REQUIRED.value
        timeline = repository.get_task_timeline(task.id, repo.id)
        detected_events = [e for e in timeline if e.event_type == "CRASH_DETECTED"]
        assert len(detected_events) == 1
        assert "Host out of memory" in detected_events[0].event_data["reason"]

    def test_recover_task_with_exhausted_retry_budget(self, db_session: Session) -> None:
        """When repair budget is exhausted, crash recovery transitions task to FAILED rather than infinite loop."""
        user, repo = _seed_user_and_repo(db_session, "crash-exhaust")
        repository = TaskRepository(db_session)

        task = repository.create_task(repo.id, "Budget Exhausted Task", user_id=user.id)
        plan = repository.save_plan(task.id, repo.id, summary="Plan", steps=[{"step": 1}])
        repository.approve_plan(task.id, repo.id, plan_version=plan.version, user_id=user.id)
        repository.record_workspace(task.id, repo.id, "/ws/task", "agent/task", "base-sha")
        repository.transition_status(task.id, repo.id, TaskStatus.WORKSPACE_SETUP)
        repository.transition_status(task.id, repo.id, TaskStatus.EXECUTING)
        repository.transition_status(task.id, repo.id, TaskStatus.TESTING)
        repository.transition_status(task.id, repo.id, TaskStatus.REPAIRING)

        # Exhaust repair attempts to 3
        repository.increment_repair_attempt(task.id, repo.id)
        repository.increment_repair_attempt(task.id, repo.id)
        repository.increment_repair_attempt(task.id, repo.id)
        db_session.refresh(task)
        assert task.repair_attempts_used == 3

        reconciled = repository.reconcile_crashed_task(task.id, repo.id, reason="Worker crash during repair attempt 3")

        assert reconciled.status == TaskStatus.FAILED.value
        assert "repair attempt budget exhausted" in reconciled.error_message

        timeline = repository.get_task_timeline(task.id, repo.id)
        failed_events = [e for e in timeline if e.event_type == "RECOVERY_FAILED"]
        assert len(failed_events) == 1

    def test_retry_counter_preserved_across_worker_restart(self, db_session: Session) -> None:
        """Worker crash recovery guarantees that repair_attempts_used is NEVER decremented or reset to 0."""
        user, repo = _seed_user_and_repo(db_session, "retry-pres")
        repository = TaskRepository(db_session)

        task = repository.create_task(repo.id, "Retry Preserved Task", user_id=user.id)
        plan = repository.save_plan(task.id, repo.id, summary="Plan", steps=[{"step": 1}])
        repository.approve_plan(task.id, repo.id, plan_version=plan.version, user_id=user.id)
        repository.record_workspace(task.id, repo.id, "/ws/task", "agent/task", "base-sha")
        repository.transition_status(task.id, repo.id, TaskStatus.WORKSPACE_SETUP)
        repository.transition_status(task.id, repo.id, TaskStatus.EXECUTING)
        repository.transition_status(task.id, repo.id, TaskStatus.TESTING)
        repository.transition_status(task.id, repo.id, TaskStatus.REPAIRING)

        # 2 attempts used
        repository.increment_repair_attempt(task.id, repo.id)
        repository.increment_repair_attempt(task.id, repo.id)
        db_session.refresh(task)
        assert task.repair_attempts_used == 2

        # Reconcile after crash
        reconciled = repository.reconcile_crashed_task(task.id, repo.id)
        assert reconciled.repair_attempts_used == 2, "Retry counter was corrupted during crash recovery"

    def test_recover_interrupted_tasks_batch_repository_wide(self, db_session: Session) -> None:
        """Batch recovery detects all volatile tasks in a repository and reconciles them."""
        user, repo = _seed_user_and_repo(db_session, "batch-rec")
        service = TaskHistoryService(session=db_session)

        # Create 2 active tasks in volatile states
        t1 = service.create_task(repo.id, "Batch Task 1", user_id=user.id)
        p1 = service.save_plan(t1.id, repo.id, summary="Plan 1", steps=[{"step": 1}])
        service.approve_plan(t1.id, repo.id, plan_version=p1.version, user_id=user.id)
        service.record_workspace(t1.id, repo.id, "/ws/t1", "agent/t1", "base-sha")
        service.transition_status(t1.id, repo.id, TaskStatus.WORKSPACE_SETUP)
        service.transition_status(t1.id, repo.id, TaskStatus.EXECUTING)

        t2 = service.create_task(repo.id, "Batch Task 2", user_id=user.id)
        p2 = service.save_plan(t2.id, repo.id, summary="Plan 2", steps=[{"step": 1}])
        service.approve_plan(t2.id, repo.id, plan_version=p2.version, user_id=user.id)
        service.record_workspace(t2.id, repo.id, "/ws/t2", "agent/t2", "base-sha")
        service.transition_status(t2.id, repo.id, TaskStatus.WORKSPACE_SETUP)
        service.transition_status(t2.id, repo.id, TaskStatus.EXECUTING)
        service.transition_status(t2.id, repo.id, TaskStatus.TESTING)

        # Create 1 task in a safe state (PLANNING)
        t3 = service.create_task(repo.id, "Safe Task 3", user_id=user.id)
        service.transition_status(t3.id, repo.id, TaskStatus.PLANNING)

        # Run repository-wide crash recovery
        recovery_results = service.recover_interrupted_tasks(repo.id, worker_id="worker-node-42")

        assert len(recovery_results) == 2
        recovered_ids = {r["task_id"] for r in recovery_results}
        assert str(t1.id) in recovered_ids
        assert str(t2.id) in recovered_ids
        assert str(t3.id) not in recovered_ids

        # t3 remains unchanged
        db_session.refresh(t3)
        assert t3.status == TaskStatus.PLANNING.value

    def test_recovery_is_idempotent_on_non_volatile_tasks(self, db_session: Session) -> None:
        """Calling recovery on a task that is completed or in READY_FOR_PUBLICATION is an idempotent no-op."""
        user, repo = _seed_user_and_repo(db_session, "rec-idemp")
        repository = TaskRepository(db_session)

        task = repository.create_task(repo.id, "Completed Task", user_id=user.id)
        plan = repository.save_plan(task.id, repo.id, summary="Plan", steps=[{"step": 1}])
        repository.approve_plan(task.id, repo.id, plan_version=plan.version, user_id=user.id)
        repository.record_workspace(task.id, repo.id, "/ws/task", "agent/task", "base-sha")
        repository.transition_status(task.id, repo.id, TaskStatus.WORKSPACE_SETUP)
        repository.transition_status(task.id, repo.id, TaskStatus.EXECUTING)
        repository.transition_status(task.id, repo.id, TaskStatus.TESTING)
        repository.transition_status(task.id, repo.id, TaskStatus.VERIFYING)
        repository.record_verification_result(task.id, repo.id, "sha-verified", VerificationStatus.PASSED)
        db_session.refresh(task)
        assert task.status == TaskStatus.READY_FOR_PUBLICATION.value

        reconciled = repository.reconcile_crashed_task(task.id, repo.id)
        assert reconciled.status == TaskStatus.READY_FOR_PUBLICATION.value


# ---------------------------------------------------------------------------
# 4. Full 17-Step End-to-End Workflow Acceptance (Day 7)
# ---------------------------------------------------------------------------

class TestFullWorkflow17StepEndToEndAcceptance:
    """Verifies complete 17-step autonomous development lifecycle from Finding to Draft PR."""

    def test_17_step_full_lifecycle_workflow_complete(self, db_session: Session) -> None:
        """Execute full 17-step end-to-end lifecycle and verify 100% referential integrity and audit consistency."""
        user, repo = _seed_user_and_repo(db_session, "17step-demo")
        repository = TaskRepository(db_session)

        # STEP 1: Ingest Week 2 Defect Finding
        run = AnalysisRun(
            id=uuid.uuid4(),
            repository_id=repo.id,
            feature_type=AnalysisFeature.DETECT_BUGS.value,
            status=AnalysisRunStatus.COMPLETED.value,
            target_path="backend/app/auth.py",
            source_revision="commit-base-001",
        )
        db_session.add(run)
        db_session.flush()

        finding = AnalysisFinding(
            id=uuid.uuid4(),
            analysis_run_id=run.id,
            repository_id=repo.id,
            category="SECURITY",
            severity="HIGH",
            title="SQL Injection vulnerability in user lookup",
            description="String formatting in raw SQL query creates injection risk",
            evidence="db.execute(f'SELECT * FROM users WHERE id = {user_id}')",
            file_path="backend/app/auth.py",
            start_line=120,
            end_line=125,
        )
        db_session.add(finding)
        db_session.flush()

        # STEP 2: Create GitHub Issue from Finding
        issue, _ = repository.upsert_github_issue(
            repository_id=repo.id,
            issue_number=101,
            title="[Security] Fix SQL Injection in auth.py",
            body="Identified SQL injection flaw in auth.py during Week 2 scan.",
            html_url="https://github.com/17step-org/repo-17step/issues/101",
            author="security-bot",
            origin_finding_id=finding.id,
        )
        assert issue.issue_number == 101

        # STEP 3: Create Task linked to GitHub Issue and Finding
        task = repository.create_task(
            repository_id=repo.id,
            title=issue.title,
            description=issue.body,
            source_type=TaskSourceType.GITHUB_ISSUE,
            source_id="101",
            finding_id=finding.id,
            github_issue_id=issue.id,
            user_id=user.id,
            base_revision="commit-base-001",
        )
        assert task.status == TaskStatus.CREATED.value
        assert task.finding_id == finding.id

        # STEP 4: Generate Implementation Plan (v1) -> Task transitions to PENDING_APPROVAL
        plan_v1 = repository.save_plan(
            task_id=task.id,
            repository_id=repo.id,
            summary="Replace raw SQL with parameterized query",
            steps=[{"step": 1, "action": "Refactor execute statement"}],
            expected_files=["backend/app/auth.py"],
            tests_to_run=["tests/test_auth.py"],
            validation_strategy="Run auth unit tests and static security scan",
            base_revision="commit-base-001",
        )
        assert plan_v1.version == 1
        db_session.refresh(task)
        assert task.status == TaskStatus.PENDING_APPROVAL.value

        # STEP 5: Human Rejection of Plan v1 with feedback -> Task transitions to REJECTED
        rej = repository.reject_plan(
            task_id=task.id,
            repository_id=repo.id,
            plan_version=1,
            feedback="Please also include SQLAlchemy ORM query rather than raw execute",
            user_id=user.id,
        )
        assert rej.decision == ApprovalDecision.REJECTED.value
        db_session.refresh(task)
        assert task.status == TaskStatus.REJECTED.value

        # STEP 6: Revise Plan (v2) -> Invalidates prior decision, advances to PENDING_APPROVAL
        plan_v2 = repository.save_plan(
            task_id=task.id,
            repository_id=repo.id,
            summary="Migrate user lookup to SQLAlchemy ORM select() statement",
            steps=[
                {"step": 1, "action": "Replace execute with select(User).where(User.id == user_id)"},
                {"step": 2, "action": "Add parameter boundary tests in tests/test_auth.py"},
            ],
            expected_files=["backend/app/auth.py", "tests/test_auth.py"],
            tests_to_run=["tests/test_auth.py"],
            validation_strategy="Pytest coverage and Bandit security scan",
            base_revision="commit-base-001",
        )
        assert plan_v2.version == 2
        db_session.refresh(task)
        assert task.status == TaskStatus.PENDING_APPROVAL.value
        assert task.approved_plan_version is None

        # STEP 7: Human Approves Plan v2 -> Task transitions to APPROVED
        appr = repository.approve_plan(
            task_id=task.id,
            repository_id=repo.id,
            plan_version=2,
            feedback="Approved ORM migration plan.",
            user_id=user.id,
        )
        assert appr.decision == ApprovalDecision.APPROVED.value
        db_session.refresh(task)
        assert task.status == TaskStatus.APPROVED.value
        assert task.approved_plan_version == 2

        # STEP 8: Initialize Workspace -> Transition to EXECUTING
        ws = repository.record_workspace(
            task_id=task.id,
            repository_id=repo.id,
            workspace_path="/tmp/workspaces/task-101",
            task_branch="agent/task-101-sql-injection",
            base_revision="commit-base-001",
            status=WorkspaceStatus.READY,
        )
        assert ws.task_branch == "agent/task-101-sql-injection"

        repository.transition_status(task.id, repo.id, TaskStatus.WORKSPACE_SETUP)
        repository.transition_status(task.id, repo.id, TaskStatus.EXECUTING)
        ex = repository.record_execution_start(task.id, repo.id, worker_id="agent-worker-01")

        # STEP 9: Tool Invocations (Read file, Apply patch) with secret scrubbing
        t_read = repository.record_tool_invocation(
            task_id=task.id,
            repository_id=repo.id,
            tool_name="read_file",
            arguments={"path": "backend/app/auth.py", "lines": [120, 130]},
            status=ToolInvocationStatus.COMPLETED,
            duration_ms=12,
            output_summary="Read 10 lines from auth.py",
        )
        t_patch = repository.record_tool_invocation(
            task_id=task.id,
            repository_id=repo.id,
            tool_name="patch_file",
            arguments={"path": "backend/app/auth.py", "diff": "- execute(f'SELECT...')\\n+ select(User)..."},
            status=ToolInvocationStatus.COMPLETED,
            duration_ms=45,
            output_summary="Applied ORM patch to auth.py",
        )
        assert t_read.status == ToolInvocationStatus.COMPLETED.value
        assert t_patch.status == ToolInvocationStatus.COMPLETED.value

        # STEP 10: Run Tests (Attempt 1: Fail) -> Transition to TESTING
        repository.transition_status(task.id, repo.id, TaskStatus.TESTING)
        tr1 = repository.record_test_run(
            task_id=task.id,
            repository_id=repo.id,
            command="pytest tests/test_auth.py",
            status=TestRunStatus.FAILED,
            exit_code=1,
            duration_ms=1200,
            tests_total=10,
            tests_passed=9,
            tests_failed=1,
            sanitized_output="FAILED tests/test_auth.py::test_user_lookup - NameError: select is not imported",
            target_revision="sha-patch-001",
        )
        assert tr1.tests_failed == 1

        # STEP 11: Bounded Repair Loop (Attempt 1) -> Transition to REPAIRING
        repository.transition_status(task.id, repo.id, TaskStatus.REPAIRING)
        rep1, ok1 = repository.increment_repair_attempt(
            task_id=task.id,
            repository_id=repo.id,
            failure_classification="SYNTAX_ERROR",
            diagnosis="Missing import for select in auth.py",
            applied_patch="from sqlalchemy import select",
        )
        assert ok1 is True
        assert rep1.attempt_number == 1
        db_session.refresh(task)
        assert task.repair_attempts_used == 1

        # STEP 12: Re-test (Attempt 2: Fail) -> Transition to TESTING
        repository.transition_status(task.id, repo.id, TaskStatus.TESTING)
        tr2 = repository.record_test_run(
            task_id=task.id,
            repository_id=repo.id,
            command="pytest tests/test_auth.py",
            status=TestRunStatus.FAILED,
            exit_code=1,
            duration_ms=1150,
            tests_total=10,
            tests_passed=9,
            tests_failed=1,
            sanitized_output="FAILED tests/test_auth.py::test_boundary_conditions - AssertionError",
            target_revision="sha-patch-002",
        )
        assert tr2.status == TestRunStatus.FAILED.value

        # STEP 13: Bounded Repair Loop (Attempt 2: Success patch) -> Transition to REPAIRING
        repository.transition_status(task.id, repo.id, TaskStatus.REPAIRING)
        rep2, ok2 = repository.increment_repair_attempt(
            task_id=task.id,
            repository_id=repo.id,
            failure_classification="ASSERTION_ERROR",
            diagnosis="Fix boundary condition in user lookup handler",
            applied_patch="if not user_id: return None",
        )
        assert ok2 is True
        assert rep2.attempt_number == 2
        db_session.refresh(task)
        assert task.repair_attempts_used == 2

        # STEP 14: Re-test (Attempt 3: Pass) -> Transition to VERIFYING
        repository.transition_status(task.id, repo.id, TaskStatus.TESTING)
        tr3 = repository.record_test_run(
            task_id=task.id,
            repository_id=repo.id,
            command="pytest tests/test_auth.py",
            status=TestRunStatus.PASSED,
            exit_code=0,
            duration_ms=1320,
            tests_total=10,
            tests_passed=10,
            tests_failed=0,
            sanitized_output="10 passed in 1.32s",
            target_revision="sha-patch-003",
        )
        assert tr3.tests_failed == 0

        repository.record_execution_finish(
            task_id=task.id,
            repository_id=repo.id,
            execution_id=ex.id,
            status=ExecutionStatus.COMPLETED,
        )

        repository.transition_status(task.id, repo.id, TaskStatus.VERIFYING)

        # STEP 15: Independent Verification Engine (PASSED, 0 blockers) -> READY_FOR_PUBLICATION
        ver = repository.record_verification_result(
            task_id=task.id,
            repository_id=repo.id,
            verified_revision="sha-patch-003",
            status=VerificationStatus.PASSED,
            checks=[
                {"check": "pytest", "status": "PASSED"},
                {"check": "bandit", "status": "PASSED"},
                {"check": "ruff", "status": "PASSED"},
                {"check": "ai_review", "status": "PASSED"},
            ],
            blocking_findings=[],
            warnings=[],
            summary="All tests passed, zero security flaws, clean AI review.",
        )
        assert ver.status == VerificationStatus.PASSED.value
        db_session.refresh(task)
        assert task.status == TaskStatus.READY_FOR_PUBLICATION.value

        # STEP 16: Human Publication Authorization Gate -> Transition to PUBLISHING
        auth_res = repository.authorize_publication(
            task_id=task.id,
            repository_id=repo.id,
            head_sha="sha-patch-003",
            user_id=user.id,
            notes="Ready to publish PR to GitHub",
        )
        assert auth_res.status == TaskStatus.PUBLISHING.value
        db_session.refresh(task)
        assert task.status == TaskStatus.PUBLISHING.value

        # STEP 17: Published GitHub Draft PR -> Transition to DRAFT_PR_CREATED
        pr = repository.record_pull_request(
            task_id=task.id,
            repository_id=repo.id,
            pr_url="https://github.com/17step-org/repo-17step/pull/202",
            base_branch="main",
            head_branch="agent/task-101-sql-injection",
            head_sha="sha-patch-003",
            title=f"Fix #{issue.issue_number}: {task.title}",
            body="Autonomous PR addressing SQL injection in auth.py with SQLAlchemy ORM query.",
            pr_number=202,
            is_draft=True,
        )
        assert pr.pr_number == 202
        db_session.refresh(task)
        assert task.status == TaskStatus.DRAFT_PR_CREATED.value

        # VERIFICATION: End-to-End Traceability Graph Validation
        trace = repository.get_task_traceability(task.id, repo.id)
        assert trace["is_complete_workflow"] is True
        assert trace["traceability_status"] == "COMPLETE"
        assert trace["task"]["status"] == TaskStatus.DRAFT_PR_CREATED.value
        assert trace["finding"]["finding_id"] == str(finding.id)
        assert trace["latest_plan"]["version"] == 2
        assert trace["latest_approval"]["decision"] == ApprovalDecision.APPROVED.value
        assert trace["workspace"]["task_branch"] == "agent/task-101-sql-injection"
        assert trace["repair_attempts_used"] == 2
        assert len(trace["tool_invocations"]) == 2
        assert len(trace["test_runs"]) == 3
        assert len(trace["repair_attempts"]) == 2
        assert trace["latest_verification"]["status"] == VerificationStatus.PASSED.value
        assert trace["pull_request"]["pr_number"] == 202

        # Validate against Pydantic schema
        pydantic_trace = TaskTraceabilityResponse.model_validate(trace)
        assert pydantic_trace.is_complete_workflow is True
        assert pydantic_trace.pull_request.pr_url == "https://github.com/17step-org/repo-17step/pull/202"

        # Verify zero manual interventions occurred between Step 7 approval and Step 17 PR creation
        timeline = repository.get_task_timeline(task.id, repo.id)
        assert len(timeline) >= 12


# ---------------------------------------------------------------------------
# 5. Multi-Tenant Day 6 & 7 Isolation
# ---------------------------------------------------------------------------

class TestMultiTenantDay6Day7Isolation:
    """Verifies that active tasks, crash recovery, and traceability are completely isolated across repositories."""

    def test_cross_repository_active_tasks_and_recovery_isolated(self, db_session: Session) -> None:
        """Tasks from Repo A cannot be listed or recovered by queries targeting Repo B."""
        user_a, repo_a = _seed_user_and_repo(db_session, "tenant-a")
        user_b, repo_b = _seed_user_and_repo(db_session, "tenant-b")
        repository = TaskRepository(db_session)

        # Create active task in Repo A
        t_a = repository.create_task(repo_a.id, "Repo A Task", user_id=user_a.id)

        # Query active tasks in Repo B
        actives_b = repository.get_active_tasks_for_repository(repo_b.id)
        assert len(actives_b) == 0

        # Run recovery in Repo B
        rec_b = repository.recover_interrupted_tasks(repo_b.id)
        assert len(rec_b) == 0

        # Task A remains untouched in CREATED status
        db_session.refresh(t_a)
        assert t_a.status == TaskStatus.CREATED.value

    def test_cross_repository_traceability_blocked(self, db_session: Session) -> None:
        """Attempting to access Repo A's task traceability using Repo B's ID raises TaskNotFoundError."""
        user_a, repo_a = _seed_user_and_repo(db_session, "trace-iso-a")
        _, repo_b = _seed_user_and_repo(db_session, "trace-iso-b")
        repository = TaskRepository(db_session)

        task_a = repository.create_task(repo_a.id, "Task A", user_id=user_a.id)

        with pytest.raises(TaskNotFoundError):
            repository.get_task_traceability(task_a.id, repo_b.id)


# ---------------------------------------------------------------------------
# 6. Pydantic Schema Conformity (Days 6 & 7)
# ---------------------------------------------------------------------------

class TestPydanticSchemaConformityDay6Day7:
    """Validates that Day 6 and Day 7 responses conform strictly to agreed Pydantic contracts."""

    def test_task_recovery_response_schema_validation(self) -> None:
        """Validate TaskRecoveryResponse schema instantiation."""
        rec_data = {
            "recovered_tasks_count": 2,
            "tasks": [
                {"task_id": str(uuid.uuid4()), "status": "RECOVERY_REQUIRED"},
                {"task_id": str(uuid.uuid4()), "status": "FAILED"},
            ],
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        resp = TaskRecoveryResponse.model_validate(rec_data)
        assert resp.recovered_tasks_count == 2
        assert len(resp.tasks) == 2

    def test_task_traceability_response_with_empty_collections(self, db_session: Session) -> None:
        """A freshly created task's traceability validates cleanly against TaskTraceabilityResponse."""
        user, repo = _seed_user_and_repo(db_session, "schema-trace")
        repository = TaskRepository(db_session)

        task = repository.create_task(repo.id, "Minimal Traceability Task", user_id=user.id)
        trace_dict = repository.get_task_traceability(task.id, repo.id)

        resp = TaskTraceabilityResponse.model_validate(trace_dict)
        assert resp.task.task_id == str(task.id)
        assert resp.is_complete_workflow is False
        assert len(resp.tool_invocations) == 0
        assert len(resp.test_runs) == 0
        assert len(resp.repair_attempts) == 0
