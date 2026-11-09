"""Durable Autonomous Task Workflow Execution Subsystem.

Integrates DBOS durable workflows and multi-step recovery for autonomous task execution:
1. VALIDATE_APPROVAL: Verifies human plan approval (ADR-010) and base revision consistency.
2. INITIALIZE_WORKSPACE: Sets up isolated workspace sandbox (READY -> IN_USE).
3. EXECUTE_PLAN_AND_SYNTHESIZE: Runs plan steps via AgentExecutionLoop and EditSynthesizer.
4. VALIDATE_PLAN_BOUND_DIFF: Verifies that modified files strictly match approved expected files.
5. RUN_TESTS_AND_REPAIR: Executes restricted tests and bounded self-repair (max 3 attempts).
6. RUN_INDEPENDENT_VERIFICATION: Multi-dimensional verification (Diff, Security, AST, AI Review).
7. PUBLISH_DRAFT_PR: Commits, pushes, and creates GitHub Draft PR if publication is authorized.
8. COMPLETE_WORKFLOW: Finalizes execution telemetry and emits completion events.
"""

from __future__ import annotations

import asyncio
import json
import logging
import threading
import time
import uuid
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from app.core.database import SessionLocal
from app.core.redis import get_redis
from app.core.secret_redaction import redact, redact_obj
from app.models.task import AgentTask, TaskStatus
from app.repositories.task_repository import TaskRepository
from app.schemas.workspace import WorkspaceExecutionEventType
from app.services.task_execution_orchestrator import (
    TaskExecutionOrchestrator,
    get_task_execution_orchestrator,
)
from sandbox.diff_verifier import WorkspaceDiffVerifier
from sandbox.exceptions import WorkspaceError
from ai.workflows.workflow_models import (
    AutonomousWorkflowInput,
    AutonomousWorkflowResult,
    AutonomousWorkflowStatus,
    WorkflowStepRecord,
)

try:
    from dbos import DBOS, WorkflowStatus
    import dbos._reg as dbosreg
    HAS_DBOS = True
except ImportError:
    DBOS = None  # type: ignore
    WorkflowStatus = None  # type: ignore
    dbosreg = None
    HAS_DBOS = False


def dbos_workflow(*dargs, **dkwargs):
    """Workflow decorator that delegates to DBOS when initialized, or executes natively."""
    def decorator(fn):
        if HAS_DBOS and DBOS is not None:
            wrapped = DBOS.workflow(*dargs, **dkwargs)(fn)
            @functools.wraps(fn)
            def runner(*args, **kwargs):
                if getattr(dbosreg, "dbos", None) is not None:
                    return wrapped(*args, **kwargs)
                return fn(*args, **kwargs)
            return runner
        return fn
    return decorator


def dbos_step(*dargs, **dkwargs):
    """Step decorator that delegates to DBOS when initialized, or executes natively."""
    def decorator(fn):
        if HAS_DBOS and DBOS is not None:
            wrapped = DBOS.step(*dargs, **dkwargs)(fn)
            @functools.wraps(fn)
            def runner(*args, **kwargs):
                if getattr(dbosreg, "dbos", None) is not None:
                    return wrapped(*args, **kwargs)
                return fn(*args, **kwargs)
            return runner
        return fn
    return decorator

logger = logging.getLogger(__name__)

# In-memory durable registry for fast status queries and duplicate prevention
_active_workflows: dict[str, AutonomousWorkflowResult] = {}
_task_to_workflow: dict[str, str] = {}
_registry_lock = threading.RLock()


# ---------------------------------------------------------------------------
# Progress Event Publishing
# ---------------------------------------------------------------------------

def publish_workflow_event(
    task_id: str,
    workflow_id: str,
    event_type: str,
    message: str,
    payload: dict[str, Any] | None = None,
    user_id: str | None = None,
) -> None:
    """Publish a real-time event to the Redis 'platform_events' channel for SSE subscribers."""
    try:
        r = get_redis()
        event_dict = {
            "type": event_type,
            "user_id": user_id,
            "data": {
                "task_id": task_id,
                "workflow_id": workflow_id,
                "message": redact(message),
                "timestamp": datetime.now(UTC).isoformat(),
                **(payload or {}),
            },
        }
        r.publish("platform_events", json.dumps(event_dict))
    except Exception as exc:
        logger.debug("publish_workflow_event_failed: %s", exc)


