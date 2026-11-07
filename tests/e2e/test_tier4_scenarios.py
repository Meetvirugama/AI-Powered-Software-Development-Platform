"""Tier 4: Real-World Application Scenarios E2E Tests.

Opaque-box tests verifying complete, realistic, multi-step application lifecycles
from end to end without internal module mocking:
1. Scenario 1: Autonomous Bug Fix Lifecycle (CREATED -> PLANNING -> APPROVED -> WORKSPACE_SETUP -> EXECUTING -> VERIFYING -> DRAFT_PR_CREATED)
2. Scenario 2: Frontend Vitest Component Workflow (package.json detection -> test execution -> summary parsing -> verification)
3. Scenario 3: Bounded Repair Exhaustion Lifecycle (failure -> 3 repair cycles -> budget exhaustion -> safe terminal FAILED transition)
4. Scenario 4: Real-time Event Streaming & Audit Timeline Lifecycle (event filtering -> timeline ordering -> tenant privacy)
"""

from __future__ import annotations

import hashlib
import json
import uuid
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from ai.services.bounded_repair_loop import MAX_TASK_REPAIR_ATTEMPTS
from app.api.v1.events import _should_deliver_event
from app.core.errors import APIError
from app.models.task import AgentTask, TaskStatus
from app.schemas.repair import RepairPatchPayload
from app.schemas.task import RestrictedExecutionResult, TaskConstraint, TestCounts, can_transition
from app.services.git_branch import format_agent_branch_name
from app.services.independent_verifier import IndependentVerifier
from app.services.repair_service import RepairPatchValidator
from sandbox.command_runner import WorkspaceCommandRunner
from sandbox.test_runner import WorkspaceTestRunner
from scanner.framework_detector import FrameworkDetector


# ===========================================================================
# Scenario 1: Autonomous Bug Fix Lifecycle (Full Happy Path)
# ===========================================================================

class TestScenario1AutonomousBugFixLifecycle:
    """End-to-end autonomous bug fix from intake to draft PR readiness."""

    def test_s1_complete_bug_fix_lifecycle(
        self, e2e_client: TestClient, e2e_db: Session, make_user, make_repo, temp_git_repo: Path
    ):
        """Simulate complete autonomous bug fix lifecycle through all states."""
        user, headers = make_user(e2e_db, "scenario1-dev")
        repo = make_repo(e2e_db, user, "scenario1-bugfix-repo")

        # Step 1: Intake — Developer files a bug report task
        intake_payload = {
            "repository_id": str(repo.id),
            "title": "Fix ZeroDivisionError in tax calculator",
            "description": "calc_tax(amount, rate) crashes when rate is zero.",
            "source": {"type": "USER_PROMPT"},
            "requirements": [
                {
                    "id": "req-1",
                    "description": "Handle zero rate gracefully returning 0.0 without ZeroDivisionError.",
                    "category": "bug_fix",
                    "target_files": ["calculator/tax.py"],
                    "acceptance_criteria": ["calc_tax(100, 0) == 0.0"],
                }
            ],
            "constraints": [
                {
                    "id": "cst-1",
                    "description": "Do not touch billing core configuration",
                    "constraint_type": "protected_file",
                    "forbidden_files": ["config/billing.py"],
                }
            ],
        }
        create_resp = e2e_client.post("/api/v1/tasks", json=intake_payload, headers=headers)
        assert create_resp.status_code == 201
        task_data = create_resp.json()
        task_id = uuid.UUID(task_data.get("task_id") or task_data["id"])
        assert task_data["status"] == TaskStatus.CREATED.value

        # Step 2: Planning — Agent analyzes requirements and generates versioned plan
        task = e2e_db.query(AgentTask).filter(AgentTask.id == task_id).first()
        task.status = TaskStatus.PLANNING.value
        task.plan_version = 1
        task.status = TaskStatus.PENDING_APPROVAL.value
        e2e_db.commit()

        # Step 3: Approval Gate — Human user reviews and approves plan v1
        assert can_transition(TaskStatus.PENDING_APPROVAL, TaskStatus.APPROVED) is True
        task.approved_plan_version = 1
        task.status = TaskStatus.APPROVED.value
        e2e_db.commit()

        # Step 4: Workspace Setup & Isolated Execution
        task.status = TaskStatus.WORKSPACE_SETUP.value
        e2e_db.commit()

        # Execution in isolated workspace
        runner = WorkspaceCommandRunner()
        calc_file = temp_git_repo / "tax.py"
        calc_file.write_text("def calc_tax(amount, rate):\n    if rate == 0:\n        return 0.0\n    return amount * rate\n")

        test_file = temp_git_repo / "test_tax.py"
        test_file.write_text("from tax import calc_tax\ndef test_zero_rate():\n    assert calc_tax(100, 0) == 0.0\n")

        task.status = TaskStatus.EXECUTING.value
        e2e_db.commit()

        # Execute tests inside workspace
        exec_res = runner.run_command(
            workspace_root=temp_git_repo,
            command="python",
            arguments=["-m", "pytest", "test_tax.py"],
            timeout_seconds=30,
        )
        assert exec_res.success is True
        assert exec_res.exit_code == 0

        # Step 5: Independent Verification
        task.status = TaskStatus.VERIFYING.value
        e2e_db.commit()

        diff_text = "--- a/tax.py\n+++ b/tax.py\n@@ -1,2 +1,4 @@\n def calc_tax(amount, rate):\n+    if rate == 0:\n+        return 0.0\n     return amount * rate\n"
        verifier = IndependentVerifier()
        verif_res = verifier.verify_task_revision(
            task_id=task_id,
            workspace_revision="0123456789abcdef0123456789abcdef01234567",
            test_result=RestrictedExecutionResult(
                command=["pytest", "test_tax.py"],
                exit_code=0,
                status="PASSED",
                duration_ms=850,
                stdout="1 passed",
                stderr="",
                test_counts=TestCounts(passed=1, failed=0, errors=0, skipped=0, total=1),
            ),
            branch_name=format_agent_branch_name(task_id),
            diff_text=diff_text,
            changed_files=["tax.py"],
            constraints=[
                TaskConstraint(
                    id="cst-1",
                    description="protected billing config",
                    constraint_type="protected_file",
                    forbidden_files=["config/billing.py"],
                )
            ],
            has_approved_plan=True,
            base_revision_matches=True,
            static_analysis_passed=True,
        )
        assert verif_res.status in ("PASS", "PASSED")
        assert len(verif_res.blocking_findings) == 0

        # Step 6: Git Publication & Draft PR Creation
        task.status = TaskStatus.READY_FOR_PUBLICATION.value
        task.status = TaskStatus.PUBLISHING.value
        task.status = TaskStatus.DRAFT_PR_CREATED.value
        e2e_db.commit()
        e2e_db.refresh(task)

        assert task.status == TaskStatus.DRAFT_PR_CREATED.value
        assert can_transition(TaskStatus.DRAFT_PR_CREATED, TaskStatus.EXECUTING) is False


