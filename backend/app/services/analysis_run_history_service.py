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
from typing import Any, List, Optional, Tuple

from sqlalchemy.orm import Session

from app.models.analysis_run import AnalysisRun, AnalysisRunStatus
from app.repositories.analysis_run_repository import AnalysisRunRepository
from app.services.history.base import BaseHistoryService

logger = logging.getLogger(__name__)


class AnalysisRunHistoryService(BaseHistoryService):
    """Unified service managing persistent history, queries, and database integrity for all analysis runs."""

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

    # -----------------------------------------------------------------------
    # 7. Evaluation Dataset Export (Issue #195)
    # -----------------------------------------------------------------------

    def export_evaluation_records(
        self,
        repository_id: uuid.UUID | str,
        *,
        feature_type: Optional[str] = None,
        status: Optional[str] = None,
        include_feedback_only: bool = False,
        limit: int = 1000,
        db: Optional[Session] = None,
    ) -> list[dict[str, Any]]:
        """Extract structured evaluation records for regression datasets (Issue #195).

        Formats runs, findings, and attached user feedback into standardized evaluation samples
        suitable for regression testing and evaluation pipelines (e.g. Langfuse datasets).
        """
        import json
        from app.schemas.analysis import normalize_analysis_feature_type

        normalized_feature = None
        if feature_type:
            raw_feat = getattr(feature_type, "value", feature_type)
            try:
                normalized_feature = normalize_analysis_feature_type(str(raw_feat))
            except ValueError:
                normalized_feature = str(raw_feat)

        with self._get_session(db) as session:
            repo = AnalysisRunRepository(session)
            runs, _ = repo.list_by_repository(
                repository_id,
                feature_type=normalized_feature,
                status=status,
                offset=0,
                limit=limit,
            )

            records: list[dict[str, Any]] = []
            for run in runs:
                feat = (
                    getattr(run, "feature_type", None)
                    or (run.get("feature_type") if isinstance(run, dict) else "explain")
                )
                if hasattr(feat, "value"):
                    feat = feat.value
                try:
                    normalized_feat = normalize_analysis_feature_type(str(feat)) or feat
                except ValueError:
                    normalized_feat = feat

                stat = (
                    getattr(run, "status", None)
                    or (run.get("status") if isinstance(run, dict) else "COMPLETED")
                )
                if hasattr(stat, "value"):
                    stat = stat.value

                # Extract findings and look for feedback
                finding_items: list[dict[str, Any]] = []
                feedback_entries: list[dict[str, Any]] = []
                feedback_counts: dict[str, int] = {}

                raw_findings = (
                    getattr(run, "findings", None)
                    or (run.get("findings") if isinstance(run, dict) else [])
                    or []
                )

                for f in raw_findings:
                    if isinstance(f, dict):
                        meta = f.get("finding_metadata") or f.get("metadata") or {}
                        f_id = str(f.get("id", ""))
                        cat = f.get("category", "general")
                        sev = f.get("severity", "MEDIUM")
                        title = f.get("title", "")
                        desc = f.get("description", "")
                        file_path = f.get("file_path", "")
                        s_line = f.get("start_line")
                        e_line = f.get("end_line")
                        rev = f.get("source_revision")
                        sym = f.get("symbol_name")
                        evid = f.get("evidence", "")
                        sug_fix = f.get("suggested_fix")
                        conf = f.get("confidence", "medium")
                        is_unc = bool(f.get("is_uncertain", False))
                        is_new = bool(f.get("is_new_in_change", True))
                        src_type = f.get("source_type", "AI")
                        rule_id = f.get("rule_id")
                    else:
                        meta = getattr(f, "finding_metadata", None) or {}
                        f_id = str(getattr(f, "id", ""))
                        cat = getattr(f, "category", "general")
                        sev = getattr(f, "severity", "MEDIUM")
                        title = getattr(f, "title", "")
                        desc = getattr(f, "description", "")
                        file_path = getattr(f, "file_path", "")
                        s_line = getattr(f, "start_line", None)
                        e_line = getattr(f, "end_line", None)
                        rev = getattr(f, "source_revision", None)
                        sym = getattr(f, "symbol_name", None)
                        evid = getattr(f, "evidence", "")
                        sug_fix = getattr(f, "suggested_fix", None)
                        conf = getattr(f, "confidence", "medium")
                        is_unc = bool(getattr(f, "is_uncertain", False))
                        is_new = bool(getattr(f, "is_new_in_change", True))
                        src_type = getattr(f, "source_type", "AI")
                        rule_id = getattr(f, "rule_id", None)

                    if not isinstance(meta, dict) and hasattr(meta, "to_dict"):
                        meta = meta.to_dict()
                    elif not isinstance(meta, dict):
                        meta = {}

                    fb = meta.get("feedback")
                    if fb and isinstance(fb, dict):
                        feedback_entries.append(fb)
                        fb_type = str(fb.get("feedback_type", "unspecified")).lower()
                        feedback_counts[fb_type] = feedback_counts.get(fb_type, 0) + 1

                    finding_dict = {
                        "id": f_id,
                        "category": cat,
                        "severity": sev,
                        "title": title,
                        "description": desc,
                        "file_path": file_path,
                        "start_line": s_line,
                        "end_line": e_line,
                        "source_revision": rev,
                        "symbol_name": sym,
                        "evidence": evid,
                        "suggested_fix": sug_fix,
                        "confidence": conf,
                        "is_uncertain": is_unc,
                        "is_new_in_change": is_new,
                        "source_type": src_type,
                        "rule_id": rule_id,
                        "feedback": fb,
                    }
                    finding_items.append(finding_dict)

                # Check for run-level feedback in result_payload
                res_payload = (
                    getattr(run, "result_payload", None)
                    or (run.get("result_payload") if isinstance(run, dict) else {})
                    or {}
                )
                if isinstance(res_payload, dict):
                    run_fb = res_payload.get("feedback") or res_payload.get("user_feedback")
                    if run_fb and isinstance(run_fb, dict):
                        feedback_entries.append(run_fb)
                        fb_type = str(run_fb.get("feedback_type", "unspecified")).lower()
                        feedback_counts[fb_type] = feedback_counts.get(fb_type, 0) + 1

                has_feedback = len(feedback_entries) > 0
                if include_feedback_only and not has_feedback:
                    continue

                created_dt = getattr(run, "created_at", None) or (run.get("created_at") if isinstance(run, dict) else None)
                completed_dt = getattr(run, "completed_at", None) or (run.get("completed_at") if isinstance(run, dict) else None)
                duration_sec: Optional[float] = None
                if created_dt and completed_dt and hasattr(completed_dt, "__sub__"):
                    try:
                        duration_sec = round((completed_dt - created_dt).total_seconds(), 3)
                    except Exception:
                        duration_sec = None

                run_id = str(getattr(run, "id", None) or (run.get("id") if isinstance(run, dict) else ""))
                run_repo_id = str(getattr(run, "repository_id", None) or (run.get("repository_id") if isinstance(run, dict) else repository_id))
                target_path = getattr(run, "target_path", None) or (run.get("target_path") if isinstance(run, dict) else None)
                target_symbol = getattr(run, "target_symbol", None) or (run.get("target_symbol") if isinstance(run, dict) else None)
                start_line = getattr(run, "start_line", None) or (run.get("start_line") if isinstance(run, dict) else None)
                end_line = getattr(run, "end_line", None) or (run.get("end_line") if isinstance(run, dict) else None)
                source_revision = getattr(run, "source_revision", None) or (run.get("source_revision") if isinstance(run, dict) else None)
                findings_count = getattr(run, "findings_count", None) or (run.get("findings_count") if isinstance(run, dict) else len(finding_items))
                test_output = getattr(run, "test_output", None) or (run.get("test_output") if isinstance(run, dict) else None)
                error_msg = getattr(run, "error_message", None) or (run.get("error_message") if isinstance(run, dict) else None)

                from app.core.secret_redaction import redact, redact_obj

                record = {
                    "id": run_id,
                    "repository_id": run_repo_id,
                    "feature_type": normalized_feat,
                    "status": stat,
                    "input": {
                        "target_path": target_path,
                        "target_symbol": target_symbol,
                        "start_line": start_line,
                        "end_line": end_line,
                        "source_revision": source_revision,
                    },
                    "output": {
                        "findings_count": findings_count if findings_count is not None else len(finding_items),
                        "result_payload": redact_obj(res_payload),
                        "test_output": redact(test_output) if test_output else None,
                    },
                    "findings": redact_obj(finding_items),
                    "feedback_summary": redact_obj({
                        "has_feedback": has_feedback,
                        "total_feedback": len(feedback_entries),
                        "by_type": feedback_counts,
                        "entries": feedback_entries,
                    }),
                    "metadata": {
                        "created_at": created_dt.isoformat() if hasattr(created_dt, "isoformat") else str(created_dt or ""),
                        "completed_at": completed_dt.isoformat() if hasattr(completed_dt, "isoformat") else (str(completed_dt) if completed_dt else None),
                        "duration_seconds": duration_sec,
                        "error_message": redact(error_msg) if error_msg else None,
                    },
                }
                records.append(record)

            return records

    def export_evaluation_dataset(
        self,
        repository_id: uuid.UUID | str,
        *,
        format: str = "jsonl",
        feature_type: Optional[str] = None,
        status: Optional[str] = None,
        include_feedback_only: bool = False,
        limit: int = 1000,
        db: Optional[Session] = None,
    ) -> str | list[dict[str, Any]]:
        """Export analysis runs and feedback as a dataset in JSONL, JSON, or Langfuse format (Issue #195).

        Supported formats:
        - 'jsonl': Newline-delimited JSON string (standard for regression datasets)
        - 'json': Pretty-formatted JSON string array
        - 'langfuse' / 'langfuse_jsonl': Newline-delimited JSON formatted for Langfuse dataset items (input, expected_output, metadata)
        - 'langfuse_json': Formatted JSON array for Langfuse datasets
        - 'records': Raw Python list of dictionaries
        """
        import json

        records = self.export_evaluation_records(
            repository_id,
            feature_type=feature_type,
            status=status,
            include_feedback_only=include_feedback_only,
            limit=limit,
            db=db,
        )

        fmt = (format or "jsonl").strip().lower()
        if fmt == "jsonl":
            return "\n".join(json.dumps(r, default=str) for r in records)
        elif fmt == "json":
            return json.dumps(records, default=str, indent=2)
        elif fmt in ("langfuse", "langfuse_jsonl", "langfuse-jsonl"):
            langfuse_items = []
            for r in records:
                langfuse_items.append({
                    "id": r["id"],
                    "input": {
                        "feature_type": r["feature_type"],
                        **r["input"],
                    },
                    "expected_output": {
                        "findings_count": r["output"]["findings_count"],
                        "findings": r["findings"],
                        "result_payload": r["output"]["result_payload"],
                        "test_output": r["output"]["test_output"],
                    },
                    "metadata": {
                        "repository_id": r["repository_id"],
                        "status": r["status"],
                        "feedback_summary": r["feedback_summary"],
                        **r["metadata"],
                    },
                })
            return "\n".join(json.dumps(item, default=str) for item in langfuse_items)
        elif fmt in ("langfuse_json", "langfuse-json"):
            langfuse_items = []
            for r in records:
                langfuse_items.append({
                    "id": r["id"],
                    "input": {
                        "feature_type": r["feature_type"],
                        **r["input"],
                    },
                    "expected_output": {
                        "findings_count": r["output"]["findings_count"],
                        "findings": r["findings"],
                        "result_payload": r["output"]["result_payload"],
                        "test_output": r["output"]["test_output"],
                    },
                    "metadata": {
                        "repository_id": r["repository_id"],
                        "status": r["status"],
                        "feedback_summary": r["feedback_summary"],
                        **r["metadata"],
                    },
                })
            return json.dumps(langfuse_items, default=str, indent=2)
        elif fmt == "records":
            return records
        else:
            raise ValueError(
                f"Unsupported dataset export format '{format}'. Supported: 'jsonl', 'json', 'langfuse', 'records'"
            )
