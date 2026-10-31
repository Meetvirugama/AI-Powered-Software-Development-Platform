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
from scanner.symbol_blast_radius import SymbolBlastRadiusEngine
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


# ═══════════════════════════════════════════════════════════════════════════
# 1. Diff Range to AST Symbol Matching Tests
# ═══════════════════════════════════════════════════════════════════════════

class TestDiffRangeSymbolMatching:
    """Tests for SymbolBlastRadiusEngine.map_diff_ranges_to_symbols."""

    def test_single_hunk_exact_match(self):
        engine = SymbolBlastRadiusEngine()
        file_id = uuid4()
        sym_login = _make_symbol("login", "function", file_id=file_id, start_line=10, end_line=25)
        sym_logout = _make_symbol("logout", "function", file_id=file_id, start_line=30, end_line=45)

        symbols_by_file = {"src/auth.py": [sym_login, sym_logout]}
        diff = [
            FileDiffRange(
                file_path="src/auth.py",
                diff_ranges=[LineRange(start_line=12, end_line=15)],
            )
        ]

        matched = engine.map_diff_ranges_to_symbols(diff, symbols_by_file)
        assert len(matched) == 1
        assert matched[0].name == "login"
        assert matched[0].id == sym_login.id

    def test_multi_hunk_matching_multiple_symbols(self):
        engine = SymbolBlastRadiusEngine()
        file_id = uuid4()
        sym1 = _make_symbol("func_one", "function", file_id=file_id, start_line=5, end_line=15)
        sym2 = _make_symbol("func_two", "function", file_id=file_id, start_line=25, end_line=35)
        sym3 = _make_symbol("func_three", "function", file_id=file_id, start_line=50, end_line=60)

        symbols_by_file = {"src/app.py": [sym1, sym2, sym3]}
        diff = [
            FileDiffRange(
                file_path="src/app.py",
                diff_ranges=[
                    LineRange(start_line=10, end_line=12),
                    LineRange(start_line=55, end_line=58),
                ],
            )
        ]

        matched = engine.map_diff_ranges_to_symbols(diff, symbols_by_file)
        assert len(matched) == 2
        matched_names = {s.name for s in matched}
        assert matched_names == {"func_one", "func_three"}

    def test_class_and_method_nested_matching(self):
        engine = SymbolBlastRadiusEngine()
        file_id = uuid4()
        cls_sym = _make_symbol("TokenManager", "class", file_id=file_id, start_line=1, end_line=50)
        method_sym = _make_symbol(
            "verify", "method", file_id=file_id, start_line=20, end_line=35, parent_id=cls_sym.id
        )

        symbols_by_file = {"src/tokens.py": [cls_sym, method_sym]}
        # Hunk covers only the method lines
        diff = [
            FileDiffRange(
                file_path="src/tokens.py",
                diff_ranges=[LineRange(start_line=22, end_line=24)],
            )
        ]

        matched = engine.map_diff_ranges_to_symbols(diff, symbols_by_file)
        matched_names = {s.name for s in matched}
        assert "verify" in matched_names
        assert "TokenManager" in matched_names

    def test_empty_diff_or_non_overlapping_returns_empty(self):
        engine = SymbolBlastRadiusEngine()
        sym = _make_symbol("helper", start_line=10, end_line=20)
        symbols_by_file = {"src/utils.py": [sym]}

        # Non-overlapping range
        diff = [
            FileDiffRange(
                file_path="src/utils.py",
                diff_ranges=[LineRange(start_line=50, end_line=60)],
            )
        ]
        assert engine.map_diff_ranges_to_symbols(diff, symbols_by_file) == []

        # Empty diff
        assert engine.map_diff_ranges_to_symbols([], symbols_by_file) == []

    def test_accepts_raw_tuple_mappings(self):
        engine = SymbolBlastRadiusEngine()
        sym = _make_symbol("process", start_line=10, end_line=30)
        symbols_by_file = {"src/worker.py": [sym]}

        raw_diff = {"src/worker.py": [(15, 20)]}
        matched = engine.map_diff_ranges_to_symbols(raw_diff, symbols_by_file)
        assert len(matched) == 1
        assert matched[0].name == "process"


