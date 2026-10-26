"""Standalone Code Review History Service for Week 2 Day 5–6 (Developer Intelligence Suite).

Owner: Om (Database & Persistence) & Yug (API Integration)

Provides business-logic and session-managed orchestration for:
1. Persisting completed code review runs (`feature_type="review"`) with structured `ReviewReport`
   and categorized `ReviewFinding` rows across `correctness`, `security`, `performance`,
   `reliability`, and `maintainability`.
2. Persisting failed code review runs (`status="FAILED"`, `error_message`) separately from
   successful zero-finding review reports (`status="COMPLETED"`, `total_findings=0`, `risk_level="NONE"`).
3. Ensuring a review of a newer revision does not silently overwrite previous revision results
   (`Docs/week2.md` §9 & §10).
4. History retrieval with pagination, ordering (newest first), and multi-criteria filtering
   (by status, target_path, source_revision).
5. Reopening past code review runs from history with full fidelity (Scenario D Step 7).
6. Multi-tenant repository isolation: strictly enforcing repository boundary checks on all queries.
"""

from __future__ import annotations

import logging
import uuid
from contextlib import contextmanager
from datetime import datetime
from typing import Any, Generator, List, Optional, Sequence, Tuple

from sqlalchemy.orm import Session, sessionmaker

from app.models.analysis_run import AnalysisFeature, AnalysisRun, AnalysisRunStatus
from app.repositories.analysis_run_repository import AnalysisRunRepository

logger = logging.getLogger(__name__)


class ReviewHistoryService:
    """Service managing persistent history for Standalone AI Code Review runs and findings."""

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
    # 1. Save Completed & Failed Review Runs
    # -----------------------------------------------------------------------

    def save_review(
        self,
        repository_id: uuid.UUID | str,
        target_path: Optional[str] = None,
        report: Optional[Any] = None,
        *,
        findings: Optional[Sequence[Any]] = None,
        status: str = AnalysisRunStatus.COMPLETED.value,
        source_revision: Optional[str] = None,
        user_id: Optional[uuid.UUID | str] = None,
        error_message: Optional[str] = None,
        run_id: Optional[uuid.UUID | str] = None,
        target: Optional[Any] = None,
        result_payload: Optional[dict[str, Any]] = None,
        created_at: Optional[datetime | str] = None,
        completed_at: Optional[datetime | str] = None,
        db: Optional[Session] = None,
    ) -> AnalysisRun:
        """Store a completed or failed standalone code review run with structured findings."""
        with self._get_session(db) as session:
            repo = AnalysisRunRepository(session)
            return repo.save_review_run(
                repository_id=repository_id,
                target_path=target_path,
                report=report,
                findings=findings,
                status=status,
                source_revision=source_revision,
                user_id=user_id,
                error_message=error_message,
                run_id=run_id,
                target=target,
                result_payload=result_payload,
                created_at=created_at,
                completed_at=completed_at,
            )

    def record_failure(
        self,
        repository_id: uuid.UUID | str,
        error_message: str = "Code review execution failed.",
        *,
        target_path: Optional[str] = None,
        source_revision: Optional[str] = None,
        user_id: Optional[uuid.UUID | str] = None,
        run_id: Optional[uuid.UUID | str] = None,
        target: Optional[Any] = None,
        db: Optional[Session] = None,
    ) -> AnalysisRun:
        """Store a failed review run separately from successful zero-finding review reports."""
        with self._get_session(db) as session:
            repo = AnalysisRunRepository(session)
            return repo.record_review_failure(
                repository_id=repository_id,
                target_path=target_path,
                error_message=error_message,
                source_revision=source_revision,
                user_id=user_id,
                run_id=run_id,
                target=target,
            )

    # -----------------------------------------------------------------------
    # 2. History Retrieval, Reopening & Filtering
    # -----------------------------------------------------------------------

    def list_history(
        self,
        repository_id: uuid.UUID | str,
        *,
        status: Optional[str] = None,
        target_path: Optional[str] = None,
        source_revision: Optional[str] = None,
        page: int = 1,
        page_size: int = 20,
        db: Optional[Session] = None,
    ) -> Tuple[List[AnalysisRun], int]:
        """List paginated code review runs for an authorized repository, newest first."""
        offset = max(0, (page - 1) * page_size)
        with self._get_session(db) as session:
            repo = AnalysisRunRepository(session)
            return repo.list_review_runs(
                repository_id=repository_id,
                status=status,
                target_path=target_path,
                source_revision=source_revision,
                offset=offset,
                limit=page_size,
            )

    def get_review_by_id(
        self,
        run_id: uuid.UUID | str,
        repository_id: Optional[uuid.UUID | str] = None,
        db: Optional[Session] = None,
    ) -> Optional[AnalysisRun]:
        """Fetch a specific review run with repository isolation check."""
        with self._get_session(db) as session:
            repo = AnalysisRunRepository(session)
            return repo.get_review_run(run_id, repository_id=repository_id)

    def reopen_review(
        self,
        run_id: uuid.UUID | str,
        repository_id: Optional[uuid.UUID | str] = None,
        db: Optional[Session] = None,
    ) -> Optional[dict[str, Any]]:
        """Reopen a code review run from history matching ReviewReportResponse (Scenario D Step 7)."""
        with self._get_session(db) as session:
            repo = AnalysisRunRepository(session)
            return repo.reopen_review(run_id, repository_id=repository_id)

    def get_latest(
        self,
        repository_id: uuid.UUID | str,
        target_path: Optional[str] = None,
        *,
        source_revision: Optional[str] = None,
        status: str = AnalysisRunStatus.COMPLETED.value,
        db: Optional[Session] = None,
    ) -> Optional[AnalysisRun]:
        """Get the most recent completed review run matching target and revision."""
        with self._get_session(db) as session:
            repo = AnalysisRunRepository(session)
            return repo.get_latest_review(
                repository_id=repository_id,
                target_path=target_path,
                source_revision=source_revision,
                status=status,
            )

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
        feature_type: Optional[str] = None,
        status: Optional[str] = None,
        target_path: Optional[str] = None,
        source_revision: Optional[str] = None,
        offset: int = 0,
        limit: int = 20,
        db: Optional[Session] = None,
    ) -> Tuple[List[AnalysisRun], int]:
        """Compatible with GET /repositories/{id}/analysis-runs."""
        with self._get_session(db) as session:
            repo = AnalysisRunRepository(session)
            return repo.list_by_repository(
                repository_id=repository_id,
                feature_type=feature_type or AnalysisFeature.REVIEW.value,
                status=status,
                target_path=target_path,
                source_revision=source_revision,
                offset=offset,
                limit=limit,
            )

    def get_run(
        self,
        run_id: uuid.UUID | str,
        repository_id: Optional[uuid.UUID | str] = None,
        db: Optional[Session] = None,
    ) -> Optional[AnalysisRun]:
        """Compatible with GET /analysis-runs/{run_id}."""
        with self._get_session(db) as session:
            repo = AnalysisRunRepository(session)
            if repository_id is not None:
                return repo.get_by_id_and_repository(run_id, repository_id)
            return repo.get_by_id(run_id)
