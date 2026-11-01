"""Unit tests for Week 3 Day 1 Task Intake & Verification Schemas.

Owner: Dev — Week 3 Day 1 Deliverable (Docs/daily_tasks.md line 608)
Coverage:
1. TaskStatus enum and canonical state transition validation graph (Docs/week3.md §7.1, §7.2).
2. Segregated task intake elements: requirements, assumptions, and constraints.
3. Path traversal security checks on target_files and forbidden_files.
4. Constraint disjointness validation (target_files vs forbidden_files).
5. Source reference validation (GitHub issue URLs, commit SHAs, finding IDs).
6. Independent verification schema and strict verification policy rules (Docs/week3.md §6 F36).
"""

from __future__ import annotations

import uuid
import pytest
from pydantic import ValidationError

from app.schemas.task import (
    TaskAssumption,
    TaskConstraint,
    TaskCreateRequest,
    TaskDetailResponse,
    TaskIntakePayload,
    TaskRequirement,
    TaskSourceReference,
    TaskStatus,
    VALID_TASK_TRANSITIONS,
    can_transition,
)
from app.schemas.verification import (
    VerificationCheckItem,
    VerificationFinding,
    VerificationResult,
)


# ---------------------------------------------------------------------------
# 1. Task Lifecycle State Machine & Transition Tests (§7.1, §7.2)
# ---------------------------------------------------------------------------

def test_task_status_members_match_specification():
    """Verify all 16 canonical lifecycle states from Docs/week3.md §7.1 exist."""
    expected_states = {
        "CREATED",
        "PLANNING",
        "PENDING_APPROVAL",
        "APPROVED",
        "REJECTED",
        "WORKSPACE_SETUP",
        "EXECUTING",
        "TESTING",
        "REPAIRING",
        "VERIFYING",
        "READY_FOR_PUBLICATION",
        "PUBLISHING",
        "DRAFT_PR_CREATED",
        "FAILED",
        "CANCELLED",
        "RECOVERY_REQUIRED",
        "BLOCKED",
    }
    actual_states = {s.value for s in TaskStatus}
    assert actual_states == expected_states


def test_can_transition_happy_path_sequence():
    """Verify standard happy-path progression passes through human approval and verification."""
    happy_path = [
        (TaskStatus.CREATED, TaskStatus.PLANNING),
        (TaskStatus.PLANNING, TaskStatus.PENDING_APPROVAL),
        (TaskStatus.PENDING_APPROVAL, TaskStatus.APPROVED),
        (TaskStatus.APPROVED, TaskStatus.WORKSPACE_SETUP),
        (TaskStatus.WORKSPACE_SETUP, TaskStatus.EXECUTING),
        (TaskStatus.EXECUTING, TaskStatus.TESTING),
        (TaskStatus.TESTING, TaskStatus.VERIFYING),
        (TaskStatus.VERIFYING, TaskStatus.READY_FOR_PUBLICATION),
        (TaskStatus.READY_FOR_PUBLICATION, TaskStatus.PUBLISHING),
        (TaskStatus.PUBLISHING, TaskStatus.DRAFT_PR_CREATED),
    ]
    for current, target in happy_path:
        assert can_transition(current, target) is True, f"Expected {current} -> {target} to be valid"


def test_can_transition_blocks_unauthorized_jumps():
    """Verify strict policy: PENDING_APPROVAL cannot jump directly to EXECUTING without approval."""
    # Docs/week3.md §7.2: Cannot execute without explicit approval
    assert can_transition(TaskStatus.PENDING_APPROVAL, TaskStatus.EXECUTING) is False
    assert can_transition(TaskStatus.CREATED, TaskStatus.EXECUTING) is False
    assert can_transition(TaskStatus.REJECTED, TaskStatus.EXECUTING) is False
    assert can_transition(TaskStatus.DRAFT_PR_CREATED, TaskStatus.PLANNING) is False
    assert can_transition(TaskStatus.CANCELLED, TaskStatus.EXECUTING) is False


def test_can_transition_allows_self_transition():
    """Verify staying in the same status is always a no-op permitted transition."""
    for state in TaskStatus:
        assert can_transition(state, state) is True


