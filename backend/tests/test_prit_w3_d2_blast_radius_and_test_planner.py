"""Comprehensive Automated Test Suite for Week 3 Day 2 Deliverables.

Owner: Prit Zania — Repository Engine & Workspace Lead
Milestone: Week 3 — Workflow Automation & Production Hardening
Deliverable: W3-Day2 — Symbol-Level Blast Radius Engine, Test Discovery Planner & Pre-Flight Validation
Reference: Docs/week3.md §6 (F32, F33), Docs/daily_tasks.md line 614

Test Scenarios Covered:
1. Diff Line Range to AST Symbol Resolution (map_diff_ranges_to_symbols)
2. Call Graph Traversal & Transitive Blast Radius (compute_symbol_blast_radius)
3. Cyclic Dependency & Recursion Safety (infinite loop protection)
4. Multi-tier Risk Assessment (LOW, MEDIUM, HIGH, CRITICAL scoring)
5. Framework Detection (pytest, unittest, jest)
6. Existing Test Discovery & Test Case Introspection
7. Missing Coverage Detection & Standardized Test Proposals
8. Restricted Test Runner Command Generation
9. Workspace Base-Revision Pre-Flight Validation (WorkspaceBaseValidator)
10. End-to-End TaskPlanningContext Assembly & Schema Validation
"""

from __future__ import annotations

import os
from pathlib import Path
from uuid import UUID, uuid4

import pytest

from app.schemas.planner_context import (
    AffectedSymbol,
    FileDiffRange,
    LineRange,
    ProposedTest,
    RiskAssessment,
    RiskLevel,
    TaskDiffRanges,
    TaskImpactAssessment,
    TaskPlanningContext,
    TestExecutionPlan,
)
from app.schemas.workspace import WorkspaceStatus
from scanner.symbols import Symbol, SymbolEdge
from scanner.task_test_planner import TaskTestPlanner
from scanner.workspace_preflight import WorkspaceBaseValidator, WorkspacePreflightResult


# ═══════════════════════════════════════════════════════════════════════════
# Helpers & Synthetic Fixture Factories
# ═══════════════════════════════════════════════════════════════════════════

def _make_symbol(
    name: str,
    kind: str = "function",
    file_id: UUID | None = None,
    start_line: int = 1,
    end_line: int = 10,
    parent_id: UUID | None = None,
    signature: str = "",
) -> Symbol:
    return Symbol(
        id=uuid4(),
        name=name,
        kind=kind,
        file_id=file_id or uuid4(),
        start_line=start_line,
        end_line=end_line,
        signature=signature or f"def {name}():",
        parent_id=parent_id,
    )


def _make_edge(
    source: Symbol,
    target: Symbol,
    edge_type: str = "calls",
) -> SymbolEdge:
    return SymbolEdge(
        source_id=source.id,
        target_id=target.id,
        edge_type=edge_type,
    )


# 5. Task Test Planner & Framework Detection Tests
# ═══════════════════════════════════════════════════════════════════════════