# ---------------------------------------------------------------------------
# Durable Workflow Step Functions
# ---------------------------------------------------------------------------

@dbos_step()
def step_validate_approval(task_id: str, actor_id: str | None, plan_version: int | None) -> dict[str, Any]:
    """Step 1: Validate task approval status and plan version."""
    with SessionLocal() as db:
        repo = TaskRepository(db)
        task = repo.get(UUID(task_id))
        if not task:
            raise ValueError(f"Task '{task_id}' not found.")

        # Ensure task has an approved plan
        plan = repo.get_approved_plan(task.id)
        if not plan:
            raise ValueError(f"Task '{task_id}' has no approved plan. Approval gate violation (ADR-010).")

        if plan_version is not None and plan.plan_version != plan_version:
            raise ValueError(f"Plan version mismatch: expected {plan_version}, found {plan.plan_version}.")

        return {
            "task_id": str(task.id),
            "status": task.status,
            "plan_version": plan.plan_version,
            "expected_files": getattr(plan, "expected_files", []) or [],
        }


@dbos_step()
def step_initialize_workspace(task_id: str) -> dict[str, Any]:
    """Step 2: Initialize workspace sandbox and transition state to IN_USE."""
    orchestrator = get_task_execution_orchestrator()
    with SessionLocal() as db:
        repo = TaskRepository(db)
        task = repo.get(UUID(task_id))
        if not task:
            raise ValueError(f"Task '{task_id}' not found.")

        orchestrator.ensure_workspace_loaded(task)
        meta = orchestrator.workspace_manager.get_workspace(task_id)
        return {
            "task_id": task_id,
            "workspace_path": meta.workspace_path if meta else "",
            "workspace_status": meta.status.value if meta else "",
        }


@dbos_step()
def step_execute_plan_and_synthesize(
    task_id: str,
    step_payloads: dict[str, Any] | None,
    actor_id: str | None,
) -> dict[str, Any]:
    """Step 3: Execute approved plan steps with AgentExecutionLoop & EditSynthesizer."""
    orchestrator = get_task_execution_orchestrator()
    actor_uuid = UUID(actor_id) if actor_id else None

    with SessionLocal() as db:
        repo = TaskRepository(db)
        task = repo.get(UUID(task_id))
        if not task:
            raise ValueError(f"Task '{task_id}' not found.")

        orchestrator.start_task_execution(
            task=task,
            task_repo=repo,
            actor_id=actor_uuid,
            dry_run=False,
            run_steps=True,
            step_payloads=step_payloads,
            run_tests_after=False,
            auto_repair=False,
        )
        orchestrator.save_task_checkpoint(task, repo, step_name="post_step_execution")

        db.commit()
        return {
            "task_id": task_id,
            "task_status": task.status,
            "step_count": len(task.execution_steps or []),
        }


@dbos_step()
def step_validate_plan_bound_diff(task_id: str) -> dict[str, Any]:
    """Step 4: Verify that workspace diff strictly adheres to approved plan scope."""
    orchestrator = get_task_execution_orchestrator()
    diff_verifier = WorkspaceDiffVerifier()

    with SessionLocal() as db:
        repo = TaskRepository(db)
        task = repo.get(UUID(task_id))
        if not task:
            raise ValueError(f"Task '{task_id}' not found.")

        plan = repo.get_approved_plan(task.id)
        allowed_files = list(getattr(plan, "expected_files", []) or [])

        # Extract git diff
        diff_res = diff_verifier.extract_diff(
            task_id=task_id,
            workspace_path=orchestrator.workspace_manager.get_workspace_path(task_id),
            base_revision=task.base_revision,
        )
        validation_res = diff_verifier.validate_diff(diff_res, allowed_files=allowed_files)

        if not validation_res.is_valid:
            err_msg = f"Plan-bound diff validation failed: {validation_res.blocking_findings}"
            raise WorkspaceError(err_msg)

        return {
            "is_valid": True,
            "modified_files": validation_res.modified_files,
            "unapproved_files": validation_res.unapproved_files,
        }


