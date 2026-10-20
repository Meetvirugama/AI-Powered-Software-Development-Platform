"""AST-backed rule integration and structural bug analysis engine.

Owner: Prit — Repository Engine Lead (W2-Day3)
Fulfills Week 2 Day 3: AST Rule Integration.
Provides targeted structural checks using source ranges, exact line location preservation,
explicit parser failure reporting, and integration with static review & bug detection pipelines.
"""

from __future__ import annotations

import ast
import logging
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Set, Tuple

from .detector import LanguageDetector
from .parser import Parser
from .source_location import SourceLocationResolver
from .symbols import FileInfo, ParseResult, SourceRange, Symbol
from .target_selector import TargetSelectionResult, TargetSelector

logger = logging.getLogger(__name__)


@dataclass
class ASTBugFinding:
    """A verified structural bug finding detected via AST analysis."""

    rule_id: str
    category: str  # "resource_leak" | "unhandled_exception" | "null_dereference" | "logic_error" | "off_by_one" | "security" | "syntax_error"
    severity: str  # "critical" | "high" | "medium" | "low" | "info"
    message: str
    file_path: str
    line_number: int  # 1-indexed start line
    end_line: int  # 1-indexed end line (inclusive)
    column: int = 1  # 1-indexed column
    end_column: Optional[int] = None
    evidence: str = ""
    remediation: str = ""
    confidence: str = "high"  # "high" | "medium" | "low"
    is_structural: bool = True
    scanner: str = "ast_rules"
    enclosing_symbol: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert finding to standard dictionary representation."""
        return {
            "rule_id": self.rule_id,
            "category": self.category,
            "severity": self.severity,
            "message": self.message,
            "file_path": self.file_path,
            "line_number": self.line_number,
            "end_line": self.end_line,
            "column": self.column,
            "end_column": self.end_column,
            "evidence": self.evidence,
            "remediation": self.remediation,
            "confidence": self.confidence,
            "is_structural": self.is_structural,
            "scanner": self.scanner,
            "enclosing_symbol": self.enclosing_symbol,
            "metadata": self.metadata or {},
        }

    def to_static_finding_dict(self) -> Dict[str, Any]:
        """Convert finding to Devu's StaticFinding dictionary format."""
        meta = dict(self.metadata or {})
        meta.update(
            {
                "end_line": self.end_line,
                "category": self.category,
                "evidence": self.evidence,
                "remediation": self.remediation,
                "confidence": self.confidence,
                "is_structural": self.is_structural,
                "enclosing_symbol": self.enclosing_symbol,
            }
        )
        return {
            "rule_id": self.rule_id,
            "severity": self.severity,
            "message": self.message,
            "file_path": self.file_path,
            "line_number": self.line_number,
            "scanner": self.scanner,
            "metadata": meta,
        }


@dataclass
class ASTRuleAnalysisResult:
    """The aggregate result of running AST rules on a target file or code range."""

    success: bool
    file_path: str
    findings: List[ASTBugFinding] = field(default_factory=list)
    parse_status: str = "OK"  # "OK" | "SYNTAX_WARNING" | "PARSE_ERROR" | "UNSUPPORTED_LANGUAGE"
    has_syntax_errors: bool = False
    error_message: Optional[str] = None
    rules_evaluated: int = 0
    target_range: Optional[SourceRange] = None
    target_symbol: Optional[str] = None
    total_lines: int = 0

    def to_dict(self) -> Dict[str, Any]:
        """Convert result to dictionary representation."""
        return {
            "success": self.success,
            "file_path": self.file_path,
            "findings_count": len(self.findings),
            "findings": [f.to_dict() for f in self.findings],
            "parse_status": self.parse_status,
            "has_syntax_errors": self.has_syntax_errors,
            "error_message": self.error_message,
            "rules_evaluated": self.rules_evaluated,
            "target_range": {
                "start_line": self.target_range.start_line,
                "end_line": self.target_range.end_line,
                "symbol_name": self.target_range.symbol_name,
            }
            if self.target_range
            else None,
            "target_symbol": self.target_symbol,
            "total_lines": self.total_lines,
        }

    def findings_by_severity(self) -> Dict[str, List[ASTBugFinding]]:
        """Group findings by severity level."""
        groups: Dict[str, List[ASTBugFinding]] = {
            "critical": [],
            "high": [],
            "medium": [],
            "low": [],
            "info": [],
        }
        for finding in self.findings:
            sev = finding.severity.lower()
            if sev not in groups:
                groups[sev] = []
            groups[sev].append(finding)
        return groups

    def findings_by_category(self) -> Dict[str, List[ASTBugFinding]]:
        """Group findings by bug category."""
        groups: Dict[str, List[ASTBugFinding]] = {}
        for finding in self.findings:
            cat = finding.category.lower()
            if cat not in groups:
                groups[cat] = []
            groups[cat].append(finding)
        return groups


# ---------------------------------------------------------------------------
# Base AST Rule Definition
# ---------------------------------------------------------------------------


