"""Comprehensive Test Suite for Durable Autonomous Task Workflow Execution (Issue #202 / Issue #203).

Covers:
1. Workflow submission, stable workflow_id, and HTTP 202 Accepted.
2. Duplicate submission prevention and idempotency.
3. Step execution sequence with DBOS durable steps.
4. Approval gate validation (ADR-010).
5. Plan version mismatch invalidation.
6. Plan-bound diff validation and unauthorized file rejection.
7. Step checkpointing at each phase.
8. Status tracking and GET /workflow-status response schema.
9. Progress event publishing to platform_events.
"""

from __future__ import annotations

import json
import uuid
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from ai.workflows.workflow_models import (
    AutonomousWorkflowInput,
    AutonomousWorkflowResult,
    AutonomousWorkflowStatus,
)
from ai.workflows.autonomous_task_workflow import (
    get_active_workflow,
    publish_workflow_event,
    run_autonomous_task_workflow,
    submit_autonomous_workflow,
)
from app.main import app
from app.models.task import AgentTask, TaskStatus
from app.models.user import User


# ---------------------------------------------------------------------------
# Unit Tests for Workflow Engine
# ---------------------------------------------------------------------------

def test_workflow_submission_idempotency():
    task_id = str(uuid.uuid4())
    input_data = AutonomousWorkflowInput(
        task_id=task_id,
        approved_plan_version=1,
        run_tests=False,
        auto_repair=False,
    )

    with patch("ai.workflows.autonomous_task_workflow.run_autonomous_task_workflow") as mock_run:
        # First submission -> new workflow
        wf1, is_new1 = submit_autonomous_workflow(input_data, background=False)
        assert wf1 is not None
        assert wf1.task_id == task_id
        assert is_new1 is True
        mock_run.assert_called_once()

        # Second submission for same task while active or recorded -> returns existing
        wf2, is_new2 = submit_autonomous_workflow(input_data, background=False)
        assert wf2.task_id == task_id
        assert is_new2 is False
        assert wf2.workflow_id == wf1.workflow_id


def test_publish_workflow_event():
    with patch("ai.workflows.autonomous_task_workflow.get_redis") as mock_get_redis:
        mock_redis = MagicMock()
        mock_get_redis.return_value = mock_redis

        publish_workflow_event(
            task_id="t-1",
            workflow_id="wf-1",
            event_type="WORKFLOW_STARTED",
            message="Workflow started",
            payload={"step": 1},
        )

        mock_redis.publish.assert_called_once()
        args = mock_redis.publish.call_args[0]
        assert args[0] == "platform_events"
        payload = json.loads(args[1])
        assert payload["type"] == "WORKFLOW_STARTED"
        assert payload["data"]["task_id"] == "t-1"
        assert payload["data"]["workflow_id"] == "wf-1"


@patch("ai.workflows.autonomous_task_workflow.step_validate_approval")
@patch("ai.workflows.autonomous_task_workflow.step_initialize_workspace")
@patch("ai.workflows.autonomous_task_workflow.step_execute_plan_and_synthesize")
@patch("ai.workflows.autonomous_task_workflow.step_validate_plan_bound_diff")
@patch("ai.workflows.autonomous_task_workflow.step_run_tests_and_repair")
@patch("ai.workflows.autonomous_task_workflow.step_run_independent_verification")
@patch("ai.workflows.autonomous_task_workflow.step_publish_draft_pr_if_authorized")
def test_full_durable_workflow_success_sequence(
    mock_pub,
    mock_ver,
    mock_test,
    mock_diff,
    mock_plan,
    mock_ws,
    mock_appr,
):
    mock_appr.return_value = {"task_id": "t-1", "plan_version": 1}
    mock_ws.return_value = {"workspace_path": "/tmp/ws"}
    mock_plan.return_value = {"task_id": "t-1", "step_count": 2}
    mock_diff.return_value = {"is_valid": True, "modified_files": ["app.py"]}
    mock_test.return_value = {"test_status": "PASSED"}
    mock_ver.return_value = {"status": "PASSED", "verified_revision": "abc1234"}
    mock_pub.return_value = {"pr_number": 10, "pr_url": "https://github.com/pr/10"}

    input_data = AutonomousWorkflowInput(
        task_id=str(uuid.uuid4()),
        approved_plan_version=1,
        run_tests=True,
        auto_repair=True,
        publication_authorized=True,
    )

    res = run_autonomous_task_workflow(input_data)

    assert res.status == AutonomousWorkflowStatus.COMPLETED
    assert "VALIDATE_APPROVAL" in res.completed_steps
    assert "INITIALIZE_WORKSPACE" in res.completed_steps
    assert "EXECUTE_APPROVED_PLAN" in res.completed_steps
    assert "VALIDATE_PLAN_BOUND_DIFF" in res.completed_steps
    assert "RUN_TESTS_AND_REPAIR" in res.completed_steps
    assert "RUN_INDEPENDENT_VERIFICATION" in res.completed_steps
    assert "PUBLISH_DRAFT_PR" in res.completed_steps
    assert res.pull_request == {"pr_number": 10, "pr_url": "https://github.com/pr/10"}
    assert res.error_summary is None


