"""Bug Finding Validator — Verifies Structured AI Findings and Enforces Grounding.

Part of Phase 4: AI Investigation, Counterevidence Validation & Priority Scoring (task.md).
Ensures:
- Valid file paths and line ranges within target boundaries.
- No hallucinated symbol references or phantom file paths.
- Secret redaction on evidence and descriptions.
- Consistent schema validation and sanitization.
"""

from __future__ import annotations

import logging
from typing import Any, Sequence

from app.core.secret_redaction import redact
from app.schemas.analysis import BugFinding

logger = logging.getLogger(__name__)


class BugFindingValidator:
    """Validates, sanitizes, and grounds AI-generated bug findings against repository context."""

    def __init__(self) -> None:
        pass

    def validate_and_sanitize(
        self,
        finding: BugFinding,
        *,
        target_file_path: str,
        total_lines: int | None = None,
        known_files: Sequence[str] | None = None,
    ) -> BugFinding | None:
        """Validate line boundaries, ground paths, and redact secrets."""
        # 1. Ground source file path
        source_ref = finding.source_reference
        if source_ref.file_path != target_file_path:
            # If AI reported relative or variant path, ground it to known target
            if known_files and source_ref.file_path not in known_files:
                source_ref.file_path = target_file_path

        # 2. Check line range sanity
        if total_lines and total_lines > 0:
            if source_ref.start_line > total_lines:
                source_ref.start_line = total_lines
            if source_ref.end_line > total_lines:
                source_ref.end_line = total_lines
        if source_ref.start_line < 1:
            source_ref.start_line = 1
        if source_ref.end_line < source_ref.start_line:
            source_ref.end_line = source_ref.start_line

        # 3. Redact secrets in description and evidence
        redacted_desc = redact(finding.description or "")
        redacted_ev = redact(finding.evidence or "")
        redacted_title = redact(finding.title or "")
        redacted_fix = redact(finding.suggested_fix or "") if finding.suggested_fix else None

        finding.description = redacted_desc
        finding.evidence = redacted_ev
        finding.title = redacted_title
        finding.suggested_fix = redacted_fix

        return finding

    def filter_hallucinated_findings(
        self,
        findings: list[BugFinding],
        known_files: Sequence[str],
    ) -> list[BugFinding]:
        """Strip findings pointing to nonexistent phantom files."""
        if not known_files:
            return findings

        valid: list[BugFinding] = []
        file_set = set(known_files)
        for f in findings:
            if f.source_reference.file_path in file_set:
                valid.append(f)
            else:
                logger.warning(
                    "Dropping ungrounded AI bug finding pointing to '%s'",
                    f.source_reference.file_path,
                )
        return valid