class BaseASTRule:
    """Abstract base class for all structural AST bug detection rules."""

    rule_id: str = "AST-GENERIC"
    name: str = "Generic AST Rule"
    category: str = "logic_error"
    severity: str = "medium"
    description: str = ""
    default_confidence: str = "high"

    def check_python(
        self,
        tree: ast.AST,
        content: str,
        file_path: str,
        lines: List[str],
    ) -> List[ASTBugFinding]:
        """Inspect a Python AST tree and return detected structural findings."""
        return []

    def check_tree_sitter(
        self,
        root_node: Any,
        content: str,
        file_path: str,
        language: str,
        lines: List[str],
    ) -> List[ASTBugFinding]:
        """Inspect a Tree-sitter AST and return detected structural findings."""
        return []

    @staticmethod
    def _extract_line_snippet(lines: Sequence[str], line_idx: int) -> str:
        """Safely extract line text without trailing newlines (1-indexed line)."""
        if 1 <= line_idx <= len(lines):
            return lines[line_idx - 1].strip()
        return ""


# ---------------------------------------------------------------------------
# Concrete Structural Rules
# ---------------------------------------------------------------------------


class UnclosedResourceRule(BaseASTRule):
    """AST-RES-001: Detect unclosed resources allocated without context managers."""

    rule_id = "AST-RES-001"
    name = "Unclosed Resource Leak"
    category = "resource_leak"
    severity = "high"
    description = (
        "File or network resource is allocated without using a 'with' context manager "
        "or deterministic closure in a finally block."
    )
    default_confidence = "high"

    RESOURCE_FACTORIES = {"open", "socket", "create_connection", "connect"}

    def check_python(
        self,
        tree: ast.AST,
        content: str,
        file_path: str,
        lines: List[str],
    ) -> List[ASTBugFinding]:
        findings: List[ASTBugFinding] = []

        # Track assignments inside with-statements to avoid false positives
        with_managed_lines: Set[int] = set()
        for node in ast.walk(tree):
            if isinstance(node, (ast.With, ast.AsyncWith)):
                for item in node.items:
                    with_managed_lines.add(item.context_expr.lineno)

        for node in ast.walk(tree):
            if isinstance(node, ast.Assign):
                if isinstance(node.value, ast.Call):
                    call = node.value
                    func_name = ""
                    if isinstance(call.func, ast.Name):
                        func_name = call.func.id
                    elif isinstance(call.func, ast.Attribute):
                        func_name = call.func.attr

                    if func_name in self.RESOURCE_FACTORIES:
                        if call.lineno not in with_managed_lines:
                            line_no = call.lineno
                            end_line = getattr(node, "end_lineno", line_no)
                            snippet = self._extract_line_snippet(lines, line_no)
                            findings.append(
                                ASTBugFinding(
                                    rule_id=self.rule_id,
                                    category=self.category,
                                    severity=self.severity,
                                    message=(
                                        f"Resource allocated by '{func_name}()' is not managed "
                                        "by a 'with' context manager, risking resource leaks."
                                    ),
                                    file_path=file_path,
                                    line_number=line_no,
                                    end_line=end_line,
                                    column=getattr(call, "col_offset", 0) + 1,
                                    evidence=snippet,
                                    remediation=(
                                        f"Use 'with {snippet}:' or ensure resource is closed "
                                        "within a 'finally' block."
                                    ),
                                    confidence=self.default_confidence,
                                )
                            )

        return findings


class SwallowedExceptionRule(BaseASTRule):
    """AST-EXC-001: Detect swallowed exceptions or bare except blocks with pass."""

    rule_id = "AST-EXC-001"
    name = "Swallowed Exception"
    category = "unhandled_exception"
    severity = "medium"
    description = (
        "An exception handler catches an exception and silences it using pass/empty body "
        "without logging or re-raising, concealing defects."
    )
    default_confidence = "high"

    def check_python(
        self,
        tree: ast.AST,
        content: str,
        file_path: str,
        lines: List[str],
    ) -> List[ASTBugFinding]:
        findings: List[ASTBugFinding] = []

        for node in ast.walk(tree):
            if isinstance(node, ast.ExceptHandler):
                line_no = node.lineno
                end_line = getattr(node, "end_lineno", line_no)
                snippet = self._extract_line_snippet(lines, line_no)

                is_bare = node.type is None
                is_broad = False
                if isinstance(node.type, ast.Name) and node.type.id in (
                    "Exception",
                    "BaseException",
                ):
                    is_broad = True

                # Check if body is just pass, ellipsis, or docstring
                is_empty_or_pass = False
                if len(node.body) == 1:
                    stmt = node.body[0]
                    if isinstance(stmt, ast.Pass):
                        is_empty_or_pass = True
                    elif isinstance(stmt, ast.Expr) and isinstance(
                        stmt.value, ast.Constant
                    ):
                        is_empty_or_pass = True

                if is_bare and is_empty_or_pass:
                    findings.append(
                        ASTBugFinding(
                            rule_id=self.rule_id,
                            category=self.category,
                            severity="high",
                            message=(
                                "Bare 'except:' block silences all exceptions with 'pass', "
                                "preventing diagnosis of system errors."
                            ),
                            file_path=file_path,
                            line_number=line_no,
                            end_line=end_line,
                            column=getattr(node, "col_offset", 0) + 1,
                            evidence=snippet,
                            remediation=(
                                "Specify explicit exception classes and log the failure or re-raise."
                            ),
                            confidence="high",
                        )
                    )
                elif is_broad and is_empty_or_pass:
                    findings.append(
                        ASTBugFinding(
                            rule_id=self.rule_id,
                            category=self.category,
                            severity=self.severity,
                            message=(
                                f"Exception handler for '{ast.unparse(node.type)}' silences error with 'pass'."
                            ),
                            file_path=file_path,
                            line_number=line_no,
                            end_line=end_line,
                            column=getattr(node, "col_offset", 0) + 1,
                            evidence=snippet,
                            remediation=(
                                "Log the captured exception or re-raise to preserve debugging trace."
                            ),
                            confidence=self.default_confidence,
                        )
                    )

        return findings

    def check_tree_sitter(
        self,
        root_node: Any,
        content: str,
        file_path: str,
        language: str,
        lines: List[str],
    ) -> List[ASTBugFinding]:
        findings: List[ASTBugFinding] = []
        if language in ("javascript", "typescript", "JavaScript", "TypeScript"):
            # Look for catch_clause with empty compound_statement
            def traverse(node: Any):
                if node.type == "catch_clause":
                    body = node.child_by_field_name("body")
                    if body and body.type == "statement_block":
                        # Named children check: if 0 named children, it's empty
                        if body.named_child_count == 0:
                            start_line = node.start_point[0] + 1
                            end_line = node.end_point[0] + 1
                            snippet = self._extract_line_snippet(lines, start_line)
                            findings.append(
                                ASTBugFinding(
                                    rule_id=self.rule_id,
                                    category=self.category,
                                    severity=self.severity,
                                    message="Empty catch block silences errors without handling or logging.",
                                    file_path=file_path,
                                    line_number=start_line,
                                    end_line=end_line,
                                    column=node.start_point[1] + 1,
                                    evidence=snippet,
                                    remediation="Log or handle the caught error instead of discarding it.",
                                    confidence="high",
                                )
                            )
                for child in node.children:
                    traverse(child)

            traverse(root_node)

        return findings