@dbos_step()
def step_run_tests_and_repair(
    task_id: str,
    auto_repair: bool,
    actor_id: str | None,
) -> dict[str, Any]:
    """Step 5: Run tests and perform bounded self-repair if needed."""
    orchestrator = get_task_execution_orchestrator()
    actor_uuid = UUID(actor_id) if actor_id else None

    with SessionLocal() as db:
        repo = TaskRepository(db)
        task = repo.get(UUID(task_id))
        if not task:
            raise ValueError(f"Task '{task_id}' not found.")

        test_res = orchestrator.execute_task_tests(task=task, task_repo=repo, actor_id=actor_uuid)
        repair_res = None
        if test_res.status != "PASSED" and auto_repair:
            repair_res = orchestrator.execute_bounded_repair(task=task, task_repo=repo, actor_id=actor_uuid)

        orchestrator.save_task_checkpoint(task, repo, step_name="post_test_and_repair")
        db.commit()

        return {
            "test_status": test_res.status,
            "repair_attempted": repair_res is not None,
            "repair_status": repair_res.status if repair_res else None,
        }


@dbos_step()
def step_run_independent_verification(task_id: str, actor_id: str | None) -> dict[str, Any]:
    """Step 6: Run multi-dimensional independent verification."""
    orchestrator = get_task_execution_orchestrator()
    actor_uuid = UUID(actor_id) if actor_id else None

    with SessionLocal() as db:
        repo = TaskRepository(db)
        task = repo.get(UUID(task_id))
        if not task:
            raise ValueError(f"Task '{task_id}' not found.")

        ver_schema = orchestrator.run_independent_verification(
            task=task,
            task_repo=repo,
            actor_id=actor_uuid,
            require_passing_tests=True,
        )
        orchestrator.save_task_checkpoint(
            task,
            repo,
            step_name="post_independent_verification",
            state_data={"verified_revision": ver_schema.verified_revision, "verification_status": ver_schema.status},
        )
        db.commit()

        return ver_schema.model_dump(mode="json")


@dbos_step()
def step_publish_draft_pr_if_authorized(
    task_id: str,
    publication_authorized: bool,
    pr_title: str | None,
    pr_body: str | None,
    actor_id: str | None,
) -> dict[str, Any] | None:
    """Step 7: Create GitHub Draft PR if human publication authorization is granted."""
    if not publication_authorized:
        return None

    orchestrator = get_task_execution_orchestrator()
    actor_uuid = UUID(actor_id) if actor_id else None

    with SessionLocal() as db:
        repo = TaskRepository(db)
        task = repo.get(UUID(task_id))
        if not task:
            raise ValueError(f"Task '{task_id}' not found.")

        # Idempotency check: see if Draft PR already exists
        existing_pr = repo.get_pull_request(task.id)
        if existing_pr:
            return {
                "pr_id": str(existing_pr.id),
                "pr_number": existing_pr.pr_number,
                "pr_url": existing_pr.pr_url,
                "is_draft": existing_pr.is_draft,
                "title": existing_pr.title,
            }

        pr_rec = orchestrator.create_draft_pull_request(
            task=task,
            task_repo=repo,
            actor_id=actor_uuid,
            publication_authorized=True,
            title=pr_title,
            body=pr_body,
        )
        db.commit()

        return {
            "pr_id": str(pr_rec.id),
            "pr_number": pr_rec.pr_number,
            "pr_url": pr_rec.pr_url,
            "is_draft": pr_rec.is_draft,
            "title": pr_rec.title,
        }


# ---------------------------------------------------------------------------
# Main Durable Workflow
# ---------------------------------------------------------------------------

