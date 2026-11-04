"""Test Generation & Quality Reporting Engine.

Fulfills task.md §6, §8, §10 (Phase 8 & 11 P1):
Generates structured summaries, markdown reports, and export payloads for
discovered requirements, generated suites, execution outcomes, and quality metrics.
"""

from __future__ import annotations

import json
from typing import Any

from app.schemas.analysis import (
    TestGenerationResult,
    TestQualityReport,
    TestRequirement,
)


def format_test_suite_report_markdown(result: TestGenerationResult) -> str:
    """Format a comprehensive markdown report for the generated test suite and requirements."""
    lines: list[str] = []
    lines.append("# Repository Test Intelligence & Generation Report\n")

    # Overview
    lines.append("## 1. Overview")
    lines.append(f"- **Detected Framework**: `{result.detected_framework}`")
    lines.append(f"- **Proposed Test Path**: `{result.proposed_test_path}`")
    lines.append(f"- **Syntax Valid**: `{'Yes' if result.syntax_valid else 'No'}`")
    lines.append(f"- **Execution Status**: `{result.execution_status}`")
    lines.append(f"- **Generated Scenarios**: {len(result.covered_scenarios)}")
    lines.append(f"- **Total Discovered Requirements**: {len(result.requirements)}")
    lines.append(f"- **Remaining Missing Requirements**: {len(result.missing_requirements)}\n")

    # Quality Scorecard
    if result.quality_report:
        qr = result.quality_report
        lines.append("## 2. Test Quality Scorecard")
        lines.append("| Metric | Measured Value | Target |")
        lines.append("| --- | --- | --- |")
        lines.append(
            f"| Requirement Coverage | {qr.requirement_coverage_percent if qr.requirement_coverage_percent is not None else 'N/A'}% | >= 80% |"
        )
        lines.append(
            f"| Line Coverage | {qr.line_coverage_percent if qr.line_coverage_percent is not None else 'N/A'}% | >= 75% |"
        )
        lines.append(
            f"| Branch Coverage | {qr.branch_coverage_percent if qr.branch_coverage_percent is not None else 'N/A'}% | >= 70% |"
        )
        lines.append(
            f"| Mutation Score | {qr.mutation_score_percent if qr.mutation_score_percent is not None else 'N/A'}% | >= 70% |"
        )
        lines.append(f"| Duplicate Tests | {qr.duplicate_test_count} | 0 |")
        lines.append(f"| Flaky Test Indicators | {qr.flaky_test_count} | 0 |")
        lines.append(f"| Weak Assertions | {qr.weak_assertion_count} | 0 |")
        lines.append(f"| Overall Quality Score | {qr.quality_score if qr.quality_score is not None else 'N/A'}/100 | >= 80 |\n")

        if qr.summary_notes:
            lines.append("### Quality Notes")
            for note in qr.summary_notes:
                lines.append(f"- {note}")
            lines.append("")

    # Requirement Matrix
    if result.requirements:
        lines.append("## 3. Discovered Test Requirement Matrix")
        lines.append("| ID | Category | Priority | Status | Title |")
        lines.append("| --- | --- | --- | --- | --- |")
        for req in result.requirements[:30]:  # Cap at top 30 in markdown view
            status_emoji = "✅" if req.status == "COVERED" else ("⚠️" if req.status == "PARTIAL" else "❌")
            lines.append(
                f"| `{req.requirement_id}` | {req.category} | {req.priority} | {status_emoji} {req.status} | {req.title} |"
            )
        lines.append("")

    # Assumptions & Warnings
    if result.assumptions_and_warnings:
        lines.append("## 4. Assumptions & Warnings")
        for w in result.assumptions_and_warnings:
            lines.append(f"- {w}")
        lines.append("")

    return "\n".join(lines)