class MutableDefaultArgumentRule(BaseASTRule):
    """AST-ARG-001: Detect mutable default values in function definitions."""

    rule_id = "AST-ARG-001"
    name = "Mutable Default Argument"
    category = "logic_error"
    severity = "medium"
    description = (
        "Default parameter value is a mutable structure (list, dict, set), "
        "causing unintended shared state across calls."
    )
    default_confidence = "high"

    def check_python(
        self,
        tree: ast.AST,
        content: str,
        file_path: str,
        lines: List[str],
    ) -> List[ASTBugFinding]:
        findings: List[ASTBugFinding] = []

        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                defaults = node.args.defaults + [
                    d for d in node.args.kw_defaults if d is not None
                ]
                for default_val in defaults:
                    if isinstance(default_val, (ast.List, ast.Dict, ast.Set)):
                        line_no = default_val.lineno
                        end_line = getattr(default_val, "end_lineno", line_no)
                        snippet = self._extract_line_snippet(lines, line_no)
                        val_str = ast.unparse(default_val)
                        findings.append(
                            ASTBugFinding(
                                rule_id=self.rule_id,
                                category=self.category,
                                severity=self.severity,
                                message=(
                                    f"Function '{node.name}' uses mutable default argument '{val_str}', "
                                    "which retains state across repeated invocations."
                                ),
                                file_path=file_path,
                                line_number=line_no,
                                end_line=end_line,
                                column=getattr(default_val, "col_offset", 0) + 1,
                                evidence=snippet,
                                remediation=(
                                    "Use None as default value and initialize with empty collection inside function body."
                                ),
                                confidence=self.default_confidence,
                            )
                        )

        return findings


class NullDereferenceComparisonRule(BaseASTRule):
    """AST-NULL-001: Detect dangerous null/None comparisons or immediate dereferences."""

    rule_id = "AST-NULL-001"
    name = "Null Safety / Comparison Defect"
    category = "null_dereference"
    severity = "medium"
    description = (
        "Equality comparison against None (use 'is None') or dereferencing an object "
        "inside an 'if x is None' block."
    )
    default_confidence = "high"

    def check_python(
        self,
        tree: ast.AST,
        content: str,
        file_path: str,
        lines: List[str],
    ) -> List[ASTBugFinding]:
        findings: List[ASTBugFinding] = []

        for node in ast.walk(tree):
            # 1. Comparison with == None or != None
            if isinstance(node, ast.Compare):
                for op, comp in zip(node.ops, node.comparators):
                    if isinstance(op, (ast.Eq, ast.NotEq)) and isinstance(
                        comp, ast.Constant
                    ) and comp.value is None:
                        line_no = node.lineno
                        end_line = getattr(node, "end_lineno", line_no)
                        snippet = self._extract_line_snippet(lines, line_no)
                        op_str = "==" if isinstance(op, ast.Eq) else "!="
                        rec_op = "is None" if isinstance(op, ast.Eq) else "is not None"
                        findings.append(
                            ASTBugFinding(
                                rule_id=self.rule_id,
                                category=self.category,
                                severity="low",
                                message=(
                                    f"Comparison with '{op_str} None' violates PEP 8 and may trigger "
                                    f"custom __eq__ traps. Use '{rec_op}' instead."
                                ),
                                file_path=file_path,
                                line_number=line_no,
                                end_line=end_line,
                                column=getattr(node, "col_offset", 0) + 1,
                                evidence=snippet,
                                remediation=f"Change comparison to use '{rec_op}'.",
                                confidence="high",
                            )
                        )

            # 2. Dereferencing attribute inside `if x is None:` block
            if isinstance(node, ast.If):
                test = node.test
                null_var_name = None
                if isinstance(test, ast.Compare):
                    if (
                        len(test.ops) == 1
                        and isinstance(test.ops[0], ast.Is)
                        and isinstance(test.comparators[0], ast.Constant)
                        and test.comparators[0].value is None
                        and isinstance(test.left, ast.Name)
                    ):
                        null_var_name = test.left.id

                if null_var_name:
                    for stmt in node.body:
                        for subnode in ast.walk(stmt):
                            if (
                                isinstance(subnode, ast.Attribute)
                                and isinstance(subnode.value, ast.Name)
                                and subnode.value.id == null_var_name
                            ):
                                line_no = subnode.lineno
                                end_line = getattr(subnode, "end_lineno", line_no)
                                snippet = self._extract_line_snippet(lines, line_no)
                                findings.append(
                                    ASTBugFinding(
                                        rule_id=self.rule_id,
                                        category=self.category,
                                        severity="critical",
                                        message=(
                                            f"Variable '{null_var_name}' is confirmed None, but its attribute "
                                            f"'{subnode.attr}' is dereferenced inside the None-check block."
                                        ),
                                        file_path=file_path,
                                        line_number=line_no,
                                        end_line=end_line,
                                        column=getattr(subnode, "col_offset", 0) + 1,
                                        evidence=snippet,
                                        remediation=(
                                            f"Check 'if {null_var_name} is not None:' before accessing attributes."
                                        ),
                                        confidence="high",
                                    )
                                )

        return findings


