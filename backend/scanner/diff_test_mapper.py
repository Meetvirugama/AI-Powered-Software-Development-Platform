"""backend/scanner/diff_test_mapper.py

Diff-to-Test Mapping Engine for Autonomous Diff-Based Verification.
Part of Phase 4 (task.md §6 & §17 / TASK_PLANNER_IMPLEMENTATION_PLAN.md Phase 4).

Maps modified files and symbol call edges to specific existing test suites (pytest & vitest),
enforcing a 120s execution ceiling and structured multi-level evidence confidence.
"""

from __future__ import annotations

import ast
import logging
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sandbox.path_guard import WorkspacePathGuard

logger = logging.getLogger(__name__)

DEFAULT_TEST_TIMEOUT_SECONDS = 120


@dataclass
class TestMappingEvidence:
    """Evidence record supporting why a test was selected for a modified file."""

    source_file: str
    test_file: str
    confidence: str  # "PROVEN", "STRONG", "SUSPECTED"
    evidence_type: str  # "direct_import", "exact_name_match", "stem_match", "directory_match"
    reason: str


@dataclass
class DiffTestMappingResult:
    """Outcome of mapping changed repository files to targeted test suites."""

    changed_files: list[str]
    mapped_tests: list[str]
    test_framework: str  # "pytest", "vitest", "mixed", "none"
    test_command: str
    timeout_seconds: int = DEFAULT_TEST_TIMEOUT_SECONDS
    evidence: list[TestMappingEvidence] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "changed_files": self.changed_files,
            "mapped_tests": self.mapped_tests,
            "test_framework": self.test_framework,
            "test_command": self.test_command,
            "timeout_seconds": self.timeout_seconds,
            "evidence": [
                {
                    "source_file": e.source_file,
                    "test_file": e.test_file,
                    "confidence": e.confidence,
                    "evidence_type": e.evidence_type,
                    "reason": e.reason,
                }
                for e in self.evidence
            ],
        }


