"""Core AnalysisRun creation, retrieval, finding attachment, and summary aggregate."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, List, Optional, Sequence, Tuple

from sqlalchemy import delete, func, select
from sqlalchemy.orm import selectinload

from app.models.analysis_finding import AnalysisFinding
from app.models.analysis_run import AnalysisRun, AnalysisRunStatus
from app.repositories.analysis.base import (
    AnalysisRepositoryBase,
    _ensure_datetime,
    _ensure_uuid,
    scrub_sensitive_data,
    scrub_sensitive_text,
)


class AnalysisCoreMixin(AnalysisRepositoryBase):
    """Core analysis run and finding query/lifecycle methods."""

    def create_run(
        self,
        *,
        id: Optional[uuid.UUID | str] = None,
        repository_id: uuid.UUID | str,
        user_id: Optional[uuid.UUID | str] = None,
        feature_type: str,
        status: str = AnalysisRunStatus.PENDING.value,
        target_path: Optional[str] = None,
        target_symbol: Optional[str] = None,
        start_line: Optional[int] = None,
        end_line: Optional[int] = None,
        source_revision: Optional[str] = None,
        findings_count: int = 0,
        result_payload: Optional[dict[str, Any]] = None,
        test_output: Optional[str] = None,
        findings: Optional[Sequence[Any]] = None,
        error_message: Optional[str] = None,
        created_at: Optional[datetime | str] = None,
        completed_at: Optional[datetime | str] = None,
        **extra_kwargs: Any,
    ) -> AnalysisRun:
        """Create and persist an AnalysisRun, optionally with associated findings.

        Accepts both dict kwargs and explicit parameters.
        Handles UUID/datetime coercion and extracts test_output from result_payload if present.
        """
        run_uuid = _ensure_uuid(id) or uuid.uuid4()
        repo_uuid = _ensure_uuid(repository_id)
        if repo_uuid is None:
            raise ValueError(f"Invalid repository_id: {repository_id}")

        user_uuid = _ensure_uuid(user_id)
        if user_uuid is not None:
            from app.models.user import User
            try:
                if self.session.get(User, user_uuid) is None:
                    user_uuid = None
            except Exception:
                pass
        created_dt = _ensure_datetime(created_at) or datetime.now(timezone.utc)
        completed_dt = _ensure_datetime(completed_at)

        # If completed or failed status and completed_at is None, set to now
        if completed_dt is None and status in (
            AnalysisRunStatus.COMPLETED.value,
            AnalysisRunStatus.FAILED.value,
            AnalysisRunStatus.CANCELLED.value,
        ):
            completed_dt = datetime.now(timezone.utc)

        # Extract large test outputs if passed in payload or kwargs (top-level or nested under "result")
        if test_output is None and isinstance(result_payload, dict):
            test_output = (
                result_payload.get("test_content")
                or result_payload.get("complete_test_code")
                or result_payload.get("test_output")
                or (
                    result_payload.get("result", {}).get("test_content")
                    if isinstance(result_payload.get("result"), dict)
                    else None
                )
            )
            if test_output is None and isinstance(result_payload.get("result"), dict):
                test_output = (
                    result_payload["result"].get("test_content")
                    or result_payload["result"].get("complete_test_code")
                    or result_payload["result"].get("test_output")
                )

        # Scrub credentials and sensitive tokens from persisted fields (Week 2 — Day 7)
        error_message = scrub_sensitive_text(error_message)
        test_output = scrub_sensitive_text(test_output)
        if result_payload is not None:
            result_payload = scrub_sensitive_data(result_payload)

        # Normalize feature_type and status strings
        feat_val = feature_type.value if hasattr(feature_type, "value") else str(feature_type)
        status_val = status.value if hasattr(status, "value") else str(status)

        finding_items = list(findings or [])
        calculated_findings_count = findings_count or len(finding_items)

        existing_run = self.session.get(AnalysisRun, run_uuid)
        if existing_run is not None:
            existing_run.status = status_val
            existing_run.findings_count = calculated_findings_count
            if result_payload is not None:
                existing_run.result_payload = result_payload
            if test_output is not None:
                existing_run.test_output = test_output
            if error_message is not None:
                existing_run.error_message = error_message
            if completed_dt is not None:
                existing_run.completed_at = completed_dt
            if finding_items:
                for item in finding_items:
                    self._attach_finding_to_run(existing_run, item)
            self.session.commit()
            self.session.refresh(existing_run)
            return existing_run

        run = AnalysisRun(
            id=run_uuid,
            repository_id=repo_uuid,
            user_id=user_uuid,
            feature_type=feat_val,
            status=status_val,
            target_path=target_path,
            target_symbol=target_symbol,
            start_line=start_line,
            end_line=end_line,
            source_revision=source_revision,
            findings_count=calculated_findings_count,
            result_payload=result_payload,
            test_output=test_output,
            error_message=error_message,
            created_at=created_dt,
            completed_at=completed_dt,
        )

        self.session.add(run)

        # Persist associated structured findings
        if finding_items:
            for item in finding_items:
                self._attach_finding_to_run(run, item)

        self.session.commit()
        self.session.refresh(run)
        return run

    def _attach_finding_to_run(self, run: AnalysisRun, item: Any) -> AnalysisFinding:
        """Helper to coerce a dict or Pydantic finding into an AnalysisFinding model with secret scrubbing."""
        if isinstance(item, AnalysisFinding):
            item.analysis_run_id = run.id
            item.repository_id = run.repository_id
            item.title = scrub_sensitive_text(item.title) or "Finding"
            item.description = scrub_sensitive_text(item.description) or ""
            item.evidence = scrub_sensitive_text(item.evidence) or ""
            if item.suggested_fix:
                item.suggested_fix = scrub_sensitive_text(item.suggested_fix)
            meta = dict(item.finding_metadata or {})
            if "provenance" not in meta:
                st = str(item.source_type or "AI").upper()
                meta["provenance"] = "static_rule" if st == "STATIC" else ("combined" if st == "COMBINED" else "llm")
            if "evidence_hash" not in meta and item.evidence:
                import hashlib
                meta["evidence_hash"] = hashlib.sha256(item.evidence.strip().encode("utf-8")).hexdigest()[:16]
            if "deduplication_key" not in meta:
                cat = str(item.category or "general").lower()
                r_id = item.rule_id or "none"
                meta["deduplication_key"] = f"{item.file_path}:{item.start_line or 0}-{item.end_line or 0}:{cat}:{r_id}"
            item.finding_metadata = scrub_sensitive_data(meta)
            self.session.add(item)
            return item

        # Extract dictionary
        raw: dict[str, Any] = {}
        if hasattr(item, "model_dump"):
            raw = item.model_dump()
        elif hasattr(item, "dict"):
            raw = item.dict()
        elif isinstance(item, dict):
            raw = dict(item)

        finding_uuid = _ensure_uuid(raw.get("id")) or uuid.uuid4()
        source_ref = raw.get("source_reference") or {}
        if hasattr(source_ref, "model_dump"):
            source_ref = source_ref.model_dump()
        elif hasattr(source_ref, "dict"):
            source_ref = source_ref.dict()
        elif not isinstance(source_ref, dict):
            source_ref = {}

        file_path = raw.get("file_path") or source_ref.get("file_path") or run.target_path or "unknown"
        start_line = raw.get("start_line") if "start_line" in raw else source_ref.get("start_line")
        end_line = raw.get("end_line") if "end_line" in raw else source_ref.get("end_line")
        rev = raw.get("source_revision") or source_ref.get("revision") or run.source_revision
        sym = raw.get("symbol_name") or source_ref.get("symbol_name") or run.target_symbol

        raw_meta = dict(raw.get("metadata") or raw.get("finding_metadata") or {})
        for field_name in ("provenance", "deduplication_key", "evidence_hash", "rule_version", "model_version"):
            if field_name in raw and field_name not in raw_meta and raw[field_name] is not None:
                raw_meta[field_name] = raw[field_name]

        if "provenance" not in raw_meta:
            st = str(raw.get("source_type", "AI")).upper()
            raw_meta["provenance"] = "static_rule" if st == "STATIC" else ("combined" if st == "COMBINED" else "llm")
        if "evidence_hash" not in raw_meta and raw.get("evidence"):
            import hashlib
            raw_meta["evidence_hash"] = hashlib.sha256(str(raw["evidence"]).strip().encode("utf-8")).hexdigest()[:16]
        if "deduplication_key" not in raw_meta:
            cat = str(raw.get("category", "general")).lower()
            r_id = raw.get("rule_id") or "none"
            raw_meta["deduplication_key"] = f"{file_path}:{start_line or 0}-{end_line or 0}:{cat}:{r_id}"

        finding = AnalysisFinding(
            id=finding_uuid,
            analysis_run_id=run.id,
            repository_id=run.repository_id,
            category=str(raw.get("category", "general")),
            severity=str(raw.get("severity", "MEDIUM")).upper(),
            title=scrub_sensitive_text(str(raw.get("title", "Finding"))) or "Finding",
            description=scrub_sensitive_text(str(raw.get("description", ""))) or "",
            file_path=file_path,
            start_line=start_line,
            end_line=end_line,
            source_revision=rev,
            symbol_name=sym,
            evidence=scrub_sensitive_text(str(raw.get("evidence", ""))) or "",
            suggested_fix=scrub_sensitive_text(raw.get("suggested_fix")) if raw.get("suggested_fix") else None,
            confidence=str(raw.get("confidence", "medium")),
            is_uncertain=bool(raw.get("is_uncertain", False)),
            is_new_in_change=bool(raw.get("is_new_in_change", True)),
            source_type=str(raw.get("source_type", "AI")),
            rule_id=raw.get("rule_id"),
            finding_metadata=scrub_sensitive_data(raw_meta) if raw_meta else None,
        )
        self.session.add(finding)
        return finding

    def _deduplicate_findings_data(self, findings: Sequence[Any]) -> list[dict[str, Any]]:
        """Deduplicate findings before persistence, combining STATIC and AI findings where appropriate.

        Owner: Om — Finding Persistence.
        Deduplication rule:
        Findings are considered identical if they target the same file, line range (or None),
        category, and rule_id or title.
        When duplicates occur:
        - If one is STATIC and one is AI, the merged finding has source_type="COMBINED"
        - The higher confidence is preserved ("high" > "medium" > "low")
        - Rule ID and suggested fix are retained
        - Evidence is combined if distinct
        """
        deduped: dict[tuple[Any, ...], dict[str, Any]] = {}
        for item in findings:
            raw: dict[str, Any] = {}
            if hasattr(item, "model_dump"):
                raw = item.model_dump()
            elif hasattr(item, "dict"):
                raw = item.dict()
            elif isinstance(item, dict):
                raw = dict(item)
            elif isinstance(item, AnalysisFinding):
                raw = item.to_dict()

            source_ref = raw.get("source_reference") or {}
            if hasattr(source_ref, "model_dump"):
                source_ref = source_ref.model_dump()
            elif hasattr(source_ref, "dict"):
                source_ref = source_ref.dict()
            elif not isinstance(source_ref, dict):
                source_ref = {}

            f_path = str(raw.get("file_path") or source_ref.get("file_path") or "").replace("\\", "/").strip().lower()
            s_line = raw.get("start_line") if "start_line" in raw else source_ref.get("start_line")
            e_line = raw.get("end_line") if "end_line" in raw else source_ref.get("end_line")
            cat = str(raw.get("category", "")).strip().lower()
            r_id = str(raw.get("rule_id") or "").strip().lower()
            t_title = str(raw.get("title", "")).strip().lower()

            key = (f_path, s_line, e_line, cat, r_id or t_title)

            if key not in deduped:
                deduped[key] = raw
            else:
                existing = deduped[key]
                # Merge source types: STATIC + AI -> COMBINED
                exist_type = str(existing.get("source_type", "AI")).upper()
                new_type = str(raw.get("source_type", "AI")).upper()
                if (exist_type == "STATIC" and new_type == "AI") or (exist_type == "AI" and new_type == "STATIC"):
                    existing["source_type"] = "COMBINED"
                elif exist_type != new_type and (exist_type == "COMBINED" or new_type == "COMBINED"):
                    existing["source_type"] = "COMBINED"

                # Merge confidence: prefer high > medium > low
                conf_weights = {"high": 3, "medium": 2, "low": 1}
                exist_conf = str(existing.get("confidence", "medium")).lower()
                new_conf = str(raw.get("confidence", "medium")).lower()
                if conf_weights.get(new_conf, 1) > conf_weights.get(exist_conf, 1):
                    existing["confidence"] = new_conf

                # Merge rule_id if missing in existing
                if not existing.get("rule_id") and raw.get("rule_id"):
                    existing["rule_id"] = raw.get("rule_id")

                # Merge suggested fix if missing
                if not existing.get("suggested_fix") and raw.get("suggested_fix"):
                    existing["suggested_fix"] = raw.get("suggested_fix")

                # Merge evidence
                exist_ev = str(existing.get("evidence", ""))
                new_ev = str(raw.get("evidence", ""))
                if new_ev and new_ev not in exist_ev:
                    existing["evidence"] = f"{exist_ev}\n{new_ev}".strip()

        return list(deduped.values())

    def get_by_id(self, run_id: uuid.UUID | str) -> Optional[AnalysisRun]:
        """Retrieve an AnalysisRun with eager-loaded findings by primary key ID."""
        r_uuid = _ensure_uuid(run_id)
        if r_uuid is None:
            return None

        stmt = (
            select(AnalysisRun)
            .where(AnalysisRun.id == r_uuid)
            .options(selectinload(AnalysisRun.findings))
        )
        return self.session.execute(stmt).scalar_one_or_none()

    def get_by_id_and_repository(
        self,
        run_id: uuid.UUID | str,
        repository_id: uuid.UUID | str,
    ) -> Optional[AnalysisRun]:
        """Retrieve an AnalysisRun strictly enforcing repository scoping."""
        r_uuid = _ensure_uuid(run_id)
        repo_uuid = _ensure_uuid(repository_id)
        if r_uuid is None or repo_uuid is None:
            return None

        stmt = (
            select(AnalysisRun)
            .where(
                AnalysisRun.id == r_uuid,
                AnalysisRun.repository_id == repo_uuid,
            )
            .options(selectinload(AnalysisRun.findings))
        )
        return self.session.execute(stmt).scalar_one_or_none()

    def list_by_repository(
        self,
        repository_id: uuid.UUID | str,
        *,
        user_id: Optional[uuid.UUID | str] = None,
        feature_type: Optional[str] = None,
        status: Optional[str] = None,
        target_path: Optional[str] = None,
        target_symbol: Optional[str] = None,
        source_revision: Optional[str] = None,
        offset: int = 0,
        limit: int = 20,
    ) -> Tuple[List[AnalysisRun], int]:
        """List paginated analysis runs for an authorized repository, ordered newest first.

        Returns (items, total_count).
        """
        repo_uuid = _ensure_uuid(repository_id)
        if repo_uuid is None:
            return [], 0

        stmt = select(AnalysisRun).where(AnalysisRun.repository_id == repo_uuid)

        if user_id:
            u_uuid = _ensure_uuid(user_id)
            if u_uuid:
                stmt = stmt.where(AnalysisRun.user_id == u_uuid)

        if feature_type:
            feat_val = feature_type.value if hasattr(feature_type, "value") else str(feature_type)
            if feat_val in ("review", "code_review"):
                stmt = stmt.where(AnalysisRun.feature_type.in_(["review", "code_review"]))
            elif feat_val in ("detect_bugs", "bugs"):
                stmt = stmt.where(AnalysisRun.feature_type.in_(["detect_bugs", "bugs"]))
            elif feat_val in ("generate_tests", "tests"):
                stmt = stmt.where(AnalysisRun.feature_type.in_(["generate_tests", "tests"]))
            else:
                stmt = stmt.where(AnalysisRun.feature_type == feat_val)

        if status:
            status_val = status.value if hasattr(status, "value") else str(status)
            stmt = stmt.where(AnalysisRun.status == status_val)

        if target_path:
            stmt = stmt.where(AnalysisRun.target_path == target_path)

        if target_symbol:
            stmt = stmt.where(AnalysisRun.target_symbol == target_symbol)

        if source_revision:
            stmt = stmt.where(AnalysisRun.source_revision == source_revision)

        # Count query
        count_stmt = select(func.count()).select_from(stmt.subquery())
        total = self.session.scalar(count_stmt) or 0

        # Query paginated runs ordered by created_at descending
        ordered_stmt = (
            stmt.order_by(AnalysisRun.created_at.desc())
            .offset(offset)
            .limit(limit)
            .options(selectinload(AnalysisRun.findings))
        )
        items = list(self.session.scalars(ordered_stmt).all())
        return items, total

    def update_status(
        self,
        run_id: uuid.UUID | str,
        status: str,
        *,
        error_message: Optional[str] = None,
        result_payload: Optional[dict[str, Any]] = None,
        test_output: Optional[str] = None,
        completed_at: Optional[datetime] = None,
    ) -> Optional[AnalysisRun]:
        """Update lifecycle status and output payloads of an existing analysis run."""
        run = self.get_by_id(run_id)
        if run is None:
            return None

        status_val = status.value if hasattr(status, "value") else str(status)
        run.status = status_val

        if error_message is not None:
            run.error_message = error_message
        if result_payload is not None:
            run.result_payload = result_payload
        if test_output is not None:
            run.test_output = test_output

        if completed_at is not None:
            run.completed_at = completed_at
        elif status_val in (
            AnalysisRunStatus.COMPLETED.value,
            AnalysisRunStatus.FAILED.value,
            AnalysisRunStatus.CANCELLED.value,
        ):
            run.completed_at = datetime.now(timezone.utc)

        self.session.commit()
        self.session.refresh(run)
        return run

    def add_findings(
        self,
        run_id: uuid.UUID | str,
        findings: Sequence[Any],
    ) -> List[AnalysisFinding]:
        """Append findings to an existing analysis run and update its findings count."""
        run = self.get_by_id(run_id)
        if run is None:
            raise ValueError(f"AnalysisRun not found: {run_id}")

        added: list[AnalysisFinding] = []
        for item in findings:
            finding = self._attach_finding_to_run(run, item)
            added.append(finding)

        run.findings_count = (run.findings_count or 0) + len(added)
        self.session.commit()
        self.session.refresh(run)
        return added

    def delete(self, run_id: uuid.UUID | str) -> bool:
        """Delete an analysis run and its associated findings."""
        run = self.get_by_id(run_id)
        if run is None:
            return False

        self.session.delete(run)
        self.session.commit()
        return True

    def delete_by_repository(self, repository_id: uuid.UUID | str) -> int:
        """Delete all analysis runs and findings for a repository."""
        repo_uuid = _ensure_uuid(repository_id)
        if repo_uuid is None:
            return 0

        stmt = select(AnalysisRun.id).where(AnalysisRun.repository_id == repo_uuid)
        run_ids = list(self.session.scalars(stmt).all())
        if not run_ids:
            return 0

        self.session.execute(
            delete(AnalysisFinding).where(AnalysisFinding.repository_id == repo_uuid)
        )
        self.session.execute(
            delete(AnalysisRun).where(AnalysisRun.repository_id == repo_uuid)
        )
        self.session.commit()
        return len(run_ids)

    def delete_run(
        self,
        run_id: uuid.UUID | str,
        repository_id: Optional[uuid.UUID | str] = None,
    ) -> bool:
        """Delete an analysis run with optional repository boundary validation."""
        run_uuid = _ensure_uuid(run_id)
        if run_uuid is None:
            return False

        if repository_id is not None:
            run = self.get_by_id_and_repository(run_uuid, repository_id)
        else:
            run = self.get_by_id(run_uuid)

        if run is None:
            return False

        self.session.delete(run)
        self.session.commit()
        return True

    def get_run_summary(
        self,
        repository_id: uuid.UUID | str,
    ) -> dict[str, Any]:
        """Aggregate analysis run and finding metrics for an authorized repository (Week 2 — Day 6)."""
        repo_uuid = _ensure_uuid(repository_id)
        if repo_uuid is None:
            return {
                "total_runs": 0,
                "by_feature": {},
                "by_status": {},
                "total_findings": 0,
                "findings_by_severity": {},
                "findings_by_category": {},
            }

        # 1. Total runs & breakdown by feature and status
        runs_stmt = select(
            AnalysisRun.feature_type,
            AnalysisRun.status,
            func.count(AnalysisRun.id),
        ).where(
            AnalysisRun.repository_id == repo_uuid
        ).group_by(
            AnalysisRun.feature_type,
            AnalysisRun.status,
        )

        rows = self.session.execute(runs_stmt).all()
        total_runs = 0
        by_feature: dict[str, int] = {}
        by_status: dict[str, int] = {}

        for feat, stat, cnt in rows:
            feat_str = str(feat.value if hasattr(feat, "value") else feat)
            stat_str = str(stat.value if hasattr(stat, "value") else stat)
            total_runs += cnt
            by_feature[feat_str] = by_feature.get(feat_str, 0) + cnt
            by_status[stat_str] = by_status.get(stat_str, 0) + cnt

        # 2. Findings breakdown by severity and category
        findings_stmt = select(
            AnalysisFinding.severity,
            AnalysisFinding.category,
            func.count(AnalysisFinding.id),
        ).where(
            AnalysisFinding.repository_id == repo_uuid
        ).group_by(
            AnalysisFinding.severity,
            AnalysisFinding.category,
        )

        f_rows = self.session.execute(findings_stmt).all()
        total_findings = 0
        by_severity: dict[str, int] = {}
        by_category: dict[str, int] = {}

        for sev, cat, cnt in f_rows:
            sev_str = str(sev).upper()
            cat_str = str(cat).lower()
            total_findings += cnt
            by_severity[sev_str] = by_severity.get(sev_str, 0) + cnt
            by_category[cat_str] = by_category.get(cat_str, 0) + cnt

        return {
            "repository_id": str(repo_uuid),
            "total_runs": total_runs,
            "by_feature": by_feature,
            "by_status": by_status,
            "total_findings": total_findings,
            "findings_by_severity": by_severity,
            "findings_by_category": by_category,
        }

    # Backwards-compatible method aliases
    create = create_run
    save = create_run
    get_run = get_by_id
    list_runs = list_by_repository
    delete_repository_runs = delete_by_repository