class IterationMutationRule(BaseASTRule):
    """AST-ITER-001: Detect collection mutation during iteration."""

    rule_id = "AST-ITER-001"
    name = "Collection Mutation During Iteration"
    category = "off_by_one"
    severity = "high"
    description = (
        "Mutating a collection (remove/append/pop/del) while iterating over it, "
        "causing skipped elements or index corruption."
    )
    default_confidence = "high"

    MUTATING_METHODS = {"remove", "pop", "append", "extend", "insert", "clear"}

    def check_python(
        self,
        tree: ast.AST,
        content: str,
        file_path: str,
        lines: List[str],
    ) -> List[ASTBugFinding]:
        findings: List[ASTBugFinding] = []

        for node in ast.walk(tree):
            if isinstance(node, (ast.For, ast.AsyncFor)):
                iter_var_name = None
                if isinstance(node.iter, ast.Name):
                    iter_var_name = node.iter.id

                if iter_var_name:
                    for stmt in node.body:
                        for subnode in ast.walk(stmt):
                            # Method call: items.remove(...)
                            if (
                                isinstance(subnode, ast.Call)
                                and isinstance(subnode.func, ast.Attribute)
                                and isinstance(subnode.func.value, ast.Name)
                                and subnode.func.value.id == iter_var_name
                                and subnode.func.attr in self.MUTATING_METHODS
                            ):
                                line_no = subnode.lineno
                                end_line = getattr(subnode, "end_lineno", line_no)
                                snippet = self._extract_line_snippet(lines, line_no)
                                findings.append(
                                    ASTBugFinding(
                                        rule_id=self.rule_id,
                                        category=self.category,
                                        severity=self.severity,
                                        message=(
                                            f"Collection '{iter_var_name}' is mutated via '.{subnode.func.attr}()' "
                                            "while being actively iterated over, causing skipped elements or erratic loop bounds."
                                        ),
                                        file_path=file_path,
                                        line_number=line_no,
                                        end_line=end_line,
                                        column=getattr(subnode, "col_offset", 0) + 1,
                                        evidence=snippet,
                                        remediation=(
                                            f"Iterate over a copy using 'for item in list({iter_var_name}):' or use a list comprehension."
                                        ),
                                        confidence=self.default_confidence,
                                    )
                                )

                            # Delete statement: del items[idx]
                            elif isinstance(subnode, ast.Delete):
                                for target in subnode.targets:
                                    if (
                                        isinstance(target, ast.Subscript)
                                        and isinstance(target.value, ast.Name)
                                        and target.value.id == iter_var_name
                                    ):
                                        line_no = subnode.lineno
                                        end_line = getattr(subnode, "end_lineno", line_no)
                                        snippet = self._extract_line_snippet(lines, line_no)
                                        findings.append(
                                            ASTBugFinding(
                                                rule_id=self.rule_id,
                                                category=self.category,
                                                severity=self.severity,
                                                message=(
                                                    f"Collection '{iter_var_name}' element is deleted while iterating over it."
                                                ),
                                                file_path=file_path,
                                                line_number=line_no,
                                                end_line=end_line,
                                                column=getattr(subnode, "col_offset", 0) + 1,
                                                evidence=snippet,
                                                remediation=(
                                                    f"Iterate over a copy using 'list({iter_var_name})' before deleting elements."
                                                ),
                                                confidence=self.default_confidence,
                                            )
                                        )

        return findings


