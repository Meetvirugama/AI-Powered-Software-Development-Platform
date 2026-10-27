"""Bug Scan History & Finding Persistence Service for Week 2 Day 3 (Developer Intelligence Suite).

Owner: Om — Database & Persistence.

Provides business-logic and session-managed orchestration for:
1. Persisting completed bug detection runs with concrete structured findings and source revision metadata.
2. Persisting failed bug scans separately from successful output with error messages,
   strictly preventing scan failures from masquerading as clean/zero-defect code.
3. Preserving repository_id, target coordinates (file, symbol, 1-indexed inclusive line range),
   and source revision (git SHA or branch).
4. Deduplicating duplicate finding records and repeated identical scan requests.
5. History retrieval with pagination, ordering (newest first), and multi-criteria filtering
   (by status, target_path, target_symbol, source_revision, min_severity, category).
6. Reopening past bug scan runs from history with full fidelity (Scenario B Step 6).
7. Direct querying of persisted findings across scans by file, category, severity, and rule_id.
8. Multi-tenant repository isolation: strictly enforcing repository boundary checks on all queries.
"""

from __future__ import annotations

import logging
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Generator, List, Optional, Sequence, Tuple

from sqlalchemy.orm import Session, sessionmaker

from app.models.analysis_finding import AnalysisFinding
from app.models.analysis_run import AnalysisFeature, AnalysisRun, AnalysisRunStatus
from app.repositories.analysis_run_repository import AnalysisRunRepository

logger = logging.getLogger(__name__)