# ═══════════════════════════════════════════════════════════════════════════
# 2. Dependency Graph Traversal & Blast Radius Tests
# ═══════════════════════════════════════════════════════════════════════════

class TestDependencyGraphTraversal:
    """Tests for compute_symbol_blast_radius graph traversal."""

    def test_isolated_symbol_zero_callers(self):
        engine = SymbolBlastRadiusEngine()
        f_id = uuid4()
        sym = _make_symbol("standalone_func", file_id=f_id)
        file_paths = {f_id: "src/calc.py"}

        direct, trans, affected_files = engine.compute_symbol_blast_radius(
            direct_symbols=[sym],
            symbol_edges=[],
            all_symbols_by_id={sym.id: sym},
            file_paths=file_paths,
        )

        assert len(direct) == 1
        assert direct[0].name == "standalone_func"
        assert direct[0].depth == 0
        assert direct[0].is_direct_target is True
        assert len(trans) == 0
        assert affected_files == ["src/calc.py"]

    def test_direct_callers_traversal_depth_one(self):
        engine = SymbolBlastRadiusEngine()
        f_target = uuid4()
        f_caller1 = uuid4()
        f_caller2 = uuid4()

        target = _make_symbol("hash_password", file_id=f_target)
        caller1 = _make_symbol("register_user", file_id=f_caller1)
        caller2 = _make_symbol("reset_password", file_id=f_caller2)

        edges = [
            _make_edge(caller1, target, "calls"),
            _make_edge(caller2, target, "calls"),
        ]

        all_syms = {s.id: s for s in [target, caller1, caller2]}
        file_paths = {
            f_target: "src/auth/hash.py",
            f_caller1: "src/services/register.py",
            f_caller2: "src/services/reset.py",
        }

        direct, trans, affected_files = engine.compute_symbol_blast_radius(
            direct_symbols=[target],
            symbol_edges=edges,
            all_symbols_by_id=all_syms,
            file_paths=file_paths,
            max_depth=2,
        )

        assert len(direct) == 1
        assert direct[0].callers_count == 2
        assert len(trans) == 2

        trans_names = {t.name for t in trans}
        assert trans_names == {"register_user", "reset_password"}
        assert all(t.depth == 1 for t in trans)
        assert all(t.impact_type == "caller" for t in trans)
        assert len(affected_files) == 3

    def test_transitive_multi_hop_chain(self):
        # Chain: Controller -> Service -> Repository (target)
        engine = SymbolBlastRadiusEngine()
        f_repo, f_srv, f_ctrl = uuid4(), uuid4(), uuid4()

        repo = _make_symbol("get_user_by_id", file_id=f_repo)
        srv = _make_symbol("authenticate_user", file_id=f_srv)
        ctrl = _make_symbol("login_endpoint", file_id=f_ctrl)

        edges = [
            _make_edge(srv, repo, "calls"),
            _make_edge(ctrl, srv, "calls"),
        ]

        all_syms = {s.id: s for s in [repo, srv, ctrl]}
        file_paths = {
            f_repo: "src/repo.py",
            f_srv: "src/service.py",
            f_ctrl: "src/controller.py",
        }

        direct, trans, files = engine.compute_symbol_blast_radius(
            direct_symbols=[repo],
            symbol_edges=edges,
            all_symbols_by_id=all_syms,
            file_paths=file_paths,
            max_depth=3,
        )

        assert len(direct) == 1
        assert len(trans) == 2
        # srv at depth 1, ctrl at depth 2
        depths = {t.name: t.depth for t in trans}
        assert depths["authenticate_user"] == 1
        assert depths["login_endpoint"] == 2
        assert set(files) == {"src/controller.py", "src/repo.py", "src/service.py"}

    def test_depth_limit_truncation(self):
        # Chain: A -> B -> C -> D (target) with max_depth=1
        engine = SymbolBlastRadiusEngine(max_depth=1)
        f = uuid4()
        d = _make_symbol("D", file_id=f)
        c = _make_symbol("C", file_id=f)
        b = _make_symbol("B", file_id=f)

        edges = [
            _make_edge(c, d, "calls"),
            _make_edge(b, c, "calls"),
        ]

        all_syms = {s.id: s for s in [d, c, b]}
        file_paths = {f: "src/chain.py"}

        direct, trans, _ = engine.compute_symbol_blast_radius(
            direct_symbols=[d],
            symbol_edges=edges,
            all_symbols_by_id=all_syms,
            file_paths=file_paths,
            max_depth=1,
        )

        assert len(direct) == 1
        assert len(trans) == 1
        assert trans[0].name == "C"  # B is pruned by max_depth=1

    def test_subclass_inheritance_edge_classification(self):
        engine = SymbolBlastRadiusEngine()
        f = uuid4()
        base_cls = _make_symbol("BaseValidator", "class", file_id=f)
        child_cls = _make_symbol("StrictValidator", "class", file_id=f)

        edge = _make_edge(child_cls, base_cls, "extends")
        all_syms = {base_cls.id: base_cls, child_cls.id: child_cls}
        file_paths = {f: "src/validators.py"}

        direct, trans, _ = engine.compute_symbol_blast_radius(
            direct_symbols=[base_cls],
            symbol_edges=[edge],
            all_symbols_by_id=all_syms,
            file_paths=file_paths,
        )

        assert len(trans) == 1
        assert trans[0].name == "StrictValidator"
        assert trans[0].impact_type == "subclass"


