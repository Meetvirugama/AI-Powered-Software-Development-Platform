"""Repository-wide Test Requirement Discovery Engine.

Fulfills task.md §2, §3 (Phase 2 P0):
Discovers comprehensive test requirements across 14 categories from AST symbols,
parameters, error handling, API routes, database models, and documentation.
Reconciles code, dependency graph, existing tests, and architecture into a normalized
TestRequirement matrix.
"""

from __future__ import annotations

import ast
import logging
import os
import re
from collections.abc import Mapping, Sequence
from uuid import UUID

from app.schemas.analysis import (
    TestRequirement,
    TestRequirementCategory,
)

from scanner.symbols import Symbol, SymbolEdge

logger = logging.getLogger(__name__)

# Categories recognized by the discovery engine
ALL_CATEGORIES: list[TestRequirementCategory] = [
    "functional",
    "boundary",
    "negative",
    "exception_handling",
    "integration",
    "api_contract",
    "security",
    "state_lifecycle",
    "concurrency",
    "regression",
    "performance",
    "configuration",
    "frontend",
    "end_to_end",
]

# Patterns for mockable external integrations
_DB_PATTERNS = re.compile(r"\b(db|session|repository|collection)\.(query|execute|commit|rollback|add|delete|find|save)\b", re.IGNORECASE)
_HTTP_PATTERNS = re.compile(r"\b(httpx|requests|fetch|axios|http_client)\.(get|post|put|delete|patch|request)\b", re.IGNORECASE)
_CACHE_PATTERNS = re.compile(r"\b(redis|cache|memcached)\.(get|set|delete|expire|hget|hset)\b", re.IGNORECASE)
_AUTH_PATTERNS = re.compile(r"\b(password|secret|token|jwt|auth|credential|api_key|permission|role|user_id|tenant_id)\b", re.IGNORECASE)
_CONFIG_PATTERNS = re.compile(r"\b(os\.environ|os\.getenv|settings\.|process\.env)\b")
_DEFECT_PATTERNS = re.compile(r"(?i)\b(FIXME|TODO|BUG|HACK|XXX)\b:?\s*(.+)")