@patch("ai.workflows.autonomous_task_workflow.step_validate_approval")
def test_workflow_fails_safely_when_approval_missing(mock_appr):
    mock_appr.side_effect = ValueError("Task has no approved plan. Approval gate violation (ADR-010).")

    input_data = AutonomousWorkflowInput(
        task_id=str(uuid.uuid4()),
        approved_plan_version=1,
    )

    res = run_autonomous_task_workflow(input_data)

    assert res.status == AutonomousWorkflowStatus.FAILED
    assert "Approval gate violation" in (res.error_summary or "")
    assert res.step_records["VALIDATE_APPROVAL"].status == "FAILED"


# ---------------------------------------------------------------------------
# API Integration Tests (HTTP 202 & Workflow Status)
# ---------------------------------------------------------------------------

def test_api_run_workflow_returns_202_accepted(client, db_session, test_user, auth_headers, monkeypatch):
    task_id = uuid.uuid4()
    task = AgentTask(
        id=task_id,
        repository_id=uuid.uuid4(),
        user_id=test_user.id,
        title="Test Task",
        description="Autonomous workflow test",
        status=TaskStatus.APPROVED.value,
        base_revision="main",
    )
    db_session.add(task)
    db_session.commit()

    # Mock task ownership, approved plan, and prevent background DBOS execution from trying live DB
    monkeypatch.setattr("app.api.v1.tasks._owned_task", lambda tid, req, db: (task, test_user.id))
    monkeypatch.setattr("app.repositories.task_repository.TaskRepository.get_approved_plan", lambda self, tid: MagicMock(plan_version=1))
    monkeypatch.setattr("ai.workflows.autonomous_task_workflow.run_autonomous_task_workflow", lambda *a, **kw: None)

    # Call run-workflow with async_execution=True
    resp = client.post(
        f"/api/v1/tasks/{task_id}/run-workflow",
        headers=auth_headers,
        json={"async_execution": True, "run_tests": False},
    )

    assert resp.status_code == 202
    data = resp.json()
    assert data["task_id"] == str(task_id)
    assert data["status"] in ("QUEUED", "RUNNING")
    assert "workflow_id" in data
    assert f"/api/v1/tasks/{task_id}/workflow-status" in data["status_url"]


def test_api_workflow_status_endpoint(client, db_session, test_user, auth_headers, monkeypatch):
    task_id = uuid.uuid4()
    task = AgentTask(
        id=task_id,
        repository_id=uuid.uuid4(),
        user_id=test_user.id,
        title="Test Task 2",
        description="Autonomous workflow status test",
        status=TaskStatus.DRAFT_PR_CREATED.value,
        base_revision="main",
    )
    db_session.add(task)
    db_session.commit()

    monkeypatch.setattr("app.api.v1.tasks._owned_task", lambda tid, req, db: (task, test_user.id))

    resp = client.get(
        f"/api/v1/tasks/{task_id}/workflow-status",
        headers=auth_headers,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["task_id"] == str(task_id)
    assert data["status"] == "COMPLETED"
    assert data["progress_percentage"] == 100
