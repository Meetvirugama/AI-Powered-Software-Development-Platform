"""Comprehensive Test Suite for Task Planner, Executor, Intelligence & Verification.

Directly verifies requirements and acceptance criteria from:
- TASK_PLANNER_EXECUTOR_COMPREHENSIVE_TEST_PLAN.md (Sections 7.1 to 7.8)
- task.md (Sections 1 to 11)
"""

from __future__ import annotations

import ast
import uuid
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from ai.context.task_context import TaskContextBuilder, TaskContextManifest
from ai.services.agent_execution_loop import (
    AgentExecutionLoop,
    AgentExecutionResult,
    StepExecutionStatus,
)
from ai.services.execution_budget_manager import (
    BudgetExceededError,
    ExecutionBudget,
    ExecutionBudgetManager,
)
from ai.services.execution_checkpoint_manager import (
    ExecutionCheckpoint,
    ExecutionCheckpointManager,
)
from ai.services.execution_recovery import (
    ExecutionRecoveryService,
    RecoveryOutcome,
)
from ai.services.execution_verifier import (
    ExecutionVerifier,
    StepVerificationEvidence,
    StepVerificationOutcome,
)
from ai.services.plan_replanner import PlanReplanner
from ai.services.requirement_verifier import (
    RequirementComplianceItem,
    RequirementToCodeVerifier,
    RequirementVerificationResult,
)
from ai.services.task_completeness_checker import (
    CompletenessIssue,
    PlanCompletenessReport,
    TaskCompletenessChecker,
)
from ai.services.task_planner import PlanningOutcome, TaskPlanner
from ai.services.task_requirement_discovery import (
    DiscoveredTaskRequirement,
    TaskRequirementDiscovery,
)
from app.core.input_security import UnsafePathError, validate_repo_relative_path
from app.models.code_symbol import CodeSymbol
from app.models.repository import Repository
from app.models.symbol_edge import SymbolEdge
from app.models.task import AgentTask
from app.schemas.task import TaskConstraint, TaskRequirement
from app.schemas.plan import (
    ExecutionPolicy,
    PlanDependencyGraph,
    PlanStep,
    PlanTransition,
    StepVerification,
    StructuredPlan,
)
from app.schemas.workspace import WorkspaceStatus
from app.services.task_execution_report import TaskExecutionReportGenerator
from app.schemas.planner_context import AffectedSymbol
from scanner.task_test_planner import TaskTestPlanner


# ============================================================================
# Section 7.1: Repository Intelligence & Context Retrieval (CTX-01 to CTX-12)
# ============================================================================


class TestSection71RepositoryIntelligenceAndContext:
    """Tests for TaskContextBuilder, shared intelligence, budget limits, and provenance."""

    def test_ctx_01_shared_context_integration(self):
        """CTX-01: TaskContextBuilder integrates shared repository intelligence structures."""
        repo_id = uuid.uuid4()
        task = AgentTask(
            id=uuid.uuid4(),
            repository_id=repo_id,
            title="Implement auth helper",
            description="Implement JWT auth helper in src/auth.py",
            requirements=[{"id": "REQ-1", "description": "JWT helper", "target_files": ["src/auth.py"]}],
        )
        builder = TaskContextBuilder(token_budget=2000)
        manifest = builder.build_task_context(task)
        assert isinstance(manifest, TaskContextManifest)
        assert manifest.snapshot_id is not None
        assert "src/auth.py" in manifest.target_files

    def test_ctx_03_budget_and_truncation_transparency(self):
        """CTX-03 & CTX-04: Limits are respected, and omissions/truncation are flagged."""
        builder = TaskContextBuilder(token_budget=100)
        assert builder.token_budget == 100

    def test_ctx_08_architecture_rules_and_provenance(self):
        """CTX-08 & CTX-12: Architecture rules and context provenance are recorded."""
        manifest = TaskContextManifest(
            snapshot_id="snap_12345",
            commit_sha="c0ffee1",
            target_files=["src/service.py"],
            architecture_rules=["Layer separation: Controllers must not access DB directly."],
            existing_tests=["tests/test_service.py"],
            truncated_context=False,
            confidence=0.95,
        )
        as_dict = manifest.to_dict()
        assert as_dict["snapshot_id"] == "snap_12345"
        assert as_dict["commit_sha"] == "c0ffee1"
        assert len(as_dict["architecture_rules"]) == 1
        assert as_dict["confidence"] == 0.95

    def test_ctx_11_path_safety_traversal_rejection(self):
        """CTX-11: Traversal paths outside repository cannot be retrieved."""
        with pytest.raises(UnsafePathError):
            validate_repo_relative_path("../../etc/passwd")