class BugScanHistoryService:
    """Service managing persistent history for Bug Detection scans and structured findings."""

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
        raise RuntimeError("No database session or session_factory configured for BugScanHistoryService.")

    # -----------------------------------------------------------------------
    # 1. Save Completed & Failed Bug Scans (With Finding Persistence)
    # -----------------------------------------------------------------------

    def save_bug_scan(
        self,
        repository_id: uuid.UUID | str,
        target_path: Optional[str] = None,
        findings: Optional[Sequence[Any]] = None,
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
        result_payload: Optional[dict[str, Any]] = None,
        missing_context: Optional[Sequence[str]] = None,
        deduplicate_findings: bool = True,
        deduplicate_run: bool = False,
        created_at: Optional[datetime | str] = None,
        completed_at: Optional[datetime | str] = None,
        db: Optional[Session] = None,
    ) -> AnalysisRun:
        """Store a completed or failed bug detection scan with structured findings (Week 2 — Day 3)."""
        with self._get_session(db) as session:
            repo = AnalysisRunRepository(session)
            return repo.save_bug_scan_run(
                repository_id=repository_id,
                target_path=target_path,
                findings=findings,
                status=status,
                target_symbol=target_symbol,
                start_line=start_line,
                end_line=end_line,
                source_revision=source_revision,
                user_id=user_id,
                error_message=error_message,
                run_id=run_id,
                target=target,
                result_payload=result_payload,
                missing_context=missing_context,
                deduplicate_findings=deduplicate_findings,
                deduplicate_run=deduplicate_run,
                created_at=created_at,
                completed_at=completed_at,
            )

    # Alias matching Day 7 acceptance convention
    save_scan = save_bug_scan

    def record_failure(
        self,
        repository_id: uuid.UUID | str,
        error_message: str,
        *,
        target_path: Optional[str] = None,
        target_symbol: Optional[str] = None,
        start_line: Optional[int] = None,
        end_line: Optional[int] = None,
        source_revision: Optional[str] = None,
        user_id: Optional[uuid.UUID | str] = None,
        run_id: Optional[uuid.UUID | str] = None,
        target: Optional[Any] = None,
        db: Optional[Session] = None,
    ) -> AnalysisRun:
        """Record an explicit failed scan separately from clean zero-defect runs."""
        with self._get_session(db) as session:
            repo = AnalysisRunRepository(session)
            return repo.record_bug_scan_failure(
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
        min_severity: Optional[str] = None,
        category: Optional[str] = None,
        user_id: Optional[uuid.UUID | str] = None,
        page: int = 1,
        page_size: int = 20,
        db: Optional[Session] = None,
    ) -> Tuple[List[AnalysisRun], int]:
        """List paginated bug scan history for an authorized repository, ordered newest first."""
        offset = max(0, (page - 1) * page_size)
        with self._get_session(db) as session:
            repo = AnalysisRunRepository(session)
            return repo.list_bug_scan_runs(
                repository_id=repository_id,
                user_id=user_id,
                status=status,
                target_path=target_path,
                target_symbol=target_symbol,
                source_revision=source_revision,
                min_severity=min_severity,
                category=category,
                offset=offset,
                limit=page_size,
            )

    def get_scan(
        self,
        run_id: uuid.UUID | str,
        repository_id: Optional[uuid.UUID | str] = None,
        db: Optional[Session] = None,
    ) -> Optional[AnalysisRun]:
        """Retrieve a specific bug scan run with findings, enforcing repository boundary check."""
        with self._get_session(db) as session:
            repo = AnalysisRunRepository(session)
            return repo.get_bug_scan_run(run_id, repository_id=repository_id)

    def reopen(
        self,
        run_id: uuid.UUID | str,
        repository_id: Optional[uuid.UUID | str] = None,
        db: Optional[Session] = None,
    ) -> Optional[dict[str, Any]]:
        """Reopen and reconstitute a past bug scan from history (Scenario B Step 6)."""
        with self._get_session(db) as session:
            repo = AnalysisRunRepository(session)
            return repo.reopen_bug_scan(run_id, repository_id=repository_id)

    reopen_bug_scan = reopen
    reopen_scan = reopen

    def get_latest_scan(
        self,
        repository_id: uuid.UUID | str,
        target_path: str,
        *,
        target_symbol: Optional[str] = None,
        source_revision: Optional[str] = None,
        status: str = AnalysisRunStatus.COMPLETED.value,
        db: Optional[Session] = None,
    ) -> Optional[AnalysisRun]:
        """Fetch the most recent scan matching target file, symbol, and source revision."""
        with self._get_session(db) as session:
            repo = AnalysisRunRepository(session)
            return repo.get_latest_bug_scan(
                repository_id=repository_id,
                target_path=target_path,
                target_symbol=target_symbol,
                source_revision=source_revision,
                status=status,
            )

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
        page: int = 1,
        page_size: int = 50,
        db: Optional[Session] = None,
    ) -> Tuple[List[AnalysisFinding], int]:
        """Directly query persisted findings for an authorized repository."""
        offset = max(0, (page - 1) * page_size)
        with self._get_session(db) as session:
            repo = AnalysisRunRepository(session)
            return repo.list_findings(
                repository_id=repository_id,
                file_path=file_path,
                category=category,
                severity=severity,
                source_type=source_type,
                rule_id=rule_id,
                analysis_run_id=analysis_run_id,
                source_revision=source_revision,
                offset=offset,
                limit=page_size,
            )

    def find_existing_scan(
        self,
        repository_id: uuid.UUID | str,
        target_path: Optional[str] = None,
        *,
        target_symbol: Optional[str] = None,
        start_line: Optional[int] = None,
        end_line: Optional[int] = None,
        source_revision: Optional[str] = None,
        status: str = AnalysisRunStatus.COMPLETED.value,
        db: Optional[Session] = None,
    ) -> Optional[AnalysisRun]:
        """Check if an identical scan has already been executed for idempotency."""
        with self._get_session(db) as session:
            repo = AnalysisRunRepository(session)
            return repo.find_duplicate_scan(
                repository_id=repository_id,
                target_path=target_path,
                target_symbol=target_symbol,
                start_line=start_line,
                end_line=end_line,
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
        user_id: Optional[uuid.UUID | str] = None,
        offset: int = 0,
        limit: int = 20,
        db: Optional[Session] = None,
    ) -> Tuple[List[AnalysisRun], int]:
        """Compatible with GET /repositories/{id}/analysis-runs."""
        with self._get_session(db) as session:
            repo = AnalysisRunRepository(session)
            return repo.list_by_repository(
                repository_id=repository_id,
                user_id=user_id,
                feature_type=feature_type or AnalysisFeature.DETECT_BUGS.value,
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
