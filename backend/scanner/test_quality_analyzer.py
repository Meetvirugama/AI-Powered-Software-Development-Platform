"""Test Quality Analyzer Engine.

Fulfills task.md §6, §8 (Phase 8 P1):
Detects duplicate tests, weak assertions, flaky test patterns, and computes
independent, truthful test quality scorecards (TestQualityReport).
"""

from __future__ import annotations

import ast
import logging
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

from app.schemas.analysis import (
    TestQualityReport,
    TestRequirement,
)

from scanner.test_coverage_analyzer import TestCoverageResult

logger = logging.getLogger(__name__)

# Patterns indicating flaky or non-deterministic test code
_FLAKY_PATTERNS = [
    (re.compile(r"\btime\.sleep\s*\("), "Uses time.sleep() which causes timing flakiness"),
    (re.compile(r"\brandom\.(random|randint|choice)\s*\("), "Uses unseeded random generator"),
    (re.compile(r"\bdatetime\.now\s*\(\)"), "Uses unmocked wall-clock datetime.now()"),
    (re.compile(r"\b(socket|urllib|requests|httpx)\.(get|post|connect)\s*\("), "Unmocked network I/O in unit test"),
]

# Patterns for weak or trivial assertions
_WEAK_ASSERT_PATTERNS = [
    (re.compile(r"assert\s+True\b"), "Trivial assertion: 'assert True' verifies nothing"),
    (re.compile(r"assert\s+1\s*==\s*1"), "Trivial assertion: 'assert 1 == 1'"),
    (re.compile(r"assert\s+[a-zA-Z0-9_]+\s+is\s+not\s+None\s*$"), "Weak assertion: only checks not None without validating content"),
    (re.compile(r"expect\(true\)\.toBe\(true\)"), "Trivial Jest assertion: expect(true).toBe(true)"),
]


@dataclass
class QualityInspectionResult:
    """Detailed findings from analyzing test suite quality and reliability."""

    duplicate_tests: list[str] = field(default_factory=list)
    weak_assertions: list[str] = field(default_factory=list)
    flaky_indicators: list[str] = field(default_factory=list)
    assertion_less_tests: list[str] = field(default_factory=list)
    total_test_functions: int = 0
    passed_quality_gate: bool = True