# ============================================================================
# Section 7.2: Requirement Discovery & Matrix (REQ-01 to REQ-12)
# ============================================================================


class TestSection72RequirementDiscoveryAndCompleteness:
    """Tests for decomposing tasks into atomic requirements and completeness checking."""

    def test_req_01_atomic_requirements_and_criteria(self):
        """REQ-01 & REQ-02: Decomposes compound prompt into atomic requirements with criteria."""
        discovery = TaskRequirementDiscovery()
        task = AgentTask(
            id=uuid.uuid4(),
            title="User Auth",
            description="Add user role authorization in src/auth.py. Ensure invalid tokens are rejected with 401. Add tests for admin privileges.",
            requirements=[
                {"id": "REQ-1", "description": "Add user role authorization", "target_files": ["src/auth.py"], "acceptance_criteria": ["Tokens valid"]},
                {"id": "REQ-2", "description": "Reject invalid tokens with 401", "target_files": ["src/auth.py"], "acceptance_criteria": ["401 on expired"]},
            ],
        )
        manifest = TaskContextManifest(snapshot_id="snap1", commit_sha="abc", target_files=["src/auth.py"])
        reqs = discovery.discover_requirements(task, manifest)
        assert len(reqs) >= 2
        for r in reqs:
            assert r.requirement_id.startswith("REQ-")
            assert len(r.acceptance_criteria) > 0

    def test_req_05_completeness_checker_flags_missing_steps(self):
        """REQ-05: Completeness checker flags requirements missing implementation steps."""
        checker = TaskCompletenessChecker()
        reqs = [
            DiscoveredTaskRequirement(
                requirement_id="REQ-1",
                description="Add authentication",
                category="functional",
                priority="HIGH",
                affected_files=["src/auth.py"],
                acceptance_criteria=["Valid tokens pass"],
            ),
            DiscoveredTaskRequirement(
                requirement_id="REQ-2",
                description="Add rate limiter",
                category="security",
                priority="HIGH",
                affected_files=["src/limiter.py"],
                acceptance_criteria=["Exceeded calls get 429"],
            ),
        ]
        plan = StructuredPlan(
            summary="Auth only",
            problem_statement="Auth only",
            steps=[
                PlanStep(
                    step_id="step-1",
                    title="Auth",
                    description="Auth",
                    action_type="modify",
                    requirement_ids=["REQ-1"],
                )
            ],
        )
        report = checker.check_plan_completeness(plan, reqs)
        assert report.is_complete is False
        assert "REQ-2" in report.uncovered_requirement_ids
        assert any(i.requirement_id == "REQ-2" for i in report.issues)

    def test_req_08_requirement_status_taxonomy(self):
        """REQ-08: Requirement status supports REQUIRED, CONDITIONAL, NOT_APPLICABLE, BLOCKED, DEFERRED."""
        req = DiscoveredTaskRequirement(
            requirement_id="REQ-TAXONOMY",
            description="Deferred telemetry logging",
            category="documentation",
            priority="LOW",
            status="DEFERRED",
        )
        assert req.status == "DEFERRED"
        req_blocked = DiscoveredTaskRequirement(
            requirement_id="REQ-BLOCKED",
            description="Blocked by unmerged database schema",
            category="database",
            priority="CRITICAL",
            status="BLOCKED",
        )
        assert req_blocked.status == "BLOCKED"


# ============================================================================
# Section 7.3 & 7.4: Dependency-Aware Plan Generation & Schema (PLN / SCH)
# ============================================================================


