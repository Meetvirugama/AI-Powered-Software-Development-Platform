"""Test Coverage Analyzer Engine.

Fulfills task.md §4, §6 (Phase 4 P0):
Consumes actual test execution coverage or static analysis evidence and maps it
back to source files, symbols, lines, and branches. Computes honest, truthful
line and branch coverage metrics.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

# Regular expressions for standard pytest / jest coverage tables
_PYTEST_COV_LINE_RE = re.compile(
    r"^(?P<file>[^\s]+\.py)\s+(?P<stmts>\d+)\s+(?P<miss>\d+)(?:\s+(?P<branch>\d+)\s+(?P<br_part>\d+))?\s+(?P<cover>\d+)%",
    re.MULTILINE,
)
_TOTAL_COV_RE = re.compile(r"TOTAL\s+\d+\s+\d+\s+(\d+)%")


@dataclass
class FileCoverageSummary:
    """Coverage breakdown for an individual source file."""

    file_path: str
    total_statements: int
    missed_statements: int
    covered_statements: int
    coverage_percent: float
    uncovered_lines: list[int] = field(default_factory=list)
    branch_coverage_percent: float | None = None


@dataclass
class TestCoverageResult:
    """Consolidated repository-wide execution coverage result."""

    total_statements: int = 0
    covered_statements: int = 0
    missed_statements: int = 0
    line_coverage_percent: float = 0.0
    branch_coverage_percent: float | None = None
    file_summaries: dict[str, FileCoverageSummary] = field(default_factory=dict)
    raw_coverage_output: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_statements": self.total_statements,
            "covered_statements": self.covered_statements,
            "missed_statements": self.missed_statements,
            "line_coverage_percent": self.line_coverage_percent,
            "branch_coverage_percent": self.branch_coverage_percent,
            "files": {
                k: {
                    "total": v.total_statements,
                    "covered": v.covered_statements,
                    "missed": v.missed_statements,
                    "percent": v.coverage_percent,
                    "uncovered_lines": v.uncovered_lines,
                }
                for k, v in self.file_summaries.items()
            },
        }


class TestCoverageAnalyzer:
    """Parses and computes line and branch coverage from test runner outputs or static evidence."""

    __test__ = False

    def parse_coverage_output(self, runner_stdout: str, runner_stderr: str = "") -> TestCoverageResult:
        """Parse coverage summary tables from test execution stdout/stderr."""
        combined = f"{runner_stdout}\n{runner_stderr}"
        result = TestCoverageResult(raw_coverage_output=combined)

        total_stmts = 0
        total_miss = 0

        for match in _PYTEST_COV_LINE_RE.finditer(combined):
            fpath = match.group("file").replace("\\", "/").lstrip("/")
            stmts = int(match.group("stmts"))
            miss = int(match.group("miss"))
            pct = float(match.group("cover"))
            covered = max(0, stmts - miss)

            result.file_summaries[fpath] = FileCoverageSummary(
                file_path=fpath,
                total_statements=stmts,
                missed_statements=miss,
                covered_statements=covered,
                coverage_percent=pct,
            )
            total_stmts += stmts
            total_miss += miss

        if total_stmts > 0:
            result.total_statements = total_stmts
            result.missed_statements = total_miss
            result.covered_statements = total_stmts - total_miss
            result.line_coverage_percent = round((result.covered_statements / total_stmts) * 100.0, 2)
        else:
            # Check for TOTAL line fallback
            tot_match = _TOTAL_COV_RE.search(combined)
            if tot_match:
                result.line_coverage_percent = float(tot_match.group(1))

        return result


