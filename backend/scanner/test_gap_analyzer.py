"""Test Requirement Matrix & Gap Analysis Engine.

Fulfills task.md §2, §4, §5 (Phase 4 P0):
Compares discovered test requirements against existing test mappings and coverage
evidence, categorizing each into COVERED, PARTIAL, MISSING, BLOCKED, or NOT_APPLICABLE.
Prioritizes testing gaps by criticality, security risk, and regression impact.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from app.schemas.analysis import (
    TestRequirement,
    TestRequirementStatus,
)

from scanner.test_coverage_analyzer import TestCoverageResult
from scanner.test_mapper import TestEvidenceLevel

logger = logging.getLogger(__name__)


@dataclass
class TestGapAnalysisResult:
    """Consolidated summary of test requirement coverage and remaining gaps."""

    total_requirements: int = 0
    covered_count: int = 0
    partial_count: int = 0
    missing_count: int = 0
    blocked_count: int = 0
    not_applicable_count: int = 0
    critical_missing_count: int = 0
    requirement_coverage_percent: float = 0.0
    prioritized_gaps: list[TestRequirement] = field(default_factory=list)
    updated_requirements: list[TestRequirement] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_requirements": self.total_requirements,
            "covered_count": self.covered_count,
            "partial_count": self.partial_count,
            "missing_count": self.missing_count,
            "blocked_count": self.blocked_count,
            "not_applicable_count": self.not_applicable_count,
            "critical_missing_count": self.critical_missing_count,
            "requirement_coverage_percent": self.requirement_coverage_percent,
            "prioritized_gaps_count": len(self.prioritized_gaps),
        }


class TestGapAnalyzer:
    """Analyzes test requirements against repository evidence to compute coverage gaps."""

    __test__ = False

    def analyze_gaps(
        self,
        requirements: Sequence[TestRequirement],
        evidence_list: Sequence[TestEvidenceLevel] | None = None,
        coverage_result: TestCoverageResult | None = None,
    ) -> TestGapAnalysisResult:
        """Evaluate each requirement against available test evidence and compute matrix stats."""
        evidence = list(evidence_list or [])
        updated_reqs: list[TestRequirement] = []

        # Index evidence by source file and source symbol
        evidence_by_file: dict[str, list[TestEvidenceLevel]] = {}
        evidence_by_symbol: dict[str, list[TestEvidenceLevel]] = {}

        for ev in evidence:
            s_file = ev.source_file.replace("\\", "/").lstrip("/")
            evidence_by_file.setdefault(s_file, []).append(ev)
            if ev.source_symbol:
                evidence_by_symbol.setdefault(ev.source_symbol, []).append(ev)

        covered = 0
        partial = 0
        missing = 0
        blocked = 0
        na = 0
        critical_missing = 0
        prioritized_gaps: list[TestRequirement] = []

        for req in requirements:
            # Check if explicitly marked not applicable
            if req.status == "NOT_APPLICABLE":
                na += 1
                updated_reqs.append(req)
                continue

            if req.status == "BLOCKED":
                blocked += 1
                updated_reqs.append(req)
                continue

            status, matched_ev, note = self._evaluate_requirement_status(
                req,
                evidence_by_file,
                evidence_by_symbol,
                coverage_result,
            )

            # Create updated requirement copy with evaluated status
            req_data = req.model_dump()
            req_data["status"] = status
            if matched_ev:
                current_ev = list(req_data.get("evidence", []))
                for me in matched_ev:
                    desc = f"Verified by {me.evidence_type} in {me.test_file}"
                    if desc not in current_ev:
                        current_ev.append(desc)
                req_data["evidence"] = current_ev

            if note and not req_data.get("reason"):
                req_data["reason"] = note

            updated_req = TestRequirement.model_validate(req_data)
            updated_reqs.append(updated_req)

            if status == "COVERED":
                covered += 1
            elif status == "PARTIAL":
                partial += 1
                prioritized_gaps.append(updated_req)
                if str(updated_req.priority).upper() in ("CRITICAL", "HIGH"):
                    critical_missing += 1
            elif status == "MISSING":
                missing += 1
                prioritized_gaps.append(updated_req)
                if str(updated_req.priority).upper() in ("CRITICAL", "HIGH"):
                    critical_missing += 1

        total = len(requirements)
        applicable_total = total - na
        coverage_pct = 0.0
        if applicable_total > 0:
            # Give full weight for COVERED, 0.5 weight for PARTIAL
            effective_covered = covered + (partial * 0.5)
            coverage_pct = round((effective_covered / applicable_total) * 100.0, 1)

        # Sort prioritized gaps: CRITICAL first, then HIGH, then MEDIUM, then LOW
        priority_weights = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}
        prioritized_gaps.sort(
            key=lambda r: (
                priority_weights.get(str(r.priority).upper(), 4),
                0 if r.status == "MISSING" else 1,
                r.requirement_id,
            )
        )

        return TestGapAnalysisResult(
            total_requirements=total,
            covered_count=covered,
            partial_count=partial,
            missing_count=missing,
            blocked_count=blocked,
            not_applicable_count=na,
            critical_missing_count=critical_missing,
            requirement_coverage_percent=coverage_pct,
            prioritized_gaps=prioritized_gaps,
            updated_requirements=updated_reqs,
        )

    def _evaluate_requirement_status(
        self,
        req: TestRequirement,
        evidence_by_file: dict[str, list[TestEvidenceLevel]],
        evidence_by_symbol: dict[str, list[TestEvidenceLevel]],
        coverage_result: TestCoverageResult | None,
    ) -> tuple[TestRequirementStatus, list[TestEvidenceLevel], str | None]:
        """Determine whether requirement is COVERED, PARTIAL, or MISSING based on multi-level evidence."""
        matched_evidence: list[TestEvidenceLevel] = []

        # Find matching evidence for symbols or files
        if req.source_symbols:
            for sym in req.source_symbols:
                sym_ev = evidence_by_symbol.get(sym, [])
                matched_evidence.extend(sym_ev)
        elif req.source_files:
            for s_file in req.source_files:
                norm_f = s_file.replace("\\", "/").lstrip("/")
                file_ev = evidence_by_file.get(norm_f, [])
                for fe in file_ev:
                    if fe not in matched_evidence:
                        matched_evidence.append(fe)

        if not matched_evidence:
            return "MISSING", [], "No existing tests found covering this requirement"

        has_assertion = any(e.evidence_type in ("assertion", "mutation") for e in matched_evidence)
        has_call = any(e.evidence_type == "call" for e in matched_evidence)
        has_import = any(e.evidence_type == "import" for e in matched_evidence)

        # Category-aware coverage verification
        req_cat = str(req.category).lower()
        cat_keywords: dict[str, tuple[str, ...]] = {
            "security": ("security", "injection", "tamper", "auth", "unauth", "secret", "token", "forbid"),
            "negative": ("invalid", "reject", "malformed", "negative", "fail", "bad"),
            "exception_handling": ("raises", "exception", "error", "catch", "throw"),
            "boundary": ("empty", "zero", "null", "none", "boundary", "bound", "max", "min", "overflow"),
            "integration": ("db", "database", "http", "api", "redis", "client", "service"),
            "concurrency": ("async", "race", "concurrent", "lock", "thread"),
            "regression": ("fixme", "bug", "regression", "defect", "todo"),
        }

        # Check if any assertion matches requirement category
        has_category_assertion = False
        if req_cat in cat_keywords:
            keywords = cat_keywords[req_cat]
            for e in matched_evidence:
                t_desc = f"{e.test_symbol or ''} {e.description}".lower()
                if e.evidence_type in ("assertion", "mutation") and any(k in t_desc for k in keywords):
                    has_category_assertion = True
                    break
        elif has_assertion:
            # Functional or standard categories are covered by direct assertions
            has_category_assertion = True

        # Requirement criteria:
        # A test specifically asserts expected outcome for this category -> COVERED
        if has_category_assertion:
            return "COVERED", matched_evidence, f"Verified by behavioural assertions for {req_cat}"

        # Test exists for the symbol but doesn't cover this specific specialized category -> PARTIAL
        if has_assertion or has_call:
            return "PARTIAL", matched_evidence, f"Symbol tested in suite, but specific {req_cat} scenario remains untested"

        # Test only imports module -> PARTIAL / WEAK
        if has_import:
            return "PARTIAL", matched_evidence, "Module imported in test suite but direct invocation unverified"

        return "MISSING", [], "No existing tests found covering this requirement"
