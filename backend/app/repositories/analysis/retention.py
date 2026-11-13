"""Run integrity verification, retention pruning, and history sanitization aggregate."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, List, Optional

from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from app.models.analysis_finding import AnalysisFinding
from app.models.analysis_run import AnalysisFeature, AnalysisRun, AnalysisRunStatus
from app.repositories.analysis.base import (
    _ensure_uuid,
    scrub_sensitive_data,
    scrub_sensitive_text,
)

from app.repositories.analysis.core import AnalysisCoreMixin


class AnalysisRetentionMixin:
    """Integrity, retention, and sanitization operations."""

    def verify_integrity(
        self,
        repository_id: Optional[uuid.UUID | str] = None,
    ) -> dict[str, Any]:
        """Perform comprehensive database integrity verification across runs and findings (Week 2 — Day 6).

        Verifies:
        1. Absence of orphaned findings (findings without a valid parent analysis_run).
        2. Synchronization between findings_count column and actual associated findings count.
        3. Status and timestamp consistency (COMPLETED must have completed_at; FAILED must have error_message).
        4. Cross-repository foreign key attribution integrity.
        """
        issues: List[dict[str, Any]] = []

        # 1. Check for orphaned findings
        orphan_stmt = select(AnalysisFinding).where(
            ~AnalysisFinding.analysis_run_id.in_(select(AnalysisRun.id))
        )
        if repository_id is not None:
            repo_uuid = _ensure_uuid(repository_id)
            if repo_uuid:
                orphan_stmt = orphan_stmt.where(AnalysisFinding.repository_id == repo_uuid)

        orphans = list(self.session.scalars(orphan_stmt).all())
        for orphan in orphans:
            issues.append({
                "type": "ORPHANED_FINDING",
                "finding_id": str(orphan.id),
                "analysis_run_id": str(orphan.analysis_run_id),
                "details": f"Finding '{orphan.title}' points to non-existent analysis_run '{orphan.analysis_run_id}'.",
            })

        # 2. Check run count synchronization and status consistency
        run_query = select(AnalysisRun).options(selectinload(AnalysisRun.findings))
        if repository_id is not None:
            repo_uuid = _ensure_uuid(repository_id)
            if repo_uuid:
                run_query = run_query.where(AnalysisRun.repository_id == repo_uuid)

        all_runs = list(self.session.scalars(run_query).all())
        desynchronized_count = 0
        inconsistent_status_count = 0

        for run in all_runs:
            actual_findings_count = len(run.findings)
            valid_counts = {actual_findings_count}
            if (
                run.feature_type == AnalysisFeature.GENERATE_TESTS.value
                and actual_findings_count == 0
                and isinstance(run.result_payload, dict)
            ):
                inner_res = run.result_payload.get("result")
                scenarios = (
                    inner_res.get("covered_scenarios")
                    if isinstance(inner_res, dict)
                    else run.result_payload.get("covered_scenarios")
                )
                if isinstance(scenarios, list):
                    valid_counts.add(len(scenarios))
            if run.findings_count not in valid_counts:
                desynchronized_count += 1
                issues.append({
                    "type": "DESYNCHRONIZED_FINDINGS_COUNT",
                    "run_id": str(run.id),
                    "recorded_count": run.findings_count,
                    "actual_count": actual_findings_count,
                    "details": f"Run '{run.id}' recorded findings_count={run.findings_count} but has {actual_findings_count} associated findings.",
                })

            # Status consistency checks
            if run.status == AnalysisRunStatus.COMPLETED.value and run.completed_at is None:
                inconsistent_status_count += 1
                issues.append({
                    "type": "MISSING_COMPLETION_TIMESTAMP",
                    "run_id": str(run.id),
                    "details": f"Run '{run.id}' is COMPLETED but completed_at is null.",
                })

            if run.status == AnalysisRunStatus.FAILED.value and not run.error_message:
                inconsistent_status_count += 1
                issues.append({
                    "type": "MISSING_ERROR_MESSAGE",
                    "run_id": str(run.id),
                    "details": f"Run '{run.id}' is FAILED but error_message is missing or empty.",
                })

        return {
            "status": "CLEAN" if len(issues) == 0 else "ISSUES_FOUND",
            "total_runs_checked": len(all_runs),
            "orphaned_findings_count": len(orphans),
            "desynchronized_runs_count": desynchronized_count,
            "inconsistent_status_count": inconsistent_status_count,
            "issues_count": len(issues),
            "issues": issues,
        }

    def purge_expired_runs(
        self,
        *,
        repository_id: Optional[uuid.UUID | str] = None,
        retention_days: int = 30,
        feature_type: Optional[str] = None,
        status: Optional[str] = None,
    ) -> int:
        """Purge analysis runs and cascading findings older than retention_days (Day 7).

        Default retention is 30 days. Cascading deletes automatically remove associated findings.
        Returns the count of purged runs.
        """
        cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)
        stmt = select(AnalysisRun).where(AnalysisRun.created_at < cutoff)

        if repository_id is not None:
            repo_uuid = _ensure_uuid(repository_id)
            if repo_uuid:
                stmt = stmt.where(AnalysisRun.repository_id == repo_uuid)

        if feature_type:
            feat_val = feature_type.value if hasattr(feature_type, "value") else str(feature_type)
            stmt = stmt.where(AnalysisRun.feature_type == feat_val)

        if status:
            status_val = status.value if hasattr(status, "value") else str(status)
            stmt = stmt.where(AnalysisRun.status == status_val)

        runs_to_delete = list(self.session.scalars(stmt).all())
        count = len(runs_to_delete)
        for run in runs_to_delete:
            self.session.delete(run)

        if count > 0:
            self.session.commit()
        return count

    def prune_uncompleted_stale_runs(
        self,
        *,
        older_than_hours: int = 24,
        mark_as_failed: bool = True,
        repository_id: Optional[uuid.UUID | str] = None,
    ) -> int:
        """Prune or time-out stuck PENDING or RUNNING runs older than specified hours (Day 7).

        If mark_as_failed is True, transitions run status to FAILED with a timeout message.
        Otherwise, purges the runs completely.
        """
        cutoff = datetime.now(timezone.utc) - timedelta(hours=older_than_hours)
        stmt = select(AnalysisRun).where(
            AnalysisRun.status.in_([AnalysisRunStatus.PENDING.value, AnalysisRunStatus.RUNNING.value]),
            AnalysisRun.created_at < cutoff,
        )

        if repository_id is not None:
            repo_uuid = _ensure_uuid(repository_id)
            if repo_uuid:
                stmt = stmt.where(AnalysisRun.repository_id == repo_uuid)

        stale_runs = list(self.session.scalars(stmt).all())
        count = len(stale_runs)
        now = datetime.now(timezone.utc)

        for run in stale_runs:
            if mark_as_failed:
                run.status = AnalysisRunStatus.FAILED.value
                run.error_message = f"Analysis run timed out after {older_than_hours} hours without completion."
                run.completed_at = now
            else:
                self.session.delete(run)

        if count > 0:
            self.session.commit()
        return count

    def get_retention_metrics(
        self,
        repository_id: Optional[uuid.UUID | str] = None,
    ) -> dict[str, Any]:
        """Calculate data retention statistics across analysis runs and findings (Day 7)."""
        repo_uuid = _ensure_uuid(repository_id) if repository_id else None
        base_stmt = select(AnalysisRun)
        if repo_uuid:
            base_stmt = base_stmt.where(AnalysisRun.repository_id == repo_uuid)

        total_runs = self.session.scalar(select(func.count()).select_from(base_stmt.subquery())) or 0
        now = datetime.now(timezone.utc)

        runs_older_30d = self.session.scalar(
            select(func.count()).select_from(
                base_stmt.where(AnalysisRun.created_at < (now - timedelta(days=30))).subquery()
            )
        ) or 0
        runs_older_60d = self.session.scalar(
            select(func.count()).select_from(
                base_stmt.where(AnalysisRun.created_at < (now - timedelta(days=60))).subquery()
            )
        ) or 0
        runs_older_90d = self.session.scalar(
            select(func.count()).select_from(
                base_stmt.where(AnalysisRun.created_at < (now - timedelta(days=90))).subquery()
            )
        ) or 0

        subq = base_stmt.subquery()
        oldest_dt = self.session.scalar(select(func.min(subq.c.created_at)))
        newest_dt = self.session.scalar(select(func.max(subq.c.created_at)))

        findings_stmt = select(func.count()).select_from(AnalysisFinding)
        if repo_uuid:
            findings_stmt = findings_stmt.where(AnalysisFinding.repository_id == repo_uuid)
        total_findings = self.session.scalar(findings_stmt) or 0

        return {
            "repository_id": str(repo_uuid) if repo_uuid else None,
            "total_runs": total_runs,
            "total_findings": total_findings,
            "runs_older_30d": runs_older_30d,
            "runs_older_60d": runs_older_60d,
            "runs_older_90d": runs_older_90d,
            "oldest_run_at": oldest_dt.isoformat() if oldest_dt else None,
            "newest_run_at": newest_dt.isoformat() if newest_dt else None,
        }

    def sanitize_sensitive_data_in_history(
        self,
        repository_id: Optional[uuid.UUID | str] = None,
    ) -> int:
        """Scan existing persisted runs and findings, redacting any raw credentials or secrets (Day 7).

        Returns count of records sanitized.
        """
        repo_uuid = _ensure_uuid(repository_id) if repository_id else None
        updated_count = 0

        # 1. Audit and sanitize runs
        run_stmt = select(AnalysisRun)
        if repo_uuid:
            run_stmt = run_stmt.where(AnalysisRun.repository_id == repo_uuid)
        runs = list(self.session.scalars(run_stmt).all())
        for run in runs:
            dirty = False
            if run.error_message:
                scrubbed = scrub_sensitive_text(run.error_message)
                if scrubbed != run.error_message:
                    run.error_message = scrubbed
                    dirty = True
            if run.test_output:
                scrubbed = scrub_sensitive_text(run.test_output)
                if scrubbed != run.test_output:
                    run.test_output = scrubbed
                    dirty = True
            if run.result_payload:
                scrubbed = scrub_sensitive_data(run.result_payload)
                if scrubbed != run.result_payload:
                    run.result_payload = scrubbed
                    dirty = True
            if dirty:
                updated_count += 1

        # 2. Audit and sanitize findings
        finding_stmt = select(AnalysisFinding)
        if repo_uuid:
            finding_stmt = finding_stmt.where(AnalysisFinding.repository_id == repo_uuid)
        findings = list(self.session.scalars(finding_stmt).all())
        for f in findings:
            dirty = False
            if f.title:
                s = scrub_sensitive_text(f.title)
                if s != f.title:
                    f.title = s
                    dirty = True
            if f.description:
                s = scrub_sensitive_text(f.description)
                if s != f.description:
                    f.description = s
                    dirty = True
            if f.evidence:
                s = scrub_sensitive_text(f.evidence)
                if s != f.evidence:
                    f.evidence = s
                    dirty = True
            if f.suggested_fix:
                s = scrub_sensitive_text(f.suggested_fix)
                if s != f.suggested_fix:
                    f.suggested_fix = s
                    dirty = True
            if f.finding_metadata:
                s = scrub_sensitive_data(f.finding_metadata)
                if s != f.finding_metadata:
                    f.finding_metadata = s
                    dirty = True
            if dirty:
                updated_count += 1

        if updated_count > 0:
            self.session.commit()
        return updated_count


class AnalysisRetentionRepository(AnalysisRetentionMixin, AnalysisCoreMixin):
    """Standalone domain aggregate for integrity, retention, and sanitization."""