def test_can_transition_supports_repair_and_rejection_flows():
    """Verify repair loops and plan rejection recovery transitions."""
    assert can_transition(TaskStatus.TESTING, TaskStatus.REPAIRING) is True
    assert can_transition(TaskStatus.REPAIRING, TaskStatus.TESTING) is True
    assert can_transition(TaskStatus.PENDING_APPROVAL, TaskStatus.REJECTED) is True
    assert can_transition(TaskStatus.REJECTED, TaskStatus.PLANNING) is True


# ---------------------------------------------------------------------------
# 2. Source Reference Validation Tests
# ---------------------------------------------------------------------------

def test_task_source_reference_valid_github_issue():
    """Verify valid GitHub issue reference parsing."""
    ref = TaskSourceReference(
        type="GITHUB_ISSUE",
        issue_number=42,
        issue_url="https://github.com/Meetvirugama/AI-Powered-Software-Development-Platform/issues/42",
        base_revision="0123456789abcdef",
    )
    assert ref.type == "GITHUB_ISSUE"
    assert ref.issue_number == 42
    assert ref.base_revision == "0123456789abcdef"


def test_task_source_reference_invalid_url():
    """Verify invalid issue URL formats are rejected."""
    with pytest.raises(ValidationError) as exc_info:
        TaskSourceReference(
            type="GITHUB_ISSUE",
            issue_url="ftp://invalid-scheme.com/issue/1",
        )
    assert "Invalid issue URL format" in str(exc_info.value)


def test_task_source_reference_invalid_commit_sha():
    """Verify invalid commit SHA format is rejected."""
    with pytest.raises(ValidationError) as exc_info:
        TaskSourceReference(
            type="USER_PROMPT",
            base_revision="not-a-valid-sha-xyz!",
        )
    assert "Invalid base_revision commit SHA format" in str(exc_info.value)


# ---------------------------------------------------------------------------
# 3. Segregated Elements & Path Traversal Security
# ---------------------------------------------------------------------------

def test_task_requirement_valid_target_files_normalized():
    """Verify target_files are normalized and safely accepted."""
    req = TaskRequirement(
        id="req-1",
        description="Add health check endpoint",
        category="functional",
        target_files=["backend/app/main.py", "backend/tests/test_main.py"],
        acceptance_criteria=["GET /api/health returns 200"],
    )
    assert req.target_files == ["backend/app/main.py", "backend/tests/test_main.py"]


def test_task_requirement_rejects_path_traversal():
    """Verify relative escapes and root paths in target_files are rejected."""
    with pytest.raises(ValidationError) as exc_info:
        TaskRequirement(
            id="req-bad",
            description="Malicious file write",
            target_files=["../../etc/shadow"],
        )
    assert "Unsafe target_file" in str(exc_info.value)


def test_task_constraint_valid_forbidden_files_normalized():
    """Verify forbidden_files in constraints are safely accepted and normalized."""
    constraint = TaskConstraint(
        id="cst-1",
        description="Do not modify production deployment configs",
        constraint_type="protected_file",
        forbidden_files=["deploy/production.yml", ".env.production"],
    )
    assert constraint.forbidden_files == ["deploy/production.yml", ".env.production"]


def test_task_constraint_rejects_path_traversal():
    """Verify path traversal in forbidden_files is rejected."""
    with pytest.raises(ValidationError) as exc_info:
        TaskConstraint(
            id="cst-bad",
            description="Malicious escape",
            constraint_type="protected_file",
            forbidden_files=["/etc/passwd"],
        )
    assert "Unsafe forbidden_file" in str(exc_info.value)


def test_task_assumption_model():
    """Verify assumption model structure and flags."""
    assumption = TaskAssumption(
        id="asm-1",
        description="Target repository uses pytest framework",
        unresolved=True,
        risk_level="high",
    )
    assert assumption.unresolved is True
    assert assumption.risk_level == "high"


# ---------------------------------------------------------------------------
# 4. Task Intake Payload & Disjointness Validation
# ---------------------------------------------------------------------------

