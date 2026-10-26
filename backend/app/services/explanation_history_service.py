"""Explanation History Service for Week 2 Day 2 (Developer Intelligence Suite).

Owner: Om — Database & Persistence.

Provides business-logic and session-managed orchestration for:
1. Persisting completed explanation runs with full structured analysis metadata.
2. Persisting failed explanation runs separately from successful output with error messages.
3. Preserving repository_id, target coordinates (file, symbol, 1-indexed inclusive line range),
   and source revision (git SHA or branch).
4. History retrieval with pagination, ordering (newest first), and multi-criteria filtering
   (by status, target_path, target_symbol, source_revision).
5. Reopening past explanation runs from history with full fidelity (Scenario A Step 7).
6. Multi-tenant repository isolation: strictly enforcing repository boundary checks.
7. Protocol compatibility for `app.state.analysis_run_service` and route handlers.
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


class ExplanationHistoryService:
    """Service managing persistent history for Code Explanation and analysis runs."""

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
        raise RuntimeError("No database session or session_factory configured for ExplanationHistoryService.")

    # -----------------------------------------------------------------------
    # 1. Save Completed & Failed Explanations
    # -----------------------------------------------------------------------

    def save_explanation(
        self,
        repository_id: uuid.UUID | str,
        target_path: Optional[str] = None,
        explanation: Optional[Any] = None,
        *,
        status: str = AnalysisRunStatus.COMPLETED.value,
        target_symbol: Optional[str] = None,
        start_line: Optional[int] = None,
        end_line: Optional[int] = None,
        source_revision: Optional[str] = None,
        user_id: Optional[uuid.UUID | str] = None,
        error_message: Optional[str] = None,
        run_id: Optional[uuid.UUID | str] = None,
        target: Optional[Any] = None,
        created_at: Optional[datetime | str] = None,
        completed_at: Optional[datetime | str] = None,
        db: Optional[Session] = None,
    ) -> AnalysisRun:
        """Store a completed code explanation run with rich metadata (Week 2 — Day 2)."""
        with self._get_session(db) as session:
            repo = AnalysisRunRepository(session)
            return repo.save_explanation_run(
                repository_id=repository_id,
                target_path=target_path,
                explanation=explanation,
                status=status,
                target_symbol=target_symbol,
                start_line=start_line,
                end_line=end_line,
                source_revision=source_revision,
                user_id=user_id,
                error_message=error_message,
                run_id=run_id,
                target=target,
                created_at=created_at,
                completed_at=completed_at,
            )

    def record_failure(
        self,
        repository_id: uuid.UUID | str,
        target_path: Optional[str] = None,
        error_message: str = "Code explanation failed during execution.",
        *,
        target_symbol: Optional[str] = None,
        start_line: Optional[int] = None,
        end_line: Optional[int] = None,
        source_revision: Optional[str] = None,
        user_id: Optional[uuid.UUID | str] = None,
        run_id: Optional[uuid.UUID | str] = None,
        target: Optional[Any] = None,
        created_at: Optional[datetime | str] = None,
        completed_at: Optional[datetime | str] = None,
        db: Optional[Session] = None,
    ) -> AnalysisRun:
        """Store a failed explanation run separately from successful output."""
        with self._get_session(db) as session:
            repo = AnalysisRunRepository(session)
            return repo.record_explanation_failure(
                repository_id=repository_id,
                target_path=target_path,
                error_message=error_message,
                target_symbol=target_symbol,
                start_line=start_line,
                end_line=end_line,
                source_revision=source_revision,
                user_id=user_id,
                run_id=run_id,
                target=target,
                created_at=created_at,
                completed_at=completed_at,
            )

    # -----------------------------------------------------------------------
    # 2. History Retrieval & Filtering
    # -----------------------------------------------------------------------

    def list_history(
        self,
        repository_id: uuid.UUID | str,
        *,
        status: Optional[str] = None,
        target_path: Optional[str] = None,
        target_symbol: Optional[str] = None,
        source_revision: Optional[str] = None,
        user_id: Optional[uuid.UUID | str] = None,
        offset: int = 0,
        limit: int = 20,
        db: Optional[Session] = None,
    ) -> Tuple[List[AnalysisRun], int]:
        """List paginated explanation history for an authorized repository, ordered newest first."""
        with self._get_session(db) as session:
            repo = AnalysisRunRepository(session)
            return repo.list_explanation_runs(
                repository_id=repository_id,
                user_id=user_id,
                status=status,
                target_path=target_path,
                target_symbol=target_symbol,
                source_revision=source_revision,
                offset=offset,
                limit=limit,
            )

    def get_explanation(
        self,
        run_id: uuid.UUID | str,
        repository_id: Optional[uuid.UUID | str] = None,
        db: Optional[Session] = None,
    ) -> Optional[AnalysisRun]:
        """Get a specific explanation run by ID, optionally scoped to repository."""
        with self._get_session(db) as session:
            repo = AnalysisRunRepository(session)
            return repo.get_explanation_run(run_id, repository_id)

    def reopen_explanation(
        self,
        run_id: uuid.UUID | str,
        repository_id: Optional[uuid.UUID | str] = None,
        db: Optional[Session] = None,
    ) -> Optional[dict[str, Any]]:
        """Reopen a previous explanation run from persistent history (Scenario A Step 7)."""
        with self._get_session(db) as session:
            repo = AnalysisRunRepository(session)
            return repo.reopen_explanation(run_id, repository_id)

    def get_latest(
        self,
        repository_id: uuid.UUID | str,
        target_path: str,
        *,
        target_symbol: Optional[str] = None,
        source_revision: Optional[str] = None,
        status: str = AnalysisRunStatus.COMPLETED.value,
        db: Optional[Session] = None,
    ) -> Optional[AnalysisRun]:
        """Get the most recent completed explanation matching target coordinates."""
        with self._get_session(db) as session:
            repo = AnalysisRunRepository(session)
            return repo.get_latest_explanation(
                repository_id=repository_id,
                target_path=target_path,
                target_symbol=target_symbol,
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
        target_symbol: Optional[str] = None,
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
                feature_type=feature_type,
                status=status,
                target_path=target_path,
                target_symbol=target_symbol,
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
