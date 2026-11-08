"""Finding Lifecycle Service for tracking code review findings across commits.

Lifecycle States:
- NEW: First detected in the current commit.
- ACTIVE: Persists across subsequent commits.
- FIXED: Resolved by code changes and verified absent.
- REOPENED: Issue was previously marked FIXED but re-appears in a later commit.
- DISMISSED: Developer intentionally rejected or flagged as false positive.
- SUPPRESSED: Muted by repository-level rule.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)

VALID_LIFECYCLE_STATES = frozenset({"NEW", "ACTIVE", "FIXED", "REOPENED", "DISMISSED", "SUPPRESSED"})

ALLOWED_TRANSITIONS = {
    "NEW": {"ACTIVE", "FIXED", "DISMISSED", "SUPPRESSED"},
    "ACTIVE": {"FIXED", "DISMISSED", "SUPPRESSED"},
    "FIXED": {"REOPENED"},
    "REOPENED": {"ACTIVE", "FIXED", "DISMISSED"},
    "DISMISSED": {"REOPENED", "ACTIVE"},
    "SUPPRESSED": {"ACTIVE"},
}


class ReviewLifecycleService:
    """Manages state transitions and tracking for code review findings across commits."""

    __test__ = False

    def validate_transition(self, current_state: str, new_state: str) -> bool:
        """Validate whether a state transition is permitted by the state machine."""
        cur = current_state.upper()
        nxt = new_state.upper()
        if cur == nxt:
            return True
        allowed = ALLOWED_TRANSITIONS.get(cur, set())
        return nxt in allowed

    def update_lifecycle_for_finding(
        self,
        finding: dict[str, Any],
        new_state: str,
        commit_sha: Optional[str] = None,
        reason: Optional[str] = None,
    ) -> dict[str, Any]:
        """Update the lifecycle metadata dictionary for a finding."""
        meta = dict(finding.get("metadata") or finding.get("finding_metadata") or {})
        lifecycle = dict(meta.get("lifecycle") or {})

        current_state = str(lifecycle.get("status") or "NEW").upper()
        target_state = new_state.upper()

        if not self.validate_transition(current_state, target_state):
            logger.warning(
                "invalid_lifecycle_transition_ignored",
                extra={"from": current_state, "to": target_state},
            )
            return finding

        history = list(lifecycle.get("history") or [])
        history.append({
            "from": current_state,
            "to": target_state,
            "commit_sha": commit_sha,
            "reason": reason,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

        lifecycle["status"] = target_state
        if not lifecycle.get("first_detected_commit") and commit_sha:
            lifecycle["first_detected_commit"] = commit_sha
        if commit_sha:
            lifecycle["last_detected_commit"] = commit_sha
        if target_state == "FIXED" and commit_sha:
            lifecycle["fixed_in_commit"] = commit_sha

        lifecycle["history"] = history
        meta["lifecycle"] = lifecycle
        finding["finding_metadata"] = meta
        return finding

    def track_findings_across_commits(
        self,
        *,
        current_findings: list[dict[str, Any]],
        previous_findings: list[dict[str, Any]],
        current_commit_sha: str,
        is_complete_review: bool = True,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """Compare current findings against previous commit findings to compute lifecycle states.

        Returns:
            (updated_current_findings, resolved_previous_findings)
        """
        prev_by_fp: dict[str, dict[str, Any]] = {}
        for pf in previous_findings:
            fp = pf.get("deduplication_key")
            if fp:
                prev_by_fp[fp] = pf

        updated_current: list[dict[str, Any]] = []
        curr_seen_fps: set[str] = set()

        for cf in current_findings:
            fp = cf.get("deduplication_key")
            if not fp:
                updated_current.append(cf)
                continue

            curr_seen_fps.add(fp)

            if fp in prev_by_fp:
                prev = prev_by_fp[fp]
                prev_meta = prev.get("finding_metadata") or prev.get("metadata") or {}
                prev_life = dict(prev_meta.get("lifecycle") or {})
                cf_meta = dict(cf.get("finding_metadata") or cf.get("metadata") or {})
                cf_meta["lifecycle"] = prev_life
                cf["finding_metadata"] = cf_meta

                prev_status = str(prev_life.get("status") or "NEW").upper()
                if prev_status == "FIXED":
                    next_status = "REOPENED"
                    reason = "Defect re-detected in new commit"
                elif prev_status == "DISMISSED":
                    next_status = "DISMISSED"
                    reason = "Preserved dismissed status"
                else:
                    next_status = "ACTIVE"
                    reason = "Defect persists in subsequent commit"

                self.update_lifecycle_for_finding(cf, next_status, commit_sha=current_commit_sha, reason=reason)
            else:
                self.update_lifecycle_for_finding(cf, "NEW", commit_sha=current_commit_sha, reason="Initial detection")

            updated_current.append(cf)

        # Detect resolved findings: issues in previous run that are absent in current complete review
        resolved_findings: list[dict[str, Any]] = []
        if is_complete_review:
            for fp, prev in prev_by_fp.items():
                if fp not in curr_seen_fps:
                    prev_meta = prev.get("finding_metadata") or prev.get("metadata") or {}
                    prev_life = prev_meta.get("lifecycle") or {}
                    prev_status = str(prev_life.get("status") or "NEW").upper()

                    if prev_status not in ("FIXED", "DISMISSED"):
                        resolved_copy = dict(prev)
                        self.update_lifecycle_for_finding(
                            resolved_copy,
                            "FIXED",
                            commit_sha=current_commit_sha,
                            reason="Issue resolved by code changes",
                        )
                        resolved_findings.append(resolved_copy)

        return updated_current, resolved_findings
