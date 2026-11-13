"""Code explanation run persistence, retrieval, and reopen aggregate."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, List, Optional, Tuple


from app.models.analysis_run import AnalysisFeature, AnalysisRun, AnalysisRunStatus

from app.repositories.analysis.core import AnalysisCoreMixin


class ExplanationRunMixin:
    """Code Explanation history operations."""

    def save_explanation_run(
        self,
        *,
        repository_id: uuid.UUID | str,
        target_path: Optional[str] = None,
        explanation: Optional[Any] = None,
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
        **extra_kwargs: Any,
    ) -> AnalysisRun:
        """Store a completed or failed code explanation run with rich metadata (Week 2 — Day 2).

        Owner: Om — Explanation History.
        Records:
        - repository_id (strictly scoped)
        - user_id (coerced and verified)
        - feature_type="explain"
        - status (COMPLETED or FAILED)
        - target coordinates (path, symbol, 1-indexed inclusive line range)
        - source revision (git commit SHA or branch name)
        - structured result payload (purpose, logic flow, key symbols, inputs/outputs, dependencies, limitations, sources)
        - error_message (when status=FAILED)
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

        payload: Optional[dict[str, Any]] = None
        if explanation is not None:
            if hasattr(explanation, "model_dump"):
                payload = explanation.model_dump(mode="json")
            elif hasattr(explanation, "dict"):
                payload = explanation.dict()
            elif isinstance(explanation, dict):
                payload = dict(explanation)

        status_val = status.value if hasattr(status, "value") else str(status).upper()
        if status_val == AnalysisRunStatus.FAILED.value:
            if not error_message:
                error_message = "Code explanation failed during execution."
            # Store failure status separately; do not invent a fake explanation payload
            if payload and "explanation" in payload:
                payload = {"error": error_message}
        elif status_val == AnalysisRunStatus.COMPLETED.value:
            error_message = None

        return self.create_run(
            id=run_id,
            repository_id=repository_id,
            user_id=user_id,
            feature_type=AnalysisFeature.EXPLAIN.value,
            status=status_val,
            target_path=t_path,
            target_symbol=t_symbol,
            start_line=s_line,
            end_line=e_line,
            source_revision=s_rev,
            findings_count=0,
            result_payload=payload,
            error_message=error_message,
            created_at=created_at,
            completed_at=completed_at,
            **extra_kwargs,
        )

    def record_explanation_failure(
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
        """Record an explicit failed explanation run separately from successful output."""
        return self.save_explanation_run(
            repository_id=repository_id,
            target_path=target_path,
            explanation=None,
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

    def list_explanation_runs(
        self,
        repository_id: uuid.UUID | str,
        *,
        user_id: Optional[uuid.UUID | str] = None,
        status: Optional[str] = None,
        target_path: Optional[str] = None,
        target_symbol: Optional[str] = None,
        source_revision: Optional[str] = None,
        offset: int = 0,
        limit: int = 20,
    ) -> Tuple[List[AnalysisRun], int]:
        """List paginated explanation runs for an authorized repository, newest first."""
        return self.list_by_repository(
            repository_id,
            user_id=user_id,
            feature_type=AnalysisFeature.EXPLAIN.value,
            status=status,
            target_path=target_path,
            target_symbol=target_symbol,
            source_revision=source_revision,
            offset=offset,
            limit=limit,
        )

    def get_explanation_run(
        self,
        run_id: uuid.UUID | str,
        repository_id: Optional[uuid.UUID | str] = None,
    ) -> Optional[AnalysisRun]:
        """Retrieve a specific explanation run, enforcing repository scoping if provided."""
        if repository_id is not None:
            run = self.get_by_id_and_repository(run_id, repository_id)
        else:
            run = self.get_by_id(run_id)

        if run is None or run.feature_type != AnalysisFeature.EXPLAIN.value:
            return None
        return run

    def reopen_explanation(
        self,
        run_id: uuid.UUID | str,
        repository_id: Optional[uuid.UUID | str] = None,
    ) -> Optional[dict[str, Any]]:
        """Reconstitute an explanation run from persistent history (Scenario A Step 7).

        Returns a dictionary structure matching `CodeExplanationResponse`:
        - run_id
        - repository_id
        - status (COMPLETED or FAILED)
        - target (AnalysisTarget dict with path, type, symbol, start_line, end_line)
        - revision
        - explanation (structured CodeExplanation payload)
        - error_message (if failed)
        - created_at
        - completed_at
        """
        run = self.get_explanation_run(run_id, repository_id)
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

        explanation_data: Optional[dict[str, Any]] = None
        if run.result_payload:
            if "explanation" in run.result_payload:
                explanation_data = run.result_payload["explanation"]
            else:
                explanation_data = run.result_payload

        return {
            "run_id": str(run.id),
            "repository_id": str(run.repository_id),
            "status": run.status,
            "target": target_dict,
            "revision": run.source_revision,
            "explanation": explanation_data,
            "error_message": run.error_message,
            "created_at": run.created_at.isoformat() if run.created_at else None,
            "completed_at": run.completed_at.isoformat() if run.completed_at else None,
        }

    def get_latest_explanation(
        self,
        repository_id: uuid.UUID | str,
        target_path: str,
        *,
        target_symbol: Optional[str] = None,
        source_revision: Optional[str] = None,
        status: str = AnalysisRunStatus.COMPLETED.value,
    ) -> Optional[AnalysisRun]:
        """Fetch the most recent explanation run matching file, symbol, and optional revision."""
        runs, _ = self.list_explanation_runs(
            repository_id,
            status=status,
            target_path=target_path,
            target_symbol=target_symbol,
            source_revision=source_revision,
            offset=0,
            limit=1,
        )
        return runs[0] if runs else None


class ExplanationRunRepository(ExplanationRunMixin, AnalysisCoreMixin):
    """Standalone domain aggregate for code explanation history."""