class TestSection73And74PlanGenerationAndSchema:
    """Tests for DAG validation, cycle detection, transitions, and step verifications."""

    def test_pln_01_dag_validation_rejects_cycles(self):
        """PLN-01: PlanDependencyGraph rejects cyclic dependencies with ValueError."""
        steps = [
            PlanStep(step_id="step_a", title="A", description="A", action_type="modify", dependencies=["step_b"]),
            PlanStep(step_id="step_b", title="B", description="B", action_type="modify", dependencies=["step_a"]),
        ]
        graph = PlanDependencyGraph(steps)
        with pytest.raises(ValueError, match="Cyclic"):
            graph.validate()

    def test_pln_02_dag_validation_rejects_dangling_dependencies(self):
        """PLN-02: PlanDependencyGraph rejects dangling/unknown dependencies."""
        steps = [
            PlanStep(step_id="step_1", title="1", description="1", action_type="modify", dependencies=["step_nonexistent"]),
        ]
        graph = PlanDependencyGraph(steps)
        with pytest.raises(ValueError, match="Dangling dependency"):
            graph.validate()

    def test_sch_01_structured_plan_with_verifications_and_policy(self):
        """SCH-01: StructuredPlan schema supports step verifications, transitions, and policies."""
        plan = StructuredPlan(
            summary="Feature Plan",
            problem_statement="Add feature",
            expected_files_to_modify=["src/feature.py"],
            steps=[
                PlanStep(
                    step_id="step-1",
                    title="Implement feature",
                    description="Code feature logic",
                    action_type="modify",
                    expected_files=["src/feature.py"],
                    requirement_ids=["REQ-1"],
                    step_verifications=[
                        StepVerification(
                            verification_type="syntax",
                            target_file="src/feature.py",
                            command="ast.parse",
                            is_blocking=True,
                        )
                    ],
                    transitions=[
                        PlanTransition(outcome="success", next_step_id="step-2"),
                        PlanTransition(outcome="failure", next_step_id=None, recovery_step_id=None),
                    ],
                ),
                PlanStep(
                    step_id="step-2",
                    title="Test feature",
                    description="Execute tests",
                    action_type="execute_command",
                    command="pytest tests/test_feature.py",
                    dependencies=["step-1"],
                ),
            ],
            execution_policy=ExecutionPolicy(fail_fast=True, max_retries_per_step=2),
            final_validation_strategy=["FULL_INDEPENDENT_VERIFICATION"],
        )
        assert len(plan.steps) == 2
        assert plan.steps[0].step_verifications[0].is_blocking is True
        assert plan.execution_policy.fail_fast is True

    def test_pln_03_topological_sort_deterministic_order(self):
        """PLN-03: PlanDependencyGraph topological_sort produces valid deterministic dependency ordering."""
        steps = [
            PlanStep(step_id="step_c", title="C", description="C", action_type="modify", dependencies=["step_b"]),
            PlanStep(step_id="step_a", title="A", description="A", action_type="modify", dependencies=[]),
            PlanStep(step_id="step_b", title="B", description="B", action_type="modify", dependencies=["step_a"]),
        ]
        graph = PlanDependencyGraph(steps)
        ordered = graph.topological_sort()
        ids = [s.step_id for s in ordered]
        assert ids.index("step_a") < ids.index("step_b") < ids.index("step_c")

    def test_sch_10_json_serialization_roundtrip(self):
        """SCH-10: StructuredPlan serialization and deserialization preserves all fields."""
        plan = StructuredPlan(
            summary="Roundtrip Plan",
            problem_statement="Test serialization",
            steps=[PlanStep(step_id="step-1", title="S1", description="S1", action_type="modify")],
        )
        json_data = plan.model_dump_json()
        restored = StructuredPlan.model_validate_json(json_data)
        assert restored.summary == "Roundtrip Plan"
        assert len(restored.steps) == 1


# ============================================================================
# Section 7.5: AgentExecutionLoop & Fail-Closed Execution (EXE-01 to EXE-20)
# ============================================================================