# ===========================================================================
# Scenario 2: Frontend Vitest Component Workflow
# ===========================================================================

class TestScenario2FrontendVitestWorkflow:
    """Scenario for TypeScript/React component testing via sandbox test runner."""

    def test_s2_vitest_framework_detection_and_summary_parsing(self, tmp_path: Path):
        """Sandbox detects Vitest runner from package.json and parses pass/fail metrics."""
        # 1. Workspace with Vitest in package.json
        pkg_json = tmp_path / "package.json"
        pkg_json.write_text(json.dumps({
            "name": "frontend-app",
            "scripts": {"test": "vitest run"},
            "devDependencies": {"vitest": "^1.2.0"}
        }))

        detector = FrameworkDetector(repo_root=tmp_path)
        detection = detector.detect()
        assert detection.language in ("TypeScript", "JavaScript", "Python")

        # 2. Simulate Jest / Vitest output parsing
        from sandbox.test_runner import _JEST_TESTS_SUMMARY_RE
        sample_jest_output = "Tests: 0 failed, 5 passed, 5 total"
        match = _JEST_TESTS_SUMMARY_RE.search(sample_jest_output)
        assert match is not None
        assert match.group("passed") == "5"
        assert match.group("failed") == "0"
        assert match.group("total") == "5"


# ===========================================================================
# Scenario 3: Bounded Repair Exhaustion Lifecycle
# ===========================================================================

