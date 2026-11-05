"""Repository-Aware AI Bug Investigator.

Part of Phase 4: AI Investigation, Counterevidence Validation & Priority Scoring (task.md).
Coordinates the two-pass investigation process:
Pass 1: Structured investigation packet reasoning over target and dependency slice.
Pass 2: Counterevidence and defensive guard verification to prevent false positives.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass, field

from app.schemas.analysis import AnalysisSourceReference, BugDetectionRequest, BugFinding
from app.services.bug_candidate_discovery import BugCandidate
from app.services.bug_graph_context_service import BugGraphSlice
from app.services.bug_priority_service import BugPriorityService
from app.services.bug_validation_service import BugValidationService

from ai.context.builder import IntelligenceContext
from ai.services.bug_detection_engine import BugDetectionEngine
from ai.services.bug_finding_validator import BugFindingValidator

logger = logging.getLogger(__name__)


@dataclass
class InvestigationPacket:
    """Bounded packet prepared for AI bug investigation."""
    candidate: BugCandidate | None
    target_code: str
    target_file_path: str
    start_line: int
    end_line: int
    dependency_trace: list[str] = field(default_factory=list)
    counterevidence_points: list[str] = field(default_factory=list)
    associated_tests: list[str] = field(default_factory=list)
    repository_rules: list[str] = field(default_factory=list)


class BugInvestigator:
    """Conducts two-pass investigation combining LLM reasoning with repository counterevidence."""

    def __init__(
        self,
        engine: BugDetectionEngine | None = None,
        validator: BugFindingValidator | None = None,
        validation_service: BugValidationService | None = None,
        priority_service: BugPriorityService | None = None,
    ) -> None:
        self.engine = engine
        self.validator = validator or BugFindingValidator()
        self.validation_service = validation_service or BugValidationService()
        self.priority_service = priority_service or BugPriorityService()

    def build_investigation_packet(
        self,
        *,
        candidate: BugCandidate | None,
        target_code: str,
        target_file_path: str,
        start_line: int,
        end_line: int,
        program_slice: BugGraphSlice | None = None,
        guards: Sequence[str] | None = None,
        rules: Sequence[str] | None = None,
    ) -> InvestigationPacket:
        """Assemble structured investigation packet bounded by repository slice."""
        trace = program_slice.dependency_trace if program_slice else []
        test_names = [t.test_symbol_name for t in (program_slice.associated_tests if program_slice else [])]
        counter = list(guards or [])

        return InvestigationPacket(
            candidate=candidate,
            target_code=target_code,
            target_file_path=target_file_path,
            start_line=start_line,
            end_line=end_line,
            dependency_trace=trace,
            counterevidence_points=counter,
            associated_tests=test_names,
            repository_rules=list(rules or []),
        )

    async def investigate_and_verify(
        self,
        *,
        request: BugDetectionRequest,
        context: IntelligenceContext,
        program_slice: BugGraphSlice | None = None,
        guards: Sequence[str] | None = None,
        candidates: Sequence[BugCandidate] | None = None,
    ) -> list[BugFinding]:
        """Execute two-pass investigation and return calibrated BugFindings."""
        raw_findings: list[BugFinding] = []

        # Pass 1: AI Reasoner (via BugDetectionEngine if available and requested)
        if request.include_ai and self.engine:
            try:
                raw_findings = await self.engine.detect_bugs(request, context)
            except Exception as e:
                logger.warning("AI Bug Detection pass failed or skipped: %s", e)

        # Convert high-confidence static/taint candidates if AI didn't catch them
        if candidates:
            existing_lines = {f.source_reference.start_line for f in raw_findings}
            for c in candidates:
                if c.start_line not in existing_lines and c.severity in ("CRITICAL", "HIGH"):
                    mapped_source_type = "STATIC" if c.source_type in ("STATIC", "TAINT", "CONFIG", "CHANGE_RISK") else "COMBINED"
                    raw_findings.append(
                        BugFinding(
                            id=c.candidate_id,
                            category=c.category,
                            severity=c.severity,  # type: ignore[arg-type]
                            title=c.evidence.splitlines()[0][:100],
                            description=c.evidence,
                            source_reference=AnalysisSourceReference(
                                file_path=c.file_path,
                                start_line=c.start_line,
                                end_line=c.end_line,
                            ),
                            evidence=c.evidence,
                            suggested_fix=c.remediation or "Address identified defect pattern.",
                            confidence=c.confidence,  # type: ignore[arg-type]
                            source_type=mapped_source_type,  # type: ignore[arg-type]
                            rule_id=c.rule_id,
                        )
                    )

        # Pass 2: Counterevidence Validation and Priority Calibration
        validated_findings: list[BugFinding] = []
        dep_trace = program_slice.dependency_trace if program_slice else []
        associated_tests = program_slice.associated_tests if program_slice else []

        for f in raw_findings:
            # 1. Validate & Sanitize boundaries
            sanitized = self.validator.validate_and_sanitize(
                f,
                target_file_path=context.target.file_path,
                total_lines=None,
            )
            if not sanitized:
                continue

            # 2. Counterevidence Verification
            val_result = self.validation_service.validate_candidate(
                title=sanitized.title,
                category=str(sanitized.category),
                evidence=sanitized.evidence,
                source_type=str(sanitized.source_type),
                guards=guards or [],
                associated_tests=associated_tests,
                missing_context=[m.file_path for m in context.missing_context] if hasattr(context, "missing_context") else [],
                has_dependency_trace=bool(dep_trace),
            )

            # Assign evidence level and counterevidence
            sanitized.evidence_level = val_result.evidence_level
            sanitized.counterevidence = val_result.counterevidence
            sanitized.dependency_trace = dep_trace

            # 3. Priority Score Calculation
            is_sec = str(sanitized.category).lower() == "security"
            priority = self.priority_service.calculate_priority(
                severity=str(sanitized.severity),
                evidence_level=sanitized.evidence_level,
                confidence=str(sanitized.confidence),
                has_callers=bool(dep_trace),
                is_security=is_sec,
                is_sanitized=val_result.is_refuted,
                caller_count=len(dep_trace),
            )
            sanitized.priority_score = priority.priority_score

            # If not completely refuted, include in findings
            if not val_result.is_refuted or sanitized.severity != "CRITICAL":
                validated_findings.append(sanitized)

        return validated_findings
