"""Standalone AI Code Review History Service for Week 2 Day 5 (Developer Intelligence Suite).

Owner: Om — Database & Persistence.

Provides business-logic and session-managed orchestration for:
1. Persisting completed standalone AI code reviews with categorized findings (correctness, security,
   performance, reliability, maintainability), source locations, and revision metadata.
2. Persisting failed review runs separately with descriptive error messages,
   strictly preventing execution failures from masquerading as clean reviews with zero findings.
3. Preserving repository_id, target coordinates (file, commit SHA, PR diff, unified diff),
   and source revisions (git commit SHA, PR number, base/head revisions).
4. Ensuring reviews of newer revisions never overwrite historical results across commits.
5. History retrieval with pagination, ordering (newest first), and multi-criteria filtering
   (by status, target_path, source_revision, commit_sha, pr_number).
6. Reopening past review runs from persistent history with full fidelity matching ReviewReportResponse
   (Scenario D Step 7).
7. Multi-tenant repository isolation: strictly enforcing repository boundary checks on all operations.
8. Protocol compatibility for `app.state.review_history_service` and route handlers.
"""

from __future__ import annotations

import logging
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Generator, List, Optional, Sequence, Tuple

from sqlalchemy.orm import Session, sessionmaker

from app.models.analysis_run import AnalysisFeature, AnalysisRun, AnalysisRunStatus
from app.repositories.analysis_run_repository import AnalysisRunRepository

logger = logging.getLogger(__name__)


