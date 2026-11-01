"""Unit tests for Week 3 Day 2 Planner Schema & Step Dependency Graph.

Owner: Dev — Week 3 Day 2 Deliverable (Docs/daily_tasks.md line 616 & Docs/week3.md §6 F32)
Coverage:
1. PlanStep validation (step_id pattern, repo-relative path traversal security, dependencies).
2. PlanDependencyGraph DAG validation (self-dependencies, dangling references, cycle detection).
3. Topological sorting and execution wave staging for parallel execution.
4. StructuredPlan (PlannerSchema) model integrity, commit SHA checks, and file consolidation.
5. Task constraint enforcement (validate_against_constraints checking forbidden files).
6. PlanApprovalPayload, PlanRejectionPayload, and approval state transitions.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.schemas.plan import (
    PlanApprovalPayload,
    PlanDependencyGraph,
    PlanRejectionPayload,
    PlanRevisionRequest,
    PlanRisk,
    PlanStep,
    PlannerSchema,
    StructuredPlan,
    ValidationStrategy,
)


# ---------------------------------------------------------------------------
# 1. PlanStep Model & Security Validation Tests
# ---------------------------------------------------------------------------

def test_plan_step_valid_construction():
    """Verify valid PlanStep creation with attributes and defaults."""
    step = PlanStep(
        step_id="step_1",
        title="Inspect user auth controller",
        description="Verify token extraction logic in auth controller.",
        step_type="inspect",
        expected_files=["backend/app/api/auth.py"],
        dependencies=[],
        verification=["pytest backend/tests/test_auth.py"],
        risk_level="low",
    )
    assert step.step_id == "step_1"
    assert step.title == "Inspect user auth controller"
    assert step.step_type == "inspect"
    assert step.expected_files == ["backend/app/api/auth.py"]
    assert step.dependencies == []
    assert step.risk_level == "low"
    assert step.rollback_hint is None


def test_plan_step_rejects_invalid_step_id():
    """Verify step_id format constraint (alphanumeric, hyphens, underscores)."""
    with pytest.raises(ValidationError) as exc_info:
        PlanStep(
            step_id="step 1 with spaces!",
            title="Invalid step id",
            description="Testing step_id pattern validation.",
        )
    assert "Invalid step_id" in str(exc_info.value)


def test_plan_step_rejects_path_traversal_in_expected_files():
    """Verify expected_files prevents path traversal escapes."""
    with pytest.raises(ValidationError) as exc_info:
        PlanStep(
            step_id="step_bad_path",
            title="Malicious file write",
            description="Attempt to escape repo boundary.",
            expected_files=["../../etc/passwd"],
        )
    assert "Unsafe expected_file" in str(exc_info.value)


def test_plan_step_dependencies_deduplicated_and_cleaned():
    """Verify dependencies are stripped and deduplicated."""
    step = PlanStep(
        step_id="step_2",
        title="Run tests",
        description="Run test suite after changes.",
        dependencies=["step_1", "step_1", "  step_0  "],
    )
    assert step.dependencies == ["step_1", "step_0"]


def test_plan_step_rejects_empty_dependency_string():
    """Verify empty or blank dependency IDs are rejected."""
    with pytest.raises(ValidationError) as exc_info:
        PlanStep(
            step_id="step_2",
            title="Run tests",
            description="Run test suite.",
            dependencies=["   "],
        )
    assert "Dependency step_id cannot be blank" in str(exc_info.value)


# ---------------------------------------------------------------------------
# 2. PlanDependencyGraph DAG Validation & Cycle Detection Tests
# ---------------------------------------------------------------------------

def test_dependency_graph_linear_topological_sort():
    """Verify linear dependency chain step_1 -> step_2 -> step_3 orders correctly."""
    steps = [
        PlanStep(step_id="step_3", title="Step 3", description="Third", dependencies=["step_2"]),
        PlanStep(step_id="step_1", title="Step 1", description="First", dependencies=[]),
        PlanStep(step_id="step_2", title="Step 2", description="Second", dependencies=["step_1"]),
    ]
    graph = PlanDependencyGraph(steps)
    graph.validate()
    order = graph.get_execution_order()
    assert order == ["step_1", "step_2", "step_3"]

    stages = graph.get_execution_stages()
    assert stages == [["step_1"], ["step_2"], ["step_3"]]


def test_dependency_graph_diamond_dag_and_stages():
    """Verify diamond dependency graph resolves correct stages for parallel execution."""
    # step_1 -> (step_2a, step_2b) -> step_3
    steps = [
        PlanStep(step_id="step_1", title="Init", description="Root step"),
        PlanStep(step_id="step_2a", title="Feature A", description="Branch A", dependencies=["step_1"]),
        PlanStep(step_id="step_2b", title="Feature B", description="Branch B", dependencies=["step_1"]),
        PlanStep(step_id="step_3", title="Integration", description="Merge step", dependencies=["step_2a", "step_2b"]),
    ]
    graph = PlanDependencyGraph(steps)
    graph.validate()

    order = graph.get_execution_order()
    assert order[0] == "step_1"
    assert set(order[1:3]) == {"step_2a", "step_2b"}
    assert order[3] == "step_3"

    stages = graph.get_execution_stages()
    assert len(stages) == 3
    assert stages[0] == ["step_1"]
    assert set(stages[1]) == {"step_2a", "step_2b"}
    assert stages[2] == ["step_3"]


def test_dependency_graph_detects_duplicate_step_id():
    """Verify duplicate step IDs raise clear ValueError."""
    steps = [
        PlanStep(step_id="step_1", title="Step 1", description="First"),
        PlanStep(step_id="step_1", title="Step 1 Duplicate", description="Second"),
    ]
    graph = PlanDependencyGraph(steps)
    with pytest.raises(ValueError) as exc_info:
        graph.validate()
    assert "Duplicate step_id(s) found in plan: step_1" in str(exc_info.value)


def test_dependency_graph_detects_self_dependency():
    """Verify step depending on itself raises ValueError."""
    steps = [
        PlanStep(step_id="step_loop", title="Loop", description="Self loop", dependencies=["step_loop"])
    ]
    graph = PlanDependencyGraph(steps)
    with pytest.raises(ValueError) as exc_info:
        graph.validate()
    assert "Self-dependency detected: Step 'step_loop' cannot depend on itself" in str(exc_info.value)


def test_dependency_graph_detects_dangling_dependency():
    """Verify dependency on a non-existent step raises ValueError."""
    steps = [
        PlanStep(step_id="step_1", title="Step 1", description="First", dependencies=["step_ghost"])
    ]
    graph = PlanDependencyGraph(steps)
    with pytest.raises(ValueError) as exc_info:
        graph.validate()
    assert "Dangling dependency: Step 'step_1' depends on unknown step 'step_ghost'" in str(exc_info.value)


def test_dependency_graph_detects_two_step_cycle():
    """Verify direct cycle step_1 -> step_2 -> step_1 is detected with path."""
    steps = [
        PlanStep(step_id="step_1", title="A", description="A", dependencies=["step_2"]),
        PlanStep(step_id="step_2", title="B", description="B", dependencies=["step_1"]),
    ]
    graph = PlanDependencyGraph(steps)
    with pytest.raises(ValueError) as exc_info:
        graph.validate()
    assert "Cyclic step dependency detected" in str(exc_info.value)


def test_dependency_graph_detects_multi_step_cycle():
    """Verify cycle across 3 steps (step_1 -> step_2 -> step_3 -> step_1) is caught."""
    steps = [
        PlanStep(step_id="step_1", title="A", description="A", dependencies=["step_3"]),
        PlanStep(step_id="step_2", title="B", description="B", dependencies=["step_1"]),
        PlanStep(step_id="step_3", title="C", description="C", dependencies=["step_2"]),
    ]
    graph = PlanDependencyGraph(steps)
    with pytest.raises(ValueError) as exc_info:
        graph.validate()
    assert "Cyclic step dependency detected" in str(exc_info.value)


# ---------------------------------------------------------------------------
# 3. StructuredPlan (PlannerSchema) Model Integrity Tests
# ---------------------------------------------------------------------------

def test_structured_plan_valid_instantiation():
    """Verify canonical StructuredPlan matching Docs/week3.md §6 F32."""
    plan = StructuredPlan(
        task_id="task_123",
        plan_version=1,
        base_revision="abc1234567def",
        summary="Fix incorrect input validation",
        problem_statement="Input parser throws unhandled exception on null byte.",
        assumptions=["Python 3.11+ stdlib available", "Existing tests pass"],
        unresolved_questions=[],
        relevant_files=["backend/app/input.py"],
        relevant_symbols=["InputParser.validate"],
        steps=[
            PlanStep(
                step_id="step_1",
                title="Inspect validation path",
                description="Inspect the validation path in input.py",
                step_type="inspect",
                expected_files=["backend/app/input.py"],
                dependencies=[],
                verification=["Existing validation tests pass"],
            ),
            PlanStep(
                step_id="step_2",
                title="Implement minimal correction",
                description="Implement the minimal validation correction",
                step_type="edit",
                expected_files=["backend/app/input.py"],
                dependencies=["step_1"],
                verification=["New regression test passes"],
            ),
        ],
        validation_strategy=ValidationStrategy(
            automated_tests=["pytest backend/tests/test_input.py"],
            verification_suite=["tests", "static_analysis", "secret_scan", "ai_code_review"],
        ),
        risks_and_side_effects=[
            PlanRisk(
                risk_id="rsk-1",
                description="May reject legacy malformed payloads",
                severity="low",
                mitigation="Add backward-compatibility option",
            )
        ],
    )
    assert plan.task_id == "task_123"
    assert plan.plan_version == 1
    assert plan.status == "PENDING_APPROVAL"
    assert plan.expected_files_to_modify == ["backend/app/input.py"]
    assert plan.get_execution_order() == ["step_1", "step_2"]
    assert len(plan.get_execution_stages()) == 2


def test_planner_schema_alias_identity():
    """Verify PlannerSchema is an exact alias for StructuredPlan."""
    assert PlannerSchema is StructuredPlan


def test_structured_plan_rejects_invalid_commit_sha():
    """Verify invalid base_revision commit SHA raises ValidationError."""
    with pytest.raises(ValidationError) as exc_info:
        StructuredPlan(
            task_id="task_123",
            base_revision="not-a-valid-sha-xyz",
            summary="Invalid sha test",
            problem_statement="Testing commit sha validation",
            steps=[PlanStep(step_id="step_1", title="Step 1", description="Desc")],
        )
    assert "Invalid base_revision commit SHA format" in str(exc_info.value)


def test_structured_plan_rejects_empty_steps():
    """Verify plan must have at least one step."""
    with pytest.raises(ValidationError):
        StructuredPlan(
            task_id="task_123",
            base_revision="1234567890abcdef",
            summary="Empty steps test",
            problem_statement="Should fail because steps is empty",
            steps=[],
        )


def test_structured_plan_auto_consolidates_expected_files():
    """Verify expected_files across multiple steps are consolidated into expected_files_to_modify."""
    plan = StructuredPlan(
        task_id="task_123",
        base_revision="1234567890abcdef",
        summary="Consolidation test",
        problem_statement="Check expected_files consolidation",
        steps=[
            PlanStep(step_id="step_1", title="Edit A", description="Edit A", expected_files=["src/a.py"]),
            PlanStep(
                step_id="step_2",
                title="Edit B",
                description="Edit B",
                dependencies=["step_1"],
                expected_files=["src/b.py", "src/a.py"],
            ),
        ],
    )
    assert plan.expected_files_to_modify == ["src/a.py", "src/b.py"]


def test_structured_plan_rejects_cyclic_steps_on_creation():
    """Verify Pydantic model validator rejects cyclic plans immediately upon creation."""
    with pytest.raises(ValidationError) as exc_info:
        StructuredPlan(
            task_id="task_123",
            base_revision="1234567890abcdef",
            summary="Cycle test",
            problem_statement="Should fail due to cycle",
            steps=[
                PlanStep(step_id="step_1", title="A", description="A", dependencies=["step_2"]),
                PlanStep(step_id="step_2", title="B", description="B", dependencies=["step_1"]),
            ],
        )
    assert "Cyclic step dependency detected" in str(exc_info.value)


# ---------------------------------------------------------------------------
# 4. Policy Constraint Checking Tests
# ---------------------------------------------------------------------------

def test_validate_against_constraints_detects_forbidden_files():
    """Verify validate_against_constraints flags forbidden files under policy."""
    plan = StructuredPlan(
        task_id="task_123",
        base_revision="1234567890abcdef",
        summary="Constraint check",
        problem_statement="Check policy guardrails",
        steps=[
            PlanStep(
                step_id="step_1",
                title="Modify config",
                description="Edit app configuration",
                expected_files=["backend/app/config.py"],
            )
        ],
    )
    with pytest.raises(ValueError) as exc_info:
        plan.validate_against_constraints(forbidden_files=["backend/app/config.py", ".env.production"])
    assert "Plan targets forbidden file(s) under policy constraint: backend/app/config.py" in str(exc_info.value)


def test_validate_against_constraints_passes_when_disjoint():
    """Verify validate_against_constraints passes when no forbidden files are targeted."""
    plan = StructuredPlan(
        task_id="task_123",
        base_revision="1234567890abcdef",
        summary="Disjoint check",
        problem_statement="Check safe files",
        steps=[
            PlanStep(
                step_id="step_1",
                title="Modify service",
                description="Edit app service",
                expected_files=["backend/app/service.py"],
            )
        ],
    )
    conflicts = plan.validate_against_constraints(forbidden_files=["backend/app/config.py"])
    assert conflicts == []


# ---------------------------------------------------------------------------
# 5. Plan Approval & Rejection Workflow Tests
# ---------------------------------------------------------------------------

def test_plan_approval_transition():
    """Verify approve() transitions plan to APPROVED with auditor attribution."""
    plan = StructuredPlan(
        task_id="task_123",
        plan_version=1,
        base_revision="1234567890abcdef",
        summary="Approval test",
        problem_statement="Test human approval",
        steps=[PlanStep(step_id="step_1", title="Step 1", description="Desc")],
    )
    assert plan.status == "PENDING_APPROVAL"
    assert plan.approved_by is None

    plan.approve(approved_by="tech_lead_alice", notes="Looks well-scoped.")
    assert plan.status == "APPROVED"
    assert plan.approved_by == "tech_lead_alice"
    assert plan.approved_at is not None


def test_plan_rejection_transition():
    """Verify reject() transitions plan to REJECTED with mandatory justification."""
    plan = StructuredPlan(
        task_id="task_123",
        plan_version=1,
        base_revision="1234567890abcdef",
        summary="Rejection test",
        problem_statement="Test human rejection",
        steps=[PlanStep(step_id="step_1", title="Step 1", description="Desc")],
    )
    plan.reject(rejected_by="security_reviewer_bob", reason="Missing authentication check.")
    assert plan.status == "REJECTED"
    assert plan.rejection_reason == "Missing authentication check."
    assert plan.approved_by is None


def test_plan_approval_and_rejection_payload_schemas():
    """Verify approval and rejection request payload schemas."""
    approval = PlanApprovalPayload(
        plan_version=2,
        approved_by="lead_dev",
        review_notes="Approved for workspace execution.",
    )
    assert approval.plan_version == 2
    assert approval.approved_by == "lead_dev"

    rejection = PlanRejectionPayload(
        plan_version=2,
        rejected_by="qa_engineer",
        reason="Does not address edge case with null input.",
        requested_revisions=["Add null check step", "Add unit test for null input"],
    )
    assert rejection.plan_version == 2
    assert len(rejection.requested_revisions) == 2

    revision_req = PlanRevisionRequest(
        target_plan_version=1,
        feedback="Include integration test",
    )
    assert revision_req.target_plan_version == 1