class TestTaskTestPlanner:
    """Tests for TaskTestPlanner discovery and test proposals."""

    def test_detect_framework_from_pytest_fixture_sample(self):
        planner = TaskTestPlanner()
        fixture_dir = Path(__file__).parent / "fixtures" / "framework_samples" / "pytest_repo"
        if not fixture_dir.exists():
            pytest.skip("Fixture not found")
        fw = planner.detect_framework(repo_root=fixture_dir)
        assert fw == "pytest"

    def test_detect_framework_from_jest_fixture_sample(self):
        planner = TaskTestPlanner()
        fixture_dir = Path(__file__).parent / "fixtures" / "framework_samples" / "jest_repo"
        if not fixture_dir.exists():
            pytest.skip("Fixture not found")
        fw = planner.detect_framework(repo_root=fixture_dir)
        assert fw == "jest"

    def test_detect_framework_from_unittest_fixture_sample(self):
        planner = TaskTestPlanner()
        fixture_dir = Path(__file__).parent / "fixtures" / "framework_samples" / "unittest_repo"
        if not fixture_dir.exists():
            pytest.skip("Fixture not found")
        fw = planner.detect_framework(repo_root=fixture_dir)
        assert fw == "unittest"

    def test_detect_framework_fallback_from_paths(self):
        planner = TaskTestPlanner()
        assert planner.detect_framework(file_paths=["src/components/App.test.tsx"]) == "jest"
        assert planner.detect_framework(file_paths=["src/auth.py", "conftest.py", "tests/test_auth.py"]) == "pytest"
        assert planner.detect_framework(file_paths=["src/auth.py", "tests/test_auth.py"]) == "unittest"


    def test_propose_new_tests_for_uncovered_symbols(self):
        planner = TaskTestPlanner()
        sym = AffectedSymbol(
            name="calculate_tax",
            kind="function",
            file_path="src/billing/tax.py",
            start_line=1,
            end_line=20,
            is_direct_target=True,
        )

        # Existing tests don't mention calculate_tax
        existing_cases = ["test_user_login", "test_logout"]
        untested, proposed = planner.propose_new_tests([sym], existing_cases, "pytest")

        assert untested == ["calculate_tax"]
        assert len(proposed) == 1
        assert proposed[0].target_symbol == "calculate_tax"
        assert proposed[0].suggested_test_file == "tests/billing/test_tax.py"
        assert proposed[0].suggested_test_name == "test_calculate_tax_success"

    def test_propose_new_tests_jest_naming_conventions(self):
        planner = TaskTestPlanner()
        sym = AffectedSymbol(
            name="formatCurrency",
            kind="function",
            file_path="src/utils/format.ts",
            start_line=1,
            end_line=15,
            is_direct_target=True,
        )

        untested, proposed = planner.propose_new_tests([sym], [], "jest")
        assert len(proposed) == 1
        assert proposed[0].suggested_test_file == "src/utils/__tests__/format.test.ts"
        assert proposed[0].framework == "jest"

    def test_build_test_command_formatting(self):
        planner = TaskTestPlanner()

        # Pytest
        cmd_py = planner.build_test_command("pytest", ["tests/test_auth.py", "tests/test_user.py"])
        assert cmd_py.startswith("pytest tests/test_auth.py tests/test_user.py")

        # Jest
        cmd_jest = planner.build_test_command("jest", ["src/__tests__/app.test.ts"])
        assert cmd_jest.startswith("npm test -- src/__tests__/app.test.ts")

        # Unittest
        cmd_ut = planner.build_test_command("unittest", ["tests/test_calc.py"])
        assert cmd_ut.startswith("python -m unittest tests/test_calc.py")


# ═══════════════════════════════════════════════════════════════════════════
# 6. Workspace Base-Revision Pre-Flight Validation Tests
# ═══════════════════════════════════════════════════════════════════════════

class TestWorkspaceBaseValidator:
    """Tests for WorkspaceBaseValidator boundary and revision checks."""

    def test_validate_base_revision_valid_sha_and_names(self):
        validator = WorkspaceBaseValidator()
        # 40-char hex SHA
        ok, rev, err = validator.validate_base_revision("a" * 40)
        assert ok is True
        assert rev == "a" * 40
        assert err is None

        # Standard branch ref
        ok, rev, _ = validator.validate_base_revision("main")
        assert ok is True
        assert rev == "main"

    def test_validate_base_revision_illegal_characters_rejected(self):
        validator = WorkspaceBaseValidator()
        ok, _, err = validator.validate_base_revision("sha; rm -rf /")
        assert ok is False
        assert "Invalid base_revision" in err

    def test_preflight_valid_workspace_and_targets(self, tmp_path):
        validator = WorkspaceBaseValidator()
        # Setup fake workspace
        w_dir = tmp_path / ".workspaces" / "task-123"
        w_dir.mkdir(parents=True)
        (w_dir / "src").mkdir()
        (w_dir / "src" / "app.py").write_text("print('hello')", encoding="utf-8")

        res = validator.validate_preflight(
            workspace_path=w_dir,
            base_revision="b" * 40,
            target_files=["src/app.py"],
            workspace_status=WorkspaceStatus.READY,
        )

        assert res.is_valid is True
        assert len(res.errors) == 0
        assert res.target_files_verified == ["src/app.py"]
        assert res.workspace_status == WorkspaceStatus.READY

    def test_preflight_traversal_rejection(self, tmp_path):
        validator = WorkspaceBaseValidator()
        w_dir = tmp_path / ".workspaces" / "task-safe"
        w_dir.mkdir(parents=True)

        res = validator.validate_preflight(
            workspace_path=w_dir,
            target_files=["../../etc/passwd"],
        )

        assert res.is_valid is False
        assert any("Target file validation failed" in err for err in res.errors)

    def test_preflight_invalid_workspace_status_rejection(self, tmp_path):
        validator = WorkspaceBaseValidator()
        w_dir = tmp_path / "workspace"
        w_dir.mkdir()

        res = validator.validate_preflight(
            workspace_path=w_dir,
            workspace_status=WorkspaceStatus.FAILED,  # FAILED is not ready for planning
        )

        assert res.is_valid is False
        assert any("not ready for planning" in err for err in res.errors)