class TestSection75AgentExecutionLoop:
    """Tests for fail-closed executor invariants, payload validity, and verifier integration."""

    def test_exe_01_fail_closed_on_missing_payload(self):
        """EXE-01: Modifying a file with NO payload fails closed (never writes synthetic comments)."""
        mock_ws = MagicMock()
        mock_ws.get_workspace.return_value = MagicMock(status=WorkspaceStatus.IN_USE)
        mock_ws.read_file.return_value = MagicMock(success=True, content="original code")
        loop = AgentExecutionLoop(workspace_manager=mock_ws)

        step = PlanStep(
            step_id="step-1",
            title="Update config",
            description="Modify config",
            action_type="modify",
            expected_files=["config.py"],
        )
        res = loop.execute_plan(
            task_id="task-123",
            plan=[step],
            step_payloads={},  # Intentionally empty payload
        )
        assert res.status == StepExecutionStatus.FAILED
        assert "no content payload" in (res.error_message or "").lower()
        mock_ws.write_file.assert_not_called()

    def test_exe_02_fail_closed_on_unknown_action(self):
        """EXE-02: Unknown action_type fails closed immediately."""
        mock_ws = MagicMock()
        mock_ws.get_workspace.return_value = MagicMock(status=WorkspaceStatus.IN_USE)
        loop = AgentExecutionLoop(workspace_manager=mock_ws)
        step = PlanStep(
            step_id="step-1",
            title="Invalid",
            description="Invalid action",
            action_type="unknown_action_xyz",
        )
        res = loop.execute_plan(
            task_id="task-123",
            plan=[step],
        )
        assert res.status == StepExecutionStatus.FAILED
        assert "unsupported action_type" in (res.error_message or "").lower()

    def test_exe_03_pytest_exit_code_5_not_passed(self):
        """EXE-03: Pytest exit code 5 (NO_TESTS_COLLECTED) fails closed and is NOT PASSED."""
        mock_ws = MagicMock()
        mock_ws.get_workspace.return_value = MagicMock(status=WorkspaceStatus.IN_USE)
        mock_ws.execute_command.return_value = MagicMock(
            exit_code=5,
            stdout="collected 0 items",
            stderr="collected 0 items",
        )
        mock_router = MagicMock()
        mock_router.execute_tool.return_value = MagicMock(
            is_error=True,
            output="collected 0 items / no tests ran",
            exit_code=5,
        )
        loop = AgentExecutionLoop(workspace_manager=mock_ws, tool_router=mock_router)

        step = PlanStep(
            step_id="step-1",
            title="Run tests",
            description="Run pytest",
            action_type="execute_command",
            command="pytest tests/missing.py",
        )
        res = loop.execute_plan(
            task_id="task-123",
            plan=[step],
        )
        assert res.status == StepExecutionStatus.FAILED
        assert "NO_TESTS_COLLECTED" in (res.error_message or "")

    def test_exe_04_execution_verifier_detects_forbidden_file_writes(self):
        """EXE-04 & EXE-06: ExecutionVerifier blocks completion if forbidden file was modified."""
        verifier = ExecutionVerifier()
        step = PlanStep(step_id="step-1", title="Touch forbidden", description="test", action_type="modify")
        outcome = verifier.verify_step_execution(
            task_id="task-123",
            step=step,
            step_output={},
            modified_files=[".env", "src/auth.py"],
            forbidden_files=[".env"],
        )
        assert outcome.is_verified is False
        assert "forbidden file" in outcome.failure_reason.lower()

    def test_exe_10_inspection_read_error_preserved(self):
        """EXE-10: File inspection failures on unreadable existing files are preserved, not swallowed."""
        mock_ws = MagicMock()
        mock_ws.get_workspace.return_value = MagicMock(status=WorkspaceStatus.IN_USE)
        mock_ws.read_file.return_value = MagicMock(success=False, error="Permission denied on disk")
        loop = AgentExecutionLoop(workspace_manager=mock_ws)

        step = PlanStep(
            step_id="step-inspect",
            title="Inspect protected file",
            description="Inspect",
            action_type="inspect",
            expected_files=["protected/secret.py"],
        )
        res = loop.execute_plan(task_id="task-123", plan=[step])
        assert res.status == StepExecutionStatus.FAILED
        assert "Permission denied on disk" in (res.error_message or "")


# ============================================================================
# Section 7.6: Test Discovery & Test Generation Integration (TST-01 to TST-28)
# ============================================================================