class ReviewHistoryService:
    """Service managing persistent history for Standalone AI Code Review runs."""

    __test__ = False

    def __init__(
        self,
        session_factory: Optional[sessionmaker] = None,
        session: Optional[Session] = None,
    ) -> None:
        self.session_factory = session_factory
        self._session = session

    @contextmanager
    def _get_session(self, db: Optional[Session] = None) -> Generator[Session, None, None]:
        """Provide an active database session from argument, cached session, or session factory."""
        if db is not None:
            yield db
            return
        if self._session is not None:
            yield self._session
            return
        if self.session_factory is not None:
            s: Session = self.session_factory()
            try:
                yield s
            finally:
                s.close()
            return
        raise RuntimeError("No database session or session_factory configured for ReviewHistoryService.")

    # -----------------------------------------------------------------------
    # 1. Save Completed & Failed Reviews
    # -----------------------------------------------------------------------

    def save_review(
        self,
        repository_id: uuid.UUID | str,
        target_path: Optional[str] = None,
        report: Optional[Any] = None,
        *,
        findings: Optional[Sequence[Any]] = None,
        review_report: Optional[Any] = None,
        status: str = AnalysisRunStatus.COMPLETED.value,
        review_target: Optional[Any] = None,
        target: Optional[Any] = None,
        commit_sha: Optional[str] = None,
        pr_number: Optional[int] = None,
        diff: Optional[str] = None,
        base_revision: Optional[str] = None,
        head_revision: Optional[str] = None,
        source_revision: Optional[str] = None,
        target_symbol: Optional[str] = None,
        start_line: Optional[int] = None,
        end_line: Optional[int] = None,
        user_id: Optional[uuid.UUID | str] = None,
        error_message: Optional[str] = None,
        run_id: Optional[uuid.UUID | str] = None,
        result_payload: Optional[dict[str, Any]] = None,
        missing_context: Optional[Sequence[str]] = None,
        deduplicate_findings: bool = True,
        deduplicate_run: bool = False,
        created_at: Optional[datetime | str] = None,
        completed_at: Optional[datetime | str] = None,
        db: Optional[Session] = None,
        **extra_kwargs: Any,
    ) -> AnalysisRun:
        """Store a completed or failed code review with rich structured findings (Week 2 — Day 5)."""
        actual_report = report if report is not None else review_report
        actual_findings = findings
        if actual_findings is None and actual_report is not None:
            if hasattr(actual_report, "findings"):
                actual_findings = getattr(actual_report, "findings", None)
            elif isinstance(actual_report, dict) and "findings" in actual_report:
                actual_findings = actual_report.get("findings")

        with self._get_session(db) as session:
            repo = AnalysisRunRepository(session)
            return repo.save_review_run(
                repository_id=repository_id,
                review_target=review_target or target,
                report=actual_report,
                findings=actual_findings,
                status=status,
                target_path=target_path,
                target_symbol=target_symbol,
                start_line=start_line,
                end_line=end_line,
                source_revision=source_revision,
                commit_sha=commit_sha,
                pr_number=pr_number,
                diff=diff,
                base_revision=base_revision,
                head_revision=head_revision,
                user_id=user_id,
                error_message=error_message,
                run_id=run_id,
                target=target or review_target,
                result_payload=result_payload,
                missing_context=missing_context,
                deduplicate_findings=deduplicate_findings,
                deduplicate_run=deduplicate_run,
                created_at=created_at,
                completed_at=completed_at,
                **extra_kwargs,
            )

    def record_failure(
        self,
        repository_id: uuid.UUID | str,
        error_message: str,
        *,
        target_path: Optional[str] = None,
        review_target: Optional[Any] = None,
        source_revision: Optional[str] = None,
        commit_sha: Optional[str] = None,
        pr_number: Optional[int] = None,
        user_id: Optional[uuid.UUID | str] = None,
        run_id: Optional[uuid.UUID | str] = None,
        created_at: Optional[datetime | str] = None,
        db: Optional[Session] = None,
    ) -> AnalysisRun:
        """Explicitly record a failed code review run in persistence."""
        with self._get_session(db) as session:
            repo = AnalysisRunRepository(session)
            return repo.record_review_failure(
                repository_id=repository_id,
                error_message=error_message,
                target_path=target_path,
                review_target=review_target,
                source_revision=source_revision,
                commit_sha=commit_sha,
                pr_number=pr_number,
                user_id=user_id,
                run_id=run_id,
                created_at=created_at,
            )

    # -----------------------------------------------------------------------
    # 2. History Retrieval, Reopening & Queries
    # -----------------------------------------------------------------------

    def get_review(
        self,
        run_id: uuid.UUID | str,
        repository_id: Optional[uuid.UUID | str] = None,
        db: Optional[Session] = None,
    ) -> Optional[AnalysisRun]:
        """Fetch a specific review run with eager-loaded findings."""
        with self._get_session(db) as session:
            repo = AnalysisRunRepository(session)
            return repo.get_review_run(run_id, repository_id=repository_id)

    def reopen_review(
        self,
        run_id: uuid.UUID | str,
        repository_id: Optional[uuid.UUID | str] = None,
        db: Optional[Session] = None,
    ) -> Optional[dict[str, Any]]:
        """Reopen and reconstitute a past review run matching ReviewReportResponse (Scenario D Step 7)."""
        with self._get_session(db) as session:
            repo = AnalysisRunRepository(session)
            return repo.reopen_review(run_id, repository_id=repository_id)

    def list_reviews(
        self,
        repository_id: uuid.UUID | str,
        *,
        status: Optional[str] = None,
        target_path: Optional[str] = None,
        source_revision: Optional[str] = None,
        commit_sha: Optional[str] = None,
        pr_number: Optional[int] = None,
        user_id: Optional[uuid.UUID | str] = None,
        offset: int = 0,
        limit: int = 50,
        db: Optional[Session] = None,
    ) -> Tuple[List[AnalysisRun], int]:
        """List paginated review runs for an authorized repository, newest first."""
        with self._get_session(db) as session:
            repo = AnalysisRunRepository(session)
            return repo.list_review_runs(
                repository_id=repository_id,
                user_id=user_id,
                status=status,
                target_path=target_path,
                source_revision=source_revision,
                commit_sha=commit_sha,
                pr_number=pr_number,
                offset=offset,
                limit=limit,
            )

    def get_latest_review(
        self,
        repository_id: uuid.UUID | str,
        *,
        target_path: Optional[str] = None,
        source_revision: Optional[str] = None,
        commit_sha: Optional[str] = None,
        pr_number: Optional[int] = None,
        status: str = AnalysisRunStatus.COMPLETED.value,
        db: Optional[Session] = None,
    ) -> Optional[AnalysisRun]:
        """Fetch the latest review run matching given target criteria."""
        with self._get_session(db) as session:
            repo = AnalysisRunRepository(session)
            return repo.get_latest_review(
                repository_id=repository_id,
                target_path=target_path,
                source_revision=source_revision,
                commit_sha=commit_sha,
                pr_number=pr_number,
                status=status,
            )

    def find_duplicate_review(
        self,
        repository_id: uuid.UUID | str,
        *,
        target_path: Optional[str] = None,
        source_revision: Optional[str] = None,
        commit_sha: Optional[str] = None,
        pr_number: Optional[int] = None,
        status: str = AnalysisRunStatus.COMPLETED.value,
        db: Optional[Session] = None,
    ) -> Optional[AnalysisRun]:
        """Check for duplicate completed review runs."""
        with self._get_session(db) as session:
            repo = AnalysisRunRepository(session)
            return repo.find_duplicate_review(
                repository_id=repository_id,
                target_path=target_path,
                source_revision=source_revision,
                commit_sha=commit_sha,
                pr_number=pr_number,
                status=status,
            )

    def delete_review(
        self,
        run_id: uuid.UUID | str,
        repository_id: Optional[uuid.UUID | str] = None,
        db: Optional[Session] = None,
    ) -> bool:
        """Delete a review run with repository boundary check."""
        with self._get_session(db) as session:
            repo = AnalysisRunRepository(session)
            return repo.delete_review_run(run_id, repository_id=repository_id)

    def get_review_summary(
        self,
        repository_id: uuid.UUID | str,
        db: Optional[Session] = None,
    ) -> dict[str, Any]:
        """Compute aggregate review statistics for a repository."""
        runs, total_runs = self.list_reviews(repository_id, limit=500, db=db)
        total_findings = sum(r.findings_count for r in runs)
        completed_runs = sum(1 for r in runs if r.status == AnalysisRunStatus.COMPLETED.value)
        failed_runs = sum(1 for r in runs if r.status == AnalysisRunStatus.FAILED.value)

        categories: dict[str, int] = {}
        severities: dict[str, int] = {}

        for run in runs:
            for f in run.findings:
                cat = str(f.category).lower()
                categories[cat] = categories.get(cat, 0) + 1
                sev = str(f.severity).upper()
                severities[sev] = severities.get(sev, 0) + 1

        return {
            "total_runs": total_runs,
            "completed_runs": completed_runs,
            "failed_runs": failed_runs,
            "total_findings": total_findings,
            "category_counts": categories,
            "severity_counts": severities,
        }

    # -----------------------------------------------------------------------
    # 3. Router & Orchestrator Protocol Compatibility
    # -----------------------------------------------------------------------

    def record_run(self, record: dict[str, Any], db: Optional[Session] = None) -> AnalysisRun:
        """Compatible with explanation_orchestrator.record_analysis_run."""
        with self._get_session(db) as session:
            repo = AnalysisRunRepository(session)
            return repo.create_run(**record)

    save_run = record_run
    create_run = record_run

    def list_runs(
        self,
        repository_id: uuid.UUID | str,
        *,
        status: Optional[str] = None,
        target_path: Optional[str] = None,
        source_revision: Optional[str] = None,
        offset: int = 0,
        limit: int = 50,
        db: Optional[Session] = None,
        **extra_kwargs: Any,
    ) -> Tuple[List[AnalysisRun], int]:
        """Protocol listing method compatible with AnalysisRunRepository."""
        return self.list_reviews(
            repository_id=repository_id,
            status=status,
            target_path=target_path,
            source_revision=source_revision,
            offset=offset,
            limit=limit,
            db=db,
        )

    def get_run(
        self,
        run_id: uuid.UUID | str,
        repository_id: Optional[uuid.UUID | str] = None,
        db: Optional[Session] = None,
    ) -> Optional[AnalysisRun]:
        """Protocol retrieval method compatible with AnalysisRunRepository."""
        return self.get_review(run_id, repository_id=repository_id, db=db)
