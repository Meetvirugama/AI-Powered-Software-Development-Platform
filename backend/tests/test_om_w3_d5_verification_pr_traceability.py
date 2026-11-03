"""Tests for Om's Week 3 Day 5 Persistence Deliverables.

Focus:
1. Independent verification persistence tied strictly to verified revision (§6 F36).
2. Verification state transitions (PASSED -> READY_FOR_PUBLICATION, blocking findings -> BLOCKED).
3. Publication authorization gate requiring passing verification and revision matching (§6 F37).
4. GitHub Draft PR persistence, revision tracking, and idempotent update handling.
5. End-to-end audit traceability linking: Finding -> Issue/Task -> Plan -> Approval -> Workspace -> Execution -> Test Run -> Verification -> Draft PR.
6. Multi-tenant repository boundary isolation.
7. Automated secret scrubbing across verification findings and PR body/title.
8. Pydantic schema validation for Day 5 models (VerificationResultResponse, TaskPullRequestResponse, TaskTraceabilityResponse).
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from sqlalchemy.orm import Session

from app.models.analysis_finding import AnalysisFinding
from app.models.analysis_run import AnalysisFeature, AnalysisRun, AnalysisRunStatus
from app.models.github_installation import GitHubInstallation
from app.models.repository import Repository, SyncStatus
from app.models.task import (
    ApprovalDecision,
    ExecutionStatus,
    RepairResult,
    Task,
    TaskApproval,
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
    TaskPullRequestResponse,
    TaskTraceabilityResponse,
    VerificationResultResponse,
)
from app.services.task_history_service import TaskHistoryService


# ---------------------------------------------------------------------------
# Test Helpers
# ---------------------------------------------------------------------------

def _seed_user_and_repo(
    db_session: Session,
    login: str = "om-d5-user",
    repo_name: str = "d5-repo",
) -> tuple[User, Repository]:
    """Helper to seed isolated tenant user and repository using standard conftest db."""
    user = User(
        id=uuid.uuid4(),
        github_id=abs(hash(f"{login}_{uuid.uuid4().hex[:4]}")) % 1000000,
        login=f"{login}_{uuid.uuid4().hex[:4]}",
        email=f"{login}@example.com",
    )
    db_session.add(user)
    db_session.flush()

    installation = GitHubInstallation(
        id=uuid.uuid4(),
        user_id=user.id,
        installation_id=f"inst_{uuid.uuid4().hex[:8]}",
        account_login=user.login,
        permissions={"contents": "write", "pull_requests": "write"},
    )
    db_session.add(installation)
    db_session.flush()

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
    db_session.add(repo)
    db_session.commit()
    db_session.refresh(user)
    db_session.refresh(repo)
    return user, repo


def _seed_approved_task_with_workspace(
    db_session: Session,
    repo_id: uuid.UUID,
    user_id: uuid.UUID,
    base_rev: str = "main",
) -> tuple[Task, TaskPlan, Workspace]:
    """Helper to seed task through approval and workspace setup."""
    repo = TaskRepository(db_session)
    task = repo.create_task(
        repository_id=repo_id,
        title="Implement secure token rotation",
        source_type=TaskSourceType.GITHUB_ISSUE,
        user_id=user_id,
        base_revision=base_rev,
    )
    plan = repo.save_plan(
        task_id=task.id,
        repository_id=repo_id,
        summary="Security rotation plan",
        steps=[{"step": 1, "description": "Update token generator"}],
        expected_files=["app/core/tokens.py"],
        base_revision=base_rev,
    )
    repo.approve_plan(
        task_id=task.id,
        repository_id=repo_id,
        plan_version=plan.version,
        user_id=user_id,
    )
    ws = repo.record_workspace(
        task_id=task.id,
        repository_id=repo_id,
        task_branch=f"agent/task-{task.id}",
        base_revision=base_rev,
        workspace_path=f"/tmp/workspaces/{task.id}",
    )
    return task, plan, ws


# ===========================================================================
# 1. Independent Verification Persistence & State Transitions (§6 F36)
# ===========================================================================

class TestIndependentVerificationPersistence:
    """Verifies multi-dimensional verification result logging and state gating."""

    def test_record_and_get_verification_results(self, db_session: Session) -> None:
        user, repo = _seed_user_and_repo(db_session, "ver-1")
        repository = TaskRepository(db_session)
        task, plan, ws = _seed_approved_task_with_workspace(db_session, repo.id, user.id)

        # Move to EXECUTING -> TESTING
        ex = repository.record_execution_start(task.id, repo.id, worker_id="worker-01")
        repository.record_execution_finish(task.id, repo.id, execution_id=ex.id, status=ExecutionStatus.COMPLETED)
        repository.record_test_run(task.id, repo.id, command="pytest", status=TestRunStatus.PASSED)

        checks = [
            {"name": "tests", "status": "PASSED"},
            {"name": "static_analysis", "status": "PASSED"},
            {"name": "ai_code_review", "status": "COMPLETED"},
            {"name": "secret_scan", "status": "PASSED"},
        ]
        ver = repository.record_verification_result(
            task_id=task.id,
            repository_id=repo.id,
            verified_revision="git-commit-abc123",
            status=VerificationStatus.PASSED,
            checks=checks,
            summary="All 4 checks passed with token ghp_secretKey1234567890123456789012345678",
        )

        assert ver.id is not None
        assert ver.verified_revision == "git-commit-abc123"
        assert ver.status == "PASSED"
        assert len(ver.checks) == 4
        assert "ghp_" not in ver.summary
        assert "[REDACTED]" in ver.summary

        # Query all and latest
        results = repository.get_verification_results(task.id, repo.id)
        assert len(results) == 1
        assert results[0].id == ver.id

        latest = repository.get_latest_verification_result(task.id, repo.id)
        assert latest is not None
        assert latest.id == ver.id

    def test_passing_verification_advances_task_to_ready_for_publication(self, db_session: Session) -> None:
        user, repo = _seed_user_and_repo(db_session, "ver-2")
        repository = TaskRepository(db_session)
        task, plan, ws = _seed_approved_task_with_workspace(db_session, repo.id, user.id)

        ex = repository.record_execution_start(task.id, repo.id, worker_id="worker-02")
        repository.record_execution_finish(task.id, repo.id, execution_id=ex.id, status=ExecutionStatus.COMPLETED)

        # Passing verification with zero blocking findings
        repository.record_verification_result(
            task_id=task.id,
            repository_id=repo.id,
            verified_revision="rev-ok-123",
            status=VerificationStatus.PASSED,
            blocking_findings=[],
            summary="Clean verification",
        )

        refreshed_task = repository.get_task(task.id, repo.id)
        assert refreshed_task.status == TaskStatus.READY_FOR_PUBLICATION.value

    def test_blocking_findings_transitions_task_to_blocked(self, db_session: Session) -> None:
        user, repo = _seed_user_and_repo(db_session, "ver-3")
        repository = TaskRepository(db_session)
        task, plan, ws = _seed_approved_task_with_workspace(db_session, repo.id, user.id)

        ex = repository.record_execution_start(task.id, repo.id, worker_id="worker-03")
        repository.record_execution_finish(task.id, repo.id, execution_id=ex.id, status=ExecutionStatus.COMPLETED)

        # Verification with blocking security finding
        blocking = [
            {"id": "SEC-01", "rule": "SQL_INJECTION", "severity": "HIGH", "file": "app/db.py"}
        ]
        repository.record_verification_result(
            task_id=task.id,
            repository_id=repo.id,
            verified_revision="rev-bad-456",
            status=VerificationStatus.PASSED,  # Even if status is passed, blocking findings block publication!
            blocking_findings=blocking,
            summary="Found security violation",
        )

        refreshed_task = repository.get_task(task.id, repo.id)
        assert refreshed_task.status == TaskStatus.BLOCKED.value

    def test_failed_verification_status_transitions_task_to_blocked(self, db_session: Session) -> None:
        user, repo = _seed_user_and_repo(db_session, "ver-4")
        repository = TaskRepository(db_session)
        task, plan, ws = _seed_approved_task_with_workspace(db_session, repo.id, user.id)

        ex = repository.record_execution_start(task.id, repo.id, worker_id="worker-04")
        repository.record_execution_finish(task.id, repo.id, execution_id=ex.id, status=ExecutionStatus.COMPLETED)

        repository.record_verification_result(
            task_id=task.id,
            repository_id=repo.id,
            verified_revision="rev-failed-789",
            status=VerificationStatus.FAILED,
            summary="Static checks failed",
        )

        refreshed_task = repository.get_task(task.id, repo.id)
        assert refreshed_task.status == TaskStatus.BLOCKED.value

    def test_verification_on_terminal_task_rejected(self, db_session: Session) -> None:
        user, repo = _seed_user_and_repo(db_session, "ver-5")
        repository = TaskRepository(db_session)
        task = repository.create_task(repo.id, "Terminal task")
        task.status = TaskStatus.FAILED.value
        db_session.commit()

        with pytest.raises(InvalidStateTransitionError, match="terminal status"):
            repository.record_verification_result(
                task_id=task.id,
                repository_id=repo.id,
                verified_revision="rev-xyz",
                status=VerificationStatus.PASSED,
            )


# ===========================================================================
# 2. Publication Authorization Gate (§6 F37)
# ===========================================================================

class TestPublicationAuthorizationGate:
    """Verifies that publishing requires explicit human authorization and passing verification."""

    def test_authorize_publication_success_and_state_transition(self, db_session: Session) -> None:
        user, repo = _seed_user_and_repo(db_session, "pub-1")
        repository = TaskRepository(db_session)
        task, plan, ws = _seed_approved_task_with_workspace(db_session, repo.id, user.id)

        ex = repository.record_execution_start(task.id, repo.id, worker_id="worker-01")
        repository.record_execution_finish(task.id, repo.id, execution_id=ex.id, status=ExecutionStatus.COMPLETED)
        repository.record_verification_result(
            task_id=task.id,
            repository_id=repo.id,
            verified_revision="head-sha-777",
            status=VerificationStatus.PASSED,
            blocking_findings=[],
            summary="Verification passed without blockers",
        )

        # Task is now in READY_FOR_PUBLICATION
        assert task.status == TaskStatus.READY_FOR_PUBLICATION.value

        # Authorize publication
        updated_task = repository.authorize_publication(
            task_id=task.id,
            repository_id=repo.id,
            head_sha="head-sha-777",
            user_id=user.id,
            notes="Ready for PR with key sk-groqSecretKey1234567890123456",
        )

        assert updated_task.status == TaskStatus.PUBLISHING.value

        # Verify timeline event
        timeline = repository.get_task_timeline(task.id, repo.id)
        auth_events = [ev for ev in timeline if ev.event_type == TaskEventType.PUBLICATION_AUTHORIZED.value]
        assert len(auth_events) == 1
        assert auth_events[0].event_data["authorized_head_sha"] == "head-sha-777"
        assert "sk-" not in auth_events[0].event_data["notes"]
        assert "[REDACTED]" in auth_events[0].event_data["notes"]

    def test_authorize_publication_rejected_when_not_in_ready_status(self, db_session: Session) -> None:
        user, repo = _seed_user_and_repo(db_session, "pub-2")
        repository = TaskRepository(db_session)
        task = repository.create_task(repo.id, "Unverified task")
        task.status = TaskStatus.EXECUTING.value
        db_session.commit()

        with pytest.raises(InvalidStateTransitionError, match="requires READY_FOR_PUBLICATION"):
            repository.authorize_publication(task.id, repo.id, head_sha="some-sha")

    def test_authorize_publication_rejected_on_revision_mismatch(self, db_session: Session) -> None:
        user, repo = _seed_user_and_repo(db_session, "pub-3")
        repository = TaskRepository(db_session)
        task, plan, ws = _seed_approved_task_with_workspace(db_session, repo.id, user.id)

        ex = repository.record_execution_start(task.id, repo.id, worker_id="worker-01")
        repository.record_execution_finish(task.id, repo.id, execution_id=ex.id, status=ExecutionStatus.COMPLETED)
        repository.record_verification_result(
            task_id=task.id,
            repository_id=repo.id,
            verified_revision="verified-sha-111",
            status=VerificationStatus.PASSED,
        )

        # Attempt to authorize different revision
        with pytest.raises(InvalidStateTransitionError, match="does not match latest verified revision"):
            repository.authorize_publication(task.id, repo.id, head_sha="different-sha-222")

    def test_authorize_publication_rejected_if_verification_had_blocking_findings(self, db_session: Session) -> None:
        user, repo = _seed_user_and_repo(db_session, "pub-4")
        repository = TaskRepository(db_session)
        task, plan, ws = _seed_approved_task_with_workspace(db_session, repo.id, user.id)

        ex = repository.record_execution_start(task.id, repo.id, worker_id="worker-01")
        repository.record_execution_finish(task.id, repo.id, execution_id=ex.id, status=ExecutionStatus.COMPLETED)
        repository.record_verification_result(
            task_id=task.id,
            repository_id=repo.id,
            verified_revision="sha-blocked",
            status=VerificationStatus.PASSED,
            blocking_findings=[{"id": "CRIT-01", "msg": "Vulnerability detected"}],
        )

        # Task is BLOCKED, not READY_FOR_PUBLICATION
        with pytest.raises(InvalidStateTransitionError):
            repository.authorize_publication(task.id, repo.id, head_sha="sha-blocked")


# ===========================================================================
# 3. Pull Request Persistence & Idempotency (§6 F37)
# ===========================================================================

class TestPullRequestPersistence:
    """Verifies PR metadata persistence, state transitions, and retry idempotency."""

    def test_record_pull_request_advances_task_to_draft_pr_created(self, db_session: Session) -> None:
        user, repo = _seed_user_and_repo(db_session, "pr-1")
        repository = TaskRepository(db_session)
        task, plan, ws = _seed_approved_task_with_workspace(db_session, repo.id, user.id)

        ex = repository.record_execution_start(task.id, repo.id, worker_id="worker-01")
        repository.record_execution_finish(task.id, repo.id, execution_id=ex.id, status=ExecutionStatus.COMPLETED)
        repository.record_verification_result(
            task.id, repo.id, "sha-999", VerificationStatus.PASSED, blocking_findings=[]
        )
        repository.authorize_publication(task.id, repo.id, head_sha="sha-999", user_id=user.id)

        pr = repository.record_pull_request(
            task_id=task.id,
            repository_id=repo.id,
            pr_url="https://github.com/octocat/sample-repo/pull/42",
            base_branch="main",
            head_branch="agent/task-123",
            head_sha="sha-999",
            title="Fix authentication token refresh",
            body="Generated PR description with sk-apiKey12345678901234567890",
            pr_number=42,
            is_draft=True,
        )

        assert pr.id is not None
        assert pr.pr_number == 42
        assert pr.is_draft is True
        assert "sk-" not in pr.body
        assert "[REDACTED]" in pr.body

        # Verify task transitioned to DRAFT_PR_CREATED
        refreshed_task = repository.get_task(task.id, repo.id)
        assert refreshed_task.status == TaskStatus.DRAFT_PR_CREATED.value

        # Verify query method
        fetched_pr = repository.get_pull_request(task.id, repo.id)
        assert fetched_pr is not None
        assert fetched_pr.id == pr.id
        assert fetched_pr.pr_url == "https://github.com/octocat/sample-repo/pull/42"

    def test_record_pull_request_blocked_without_publication_authorization(self, db_session: Session) -> None:
        user, repo = _seed_user_and_repo(db_session, "pr-2")
        repository = TaskRepository(db_session)
        task = repository.create_task(repo.id, "Task not yet published")
        task.status = TaskStatus.EXECUTING.value
        db_session.commit()

        with pytest.raises(InvalidStateTransitionError, match="Publication authorization is required"):
            repository.record_pull_request(
                task_id=task.id,
                repository_id=repo.id,
                pr_url="https://github.com/org/repo/pull/99",
                base_branch="main",
                head_branch="agent/task-unauthorized",
                head_sha="sha-unauth",
                title="Unauthorized PR",
            )

    def test_record_pull_request_is_idempotent_on_retries(self, db_session: Session) -> None:
        user, repo = _seed_user_and_repo(db_session, "pr-3")
        repository = TaskRepository(db_session)
        task, plan, ws = _seed_approved_task_with_workspace(db_session, repo.id, user.id)

        ex = repository.record_execution_start(task.id, repo.id, worker_id="worker-01")
        repository.record_execution_finish(task.id, repo.id, execution_id=ex.id, status=ExecutionStatus.COMPLETED)
        repository.record_verification_result(task.id, repo.id, "sha-idem", VerificationStatus.PASSED)
        repository.authorize_publication(task.id, repo.id, head_sha="sha-idem")

        # Initial PR creation
        pr1 = repository.record_pull_request(
            task_id=task.id,
            repository_id=repo.id,
            pr_url="https://github.com/org/repo/pull/10",
            base_branch="main",
            head_branch="agent/task-idem",
            head_sha="sha-idem",
            title="Initial draft title",
            pr_number=10,
        )

        # Retry with updated title / details (e.g. network retry after draft PR created)
        pr2 = repository.record_pull_request(
            task_id=task.id,
            repository_id=repo.id,
            pr_url="https://github.com/org/repo/pull/10",
            base_branch="main",
            head_branch="agent/task-idem",
            head_sha="sha-idem",
            title="Updated draft title on retry",
            pr_number=10,
        )

        assert pr1.id == pr2.id
        assert pr2.title == "Updated draft title on retry"


# ===========================================================================
# 4. End-to-End Traceability Graph (§6 F39, Day 5 Deliverable)
# ===========================================================================

class TestEndToEndTraceability:
    """Verifies complete traceability graph: Finding -> Issue/Task -> Plan -> Workspace -> Execution -> Test -> Repair -> Verification -> PR."""

    def test_end_to_end_traceability_graph_complete(self, db_session: Session) -> None:
        user, repo = _seed_user_and_repo(db_session, "trace-1")
        repository = TaskRepository(db_session)

        # 1. Seed Week 2 Finding
        analysis_run = AnalysisRun(
            id=uuid.uuid4(),
            repository_id=repo.id,
            feature_type=AnalysisFeature.DETECT_BUGS.value,
            status=AnalysisRunStatus.COMPLETED.value,
            target_path="backend/app/auth.py",
            source_revision="base-commit-000",
        )
        db_session.add(analysis_run)
        db_session.flush()

        finding = AnalysisFinding(
            id=uuid.uuid4(),
            analysis_run_id=analysis_run.id,
            repository_id=repo.id,
            category="SECURITY",
            severity="HIGH",
            title="Hardcoded credential leak in auth.py",
            description="Found sensitive credential reference",
            evidence="const token = 'sk-test'",
            file_path="backend/app/auth.py",
            start_line=45,
            end_line=48,
        )
        db_session.add(finding)
        db_session.flush()

        # 2. Create Task linked to Finding
        task = repository.create_task(
            repository_id=repo.id,
            title="Fix credential leak in auth.py",
            source_type=TaskSourceType.BUG_FINDING,
            finding_id=finding.id,
            user_id=user.id,
            base_revision="base-commit-000",
        )

        # 3. Plan & Approve
        plan = repository.save_plan(
            task_id=task.id,
            repository_id=repo.id,
            summary="Remediate credential leak",
            steps=[{"step": 1, "action": "Move credential to env"}],
            expected_files=["backend/app/auth.py"],
            base_revision="base-commit-000",
        )
        repository.approve_plan(task.id, repo.id, plan_version=plan.version, user_id=user.id)

        # 4. Workspace
        ws = repository.record_workspace(
            task_id=task.id,
            repository_id=repo.id,
            task_branch=f"agent/task-{task.id}",
            base_revision="base-commit-000",
            workspace_path=f"/tmp/workspaces/{task.id}",
        )

        # 5. Execution
        exec_start = repository.record_execution_start(task.id, repo.id, worker_id="worker-e2e")
        exec_finish = repository.record_execution_finish(task.id, repo.id, execution_id=exec_start.id, status=ExecutionStatus.COMPLETED)

        # 6. Test Run
        test_run = repository.record_test_run(
            task_id=task.id,
            repository_id=repo.id,
            command="pytest backend/tests/test_auth.py",
            status=TestRunStatus.PASSED,
            tests_total=5,
            tests_passed=5,
            tests_failed=0,
            target_revision="rev-final-999",
        )

        # 7. Verification
        ver = repository.record_verification_result(
            task_id=task.id,
            repository_id=repo.id,
            verified_revision="rev-final-999",
            status=VerificationStatus.PASSED,
            checks=[{"name": "tests", "status": "PASSED"}],
            blocking_findings=[],
            summary="All independent verification checks passed",
        )

        # 8. Publication Authorization
        repository.authorize_publication(task.id, repo.id, head_sha="rev-final-999", user_id=user.id)

        # 9. Draft PR
        pr = repository.record_pull_request(
            task_id=task.id,
            repository_id=repo.id,
            pr_url="https://github.com/org/repo/pull/88",
            base_branch="main",
            head_branch=f"agent/task-{task.id}",
            head_sha="rev-final-999",
            title="[Draft] Remediate credential leak in auth.py",
            pr_number=88,
        )

        # 10. Query Traceability Graph
        trace = repository.get_task_traceability(task.id, repo.id)

        assert trace["task"]["task_id"] == str(task.id)
        assert trace["task"]["status"] == TaskStatus.DRAFT_PR_CREATED.value

        # Finding linkage
        assert trace["finding"] is not None
        assert trace["finding"]["finding_id"] == str(finding.id)
        assert trace["finding"]["severity"] == "HIGH"

        # Plan linkage
        assert trace["latest_plan"] is not None
        assert trace["latest_plan"]["version"] == 1

        # Approval linkage
        assert trace["latest_approval"] is not None
        assert trace["latest_approval"]["decision"] == ApprovalDecision.APPROVED.value

        # Workspace linkage
        assert trace["workspace"] is not None
        assert trace["workspace"]["task_branch"] == f"agent/task-{task.id}"

        # Execution linkage
        assert trace["latest_execution"] is not None
        assert trace["latest_execution"]["worker_id"] == "worker-e2e"

        # Test Run linkage
        assert trace["latest_test_run"] is not None
        assert trace["latest_test_run"]["tests_passed"] == 5

        # Verification linkage
        assert trace["latest_verification"] is not None
        assert trace["latest_verification"]["verified_revision"] == "rev-final-999"

        # Pull Request linkage
        assert trace["pull_request"] is not None
        assert trace["pull_request"]["pr_number"] == 88

        # Timeline linkage
        assert len(trace["timeline"]) >= 7

        # Overall traceability status
        assert trace["traceability_status"] == "COMPLETE"


# ===========================================================================
# 5. Multi-Tenant Isolation & Security
# ===========================================================================

class TestMultiTenantDay5Isolation:
    """Verifies that verification, pull request, and traceability are repository-isolated."""

    def test_cross_repository_verification_and_pr_access_blocked(self, db_session: Session) -> None:
        user1, repo1 = _seed_user_and_repo(db_session, "iso-1")
        user2, repo2 = _seed_user_and_repo(db_session, "iso-2")
        repository = TaskRepository(db_session)

        task1, plan1, ws1 = _seed_approved_task_with_workspace(db_session, repo1.id, user1.id)
        ex = repository.record_execution_start(task1.id, repo1.id, worker_id="w1")
        repository.record_execution_finish(task1.id, repo1.id, execution_id=ex.id, status=ExecutionStatus.COMPLETED)
        repository.record_verification_result(task1.id, repo1.id, "sha-iso", VerificationStatus.PASSED)
        repository.authorize_publication(task1.id, repo1.id, head_sha="sha-iso")
        repository.record_pull_request(
            task_id=task1.id,
            repository_id=repo1.id,
            pr_url="https://github.com/org/repo1/pull/1",
            base_branch="main",
            head_branch="agent/task-1",
            head_sha="sha-iso",
            title="Repo 1 PR",
        )

        # Attempt to access Repo 1 artifacts via Repo 2
        with pytest.raises(TaskNotFoundError):
            repository.get_verification_results(task1.id, repo2.id)

        with pytest.raises(TaskNotFoundError):
            repository.get_pull_request(task1.id, repo2.id)

        with pytest.raises(TaskNotFoundError):
            repository.authorize_publication(task1.id, repo2.id, head_sha="sha-iso")

        with pytest.raises(TaskNotFoundError):
            repository.get_task_traceability(task1.id, repo2.id)


# ===========================================================================
# 6. Pydantic Response Schema Conformity
# ===========================================================================

class TestDay5PydanticSchemaConformity:
    """Verifies that model to_dict() envelopes match Day 5 Pydantic response models."""

    def test_model_to_dict_matches_pydantic_day5_response_schemas(self, db_session: Session) -> None:
        user, repo = _seed_user_and_repo(db_session, "schema-1")
        repository = TaskRepository(db_session)
        task, plan, ws = _seed_approved_task_with_workspace(db_session, repo.id, user.id)

        ex = repository.record_execution_start(task.id, repo.id, worker_id="w-schema")
        repository.record_execution_finish(task.id, repo.id, execution_id=ex.id, status=ExecutionStatus.COMPLETED)

        ver = repository.record_verification_result(
            task.id, repo.id, "sha-pydantic", VerificationStatus.PASSED, summary="Verified"
        )
        ver_dict = ver.to_dict()
        ver_pydantic = VerificationResultResponse.model_validate(ver_dict)
        assert ver_pydantic.verified_revision == "sha-pydantic"

        repository.authorize_publication(task.id, repo.id, head_sha="sha-pydantic", user_id=user.id)

        pr = repository.record_pull_request(
            task.id, repo.id, "https://github.com/octo/repo/pull/5", "main", "agent/task", "sha-pydantic", "PR title", pr_number=5
        )
        pr_dict = pr.to_dict()
        pr_pydantic = TaskPullRequestResponse.model_validate(pr_dict)
        assert pr_pydantic.pr_number == 5

        # Traceability response schema validation
        trace = repository.get_task_traceability(task.id, repo.id)
        trace_pydantic = TaskTraceabilityResponse.model_validate(trace)
        assert trace_pydantic.traceability_status == "COMPLETE"
        assert trace_pydantic.pull_request.pr_url == "https://github.com/octo/repo/pull/5"