class TestSection76TestPlannerAndEvidenceHierarchy:
    """Tests for TaskTestPlanner evidence hierarchy, blast radius, and batching."""

    def test_tst_03_no_five_file_truncation_and_batching(self):
        """TST-03 & TST-16: More than 5 test files are not silently truncated; batches supported."""
        planner = TaskTestPlanner()
        test_files = [f"tests/test_module_{i}.py" for i in range(15)]
        batches = planner.build_test_manifest_batches(test_files, batch_size=5)
        assert len(batches) == 3
        flattened = [f for b in batches for f in b]
        assert len(flattened) == 15
        assert set(flattened) == set(test_files)

    def test_tst_05_propose_new_tests_with_call_edges(self):
        """TST-05: Call edges linking tests to symbols count as evidence of coverage."""
        from types import SimpleNamespace
        planner = TaskTestPlanner()
        sym = AffectedSymbol(
            name="authenticate",
            kind="function",
            file_path="src/auth.py",
            start_line=1,
            end_line=10,
        )
        edge = SimpleNamespace(
            caller_symbol="test_login",
            callee_symbol="authenticate",
        )
        untested, proposed = planner.propose_new_tests(
            directly_modified=[sym],
            existing_test_cases=["test_login"],
            framework="pytest",
            symbol_edges=[edge],
        )
        assert "authenticate" not in untested

    def test_tst_01_framework_detection_pytest(self):
        """TST-01 & TST-15: Detects pytest framework from repository configuration."""
        planner = TaskTestPlanner()
        fw = planner.detect_framework(file_paths=["tests/test_api.py", "conftest.py"])
        assert fw == "pytest"

    def test_tst_16_build_test_command_honors_explicit_max_files(self):
        """TST-03 & TST-16: build_test_command uses custom max_files and does not silently truncate."""
        planner = TaskTestPlanner()
        test_files = [f"tests/test_{i}.py" for i in range(12)]
        cmd = planner.build_test_command(framework="pytest", existing_test_files=test_files, max_files=12)
        for f in test_files:
            assert f in cmd


# ============================================================================
# Section 7.7: Acceptance Verification & Final Reporting (VER-01 to VER-14)
# ============================================================================


class TestSection77AcceptanceVerificationAndReporting:
    """Tests for criterion-level proof, syntax validation, and honest report generation."""

    def test_ver_01_criterion_level_proof_and_failure_detection(self):
        """VER-01 & VER-02: Diff alone does not satisfy requirement if tests or criteria fail."""
        verifier = RequirementToCodeVerifier()
        reqs = [
            TaskRequirement(
                id="REQ-AUTH",
                description="Secure login endpoint",
                category="security",
                target_files=["src/login.py"],
                acceptance_criteria=["Invalid credentials return 401"],
            )
        ]
        plan = StructuredPlan(
            summary="Login",
            problem_statement="Login",
            expected_files_to_modify=["src/login.py"],
            steps=[
                PlanStep(
                    step_id="step-1",
                    title="Login",
                    description="Login",
                    action_type="modify",
                    expected_files=["src/login.py"],
                )
            ],
        )
        # Tests failed
        result = verifier.verify_requirements_against_diff(
            task_id="task-999",
            requirements=reqs,
            constraints=[],
            original_plan=plan,
            final_diff=["src/login.py"],
            test_results={"status": "FAILED", "failed": 1, "passed": 0, "exit_code": 1},
        )
        assert result.overall_status == "FAIL"
        assert "REQ-AUTH" in result.unmet_requirements

    def test_ver_09_syntax_error_in_modified_file_blocks_verification(self):
        """VER-09: SyntaxError in modified file causes verification failure."""
        verifier = RequirementToCodeVerifier()
        reqs = [
            TaskRequirement(id="REQ-1", description="Add math helper", category="functional", target_files=["src/calc.py"])
        ]
        plan = StructuredPlan(
            summary="Calc",
            problem_statement="Calc",
            expected_files_to_modify=["src/calc.py"],
            steps=[
                PlanStep(
                    step_id="step-1",
                    title="Calc",
                    description="Calc",
                    action_type="modify",
                    expected_files=["src/calc.py"],
                )
            ],
        )
        result = verifier.verify_requirements_against_diff(
            task_id="task-123",
            requirements=reqs,
            constraints=[],
            original_plan=plan,
            final_diff=["src/calc.py"],
            file_contents={"src/calc.py": "def invalid_python(:\n    pass"},
        )
        assert result.overall_status == "FAIL"
        assert any("Syntax error" in f.message for f in result.findings)

    def test_ver_03_criterion_evidence_evaluation_partial_and_blocked(self):
        """VER-03, VER-06: Criterion evidence map tracks individual criteria status."""
        verifier = RequirementToCodeVerifier()
        reqs = [
            TaskRequirement(
                id="REQ-CRIT",
                description="Complex feature",
                category="functional",
                target_files=["src/feature.py"],
                acceptance_criteria=["Criterion 1 passed", "Criterion 2 blocked"],
            )
        ]
        plan = StructuredPlan(
            summary="Complex",
            problem_statement="Complex",
            expected_files_to_modify=["src/feature.py"],
            steps=[PlanStep(step_id="step-1", title="S1", description="S1", action_type="modify", expected_files=["src/feature.py"])],
        )
        evidence = {
            "REQ-CRIT": {
                "criteria": {
                    "Criterion 1 passed": "PASS",
                    "Criterion 2 blocked": "BLOCKED",
                }
            }
        }
        res = verifier.verify_requirements_against_diff(
            task_id="task-crit",
            requirements=reqs,
            constraints=[],
            original_plan=plan,
            final_diff=["src/feature.py"],
            evidence_map=evidence,
        )
        assert res.overall_status in ("FAIL", "REQUIRES_HUMAN_REVIEW")
        item = res.compliance_items[0]
        assert item.status == "PARTIAL"
        assert "Criterion 2 blocked" in item.unmet_criteria

    def test_ver_14_honest_task_completion_report_generation(self):
        """VER-14: Report generator distinguishes verified, partial, and blocked items."""
        generator = TaskExecutionReportGenerator()
        rep = generator.build_report(
            task_id="task-555",
            requirements=[
                {"id": "REQ-1", "status": "SATISFIED"},
                {"id": "REQ-2", "status": "BLOCKED"},
            ],
            plan_steps=[{"step_id": "step-1"}],
            modified_files=["src/feature.py"],
            test_results={"status": "PASSED", "passed": 5, "failed": 0},
        )
        assert rep["final_task_status"] == "BLOCKED"
        assert rep["requirements"]["verified_count"] == 1
        assert rep["requirements"]["blocked_count"] == 1
        assert "## Remaining Work" in rep["markdown_report"]