class IdenticalBranchesRule(BaseASTRule):
    """AST-LOGIC-001: Detect identical if-else bodies or duplicate condition checks."""

    rule_id = "AST-LOGIC-001"
    name = "Identical Branches or Duplicate Condition"
    category = "logic_error"
    severity = "medium"
    description = (
        "An if statement contains identical execution branches or duplicated condition tests, "
        "indicating dead logic or copy-paste errors."
    )
    default_confidence = "high"

    def check_python(
        self,
        tree: ast.AST,
        content: str,
        file_path: str,
        lines: List[str],
    ) -> List[ASTBugFinding]:
        findings: List[ASTBugFinding] = []

        for node in ast.walk(tree):
            if isinstance(node, ast.If):
                # 1. Compare if-body and else-body (if else exists and is not an elif)
                if node.orelse and not (
                    len(node.orelse) == 1 and isinstance(node.orelse[0], ast.If)
                ):
                    try:
                        body_dump = ast.dump(ast.Module(body=node.body, type_ignores=[]))
                        orelse_dump = ast.dump(ast.Module(body=node.orelse, type_ignores=[]))
                        if body_dump == orelse_dump:
                            line_no = node.lineno
                            end_line = getattr(node, "end_lineno", line_no)
                            snippet = self._extract_line_snippet(lines, line_no)
                            findings.append(
                                ASTBugFinding(
                                    rule_id=self.rule_id,
                                    category=self.category,
                                    severity=self.severity,
                                    message=(
                                        "The 'if' and 'else' branches execute identical code, "
                                        "making the condition redundant."
                                    ),
                                    file_path=file_path,
                                    line_number=line_no,
                                    end_line=end_line,
                                    column=getattr(node, "col_offset", 0) + 1,
                                    evidence=snippet,
                                    remediation=(
                                        "Differentiate branch logic or remove redundant conditional check."
                                    ),
                                    confidence=self.default_confidence,
                                )
                            )
                    except Exception:
                        pass

                # 2. Check duplicate conditions in if-elif chain
                conditions: List[Tuple[str, int, int]] = []
                current: Optional[ast.If] = node
                while current:
                    try:
                        cond_str = ast.unparse(current.test)
                        conditions.append((cond_str, current.test.lineno, getattr(current.test, "end_lineno", current.test.lineno)))
                    except Exception:
                        pass
                    if len(current.orelse) == 1 and isinstance(current.orelse[0], ast.If):
                        current = current.orelse[0]
                    else:
                        break

                seen_conditions: Set[str] = set()
                for cond_str, cond_line, cond_end in conditions:
                    if cond_str in seen_conditions:
                        snippet = self._extract_line_snippet(lines, cond_line)
                        findings.append(
                            ASTBugFinding(
                                rule_id=self.rule_id,
                                category=self.category,
                                severity="high",
                                message=(
                                    f"Condition '{cond_str}' is duplicated in the if-elif chain; "
                                    "the second branch will never execute."
                                ),
                                file_path=file_path,
                                line_number=cond_line,
                                end_line=cond_end,
                                column=1,
                                evidence=snippet,
                                remediation="Remove duplicate elif condition or replace with intended condition.",
                                confidence="high",
                            )
                        )
                    seen_conditions.add(cond_str)

        return findings


class DeadCodeRule(BaseASTRule):
    """AST-DEAD-001: Detect unreachable statements following terminal statements."""

    rule_id = "AST-DEAD-001"
    name = "Unreachable Code After Return"
    category = "logic_error"
    severity = "low"
    description = (
        "Statements immediately follow an unconditional return, raise, break, or continue, "
        "making them unreachable."
    )
    default_confidence = "high"

    TERMINAL_TYPES = (ast.Return, ast.Raise, ast.Break, ast.Continue)

    def check_python(
        self,
        tree: ast.AST,
        content: str,
        file_path: str,
        lines: List[str],
    ) -> List[ASTBugFinding]:
        findings: List[ASTBugFinding] = []

        def check_block(body: List[ast.stmt]):
            terminal_found = False
            for stmt in body:
                if terminal_found:
                    line_no = stmt.lineno
                    end_line = getattr(stmt, "end_lineno", line_no)
                    snippet = self._extract_line_snippet(lines, line_no)
                    findings.append(
                        ASTBugFinding(
                            rule_id=self.rule_id,
                            category=self.category,
                            severity=self.severity,
                            message=(
                                f"Statement '{snippet}' is unreachable because it follows a terminal "
                                "control statement (return/raise/break/continue)."
                            ),
                            file_path=file_path,
                            line_number=line_no,
                            end_line=end_line,
                            column=getattr(stmt, "col_offset", 0) + 1,
                            evidence=snippet,
                            remediation="Remove or relocate unreachable statements.",
                            confidence=self.default_confidence,
                        )
                    )
                    break
                if isinstance(stmt, self.TERMINAL_TYPES):
                    terminal_found = True

        for node in ast.walk(tree):
            for field_name, value in ast.iter_fields(node):
                if isinstance(value, list) and value and isinstance(value[0], ast.stmt):
                    check_block(value)

        return findings