# ═══════════════════════════════════════════════════════════════════════════
# 3. Cycle & Recursion Safety Tests
# ═══════════════════════════════════════════════════════════════════════════

class TestCycleAndRecursionSafety:
    """Tests ensuring graph traversal terminates safely on circular dependencies."""

    def test_mutual_recursion_cycle_does_not_loop_infinitely(self):
        # A calls B, and B calls A
        engine = SymbolBlastRadiusEngine(max_depth=5)
        f = uuid4()
        sym_a = _make_symbol("func_a", file_id=f)
        sym_b = _make_symbol("func_b", file_id=f)

        edges = [
            _make_edge(sym_b, sym_a, "calls"),
            _make_edge(sym_a, sym_b, "calls"),
        ]

        all_syms = {sym_a.id: sym_a, sym_b.id: sym_b}
        file_paths = {f: "src/mutual.py"}

        direct, trans, files = engine.compute_symbol_blast_radius(
            direct_symbols=[sym_a],
            symbol_edges=edges,
            all_symbols_by_id=all_syms,
            file_paths=file_paths,
            max_depth=5,
        )

        # sym_a is in direct; sym_b visited once in transitive; no infinite loop!
        assert len(direct) == 1
        assert len(trans) == 1
        assert trans[0].name == "func_b"
        assert files == ["src/mutual.py"]

    def test_self_recursive_symbol(self):
        # A calls A
        engine = SymbolBlastRadiusEngine()
        f = uuid4()
        sym = _make_symbol("factorial", file_id=f)
        edges = [_make_edge(sym, sym, "calls")]

        direct, trans, _ = engine.compute_symbol_blast_radius(
            direct_symbols=[sym],
            symbol_edges=edges,
            all_symbols_by_id={sym.id: sym},
            file_paths={f: "src/math.py"},
        )

        assert len(direct) == 1
        assert len(trans) == 0  # Does not duplicate self into transitive


# ═══════════════════════════════════════════════════════════════════════════
# 4. Risk Assessment Scoring Tests
# ═══════════════════════════════════════════════════════════════════════════