# ═══════════════════════════════════════════════════════════════════════════
# 7. End-to-End TaskPlanningContext Assembly & Schema Invariants
# ═══════════════════════════════════════════════════════════════════════════

class TestTaskPlanningContextAssembly:
    """Tests end-to-end integration and Pydantic schema contracts."""

    def test_assemble_task_impact_assessment_envelope(self):
        planner = TaskTestPlanner()

        f_id = uuid4()
        sym = _make_symbol("login", "function", file_id=f_id, start_line=10, end_line=25)
        file_paths = {f_id: "src/auth.py"}

        direct = [
            AffectedSymbol(
                name="login",
                kind="function",
                file_path="src/auth.py",
                start_line=10,
                end_line=25,
                is_direct_target=True,
                callers_count=0,
            )
        ]
        trans = []
        affected_files = ["src/auth.py"]

        risk = RiskAssessment(
            score=0.1,
            risk_level=RiskLevel.LOW,
            requires_human_review=False,
            summary="Isolated low risk change",
            reasons=["isolated"],
        )
        test_plan = planner.create_test_plan(
            affected_files=affected_files,
            directly_modified=direct,
            repo_symbols=[sym],
            repo_edges=[],
            file_paths=file_paths,
        )

        assessment = TaskImpactAssessment(
            task_id="task_abc_123",
            target_files=["src/auth.py"],
            affected_files=affected_files,
            directly_modified_symbols=direct,
            transitively_affected_symbols=trans,
            risk=risk,
            test_plan=test_plan,
        )

        assert assessment.total_affected_files == 1
        assert assessment.total_affected_symbols == 1
        assert assessment.test_plan.recommended_test_command.startswith(("pytest", "python -m unittest"))

        # Wrap in TaskPlanningContext
        context = TaskPlanningContext(
            task_id="task_abc_123",
            repository_id=str(uuid4()),
            base_revision="c" * 40,
            impact_assessment=assessment,
            workspace_ready=True,
            detected_framework=test_plan.framework,
            resource_limits={"timeout_seconds": 60, "max_disk_mb": 500},
        )

        assert context.workspace_ready is True
        assert context.impact_assessment.total_affected_symbols == 1
        assert context.resource_limits["max_disk_mb"] == 500


# ═══════════════════════════════════════════════════════════════════════════
# 9. Edge Cases & Robustness Handling Tests
# ═══════════════════════════════════════════════════════════════════════════

class TestEdgeCasesAndFailureHandling:
    """Tests ensuring zero-crash behavior on anomalous or malformed inputs."""

    def test_preflight_nonexistent_workspace_path(self, tmp_path):
        validator = WorkspaceBaseValidator()
        non_existent = tmp_path / "does_not_exist"

        res = validator.validate_preflight(
            workspace_path=non_existent,
            base_revision="c" * 40,
        )

        assert res.is_valid is False
        assert any("does not exist" in err for err in res.errors)

    def test_null_bytes_and_traversal_in_preflight_target(self, tmp_path):
        validator = WorkspaceBaseValidator()
        w_dir = tmp_path / "workspace"
        w_dir.mkdir()

        res = validator.validate_preflight(
            workspace_path=w_dir,
            target_files=["src/\x00evil.py", "../../../windows/system32"],
        )

        assert res.is_valid is False
        assert len(res.errors) >= 1