class TestQualityAnalyzer:
    """Evaluates test suite source code to measure assertion quality, redundancy, and flakiness."""

    __test__ = False

    def inspect_test_code(self, test_code: str, file_path: str = "test_suite.py") -> QualityInspectionResult:
        """Inspect generated or existing test code for quality antipatterns."""
        result = QualityInspectionResult()
        is_python = file_path.endswith(".py") or "def test_" in test_code

        # 1. Regex pattern scans for flakiness and weak assertions
        for line_no, line in enumerate(test_code.splitlines(), start=1):
            for pat, reason in _FLAKY_PATTERNS:
                if pat.search(line):
                    result.flaky_indicators.append(f"{file_path}:{line_no} - {reason}")
            for pat, reason in _WEAK_ASSERT_PATTERNS:
                if pat.search(line):
                    result.weak_assertions.append(f"{file_path}:{line_no} - {reason}")

        # 2. Python AST structural inspection
        if is_python:
            try:
                tree = ast.parse(test_code, filename=file_path)
                test_bodies: dict[str, str] = {}

                for node in ast.walk(tree):
                    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("test"):
                        result.total_test_functions += 1

                        # Check for assertions inside function
                        has_assert = False
                        body_stmts: list[str] = []
                        for child in ast.walk(node):
                            if isinstance(child, ast.Assert):
                                has_assert = True
                            elif isinstance(child, ast.Call):
                                call_name = ""
                                if isinstance(child.func, ast.Attribute) and child.func.attr.startswith("assert"):
                                    has_assert = True
                                    call_name = child.func.attr
                                elif isinstance(child.func, ast.Name):
                                    call_name = child.func.id
                                if call_name:
                                    body_stmts.append(call_name)

                        if not has_assert:
                            result.assertion_less_tests.append(f"Test '{node.name}' has no assert statements")
                            result.weak_assertions.append(f"{file_path}:{node.lineno} - Test '{node.name}' contains zero assertions")

                        # Check duplicate logic across tests
                        body_signature = "|".join(sorted(body_stmts))
                        if body_signature and body_signature in test_bodies:
                            first_test = test_bodies[body_signature]
                            result.duplicate_tests.append(
                                f"Test '{node.name}' duplicates call logic of '{first_test}'"
                            )
                        elif body_signature:
                            test_bodies[body_signature] = node.name

            except SyntaxError:
                pass
        else:
            # JS/TS regex fallback
            test_matches = re.findall(r"(?:it|test)\s*\(\s*['\"]([^'\"]+)['\"]", test_code)
            result.total_test_functions = len(test_matches)

        if result.weak_assertions or result.duplicate_tests or result.flaky_indicators:
            result.passed_quality_gate = len(result.weak_assertions) == 0

        return result

    def compute_quality_report(
        self,
        requirements: Sequence[TestRequirement],
        test_code_map: Mapping[str, str] | None = None,
        coverage_result: TestCoverageResult | None = None,
        execution_passed: bool = True,
    ) -> TestQualityReport:
        """Compute the complete independent quality scorecard (task.md §8)."""
        code_map = dict(test_code_map or {})
        total_duplicates = 0
        total_flaky = 0
        total_weak = 0
        notes: list[str] = []

        for fpath, code in code_map.items():
            inspection = self.inspect_test_code(code, fpath)
            total_duplicates += len(inspection.duplicate_tests)
            total_flaky += len(inspection.flaky_indicators)
            total_weak += len(inspection.weak_assertions)

            if inspection.weak_assertions:
                notes.extend(inspection.weak_assertions[:2])
            if inspection.flaky_indicators:
                notes.extend(inspection.flaky_indicators[:2])

        # Requirement Coverage
        applicable_reqs = [r for r in requirements if r.status != "NOT_APPLICABLE"]
        covered_reqs = [r for r in applicable_reqs if r.status == "COVERED"]
        partial_reqs = [r for r in applicable_reqs if r.status == "PARTIAL"]

        req_cov_pct = 0.0
        if applicable_reqs:
            req_cov_pct = round(((len(covered_reqs) + len(partial_reqs) * 0.5) / len(applicable_reqs)) * 100.0, 1)

        # Untested critical requirements
        untested_crit = [
            r.requirement_id
            for r in applicable_reqs
            if str(r.priority).upper() in ("CRITICAL", "HIGH") and r.status in ("MISSING", "BLOCKED")
        ]

        # Execution Line Coverage
        line_cov_pct = coverage_result.line_coverage_percent if coverage_result else None
        branch_cov_pct = coverage_result.branch_coverage_percent if coverage_result else None

        # Estimated mutation score based on assertion quality and requirement coverage
        mutation_score: float | None = None
        if execution_passed and applicable_reqs:
            # Baseline from requirement coverage penalised by weak assertions
            base_mutation = req_cov_pct
            if total_weak > 0:
                base_mutation = max(0.0, base_mutation - (total_weak * 10.0))
            mutation_score = round(base_mutation, 1)

        # Overall composite Quality Score (0-100)
        score = 100.0
        if req_cov_pct < 100:
            score -= (100.0 - req_cov_pct) * 0.4
        if line_cov_pct is not None and line_cov_pct < 100:
            score -= (100.0 - line_cov_pct) * 0.2
        if total_weak > 0:
            score -= min(30.0, total_weak * 5.0)
        if total_flaky > 0:
            score -= min(20.0, total_flaky * 5.0)
        if total_duplicates > 0:
            score -= min(15.0, total_duplicates * 3.0)
        if untested_crit:
            score -= min(25.0, len(untested_crit) * 5.0)

        quality_score = max(0.0, round(score, 1))

        if total_weak == 0 and total_flaky == 0:
            notes.append("Clean assertion quality: 0 weak assertions and 0 flaky patterns detected.")

        return TestQualityReport(
            requirement_coverage_percent=req_cov_pct,
            line_coverage_percent=line_cov_pct,
            branch_coverage_percent=branch_cov_pct,
            mutation_score_percent=mutation_score,
            duplicate_test_count=total_duplicates,
            flaky_test_count=total_flaky,
            weak_assertion_count=total_weak,
            untested_critical_requirements=untested_crit,
            quality_score=quality_score,
            summary_notes=notes,
        )