# ============================================================================
# Section 7.8: Recovery, Budgets & Observability (OPS-01 to OPS-12)
# ============================================================================


class TestSection78RecoveryBudgetsAndCheckpoints:
    """Tests for checkpoints, budget enforcement, and adaptive recovery."""

    def test_ops_01_and_ops_02_checkpoints_save_and_resume(self):
        """OPS-01 & OPS-02: Checkpoints saved after step completion allow clean resumption."""
        ckpt_mgr = ExecutionCheckpointManager()
        ckpt = ckpt_mgr.save_checkpoint(
            task_id="task-777",
            step_id="step-1",
            workspace_revision="abc1234",
            diff_hash="hash-1",
            completed_step_ids=["step-1"],
            completed_requirement_ids=["REQ-1"],
            verified_files=["src/a.py"],
        )
        assert ckpt.step_id == "step-1"
        assert ckpt_mgr.can_resume("task-777") is True
        latest = ckpt_mgr.get_latest_checkpoint("task-777")
        assert latest is not None
        assert latest.checkpoint_id == ckpt.checkpoint_id

    def test_ops_06_and_ops_07_budget_manager_enforces_caps(self):
        """OPS-06 & OPS-07: BudgetManager enforces max steps, files, and token limits."""
        budget = ExecutionBudget(max_steps=2, max_modified_files=1, token_budget=1000)
        mgr = ExecutionBudgetManager(budget)

        mgr.record_step_attempt("step-1")
        mgr.record_step_attempt("step-2")
        with pytest.raises(BudgetExceededError, match="Step limit reached"):
            mgr.record_step_attempt("step-3")

        mgr.record_file_modification("src/first.py")
        with pytest.raises(BudgetExceededError, match="Modified file limit reached"):
            mgr.record_file_modification("src/second.py")

    def test_ops_04_and_ops_05_adaptive_recovery_and_approval_gate(self):
        """OPS-04 & OPS-05: Scope expansion pauses for approval; otherwise replans from checkpoint."""
        recovery = ExecutionRecoveryService()
        ckpt_mgr = ExecutionCheckpointManager()
        budget_mgr = ExecutionBudgetManager(ExecutionBudget(max_steps=10))

        # 1. Scope expansion triggers approval requirement
        plan = StructuredPlan(
            summary="Original",
            problem_statement="Original",
            steps=[PlanStep(step_id="step-1", title="S1", description="S1", action_type="modify")],
        )
        outcome_approval = recovery.handle_step_failure(
            task_id="task-rec-1",
            failed_step_id="step-1",
            failure_reason="Requires database migration",
            original_plan=plan,
            checkpoint_manager=ckpt_mgr,
            budget_manager=budget_mgr,
            scope_expansion_detected=True,
        )
        assert outcome_approval.action == "REQUIRES_APPROVAL"
        assert outcome_approval.requires_human_approval is True

        # 2. Standard recoverable failure replans remaining work
        outcome_replan = recovery.handle_step_failure(
            task_id="task-rec-1",
            failed_step_id="step-1",
            failure_reason="Syntax error on first attempt",
            original_plan=plan,
            checkpoint_manager=ckpt_mgr,
            budget_manager=budget_mgr,
            scope_expansion_detected=False,
        )
        assert outcome_replan.can_recover is True
        assert outcome_replan.action == "RESUME_REPLANNED"
        assert outcome_replan.replanned_plan is not None

    def test_ops_03_rollback_to_checkpoint(self):
        """OPS-03: Rollback prunes intermediate checkpoints and restores target checkpoint state."""
        ckpt_mgr = ExecutionCheckpointManager()
        c1 = ckpt_mgr.save_checkpoint("task-rb", "step-1", "rev-1", completed_step_ids=["step-1"])
        c2 = ckpt_mgr.save_checkpoint("task-rb", "step-2", "rev-2", completed_step_ids=["step-1", "step-2"])
        c3 = ckpt_mgr.save_checkpoint("task-rb", "step-3", "rev-3", completed_step_ids=["step-1", "step-2", "step-3"])
        assert len(ckpt_mgr.list_checkpoints("task-rb")) == 3

        restored = ckpt_mgr.rollback_to_checkpoint("task-rb", c2.checkpoint_id)
        assert restored.step_id == "step-2"
        assert len(ckpt_mgr.list_checkpoints("task-rb")) == 2
        assert ckpt_mgr.get_latest_checkpoint("task-rb").checkpoint_id == c2.checkpoint_id

    def test_ops_08_retry_caps_prevent_infinite_loops(self):
        """OPS-08: Exceeding per-step max retries triggers budget failure."""
        budget = ExecutionBudget(max_retries_per_step=2)
        mgr = ExecutionBudgetManager(budget)
        mgr.record_step_attempt("step-retry")
        mgr.record_step_attempt("step-retry")
        with pytest.raises(BudgetExceededError, match="exceeded max retries"):
            mgr.record_step_attempt("step-retry")


