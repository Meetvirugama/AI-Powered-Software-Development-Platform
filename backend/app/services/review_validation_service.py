"""Finding Validation Service and Quality Gate for AI Code Review.

Enforces:
- Evidence sufficiency: Verifies that findings cite non-trivial code evidence.
- Evidence level gating: Classifies findings as PROVEN, STRONG, SUSPECTED, or NEEDS_CONTEXT.
- Changed-line policy: Distinguishes between changed lines (eligible for GitHub comments)
  and unchanged context lines (retained for platform Studio UI only).
- Confidence threshold evaluation: Configurable minimum confidence (HIGH, MEDIUM, LOW).
- Path traversal defense and source file existence checks.
- Two distinct output collections: Platform findings vs GitHub publishable findings.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import logging
from typing import Any, Optional
from uuid import UUID

from app.core.input_security import validate_repo_relative_path, UnsafePathError
from app.schemas.analysis import ReviewCategory, ReviewFinding

logger = logging.getLogger(__name__)


@dataclass
class QualityGateResult:
    """Categorized findings partitioned into platform-wide vs GitHub publishable."""

    platform_findings: list[dict[str, Any]]
    publishable_findings: list[dict[str, Any]]
    rejected_findings: list[dict[str, Any]]
    total_analyzed: int
    publishable_count: int
    rejected_count: int


class ReviewValidationService:
    """Validates code review findings and enforces precision quality gates."""

    __test__ = False

    CONFIDENCE_WEIGHTS = {"high": 3, "medium": 2, "low": 1}
    MIN_EVIDENCE_LENGTH = 10

    def validate_finding(
        self,
        finding: ReviewFinding | dict[str, Any],
        *,
        allowed_paths: Optional[set[str]] = None,
        file_line_counts: Optional[dict[str, int]] = None,
    ) -> tuple[bool, Optional[str]]:
        """Perform static syntactic and boundary validation on a single review finding."""
        f_dict = finding if isinstance(finding, dict) else finding.model_dump()

        src = f_dict.get("source_reference") or {}
        file_path = src.get("file_path") or f_dict.get("file_path")
        start_line = src.get("start_line") or f_dict.get("start_line")

        if not file_path:
            return False, "Missing file path"

        try:
            safe_path = validate_repo_relative_path(file_path)
        except UnsafePathError:
            return False, f"Unsafe file path rejected: {file_path}"

        if allowed_paths is not None and safe_path not in allowed_paths:
            return False, f"File path '{safe_path}' is not present in repository/diff scope"

        if start_line is not None:
            if not isinstance(start_line, int) or start_line <= 0:
                return False, f"Invalid start_line number: {start_line}"
            if file_line_counts and safe_path in file_line_counts:
                max_lines = file_line_counts[safe_path]
                # Allow generous boundary for diffs where added lines expand beyond base
                if max_lines > 0 and start_line > max_lines + 500:
                    return False, f"Line number {start_line} exceeds file length ({max_lines})"

        evidence = str(f_dict.get("evidence") or "").strip()
        if len(evidence) < self.MIN_EVIDENCE_LENGTH:
            return False, f"Insufficient evidence snippet (< {self.MIN_EVIDENCE_LENGTH} chars)"

        return True, None

    def assess_evidence_level(
        self,
        finding: ReviewFinding | dict[str, Any],
        is_changed_line: bool = True,
    ) -> str:
        """Assign evidence level: PROVEN, STRONG, SUSPECTED, or NEEDS_CONTEXT."""
        f_dict = finding if isinstance(finding, dict) else finding.model_dump()
        source_type = str(f_dict.get("source_type") or "AI").upper()
        confidence = str(f_dict.get("confidence") or "medium").lower()
        is_uncertain = bool(f_dict.get("is_uncertain", False))
        evidence = str(f_dict.get("evidence") or "").strip()

        if is_uncertain:
            return "NEEDS_CONTEXT"

        # Static analyzer rules with concrete line references are proven
        if source_type in ("STATIC", "COMBINED") and len(evidence) >= 20:
            return "PROVEN"

        if confidence == "high" and is_changed_line and len(evidence) >= 25:
            return "STRONG"

        if confidence in ("high", "medium"):
            return "STRONG" if is_changed_line else "SUSPECTED"

        return "SUSPECTED"

    def evaluate_quality_gate(
        self,
        findings: list[ReviewFinding | dict[str, Any]],
        *,
        changed_lines_by_file: Optional[dict[str, set[int]]] = None,
        allowed_paths: Optional[set[str]] = None,
        file_line_counts: Optional[dict[str, int]] = None,
        min_confidence: str = "medium",
        changed_lines_only: bool = True,
        max_publishable: int = 15,
    ) -> QualityGateResult:
        """Filter and partition findings into platform-visible and GitHub-publishable collections."""
        min_conf_val = self.CONFIDENCE_WEIGHTS.get(min_confidence.lower(), 2)

        platform_findings: list[dict[str, Any]] = []
        publishable_findings: list[dict[str, Any]] = []
        rejected_findings: list[dict[str, Any]] = []

        for f in findings:
            f_dict = f if isinstance(f, dict) else f.model_dump()

            is_valid, reason = self.validate_finding(
                f_dict,
                allowed_paths=allowed_paths,
                file_line_counts=file_line_counts,
            )
            if not is_valid:
                f_dict["rejection_reason"] = reason
                rejected_findings.append(f_dict)
                continue

            src = f_dict.get("source_reference") or {}
            file_path = src.get("file_path") or f_dict.get("file_path")
            line = src.get("start_line") or f_dict.get("start_line")

            # Determine whether finding is on a changed line
            is_changed = True
            if changed_lines_by_file is not None and file_path in changed_lines_by_file:
                is_changed = int(line or 0) in changed_lines_by_file[file_path]
            f_dict["is_changed_line"] = is_changed

            # Assign evidence level
            evidence_level = self.assess_evidence_level(f_dict, is_changed_line=is_changed)
            f_dict["evidence_level"] = evidence_level

            # Valid findings are always preserved for the platform UI
            platform_findings.append(f_dict)

            # Check publication criteria
            conf_val = self.CONFIDENCE_WEIGHTS.get(str(f_dict.get("confidence") or "medium").lower(), 1)
            is_eligible_for_publish = (
                evidence_level in ("PROVEN", "STRONG")
                and conf_val >= min_conf_val
                and (not changed_lines_only or is_changed)
                and len(publishable_findings) < max_publishable
            )

            if is_eligible_for_publish:
                publishable_findings.append(f_dict)

        return QualityGateResult(
            platform_findings=platform_findings,
            publishable_findings=publishable_findings,
            rejected_findings=rejected_findings,
            total_analyzed=len(findings),
            publishable_count=len(publishable_findings),
            rejected_count=len(rejected_findings),
        )