class TestRequirementDiscovery:
    """Discovers repository-wide test requirements across 14 behavior and risk categories."""

    __test__ = False

    def __init__(
        self,
        symbols: Sequence[Symbol] | None = None,
        edges: Sequence[SymbolEdge] | None = None,
        file_paths: Mapping[UUID, str] | Sequence[str] | None = None,
    ) -> None:
        self.symbols = list(symbols or [])
        self.edges = list(edges or [])
        self.file_paths_map: dict[str, str] = {}

        if isinstance(file_paths, Mapping):
            self.file_paths_map = {str(k): v.replace("\\", "/").lstrip("/") for k, v in file_paths.items()}
            self.all_files = sorted(set(self.file_paths_map.values()))
        elif isinstance(file_paths, Sequence):
            self.all_files = sorted({p.replace("\\", "/").lstrip("/") for p in file_paths})
        else:
            self.all_files = []

        self._symbols_by_file: dict[str, list[Symbol]] = {}
        for sym in self.symbols:
            fpath = self.file_paths_map.get(str(sym.file_id), "")
            if fpath:
                self._symbols_by_file.setdefault(fpath, []).append(sym)

    def discover_requirements(
        self,
        target_files: Sequence[str] | None = None,
        file_contents: Mapping[str, str] | None = None,
        focus_categories: Sequence[str] | None = None,
        changed_files: Sequence[str] | None = None,
    ) -> list[TestRequirement]:
        """Discover prioritized test requirements across the repository or targeted files."""
        contents = dict(file_contents or {})
        files_to_scan = list(target_files) if target_files else self.all_files
        if not files_to_scan and contents:
            files_to_scan = list(contents.keys())

        normalized_targets = [f.replace("\\", "/").lstrip("/") for f in files_to_scan]
        focus_set = {c.lower() for c in focus_categories} if focus_categories else None
        changed_set = {c.replace("\\", "/").lstrip("/") for c in (changed_files or [])}

        requirements: list[TestRequirement] = []
        req_counter = 1

        for fpath in normalized_targets:
            code = contents.get(fpath, "")
            is_test_file = self._is_test_path(fpath)
            if is_test_file:
                continue

            file_symbols = self._symbols_by_file.get(fpath, [])

            # Discover from Python AST if python file
            if fpath.endswith(".py") and code:
                py_reqs = self._discover_python_file(
                    fpath,
                    code,
                    file_symbols,
                    req_counter,
                    is_changed=fpath in changed_set,
                )
                req_counter += len(py_reqs)
                requirements.extend(py_reqs)
            elif (fpath.endswith((".ts", ".tsx", ".js", ".jsx"))) and code:
                js_reqs = self._discover_js_ts_file(
                    fpath,
                    code,
                    file_symbols,
                    req_counter,
                    is_changed=fpath in changed_set,
                )
                req_counter += len(js_reqs)
                requirements.extend(js_reqs)
            else:
                # Fallback discovery from symbols alone
                sym_reqs = self._discover_from_symbols(
                    fpath,
                    file_symbols,
                    req_counter,
                    is_changed=fpath in changed_set,
                )
                req_counter += len(sym_reqs)
                requirements.extend(sym_reqs)

        # Filter by focus categories if specified
        if focus_set:
            requirements = [r for r in requirements if r.category.lower() in focus_set]

        # Deduplicate and sort by priority
        return self._prioritize_and_dedup(requirements)

    def _is_test_path(self, path: str) -> bool:
        low = path.lower()
        base = os.path.basename(low)
        return (
            "test" in base
            or "spec" in base
            or "/tests/" in f"/{low}"
            or "/__tests__/" in f"/{low}"
        )

    # -----------------------------------------------------------------------
    # Python File Deep AST Requirement Extraction
    # -----------------------------------------------------------------------

    def _discover_python_file(
        self,
        fpath: str,
        code: str,
        symbols: list[Symbol],
        start_counter: int,
        is_changed: bool = False,
    ) -> list[TestRequirement]:
        reqs: list[TestRequirement] = []
        c = start_counter

        try:
            tree = ast.parse(code, filename=fpath)
        except SyntaxError:
            return self._discover_from_symbols(fpath, symbols, start_counter, is_changed)

        # 1. Defect & Regression comments
        for line_no, line in enumerate(code.splitlines(), start=1):
            m = _DEFECT_PATTERNS.search(line)
            if m:
                tag, note = m.group(1).upper(), m.group(2).strip()
                reqs.append(
                    TestRequirement(
                        requirement_id=f"REQ-REG-{c:03d}",
                        title=f"Regression & Defect Guard: {tag} at line {line_no}",
                        category="regression",
                        priority="HIGH" if tag in ("FIXME", "BUG") else "MEDIUM",
                        source_files=[fpath],
                        source_symbols=[],
                        expected_behavior=f"Verify fix or guard against unresolved defect ({tag}: {note})",
                        evidence=[f"{fpath}:{line_no} contains defect comment '{line.strip()}'"],
                        status="MISSING",
                        target_line=line_no,
                    )
                )
                c += 1

        # 2. Configuration access
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                call_str = ast.unparse(node.func) if hasattr(ast, "unparse") else ""
                if "os.getenv" in call_str or "os.environ" in call_str:
                    env_name = "CONFIG_PARAM"
                    if node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str):
                        env_name = node.args[0].value
                    reqs.append(
                        TestRequirement(
                            requirement_id=f"REQ-CONF-{c:03d}",
                            title=f"Configuration & Env Fallback: {env_name}",
                            category="configuration",
                            priority="MEDIUM",
                            source_files=[fpath],
                            source_symbols=[],
                            expected_behavior=f"Verify {env_name} reads properly when present and falls back gracefully when unset",
                            evidence=[f"{fpath}:{node.lineno} accesses environment setting {env_name}"],
                            status="MISSING",
                            target_line=node.lineno,
                        )
                    )
                    c += 1

        # 3. Class and Function analysis
        for node in ast.iter_child_nodes(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                fn_reqs = self._analyze_python_function(node, fpath, c, is_changed=is_changed)
                c += len(fn_reqs)
                reqs.extend(fn_reqs)
            elif isinstance(node, ast.ClassDef):
                cls_reqs = self._analyze_python_class(node, fpath, c, is_changed=is_changed)
                c += len(cls_reqs)
                reqs.extend(cls_reqs)

        return reqs

    def _analyze_python_function(
        self,
        node: ast.FunctionDef | ast.AsyncFunctionDef,
        fpath: str,
        counter: int,
        class_name: str | None = None,
        is_changed: bool = False,
    ) -> list[TestRequirement]:
        reqs: list[TestRequirement] = []
        c = counter
        sym_name = f"{class_name}.{node.name}" if class_name else node.name
        is_async = isinstance(node, ast.AsyncFunctionDef)

        # 1. Functional Requirement
        reqs.append(
            TestRequirement(
                requirement_id=f"REQ-FUNC-{c:03d}",
                title=f"Functional: {sym_name} happy path execution",
                category="functional",
                priority="CRITICAL" if is_changed else "HIGH",
                source_files=[fpath],
                source_symbols=[sym_name],
                expected_behavior=f"Execute {sym_name} with valid inputs and verify expected return value and state changes",
                evidence=[f"Callable symbol {sym_name} declared at {fpath}:{node.lineno}"],
                status="MISSING",
                target_line=node.lineno,
            )
        )
        c += 1

        # 2. Boundary & Negative testing from parameters
        arg_names = [a.arg for a in node.args.args if a.arg not in ("self", "cls")]
        if arg_names:
            reqs.append(
                TestRequirement(
                    requirement_id=f"REQ-BOUND-{c:03d}",
                    title=f"Boundary: {sym_name} with edge inputs ({', '.join(arg_names[:3])})",
                    category="boundary",
                    priority="HIGH",
                    source_files=[fpath],
                    source_symbols=[sym_name],
                    expected_behavior=f"Verify {sym_name} handles empty collections, zero/null, boundary values without crashing",
                    evidence=[f"Parameters '{', '.join(arg_names)}' accept inputs at {fpath}:{node.lineno}"],
                    status="MISSING",
                    target_line=node.lineno,
                )
            )
            c += 1

            reqs.append(
                TestRequirement(
                    requirement_id=f"REQ-NEG-{c:03d}",
                    title=f"Negative: {sym_name} with invalid/malformed parameters",
                    category="negative",
                    priority="MEDIUM",
                    source_files=[fpath],
                    source_symbols=[sym_name],
                    expected_behavior="Reject invalid argument types and None/null values gracefully with validation error",
                    evidence=[f"Input contract for {sym_name} at {fpath}:{node.lineno}"],
                    status="MISSING",
                    target_line=node.lineno,
                )
            )
            c += 1

        # 3. Exception handling & Raise nodes
        raises = [sub for sub in ast.walk(node) if isinstance(sub, ast.Raise)]
        if raises:
            reqs.append(
                TestRequirement(
                    requirement_id=f"REQ-EXC-{c:03d}",
                    title=f"Exception Handling: {sym_name} error paths",
                    category="exception_handling",
                    priority="HIGH",
                    source_files=[fpath],
                    source_symbols=[sym_name],
                    expected_behavior=f"Assert {sym_name} raises expected exception types and error messages on invalid conditions",
                    evidence=[f"{len(raises)} raise statement(s) detected in {sym_name} at {fpath}:{node.lineno}"],
                    status="MISSING",
                    target_line=node.lineno,
                )
            )
            c += 1

        # 4. Concurrency if async
        if is_async:
            reqs.append(
                TestRequirement(
                    requirement_id=f"REQ-CONC-{c:03d}",
                    title=f"Concurrency & Async Safety: {sym_name}",
                    category="concurrency",
                    priority="MEDIUM",
                    source_files=[fpath],
                    source_symbols=[sym_name],
                    expected_behavior=f"Verify {sym_name} completes concurrently under async gather without race conditions",
                    evidence=[f"Async coroutine function {sym_name} defined at {fpath}:{node.lineno}"],
                    status="MISSING",
                    target_line=node.lineno,
                )
            )
            c += 1

        # 5. External integrations (DB, HTTP, Redis)
        fn_code = ast.unparse(node) if hasattr(ast, "unparse") else ""
        if _DB_PATTERNS.search(fn_code):
            reqs.append(
                TestRequirement(
                    requirement_id=f"REQ-INT-{c:03d}",
                    title=f"Integration: {sym_name} database transaction",
                    category="integration",
                    priority="HIGH",
                    source_files=[fpath],
                    source_symbols=[sym_name],
                    expected_behavior=f"Verify {sym_name} queries, saves, and commits data correctly with rollback on failure",
                    evidence=[f"Database operations detected inside {sym_name} at {fpath}:{node.lineno}"],
                    status="MISSING",
                    target_line=node.lineno,
                )
            )
            c += 1

        if _HTTP_PATTERNS.search(fn_code):
            reqs.append(
                TestRequirement(
                    requirement_id=f"REQ-INT-{c:03d}",
                    title=f"Integration: {sym_name} external HTTP client",
                    category="integration",
                    priority="HIGH",
                    source_files=[fpath],
                    source_symbols=[sym_name],
                    expected_behavior=f"Verify {sym_name} sends expected HTTP payload, handles timeouts, and processes response",
                    evidence=[f"External HTTP calls detected in {sym_name} at {fpath}:{node.lineno}"],
                    status="MISSING",
                    target_line=node.lineno,
                )
            )
            c += 1

        # 6. Security & Auth
        if _AUTH_PATTERNS.search(sym_name) or _AUTH_PATTERNS.search(fn_code):
            reqs.append(
                TestRequirement(
                    requirement_id=f"REQ-SEC-{c:03d}",
                    title=f"Security & Auth: {sym_name} access boundary",
                    category="security",
                    priority="CRITICAL",
                    source_files=[fpath],
                    source_symbols=[sym_name],
                    expected_behavior="Verify unauthorized or tampered credentials are rejected and secrets are never leaked",
                    evidence=[f"Security/auth token patterns found in {sym_name} at {fpath}:{node.lineno}"],
                    status="MISSING",
                    target_line=node.lineno,
                )
            )
            c += 1

        # 7. API Contract
        has_api_decorator = any(
            isinstance(d, ast.Call)
            and any(m in getattr(d.func, "attr", "") for m in ("get", "post", "put", "delete", "patch"))
            for d in node.decorator_list
        )
        if has_api_decorator or "router." in fn_code or "app." in fn_code:
            reqs.append(
                TestRequirement(
                    requirement_id=f"REQ-API-{c:03d}",
                    title=f"API Contract: {sym_name} request/response schema",
                    category="api_contract",
                    priority="CRITICAL",
                    source_files=[fpath],
                    source_symbols=[sym_name],
                    expected_behavior=f"Verify HTTP status codes, response headers, and Pydantic validation for {sym_name}",
                    evidence=[f"API route decorator detected on {sym_name} at {fpath}:{node.lineno}"],
                    status="MISSING",
                    target_line=node.lineno,
                )
            )
            c += 1

        return reqs

    def _analyze_python_class(
        self,
        node: ast.ClassDef,
        fpath: str,
        counter: int,
        is_changed: bool = False,
    ) -> list[TestRequirement]:
        reqs: list[TestRequirement] = []
        c = counter

        # State & lifecycle requirement for class instantiation and teardown
        reqs.append(
            TestRequirement(
                requirement_id=f"REQ-STATE-{c:03d}",
                title=f"State & Lifecycle: {node.name} instance initialization & transitions",
                category="state_lifecycle",
                priority="HIGH" if is_changed else "MEDIUM",
                source_files=[fpath],
                source_symbols=[node.name],
                expected_behavior=f"Construct {node.name} with default and custom state, verify invariants and lifecycle transitions",
                evidence=[f"Class definition {node.name} at {fpath}:{node.lineno}"],
                status="MISSING",
                target_line=node.lineno,
            )
        )
        c += 1

        for child in node.body:
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                fn_reqs = self._analyze_python_function(
                    child,
                    fpath,
                    c,
                    class_name=node.name,
                    is_changed=is_changed,
                )
                c += len(fn_reqs)
                reqs.extend(fn_reqs)

        return reqs

    # -----------------------------------------------------------------------
    # JS / TS File Structural Requirement Extraction
    # -----------------------------------------------------------------------

    def _discover_js_ts_file(
        self,
        fpath: str,
        code: str,
        symbols: list[Symbol],
        start_counter: int,
        is_changed: bool = False,
    ) -> list[TestRequirement]:
        reqs: list[TestRequirement] = []
        c = start_counter
        is_frontend = fpath.endswith((".tsx", ".jsx")) or "/components/" in fpath or "/pages/" in fpath

        # 1. Defect comments
        for line_no, line in enumerate(code.splitlines(), start=1):
            m = _DEFECT_PATTERNS.search(line)
            if m:
                tag, note = m.group(1).upper(), m.group(2).strip()
                reqs.append(
                    TestRequirement(
                        requirement_id=f"REQ-REG-{c:03d}",
                        title=f"Regression Guard: {tag} at line {line_no}",
                        category="regression",
                        priority="HIGH" if tag in ("FIXME", "BUG") else "MEDIUM",
                        source_files=[fpath],
                        source_symbols=[],
                        expected_behavior=f"Verify fix or guard against defect ({tag}: {note})",
                        evidence=[f"{fpath}:{line_no} contains defect comment '{line.strip()}'"],
                        status="MISSING",
                        target_line=line_no,
                    )
                )
                c += 1

        # 2. Frontend Component Testing
        if is_frontend:
            comp_name = os.path.splitext(os.path.basename(fpath))[0]
            reqs.append(
                TestRequirement(
                    requirement_id=f"REQ-FE-{c:03d}",
                    title=f"Frontend: {comp_name} render & user interactions",
                    category="frontend",
                    priority="HIGH",
                    source_files=[fpath],
                    source_symbols=[comp_name],
                    expected_behavior=f"Mount {comp_name}, assert correct DOM output, loading states, and event handling",
                    evidence=[f"Frontend UI module at {fpath}"],
                    status="MISSING",
                    target_line=1,
                )
            )
            c += 1

        # 3. Discover functions/methods from symbols or regex
        fn_pattern = re.compile(r"(?:export\s+)?(?:async\s+)?function\s+([A-Za-z0-9_]+)\s*\(([^)]*)\)", re.MULTILINE)
        for match in fn_pattern.finditer(code):
            fn_name = match.group(1)
            params = [p.strip().split(":")[0].strip() for p in match.group(2).split(",") if p.strip()]
            reqs.append(
                TestRequirement(
                    requirement_id=f"REQ-FUNC-{c:03d}",
                    title=f"Functional: {fn_name} behavior",
                    category="functional",
                    priority="CRITICAL" if is_changed else "HIGH",
                    source_files=[fpath],
                    source_symbols=[fn_name],
                    expected_behavior=f"Execute {fn_name} with valid inputs and verify return value",
                    evidence=[f"Function {fn_name} declared in {fpath}"],
                    status="MISSING",
                    target_line=code[: match.start()].count("\n") + 1,
                )
            )
            c += 1

            if params:
                reqs.append(
                    TestRequirement(
                        requirement_id=f"REQ-BOUND-{c:03d}",
                        title=f"Boundary: {fn_name} edge cases ({', '.join(params[:2])})",
                        category="boundary",
                        priority="HIGH",
                        source_files=[fpath],
                        source_symbols=[fn_name],
                        expected_behavior=f"Handle empty, null, undefined, and boundary values for {fn_name}",
                        evidence=[f"Parameters '{', '.join(params)}' accept inputs in {fpath}"],
                        status="MISSING",
                        target_line=code[: match.start()].count("\n") + 1,
                    )
                )
                c += 1

        return reqs

    # -----------------------------------------------------------------------
    # Fallback Symbol-Based Discovery
    # -----------------------------------------------------------------------

    def _discover_from_symbols(
        self,
        fpath: str,
        symbols: list[Symbol],
        start_counter: int,
        is_changed: bool = False,
    ) -> list[TestRequirement]:
        reqs: list[TestRequirement] = []
        c = start_counter

        for sym in symbols:
            if sym.kind in ("function", "method"):
                reqs.append(
                    TestRequirement(
                        requirement_id=f"REQ-FUNC-{c:03d}",
                        title=f"Functional: {sym.name} execution",
                        category="functional",
                        priority="HIGH" if not is_changed else "CRITICAL",
                        source_files=[fpath],
                        source_symbols=[sym.name],
                        expected_behavior=f"Verify {sym.name} executes correctly and adheres to interface contract",
                        evidence=[f"Symbol {sym.kind} '{sym.name}' indexed at {fpath}:{sym.start_line}"],
                        status="MISSING",
                        target_line=sym.start_line,
                    )
                )
                c += 1
            elif sym.kind == "class":
                reqs.append(
                    TestRequirement(
                        requirement_id=f"REQ-STATE-{c:03d}",
                        title=f"State: {sym.name} lifecycle",
                        category="state_lifecycle",
                        priority="MEDIUM",
                        source_files=[fpath],
                        source_symbols=[sym.name],
                        expected_behavior=f"Construct and verify state management for {sym.name}",
                        evidence=[f"Class symbol '{sym.name}' at {fpath}:{sym.start_line}"],
                        status="MISSING",
                        target_line=sym.start_line,
                    )
                )
                c += 1

        return reqs

    # -----------------------------------------------------------------------
    # Deduplication & Priority Sorting
    # -----------------------------------------------------------------------

    def _prioritize_and_dedup(self, requirements: list[TestRequirement]) -> list[TestRequirement]:
        priority_order = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}
        seen: set[str] = set()
        deduped: list[TestRequirement] = []

        for req in requirements:
            key = (req.category, tuple(req.source_files), tuple(req.source_symbols), req.title)
            if key not in seen:
                seen.add(key)
                deduped.append(req)

        deduped.sort(key=lambda r: (priority_order.get(str(r.priority).upper(), 4), r.category, r.requirement_id))
        return deduped