def test_task_intake_payload_success():
    """Verify valid intake payload creation with all segregated elements."""
    repo_id = uuid.uuid4()
    payload = TaskIntakePayload(
        repository_id=repo_id,
        title="Implement secure file parsing",
        description="Safely parse files without path traversal vulnerabilities.",
        source=TaskSourceReference(type="USER_PROMPT"),
        requirements=[
            TaskRequirement(
                id="req-1",
                description="Parse repo relative paths safely",
                target_files=["backend/app/core/input_security.py"],
            )
        ],
        assumptions=[
            TaskAssumption(
                id="asm-1",
                description="Python 3.11+ pathlib is available",
                unresolved=False,
            )
        ],
        constraints=[
            TaskConstraint(
                id="cst-1",
                description="Never modify root configuration",
                constraint_type="protected_file",
                forbidden_files=["backend/app/main.py"],
            )
        ],
    )
    assert payload.repository_id == repo_id
    assert payload.title == "Implement secure file parsing"
    assert len(payload.requirements) == 1
    assert len(payload.assumptions) == 1
    assert len(payload.constraints) == 1


def test_task_intake_payload_disjointness_violation():
    """Verify error when a requirement targets a file listed in forbidden_files constraints."""
    repo_id = uuid.uuid4()
    with pytest.raises(ValidationError) as exc_info:
        TaskIntakePayload(
            repository_id=repo_id,
            title="Overlap defect",
            description="Should fail due to constraint conflict.",
            source=TaskSourceReference(type="USER_PROMPT"),
            requirements=[
                TaskRequirement(
                    id="req-conflict",
                    description="Update config file",
                    target_files=["backend/app/config.py"],
                )
            ],
            constraints=[
                TaskConstraint(
                    id="cst-protect",
                    description="Config is immutable",
                    constraint_type="protected_file",
                    forbidden_files=["backend/app/config.py"],
                )
            ],
        )
    assert "targets forbidden file(s): backend/app/config.py" in str(exc_info.value)


def test_task_intake_payload_requires_at_least_one_requirement():
    """Verify intake fails if requirements list is empty."""
    with pytest.raises(ValidationError):
        TaskIntakePayload(
            repository_id=uuid.uuid4(),
            title="Empty task",
            description="No requirements provided",
            source=TaskSourceReference(type="USER_PROMPT"),
            requirements=[],
        )


def test_task_intake_payload_rejects_blank_title():
    """Verify intake fails if title is only whitespace."""
    with pytest.raises(ValidationError) as exc_info:
        TaskIntakePayload(
            repository_id=uuid.uuid4(),
            title="   ",
            description="Some description",
            source=TaskSourceReference(type="USER_PROMPT"),
            requirements=[
                TaskRequirement(id="req-1", description="Valid req")
            ],
        )
    assert "Task title must contain non-whitespace characters" in str(exc_info.value)


def test_task_detail_response_construction():
    """Verify task detail response envelope serialization."""
    repo_id = str(uuid.uuid4())
    task_id = "task_98765"
    response = TaskDetailResponse(
        task_id=task_id,
        repository_id=repo_id,
        title="Add user avatar upload",
        description="Allow users to upload profile pictures",
        status=TaskStatus.CREATED,
        source=TaskSourceReference(type="USER_PROMPT"),
        requirements=[
            TaskRequirement(id="req-1", description="Save avatar to storage")
        ],
        plan_version=1,
        repair_attempts_used=0,
        repair_attempts_max=3,
    )
    assert response.task_id == task_id
    assert response.status == TaskStatus.CREATED
    assert response.plan_version == 1
    assert response.repair_attempts_max == 3


# ---------------------------------------------------------------------------
# 5. Independent Verification Schema & Policy Rules (§6 F36)
# ---------------------------------------------------------------------------

def test_verification_result_pass_success():
    """Verify valid PASS verification result where all checks pass and 0 blockers exist."""
    res = VerificationResult(
        task_id="task_123",
        verified_revision="abcdef123456",
        status="PASS",
        checks=[
            VerificationCheckItem(name="tests", status="PASSED", duration_ms=1200),
            VerificationCheckItem(name="static_analysis", status="PASSED", duration_ms=450),
            VerificationCheckItem(name="secret_scan", status="PASSED", duration_ms=110),
            VerificationCheckItem(name="ai_code_review", status="COMPLETED", duration_ms=2300),
        ],
        blocking_findings=[],
        warnings=[],
        pr_summary="Automated verification passed successfully.",
    )
    assert res.is_pass is True
    assert res.is_eligible_for_publication is True