class TestRiskAssessmentScoring:
    """Tests for deterministic quantitative & qualitative risk scoring."""

    def test_low_risk_isolated_change(self):
        engine = SymbolBlastRadiusEngine()
        direct = [
            AffectedSymbol(
                name="format_date",
                kind="function",
                file_path="src/utils.py",
                start_line=1,
                end_line=10,
                is_direct_target=True,
                callers_count=0,
            )
        ]

        risk = engine.evaluate_risk(direct, [], ["src/utils.py"], [])
        assert risk.risk_level == RiskLevel.LOW
        assert risk.score < 0.30
        assert risk.requires_human_review is False
        assert any("isolated" in r.lower() for r in risk.reasons)

    def test_medium_risk_moderate_callers(self):
        engine = SymbolBlastRadiusEngine()
        direct = [
            AffectedSymbol(
                name="validate_email",
                kind="function",
                file_path="src/validation.py",
                start_line=1,
                end_line=15,
                is_direct_target=True,
                callers_count=3,
            )
        ]
        transitive = [
            AffectedSymbol(
                name="register",
                kind="function",
                file_path="src/auth.py",
                start_line=1,
                end_line=20,
                depth=1,
            )
        ]

        risk = engine.evaluate_risk(direct, transitive, ["src/validation.py", "src/auth.py"], [])
        assert risk.risk_level == RiskLevel.MEDIUM
        assert 0.30 <= risk.score < 0.55

    def test_high_risk_many_callers_and_files(self):
        engine = SymbolBlastRadiusEngine()
        direct = [
            AffectedSymbol(
                name="get_db_session",
                kind="function",
                file_path="src/db.py",
                start_line=1,
                end_line=20,
                is_direct_target=True,
                callers_count=6,
            )
        ]

        risk = engine.evaluate_risk(
            direct,
            [],
            ["src/db.py", "src/users.py", "src/orders.py"],
            [],
        )
        assert risk.risk_level == RiskLevel.HIGH
        assert risk.score >= 0.55
        assert risk.requires_human_review is True

    def test_critical_risk_subclass_impact_and_fanin(self):
        engine = SymbolBlastRadiusEngine()
        direct = [
            AffectedSymbol(
                name="BaseModel",
                kind="class",
                file_path="src/models/base.py",
                start_line=1,
                end_line=50,
                is_direct_target=True,
                callers_count=12,
            )
        ]
        subclasses = [
            AffectedSymbol(
                name=f"Model_{i}",
                kind="class",
                file_path=f"src/models/m{i}.py",
                start_line=1,
                end_line=20,
                impact_type="subclass",
                depth=1,
            )
            for i in range(4)
        ]

        affected_files = ["src/models/base.py"] + [f"src/models/m{i}.py" for i in range(4)]
        risk = engine.evaluate_risk(direct, subclasses, affected_files, [])

        assert risk.risk_level == RiskLevel.CRITICAL
        assert risk.score >= 0.80
        assert risk.requires_human_review is True
        assert any("subclass" in r.lower() for r in risk.reasons)


# ═══════════════════════════════════════════════════════════════════════════
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
        engine = SymbolBlastRadiusEngine()
        planner = TaskTestPlanner()

        f_id = uuid4()
        sym = _make_symbol("login", "function", file_id=f_id, start_line=10, end_line=25)
        file_paths = {f_id: "src/auth.py"}

        direct, trans, affected_files = engine.compute_symbol_blast_radius(
            direct_symbols=[sym],
            symbol_edges=[],
            all_symbols_by_id={sym.id: sym},
            file_paths=file_paths,
        )

        risk = engine.evaluate_risk(direct, trans, affected_files, [])
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
# 8. Real-World Multi-Language Fixture Resolution Tests
# ═══════════════════════════════════════════════════════════════════════════

