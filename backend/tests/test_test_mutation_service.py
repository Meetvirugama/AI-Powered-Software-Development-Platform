"""Unit tests for MutationTestingService (task.md §7).

Verifies:
1. AST mutant generation across comparison, arithmetic, and constant operators.
2. Accurate evaluation of mutants (killed vs survived).
3. Mutation score calculation.
4. Handling of timeouts and execution crashes.
"""

from __future__ import annotations

from app.services.test_mutation_service import MutationTestingService


def test_generate_mutants_comparison_and_arithmetic() -> None:
    service = MutationTestingService()
    source = """
def is_valid_age(age: int) -> bool:
    if age >= 18:
        return True
    return False

def calculate_discount(price: float) -> float:
    return price - 10.0
"""
    mutants = service.generate_mutants(source, max_mutants=10)
    assert len(mutants) >= 3

    # Check for comparison mutant (>= -> >)
    comp_muts = [m for m in mutants if "Compare" in m.operator_type]
    assert len(comp_muts) > 0
    assert any("age > 18" in m.full_source for m in comp_muts)

    # Check for arithmetic mutant (- -> +)
    arith_muts = [m for m in mutants if "BinOp" in m.operator_type]
    assert len(arith_muts) > 0
    assert any("price + 10.0" in m.full_source for m in arith_muts)

    # Check for boolean constant mutant (True -> False)
    const_muts = [m for m in mutants if "Constant" in m.operator_type]
    assert len(const_muts) > 0


def test_evaluate_mutants_score_calculation() -> None:
    service = MutationTestingService()
    source = """
def add(a: int, b: int) -> int:
    return a + b
"""
    mutants = service.generate_mutants(source, max_mutants=5)
    assert len(mutants) > 0

    # Executor kills arithmetic mutants (a - b fails assertion), survives others if any
    def mock_executor(mutant_source: str) -> tuple[bool, str | None]:
        if "a - b" in mutant_source:
            return False, "AssertionError: 2 != 0"
        return True, None

    report = service.evaluate_mutants(mutants, mock_executor)
    assert report.total_mutants == len(mutants)
    assert report.killed_mutants >= 1
    assert report.mutation_score > 0.0
    assert report.duration_seconds >= 0.0


def test_evaluate_mutants_all_killed_100_percent() -> None:
    service = MutationTestingService()
    source = """
def is_positive(x: int) -> bool:
    return x > 0
"""
    mutants = service.generate_mutants(source, max_mutants=2)

    def mock_killing_executor(mutant_source: str) -> tuple[bool, str | None]:
        return False, "Failed assertion"

    report = service.evaluate_mutants(mutants, mock_killing_executor)
    assert report.killed_mutants == len(mutants)
    assert report.survived_mutants == 0
    assert report.mutation_score == 100.0


def test_evaluate_mutants_timeout_handling() -> None:
    service = MutationTestingService()
    source = "def foo(x): return x == 1"
    mutants = service.generate_mutants(source, max_mutants=2)

    def mock_timeout_executor(mutant_source: str) -> tuple[bool, str | None]:
        raise TimeoutError("Test execution exceeded 60s")

    report = service.evaluate_mutants(mutants, mock_timeout_executor)
    assert report.timeout_mutants == len(mutants)