@dbos_workflow()
def run_autonomous_task_workflow(
    input_data: AutonomousWorkflowInput,
    workflow_id: str | None = None,
) -> AutonomousWorkflowResult:
    """Execute the end-to-end autonomous task workflow with durable boundaries."""
    task_id = input_data.task_id
    wf_id = workflow_id or f"wf-{task_id}-{uuid.uuid4().hex[:8]}"
    start_iso = datetime.now(UTC).isoformat()

    result = AutonomousWorkflowResult(
        workflow_id=wf_id,
        task_id=task_id,
        status=AutonomousWorkflowStatus.RUNNING,
        started_at=start_iso,
        updated_at=start_iso,
    )

    with _registry_lock:
        _active_workflows[wf_id] = result
        _task_to_workflow[task_id] = wf_id

    def update_step(name: str, status: str, output: dict[str, Any] | None = None, error: str | None = None) -> None:
        rec = result.step_records.get(name) or WorkflowStepRecord(step_name=name, status=status)
        rec.status = status
        if output:
            rec.output = output
        if error:
            rec.error = error
        if status in ("COMPLETED", "FAILED"):
            rec.completed_at = datetime.now(UTC).isoformat()
        result.step_records[name] = rec
        if status == "COMPLETED" and name not in result.completed_steps:
            result.completed_steps.append(name)
        result.updated_at = datetime.now(UTC).isoformat()

    try:
        # Step 1: Validate Approval
        result.status = AutonomousWorkflowStatus.RUNNING
        result.current_step = "VALIDATE_APPROVAL"
        publish_workflow_event(task_id, wf_id, "WORKFLOW_STARTED", "Autonomous workflow initiated.", user_id=input_data.actor_id)
        update_step("VALIDATE_APPROVAL", "RUNNING")
        appr_out = step_validate_approval(task_id, input_data.actor_id, input_data.approved_plan_version)
        update_step("VALIDATE_APPROVAL", "COMPLETED", appr_out)

        # Step 2: Initialize Workspace
        result.current_step = "INITIALIZE_WORKSPACE"
        update_step("INITIALIZE_WORKSPACE", "RUNNING")
        ws_out = step_initialize_workspace(task_id)
        update_step("INITIALIZE_WORKSPACE", "COMPLETED", ws_out)

        # Step 3: Execute Approved Plan & Synthesize Missing Edits
        result.status = AutonomousWorkflowStatus.SYNTHESIZING
        result.current_step = "EXECUTE_APPROVED_PLAN"
        publish_workflow_event(task_id, wf_id, "SYNTHESIS_STARTED", "Executing plan steps and synthesizing missing edits.", user_id=input_data.actor_id)
        update_step("EXECUTE_APPROVED_PLAN", "RUNNING")
        plan_out = step_execute_plan_and_synthesize(task_id, input_data.step_payloads, input_data.actor_id)
        update_step("EXECUTE_APPROVED_PLAN", "COMPLETED", plan_out)

        # Step 4: Validate Plan-Bound Diff
        result.status = AutonomousWorkflowStatus.VALIDATING
        result.current_step = "VALIDATE_PLAN_BOUND_DIFF"
        update_step("VALIDATE_PLAN_BOUND_DIFF", "RUNNING")
        diff_out = step_validate_plan_bound_diff(task_id)
        update_step("VALIDATE_PLAN_BOUND_DIFF", "COMPLETED", diff_out)

        # Step 5: Run Tests and Bounded Self-Repair
        if input_data.run_tests:
            result.status = AutonomousWorkflowStatus.TESTING
            result.current_step = "RUN_TESTS_AND_REPAIR"
            publish_workflow_event(task_id, wf_id, "TESTS_STARTED", "Running workspace test suites.", user_id=input_data.actor_id)
            update_step("RUN_TESTS_AND_REPAIR", "RUNNING")
            test_out = step_run_tests_and_repair(task_id, input_data.auto_repair, input_data.actor_id)
            update_step("RUN_TESTS_AND_REPAIR", "COMPLETED", test_out)

        # Step 6: Independent Verification
        result.status = AutonomousWorkflowStatus.VERIFYING
        result.current_step = "RUN_INDEPENDENT_VERIFICATION"
        publish_workflow_event(task_id, wf_id, "VERIFICATION_STARTED", "Conducting independent verification.", user_id=input_data.actor_id)
        update_step("RUN_INDEPENDENT_VERIFICATION", "RUNNING")
        ver_out = step_run_independent_verification(task_id, input_data.actor_id)
        update_step("RUN_INDEPENDENT_VERIFICATION", "COMPLETED", ver_out)
        result.verification = ver_out

        # Step 7: Draft PR Publication
        if input_data.publication_authorized:
            result.current_step = "PUBLISH_DRAFT_PR"
            update_step("PUBLISH_DRAFT_PR", "RUNNING")
            pr_out = step_publish_draft_pr_if_authorized(
                task_id=task_id,
                publication_authorized=True,
                pr_title=input_data.pr_title,
                pr_body=input_data.pr_body,
                actor_id=input_data.actor_id,
            )
            update_step("PUBLISH_DRAFT_PR", "COMPLETED", pr_out or {})
            result.pull_request = pr_out

        # Complete Workflow
        result.status = AutonomousWorkflowStatus.COMPLETED
        result.current_step = None
        result.completed_at = datetime.now(UTC).isoformat()
        result.updated_at = result.completed_at
        publish_workflow_event(task_id, wf_id, "WORKFLOW_COMPLETED", "Autonomous workflow completed successfully.", user_id=input_data.actor_id)

    except Exception as exc:
        err_msg = redact(str(exc))
        logger.error("autonomous_workflow_step_failed", extra={"task_id": task_id, "workflow_id": wf_id, "error": err_msg})
        result.status = AutonomousWorkflowStatus.FAILED
        result.error_summary = err_msg
        result.completed_at = datetime.now(UTC).isoformat()
        result.updated_at = result.completed_at
        if result.current_step:
            update_step(result.current_step, "FAILED", error=err_msg)
        publish_workflow_event(task_id, wf_id, "WORKFLOW_FAILED", f"Autonomous workflow failed: {err_msg}", payload={"error": err_msg}, user_id=input_data.actor_id)

    return result


