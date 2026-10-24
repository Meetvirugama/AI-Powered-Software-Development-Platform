"""Database query-layer for Analysis Runs and Findings (Week 2 — Day 1).

Owner: Om — Database & Persistence.
Provides repository methods for saving, querying, updating, and paginating
analysis runs and structured findings, strictly enforcing multi-tenant repository isolation.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, List, Optional, Sequence, Tuple

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session, selectinload

from app.models.analysis_finding import AnalysisFinding
from app.models.analysis_run import AnalysisFeature, AnalysisRun, AnalysisRunStatus


def _ensure_uuid(val: Any) -> Optional[uuid.UUID]:
    if val is None:
        return None
    if isinstance(val, uuid.UUID):
        return val
    try:
        return uuid.UUID(str(val))
    except (ValueError, TypeError):
        return None


def _ensure_datetime(val: Any) -> Optional[datetime]:
    if val is None:
        return None
    if isinstance(val, datetime):
        return val
    if isinstance(val, str):
        try:
            return datetime.fromisoformat(val.replace("Z", "+00:00"))
        except (ValueError, TypeError):
            return None
    return None


class AnalysisRunRepository:
    """Repository managing persistence for analysis runs and structured findings."""

    def __init__(self, session: Session) -> None:
        self.session = session

    # -----------------------------------------------------------------------
    # Create & Save
    # -----------------------------------------------------------------------

    def create_run(
        self,
        *,
        id: Optional[uuid.UUID | str] = None,
        repository_id: uuid.UUID | str,
        user_id: Optional[uuid.UUID | str] = None,
        feature_type: str,
        status: str = AnalysisRunStatus.PENDING.value,
        target_path: Optional[str] = None,
        target_symbol: Optional[str] = None,
        start_line: Optional[int] = None,
        end_line: Optional[int] = None,
        source_revision: Optional[str] = None,
        findings_count: int = 0,
        result_payload: Optional[dict[str, Any]] = None,
        test_output: Optional[str] = None,
        findings: Optional[Sequence[Any]] = None,
        error_message: Optional[str] = None,
        created_at: Optional[datetime | str] = None,
        completed_at: Optional[datetime | str] = None,
        **extra_kwargs: Any,
    ) -> AnalysisRun:
        """Create and persist an AnalysisRun, optionally with associated findings.

        Accepts both dict kwargs and explicit parameters.
        Handles UUID/datetime coercion and extracts test_output from result_payload if present.
        """
        run_uuid = _ensure_uuid(id) or uuid.uuid4()
        repo_uuid = _ensure_uuid(repository_id)
        if repo_uuid is None:
            raise ValueError(f"Invalid repository_id: {repository_id}")

        user_uuid = _ensure_uuid(user_id)
        if user_uuid is not None:
            from app.models.user import User
            try:
                if self.session.get(User, user_uuid) is None:
                    user_uuid = None
            except Exception:
                pass
        created_dt = _ensure_datetime(created_at) or datetime.now(timezone.utc)
        completed_dt = _ensure_datetime(completed_at)

        # If completed or failed status and completed_at is None, set to now
        if completed_dt is None and status in (
            AnalysisRunStatus.COMPLETED.value,
            AnalysisRunStatus.FAILED.value,
            AnalysisRunStatus.CANCELLED.value,
        ):
            completed_dt = datetime.now(timezone.utc)

        # Extract large test outputs if passed in payload or kwargs (top-level or nested under "result")
        if test_output is None and isinstance(result_payload, dict):
            test_output = (
                result_payload.get("test_content")
                or result_payload.get("complete_test_code")
                or result_payload.get("test_output")
                or (
                    result_payload.get("result", {}).get("test_content")
                    if isinstance(result_payload.get("result"), dict)
                    else None
                )
            )
            if test_output is None and isinstance(result_payload.get("result"), dict):
                test_output = (
                    result_payload["result"].get("test_content")
                    or result_payload["result"].get("complete_test_code")
                    or result_payload["result"].get("test_output")
                )

        # Normalize feature_type and status strings
        feat_val = feature_type.value if hasattr(feature_type, "value") else str(feature_type)
        status_val = status.value if hasattr(status, "value") else str(status)

        finding_items = list(findings or [])
        calculated_findings_count = findings_count or len(finding_items)

        existing_run = self.session.get(AnalysisRun, run_uuid)
        if existing_run is not None:
            existing_run.status = status_val
            existing_run.findings_count = calculated_findings_count
            if result_payload is not None:
                existing_run.result_payload = result_payload
            if test_output is not None:
                existing_run.test_output = test_output
            if error_message is not None:
                existing_run.error_message = error_message
            if completed_dt is not None:
                existing_run.completed_at = completed_dt
            if finding_items:
                for item in finding_items:
                    self._attach_finding_to_run(existing_run, item)
            self.session.commit()
            self.session.refresh(existing_run)
            return existing_run

        run = AnalysisRun(
            id=run_uuid,
            repository_id=repo_uuid,
            user_id=user_uuid,
            feature_type=feat_val,
            status=status_val,
            target_path=target_path,
            target_symbol=target_symbol,
            start_line=start_line,
            end_line=end_line,
            source_revision=source_revision,
            findings_count=calculated_findings_count,
            result_payload=result_payload,
            test_output=test_output,
            error_message=error_message,
            created_at=created_dt,
            completed_at=completed_dt,
        )

        self.session.add(run)

        # Persist associated structured findings
        if finding_items:
            for item in finding_items:
                self._attach_finding_to_run(run, item)

        self.session.commit()
        self.session.refresh(run)
        return run

    # Aliases for orchestrator compatibility
    create = create_run
    save = create_run

    def _attach_finding_to_run(self, run: AnalysisRun, item: Any) -> AnalysisFinding:
        """Helper to coerce a dict or Pydantic finding into an AnalysisFinding model."""
        if isinstance(item, AnalysisFinding):
            item.analysis_run_id = run.id
            item.repository_id = run.repository_id
            self.session.add(item)
            return item

        # Extract dictionary
        raw: dict[str, Any] = {}
        if hasattr(item, "model_dump"):
            raw = item.model_dump()
        elif hasattr(item, "dict"):
            raw = item.dict()
        elif isinstance(item, dict):
            raw = dict(item)

        finding_uuid = _ensure_uuid(raw.get("id")) or uuid.uuid4()
        source_ref = raw.get("source_reference") or {}
        if hasattr(source_ref, "model_dump"):
            source_ref = source_ref.model_dump()
        elif hasattr(source_ref, "dict"):
            source_ref = source_ref.dict()
        elif not isinstance(source_ref, dict):
            source_ref = {}

        file_path = raw.get("file_path") or source_ref.get("file_path") or run.target_path or "unknown"
        start_line = raw.get("start_line") if "start_line" in raw else source_ref.get("start_line")
        end_line = raw.get("end_line") if "end_line" in raw else source_ref.get("end_line")
        rev = raw.get("source_revision") or source_ref.get("revision") or run.source_revision
        sym = raw.get("symbol_name") or source_ref.get("symbol_name") or run.target_symbol

        finding = AnalysisFinding(
            id=finding_uuid,
            analysis_run_id=run.id,
            repository_id=run.repository_id,
            category=str(raw.get("category", "general")),
            severity=str(raw.get("severity", "MEDIUM")).upper(),
            title=str(raw.get("title", "Finding")),
            description=str(raw.get("description", "")),
            file_path=file_path,
            start_line=start_line,
            end_line=end_line,
            source_revision=rev,
            symbol_name=sym,
            evidence=str(raw.get("evidence", "")),
            suggested_fix=raw.get("suggested_fix"),
            confidence=str(raw.get("confidence", "medium")),
            is_uncertain=bool(raw.get("is_uncertain", False)),
            is_new_in_change=bool(raw.get("is_new_in_change", True)),
            source_type=str(raw.get("source_type", "AI")),
            rule_id=raw.get("rule_id"),
            finding_metadata=raw.get("metadata") or raw.get("finding_metadata"),
        )
        self.session.add(finding)
        return finding

    # -----------------------------------------------------------------------
    # Retrieval & Listing (Repository-Isolated)
    # -----------------------------------------------------------------------

    def get_by_id(self, run_id: uuid.UUID | str) -> Optional[AnalysisRun]:
        """Retrieve an AnalysisRun with eager-loaded findings by primary key ID."""
        r_uuid = _ensure_uuid(run_id)
        if r_uuid is None:
            return None

        stmt = (
            select(AnalysisRun)
            .where(AnalysisRun.id == r_uuid)
            .options(selectinload(AnalysisRun.findings))
        )
        return self.session.execute(stmt).scalar_one_or_none()

    # Alias matching AnalysisRunPersistenceProtocol
    get_run = get_by_id

    def get_by_id_and_repository(
        self,
        run_id: uuid.UUID | str,
        repository_id: uuid.UUID | str,
    ) -> Optional[AnalysisRun]:
        """Retrieve an AnalysisRun strictly enforcing repository scoping."""
        r_uuid = _ensure_uuid(run_id)
        repo_uuid = _ensure_uuid(repository_id)
        if r_uuid is None or repo_uuid is None:
            return None

        stmt = (
            select(AnalysisRun)
            .where(
                AnalysisRun.id == r_uuid,
                AnalysisRun.repository_id == repo_uuid,
            )
            .options(selectinload(AnalysisRun.findings))
        )
        return self.session.execute(stmt).scalar_one_or_none()

    def list_by_repository(
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
    ) -> Tuple[List[AnalysisRun], int]:
        """List paginated analysis runs for an authorized repository, ordered newest first.

        Returns (items, total_count).
        """
        repo_uuid = _ensure_uuid(repository_id)
        if repo_uuid is None:
            return [], 0

        stmt = select(AnalysisRun).where(AnalysisRun.repository_id == repo_uuid)

        if feature_type:
            feat_val = feature_type.value if hasattr(feature_type, "value") else str(feature_type)
            stmt = stmt.where(AnalysisRun.feature_type == feat_val)

        if status:
            status_val = status.value if hasattr(status, "value") else str(status)
            stmt = stmt.where(AnalysisRun.status == status_val)

        if target_path:
            stmt = stmt.where(AnalysisRun.target_path == target_path)

        if target_symbol:
            stmt = stmt.where(AnalysisRun.target_symbol == target_symbol)

        if source_revision:
            stmt = stmt.where(AnalysisRun.source_revision == source_revision)

        # Count query
        count_stmt = select(func.count()).select_from(stmt.subquery())
        total = self.session.scalar(count_stmt) or 0

        # Query paginated runs ordered by created_at descending
        ordered_stmt = (
            stmt.order_by(AnalysisRun.created_at.desc())
            .offset(offset)
            .limit(limit)
            .options(selectinload(AnalysisRun.findings))
        )
        items = list(self.session.scalars(ordered_stmt).all())
        return items, total

    # Alias matching AnalysisRunPersistenceProtocol
    list_runs = list_by_repository

    # -----------------------------------------------------------------------
    # Week 2 Day 2: Explanation History (Owner: Om)
    # -----------------------------------------------------------------------

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

    # -----------------------------------------------------------------------
    # Week 2 Day 3: Finding Persistence & Bug Scan History (Owner: Om)
    # -----------------------------------------------------------------------

    def _deduplicate_findings_data(self, findings: Sequence[Any]) -> list[dict[str, Any]]:
        """Deduplicate findings before persistence, combining STATIC and AI findings where appropriate.

        Owner: Om — Finding Persistence.
        Deduplication rule:
        Findings are considered identical if they target the same file, line range (or None),
        category, and rule_id or title.
        When duplicates occur:
        - If one is STATIC and one is AI, the merged finding has source_type="COMBINED"
        - The higher confidence is preserved ("high" > "medium" > "low")
        - Rule ID and suggested fix are retained
        - Evidence is combined if distinct
        """
        deduped: dict[tuple[Any, ...], dict[str, Any]] = {}
        for item in findings:
            raw: dict[str, Any] = {}
            if hasattr(item, "model_dump"):
                raw = item.model_dump()
            elif hasattr(item, "dict"):
                raw = item.dict()
            elif isinstance(item, dict):
                raw = dict(item)
            elif isinstance(item, AnalysisFinding):
                raw = item.to_dict()

            source_ref = raw.get("source_reference") or {}
            if hasattr(source_ref, "model_dump"):
                source_ref = source_ref.model_dump()
            elif hasattr(source_ref, "dict"):
                source_ref = source_ref.dict()
            elif not isinstance(source_ref, dict):
                source_ref = {}

            f_path = str(raw.get("file_path") or source_ref.get("file_path") or "").replace("\\", "/").strip().lower()
            s_line = raw.get("start_line") if "start_line" in raw else source_ref.get("start_line")
            e_line = raw.get("end_line") if "end_line" in raw else source_ref.get("end_line")
            cat = str(raw.get("category", "")).strip().lower()
            r_id = str(raw.get("rule_id") or "").strip().lower()
            t_title = str(raw.get("title", "")).strip().lower()

            key = (f_path, s_line, e_line, cat, r_id or t_title)

            if key not in deduped:
                deduped[key] = raw
            else:
                existing = deduped[key]
                # Merge source types: STATIC + AI -> COMBINED
                exist_type = str(existing.get("source_type", "AI")).upper()
                new_type = str(raw.get("source_type", "AI")).upper()
                if (exist_type == "STATIC" and new_type == "AI") or (exist_type == "AI" and new_type == "STATIC"):
                    existing["source_type"] = "COMBINED"
                elif exist_type != new_type and (exist_type == "COMBINED" or new_type == "COMBINED"):
                    existing["source_type"] = "COMBINED"

                # Merge confidence: prefer high > medium > low
                conf_weights = {"high": 3, "medium": 2, "low": 1}
                exist_conf = str(existing.get("confidence", "medium")).lower()
                new_conf = str(raw.get("confidence", "medium")).lower()
                if conf_weights.get(new_conf, 1) > conf_weights.get(exist_conf, 1):
                    existing["confidence"] = new_conf

                # Merge rule_id if missing in existing
                if not existing.get("rule_id") and raw.get("rule_id"):
                    existing["rule_id"] = raw.get("rule_id")

                # Merge suggested fix if missing
                if not existing.get("suggested_fix") and raw.get("suggested_fix"):
                    existing["suggested_fix"] = raw.get("suggested_fix")

                # Merge evidence
                exist_ev = str(existing.get("evidence", ""))
                new_ev = str(raw.get("evidence", ""))
                if new_ev and new_ev not in exist_ev:
                    existing["evidence"] = f"{exist_ev}\n{new_ev}".strip()

        return list(deduped.values())

    def save_bug_scan_run(
        self,
        *,
        repository_id: uuid.UUID | str,
        target_path: Optional[str] = None,
        findings: Optional[Sequence[Any]] = None,
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
        **extra_kwargs: Any,
    ) -> AnalysisRun:
        """Store a completed or failed bug detection scan with structured findings (Week 2 — Day 3).

        Owner: Om — Finding Persistence.
        Records:
        - repository_id (strictly scoped)
        - user_id (coerced and verified)
        - feature_type="detect_bugs"
        - status (COMPLETED or FAILED)
        - target coordinates (path, symbol, 1-indexed inclusive line range)
        - source revision (git commit SHA or branch name)
        - individual structured findings attached to this run
        - deduplication of duplicate findings and repeated identical scan requests
        - result_payload envelope with summary statistics
        - error_message (when status=FAILED, keeping failure distinct from 0 findings)
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

        repo_uuid = _ensure_uuid(repository_id)
        if repo_uuid is None:
            raise ValueError(f"Invalid repository_id: {repository_id}")

        status_val = status.value if hasattr(status, "value") else str(status).upper()

        # Idempotency / Duplicate scan check: if deduplicate_run is requested, reuse existing matching run
        if deduplicate_run and status_val == AnalysisRunStatus.COMPLETED.value:
            existing_run = self.find_duplicate_scan(
                repository_id=repo_uuid,
                target_path=t_path,
                target_symbol=t_symbol,
                start_line=s_line,
                end_line=e_line,
                source_revision=s_rev,
                status=status_val,
            )
            if existing_run is not None:
                return existing_run

        # Finding preparation and deduplication
        raw_findings = list(findings or [])
        if deduplicate_findings and raw_findings:
            raw_findings = self._deduplicate_findings_data(raw_findings)

        if status_val == AnalysisRunStatus.FAILED.value:
            if not error_message:
                error_message = "Bug detection scan failed."
            raw_findings = []
            findings_count = 0
            if result_payload is None:
                result_payload = {"error": error_message, "status": "FAILED"}
        else:
            error_message = None
            findings_count = len(raw_findings)
            if result_payload is None:
                static_count = sum(
                    1 for f in raw_findings
                    if (isinstance(f, dict) and f.get("source_type") in ("STATIC", "COMBINED"))
                    or (hasattr(f, "source_type") and getattr(f, "source_type") in ("STATIC", "COMBINED"))
                )
                ai_count = sum(
                    1 for f in raw_findings
                    if (isinstance(f, dict) and f.get("source_type") in ("AI", "COMBINED"))
                    or (hasattr(f, "source_type") and getattr(f, "source_type") in ("AI", "COMBINED"))
                )
                result_payload = {
                    "total_findings": findings_count,
                    "static_findings_count": static_count,
                    "ai_findings_count": ai_count,
                    "missing_context": list(missing_context or []),
                    "revision": s_rev,
                    "status": status_val,
                }

        return self.create_run(
            id=run_id,
            repository_id=repository_id,
            user_id=user_id,
            feature_type=AnalysisFeature.DETECT_BUGS.value,
            status=status_val,
            target_path=t_path,
            target_symbol=t_symbol,
            start_line=s_line,
            end_line=e_line,
            source_revision=s_rev,
            findings_count=findings_count,
            result_payload=result_payload,
            findings=raw_findings,
            error_message=error_message,
            created_at=created_at,
            completed_at=completed_at,
            **extra_kwargs,
        )

    def record_bug_scan_failure(
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
        """Record an explicit failed bug scan separately from successful zero-defect runs."""
        return self.save_bug_scan_run(
            repository_id=repository_id,
            target_path=target_path,
            findings=None,
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

    def find_duplicate_scan(
        self,
        *,
        repository_id: uuid.UUID | str,
        target_path: Optional[str] = None,
        target_symbol: Optional[str] = None,
        start_line: Optional[int] = None,
        end_line: Optional[int] = None,
        source_revision: Optional[str] = None,
        status: str = AnalysisRunStatus.COMPLETED.value,
    ) -> Optional[AnalysisRun]:
        """Find an existing completed bug detection run with identical coordinates to prevent duplicate scans."""
        repo_uuid = _ensure_uuid(repository_id)
        if repo_uuid is None:
            return None

        stmt = select(AnalysisRun).where(
            AnalysisRun.repository_id == repo_uuid,
            AnalysisRun.feature_type == AnalysisFeature.DETECT_BUGS.value,
            AnalysisRun.status == status,
        )

        if target_path:
            stmt = stmt.where(AnalysisRun.target_path == target_path)
        if target_symbol:
            stmt = stmt.where(AnalysisRun.target_symbol == target_symbol)
        if start_line is not None:
            stmt = stmt.where(AnalysisRun.start_line == start_line)
        if end_line is not None:
            stmt = stmt.where(AnalysisRun.end_line == end_line)
        if source_revision:
            stmt = stmt.where(AnalysisRun.source_revision == source_revision)

        stmt = stmt.order_by(AnalysisRun.created_at.desc()).options(selectinload(AnalysisRun.findings)).limit(1)
        return self.session.execute(stmt).scalar_one_or_none()

    def list_bug_scan_runs(
        self,
        repository_id: uuid.UUID | str,
        *,
        status: Optional[str] = None,
        target_path: Optional[str] = None,
        target_symbol: Optional[str] = None,
        source_revision: Optional[str] = None,
        min_severity: Optional[str] = None,
        category: Optional[str] = None,
        offset: int = 0,
        limit: int = 20,
    ) -> Tuple[List[AnalysisRun], int]:
        """List paginated bug scan runs for an authorized repository, newest first."""
        repo_uuid = _ensure_uuid(repository_id)
        if repo_uuid is None:
            return [], 0

        stmt = select(AnalysisRun).where(
            AnalysisRun.repository_id == repo_uuid,
            AnalysisRun.feature_type == AnalysisFeature.DETECT_BUGS.value,
        )

        if status:
            status_val = status.value if hasattr(status, "value") else str(status)
            stmt = stmt.where(AnalysisRun.status == status_val)
        if target_path:
            stmt = stmt.where(AnalysisRun.target_path == target_path)
        if target_symbol:
            stmt = stmt.where(AnalysisRun.target_symbol == target_symbol)
        if source_revision:
            stmt = stmt.where(AnalysisRun.source_revision == source_revision)

        if category or min_severity:
            finding_subq = select(AnalysisFinding.analysis_run_id).where(
                AnalysisFinding.repository_id == repo_uuid
            )
            if category:
                finding_subq = finding_subq.where(AnalysisFinding.category == category)
            if min_severity:
                sev_order = ["INFO", "LOW", "MEDIUM", "HIGH", "CRITICAL"]
                min_sev_idx = sev_order.index(min_severity.upper()) if min_severity.upper() in sev_order else 0
                allowed_sevs = sev_order[min_sev_idx:]
                finding_subq = finding_subq.where(AnalysisFinding.severity.in_(allowed_sevs))
            stmt = stmt.where(AnalysisRun.id.in_(finding_subq))

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

    def get_bug_scan_run(
        self,
        run_id: uuid.UUID | str,
        repository_id: Optional[uuid.UUID | str] = None,
    ) -> Optional[AnalysisRun]:
        """Retrieve a specific bug detection run with eager-loaded findings."""
        if repository_id is not None:
            run = self.get_by_id_and_repository(run_id, repository_id)
        else:
            run = self.get_by_id(run_id)

        if run is None or run.feature_type != AnalysisFeature.DETECT_BUGS.value:
            return None
        return run

    def reopen_bug_scan(
        self,
        run_id: uuid.UUID | str,
        repository_id: Optional[uuid.UUID | str] = None,
    ) -> Optional[dict[str, Any]]:
        """Reconstitute a bug scan run from persistent history (Scenario B Step 6).

        Returns a dictionary structure matching `BugDetectionResponse`:
        - run_id
        - repository_id
        - status (COMPLETED or FAILED)
        - target (AnalysisTarget dict with path, type, symbol, start_line, end_line)
        - revision
        - findings (list of structured finding dicts)
        - total_findings
        - static_findings_count
        - ai_findings_count
        - missing_context
        - error_message
        - created_at
        - completed_at
        """
        run = self.get_bug_scan_run(run_id, repository_id)
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

        findings_list = [f.to_dict() for f in run.findings]
        static_count = sum(1 for f in run.findings if f.source_type in ("STATIC", "COMBINED"))
        ai_count = sum(1 for f in run.findings if f.source_type in ("AI", "COMBINED"))

        missing_context: list[str] = []
        if run.result_payload and isinstance(run.result_payload, dict):
            missing_context = run.result_payload.get("missing_context") or []

        return {
            "run_id": str(run.id),
            "repository_id": str(run.repository_id),
            "status": run.status,
            "target": target_dict,
            "revision": run.source_revision,
            "findings": findings_list,
            "total_findings": len(findings_list),
            "static_findings_count": static_count,
            "ai_findings_count": ai_count,
            "missing_context": missing_context,
            "error_message": run.error_message,
            "created_at": run.created_at.isoformat() if run.created_at else None,
            "completed_at": run.completed_at.isoformat() if run.completed_at else None,
        }

    def get_latest_bug_scan(
        self,
        repository_id: uuid.UUID | str,
        target_path: str,
        *,
        target_symbol: Optional[str] = None,
        source_revision: Optional[str] = None,
        status: str = AnalysisRunStatus.COMPLETED.value,
    ) -> Optional[AnalysisRun]:
        """Fetch the most recent bug scan matching target file, symbol, and revision."""
        runs, _ = self.list_bug_scan_runs(
            repository_id,
            status=status,
            target_path=target_path,
            target_symbol=target_symbol,
            source_revision=source_revision,
            offset=0,
            limit=1,
        )
        return runs[0] if runs else None

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
        offset: int = 0,
        limit: int = 50,
    ) -> Tuple[List[AnalysisFinding], int]:
        """Directly query persisted findings for an authorized repository with rich filtering."""
        repo_uuid = _ensure_uuid(repository_id)
        if repo_uuid is None:
            return [], 0

        stmt = select(AnalysisFinding).where(AnalysisFinding.repository_id == repo_uuid)

        if file_path:
            stmt = stmt.where(AnalysisFinding.file_path == file_path)
        if category:
            stmt = stmt.where(AnalysisFinding.category == category)
        if severity:
            stmt = stmt.where(AnalysisFinding.severity == severity.upper())
        if source_type:
            stmt = stmt.where(AnalysisFinding.source_type == source_type.upper())
        if rule_id:
            stmt = stmt.where(AnalysisFinding.rule_id == rule_id)
        if source_revision:
            stmt = stmt.where(AnalysisFinding.source_revision == source_revision)

        run_uuid = _ensure_uuid(analysis_run_id)
        if run_uuid is not None:
            stmt = stmt.where(AnalysisFinding.analysis_run_id == run_uuid)

        count_stmt = select(func.count()).select_from(stmt.subquery())
        total = self.session.scalar(count_stmt) or 0

        ordered_stmt = (
            stmt.order_by(AnalysisFinding.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
        findings = list(self.session.scalars(ordered_stmt).all())
        return findings, total

    # -----------------------------------------------------------------------
    # Week 2 Day 4: Test Generation History (Owner: Om)
    # -----------------------------------------------------------------------

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
            prop_path_val = prop_path_val or d.get("proposed_test_path") or d.get("test_file_path")
            extracted_content = extracted_content or d.get("test_content") or d.get("code")
            if scenarios_val is None and "covered_scenarios" in d:
                scenarios_val = d.get("covered_scenarios") or d.get("scenarios_covered")
            if warnings_val is None and "assumptions_and_warnings" in d:
                warnings_val = d.get("assumptions_and_warnings") or d.get("assumptions")
            if "syntax_valid" in d:
                syntax_valid_val = bool(d.get("syntax_valid", True))
            if validation_errors_val is None and "validation_errors" in d:
                validation_errors_val = d.get("validation_errors") or d.get("validation_warnings")
            if sources_val is None and "sources" in d:
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
                    "detected_framework": framework_val,
                    "proposed_test_path": prop_path_val,
                    "test_content": final_test_output,
                    "covered_scenarios": scenarios_val or [],
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
        proposed_path = inner_res.get("proposed_test_path") or inner_res.get("test_file_path") or ""

        result_dict = {
            "detected_framework": framework,
            "proposed_test_path": proposed_path,
            "test_content": test_content,
            "covered_scenarios": inner_res.get("covered_scenarios") or inner_res.get("scenarios_covered") or [],
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

    # -----------------------------------------------------------------------
    # Status Updates & Findings Management
    # -----------------------------------------------------------------------

    def update_status(
        self,
        run_id: uuid.UUID | str,
        status: str,
        *,
        error_message: Optional[str] = None,
        result_payload: Optional[dict[str, Any]] = None,
        test_output: Optional[str] = None,
        completed_at: Optional[datetime] = None,
    ) -> Optional[AnalysisRun]:
        """Update lifecycle status and output payloads of an existing analysis run."""
        run = self.get_by_id(run_id)
        if run is None:
            return None

        status_val = status.value if hasattr(status, "value") else str(status)
        run.status = status_val

        if error_message is not None:
            run.error_message = error_message
        if result_payload is not None:
            run.result_payload = result_payload
        if test_output is not None:
            run.test_output = test_output

        if completed_at is not None:
            run.completed_at = completed_at
        elif status_val in (
            AnalysisRunStatus.COMPLETED.value,
            AnalysisRunStatus.FAILED.value,
            AnalysisRunStatus.CANCELLED.value,
        ):
            run.completed_at = datetime.now(timezone.utc)

        self.session.commit()
        self.session.refresh(run)
        return run

    def add_findings(
        self,
        run_id: uuid.UUID | str,
        findings: Sequence[Any],
    ) -> List[AnalysisFinding]:
        """Append findings to an existing analysis run and update its findings count."""
        run = self.get_by_id(run_id)
        if run is None:
            raise ValueError(f"AnalysisRun not found: {run_id}")

        added: list[AnalysisFinding] = []
        for item in findings:
            finding = self._attach_finding_to_run(run, item)
            added.append(finding)

        run.findings_count = (run.findings_count or 0) + len(added)
        self.session.commit()
        self.session.refresh(run)
        return added

    # -----------------------------------------------------------------------
    # Deletion (Cascade Cleanup)
    # -----------------------------------------------------------------------

    def delete(self, run_id: uuid.UUID | str) -> bool:
        """Delete an analysis run and its associated findings."""
        run = self.get_by_id(run_id)
        if run is None:
            return False

        self.session.delete(run)
        self.session.commit()
        return True

    def delete_by_repository(self, repository_id: uuid.UUID | str) -> int:
        """Delete all analysis runs and findings for a repository."""
        repo_uuid = _ensure_uuid(repository_id)
        if repo_uuid is None:
            return 0

        stmt = select(AnalysisRun.id).where(AnalysisRun.repository_id == repo_uuid)
        run_ids = list(self.session.scalars(stmt).all())
        if not run_ids:
            return 0

        self.session.execute(
            delete(AnalysisFinding).where(AnalysisFinding.repository_id == repo_uuid)
        )
        self.session.execute(
            delete(AnalysisRun).where(AnalysisRun.repository_id == repo_uuid)
        )
        self.session.commit()
        return len(run_ids)