def test_verification_policy_unavailable_check_cannot_be_pass():
    """Docs/week3.md §6: Any check marked as UNAVAILABLE or SKIPPED cannot be counted as PASSED."""
    with pytest.raises(ValidationError) as exc_info:
        VerificationResult(
            task_id="task_123",
            verified_revision="abcdef123456",
            status="PASS",  # Invalid! Check is UNAVAILABLE
            checks=[
                VerificationCheckItem(name="tests", status="PASSED"),
                VerificationCheckItem(name="static_analysis", status="UNAVAILABLE"),
            ],
        )
    assert "Overall status cannot be 'PASS' when check(s) are UNAVAILABLE or SKIPPED" in str(exc_info.value)


def test_verification_policy_skipped_check_cannot_be_pass():
    """Verify that a skipped check cannot result in PASS status."""
    with pytest.raises(ValidationError) as exc_info:
        VerificationResult(
            task_id="task_123",
            verified_revision="abcdef123456",
            status="PASS",
            checks=[
                VerificationCheckItem(name="tests", status="PASSED"),
                VerificationCheckItem(name="secret_scan", status="SKIPPED"),
            ],
        )
    assert "Overall status cannot be 'PASS' when check(s) are UNAVAILABLE or SKIPPED" in str(exc_info.value)


def test_verification_policy_failed_check_cannot_be_pass():
    """Verify that a failed check strictly blocks PASS status."""
    with pytest.raises(ValidationError) as exc_info:
        VerificationResult(
            task_id="task_123",
            verified_revision="abcdef123456",
            status="PASS",
            checks=[
                VerificationCheckItem(name="tests", status="FAILED", message="2 tests failed"),
                VerificationCheckItem(name="static_analysis", status="PASSED"),
            ],
        )
    assert "Overall status cannot be 'PASS' when check(s) failed: tests" in str(exc_info.value)


def test_verification_policy_blocking_findings_prevent_pass():
    """Docs/week3.md §6: Blocking security or policy findings prevent publication."""
    with pytest.raises(ValidationError) as exc_info:
        VerificationResult(
            task_id="task_123",
            verified_revision="abcdef123456",
            status="PASS",
            checks=[
                VerificationCheckItem(name="tests", status="PASSED"),
                VerificationCheckItem(name="security_scan", status="PASSED"),
            ],
            blocking_findings=[
                VerificationFinding(
                    id="find-sec-1",
                    severity="CRITICAL",
                    category="security",
                    message="Hardcoded AWS secret detected",
                    file_path="backend/app/config.py",
                    line_number=14,
                    blocking=True,
                )
            ],
        )
    assert "Overall status cannot be 'PASS' with 1 blocking finding(s)" in str(exc_info.value)


def test_verification_evaluate_status_helper():
    """Verify automatic derivation of VerificationOverallStatus via evaluate_status helper."""
    # 1. All passed -> PASS
    status = VerificationResult.evaluate_status(
        checks=[
            VerificationCheckItem(name="tests", status="PASSED"),
            VerificationCheckItem(name="static_analysis", status="PASSED"),
        ]
    )
    assert status == "PASS"

    # 2. Failed check -> FAIL
    status = VerificationResult.evaluate_status(
        checks=[
            VerificationCheckItem(name="tests", status="FAILED"),
            VerificationCheckItem(name="static_analysis", status="PASSED"),
        ]
    )
    assert status == "FAIL"

    # 3. Unavailable check -> INCONCLUSIVE (without warnings)
    status = VerificationResult.evaluate_status(
        checks=[
            VerificationCheckItem(name="tests", status="PASSED"),
            VerificationCheckItem(name="static_analysis", status="UNAVAILABLE"),
        ]
    )
    assert status == "INCONCLUSIVE"

    # 4. Warnings present -> REQUIRES_HUMAN_REVIEW
    warning = VerificationFinding(
        id="warn-1",
        severity="LOW",
        category="lint",
        message="Unused variable 'x'",
        blocking=False,
    )
    status = VerificationResult.evaluate_status(
        checks=[
            VerificationCheckItem(name="tests", status="PASSED"),
            VerificationCheckItem(name="static_analysis", status="PASSED"),
        ],
        warnings=[warning],
    )
    assert status == "REQUIRES_HUMAN_REVIEW"