class DynamicExecutionRule(BaseASTRule):
    """AST-SEC-001: Detect dynamic code execution via eval/exec."""

    rule_id = "AST-SEC-001"
    name = "Dangerous Dynamic Code Execution"
    category = "security"
    severity = "critical"
    description = (
        "Execution of untrusted strings via eval(), exec(), or __import__() risks "
        "arbitrary code execution."
    )
    default_confidence = "high"

    DANGEROUS_CALLS = {"eval", "exec", "__import__"}

    def check_python(
        self,
        tree: ast.AST,
        content: str,
        file_path: str,
        lines: List[str],
    ) -> List[ASTBugFinding]:
        findings: List[ASTBugFinding] = []

        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                func_name = ""
                if isinstance(node.func, ast.Name):
                    func_name = node.func.id
                if func_name in self.DANGEROUS_CALLS:
                    line_no = node.lineno
                    end_line = getattr(node, "end_lineno", line_no)
                    snippet = self._extract_line_snippet(lines, line_no)
                    findings.append(
                        ASTBugFinding(
                            rule_id=self.rule_id,
                            category=self.category,
                            severity=self.severity,
                            message=(
                                f"Use of dynamic execution function '{func_name}()' introduces severe "
                                "remote code execution vulnerabilities."
                            ),
                            file_path=file_path,
                            line_number=line_no,
                            end_line=end_line,
                            column=getattr(node, "col_offset", 0) + 1,
                            evidence=snippet,
                            remediation=(
                                "Replace eval/exec with safe alternatives such as ast.literal_eval() "
                                "or structured parsers."
                            ),
                            confidence="high",
                        )
                    )

        return findings

    def check_tree_sitter(
        self,
        root_node: Any,
        content: str,
        file_path: str,
        language: str,
        lines: List[str],
    ) -> List[ASTBugFinding]:
        findings: List[ASTBugFinding] = []
        if language in ("javascript", "typescript", "JavaScript", "TypeScript"):
            def traverse(node: Any):
                if node.type == "call_expression":
                    func_node = node.child_by_field_name("function")
                    if func_node and func_node.type == "identifier":
                        func_text = content[func_node.start_byte : func_node.end_byte]
                        if func_text == "eval":
                            start_line = node.start_point[0] + 1
                            end_line = node.end_point[0] + 1
                            snippet = self._extract_line_snippet(lines, start_line)
                            findings.append(
                                ASTBugFinding(
                                    rule_id=self.rule_id,
                                    category=self.category,
                                    severity=self.severity,
                                    message="Direct use of 'eval()' allows arbitrary script execution.",
                                    file_path=file_path,
                                    line_number=start_line,
                                    end_line=end_line,
                                    column=node.start_point[1] + 1,
                                    evidence=snippet,
                                    remediation="Replace 'eval()' with JSON.parse() or specific validation logic.",
                                    confidence="high",
                                )
                            )
                for child in node.children:
                    traverse(child)

            traverse(root_node)

        return findings


class SelfComparisonAssignmentRule(BaseASTRule):
    """AST-LOGIC-002: Detect self-comparison and self-assignment."""

    rule_id = "AST-LOGIC-002"
    name = "Self Comparison or Self Assignment"
    category = "logic_error"
    severity = "medium"
    description = (
        "Comparing an identifier to itself (x == x) or assigning a variable to itself (x = x) "
        "indicates typos or dead logic."
    )
    default_confidence = "high"

    def check_python(
        self,
        tree: ast.AST,
        content: str,
        file_path: str,
        lines: List[str],
    ) -> List[ASTBugFinding]:
        findings: List[ASTBugFinding] = []

        for node in ast.walk(tree):
            # Self assignment: x = x
            if isinstance(node, ast.Assign) and len(node.targets) == 1:
                target = node.targets[0]
                if isinstance(target, ast.Name) and isinstance(node.value, ast.Name):
                    if target.id == node.value.id:
                        line_no = node.lineno
                        end_line = getattr(node, "end_lineno", line_no)
                        snippet = self._extract_line_snippet(lines, line_no)
                        findings.append(
                            ASTBugFinding(
                                rule_id=self.rule_id,
                                category=self.category,
                                severity="low",
                                message=f"Redundant self-assignment '{target.id} = {target.id}'.",
                                file_path=file_path,
                                line_number=line_no,
                                end_line=end_line,
                                column=getattr(node, "col_offset", 0) + 1,
                                evidence=snippet,
                                remediation="Remove redundant self-assignment.",
                                confidence="high",
                            )
                        )

            # Self comparison: x == x
            elif isinstance(node, ast.Compare):
                if isinstance(node.left, ast.Name) and len(node.comparators) == 1:
                    comp = node.comparators[0]
                    if isinstance(comp, ast.Name) and node.left.id == comp.id:
                        line_no = node.lineno
                        end_line = getattr(node, "end_lineno", line_no)
                        snippet = self._extract_line_snippet(lines, line_no)
                        findings.append(
                            ASTBugFinding(
                                rule_id=self.rule_id,
                                category=self.category,
                                severity=self.severity,
                                message=(
                                    f"Tautological comparison '{node.left.id} == {comp.id}' always evaluates to True."
                                ),
                                file_path=file_path,
                                line_number=line_no,
                                end_line=end_line,
                                column=getattr(node, "col_offset", 0) + 1,
                                evidence=snippet,
                                remediation="Verify comparator variable name.",
                                confidence="high",
                            )
                        )

        return findings


