"""Analysis Run History Service for Week 2 Day 6 (Integration, Accuracy and Security Hardening).

Owner: Om — Database & Persistence.

Provides a unified business-logic and session-managed service layer for all analysis runs:
1. Unified lifecycle management across all 4 developer intelligence capabilities:
   - Code Explanation (explain)
   - Dedicated Bug Detection (detect_bugs)
   - Framework-Aware Test Generation (generate_tests)
   - Standalone AI Code Review (code_review / review)
2. History querying with pagination, multi-criteria filtering, and newest-first sorting.
3. Multi-tenant repository isolation: strictly enforcing repository boundary checks.
4. Database integrity verification: identifying orphaned findings, desynchronized counts,
   and status timestamp inconsistencies.
5. Repository-level run & finding metrics aggregation (get_run_summary).
6. Protocol compliance for `app.state.analysis_run_service` and route handlers.
"""

from __future__ import annotations

import logging
import uuid
from contextlib import contextmanager
from typing import Any, Generator, List, Optional, Tuple

from sqlalchemy.orm import Session, sessionmaker

from app.models.analysis_run import AnalysisRun, AnalysisRunStatus
from app.repositories.analysis_run_repository import AnalysisRunRepository

logger = logging.getLogger(__name__)


class AnalysisRunHistoryService:
    """Unified service managing persistent history, queries, and database integrity for all analysis runs."""

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
        raise RuntimeError("No database session or session_factory configured for AnalysisRunHistoryService.")

    # -----------------------------------------------------------------------
    # 1. Record / Create Run (Generic & Orchestrator Protocol)
    # -----------------------------------------------------------------------

    def record_run(
        self,
        record: dict[str, Any],
        db: Optional[Session] = None,
    ) -> AnalysisRun:
        """Persist an analysis run record from orchestrator dispatch (Week 2 — Day 6)."""
        with self._get_session(db) as session:
            repo = AnalysisRunRepository(session)
            return repo.create_run(**record)

    def save_run(
        self,
        record: dict[str, Any],
        db: Optional[Session] = None,
    ) -> AnalysisRun:
        """Alias for record_run to satisfy orchestrator interface conventions."""
        return self.record_run(record, db=db)

    # -----------------------------------------------------------------------
    # 2. History Query & Multi-Criteria Filtering
    # -----------------------------------------------------------------------

    def list_runs(
        self,
        repository_id: uuid.UUID | str,
        *,
        user_id: Optional[uuid.UUID | str] = None,
        feature_type: Optional[str] = None,
        status: Optional[str] = None,
        target_path: Optional[str] = None,
        source_revision: Optional[str] = None,
        offset: int = 0,
        limit: int = 20,
        db: Optional[Session] = None,
    ) -> Tuple[List[AnalysisRun], int]:
        """List historical analysis runs scoped to a repository with filtering and pagination.

        Normalizes feature type aliases ('bugs' -> 'detect_bugs', 'tests' -> 'generate_tests', 'review' -> 'code_review').
        Supports user-level scoping via user_id.
        """
        normalized_feature = feature_type
        if feature_type == "bugs":
            normalized_feature = "detect_bugs"
        elif feature_type == "tests":
            normalized_feature = "generate_tests"
        elif feature_type == "code_review":
            normalized_feature = "review"

        with self._get_session(db) as session:
            repo = AnalysisRunRepository(session)
            return repo.list_by_repository(
                repository_id,
                user_id=user_id,
                feature_type=normalized_feature,
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
        """Retrieve a specific analysis run with its structured findings eagerly loaded.

        Enforces multi-tenant boundary checks if repository_id is supplied.
        """
        with self._get_session(db) as session:
            repo = AnalysisRunRepository(session)
            if repository_id is not None:
                return repo.get_by_id_and_repository(run_id, repository_id)
            return repo.get_by_id(run_id)

    # -----------------------------------------------------------------------
    # 3. Deletion (Cascade Cleanup with Tenant Isolation)
    # -----------------------------------------------------------------------

    def delete_run(
        self,
        run_id: uuid.UUID | str,
        repository_id: Optional[uuid.UUID | str] = None,
        db: Optional[Session] = None,
    ) -> bool:
        """Delete an analysis run and cascade to all its findings."""
        with self._get_session(db) as session:
            repo = AnalysisRunRepository(session)
            return repo.delete_run(run_id, repository_id=repository_id)

    def delete_repository_runs(
        self,
        repository_id: uuid.UUID | str,
        db: Optional[Session] = None,
    ) -> int:
        """Purge all analysis runs and findings for a deleted repository."""
        with self._get_session(db) as session:
            repo = AnalysisRunRepository(session)
            return repo.delete_by_repository(repository_id)

    # -----------------------------------------------------------------------
    # 4. Metrics Aggregation & Database Integrity
    # -----------------------------------------------------------------------

    def get_run_summary(
        self,
        repository_id: uuid.UUID | str,
        db: Optional[Session] = None,
    ) -> dict[str, Any]:
        """Aggregate total runs, breakdowns by feature/status, and findings metrics."""
        with self._get_session(db) as session:
            repo = AnalysisRunRepository(session)
            return repo.get_run_summary(repository_id)

    def verify_integrity(
        self,
        repository_id: Optional[uuid.UUID | str] = None,
        db: Optional[Session] = None,
    ) -> dict[str, Any]:
        """Verify database integrity across analysis runs and findings (Day 6 deliverable)."""
        with self._get_session(db) as session:
            repo = AnalysisRunRepository(session)
            return repo.verify_integrity(repository_id=repository_id)

    # -----------------------------------------------------------------------
    # 5. Duplicate Check / Idempotency
    # -----------------------------------------------------------------------

    def find_duplicate(
        self,
        repository_id: uuid.UUID | str,
        feature_type: str,
        *,
        target_path: Optional[str] = None,
        target_symbol: Optional[str] = None,
        start_line: Optional[int] = None,
        end_line: Optional[int] = None,
        source_revision: Optional[str] = None,
        options: Optional[dict[str, Any]] = None,
        db: Optional[Session] = None,
    ) -> Optional[AnalysisRun]:
        """Find an existing completed analysis run matching coordinates and options."""
        normalized_feat = feature_type
        if feature_type == "bugs":
            normalized_feat = "detect_bugs"
        elif feature_type == "tests":
            normalized_feat = "generate_tests"
        elif feature_type == "review":
            normalized_feat = "code_review"

        with self._get_session(db) as session:
            repo = AnalysisRunRepository(session)
            if normalized_feat == "detect_bugs":
                return repo.find_duplicate_scan(
                    repository_id=repository_id,
                    target_path=target_path,
                    target_symbol=target_symbol,
                    start_line=start_line,
                    end_line=end_line,
                    source_revision=source_revision,
                )
            elif normalized_feat == "generate_tests":
                framework = (options or {}).get("framework") if options else None
                return repo.find_duplicate_test_generation(
                    repository_id,
                    target_path or "",
                    target_symbol=target_symbol,
                    source_revision=source_revision,
                    framework=framework,
                )
            elif normalized_feat in ("code_review", "review"):
                commit_sha = (options or {}).get("commit_sha") if options else None
                pr_num = (options or {}).get("pr_number") if options else None
                return repo.find_duplicate_review(
                    repository_id,
                    target_path=target_path,
                    source_revision=source_revision,
                    commit_sha=commit_sha,
                    pr_number=pr_num,
                )
            else:
                # Code explanation
                runs, _ = repo.list_by_repository(
                    repository_id,
                    feature_type="explain",
                    status=AnalysisRunStatus.COMPLETED.value,
                    target_path=target_path,
                    source_revision=source_revision,
                    limit=1,
                )
                return runs[0] if runs else None

    # -----------------------------------------------------------------------
    # 6. Data Retention & Sensitive-Data Handling (Week 2 — Day 7)
    # -----------------------------------------------------------------------

    def purge_expired_runs(
        self,
        *,
        repository_id: Optional[uuid.UUID | str] = None,
        retention_days: int = 30,
        feature_type: Optional[str] = None,
        status: Optional[str] = None,
        db: Optional[Session] = None,
    ) -> int:
        """Purge historical analysis runs and cascading findings older than retention_days (Day 7)."""
        with self._get_session(db) as session:
            repo = AnalysisRunRepository(session)
            return repo.purge_expired_runs(
                repository_id=repository_id,
                retention_days=retention_days,
                feature_type=feature_type,
                status=status,
            )

    def prune_uncompleted_stale_runs(
        self,
        *,
        older_than_hours: int = 24,
        mark_as_failed: bool = True,
        repository_id: Optional[uuid.UUID | str] = None,
        db: Optional[Session] = None,
    ) -> int:
        """Prune or time-out stuck PENDING or RUNNING runs older than specified hours (Day 7)."""
        with self._get_session(db) as session:
            repo = AnalysisRunRepository(session)
            return repo.prune_uncompleted_stale_runs(
                older_than_hours=older_than_hours,
                mark_as_failed=mark_as_failed,
                repository_id=repository_id,
            )

    def get_retention_metrics(
        self,
        repository_id: Optional[uuid.UUID | str] = None,
        db: Optional[Session] = None,
    ) -> dict[str, Any]:
        """Aggregate data retention metrics across all runs or scoped to a repository (Day 7)."""
        with self._get_session(db) as session:
            repo = AnalysisRunRepository(session)
            return repo.get_retention_metrics(repository_id=repository_id)

    def sanitize_sensitive_data_in_history(
        self,
        repository_id: Optional[uuid.UUID | str] = None,
        db: Optional[Session] = None,
    ) -> int:
        """Audit and scrub any raw credentials or sensitive tokens from persisted history (Day 7)."""
        with self._get_session(db) as session:
            repo = AnalysisRunRepository(session)
            return repo.sanitize_sensitive_data_in_history(repository_id=repository_id)
