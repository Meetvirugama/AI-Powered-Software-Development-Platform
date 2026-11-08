"""Multi-stage finding deduplication service for AI Code Review.

Features:
- Deterministic SHA-256 finding fingerprints resilient to line shifts.
- Intra-run deduplication: Merges overlapping static and AI findings into COMBINED.
- Pull Request comment deduplication: Prevents repeating comments already posted on PR.
- Cross-commit finding matching for lifecycle tracking.
"""

from __future__ import annotations

import hashlib
import logging
import re
from typing import Any, Optional
from uuid import UUID

from app.schemas.analysis import ReviewFinding

logger = logging.getLogger(__name__)


class ReviewDeduplicationService:
    """Manages finding fingerprints, intra-run merging, and PR comment deduplication."""

    __test__ = False

    SEVERITY_RANKS = {"CRITICAL": 5, "HIGH": 4, "MEDIUM": 3, "LOW": 2, "INFO": 1}
    CONFIDENCE_RANKS = {"high": 3, "medium": 2, "low": 1}

    def compute_fingerprint(
        self,
        finding: ReviewFinding | dict[str, Any],
        repository_id: Optional[UUID | str] = None,
    ) -> str:
        """Compute a deterministic SHA-256 fingerprint for a review finding.

        Key components:
        - normalized repo id
        - normalized file path
        - review category
        - rule_id or normalized title
        - symbol name (if any)
        - normalized evidence snippet (whitespace stripped)
        """
        f_dict = finding if isinstance(finding, dict) else finding.model_dump()

        src = f_dict.get("source_reference") or {}
        file_path = str(src.get("file_path") or f_dict.get("file_path") or "").strip().lower()
        category = str(f_dict.get("category") or "other").strip().lower()
        rule_id = str(f_dict.get("rule_id") or "").strip().lower()
        title = str(f_dict.get("title") or "").strip().lower()
        symbol = str(src.get("symbol_name") or f_dict.get("symbol_name") or "").strip().lower()
        evidence = str(f_dict.get("evidence") or "").strip()
        norm_evidence = re.sub(r"\s+", " ", evidence)[:120].lower()

        core_identifier = rule_id if rule_id and rule_id != "none" else title

        key_components = [
            str(repository_id or "").strip(),
            file_path,
            category,
            core_identifier,
            symbol,
            norm_evidence,
        ]

        raw_str = "|".join(key_components)
        return hashlib.sha256(raw_str.encode("utf-8")).hexdigest()

    def deduplicate_intra_run(
        self,
        findings: list[ReviewFinding | dict[str, Any]],
        repository_id: Optional[UUID | str] = None,
    ) -> list[dict[str, Any]]:
        """Deduplicate findings within a single run and merge overlapping STATIC and AI issues."""
        seen_fingerprints: set[str] = set()
        deduped: list[dict[str, Any]] = []

        for f in findings:
            f_dict = f if isinstance(f, dict) else f.model_dump()
            fp = self.compute_fingerprint(f_dict, repository_id=repository_id)
            f_dict["deduplication_key"] = fp

            if fp in seen_fingerprints:
                # Merge into existing item if one was already added
                for existing in deduped:
                    if existing.get("deduplication_key") == fp:
                        self._merge_finding_metadata(existing, f_dict)
                        break
                continue

            # Also check for near-duplicate: same file, same category, overlapping line range (+/- 2 lines)
            merged = False
            src = f_dict.get("source_reference") or {}
            f_file = src.get("file_path") or f_dict.get("file_path")
            f_line = src.get("start_line") or f_dict.get("start_line")
            f_cat = str(f_dict.get("category") or "").lower()

            if f_file and f_line:
                for existing in deduped:
                    e_src = existing.get("source_reference") or {}
                    e_file = e_src.get("file_path") or existing.get("file_path")
                    e_line = e_src.get("start_line") or existing.get("start_line")
                    e_cat = str(existing.get("category") or "").lower()

                    if (
                        e_file == f_file
                        and e_cat == f_cat
                        and e_line
                        and abs(int(e_line) - int(f_line)) <= 2
                        and self._is_same_root_cause(existing, f_dict)
                    ):
                        self._merge_finding_metadata(existing, f_dict)
                        merged = True
                        break

            if not merged:
                seen_fingerprints.add(fp)
                deduped.append(f_dict)

        return deduped

    def _is_same_root_cause(self, f1: dict[str, Any], f2: dict[str, Any]) -> bool:
        """Determine whether two nearby findings represent the same root cause defect."""
        rule1 = f1.get("rule_id") or (f1.get("finding_metadata") or {}).get("rule_id")
        rule2 = f2.get("rule_id") or (f2.get("finding_metadata") or {}).get("rule_id")
        if rule1 and rule2 and str(rule1).strip().lower() == str(rule2).strip().lower():
            return True

        src1 = f1.get("source_reference") or {}
        src2 = f2.get("source_reference") or {}
        sym1 = f1.get("target_symbol") or src1.get("target_symbol") or src1.get("symbol_name")
        sym2 = f2.get("target_symbol") or src2.get("target_symbol") or src2.get("symbol_name")
        if sym1 and sym2 and str(sym1).strip() == str(sym2).strip():
            return True

        # 3. Matching or overlapping evidence snippets
        ev1 = str(f1.get("evidence") or "").strip().lower()
        ev2 = str(f2.get("evidence") or "").strip().lower()
        if ev1 and ev2 and (ev1 == ev2 or ev1 in ev2 or ev2 in ev1):
            return True

        # 4. Normalized title / message similarity (substring or token overlap)
        t1 = str(f1.get("title") or f1.get("message") or "").strip().lower()
        t2 = str(f2.get("title") or f2.get("message") or "").strip().lower()
        if t1 and t2:
            if t1 == t2 or t1 in t2 or t2 in t1:
                return True
            tokens1 = set(t1.split())
            tokens2 = set(t2.split())
            if tokens1 and tokens2:
                overlap = len(tokens1 & tokens2) / max(len(tokens1), len(tokens2))
                if overlap >= 0.5:
                    return True

        return False

    def _merge_finding_metadata(self, base: dict[str, Any], incoming: dict[str, Any]) -> None:
        """Merge incoming finding into base finding, elevating severity and merging source types."""
        base_sev = str(base.get("severity") or "LOW").upper()
        inc_sev = str(incoming.get("severity") or "LOW").upper()
        if self.SEVERITY_RANKS.get(inc_sev, 1) > self.SEVERITY_RANKS.get(base_sev, 1):
            base["severity"] = inc_sev

        base_conf = str(base.get("confidence") or "medium").lower()
        inc_conf = str(incoming.get("confidence") or "medium").lower()
        if self.CONFIDENCE_RANKS.get(inc_conf, 1) > self.CONFIDENCE_RANKS.get(base_conf, 1):
            base["confidence"] = inc_conf

        # Combine source types
        b_type = str(base.get("source_type") or "AI").upper()
        i_type = str(incoming.get("source_type") or "AI").upper()
        if b_type != i_type:
            base["source_type"] = "COMBINED"

        # Combine suggested fix if base does not have one
        if not base.get("suggested_fix") and incoming.get("suggested_fix"):
            base["suggested_fix"] = incoming.get("suggested_fix")

    def filter_against_existing_pr_comments(
        self,
        candidate_comments: list[dict[str, Any]],
        existing_comments: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Filter out candidate inline comments that duplicate comments already on the PR."""
        if not existing_comments:
            return candidate_comments

        existing_anchors: set[tuple[str, int]] = set()
        for ec in existing_comments:
            p = ec.get("path")
            l = ec.get("line") or ec.get("original_line")
            if p and l:
                existing_anchors.add((str(p), int(l)))

        unique_candidates: list[dict[str, Any]] = []
        for c in candidate_comments:
            c_path = c.get("path")
            c_line = c.get("line")
            if c_path and c_line and (str(c_path), int(c_line)) in existing_anchors:
                logger.info(
                    "dedup_pr_comment_suppressed",
                    extra={"path": c_path, "line": c_line},
                )
                continue
            unique_candidates.append(c)

        return unique_candidates
