"""Test generation run persistence, history, and reopen aggregate."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, List, Optional, Sequence, Tuple

from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from app.models.analysis_run import AnalysisFeature, AnalysisRun, AnalysisRunStatus
from app.repositories.analysis.base import (
    _ensure_uuid,
)

from app.repositories.analysis.core import AnalysisCoreMixin


class TestGenerationRunMixin:
    """Test Generation history operations."""

    def save_test_generation_run(
        self,
        *,
        repository_id: uuid.UUID | str,
        target_path: Optional[str] = None,
        test_result: Optional[Any] = None,
        test_output: Optional[str] = None,
        status: str = AnalysisRunStatus.COMPLETED.value,
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
        **extra_kwargs: Any,
    ) -> AnalysisRun:
        """Store a completed or failed test generation run with rich metadata (Week 2 — Day 4).

        Owner: Om — Test Generation History.
        Records:
        - repository_id (strictly scoped)
        - user_id (coerced and verified)
        - feature_type="generate_tests"
        - status (COMPLETED or FAILED)
        - target coordinates (path, symbol, 1-indexed inclusive line range)
        - source revision (git commit SHA or branch name)
        - test_output: Dedicated storage for large generated test files (Postgres TOAST)
        - result_payload: Structured TestGenerationResult payload including detected framework,
          proposed test path, covered scenarios, assumptions/warnings, syntax validity, and sources.
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

        # Unpack test_result if provided
        framework_val = detected_framework
        prop_path_val = proposed_test_path
        scenarios_val = list(covered_scenarios) if covered_scenarios is not None else None
        warnings_val = list(assumptions_and_warnings) if assumptions_and_warnings is not None else None
        syntax_valid_val = syntax_valid
        validation_errors_val = list(validation_errors) if validation_errors is not None else None
        sources_val = list(sources) if sources is not None else None
        extracted_content = test_output

        if test_result is not None:
            # Handle TestGenerationResponse wrapper
            inner_res = test_result
            if hasattr(test_result, "result"):
                inner_res = getattr(test_result, "result")
            elif isinstance(test_result, dict) and "result" in test_result:
                inner_res = test_result["result"]

            if hasattr(inner_res, "model_dump"):
                d = inner_res.model_dump(mode="json")
            elif hasattr(inner_res, "dict"):
                d = inner_res.dict()
            elif isinstance(inner_res, dict):
                d = dict(inner_res)
            else:
                d = {}

            framework_val = framework_val or d.get("detected_framework") or d.get("framework")
            prop_path_val = prop_path_val or d.get("proposed_test_path") or d.get("test_file_path") or d.get("test_path")
            extracted_content = extracted_content or d.get("test_content") or d.get("code")
            if scenarios_val is None:
                scenarios_val = d.get("covered_scenarios") or d.get("scenarios_covered") or d.get("scenarios")
            if warnings_val is None:
                warnings_val = d.get("assumptions_and_warnings") or d.get("assumptions")
            if "syntax_valid" in d:
                syntax_valid_val = bool(d.get("syntax_valid", True))
            if validation_errors_val is None:
                validation_errors_val = d.get("validation_errors") or d.get("validation_warnings")
            if sources_val is None:
                sources_val = d.get("sources")

        status_val = status.value if hasattr(status, "value") else str(status).upper()
        if status_val == AnalysisRunStatus.FAILED.value:
            if not error_message:
                error_message = "Test generation failed during execution."
            payload = result_payload or {"error": error_message, "status": "FAILED"}
            final_test_output = None
        else:
            error_message = None
            final_test_output = extracted_content or test_output
            if result_payload is not None:
                payload = dict(result_payload)
            else:
                payload = {
                    "framework": framework_val,
                    "detected_framework": framework_val,
                    "proposed_test_path": prop_path_val,
                    "test_path": prop_path_val,
                    "test_content": final_test_output,
                    "covered_scenarios": scenarios_val or [],
                    "scenarios": scenarios_val or [],
                    "assumptions_and_warnings": warnings_val or [],
                    "syntax_valid": syntax_valid_val,
                    "validation_errors": validation_errors_val or [],
                    "sources": sources_val or [],
                }

        return self.create_run(
            id=run_id,
            repository_id=repository_id,
            user_id=user_id,
            feature_type=AnalysisFeature.GENERATE_TESTS.value,
            status=status_val,
            target_path=t_path,
            target_symbol=t_symbol,
            start_line=s_line,
            end_line=e_line,
            source_revision=s_rev,
            findings_count=0,
            result_payload=payload,
            test_output=final_test_output,
            error_message=error_message,
            created_at=created_at,
            completed_at=completed_at,
            **extra_kwargs,
        )

    def record_test_generation_failure(
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
        """Record an explicit failed test-generation run separately from successful output."""
        return self.save_test_generation_run(
            repository_id=repository_id,
            target_path=target_path,
            test_result=None,
            test_output=None,
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

    def list_test_generation_runs(
        self,
        repository_id: uuid.UUID | str,
        *,
        user_id: Optional[uuid.UUID | str] = None,
        status: Optional[str] = None,
        target_path: Optional[str] = None,
        target_symbol: Optional[str] = None,
        framework: Optional[str] = None,
        source_revision: Optional[str] = None,
        offset: int = 0,
        limit: int = 20,
    ) -> Tuple[List[AnalysisRun], int]:
        """List paginated test generation runs for an authorized repository, newest first."""
        repo_uuid = _ensure_uuid(repository_id)
        if repo_uuid is None:
            return [], 0

        stmt = select(AnalysisRun).where(
            AnalysisRun.repository_id == repo_uuid,
            AnalysisRun.feature_type == AnalysisFeature.GENERATE_TESTS.value,
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

        if framework:
            stmt = stmt.where(
                func.coalesce(
                    AnalysisRun.result_payload["detected_framework"].astext,
                    AnalysisRun.result_payload["framework"].astext,
                    AnalysisRun.result_payload["result"]["detected_framework"].astext,
                ) == framework
            )

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

    def get_test_generation_run(
        self,
        run_id: uuid.UUID | str,
        repository_id: Optional[uuid.UUID | str] = None,
    ) -> Optional[AnalysisRun]:
        """Retrieve a specific test generation run, enforcing repository scoping if provided."""
        if repository_id is not None:
            run = self.get_by_id_and_repository(run_id, repository_id)
        else:
            run = self.get_by_id(run_id)

        if run is None or run.feature_type != AnalysisFeature.GENERATE_TESTS.value:
            return None
        return run

    def reopen_test_generation(
        self,
        run_id: uuid.UUID | str,
        repository_id: Optional[uuid.UUID | str] = None,
    ) -> Optional[dict[str, Any]]:
        """Reconstitute a test generation run from persistent history (Scenario C Step 7).

        Returns a dictionary structure matching TestGenerationResponse:
        - run_id
        - repository_id
        - status (COMPLETED or FAILED)
        - target (AnalysisTarget dict with path, type, symbol, start_line, end_line, revision)
        - revision
        - result (structured TestGenerationResult dict)
        - test_output (dedicated full test source code)
        - error_message (if failed)
        - created_at
        - completed_at
        """
        run = self.get_test_generation_run(run_id, repository_id)
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

        raw_payload = run.result_payload or {}
        if "result" in raw_payload and isinstance(raw_payload["result"], dict):
            inner_res = raw_payload["result"]
        else:
            inner_res = raw_payload

        test_content = run.test_output or inner_res.get("test_content") or inner_res.get("code") or ""
        framework = inner_res.get("detected_framework") or inner_res.get("framework") or "pytest"
        proposed_path = (
            inner_res.get("proposed_test_path")
            or inner_res.get("test_file_path")
            or inner_res.get("test_path")
            or ""
        )

        result_dict = {
            "framework": framework,
            "detected_framework": framework,
            "proposed_test_path": proposed_path,
            "test_path": proposed_path,
            "test_content": test_content,
            "covered_scenarios": inner_res.get("covered_scenarios") or inner_res.get("scenarios") or inner_res.get("scenarios_covered") or [],
            "scenarios": inner_res.get("scenarios") or inner_res.get("covered_scenarios") or [],
            "assumptions_and_warnings": inner_res.get("assumptions_and_warnings") or inner_res.get("assumptions") or [],
            "syntax_valid": inner_res.get("syntax_valid", True),
            "validation_errors": inner_res.get("validation_errors") or inner_res.get("validation_warnings") or [],
            "sources": inner_res.get("sources") or [],
        }

        return {
            "run_id": str(run.id),
            "repository_id": str(run.repository_id),
            "status": run.status,
            "target": target_dict,
            "revision": run.source_revision,
            "result": result_dict,
            "framework": framework,
            "test_content": run.test_output or test_content,
            "scenarios": result_dict.get("covered_scenarios") or inner_res.get("scenarios") or [],
            "test_output": run.test_output or test_content,
            "error_message": run.error_message,
            "created_at": run.created_at.isoformat() if run.created_at else None,
            "completed_at": run.completed_at.isoformat() if run.completed_at else None,
        }

    def get_latest_test_generation(
        self,
        repository_id: uuid.UUID | str,
        target_path: str,
        *,
        target_symbol: Optional[str] = None,
        framework: Optional[str] = None,
        source_revision: Optional[str] = None,
        status: str = AnalysisRunStatus.COMPLETED.value,
    ) -> Optional[AnalysisRun]:
        """Fetch the most recent test generation run matching target file, symbol, framework, and revision."""
        runs, _ = self.list_test_generation_runs(
            repository_id,
            status=status,
            target_path=target_path,
            target_symbol=target_symbol,
            framework=framework,
            source_revision=source_revision,
            offset=0,
            limit=1,
        )
        return runs[0] if runs else None

    def find_duplicate_test_generation(
        self,
        repository_id: uuid.UUID | str,
        target_path: str,
        *,
        target_symbol: Optional[str] = None,
        source_revision: Optional[str] = None,
        framework: Optional[str] = None,
        status: str = AnalysisRunStatus.COMPLETED.value,
    ) -> Optional[AnalysisRun]:
        """Check for an existing identical completed test generation run to prevent duplicate AI runs."""
        return self.get_latest_test_generation(
            repository_id,
            target_path=target_path,
            target_symbol=target_symbol,
            framework=framework,
            source_revision=source_revision,
            status=status,
        )

    def delete_test_generation_run(
        self,
        run_id: uuid.UUID | str,
        repository_id: Optional[uuid.UUID | str] = None,
    ) -> bool:
        """Delete a test generation run enforcing repository boundary check."""
        run = self.get_test_generation_run(run_id, repository_id)
        if run is None:
            return False
        self.session.delete(run)
        self.session.commit()
        return True


class TestGenerationRunRepository(TestGenerationRunMixin, AnalysisCoreMixin):
    """Standalone domain aggregate for test generation history."""
