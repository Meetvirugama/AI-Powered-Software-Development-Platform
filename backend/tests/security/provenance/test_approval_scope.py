"""Tests for cryptographic binding, scoping, and lifecycle of ExecutionApproval.

Reference:
- task.md §9 (Narrowly Scoped Human Approval)
- task.md §11 (Tests 12, 13, 14, 15, 16)
"""

from datetime import datetime, timedelta, timezone
from uuid import uuid4
import pytest

from ai.security.taint_policy import (
    ExecutionApproval,
    PolicyDecision,
    TaintPolicyEngine,
    compute_argument_hash,
)
from ai.security.taint_tracker import reset_taint_tracker


@pytest.fixture(autouse=True)
def setup():
    reset_taint_tracker()
    yield
    reset_taint_tracker()


def test_changed_arguments_invalidate_approval():
    """Modifying even a single character in arguments invalidates the approval."""
    engine = TaintPolicyEngine()
    task_id = str(uuid4())
    step_id = "step_cmd"
    original_args = {"command": "npm run build"}

    approval = engine.create_approval(
        task_id=task_id,
        step_id=step_id,
        action_type="command",
        arguments=original_args,
    )

    # Valid with original arguments
    assert approval.is_valid_for(
        task_id=task_id,
        action_type="command",
        arguments=original_args,
    ) is True

    # Tampered arguments must fail verification
    tampered_args = {"command": "npm run build --evil"}
    assert approval.is_valid_for(
        task_id=task_id,
        action_type="command",
        arguments=tampered_args,
    ) is False


def test_cross_task_approval_reuse_rejected():
    """An approval created for task A cannot be applied to task B."""
    engine = TaintPolicyEngine()
    task_a = str(uuid4())
    task_b = str(uuid4())
    args = {"command": "git push"}

    approval = engine.create_approval(
        task_id=task_a,
        step_id="step_pub",
        action_type="publish",
        arguments=args,
    )

    # Attempting to use on task B
    assert approval.is_valid_for(
        task_id=task_b,
        action_type="publish",
        arguments=args,
    ) is False


def test_cross_repository_approval_reuse_rejected():
    """An approval scoped to repo A cannot be used on repo B."""
    engine = TaintPolicyEngine()
    task_id = str(uuid4())
    repo_a = str(uuid4())
    repo_b = str(uuid4())
    args = {"command": "deploy"}

    approval = engine.create_approval(
        task_id=task_id,
        step_id="step_deploy",
        action_type="command",
        arguments=args,
        metadata={"repository_id": repo_a},
    )

    assert approval.is_valid_for(
        task_id=task_id,
        action_type="command",
        arguments=args,
        repository_id=repo_a,
    ) is True

    assert approval.is_valid_for(
        task_id=task_id,
        action_type="command",
        arguments=args,
        repository_id=repo_b,
    ) is False


def test_expired_approvals_rejected():
    """Approvals past their TTL are marked expired and rejected."""
    task_id = str(uuid4())
    args = {"command": "echo hello"}
    arg_hash = compute_argument_hash(args)
    past_time = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()

    approval = ExecutionApproval(
        task_id=task_id,
        step_id="step_1",
        action_type="command",
        argument_digest=arg_hash,
        approved_by="human_admin",
        expires_at=past_time,
        status="approved",
    )

    assert approval.is_valid_for(
        task_id=task_id,
        action_type="command",
        arguments=args,
    ) is False
    assert approval.status == "expired"


def test_approval_consumption_and_policy_allowance():
    """Valid approval converts a REQUIRES_APPROVAL action to ALLOW."""
    engine = TaintPolicyEngine()
    task_id = str(uuid4())
    args = {"command": "make release"}

    # Without approval: requires approval
    res_before = engine.evaluate(
        action_type="command",
        arguments=args,
        provenance_ids=["prov-untrusted"],
        task_id=task_id,
    )
    assert res_before.decision == PolicyDecision.REQUIRES_APPROVAL

    # Grant approval
    approval = engine.create_approval(
        task_id=task_id,
        step_id="step_release",
        action_type="command",
        arguments=args,
    )

    # With approval: allowed
    res_after = engine.evaluate(
        action_type="command",
        arguments=args,
        provenance_ids=["prov-untrusted"],
        task_id=task_id,
        approvals=[approval],
    )
    assert res_after.decision == PolicyDecision.ALLOW
    assert res_after.matching_approval_id == approval.approval_id

    # Consume approval
    approval.consume()
    assert approval.status == "consumed"

    # After consumption: cannot reuse
    res_consumed = engine.evaluate(
        action_type="command",
        arguments=args,
        provenance_ids=["prov-untrusted"],
        task_id=task_id,
        approvals=[approval],
    )
    assert res_consumed.decision == PolicyDecision.REQUIRES_APPROVAL