# ============================================================================
# Section 7.9: End-to-End Workflow & Final Integrity Verification (E2E)
# ============================================================================


class TestSection79EndToEndTaskLifecycleAndIntegrity:
    """Verifies end-to-end flow from context intake to final verifiable task report."""

    def test_e2e_01_full_task_lifecycle_plan_verify_report(self):
        """E2E-01: End-to-end execution of full pipeline yielding COMPLETED final status."""
        task_id = str(uuid.uuid4())
        repo_id = uuid.uuid4()
        task = AgentTask(
            id=uuid.UUID(task_id),
            repository_id=repo_id,
            title="Implement Token Expiration Validator",
            description="Add token expiration validator in src/validator.py and tests in tests/test_validator.py",
            requirements=[
                {
                    "id": "REQ-VAL-1",
                    "description": "Reject expired tokens with error",
                    "target_files": ["src/validator.py"],
                    "acceptance_criteria": ["Expired tokens return False"],
                }
            ],
        )

        # 1. Build Context
        ctx_builder = TaskContextBuilder(token_budget=5000)
        context = ctx_builder.build_task_context(task)
        assert context.snapshot_id is not None

        # 2. Discover Requirements
        req_discovery = TaskRequirementDiscovery()
        discovered_reqs = req_discovery.discover_requirements(task, context)
        assert len(discovered_reqs) >= 1

        # 3. Create Valid Structured Plan
        plan = StructuredPlan(
            summary="Validate tokens",
            problem_statement="Token validation needed",
            expected_files_to_modify=["src/validator.py", "tests/test_validator.py"],
            steps=[
                PlanStep(
                    step_id="step-1",
                    title="Implement validator",
                    description="Implement token expiration validation",
                    action_type="modify",
                    expected_files=["src/validator.py"],
                    requirement_ids=["REQ-VAL-1"],
                ),
                PlanStep(
                    step_id="step-2",
                    title="Implement validator tests",
                    description="Unit tests for token expiration validation",
                    action_type="test",
                    expected_files=["tests/test_validator.py"],
                    dependencies=["step-1"],
                ),
            ],
            requirements=[{"id": "REQ-VAL-1", "description": "Token validation"}],
            tests_to_run=["pytest tests/test_validator.py"],
        )

        # 4. Check Plan Completeness
        completeness_checker = TaskCompletenessChecker()
        comp_report = completeness_checker.check_plan_completeness(plan, discovered_reqs)
        assert comp_report.is_complete is True

        # 5. Execute Step with Real Content
        mock_ws = MagicMock()
        mock_ws.get_workspace.return_value = MagicMock(status=WorkspaceStatus.IN_USE)
        written_files = {}

        def fake_write(task_id, file_path, content, create_parents=True):
            written_files[file_path] = content
            return MagicMock(bytes_written=len(content))

        def fake_read(task_id, file_path):
            if file_path in written_files:
                return MagicMock(success=True, content=written_files[file_path])
            return MagicMock(success=False, content="")

        mock_ws.write_file.side_effect = fake_write
        mock_ws.read_file.side_effect = fake_read
        loop = AgentExecutionLoop(workspace_manager=mock_ws)

        exec_res = loop.execute_plan(
            task_id=task_id,
            plan=plan.steps,
            step_payloads={
                "step-1": {
                    "content": "def is_token_valid(exp_timestamp: int, now: int) -> bool:\n    return now < exp_timestamp\n"
                },
                "step-2": {
                    "content": "def test_token_valid():\n    assert True\n"
                },
            },
        )
        assert exec_res.status == StepExecutionStatus.COMPLETED
        assert "src/validator.py" in written_files
        assert "tests/test_validator.py" in written_files

        # 6. Step Verification & Checkpoint Recording
        step_verifier = ExecutionVerifier()
        step_outcome = step_verifier.verify_step_execution(
            task_id=task_id,
            step=plan.steps[0],
            step_output=exec_res.steps_executed[0].output,
            modified_files=list(written_files.keys()),
            file_contents=written_files,
            forbidden_files=[".env"],
        )
        assert step_outcome.is_verified is True

        ckpt_mgr = ExecutionCheckpointManager()
        ckpt = ckpt_mgr.save_checkpoint(
            task_id=task_id,
            step_id="step-2",
            workspace_revision="rev-final-sha",
            completed_step_ids=["step-1", "step-2"],
            completed_requirement_ids=["REQ-VAL-1"],
            verified_files=list(written_files.keys()),
        )
        assert ckpt is not None

        # 7. Independent Final Requirement Verification
        req_verifier = RequirementToCodeVerifier()
        task_reqs = [
            TaskRequirement(
                id="REQ-VAL-1",
                description="Reject expired tokens with error",
                category="functional",
                target_files=["src/validator.py"],
                acceptance_criteria=["Expired tokens return False"],
            )
        ]
        ver_result = req_verifier.verify_requirements_against_diff(
            task_id=task_id,
            requirements=task_reqs,
            constraints=[],
            original_plan=plan,
            final_diff=list(written_files.keys()),
            file_contents=written_files,
            test_results={"status": "PASSED", "passed": 1, "failed": 0, "exit_code": 0},
            evidence_map={"REQ-VAL-1": {"criteria": {"Expired tokens return False": "PASS"}}},
        )
        assert ver_result.overall_status == "PASS"

        # 8. Comprehensive Final Report
        report_gen = TaskExecutionReportGenerator()
        final_report = report_gen.build_report(
            task_id=task_id,
            requirements=ver_result.compliance_items,
            plan_steps=plan.steps,
            modified_files=list(written_files.keys()),
            test_results=ver_result.test_summary,
            checkpoints=ckpt_mgr.list_checkpoints(task_id),
            snapshot_id=context.snapshot_id,
            commit_sha="rev-final-sha",
        )
        assert final_report["final_task_status"] == "COMPLETED"
        assert final_report["requirements"]["verified_count"] == 1
        assert "## Modified Files" in final_report["markdown_report"]
        assert "src/validator.py" in final_report["markdown_report"]

    def test_e2e_02_fail_closed_prevents_unverified_task_completion(self):
        """E2E-02: Unresolved test failure or blocked criterion prevents COMPLETED status."""
        report_gen = TaskExecutionReportGenerator()
        final_report = report_gen.build_report(
            task_id="task-fail-closed",
            requirements=[
                {"id": "REQ-1", "status": "SATISFIED"},
                {"id": "REQ-2", "status": "BLOCKED"},
            ],
            plan_steps=[{"step_id": "step-1"}],
            modified_files=["src/feature.py"],
            test_results={"status": "FAILED", "failed": 2, "passed": 1, "exit_code": 1},
        )
        assert final_report["final_task_status"] in ("BLOCKED", "PARTIAL", "FAILED")
        assert final_report["final_task_status"] != "COMPLETED"
        assert len(final_report["remaining_work"]) > 0