class OffByOneIndexingRule(BaseASTRule):
    """AST-BOUND-001: Detect off-by-one boundary index patterns."""

    rule_id = "AST-BOUND-001"
    name = "Off-by-One Array Indexing"
    category = "off_by_one"
    severity = "high"
    description = (
        "Indexing a sequence directly with its exact length (e.g. items[len(items)]) "
        "causes guaranteed IndexError."
    )
    default_confidence = "high"

    def check_python(
        self,
        tree: ast.AST,
        content: str,
        file_path: str,
        lines: List[str],
    ) -> List[ASTBugFinding]:
        findings: List[ASTBugFinding] = []

        for node in ast.walk(tree):
            if isinstance(node, ast.Subscript):
                slice_node = node.slice
                # items[len(items)]
                if isinstance(slice_node, ast.Call):
                    if isinstance(slice_node.func, ast.Name) and slice_node.func.id == "len":
                        if len(slice_node.args) == 1 and isinstance(slice_node.args[0], ast.Name):
                            len_arg_name = slice_node.args[0].id
                            if isinstance(node.value, ast.Name) and node.value.id == len_arg_name:
                                line_no = node.lineno
                                end_line = getattr(node, "end_lineno", line_no)
                                snippet = self._extract_line_snippet(lines, line_no)
                                findings.append(
                                    ASTBugFinding(
                                        rule_id=self.rule_id,
                                        category=self.category,
                                        severity=self.severity,
                                        message=(
                                            f"Attempting to index '{len_arg_name}[len({len_arg_name})]' triggers IndexError "
                                            "because Python indices are 0-based."
                                        ),
                                        file_path=file_path,
                                        line_number=line_no,
                                        end_line=end_line,
                                        column=getattr(node, "col_offset", 0) + 1,
                                        evidence=snippet,
                                        remediation=f"Use '{len_arg_name}[-1]' to access the last element safely.",
                                        confidence="high",
                                    )
                                )

        return findings


# ---------------------------------------------------------------------------
# Default Rule Registry
# ---------------------------------------------------------------------------

DEFAULT_RULES: List[BaseASTRule] = [
    UnclosedResourceRule(),
    SwallowedExceptionRule(),
    MutableDefaultArgumentRule(),
    NullDereferenceComparisonRule(),
    IterationMutationRule(),
    IdenticalBranchesRule(),
    DeadCodeRule(),
    DynamicExecutionRule(),
    SelfComparisonAssignmentRule(),
    OffByOneIndexingRule(),
]


# ---------------------------------------------------------------------------
# ASTBugAnalyzer: Main Engine
# ---------------------------------------------------------------------------