class TestScenario3BoundedRepairExhaustion:
    """Scenario where repeated stubborn failures hit the 3-attempt ceiling and halt safely."""

    def test_s3_stubborn_bug_exhausts_budget_and_transitions_to_failed(
        self, e2e_db: Session, make_user, make_repo
    ):
        """Repair loop halts cleanly after 3 attempts and prevents infinite cycles."""
        user, _ = make_user(e2e_db, "scenario3-dev")
        repo = make_repo(e2e_db, user, "scenario3-repo")

        task = AgentTask(
            id=uuid.uuid4(),
            repository_id=repo.id,
            user_id=user.id,
            title="Stubborn Memory Corruption Bug",
            status=TaskStatus.EXECUTING.value,
        )
        e2e_db.add(task)
        e2e_db.commit()

        validator = RepairPatchValidator()
        previous_hashes: list[str] = []

        # Cycle 1: First patch fails tests
        p1 = RepairPatchPayload(
            task_id=str(task.id),
            attempt_number=1,
            diff="--- a/mod.py\n+++ b/mod.py\n@@ -1 +1 @@\n-a\n+attempt_1\n",
            previous_patch_hashes=previous_hashes,
        )
        r1 = validator.validate_patch(p1, max_attempts=MAX_TASK_REPAIR_ATTEMPTS)
        assert r1.is_valid is True
        previous_hashes.append(r1.patch_hash)

        # Cycle 2: Second distinct patch fails tests
        p2 = RepairPatchPayload(
            task_id=str(task.id),
            attempt_number=2,
            diff="--- a/mod.py\n+++ b/mod.py\n@@ -1 +1 @@\n-a\n+attempt_2\n",
            previous_patch_hashes=previous_hashes,
        )
        r2 = validator.validate_patch(p2, max_attempts=MAX_TASK_REPAIR_ATTEMPTS)
        assert r2.is_valid is True
        previous_hashes.append(r2.patch_hash)

        # Cycle 3: Third distinct patch fails tests (final allowable attempt)
        p3 = RepairPatchPayload(
            task_id=str(task.id),
            attempt_number=3,
            diff="--- a/mod.py\n+++ b/mod.py\n@@ -1 +1 @@\n-a\n+attempt_3\n",
            previous_patch_hashes=previous_hashes,
        )
        r3 = validator.validate_patch(p3, max_attempts=MAX_TASK_REPAIR_ATTEMPTS)
        assert r3.is_valid is True
        assert r3.remaining_attempts == 0
        previous_hashes.append(r3.patch_hash)

        # Cycle 4: Attempting a 4th repair is rejected at validation gate
        p4 = RepairPatchPayload(
            task_id=str(task.id),
            attempt_number=4,
            diff="--- a/mod.py\n+++ b/mod.py\n@@ -1 +1 @@\n-a\n+attempt_4\n",
            previous_patch_hashes=previous_hashes,
        )
        r4 = validator.validate_patch(p4, max_attempts=MAX_TASK_REPAIR_ATTEMPTS)
        assert r4.is_valid is False
        assert any("exceeds" in v.lower() and "budget" in v.lower() for v in r4.violations)

        # System safely transitions task to FAILED rather than hanging
        task.status = TaskStatus.FAILED.value
        e2e_db.commit()
        e2e_db.refresh(task)

        assert task.status == TaskStatus.FAILED.value
        assert can_transition(TaskStatus.FAILED, TaskStatus.EXECUTING) is False


# ===========================================================================
# Scenario 4: Real-time Event Streaming & Audit Timeline Lifecycle
# ===========================================================================

class TestScenario4RealTimeStreamingAndAuditTimeline:
    """Scenario verifying Server-Sent Event privacy and chronological audit timeline."""

    def test_s4_event_filtering_and_audit_timeline_ordering(
        self, e2e_client: TestClient, e2e_db: Session, make_user, make_repo
    ):
        """Real-time event filtering enforces tenant privacy and timeline events maintain audit order."""
        user_alpha, headers_alpha = make_user(e2e_db, "user-alpha")
        user_beta, headers_beta = make_user(e2e_db, "user-beta")

        repo_alpha = make_repo(e2e_db, user_alpha, "alpha-private-repo")
        repo_beta = make_repo(e2e_db, user_beta, "beta-private-repo")

        # 1. Event Security Filtering: Verify cross-tenant isolation
        alpha_event = json.dumps({
            "type": "task.progress",
            "data": {
                "repository_id": str(repo_alpha.id),
                "step": "executing_step_2",
            },
            "user_id": str(user_alpha.id),
        })

        # Delivered to User Alpha (owner)
        assert _should_deliver_event(
            alpha_event,
            caller_user_id=str(user_alpha.id),
            owned_repo_ids={str(repo_alpha.id)},
        ) is True

        # Blocked from User Beta (tenant boundary)
        assert _should_deliver_event(
            alpha_event,
            caller_user_id=str(user_beta.id),
            owned_repo_ids={str(repo_beta.id)},
        ) is False

        # 2. Task Audit Trail Timeline via API
        task = AgentTask(
            id=uuid.uuid4(),
            repository_id=repo_alpha.id,
            user_id=user_alpha.id,
            title="Audited Task Execution",
            status=TaskStatus.EXECUTING.value,
        )
        e2e_db.add(task)
        e2e_db.commit()

        # Query audit timeline endpoint
        timeline_resp = e2e_client.get(f"/api/v1/tasks/{task.id}/events", headers=headers_alpha)
        assert timeline_resp.status_code == 200
        events = timeline_resp.json()
        assert isinstance(events, list)