# ---------------------------------------------------------------------------
# Workflow Registry & Asynchronous Submission
# ---------------------------------------------------------------------------

def get_active_workflow(task_id: str) -> AutonomousWorkflowResult | None:
    """Retrieve currently active workflow for task_id, if running."""
    with _registry_lock:
        wf_id = _task_to_workflow.get(task_id)
        if wf_id:
            wf = _active_workflows.get(wf_id)
            if wf and wf.status in (
                AutonomousWorkflowStatus.QUEUED,
                AutonomousWorkflowStatus.RUNNING,
                AutonomousWorkflowStatus.SYNTHESIZING,
                AutonomousWorkflowStatus.VALIDATING,
                AutonomousWorkflowStatus.TESTING,
                AutonomousWorkflowStatus.REPAIRING,
                AutonomousWorkflowStatus.VERIFYING,
            ):
                return wf
    return None


def get_workflow_by_id(workflow_id: str) -> AutonomousWorkflowResult | None:
    """Retrieve workflow record by workflow_id."""
    with _registry_lock:
        return _active_workflows.get(workflow_id)


def submit_autonomous_workflow(
    input_data: AutonomousWorkflowInput,
    background: bool = True,
) -> tuple[AutonomousWorkflowResult, bool]:
    """Submit autonomous workflow idempotently.

    Returns:
        (result, is_new_submission)
    """
    task_id = input_data.task_id

    with _registry_lock:
        existing = get_active_workflow(task_id)
        if existing:
            return existing, False

        wf_id = f"wf-{task_id}-{uuid.uuid4().hex[:8]}"
        start_iso = datetime.now(UTC).isoformat()
        result = AutonomousWorkflowResult(
            workflow_id=wf_id,
            task_id=task_id,
            status=AutonomousWorkflowStatus.QUEUED,
            started_at=start_iso,
            updated_at=start_iso,
        )
        _active_workflows[wf_id] = result
        _task_to_workflow[task_id] = wf_id

    if background:
        # Launch durable workflow in a background worker thread
        t = threading.Thread(
            target=run_autonomous_task_workflow,
            args=(input_data, wf_id),
            daemon=True,
            name=f"WorkflowThread-{wf_id}",
        )
        t.start()
    else:
        run_autonomous_task_workflow(input_data, wf_id)

    return result, True