class TestMultiLanguageFixtureResolution:
    """Tests symbol-level blast radius and test discovery against real repository fixtures."""

    def test_python_sample_fixture_symbol_resolution(self):
        from scanner.extractor import SymbolExtractor
        from scanner.parser import Parser
        from scanner.symbols import FileInfo

        fixture_file = Path(__file__).parent / "fixtures" / "ast_sample" / "supported_python.py"
        if not fixture_file.exists():
            pytest.skip("Fixture not found")

        content = fixture_file.read_text(encoding="utf-8")
        file_id = uuid4()
        f_info = FileInfo(path=str(fixture_file), language="Python", size_bytes=len(content), is_binary=False)
        extractor = SymbolExtractor()
        symbols = extractor.extract(f_info, content, file_id=file_id)
        assert len(symbols) >= 3

        symbols_by_file = {"src/supported_python.py": symbols}
        engine = SymbolBlastRadiusEngine()

        # Target calculate_tax function lines in the fixture
        tax_sym = next((s for s in symbols if "tax" in s.name.lower() or "calc" in s.name.lower()), symbols[0])
        diff = [
            FileDiffRange(
                file_path="src/supported_python.py",
                diff_ranges=[LineRange(start_line=tax_sym.start_line, end_line=tax_sym.end_line)],
            )
        ]

        matched = engine.map_diff_ranges_to_symbols(diff, symbols_by_file)
        assert len(matched) >= 1
        assert any(s.name == tax_sym.name for s in matched)

    def test_typescript_sample_fixture_symbol_resolution(self):
        from scanner.extractor import SymbolExtractor
        from scanner.symbols import FileInfo

        fixture_file = Path(__file__).parent / "fixtures" / "ast_sample" / "supported_typescript.ts"
        if not fixture_file.exists():
            pytest.skip("Fixture not found")

        content = fixture_file.read_text(encoding="utf-8")
        file_id = uuid4()
        f_info = FileInfo(path=str(fixture_file), language="TypeScript", size_bytes=len(content), is_binary=False)

        extractor = SymbolExtractor()
        symbols = extractor.extract(f_info, content, file_id=file_id)
        assert len(symbols) >= 2



        symbols_by_file = {"src/supported_typescript.ts": symbols}
        engine = SymbolBlastRadiusEngine()

        # Match first symbol range
        target_sym = symbols[0]
        diff = [
            FileDiffRange(
                file_path="src/supported_typescript.ts",
                diff_ranges=[LineRange(start_line=target_sym.start_line, end_line=target_sym.start_line + 1)],
            )
        ]

        matched = engine.map_diff_ranges_to_symbols(diff, symbols_by_file)
        assert len(matched) >= 1
        assert matched[0].name == target_sym.name



# ═══════════════════════════════════════════════════════════════════════════
# 9. Edge Cases & Robustness Handling Tests
# ═══════════════════════════════════════════════════════════════════════════

class TestEdgeCasesAndFailureHandling:
    """Tests ensuring zero-crash behavior on anomalous or malformed inputs."""

    def test_missing_symbol_in_edges_does_not_crash(self):
        engine = SymbolBlastRadiusEngine()
        sym = _make_symbol("lone_function")
        # Edge references a non-existent UUID in all_symbols_by_id
        orphan_edge = SymbolEdge(source_id=uuid4(), target_id=sym.id, edge_type="calls")

        direct, trans, _ = engine.compute_symbol_blast_radius(
            direct_symbols=[sym],
            symbol_edges=[orphan_edge],
            all_symbols_by_id={sym.id: sym},
            file_paths={sym.file_id: "src/orphan.py"},
        )

        assert len(direct) == 1
        assert len(trans) == 0  # Orphan caller safely ignored without crashing

    def test_task_diff_ranges_empty_files_list(self):
        engine = SymbolBlastRadiusEngine()
        empty_diff = TaskDiffRanges(task_id=uuid4(), files=[])

        direct, trans, files, risk = engine.analyze_task_diff_ranges(
            task_diff=empty_diff,
            symbols_by_file={},
            symbol_edges=[],
            all_symbols_by_id={},
            file_paths={},
        )

        assert direct == []
        assert trans == []
        assert files == []
        assert risk.risk_level == RiskLevel.LOW

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

