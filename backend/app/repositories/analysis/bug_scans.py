"""Bug scan run persistence, deduplication, and findings query aggregate."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, List, Optional, Sequence, Tuple

from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from app.models.analysis_finding import AnalysisFinding
from app.models.analysis_run import AnalysisFeature, AnalysisRun, AnalysisRunStatus
from app.repositories.analysis.base import (
    _ensure_uuid,
)

from app.repositories.analysis.core import AnalysisCoreMixin


class BugScanRunMixin:
    """Bug Detection & Finding history operations."""

    def save_bug_scan_run(
        self,
        *,
        repository_id: uuid.UUID | str,
        target_path: Optional[str] = None,
        findings: Optional[Sequence[Any]] = None,
        status: str = AnalysisRunStatus.COMPLETED.value,
        target_symbol: Optional[str] = None,
        start_line: Optional[int] = None,
        end_line: Optional[int] = None,
        source_revision: Optional[str] = None,
        user_id: Optional[uuid.UUID | str] = None,
        error_message: Optional[str] = None,
        run_id: Optional[uuid.UUID | str] = None,
        target: Optional[Any] = None,
        result_payload: Optional[dict[str, Any]] = None,
        missing_context: Optional[Sequence[str]] = None,
        deduplicate_findings: bool = True,
        deduplicate_run: bool = False,
        created_at: Optional[datetime | str] = None,
        completed_at: Optional[datetime | str] = None,
        **extra_kwargs: Any,
    ) -> AnalysisRun:
        """Store a completed or failed bug detection scan with structured findings (Week 2 — Day 3).

        Owner: Om — Finding Persistence.
        Records:
        - repository_id (strictly scoped)
        - user_id (coerced and verified)
        - feature_type="detect_bugs"
        - status (COMPLETED or FAILED)
        - target coordinates (path, symbol, 1-indexed inclusive line range)
        - source revision (git commit SHA or branch name)
        - individual structured findings attached to this run
        - deduplication of duplicate findings and repeated identical scan requests
        - result_payload envelope with summary statistics
        - error_message (when status=FAILED, keeping failure distinct from 0 findings)
        """
        t_path = target_path
        t_symbol = target_symbol
        s_line = start_line
        e_line = end_line
        s_rev = source_revision

        if target is not None:
            if hasattr(target, "path"):
                t_path = t_path or target.path
                t_symbol = t_symbol or getattr(target, "symbol", None)
                s_line = s_line if s_line is not None else getattr(target, "start_line", None)
                e_line = e_line if e_line is not None else getattr(target, "end_line", None)
                s_rev = s_rev or getattr(target, "revision", None)
            elif isinstance(target, dict):
                t_path = t_path or target.get("path")
                t_symbol = t_symbol or target.get("symbol")
                s_line = s_line if s_line is not None else target.get("start_line")
                e_line = e_line if e_line is not None else target.get("end_line")
                s_rev = s_rev or target.get("revision")

        repo_uuid = _ensure_uuid(repository_id)
        if repo_uuid is None:
            raise ValueError(f"Invalid repository_id: {repository_id}")

        status_val = status.value if hasattr(status, "value") else str(status).upper()

        # Idempotency / Duplicate scan check: if deduplicate_run is requested, reuse existing matching run
        if deduplicate_run and status_val == AnalysisRunStatus.COMPLETED.value:
            existing_run = self.find_duplicate_scan(
                repository_id=repo_uuid,
                target_path=t_path,
                target_symbol=t_symbol,
                start_line=s_line,
                end_line=e_line,
                source_revision=s_rev,
                status=status_val,
            )
            if existing_run is not None:
                return existing_run

        # Finding preparation and deduplication
        raw_findings = list(findings or [])
        if deduplicate_findings and raw_findings:
            raw_findings = self._deduplicate_findings_data(raw_findings)

        if status_val == AnalysisRunStatus.FAILED.value:
            if not error_message:
                error_message = "Bug detection scan failed."
            raw_findings = []
            findings_count = 0
            if result_payload is None:
                result_payload = {"error": error_message, "status": "FAILED"}
        else:
            error_message = None
            findings_count = len(raw_findings)
            if result_payload is None:
                static_count = sum(
                    1 for f in raw_findings
                    if (isinstance(f, dict) and f.get("source_type") in ("STATIC", "COMBINED"))
                    or (hasattr(f, "source_type") and getattr(f, "source_type") in ("STATIC", "COMBINED"))
                )
                ai_count = sum(
                    1 for f in raw_findings
                    if (isinstance(f, dict) and f.get("source_type") in ("AI", "COMBINED"))
                    or (hasattr(f, "source_type") and getattr(f, "source_type") in ("AI", "COMBINED"))
                )
                result_payload = {
                    "total_findings": findings_count,
                    "static_findings_count": static_count,
                    "ai_findings_count": ai_count,
                    "missing_context": list(missing_context or []),
                    "revision": s_rev,
                    "status": status_val,
                }

        return self.create_run(
            id=run_id,
            repository_id=repository_id,
            user_id=user_id,
            feature_type=AnalysisFeature.DETECT_BUGS.value,
            status=status_val,
            target_path=t_path,
            target_symbol=t_symbol,
            start_line=s_line,
            end_line=e_line,
            source_revision=s_rev,
            findings_count=findings_count,
            result_payload=result_payload,
            findings=raw_findings,
            error_message=error_message,
            created_at=created_at,
            completed_at=completed_at,
            **extra_kwargs,
        )

    def record_bug_scan_failure(
        self,
        *,
        repository_id: uuid.UUID | str,
        target_path: Optional[str] = None,
        error_message: str,
        target_symbol: Optional[str] = None,
        start_line: Optional[int] = None,
        end_line: Optional[int] = None,
        source_revision: Optional[str] = None,
        user_id: Optional[uuid.UUID | str] = None,
        run_id: Optional[uuid.UUID | str] = None,
        target: Optional[Any] = None,
        **extra_kwargs: Any,
    ) -> AnalysisRun:
        """Record an explicit failed bug scan separately from successful zero-defect runs."""
        return self.save_bug_scan_run(
            repository_id=repository_id,
            target_path=target_path,
            findings=None,
            status=AnalysisRunStatus.FAILED.value,
            target_symbol=target_symbol,
            start_line=start_line,
            end_line=end_line,
            source_revision=source_revision,
            user_id=user_id,
            error_message=error_message,
            run_id=run_id,
            target=target,
            **extra_kwargs,
        )

    def find_duplicate_scan(
        self,
        *,
        repository_id: uuid.UUID | str,
        target_path: Optional[str] = None,
        target_symbol: Optional[str] = None,
        start_line: Optional[int] = None,
        end_line: Optional[int] = None,
        source_revision: Optional[str] = None,
        status: str = AnalysisRunStatus.COMPLETED.value,
    ) -> Optional[AnalysisRun]:
        """Find an existing completed bug detection run with identical coordinates to prevent duplicate scans."""
        repo_uuid = _ensure_uuid(repository_id)
        if repo_uuid is None:
            return None

        stmt = select(AnalysisRun).where(
            AnalysisRun.repository_id == repo_uuid,
            AnalysisRun.feature_type == AnalysisFeature.DETECT_BUGS.value,
            AnalysisRun.status == status,
        )

        if target_path:
            stmt = stmt.where(AnalysisRun.target_path == target_path)
        if target_symbol:
            stmt = stmt.where(AnalysisRun.target_symbol == target_symbol)
        if start_line is not None:
            stmt = stmt.where(AnalysisRun.start_line == start_line)
        if end_line is not None:
            stmt = stmt.where(AnalysisRun.end_line == end_line)
        if source_revision:
            stmt = stmt.where(AnalysisRun.source_revision == source_revision)

        stmt = stmt.order_by(AnalysisRun.created_at.desc()).options(selectinload(AnalysisRun.findings)).limit(1)
        return self.session.execute(stmt).scalar_one_or_none()

    def list_bug_scan_runs(
        self,
        repository_id: uuid.UUID | str,
        *,
        user_id: Optional[uuid.UUID | str] = None,
        status: Optional[str] = None,
        target_path: Optional[str] = None,
        target_symbol: Optional[str] = None,
        source_revision: Optional[str] = None,
        min_severity: Optional[str] = None,
        category: Optional[str] = None,
        offset: int = 0,
        limit: int = 20,
    ) -> Tuple[List[AnalysisRun], int]:
        """List paginated bug scan runs for an authorized repository, newest first."""
        repo_uuid = _ensure_uuid(repository_id)
        if repo_uuid is None:
            return [], 0

        stmt = select(AnalysisRun).where(
            AnalysisRun.repository_id == repo_uuid,
            AnalysisRun.feature_type == AnalysisFeature.DETECT_BUGS.value,
        )

        if user_id:
            u_uuid = _ensure_uuid(user_id)
            if u_uuid:
                stmt = stmt.where(AnalysisRun.user_id == u_uuid)

        if status:
            status_val = status.value if hasattr(status, "value") else str(status)
            stmt = stmt.where(AnalysisRun.status == status_val)
        if target_path:
            stmt = stmt.where(AnalysisRun.target_path == target_path)
        if target_symbol:
            stmt = stmt.where(AnalysisRun.target_symbol == target_symbol)
        if source_revision:
            stmt = stmt.where(AnalysisRun.source_revision == source_revision)

        if category or min_severity:
            finding_subq = select(AnalysisFinding.analysis_run_id).where(
                AnalysisFinding.repository_id == repo_uuid
            )
            if category:
                finding_subq = finding_subq.where(AnalysisFinding.category == category)
            if min_severity:
                sev_order = ["INFO", "LOW", "MEDIUM", "HIGH", "CRITICAL"]
                min_sev_idx = sev_order.index(min_severity.upper()) if min_severity.upper() in sev_order else 0
                allowed_sevs = sev_order[min_sev_idx:]
                finding_subq = finding_subq.where(AnalysisFinding.severity.in_(allowed_sevs))
            stmt = stmt.where(AnalysisRun.id.in_(finding_subq))

        count_stmt = select(func.count()).select_from(stmt.subquery())
        total = self.session.scalar(count_stmt) or 0

        ordered_stmt = (
            stmt.order_by(AnalysisRun.created_at.desc())
            .offset(offset)
            .limit(limit)
            .options(selectinload(AnalysisRun.findings))
        )
        items = list(self.session.scalars(ordered_stmt).all())
        return items, total

    def get_bug_scan_run(
        self,
        run_id: uuid.UUID | str,
        repository_id: Optional[uuid.UUID | str] = None,
    ) -> Optional[AnalysisRun]:
        """Retrieve a specific bug detection run with eager-loaded findings."""
        if repository_id is not None:
            run = self.get_by_id_and_repository(run_id, repository_id)
        else:
            run = self.get_by_id(run_id)

        if run is None or run.feature_type != AnalysisFeature.DETECT_BUGS.value:
            return None
        return run

    def reopen_bug_scan(
        self,
        run_id: uuid.UUID | str,
        repository_id: Optional[uuid.UUID | str] = None,
    ) -> Optional[dict[str, Any]]:
        """Reconstitute a bug scan run from persistent history (Scenario B Step 6).

        Returns a dictionary structure matching `BugDetectionResponse`:
        - run_id
        - repository_id
        - status (COMPLETED or FAILED)
        - target (AnalysisTarget dict with path, type, symbol, start_line, end_line)
        - revision
        - findings (list of structured finding dicts)
        - total_findings
        - static_findings_count
        - ai_findings_count
        - missing_context
        - error_message
        - created_at
        - completed_at
        """
        run = self.get_bug_scan_run(run_id, repository_id)
        if run is None:
            return None

        target_type = "file"
        if run.target_symbol:
            target_type = "symbol"
        elif run.start_line is not None and run.end_line is not None:
            target_type = "range"

        target_dict = {
            "type": target_type,
            "path": run.target_path,
            "start_line": run.start_line,
            "end_line": run.end_line,
            "symbol": run.target_symbol,
            "revision": run.source_revision,
        }

        findings_list = [f.to_dict() for f in run.findings]
        static_count = sum(1 for f in run.findings if f.source_type in ("STATIC", "COMBINED"))
        ai_count = sum(1 for f in run.findings if f.source_type in ("AI", "COMBINED"))

        missing_context: list[str] = []
        if run.result_payload and isinstance(run.result_payload, dict):
            missing_context = run.result_payload.get("missing_context") or []

        return {
            "run_id": str(run.id),
            "repository_id": str(run.repository_id),
            "status": run.status,
            "target": target_dict,
            "revision": run.source_revision,
            "findings": findings_list,
            "total_findings": len(findings_list),
            "static_findings_count": static_count,
            "ai_findings_count": ai_count,
            "missing_context": missing_context,
            "error_message": run.error_message,
            "created_at": run.created_at.isoformat() if run.created_at else None,
            "completed_at": run.completed_at.isoformat() if run.completed_at else None,
        }

    def get_latest_bug_scan(
        self,
        repository_id: uuid.UUID | str,
        target_path: str,
        *,
        target_symbol: Optional[str] = None,
        source_revision: Optional[str] = None,
        status: str = AnalysisRunStatus.COMPLETED.value,
    ) -> Optional[AnalysisRun]:
        """Fetch the most recent bug scan matching target file, symbol, and revision."""
        runs, _ = self.list_bug_scan_runs(
            repository_id,
            status=status,
            target_path=target_path,
            target_symbol=target_symbol,
            source_revision=source_revision,
            offset=0,
            limit=1,
        )
        return runs[0] if runs else None

    def list_findings(
        self,
        repository_id: uuid.UUID | str,
        *,
        file_path: Optional[str] = None,
        category: Optional[str] = None,
        severity: Optional[str] = None,
        source_type: Optional[str] = None,
        rule_id: Optional[str] = None,
        analysis_run_id: Optional[uuid.UUID | str] = None,
        source_revision: Optional[str] = None,
        offset: int = 0,
        limit: int = 50,
    ) -> Tuple[List[AnalysisFinding], int]:
        """Directly query persisted findings for an authorized repository with rich filtering."""
        repo_uuid = _ensure_uuid(repository_id)
        if repo_uuid is None:
            return [], 0

        stmt = select(AnalysisFinding).where(AnalysisFinding.repository_id == repo_uuid)

        if file_path:
            stmt = stmt.where(AnalysisFinding.file_path == file_path)
        if category:
            stmt = stmt.where(AnalysisFinding.category == category)
        if severity:
            stmt = stmt.where(AnalysisFinding.severity == severity.upper())
        if source_type:
            stmt = stmt.where(AnalysisFinding.source_type == source_type.upper())
        if rule_id:
            stmt = stmt.where(AnalysisFinding.rule_id == rule_id)
        if source_revision:
            stmt = stmt.where(AnalysisFinding.source_revision == source_revision)

        run_uuid = _ensure_uuid(analysis_run_id)
        if run_uuid is not None:
            stmt = stmt.where(AnalysisFinding.analysis_run_id == run_uuid)

        count_stmt = select(func.count()).select_from(stmt.subquery())
        total = self.session.scalar(count_stmt) or 0

        ordered_stmt = (
            stmt.order_by(AnalysisFinding.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
        findings = list(self.session.scalars(ordered_stmt).all())
        return findings, total


class BugScanRunRepository(BugScanRunMixin, AnalysisCoreMixin):
    """Standalone domain aggregate for bug detection & finding history."""