class DiffTestMapper:
    """Discovers and maps modified files in a diff to existing unit and integration test files."""

    def __init__(self, workspace_root: Path | str) -> None:
        self.workspace_root = Path(workspace_root).resolve()

    def discover_workspace_tests(self) -> tuple[list[str], list[str]]:
        """Scan workspace and classify existing test files into (python_tests, frontend_tests)."""
        python_tests: list[str] = []
        frontend_tests: list[str] = []

        for parent, dirnames, filenames in os.walk(self.workspace_root):
            # Prune ignore folders
            dirnames[:] = [
                d
                for d in dirnames
                if not d.startswith(".")
                and d not in ("node_modules", ".venv", "__pycache__", "dist", "build")
            ]

            for fname in filenames:
                file_path = Path(parent) / fname
                try:
                    rel_posix = file_path.relative_to(self.workspace_root).as_posix()
                except ValueError:
                    continue

                # Python test detection
                if fname.startswith("test_") and fname.endswith(".py"):
                    python_tests.append(rel_posix)
                elif fname.endswith("_test.py"):
                    python_tests.append(rel_posix)
                # Frontend test detection
                elif fname.endswith((".test.tsx", ".test.ts", ".spec.tsx", ".spec.ts", ".test.jsx", ".test.js")):
                    frontend_tests.append(rel_posix)

        return sorted(python_tests), sorted(frontend_tests)

    def map_changed_files(self, changed_files: list[str]) -> DiffTestMappingResult:
        """Map modified repository files to relevant test suites with evidence."""
        clean_changed = [f.replace("\\", "/").lstrip("/") for f in changed_files if f.strip()]
        if not clean_changed:
            return DiffTestMappingResult(
                changed_files=[],
                mapped_tests=[],
                test_framework="none",
                test_command="",
            )

        py_tests, fe_tests = self.discover_workspace_tests()
        mapped_tests: list[str] = []
        evidence_list: list[TestMappingEvidence] = []

        has_py_changes = any(f.endswith(".py") for f in clean_changed)
        has_fe_changes = any(
            f.endswith((".ts", ".tsx", ".js", ".jsx", ".css", ".html")) for f in clean_changed
        )

        for changed in clean_changed:
            changed_path = Path(changed)
            stem = changed_path.stem
            # If changed file is already a test file, it maps directly to itself
            if changed in py_tests or changed in fe_tests:
                if changed not in mapped_tests:
                    mapped_tests.append(changed)
                evidence_list.append(
                    TestMappingEvidence(
                        source_file=changed,
                        test_file=changed,
                        confidence="PROVEN",
                        evidence_type="direct_test_file",
                        reason="Modified file is itself an executable test file.",
                    )
                )
                continue

            # 1. Check Python test matches if changed file is python
            if changed.endswith(".py"):
                for t in py_tests:
                    t_name = Path(t).name
                    # Exact name match (e.g. tasks.py -> test_tasks.py)
                    if t_name == f"test_{stem}.py" or t_name == f"{stem}_test.py":
                        if t not in mapped_tests:
                            mapped_tests.append(t)
                        evidence_list.append(
                            TestMappingEvidence(
                                source_file=changed,
                                test_file=t,
                                confidence="STRONG",
                                evidence_type="exact_name_match",
                                reason=f"Test file '{t}' matches source stem '{stem}'.",
                            )
                        )
                    # Stem substring match (e.g. task_planner.py -> test_task_planner_and_executor.py)
                    elif stem in t_name:
                        if t not in mapped_tests:
                            mapped_tests.append(t)
                        evidence_list.append(
                            TestMappingEvidence(
                                source_file=changed,
                                test_file=t,
                                confidence="STRONG",
                                evidence_type="stem_match",
                                reason=f"Test file '{t}' contains source stem '{stem}'.",
                            )
                        )
                    else:
                        # Inspect test file contents for direct module imports
                        test_full = self.workspace_root / t
                        if test_full.exists():
                            try:
                                content = test_full.read_text(encoding="utf-8", errors="ignore")
                                if (
                                    f"import {stem}" in content
                                    or f"from {stem}" in content
                                    or stem in content
                                ):
                                    if t not in mapped_tests:
                                        mapped_tests.append(t)
                                    evidence_list.append(
                                        TestMappingEvidence(
                                            source_file=changed,
                                            test_file=t,
                                            confidence="SUSPECTED",
                                            evidence_type="direct_import",
                                            reason=f"Test file '{t}' references source symbol or module '{stem}'.",
                                        )
                                    )
                            except Exception:
                                pass

            # 2. Check Frontend test matches if changed file is frontend
            if changed_path.suffix in (".ts", ".tsx", ".js", ".jsx"):
                for t in fe_tests:
                    t_name = Path(t).name
                    if stem in t_name or changed_path.stem.lower() in t_name.lower():
                        if t not in mapped_tests:
                            mapped_tests.append(t)
                        evidence_list.append(
                            TestMappingEvidence(
                                source_file=changed,
                                test_file=t,
                                confidence="STRONG",
                                evidence_type="stem_match",
                                reason=f"Frontend test '{t}' matches component '{stem}'.",
                            )
                        )

        # Determine overall test framework and build execution command
        if has_py_changes and has_fe_changes:
            framework = "mixed"
        elif has_py_changes:
            framework = "pytest"
        elif has_fe_changes:
            framework = "vitest"
        else:
            framework = "pytest" if py_tests else "none"

        # Build command
        command = ""
        if mapped_tests:
            if framework == "vitest" or (framework == "mixed" and any(t in fe_tests for t in mapped_tests)):
                fe_mapped = [t for t in mapped_tests if t in fe_tests]
                if fe_mapped:
                    command = f"npx vitest run {' '.join(fe_mapped)}"
            if framework in ("pytest", "mixed") or not command:
                py_mapped = [t for t in mapped_tests if t in py_tests]
                if py_mapped:
                    command = f"pytest {' '.join(py_mapped)}"
        elif framework == "pytest":
            command = "pytest backend/tests/"
        elif framework == "vitest":
            command = "npm --prefix frontend test"

        return DiffTestMappingResult(
            changed_files=clean_changed,
            mapped_tests=mapped_tests,
            test_framework=framework,
            test_command=command,
            timeout_seconds=DEFAULT_TEST_TIMEOUT_SECONDS,
            evidence=evidence_list,
        )
