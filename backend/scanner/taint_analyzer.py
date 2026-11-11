"""Taint analysis engine for source-to-sink tracking and sanitizer awareness.

Part of Phase 2: Graph-Guided Detection & Program Slicing (task.md).
Identifies untrusted user input sources, propagation through intermediate variables,
presence or absence of sanitizers/defensive guards, and unsafe sinks.
"""

from __future__ import annotations

import ast
import logging
import re
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class TaintNode:
    """A node along a taint flow path."""
    name: str
    line: int
    kind: str  # "source", "propagator", "sanitizer", "sink"
    expression: str
    detail: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "line": self.line,
            "kind": self.kind,
            "expression": self.expression,
            "detail": self.detail,
        }


@dataclass
class TaintFlowCandidate:
    """A candidate taint-flow defect discovered during analysis."""
    candidate_id: str
    rule_id: str
    category: str  # "security"
    vulnerability_type: str  # "sql_injection", "command_injection", "path_traversal", "ssrf", "xss"
    severity: str  # "critical", "high", "medium", "low"
    file_path: str
    start_line: int
    end_line: int
    source: TaintNode
    sink: TaintNode
    propagators: list[TaintNode] = field(default_factory=list)
    sanitizers_found: list[TaintNode] = field(default_factory=list)
    is_sanitized: bool = False
    evidence: str = ""
    remediation: str = ""
    confidence: str = "high"

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "rule_id": self.rule_id,
            "category": self.category,
            "vulnerability_type": self.vulnerability_type,
            "severity": self.severity,
            "file_path": self.file_path,
            "start_line": self.start_line,
            "end_line": self.end_line,
            "source": self.source.to_dict(),
            "sink": self.sink.to_dict(),
            "propagators": [p.to_dict() for p in self.propagators],
            "sanitizers_found": [s.to_dict() for s in self.sanitizers_found],
            "is_sanitized": self.is_sanitized,
            "evidence": self.evidence,
            "remediation": self.remediation,
            "confidence": self.confidence,
        }