class ASTBugAnalyzer:
    """AST-backed bug analysis engine integrating structural rule checks,

    exact line location mapping, targeted source ranges, and parser failure handling.
    """

    def __init__(
        self,
        parser: Optional[Parser] = None,
        rules: Optional[Sequence[BaseASTRule]] = None,
        target_selector: Optional[TargetSelector] = None,
        source_resolver: Optional[SourceLocationResolver] = None,
        detector: Optional[LanguageDetector] = None,
    ):
        self.parser = parser or Parser()
        self.rules: List[BaseASTRule] = list(rules or DEFAULT_RULES)
        self.target_selector = target_selector or TargetSelector(parser=self.parser)
        self.source_resolver = source_resolver or SourceLocationResolver(parser=self.parser)
        self.detector = detector or LanguageDetector()

    def register_rule(self, rule: BaseASTRule) -> None:
        """Register a new custom AST rule into the analysis engine."""
        self.rules.append(rule)

    def analyze_code(
        self,
        content: str,
        file_path: str = "",
        target_range: Optional[SourceRange] = None,
        target_symbol: Optional[str] = None,
        language: Optional[str] = None,
    ) -> ASTRuleAnalysisResult:
        """Analyze source code string against all registered AST rules.

        Supports target range restriction, symbol scoping, and explicit error handling.
        """
        if not content:
            return ASTRuleAnalysisResult(
                success=True,
                file_path=file_path,
                findings=[],
                parse_status="OK",
                total_lines=0,
            )

        lines = content.splitlines()
        total_lines = len(lines)

        file_info = FileInfo(
            path=file_path or "sample.py",
            size_bytes=len(content.encode("utf-8")),
            language="unknown",
            is_binary=False,
        )
        detected_lang = language or self.detector.detect(file_info)
        resolved_range: Optional[SourceRange] = target_range

        # If a target symbol is specified without an explicit range, resolve its bounds
        if target_symbol and resolved_range is None:
            sel_result = self.target_selector.select_target(
                file_path=file_path,
                content=content,
                target_type="symbol",
                symbol_name=target_symbol,
                language=detected_lang,
            )
            if sel_result.success:
                resolved_range = SourceRange(
                    file_path=file_path,
                    start_line=sel_result.start_line,
                    end_line=sel_result.end_line,
                    symbol_name=sel_result.symbol_name,
                    symbol_kind=sel_result.symbol_kind,
                )

        raw_findings: List[ASTBugFinding] = []
        parse_status = "OK"
        has_syntax_errors = False
        error_message: Optional[str] = None
        rules_evaluated = 0

        # Python Analysis via ast.parse
        if detected_lang.lower() == "python":
            python_ast: Optional[ast.AST] = None
            try:
                python_ast = ast.parse(content, filename=file_path or "<string>")
            except SyntaxError as e:
                parse_status = "SYNTAX_WARNING"
                has_syntax_errors = True
                error_message = f"SyntaxError: {e.msg} at line {e.lineno}"
                raw_findings.append(
                    ASTBugFinding(
                        rule_id="AST-SYNTAX-ERROR",
                        category="syntax_error",
                        severity="critical",
                        message=f"Syntax error: {e.msg}",
                        file_path=file_path,
                        line_number=e.lineno or 1,
                        end_line=e.end_lineno or e.lineno or 1,
                        column=e.offset or 1,
                        evidence=(e.text or "").strip(),
                        remediation="Fix syntax error so file can be parsed cleanly.",
                        confidence="high",
                    )
                )

            if python_ast:
                for rule in self.rules:
                    try:
                        rule_findings = rule.check_python(
                            tree=python_ast,
                            content=content,
                            file_path=file_path,
                            lines=lines,
                        )
                        raw_findings.extend(rule_findings)
                        rules_evaluated += 1
                    except Exception as exc:
                        logger.warning(f"Error evaluating rule {rule.rule_id}: {exc}")

        # Multi-Language Tree-sitter Analysis
        elif self.parser.is_language_supported(detected_lang):
            file_info = FileInfo(
                path=file_path,
                size_bytes=len(content.encode("utf-8")),
                language=detected_lang,
                is_binary=False,
            )
            parse_res: ParseResult = self.parser.parse_with_status(file_info, content)
            if not parse_res.success:
                parse_status = "PARSE_ERROR"
                error_message = parse_res.error_message
            elif parse_res.has_syntax_errors:
                parse_status = "SYNTAX_WARNING"
                has_syntax_errors = True
                raw_findings.append(
                    ASTBugFinding(
                        rule_id="AST-SYNTAX-ERROR",
                        category="syntax_error",
                        severity="critical",
                        message=f"Syntax errors detected by {detected_lang} parser",
                        file_path=file_path,
                        line_number=1,
                        end_line=total_lines or 1,
                        column=1,
                        evidence="File failed grammar verification",
                        remediation=f"Resolve syntax errors in {file_path}",
                        confidence="high",
                    )
                )

            if parse_res.tree is not None:
                root_node = getattr(parse_res.tree, "root_node", None)
                if root_node:
                    for rule in self.rules:
                        try:
                            rule_findings = rule.check_tree_sitter(
                                root_node=root_node,
                                content=content,
                                file_path=file_path,
                                language=detected_lang,
                                lines=lines,
                            )
                            raw_findings.extend(rule_findings)
                            rules_evaluated += 1
                        except Exception as exc:
                            logger.warning(f"Error evaluating tree-sitter rule {rule.rule_id}: {exc}")
        else:
            parse_status = "UNSUPPORTED_LANGUAGE"
            error_message = f"Language '{detected_lang}' is not supported for AST analysis"

        # Filter findings to target range if specified
        final_findings: List[ASTBugFinding] = []
        for finding in raw_findings:
            if resolved_range is not None:
                # Finding must overlap with target line bounds
                if (
                    finding.end_line < resolved_range.start_line
                    or finding.line_number > resolved_range.end_line
                ):
                    continue
                if not finding.enclosing_symbol and resolved_range.symbol_name:
                    finding.enclosing_symbol = resolved_range.symbol_name

            final_findings.append(finding)

        return ASTRuleAnalysisResult(
            success=True,
            file_path=file_path,
            findings=final_findings,
            parse_status=parse_status,
            has_syntax_errors=has_syntax_errors,
            error_message=error_message,
            rules_evaluated=rules_evaluated,
            target_range=resolved_range,
            target_symbol=target_symbol,
            total_lines=total_lines,
        )

    def analyze_file(
        self,
        file_path: str,
        repo_root: Optional[str] = None,
        target_range: Optional[SourceRange] = None,
        target_symbol: Optional[str] = None,
    ) -> ASTRuleAnalysisResult:
        """Analyze a file on disk with path traversal protections and explicit status."""
        safe_path = Path(file_path)
        if repo_root:
            resolved_root = Path(repo_root).resolve()
            resolved_target = (resolved_root / file_path).resolve()
            try:
                resolved_target.relative_to(resolved_root)
            except ValueError:
                return ASTRuleAnalysisResult(
                    success=False,
                    file_path=file_path,
                    findings=[],
                    parse_status="PARSE_ERROR",
                    error_message=f"Path traversal detected: {file_path} escapes repository root",
                )
            safe_path = resolved_target

        if not safe_path.exists() or safe_path.is_dir():
            return ASTRuleAnalysisResult(
                success=False,
                file_path=file_path,
                findings=[],
                parse_status="PARSE_ERROR",
                error_message=f"File not found: {file_path}",
            )

        try:
            content = safe_path.read_text(encoding="utf-8", errors="replace")
        except Exception as e:
            return ASTRuleAnalysisResult(
                success=False,
                file_path=file_path,
                findings=[],
                parse_status="PARSE_ERROR",
                error_message=f"Could not read file: {e}",
            )

        return self.analyze_code(
            content=content,
            file_path=file_path,
            target_range=target_range,
            target_symbol=target_symbol,
        )

    def analyze_target_selection(
        self,
        target_result: TargetSelectionResult,
        content: str,
    ) -> ASTRuleAnalysisResult:
        """Directly analyze a verified target selection from TargetSelector."""
        if not target_result.success:
            return ASTRuleAnalysisResult(
                success=False,
                file_path=target_result.file_path,
                findings=[],
                parse_status="PARSE_ERROR",
                error_message=target_result.error_message,
            )

        target_range = SourceRange(
            file_path=target_result.file_path,
            start_line=target_result.start_line,
            end_line=target_result.end_line,
            symbol_name=target_result.symbol_name,
            symbol_kind=target_result.symbol_kind,
        )

        return self.analyze_code(
            content=content,
            file_path=target_result.file_path,
            target_range=target_range,
            target_symbol=target_result.symbol_name,
        )

    def to_static_findings(
        self,
        findings: Sequence[ASTBugFinding],
    ) -> List[Dict[str, Any]]:
        """Export AST bug findings to Devu's normalized StaticFinding dictionary format."""
        return [f.to_static_finding_dict() for f in findings]
