"""Unit tests for TestIterationOrchestrator (task.md §6).

Verifies:
1. Uncovered context window extraction with line numbers.
2. Stopping condition evaluation (max rounds, 100% coverage, coverage plateau).
3. Python test code merging (AST deduplication of functions and imports).
4. JavaScript/TypeScript test code merging (describe block injection).
5. Scenario deduplication.
"""

from __future__ import annotations

from app.schemas.analysis import TestScenario
from app.services.test_iteration_service import TestIterationOrchestrator


def test_extract_uncovered_context() -> None:
    orchestrator = TestIterationOrchestrator()
    source = """def calculate(x, y):
    if x > 0:
        return x + y
    elif x < 0:
        return x - y
    else:
        return 0
"""
    # Suppose lines 4 and 5 (elif branch) are uncovered
    ctx = orchestrator.extract_uncovered_context(source, uncovered_lines=[4, 5], context_window=1)
    assert ">    4 |     elif x < 0:" in ctx
    assert ">    5 |         return x - y" in ctx
    assert "     3 |         return x + y" in ctx


def test_should_continue_iteration_stopping_conditions() -> None:
    orchestrator = TestIterationOrchestrator(max_rounds=3)

    # 1. Max rounds reached
    cont, reason = orchestrator.should_continue_iteration(
        current_round=3,
        prev_coverage=50.0,
        new_coverage=70.0,
        uncovered_lines=[10, 11],
    )
    assert cont is False
    assert "Maximum generation rounds" in reason

    # 2. 100% coverage / no uncovered lines
    cont, reason = orchestrator.should_continue_iteration(
        current_round=1,
        prev_coverage=70.0,
        new_coverage=100.0,
        uncovered_lines=[],
    )
    assert cont is False
    assert "100% executable line coverage" in reason

    # 3. Coverage plateau
    cont, reason = orchestrator.should_continue_iteration(
        current_round=2,
        prev_coverage=65.0,
        new_coverage=65.0,
        uncovered_lines=[12, 13],
    )
    assert cont is False
    assert "plateaued" in reason

    # 4. Valid improvement opportunity
    cont, reason = orchestrator.should_continue_iteration(
        current_round=1,
        prev_coverage=40.0,
        new_coverage=65.0,
        uncovered_lines=[12, 13],
    )
    assert cont is True


def test_merge_python_tests() -> None:
    orchestrator = TestIterationOrchestrator()

    existing = """import pytest

def test_initial():
    assert 1 == 1
"""
    new_code = """from datetime import datetime

def test_initial():
    assert 1 == 1

def test_new_edge_case():
    assert 2 == 2
"""
    merged = orchestrator.merge_generated_tests(existing, new_code, framework="pytest")
    assert "def test_initial():" in merged
    assert "def test_new_edge_case():" in merged
    # Should not duplicate def test_initial
    assert merged.count("def test_initial():") == 1
    # New import should be added
    assert "from datetime import datetime" in merged


def test_merge_js_tests() -> None:
    orchestrator = TestIterationOrchestrator()

    existing = """import { describe, it, expect } from 'vitest';

describe('Calculator', () => {
    it('adds numbers', () => {
        expect(1 + 1).toBe(2);
    });
});
"""
    new_code = """
    it('adds numbers', () => {
        expect(1 + 1).toBe(2);
    });
    it('handles negative numbers', () => {
        expect(-1 + -1).toBe(-2);
    });
"""
    merged = orchestrator.merge_generated_tests(existing, new_code, framework="vitest")
    assert "it('adds numbers'" in merged
    assert "it('handles negative numbers'" in merged
    assert merged.count("it('adds numbers'") == 1
    assert merged.endswith("});\n")


def test_deduplicate_scenarios() -> None:
    orchestrator = TestIterationOrchestrator()
    s1 = [
        TestScenario(name="Normal addition", category="normal", description="Tests 1+1"),
        TestScenario(name="Zero addition", category="edge_case", description="Tests 0+0"),
    ]
    s2 = [
        TestScenario(name="Normal addition", category="normal", description="Duplicate"),
        TestScenario(name="Negative addition", category="edge_case", description="Tests -1+-1"),
    ]
    deduped = orchestrator.deduplicate_scenarios(s1, s2)
    assert len(deduped) == 3
    assert [s.name for s in deduped] == ["Normal addition", "Zero addition", "Negative addition"]
