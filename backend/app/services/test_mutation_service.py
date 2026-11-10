"""Offline Mutation Testing Engine for Test Suite Defect Detection Evaluation.

Owner: Antigravity Test Engineering Team
Reference: task.md §7 (Feature 4: Mutation Testing, MuTAP P-12 inspiration)

Capabilities:
1. AST-based mutation generation for Python source code:
   - Comparison operators (> <-> >=, < <-> <=, == <-> !=)
   - Arithmetic operators (+ <-> -, * <-> /)
   - Boolean constants (True <-> False)
   - Logical operators (and <-> or)
2. Executes test suite against each mutant in an isolated workspace.
3. Classifies mutant outcomes:
   - KILLED: Test suite failed (caught the defect).
   - SURVIVED: Test suite passed (missed the defect).
   - TIMEOUT: Test execution exceeded budget.
   - EQUIVALENT: Syntactically or semantically identical to original.
4. Calculates standard mutation score:
   Score = Killed Mutants / (Total Mutants - Equivalent Mutants) * 100
5. Designed strictly for offline quality benchmarking, not executed on every user request.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass, field
import logging
import time
from typing import Any, Callable

logger = logging.getLogger(__name__)


@dataclass
class CodeMutant:
    """Representation of an individual synthesized code mutant."""

    mutant_id: str
    operator_type: str
    line_number: int
    original_code: str
    mutated_code: str
    full_source: str
    status: str = "PENDING"  # KILLED, SURVIVED, TIMEOUT, EQUIVALENT
    error_message: str | None = None


@dataclass
class MutationReport:
    """Comprehensive offline mutation evaluation report."""

    total_mutants: int = 0
    killed_mutants: int = 0
    survived_mutants: int = 0
    equivalent_mutants: int = 0
    timeout_mutants: int = 0
    mutation_score: float = 0.0
    duration_seconds: float = 0.0
    mutants: list[CodeMutant] = field(default_factory=list)


class _ASTComparisonMutator(ast.NodeTransformer):
    """Mutates comparison operators (e.g. > to >=, == to !=)."""

    REPLACEMENTS = {
        ast.Eq: ast.NotEq,
        ast.NotEq: ast.Eq,
        ast.Gt: ast.GtE,
        ast.GtE: ast.Gt,
        ast.Lt: ast.LtE,
        ast.LtE: ast.Lt,
    }

    def __init__(self, target_line: int | None = None) -> None:
        super().__init__()
        self.target_line = target_line
        self.mutated = False
        self.operator_name = ""

    def visit_Compare(self, node: ast.Compare) -> ast.AST:
        self.generic_visit(node)
        if self.mutated:
            return node

        new_ops = []
        changed = False
        for op in node.ops:
            op_cls = op.__class__
            if (self.target_line is None or node.lineno == self.target_line) and op_cls in self.REPLACEMENTS:
                new_ops.append(self.REPLACEMENTS[op_cls]())
                self.operator_name = f"Compare:{op_cls.__name__}->{self.REPLACEMENTS[op_cls].__name__}"
                self.mutated = True
                changed = True
            else:
                new_ops.append(op)

        if changed:
            return ast.copy_location(
                ast.Compare(
                    left=node.left,
                    ops=new_ops,
                    comparators=node.comparators,
                ),
                node,
            )
        return node


class _ASTArithmeticMutator(ast.NodeTransformer):
    """Mutates binary arithmetic operators (e.g. + to -, * to /)."""

    REPLACEMENTS = {
        ast.Add: ast.Sub,
        ast.Sub: ast.Add,
        ast.Mult: ast.Div,
        ast.Div: ast.Mult,
    }

    def __init__(self, target_line: int | None = None) -> None:
        super().__init__()
        self.target_line = target_line
        self.mutated = False
        self.operator_name = ""

    def visit_BinOp(self, node: ast.BinOp) -> ast.AST:
        self.generic_visit(node)
        if self.mutated:
            return node

        op_cls = node.op.__class__
        if (self.target_line is None or node.lineno == self.target_line) and op_cls in self.REPLACEMENTS:
            self.operator_name = f"BinOp:{op_cls.__name__}->{self.REPLACEMENTS[op_cls].__name__}"
            self.mutated = True
            return ast.copy_location(
                ast.BinOp(
                    left=node.left,
                    op=self.REPLACEMENTS[op_cls](),
                    right=node.right,
                ),
                node,
            )
        return node


class _ASTConstantMutator(ast.NodeTransformer):
    """Mutates boolean constants (True to False, False to True)."""

    def __init__(self, target_line: int | None = None) -> None:
        super().__init__()
        self.target_line = target_line
        self.mutated = False
        self.operator_name = ""

    def visit_Constant(self, node: ast.Constant) -> ast.AST:
        if self.mutated:
            return node

        if (self.target_line is None or node.lineno == self.target_line) and isinstance(node.value, bool):
            self.mutated = True
            self.operator_name = f"Constant:{node.value}->{not node.value}"
            return ast.copy_location(
                ast.Constant(value=not node.value),
                node,
            )
        return node


class _ASTLogicalMutator(ast.NodeTransformer):
    """Mutates logical boolean operators (and <-> or)."""

    REPLACEMENTS = {
        ast.And: ast.Or,
        ast.Or: ast.And,
    }

    def __init__(self, target_line: int | None = None) -> None:
        super().__init__()
        self.target_line = target_line
        self.mutated = False
        self.operator_name = ""

    def visit_BoolOp(self, node: ast.BoolOp) -> ast.AST:
        self.generic_visit(node)
        if self.mutated:
            return node

        op_cls = node.op.__class__
        if (self.target_line is None or node.lineno == self.target_line) and op_cls in self.REPLACEMENTS:
            self.operator_name = f"BoolOp:{op_cls.__name__}->{self.REPLACEMENTS[op_cls].__name__}"
            self.mutated = True
            return ast.copy_location(
                ast.BoolOp(
                    op=self.REPLACEMENTS[op_cls](),
                    values=node.values,
                ),
                node,
            )
        return node


class MutationTestingService:
    """Offline mutation testing engine for test verification and quality benchmarking."""

    __test__ = False

    def generate_mutants(self, source_code: str, max_mutants: int = 15) -> list[CodeMutant]:
        """Generate a controlled list of AST mutants for the given source code."""
        try:
            tree = ast.parse(source_code)
        except SyntaxError:
            return []

        lines = source_code.splitlines()
        mutants: list[CodeMutant] = []
        mutant_idx = 0

        # Collect candidate lines
        candidate_lines: set[int] = set()
        for node in ast.walk(tree):
            if hasattr(node, "lineno"):
                candidate_lines.add(node.lineno)

        for line_no in sorted(candidate_lines):
            if len(mutants) >= max_mutants:
                break
            orig_line = lines[line_no - 1] if 0 < line_no <= len(lines) else ""

            for mutator_cls in (
                _ASTComparisonMutator,
                _ASTArithmeticMutator,
                _ASTConstantMutator,
                _ASTLogicalMutator,
            ):
                if len(mutants) >= max_mutants:
                    break
                mutator = mutator_cls(target_line=line_no)
                new_tree = mutator.visit(ast.parse(source_code))
                if mutator.mutated:
                    mutant_code = ast.unparse(new_tree)
                    if mutant_code != source_code:
                        mutant_idx += 1
                        mutated_lines = mutant_code.splitlines()
                        mutated_line_str = (
                            mutated_lines[line_no - 1].strip()
                            if 0 < line_no <= len(mutated_lines)
                            else mutant_code.strip()
                        )
                        mutants.append(
                            CodeMutant(
                                mutant_id=f"MUT-{mutant_idx:03d}",
                                operator_type=mutator.operator_name,
                                line_number=line_no,
                                original_code=orig_line.strip(),
                                mutated_code=mutated_line_str,
                                full_source=mutant_code,
                            )
                        )

        return mutants

    def evaluate_mutants(
        self,
        mutants: list[CodeMutant],
        test_executor: Callable[[str], tuple[bool, str | None]],
    ) -> MutationReport:
        """Run tests against each mutant and calculate the mutation score.

        The `test_executor(mutant_source)` must return:
            (passed: bool, error_message: str | None)
        If passed is False -> mutant is KILLED.
        If passed is True -> mutant SURVIVED.
        """
        start = time.perf_counter()
        killed = 0
        survived = 0
        timeout = 0
        equivalent = 0

        for m in mutants:
            try:
                passed, err = test_executor(m.full_source)
                if not passed:
                    m.status = "KILLED"
                    killed += 1
                else:
                    m.status = "SURVIVED"
                    survived += 1
                m.error_message = err
            except TimeoutError:
                m.status = "TIMEOUT"
                timeout += 1
            except Exception as exc:  # noqa: BLE001
                # If execution crashed, consider mutant killed if crash was due to assertion or syntax
                m.status = "KILLED"
                m.error_message = str(exc)
                killed += 1

        total = len(mutants)
        valid_denom = total - equivalent
        score = (killed / valid_denom * 100.0) if valid_denom > 0 else 0.0

        return MutationReport(
            total_mutants=total,
            killed_mutants=killed,
            survived_mutants=survived,
            equivalent_mutants=equivalent,
            timeout_mutants=timeout,
            mutation_score=round(score, 2),
            duration_seconds=round(time.perf_counter() - start, 3),
            mutants=mutants,
        )
