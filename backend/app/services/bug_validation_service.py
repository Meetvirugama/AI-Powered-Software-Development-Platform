"""Bug Validation and Counterevidence Verification Service.

Part of Phase 4: AI Investigation, Counterevidence Validation & Priority Scoring (task.md).
Implements independent counterevidence validation and assigns calibrated evidence levels:
- PROVEN: Deterministic static rule confirmation or reproducible test.
- STRONG: Multiple code relationships support defect; no protective guard found.
- SUSPECTED: Plausible logic defect hypothesized without multi-point corroboration.
- NEEDS_CONTEXT: Missing imports, external framework, or unindexed callers.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any, Sequence

logger = logging.getLogger(__name__)


@dataclass
class ValidationResult:
    """Outcome of counterevidence and guard validation."""
    evidence_level: str  # "PROVEN", "STRONG", "SUSPECTED", "NEEDS_CONTEXT"
    is_refuted: bool
    counterevidence: list[str] = field(default_factory=list)
    confidence: str = "medium"  # "high", "medium", "low"
    reproduction_status: str = "NOT_TESTED"
    validation_notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "evidence_level": self.evidence_level,
            "is_refuted": self.is_refuted,
            "counterevidence": self.counterevidence,
            "confidence": self.confidence,
            "reproduction_status": self.reproduction_status,
            "validation_notes": self.validation_notes,
        }


class BugValidationService:
    """Validates bug candidates against defensive guards, tests, and counterevidence."""

    def __init__(self) -> None:
        pass

    def validate_candidate(
        self,
        *,
        title: str,
        category: str,
        evidence: str,
        source_type: str,
        guards: Sequence[str] | None = None,
        sanitizers: Sequence[str] | None = None,
        associated_tests: Sequence[Any] | None = None,
        missing_context: Sequence[str] | None = None,
        has_dependency_trace: bool = False,
    ) -> ValidationResult:
        """Evaluate candidate against counterevidence and assign evidence level."""
        guards = guards or []
        sanitizers = sanitizers or []
        associated_tests = associated_tests or []
        missing_context = missing_context or []

        counterevidence: list[str] = []
        cat_lower = (category or "").lower()
        title_lower = (title or "").lower()
        ev_lower = (evidence or "").lower()

        # 1. Check for protective defensive guards (try/except, None checks, early returns)
        for g in guards:
            g_lower = g.lower()
            if "null" in cat_lower or "none" in title_lower:
                if any(k in g_lower for k in ("is none", "is not none", "== null", "=== null", "if not")):
                    counterevidence.append(f"Defensive guard detected in scope: `{g[:80]}`")
            if "exception" in cat_lower or "unhandled" in title_lower:
                if any(k in g_lower for k in ("try:", "except", "catch")):
                    counterevidence.append(f"Enclosing try/except block handles potential exception: `{g[:80]}`")

        # 2. Check for data-flow sanitizers
        for s in sanitizers:
            counterevidence.append(f"Sanitizer or typecast applied before sink: `{s}`")

        # 3. Check for associated tests covering this behavior
        if associated_tests:
            test_count = len(associated_tests)
            first_test = associated_tests[0]
            test_name = getattr(first_test, "test_symbol_name", "") or getattr(first_test, "test_file_path", "")
            counterevidence.append(f"Associated test suite detected ({test_count} tests, e.g. `{test_name}`)")

        # 4. Check for external/missing context dependency
        has_unindexed = len(missing_context) > 0

        # Refutation logic:
        # If defensive guard or sanitizer completely mitigates the candidate
        is_refuted = False
        if ("null" in cat_lower or "none" in title_lower) and any("guard detected" in c for c in counterevidence):
            is_refuted = True
        elif ("sql" in cat_lower or "injection" in title_lower) and sanitizers:
            is_refuted = True

        # Evidence level determination
        if is_refuted:
            evidence_level = "SUSPECTED"
            confidence = "low"
            notes = "Counterevidence indicates existing guard or sanitizer protects against this defect."
        elif has_unindexed and source_type == "AI":
            evidence_level = "NEEDS_CONTEXT"
            confidence = "low"
            notes = "External library or unindexed symbols prevent deterministic defect confirmation."
        elif source_type == "STATIC":
            # Deterministic AST / parser finding
            evidence_level = "PROVEN" if not counterevidence else "STRONG"
            confidence = "high"
            notes = "Verified by deterministic AST static analysis rule."
        elif source_type in ("TAINT", "COMBINED") or (source_type == "AI" and has_dependency_trace):
            evidence_level = "STRONG"
            confidence = "high" if not counterevidence else "medium"
            notes = "Corroborated by cross-file data flow or dependency trace without mitigating guard."
        else:
            evidence_level = "SUSPECTED"
            confidence = "medium"
            notes = "Heuristic AI finding requiring runtime or context verification."

        return ValidationResult(
            evidence_level=evidence_level,
            is_refuted=is_refuted,
            counterevidence=counterevidence,
            confidence=confidence,
            reproduction_status="NOT_TESTED",
            validation_notes=notes,
        )

