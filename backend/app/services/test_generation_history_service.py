"""Test Generation History Service for Week 2 Day 4 (Developer Intelligence Suite).

Owner: Om — Database & Persistence.

Provides business-logic and session-managed orchestration for:
1. Persisting completed framework-aware test generation runs with dedicated `test_output` storage,
   scenarios, framework conventions, and source revision metadata.
2. Persisting failed test generation runs separately with descriptive error messages,
   strictly preventing generation failures from masquerading as valid test suites.
3. Preserving repository_id, target coordinates (file, symbol, 1-indexed inclusive line range),
   and source revision (git SHA or branch).
4. History retrieval with pagination, ordering (newest first), and multi-criteria filtering
   (by status, target_path, target_symbol, source_revision, framework).
5. Reopening past test generation runs from history with full fidelity (Scenario C Step 7).
6. Multi-tenant repository isolation: strictly enforcing repository boundary checks on all queries.
7. Protocol compatibility for `app.state.test_generation_history_service` and route handlers.
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


class TestGenerationHistoryService:
    """Service managing persistent history for Framework-Aware Test Generation runs."""

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
        raise RuntimeError("No database session or session_factory configured for TestGenerationHistoryService.")

    # -----------------------------------------------------------------------
    # 1. Save Completed & Failed Test Generation Runs
    # -----------------------------------------------------------------------

    def save_test_generation(
        self,
        repository_id: uuid.UUID | str,
        target_path: Optional[str] = None,
        test_result: Optional[Any] = None,
        *,
        test_output: Optional[str] = None,
        status: str = AnalysisRunStatus.COMPLETED.value,
        framework: Optional[str] = None,
        detected_framework: Optional[str] = None,
        proposed_test_path: Optional[str] = None,
        covered_scenarios: Optional[Sequence[Any]] = None,
        assumptions_and_warnings: Optional[Sequence[str]] = None,
        syntax_valid: bool = True,
        validation_errors: Optional[Sequence[str]] = None,
        sources: Optional[Sequence[Any]] = None,
        target_symbol: Optional[str] = None,
        start_line: Optional[int] = None,
        end_line: Optional[int] = None,
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
        """Store a completed or failed test generation run with rich metadata (Week 2 — Day 4)."""
        actual_framework = detected_framework or framework
        with self._get_session(db) as session:
            repo = AnalysisRunRepository(session)
            return repo.save_test_generation_run(
                repository_id=repository_id,
                target_path=target_path,
                test_result=test_result,
                test_output=test_output,
                status=status,
                detected_framework=actual_framework,
                proposed_test_path=proposed_test_path,
                covered_scenarios=covered_scenarios,
                assumptions_and_warnings=assumptions_and_warnings,
                syntax_valid=syntax_valid,
                validation_errors=validation_errors,
                sources=sources,
                target_symbol=target_symbol,
                start_line=start_line,
                end_line=end_line,
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
        target_path: Optional[str] = None,
        error_message: str = "Test generation failed during execution.",
        *,
        target_symbol: Optional[str] = None,
        start_line: Optional[int] = None,
        end_line: Optional[int] = None,
        source_revision: Optional[str] = None,
        user_id: Optional[uuid.UUID | str] = None,
        run_id: Optional[uuid.UUID | str] = None,
        target: Optional[Any] = None,
        db: Optional[Session] = None,
    ) -> AnalysisRun:
        """Store a failed test-generation run separately from successful output."""
        with self._get_session(db) as session:
            repo = AnalysisRunRepository(session)
            return repo.record_test_generation_failure(
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
    # 2. History Retrieval, Reopening & Filtering
    # -----------------------------------------------------------------------

    def list_history(
        self,
        repository_id: uuid.UUID | str,
        *,
        status: Optional[str] = None,
        target_path: Optional[str] = None,
        target_symbol: Optional[str] = None,
        framework: Optional[str] = None,
        source_revision: Optional[str] = None,
        user_id: Optional[uuid.UUID | str] = None,
        page: int = 1,
        page_size: int = 20,
        db: Optional[Session] = None,
    ) -> Tuple[List[AnalysisRun], int]:
        """List paginated test generation runs for an authorized repository, newest first."""
        offset = max(0, (page - 1) * page_size)
        with self._get_session(db) as session:
            repo = AnalysisRunRepository(session)
            return repo.list_test_generation_runs(
                repository_id,
                user_id=user_id,
                status=status,
                target_path=target_path,
                target_symbol=target_symbol,
                framework=framework,
                source_revision=source_revision,
                offset=offset,
                limit=page_size,
            )

    def get_run_by_id(
        self,
        run_id: uuid.UUID | str,
        repository_id: Optional[uuid.UUID | str] = None,
        db: Optional[Session] = None,
    ) -> Optional[AnalysisRun]:
        """Fetch a specific test generation run with repository isolation check."""
        with self._get_session(db) as session:
            repo = AnalysisRunRepository(session)
            return repo.get_test_generation_run(run_id, repository_id=repository_id)

    def reopen_run(
        self,
        run_id: uuid.UUID | str,
        repository_id: Optional[uuid.UUID | str] = None,
        db: Optional[Session] = None,
    ) -> Optional[dict[str, Any]]:
        """Reopen a test generation run from history matching TestGenerationResponse (Scenario C Step 7)."""
        with self._get_session(db) as session:
            repo = AnalysisRunRepository(session)
            return repo.reopen_test_generation(run_id, repository_id=repository_id)

    reopen_test_generation = reopen_run

    def get_latest(
        self,
        repository_id: uuid.UUID | str,
        target_path: str,
        *,
        target_symbol: Optional[str] = None,
        framework: Optional[str] = None,
        source_revision: Optional[str] = None,
        status: str = AnalysisRunStatus.COMPLETED.value,
        db: Optional[Session] = None,
    ) -> Optional[AnalysisRun]:
        """Get the most recent completed test generation run matching target coordinates."""
        with self._get_session(db) as session:
            repo = AnalysisRunRepository(session)
            return repo.get_latest_test_generation(
                repository_id=repository_id,
                target_path=target_path,
                target_symbol=target_symbol,
                framework=framework,
                source_revision=source_revision,
                status=status,
            )

    def find_duplicate_run(
        self,
        repository_id: uuid.UUID | str,
        target_path: str,
        *,
        target_symbol: Optional[str] = None,
        source_revision: Optional[str] = None,
        framework: Optional[str] = None,
        status: str = AnalysisRunStatus.COMPLETED.value,
        db: Optional[Session] = None,
    ) -> Optional[AnalysisRun]:
        """Check for duplicate completed test runs."""
        with self._get_session(db) as session:
            repo = AnalysisRunRepository(session)
            return repo.find_duplicate_test_generation(
                repository_id=repository_id,
                target_path=target_path,
                target_symbol=target_symbol,
                source_revision=source_revision,
                framework=framework,
                status=status,
            )

    def delete_run(
        self,
        run_id: uuid.UUID | str,
        repository_id: Optional[uuid.UUID | str] = None,
        db: Optional[Session] = None,
    ) -> bool:
        """Delete a test generation run with repository boundary check."""
        with self._get_session(db) as session:
            repo = AnalysisRunRepository(session)
            return repo.delete_test_generation_run(run_id, repository_id=repository_id)

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
                feature_type=feature_type or AnalysisFeature.GENERATE_TESTS.value,
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
