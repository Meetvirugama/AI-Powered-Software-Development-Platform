"""Bug Priority Calculation Service.

Part of Phase 4: AI Investigation, Counterevidence Validation & Priority Scoring (task.md).
Implements the multi-factor priority formula:
P = 0.35S + 0.25R + 0.20E + 0.10B + 0.10C
where:
- S: Severity (0-100)
- R: Reachability (0-100)
- E: Exploitability (0-100)
- B: Blast Radius (0-100)
- C: Evidence Confidence (0-100)
Separates severity from evidence confidence so that critical suspicions
are prioritized for investigation without being mislabeled as confirmed.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class PriorityBreakdown:
    """Detailed score breakdown for transparent ranking explanation."""
    priority_score: int
    severity_score: float
    reachability_score: float
    exploitability_score: float
    blast_radius_score: float
    confidence_score: float
    formula: str = "P = 0.35S + 0.25R + 0.20E + 0.10B + 0.10C"

    def to_dict(self) -> dict[str, Any]:
        return {
            "priority_score": self.priority_score,
            "severity_score": round(self.severity_score, 1),
            "reachability_score": round(self.reachability_score, 1),
            "exploitability_score": round(self.exploitability_score, 1),
            "blast_radius_score": round(self.blast_radius_score, 1),
            "confidence_score": round(self.confidence_score, 1),
            "formula": self.formula,
        }


class BugPriorityService:
    """Calculates multidimensional defect priority scores."""

    SEVERITY_WEIGHT = 0.35
    REACHABILITY_WEIGHT = 0.25
    EXPLOITABILITY_WEIGHT = 0.20
    BLAST_RADIUS_WEIGHT = 0.10
    CONFIDENCE_WEIGHT = 0.10

    SEVERITY_MAP = {
        "CRITICAL": 100.0,
        "HIGH": 75.0,
        "MEDIUM": 50.0,
        "LOW": 25.0,
        "INFO": 10.0,
    }

    CONFIDENCE_MAP = {
        "PROVEN": 100.0,
        "STRONG": 85.0,
        "high": 80.0,
        "SUSPECTED": 50.0,
        "medium": 50.0,
        "NEEDS_CONTEXT": 30.0,
        "low": 25.0,
    }

    def calculate_priority(
        self,
        *,
        severity: str,
        reachability: float | None = None,
        exploitability: float | None = None,
        blast_radius: float | None = None,
        confidence: str | None = None,
        evidence_level: str | None = None,
        has_callers: bool = False,
        is_security: bool = False,
        is_sanitized: bool = False,
        caller_count: int = 0,
    ) -> PriorityBreakdown:
        """Compute the weighted priority score normalized to [0, 100]."""
        # 1. Severity (S)
        sev_key = (severity or "MEDIUM").upper()
        s_score = self.SEVERITY_MAP.get(sev_key, 50.0)

        # 2. Reachability (R)
        if reachability is not None:
            r_score = float(max(0, min(100, reachability)))
        else:
            if caller_count > 5:
                r_score = 90.0
            elif caller_count > 0 or has_callers:
                r_score = 75.0
            else:
                r_score = 50.0

        # 3. Exploitability (E)
        if exploitability is not None:
            e_score = float(max(0, min(100, exploitability)))
        else:
            if is_security:
                e_score = 25.0 if is_sanitized else 90.0
            else:
                e_score = 60.0

        # 4. Blast Radius (B)
        if blast_radius is not None:
            b_score = float(max(0, min(100, blast_radius)))
        else:
            if caller_count >= 10:
                b_score = 100.0
            elif caller_count >= 5:
                b_score = 80.0
            elif caller_count >= 2:
                b_score = 50.0
            else:
                b_score = 30.0

        # 5. Evidence Confidence (C)
        if evidence_level and evidence_level in self.CONFIDENCE_MAP:
            c_score = self.CONFIDENCE_MAP[evidence_level]
        elif confidence and confidence in self.CONFIDENCE_MAP:
            c_score = self.CONFIDENCE_MAP[confidence]
        else:
            c_score = 50.0

        # Weighted composite score
        composite = (
            self.SEVERITY_WEIGHT * s_score
            + self.REACHABILITY_WEIGHT * r_score
            + self.EXPLOITABILITY_WEIGHT * e_score
            + self.BLAST_RADIUS_WEIGHT * b_score
            + self.CONFIDENCE_WEIGHT * c_score
        )

        final_score = int(round(max(0.0, min(100.0, composite))))

        return PriorityBreakdown(
            priority_score=final_score,
            severity_score=s_score,
            reachability_score=r_score,
            exploitability_score=e_score,
            blast_radius_score=b_score,
            confidence_score=c_score,
        )

