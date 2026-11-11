"""Review Feedback Service for developer quality evaluation (AutoCommenter adaptation).

Collects and persists developer reactions:
- USEFUL: Helpful finding that caught a bug or improved code quality.
- NOT_USEFUL: Unhelpful or pedantic finding.
- FALSE_POSITIVE: Factually incorrect or hallucinated finding.
- ALREADY_FIXED: Issue was already addressed in source.
- DISMISSED: Developer intentionally chose not to fix.

Computes precision analytics:
- Acceptance rate = useful / total_voted
- False positive rate = false_positive / total_voted
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import logging
from typing import Any, Optional
from uuid import UUID

from sqlalchemy.orm import Session
from app.models.analysis_finding import AnalysisFinding
from app.models.analysis_run import AnalysisRun

logger = logging.getLogger(__name__)


VALID_FEEDBACK_TYPES = frozenset({"useful", "not_useful", "false_positive", "already_fixed", "dismissed"})


@dataclass
class FindingFeedbackRecord:
    finding_id: str
    feedback_type: str
    user_id: Optional[str] = None
    comment: Optional[str] = None
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> dict[str, Any]:
        return {
            "finding_id": self.finding_id,
            "feedback_type": self.feedback_type,
            "user_id": self.user_id,
            "comment": self.comment,
            "created_at": self.created_at,
        }


@dataclass
class ReviewFeedbackStats:
    total_feedback: int = 0
    useful_count: int = 0
    not_useful_count: int = 0
    false_positive_count: int = 0
    acceptance_rate: float = 0.0
    false_positive_rate: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_feedback": self.total_feedback,
            "useful_count": self.useful_count,
            "not_useful_count": self.not_useful_count,
            "false_positive_count": self.false_positive_count,
            "acceptance_rate": round(self.acceptance_rate, 4),
            "false_positive_rate": round(self.false_positive_rate, 4),
        }


class ReviewFeedbackService:
    """Manages developer feedback persistence and metrics calculation."""

    __test__ = False

    def record_feedback(
        self,
        db: Session,
        *,
        finding_id: UUID | str,
        feedback_type: str,
        user_id: Optional[UUID | str] = None,
        comment: Optional[str] = None,
    ) -> Optional[dict[str, Any]]:
        """Store or update developer feedback on an AnalysisFinding record."""
        clean_type = (feedback_type or "").strip().lower()
        if clean_type not in VALID_FEEDBACK_TYPES:
            raise ValueError(f"Invalid feedback_type '{feedback_type}'. Must be one of: {sorted(VALID_FEEDBACK_TYPES)}")

        # Convert to UUID if string
        f_uuid = UUID(str(finding_id)) if not isinstance(finding_id, UUID) else finding_id

        finding = db.query(AnalysisFinding).filter(AnalysisFinding.id == f_uuid).first()
        if not finding:
            return None

        from app.core.secret_redaction import redact

        meta = dict(finding.finding_metadata or {})
        feedback_entry = {
            "feedback_type": clean_type,
            "user_id": str(user_id) if user_id else None,
            "comment": redact(comment.strip()) if comment else None,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }

        meta["feedback"] = feedback_entry

        # If feedback is dismissed or false_positive, also update lifecycle status
        lifecycle = dict(meta.get("lifecycle") or {})
        if clean_type in ("false_positive", "dismissed"):
            lifecycle["status"] = "DISMISSED"
            lifecycle["dismissed_reason"] = clean_type
            meta["lifecycle"] = lifecycle

        finding.finding_metadata = meta
        db.commit()
        db.refresh(finding)

        logger.info(
            "finding_feedback_recorded",
            extra={"finding_id": str(finding_id), "type": clean_type},
        )
        return feedback_entry

    def compute_repository_feedback_stats(
        self,
        db: Session,
        repository_id: UUID | str,
    ) -> ReviewFeedbackStats:
        """Compute aggregate review feedback stats for a repository."""
        repo_uuid = UUID(str(repository_id)) if not isinstance(repository_id, UUID) else repository_id

        findings = (
            db.query(AnalysisFinding)
            .filter(AnalysisFinding.repository_id == repo_uuid)
            .all()
        )

        useful = 0
        not_useful = 0
        false_positive = 0

        for f in findings:
            meta = f.finding_metadata or {}
            fb = meta.get("feedback")
            if not fb or not isinstance(fb, dict):
                continue

            fb_type = fb.get("feedback_type")
            if fb_type == "useful":
                useful += 1
            elif fb_type == "not_useful":
                not_useful += 1
            elif fb_type == "false_positive":
                false_positive += 1

        total_voted = useful + not_useful + false_positive
        acc_rate = useful / total_voted if total_voted > 0 else 0.0
        fp_rate = false_positive / total_voted if total_voted > 0 else 0.0

        return ReviewFeedbackStats(
            total_feedback=total_voted,
            useful_count=useful,
            not_useful_count=not_useful,
            false_positive_count=false_positive,
            acceptance_rate=acc_rate,
            false_positive_rate=fp_rate,
        )
