"""Test Requirement Orchestration Engine.

Fulfills task.md §2, §5, §6 (Phase 5 & Phase 6 P0):
Coordinates repository-wide or targeted test requirement discovery, existing test
evidence mapping, coverage analysis, and gap prioritization across 3 modes:
1. Full Repository Mode
2. Targeted Mode
3. Change-Based Mode (with blast radius and regression focus)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence
from uuid import UUID

from sqlalchemy.orm import Session

from app.models.code_chunk import CodeChunk
from app.models.repository_file import RepositoryFile
from app.schemas.analysis import (
    TestGenerationRequest,
    TestQualityReport,
    TestRequirement,
)
from scanner.symbols import Symbol, SymbolEdge
from scanner.test_coverage_analyzer import TestCoverageAnalyzer, TestCoverageResult
from scanner.test_gap_analyzer import TestGapAnalyzer, TestGapAnalysisResult
from scanner.test_mapper import FileTestMapper, TestEvidenceLevel
from scanner.test_quality_analyzer import TestQualityAnalyzer
from scanner.test_requirement_discovery import TestRequirementDiscovery

logger = logging.getLogger(__name__)


@dataclass
class TestRequirementOrchestrationResult:
    """Consolidated outcome of the requirement discovery and gap analysis stage."""

    generation_mode: str
    target_files: list[str]
    total_requirements_count: int
    covered_requirements_count: int
    missing_requirements_count: int
    critical_missing_count: int
    requirement_coverage_percent: float
    requirements: list[TestRequirement]
    prioritized_gaps: list[TestRequirement]
    evidence_list: list[TestEvidenceLevel]
    quality_report: TestQualityReport | None = None
    coverage_result: TestCoverageResult | None = None


class TestRequirementOrchestrator:
    """Coordinates requirement discovery, test mapping, and gap analysis across repository modes."""

    __test__ = False

    def __init__(
        self,
        discovery: TestRequirementDiscovery | None = None,
        gap_analyzer: TestGapAnalyzer | None = None,
        coverage_analyzer: TestCoverageAnalyzer | None = None,
        quality_analyzer: TestQualityAnalyzer | None = None,
    ) -> None:
        self.gap_analyzer = gap_analyzer or TestGapAnalyzer()
        self.coverage_analyzer = coverage_analyzer or TestCoverageAnalyzer()
        self.quality_analyzer = quality_analyzer or TestQualityAnalyzer()

    def orchestrate_requirements(
        self,
        repository_id: UUID,
        payload: TestGenerationRequest,
        db: Session | Any,
        all_repo_files: Sequence[RepositoryFile],
        repo_symbols: Sequence[Symbol],
        repo_edges: Sequence[SymbolEdge],
        file_contents: Mapping[str, str] | None = None,
    ) -> TestRequirementOrchestrationResult:
        """Execute requirement discovery and gap analysis for the configured generation mode."""
        mode = payload.generation_mode or "targeted"
        contents = dict(file_contents or {})
        norm_file_map = {f.id: f.path.replace("\\", "/").lstrip("/") for f in all_repo_files if hasattr(f, "id")}

        # 1. Determine target files based on mode
        target_files: list[str] = []
        if mode == "full_repository":
            target_files = sorted({f.path.replace("\\", "/").lstrip("/") for f in all_repo_files})
        elif mode == "change_based":
            # Change-based uses payload.changed_files or falls back to target
            if payload.changed_files:
                target_files = [f.replace("\\", "/").lstrip("/") for f in payload.changed_files]
            else:
                target_files = [payload.target.path.replace("\\", "/").lstrip("/")]
        else:
            # Targeted mode
            target_files = [payload.target.path.replace("\\", "/").lstrip("/")]

        # 2. Discover requirements across target files
        discovery_engine = TestRequirementDiscovery(
            symbols=repo_symbols,
            edges=repo_edges,
            file_paths=norm_file_map,
        )

        discovered_reqs = discovery_engine.discover_requirements(
            target_files=target_files,
            file_contents=contents,
            focus_categories=payload.focus_categories if payload.focus_categories else None,
            changed_files=payload.changed_files if mode == "change_based" else None,
        )

        # 3. Map existing repository tests and discover multi-level evidence
        test_mapper = FileTestMapper(
            symbols=list(repo_symbols),
            edges=list(repo_edges),
            file_paths=norm_file_map,
        )
        _, evidence_list = test_mapper.map_tests_with_evidence(test_code_by_path=contents)

        # 4. Perform Gap Analysis
        gap_result = self.gap_analyzer.analyze_gaps(
            requirements=discovered_reqs,
            evidence_list=evidence_list,
            coverage_result=None,
        )

        # 5. Compute baseline quality report
        quality_report = self.quality_analyzer.compute_quality_report(
            requirements=gap_result.updated_requirements,
            test_code_map=contents,
            coverage_result=None,
            execution_passed=True,
        )

        return TestRequirementOrchestrationResult(
            generation_mode=mode,
            target_files=target_files,
            total_requirements_count=gap_result.total_requirements,
            covered_requirements_count=gap_result.covered_count,
            missing_requirements_count=gap_result.missing_count,
            critical_missing_count=gap_result.critical_missing_count,
            requirement_coverage_percent=gap_result.requirement_coverage_percent,
            requirements=gap_result.updated_requirements,
            prioritized_gaps=gap_result.prioritized_gaps,
            evidence_list=evidence_list,
            quality_report=quality_report,
        )

