"""Task Planning Test Discovery & Test Execution Plan Engine.

Owner: Prit Zania — Week 3 Day 2 Deliverable (Docs/week3.md §6 F32, F35 & Docs/daily_tasks.md line 614)
Reference: Docs/week3.md §6 (F32 Task Planner and Human Approval, F35 Restricted Test Runner)

Responsibilities:
1. Discover existing unit and integration test files for affected source files and symbols.
2. Inspect test call edges to identify specific test cases exercising modified symbols.
3. Detect untested symbols that lack test coverage across the repository.
4. Propose standardized new test file paths and test function names matching detected framework conventions.
5. Formulate the canonical test execution command line for the Day 4 Restricted Test Runner sandbox.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Mapping, Sequence
from uuid import UUID

from app.schemas.planner_context import (
    AffectedSymbol,
    ProposedTest,
    TestExecutionPlan,
)
from scanner.framework_detector import FrameworkDetector
from scanner.symbols import Symbol, SymbolEdge
from scanner.test_mapper import FileTestMapper


class TaskTestPlanner:
    """Plans test execution and proposes test coverage for task planning."""

    def __init__(self, repo_root: Path | str | None = None) -> None:
        """Initialize test planner with optional repository root directory."""
        self.repo_root = Path(repo_root) if repo_root else None
        self._framework_detector = FrameworkDetector()

    # -----------------------------------------------------------------------
    # 1. Framework Detection
    # -----------------------------------------------------------------------

    def detect_framework(
        self,
        repo_root: Path | str | None = None,
        file_paths: Sequence[str] | None = None,
    ) -> str:
        """Detect the dominant test framework (pytest, unittest, jest)."""
        target_root = Path(repo_root) if repo_root else self.repo_root

        # First check explicit file list if provided
        if file_paths:
            norm_paths = [p.replace("\\", "/").lower() for p in file_paths]
            if any(p.endswith((".test.ts", ".spec.ts", ".test.tsx", ".spec.tsx", ".test.js", ".spec.js")) for p in norm_paths):
                return "jest"
            if any(p.endswith(("_test.go", "test.java")) for p in norm_paths):
                return "pytest"
            if any("pytest" in p or "conftest.py" in p or "pytest.ini" in p for p in norm_paths):
                return "pytest"


        # Check directory manifests via FrameworkDetector
        if target_root and target_root.exists():
            try:
                res = self._framework_detector.detect(repo_root=str(target_root))
                if res and res.framework:
                    fw_raw = getattr(res.framework, "value", res.framework)
                    fw_name = str(fw_raw).lower()
                    if "jest" in fw_name or "vitest" in fw_name:
                        return "jest"
                    if "unittest" in fw_name:
                        return "unittest"
                    if "pytest" in fw_name:
                        return "pytest"
            except Exception:
                pass

        # Try FrameworkDetector with file_list if available
        if file_paths:
            try:
                res = self._framework_detector.detect(file_list=file_paths)
                if res and res.framework:
                    fw_raw = getattr(res.framework, "value", res.framework)
                    fw_name = str(fw_raw).lower()
                    if "jest" in fw_name or "vitest" in fw_name:
                        return "jest"
                    if "unittest" in fw_name:
                        return "unittest"
                    if "pytest" in fw_name:
                        return "pytest"
            except Exception:
                pass

        return "pytest"


    # -----------------------------------------------------------------------
    # 2. Existing Test Discovery
    # -----------------------------------------------------------------------

    def discover_existing_tests(
        self,
        affected_files: Sequence[str],
        repo_symbols: Sequence[Symbol],
        repo_edges: Sequence[SymbolEdge],
        file_paths: Mapping[UUID, str],
    ) -> tuple[list[str], list[str]]:
        """Identify test files and specific test functions covering affected files.

        Returns:
            Tuple of (existing_test_files, existing_test_cases).
        """
        norm_paths = {fid: p.replace("\\", "/").lstrip("/") for fid, p in file_paths.items()}
        test_mapper = FileTestMapper(list(repo_symbols), list(repo_edges), dict(file_paths))

        # Build reverse map: source_file -> set(test_files)
        test_to_source = test_mapper.map_tests()
        source_to_tests: dict[str, set[str]] = {}
        for t_file, s_file in test_to_source.items():
            norm_s = s_file.replace("\\", "/").lstrip("/")
            norm_t = t_file.replace("\\", "/").lstrip("/")
            source_to_tests.setdefault(norm_s, set()).add(norm_t)

        matched_test_files: set[str] = set()
        for aff in affected_files:
            aff_norm = aff.replace("\\", "/").lstrip("/")
            if aff_norm in source_to_tests:
                matched_test_files.update(source_to_tests[aff_norm])

            # Also check conventional naming matches
            aff_base = os.path.basename(aff_norm)
            aff_stem = os.path.splitext(aff_base)[0]

            for fid, p in norm_paths.items():
                if test_mapper.is_test_file(fid):
                    p_lower = p.lower()
                    if aff_stem.lower() in p_lower:
                        matched_test_files.add(p)

        # Discover individual test cases from symbols
        existing_test_cases: set[str] = set()
        test_file_paths_set = set(matched_test_files)

        for sym in repo_symbols:
            f_path = norm_paths.get(sym.file_id, "")
            if f_path in test_file_paths_set or "test" in f_path.lower():
                s_name = sym.name.lower()
                if s_name.startswith("test_") or s_name.startswith("test") or sym.kind == "method":
                    existing_test_cases.add(sym.name)

        return sorted(matched_test_files), sorted(existing_test_cases)

    # -----------------------------------------------------------------------
    # 3. Missing Coverage & New Test Proposals
    # -----------------------------------------------------------------------

    def propose_new_tests(
        self,
        directly_modified: Sequence[AffectedSymbol],
        existing_test_cases: Sequence[str],
        framework: str,
    ) -> tuple[list[str], list[ProposedTest]]:
        """Identify uncovered modified symbols and propose new test files/names.

        Returns:
            Tuple of (untested_symbols, proposed_tests).
        """
        existing_cases_lower = {c.lower() for c in existing_test_cases}
        untested_symbols: list[str] = []
        proposed_tests: list[ProposedTest] = []
        seen_proposals: set[str] = set()

        for sym in directly_modified:
            # Check if any existing test case mentions this symbol
            sym_clean = sym.name.lower().lstrip("_")
            covered = any(sym_clean in tc for tc in existing_cases_lower)

            if not covered:
                untested_symbols.append(sym.name)

                # Formulate target test path
                src_path = sym.file_path.replace("\\", "/").lstrip("/")
                src_dir = os.path.dirname(src_path)
                src_base = os.path.basename(src_path)
                src_stem, src_ext = os.path.splitext(src_base)

                if framework == "jest" or src_ext in (".ts", ".tsx", ".js", ".jsx"):
                    if src_dir:
                        suggested_file = f"{src_dir}/__tests__/{src_stem}.test{src_ext}"
                    else:
                        suggested_file = f"tests/{src_stem}.test{src_ext}"
                    suggested_name = f"test_{sym.name}_expected_behavior"
                else:
                    # Python pytest / unittest
                    if src_dir.startswith("src/"):
                        test_dir = "tests/" + src_dir[4:]
                    elif src_dir:
                        test_dir = f"tests/{src_dir}"
                    else:
                        test_dir = "tests"
                    suggested_file = f"{test_dir}/test_{src_stem}.py".replace("//", "/")
                    suggested_name = f"test_{sym.name}_success"

                prop_key = f"{suggested_file}::{suggested_name}"
                if prop_key not in seen_proposals:
                    seen_proposals.add(prop_key)
                    proposed_tests.append(
                        ProposedTest(
                            target_symbol=sym.name,
                            target_file=sym.file_path,
                            suggested_test_file=suggested_file,
                            suggested_test_name=suggested_name,
                            framework=framework,
                        )
                    )

        return untested_symbols, proposed_tests

    # -----------------------------------------------------------------------
    # 4. Command Line Generation
    # -----------------------------------------------------------------------

    def build_test_command(
        self,
        framework: str,
        existing_test_files: Sequence[str],
        proposed_new_test_files: Sequence[str] | None = None,
    ) -> str:
        """Format the exact test CLI command for the Restricted Test Runner sandbox."""
        all_test_files = list(existing_test_files)
        if not all_test_files and proposed_new_test_files:
            all_test_files = list(proposed_new_test_files)

        if framework == "pytest":
            if all_test_files:
                files_str = " ".join(all_test_files[:5])  # Cap at first 5 for concise command
                return f"pytest {files_str} -v --tb=short"
            return "pytest tests/ -v --tb=short"

        elif framework == "unittest":
            if all_test_files:
                files_str = " ".join(all_test_files[:5])
                return f"python -m unittest {files_str}"
            return "python -m unittest discover tests/"

        elif framework == "jest":
            if all_test_files:
                files_str = " ".join(all_test_files[:5])
                return f"npm test -- {files_str} --verbose"
            return "npm test -- --verbose"

        return "pytest tests/ -v"

    # -----------------------------------------------------------------------
    # 5. End-to-End Test Plan Generation
    # -----------------------------------------------------------------------

    def create_test_plan(
        self,
        affected_files: Sequence[str],
        directly_modified: Sequence[AffectedSymbol],
        repo_symbols: Sequence[Symbol],
        repo_edges: Sequence[SymbolEdge],
        file_paths: Mapping[UUID, str],
        repo_root: Path | str | None = None,
    ) -> TestExecutionPlan:
        """Build canonical TestExecutionPlan connecting blast radius to test execution."""
        framework = self.detect_framework(repo_root=repo_root, file_paths=list(file_paths.values()))
        existing_files, existing_cases = self.discover_existing_tests(
            affected_files=affected_files,
            repo_symbols=repo_symbols,
            repo_edges=repo_edges,
            file_paths=file_paths,
        )

        untested_syms, proposed = self.propose_new_tests(
            directly_modified=directly_modified,
            existing_test_cases=existing_cases,
            framework=framework,
        )

        cmd = self.build_test_command(
            framework=framework,
            existing_test_files=existing_files,
            proposed_new_test_files=[p.suggested_test_file for p in proposed],
        )

        return TestExecutionPlan(
            framework=framework,
            existing_test_files=existing_files,
            existing_test_cases=existing_cases,
            untested_symbols=untested_syms,
            proposed_new_tests=proposed,
            recommended_test_command=cmd,
            test_budget_timeout_seconds=60,
        )