class TaintAnalyzer:
    """Analyzes AST and source patterns to trace untrusted inputs to critical sinks."""

    # Taint sources patterns
    SOURCE_PATTERNS = {
        "request.query_params": ("request.query_params", "HTTP GET query parameters"),
        "request.args": ("request.args", "HTTP query string parameters"),
        "request.form": ("request.form", "HTTP form payload"),
        "request.json": ("request.json", "HTTP JSON body"),
        "request.data": ("request.data", "Raw HTTP request body"),
        "request.headers": ("request.headers", "HTTP header values"),
        "request.cookies": ("request.cookies", "HTTP cookie values"),
        "req.query": ("req.query", "Express/Node query parameters"),
        "req.body": ("req.body", "Express/Node request body"),
        "req.params": ("req.params", "Express/Node route parameters"),
        "sys.argv": ("sys.argv", "CLI arguments"),
        "os.environ": ("os.environ", "Environment variables"),
        "os.getenv": ("os.getenv", "Environment variables"),
        "input(": ("input", "Standard console input"),
    }

    # Sinks categorized by defect type
    SQL_SINKS = {
        "execute", "executemany", "raw_sql", "execute_sql"
    }

    CMD_SINKS = {
        "system", "popen", "spawn", "call", "check_call", "check_output", "run"
    }

    PATH_SINKS = {
        "open", "remove", "unlink", "rmdir", "rmtree", "copyfile", "copy", "move"
    }

    SSRF_SINKS = {
        "get", "post", "put", "delete", "request", "urlopen", "fetch"
    }

    SANITIZERS = {
        # SQL sanitizers
        "int": "type_cast_integer",
        "float": "type_cast_float",
        "bool": "type_cast_boolean",
        "UUID": "uuid_validation",
        "quote": "parameter_quoting",
        "escape": "character_escaping",
        "shlex.quote": "shell_quoting",
        "secure_filename": "secure_filename_sanitizer",
        "os.path.basename": "basename_path_strip",
        "pathlib.Path.resolve": "path_resolution",
        "html.escape": "html_escaping",
        "markupsafe.escape": "markup_escaping",
    }

    def __init__(self) -> None:
        pass

    def analyze_source(
        self,
        code: str,
        file_path: str = "snippet.py",
        language: str = "python",
    ) -> list[TaintFlowCandidate]:
        """Analyze code snippet or file content for source-to-sink taint flows."""
        if not code or not code.strip():
            return []

        candidates: list[TaintFlowCandidate] = []
        lang = (language or "").lower()

        if lang in ("python", "py") or file_path.endswith((".py", ".pyi")):
            candidates.extend(self._analyze_python_ast(code, file_path))

        # Always complement with pattern-based analysis for JS/TS or snippets
        candidates.extend(self._analyze_pattern_fallback(code, file_path, existing=candidates))
        return candidates

    def _analyze_python_ast(self, code: str, file_path: str) -> list[TaintFlowCandidate]:
        try:
            tree = ast.parse(code, filename=file_path)
        except Exception:
            return []

        candidates: list[TaintFlowCandidate] = []
        lines = code.splitlines()

        has_functions = any(isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) for n in ast.walk(tree))
        for node in ast.walk(tree):
            if has_functions and isinstance(node, ast.Module):
                continue
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Module)):
                continue

            # Within function or module, build local variable assignment graph
            flow_candidates = self._analyze_scope(node, lines, file_path)
            candidates.extend(flow_candidates)

        # Deduplicate candidates on (file_path, start_line, vulnerability_type)
        deduped: dict[tuple[str, int, str], TaintFlowCandidate] = {}
        for c in candidates:
            k = (c.file_path, c.start_line, c.vulnerability_type)
            if k not in deduped or (not c.is_sanitized and deduped[k].is_sanitized):
                deduped[k] = c

        return list(deduped.values())

    def _analyze_scope(
        self,
        scope_node: ast.AST,
        lines: list[str],
        file_path: str,
    ) -> list[TaintFlowCandidate]:
        candidates: list[TaintFlowCandidate] = []
        tainted_vars: dict[str, TaintNode] = {}
        sanitized_vars: dict[str, list[TaintNode]] = {}
        propagators: dict[str, list[TaintNode]] = {}

        # Scan statements in order
        for stmt in ast.walk(scope_node):
            if isinstance(stmt, ast.Assign):
                # Variable assignment: var = expr
                source_node = self._find_taint_source_in_expr(stmt.value, lines)
                target_names = [t.id for t in stmt.targets if isinstance(t, ast.Name)]

                if source_node:
                    for name in target_names:
                        tainted_vars[name] = source_node
                        propagators[name] = [
                            TaintNode(
                                name=name,
                                line=stmt.lineno,
                                kind="propagator",
                                expression=lines[stmt.lineno - 1].strip() if stmt.lineno <= len(lines) else name,
                                detail=f"Assigned untrusted input to '{name}'",
                            )
                        ]
                else:
                    # Check if assigned value propagates another tainted variable
                    for name in target_names:
                        referenced_taint = self._find_tainted_ref_in_expr(stmt.value, tainted_vars)
                        if referenced_taint:
                            # Propagate origin taint source
                            tainted_vars[name] = tainted_vars[referenced_taint]
                            # Check if sanitizer is applied in this assignment
                            sanitizer = self._find_sanitizer_in_expr(stmt.value, lines)
                            if sanitizer:
                                sanitized_vars.setdefault(name, []).append(sanitizer)
                            # Also inherit any sanitizers already on referenced_taint
                            if referenced_taint in sanitized_vars:
                                sanitized_vars.setdefault(name, []).extend(sanitized_vars[referenced_taint])

                            prev_props = list(propagators.get(referenced_taint, []))
                            prev_props.append(
                                TaintNode(
                                    name=name,
                                    line=stmt.lineno,
                                    kind="sanitizer" if sanitizer else "propagator",
                                    expression=lines[stmt.lineno - 1].strip() if stmt.lineno <= len(lines) else name,
                                    detail=f"Applied sanitizer '{sanitizer.name}'" if sanitizer else f"Propagated untrusted data from '{referenced_taint}' into '{name}'",
                                )
                            )
                            propagators[name] = prev_props

            elif isinstance(stmt, ast.Call):
                # Inspect call node for dangerous sinks
                sink_candidate = self._inspect_call_sink(
                    stmt, lines, file_path, tainted_vars, sanitized_vars, propagators
                )
                if sink_candidate:
                    candidates.append(sink_candidate)

        return candidates

    def _find_taint_source_in_expr(self, expr: ast.AST, lines: list[str]) -> TaintNode | None:
        """Check if an expression accesses a known untrusted input source."""
        # Check attribute access like request.query_params['id'] or request.args.get(...)
        for sub in ast.walk(expr):
            sub_str = self._ast_to_source(sub)
            for pattern, (label, detail) in self.SOURCE_PATTERNS.items():
                if pattern in sub_str:
                    lineno = getattr(sub, "lineno", 1)
                    raw_line = lines[lineno - 1].strip() if lineno <= len(lines) else sub_str
                    return TaintNode(
                        name=label,
                        line=lineno,
                        kind="source",
                        expression=raw_line,
                        detail=detail,
                    )
        return None

    def _find_tainted_ref_in_expr(self, expr: ast.AST, tainted_vars: dict[str, TaintNode]) -> str | None:
        """Check if any currently tainted variable is referenced inside the expression."""
        for sub in ast.walk(expr):
            if isinstance(sub, ast.Name) and sub.id in tainted_vars:
                return sub.id
        return None

    def _find_sanitizer_in_expr(self, expr: ast.AST, lines: list[str]) -> TaintNode | None:
        """Check if a known sanitizer or typecast wrapper is applied."""
        for sub in ast.walk(expr):
            if isinstance(sub, ast.Call):
                func_name = self._ast_to_source(sub.func)
                base_call = func_name.rsplit(".", 1)[-1]
                if base_call in {"unquote", "unquote_plus", "unquote_to_bytes", "unescape"}:
                    continue
                for san_name, san_desc in self.SANITIZERS.items():
                    if func_name == san_name or func_name.endswith("." + san_name):
                        lineno = getattr(sub, "lineno", 1)
                        raw_line = lines[lineno - 1].strip() if lineno <= len(lines) else func_name
                        return TaintNode(
                            name=san_name,
                            line=lineno,
                            kind="sanitizer",
                            expression=raw_line,
                            detail=san_desc,
                        )
        return None

    def _inspect_call_sink(
        self,
        call: ast.Call,
        lines: list[str],
        file_path: str,
        tainted_vars: dict[str, TaintNode],
        sanitized_vars: dict[str, list[TaintNode]],
        propagators: dict[str, list[TaintNode]],
    ) -> TaintFlowCandidate | None:
        func_expr = self._ast_to_source(call.func)
        func_parts = func_expr.split(".")
        func_name = func_parts[-1]

        lineno = getattr(call, "lineno", 1)
        raw_line = lines[lineno - 1].strip() if lineno <= len(lines) else func_expr

        # 1. SQL Injection Sink
        if func_name in self.SQL_SINKS:
            for i, arg in enumerate(call.args):
                tainted_ref = self._find_tainted_ref_in_expr(arg, tainted_vars)
                # Check for string formatting / f-strings / concatenation
                is_concatenated = self._is_unsafe_sql_construction(arg)
                if tainted_ref and (is_concatenated or i == 0):
                    sanitizers = sanitized_vars.get(tainted_ref, [])
                    # Check if query has separate parameters in call: e.g. execute(sql, (p1, p2))
                    has_param_tuple = len(call.args) > 1 or any(k.arg in ("params", "parameters") for k in call.keywords)
                    is_safe = bool(sanitizers) or (has_param_tuple and not is_concatenated)

                    source_node = tainted_vars[tainted_ref]
                    sink_node = TaintNode(
                        name=func_name,
                        line=lineno,
                        kind="sink",
                        expression=raw_line,
                        detail="Database query execution sink",
                    )

                    return TaintFlowCandidate(
                        candidate_id=f"TAINT-SQL-{lineno}",
                        rule_id="TAINT-SQL-001",
                        category="security",
                        vulnerability_type="sql_injection",
                        severity="CRITICAL" if not is_safe else "LOW",
                        file_path=file_path,
                        start_line=lineno,
                        end_line=lineno,
                        source=source_node,
                        sink=sink_node,
                        propagators=propagators.get(tainted_ref, []),
                        sanitizers_found=sanitizers,
                        is_sanitized=is_safe,
                        evidence=f"Untrusted input '{source_node.name}' (line {source_node.line}) reaches SQL query '{func_name}' at line {lineno} without parameterized binding.",
                        remediation="Use parameterized queries (e.g. `cursor.execute(query, (param,))`) or ORM models instead of string interpolation.",
                        confidence="high" if not is_safe else "low",
                    )

        # 2. Command Injection Sink
        cmd_modules = {"subprocess", "os"}
        is_cmd = func_name in self.CMD_SINKS and (len(func_parts) > 1 and func_parts[0] in cmd_modules or func_name in ("system", "popen"))
        if is_cmd:
            for arg in call.args:
                tainted_ref = self._find_tainted_ref_in_expr(arg, tainted_vars)
                if tainted_ref:
                    sanitizers = sanitized_vars.get(tainted_ref, [])
                    # Check shell=True kwargs - if shell=True is passed, it is not safe even with partial sanitizers
                    shell_true = any(k.arg == "shell" and getattr(k.value, "value", False) is True for k in call.keywords)
                    is_safe = bool(sanitizers) and not shell_true

                    source_node = tainted_vars[tainted_ref]
                    sink_node = TaintNode(
                        name=func_expr,
                        line=lineno,
                        kind="sink",
                        expression=raw_line,
                        detail="Operating system command execution sink",
                    )
                    return TaintFlowCandidate(
                        candidate_id=f"TAINT-CMD-{lineno}",
                        rule_id="TAINT-CMD-001",
                        category="security",
                        vulnerability_type="command_injection",
                        severity="CRITICAL" if not is_safe else "LOW",
                        file_path=file_path,
                        start_line=lineno,
                        end_line=lineno,
                        source=source_node,
                        sink=sink_node,
                        propagators=propagators.get(tainted_ref, []),
                        sanitizers_found=sanitizers,
                        is_sanitized=is_safe,
                        evidence=f"Untrusted input reaches OS command runner '{func_expr}' at line {lineno}.",
                        remediation="Avoid shell execution; pass arguments as an explicit sequence to `subprocess.run(..., shell=False)`.",
                        confidence="high" if not is_safe else "low",
                    )

        # 3. Path Traversal Sink
        if func_name in self.PATH_SINKS:
            if call.args:
                path_arg = call.args[0]
                tainted_ref = self._find_tainted_ref_in_expr(path_arg, tainted_vars)
                if tainted_ref:
                    sanitizers = sanitized_vars.get(tainted_ref, [])
                    is_safe = bool(sanitizers)
                    source_node = tainted_vars[tainted_ref]
                    sink_node = TaintNode(
                        name=func_name,
                        line=lineno,
                        kind="sink",
                        expression=raw_line,
                        detail="File system I/O sink",
                    )
                    return TaintFlowCandidate(
                        candidate_id=f"TAINT-PATH-{lineno}",
                        rule_id="TAINT-PATH-001",
                        category="security",
                        vulnerability_type="path_traversal",
                        severity="HIGH" if not is_safe else "LOW",
                        file_path=file_path,
                        start_line=lineno,
                        end_line=lineno,
                        source=source_node,
                        sink=sink_node,
                        propagators=propagators.get(tainted_ref, []),
                        sanitizers_found=sanitizers,
                        is_sanitized=is_safe,
                        evidence=f"Untrusted file path reaches '{func_name}' at line {lineno} without canonical path sanitization.",
                        remediation="Sanitize path using `os.path.basename()` or verify absolute path belongs to allowed base directory.",
                        confidence="high" if not is_safe else "low",
                    )

        return None

    def _is_unsafe_sql_construction(self, node: ast.AST) -> bool:
        """Check if AST node represents string concatenation, format(), or JoinedStr (f-string)."""
        if isinstance(node, ast.JoinedStr):
            return True
        if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Add, ast.Mod)):
            return True
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "format":
            return True
        return False

    def _ast_to_source(self, node: ast.AST) -> str:
        """Convert AST expression to a representative string."""
        if isinstance(node, ast.Name):
            return node.id
        if isinstance(node, ast.Attribute):
            val = self._ast_to_source(node.value)
            return f"{val}.{node.attr}" if val else node.attr
        if isinstance(node, ast.Subscript):
            val = self._ast_to_source(node.value)
            return f"{val}[...]"
        if isinstance(node, ast.Call):
            return self._ast_to_source(node.func)
        return ""

    def _analyze_pattern_fallback(
        self,
        code: str,
        file_path: str,
        existing: list[TaintFlowCandidate],
    ) -> list[TaintFlowCandidate]:
        """Regex and pattern-based analysis for multi-language and fallback coverage."""
        existing_lines = {c.start_line for c in existing}
        candidates: list[TaintFlowCandidate] = []
        lines = code.splitlines()

        # Regex patterns for direct taint to SQL/Command sinks
        sql_pattern = re.compile(
            r'(\b(?:execute|raw_sql|executemany)\s*\(\s*(?:f["\']|["\'][^"\']*\b(?:SELECT|INSERT|UPDATE|DELETE|DROP)\b[^"\']*["\']\s*\+))',
            re.IGNORECASE,
        )

        for i, line in enumerate(lines, start=1):
            if i in existing_lines:
                continue

            # Direct SQL concatenation check
            match = sql_pattern.search(line)
            if match:
                src_node = TaintNode(
                    name="concatenated_expression",
                    line=i,
                    kind="source",
                    expression=line.strip(),
                    detail="String concatenation or interpolation in SQL query statement",
                )
                sink_node = TaintNode(
                    name="execute",
                    line=i,
                    kind="sink",
                    expression=line.strip(),
                    detail="Database query execution sink",
                )
                candidates.append(
                    TaintFlowCandidate(
                        candidate_id=f"TAINT-SQL-REGEX-{i}",
                        rule_id="TAINT-SQL-001",
                        category="security",
                        vulnerability_type="sql_injection",
                        severity="HIGH",
                        file_path=file_path,
                        start_line=i,
                        end_line=i,
                        source=src_node,
                        sink=sink_node,
                        propagators=[],
                        sanitizers_found=[],
                        is_sanitized=False,
                        evidence=f"Dynamic string concatenation detected inside database execution call at line {i}.",
                        remediation="Use parameterized queries instead of direct string concatenation.",
                        confidence="high",
                    )
                )

        return candidates
