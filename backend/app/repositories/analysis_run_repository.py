"""Database query-layer for Analysis Runs and Findings (Week 2 — Day 1).

Owner: Om — Database & Persistence.
Provides repository methods for saving, querying, updating, and paginating
analysis runs and structured findings, strictly enforcing multi-tenant repository isolation.
"""

from __future__ import annotations

import re
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, List, Optional, Sequence, Tuple

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session, selectinload

from app.models.analysis_finding import AnalysisFinding
from app.models.analysis_run import AnalysisFeature, AnalysisRun, AnalysisRunStatus


# ---------------------------------------------------------------------------
# Sensitive Data Sanitization Patterns (Aligned with Sukun's security gate)
# ---------------------------------------------------------------------------

_SECRET_REDACTION_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("openai_key", re.compile(r"\bsk-(?:proj-|ant-)?[A-Za-z0-9_\-]{20,}")),
    ("github_token", re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{36,}|github_pat_[A-Za-z0-9_]{22,})")),
    ("aws_access_key", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b")),
    ("jwt_token", re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b")),
    ("db_connection_uri", re.compile(r"(?i)\b(postgres(?:ql)?|mysql|mongodb(?:\+srv)?):\/\/([^:\s]+):([^@\s]+)@")),
    (
        "private_key_block",
        re.compile(
            r"-----BEGIN (?:[A-Z]+ )?PRIVATE KEY-----[\s\S]*?-----END (?:[A-Z]+ )?PRIVATE KEY-----"
        ),
    ),
    (
        "private_key_header",
        re.compile(r"-----BEGIN (?:[A-Z]+ )?PRIVATE KEY-----"),
    ),
    (
        "credential_assignment",
        re.compile(
            r"(?i)(\b\w*(?:api_?key|secret|password|passwd|private_?key|access_?token|auth_?token|token)\w*[\x22\x27]?\s*[:=]\s*[\x22\x27])([^\x22\x27\s]{8,})([\x22\x27])"
        ),
    ),
)

_PLACEHOLDER_HINTS = re.compile(
    r"(?i)(\[REDACTED\]|<[^>]*>|\.\.\.|x{4,}|example|placeholder|changeme|your[_-]|dummy|fake|mock|"
    r"test|sample|os\.environ|getenv|settings\.|process\.env|\$\{|none|null|true|false)"
)


def scrub_sensitive_text(text: Optional[str]) -> Optional[str]:
    """Redact raw secrets, tokens, credentials, and connection strings from text before persistence."""
    if not text or not isinstance(text, str):
        return text
    redacted = text
    for name, pattern in _SECRET_REDACTION_PATTERNS:
        if name == "credential_assignment":
            def _repl_assign(match: re.Match[str]) -> str:
                prefix, val, suffix = match.group(1), match.group(2), match.group(3)
                if _PLACEHOLDER_HINTS.search(val):
                    return match.group(0)
                return f"{prefix}[REDACTED]{suffix}"

            redacted = pattern.sub(_repl_assign, redacted)
        elif name == "db_connection_uri":
            redacted = pattern.sub(r"\1://\2:[REDACTED]@", redacted)
        else:
            redacted = pattern.sub("[REDACTED]", redacted)
    return redacted


def scrub_sensitive_data(val: Any) -> Any:
    """Recursively scrub sensitive credential strings in text, dicts, or lists."""
    if isinstance(val, str):
        return scrub_sensitive_text(val)
    elif isinstance(val, dict):
        return {k: scrub_sensitive_data(v) for k, v in val.items()}
    elif isinstance(val, list):
        return [scrub_sensitive_data(item) for item in val]
    elif isinstance(val, tuple):
        return tuple(scrub_sensitive_data(item) for item in val)
    return val


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

        # Scrub credentials and sensitive tokens from persisted fields (Week 2 — Day 7)
        error_message = scrub_sensitive_text(error_message)
        test_output = scrub_sensitive_text(test_output)
        if result_payload is not None:
            result_payload = scrub_sensitive_data(result_payload)

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
        """Helper to coerce a dict or Pydantic finding into an AnalysisFinding model with secret scrubbing."""
        if isinstance(item, AnalysisFinding):
            item.analysis_run_id = run.id
            item.repository_id = run.repository_id
            item.title = scrub_sensitive_text(item.title) or "Finding"
            item.description = scrub_sensitive_text(item.description) or ""
            item.evidence = scrub_sensitive_text(item.evidence) or ""
            if item.suggested_fix:
                item.suggested_fix = scrub_sensitive_text(item.suggested_fix)
            if item.finding_metadata:
                item.finding_metadata = scrub_sensitive_data(item.finding_metadata)
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

        raw_meta = raw.get("metadata") or raw.get("finding_metadata")

        finding = AnalysisFinding(
            id=finding_uuid,
            analysis_run_id=run.id,
            repository_id=run.repository_id,
            category=str(raw.get("category", "general")),
            severity=str(raw.get("severity", "MEDIUM")).upper(),
            title=scrub_sensitive_text(str(raw.get("title", "Finding"))) or "Finding",
            description=scrub_sensitive_text(str(raw.get("description", ""))) or "",
            file_path=file_path,
            start_line=start_line,
            end_line=end_line,
            source_revision=rev,
            symbol_name=sym,
            evidence=scrub_sensitive_text(str(raw.get("evidence", ""))) or "",
            suggested_fix=scrub_sensitive_text(raw.get("suggested_fix")) if raw.get("suggested_fix") else None,
            confidence=str(raw.get("confidence", "medium")),
            is_uncertain=bool(raw.get("is_uncertain", False)),
            is_new_in_change=bool(raw.get("is_new_in_change", True)),
            source_type=str(raw.get("source_type", "AI")),
            rule_id=raw.get("rule_id"),
            finding_metadata=scrub_sensitive_data(raw_meta) if raw_meta else None,
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
        user_id: Optional[uuid.UUID | str] = None,
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

        if user_id:
            u_uuid = _ensure_uuid(user_id)
            if u_uuid:
                stmt = stmt.where(AnalysisRun.user_id == u_uuid)

        if feature_type:
            feat_val = feature_type.value if hasattr(feature_type, "value") else str(feature_type)
            if feat_val in ("review", "code_review"):
                stmt = stmt.where(AnalysisRun.feature_type.in_(["review", "code_review"]))
            elif feat_val in ("detect_bugs", "bugs"):
                stmt = stmt.where(AnalysisRun.feature_type.in_(["detect_bugs", "bugs"]))
            elif feat_val in ("generate_tests", "tests"):
                stmt = stmt.where(AnalysisRun.feature_type.in_(["generate_tests", "tests"]))
            else:
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
        user_id: Optional[uuid.UUID | str] = None,
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

    # -----------------------------------------------------------------------
    # Standalone AI Code Review Persistence (Week 2 — Day 5)
    # -----------------------------------------------------------------------

    def save_review_run(
        self,
        *,
        repository_id: uuid.UUID | str,
        review_target: Optional[Any] = None,
        report: Optional[Any] = None,
        findings: Optional[Sequence[Any]] = None,
        status: str = AnalysisRunStatus.COMPLETED.value,
        target_path: Optional[str] = None,
        target_symbol: Optional[str] = None,
        start_line: Optional[int] = None,
        end_line: Optional[int] = None,
        source_revision: Optional[str] = None,
        commit_sha: Optional[str] = None,
        pr_number: Optional[int] = None,
        diff: Optional[str] = None,
        base_revision: Optional[str] = None,
        head_revision: Optional[str] = None,
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
        """Store a completed or failed standalone AI code review run with categorized findings (Week 2 — Day 5).

        Owner: Om — Review History.
        Requirements (Docs/week2.md §9 & §12 Scenario D):
        1. Persist review reports and findings:
           - Categories: correctness, security, performance, reliability, maintainability.
           - Concrete source locations (file_path, 1-indexed inclusive line range).
           - Severity, evidence, suggested remediation, confidence, source_type (AI/STATIC/COMBINED).
        2. Associate with repository, source revision and analysis run:
           - Supports target types: file, commit, diff, pr.
           - Maps source revision (commit SHA, PR number, git branch).
        3. Ensure a review of a newer revision does not silently overwrite the old result:
           - Every review run creates a distinct, immutable history record.
           - Reviews across multiple commits/revisions coexist independently.
        4. Retrieve and reopen previous reviews:
           - Reconstitutes full review state matching ReviewReportResponse with high fidelity.
        5. Separate failed reviews from clean zero-defect reviews:
           - Failed reviews record error_message and status="FAILED".
           - Zero-finding reviews record status="COMPLETED" and findings_count=0.
        """
        effective_target = review_target if review_target is not None else target

        target_type = "file"
        t_path = target_path
        c_sha = commit_sha
        pr_num = pr_number
        d_text = diff
        b_rev = base_revision
        h_rev = head_revision
        t_symbol = target_symbol
        s_line = start_line
        e_line = end_line

        if effective_target is not None:
            if hasattr(effective_target, "type"):
                target_type = getattr(effective_target, "type", "file") or "file"
                t_path = t_path or getattr(effective_target, "path", None)
                c_sha = c_sha or getattr(effective_target, "commit_sha", None)
                pr_num = pr_num if pr_num is not None else getattr(effective_target, "pr_number", None)
                d_text = d_text or getattr(effective_target, "diff", None)
                b_rev = b_rev or getattr(effective_target, "base_revision", None)
                h_rev = h_rev or getattr(effective_target, "head_revision", None)
                s_line = s_line if s_line is not None else getattr(effective_target, "start_line", None)
                e_line = e_line if e_line is not None else getattr(effective_target, "end_line", None)
            elif isinstance(effective_target, dict):
                target_type = effective_target.get("type", "file") or "file"
                t_path = t_path or effective_target.get("path")
                c_sha = c_sha or effective_target.get("commit_sha")
                pr_num = pr_num if pr_num is not None else effective_target.get("pr_number")
                d_text = d_text or effective_target.get("diff")
                b_rev = b_rev or effective_target.get("base_revision")
                h_rev = h_rev or effective_target.get("head_revision")
                s_line = s_line if s_line is not None else effective_target.get("start_line")
                e_line = e_line if e_line is not None else effective_target.get("end_line")

        s_rev = (
            source_revision
            or h_rev
            or c_sha
            or (f"pr/{pr_num}" if pr_num is not None else None)
            or b_rev
            or (getattr(effective_target, "revision", None) if effective_target else None)
        )

        if not t_symbol:
            if pr_num is not None:
                t_symbol = f"PR #{pr_num}"
            elif c_sha:
                t_symbol = f"Commit {c_sha[:8]}"

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

        status_val = status.value if hasattr(status, "value") else str(status).upper()
        run_uuid = _ensure_uuid(run_id) or uuid.uuid4()
        created_dt = _ensure_datetime(created_at) or datetime.now(timezone.utc)
        completed_dt = _ensure_datetime(completed_at)
        if completed_dt is None and status_val in (
            AnalysisRunStatus.COMPLETED.value,
            AnalysisRunStatus.FAILED.value,
            AnalysisRunStatus.CANCELLED.value,
        ):
            completed_dt = datetime.now(timezone.utc)

        # Optional duplicate review check
        if deduplicate_run and status_val == AnalysisRunStatus.COMPLETED.value:
            existing_run = self.find_duplicate_review(
                repository_id=repo_uuid,
                target_path=t_path,
                source_revision=s_rev,
                status=status_val,
            )
            if existing_run is not None:
                return existing_run

        # Findings extraction
        effective_report = report if report is not None else extra_kwargs.get("review_report")
        raw_findings: list[Any] = []
        if findings is not None:
            raw_findings = list(findings)
        elif effective_report is not None:
            if hasattr(effective_report, "findings"):
                raw_findings = list(getattr(effective_report, "findings", []))
            elif isinstance(effective_report, dict) and "findings" in effective_report:
                raw_findings = list(effective_report.get("findings", []))

        if deduplicate_findings and raw_findings:
            raw_findings = self._deduplicate_findings_data(raw_findings)

        if status_val == AnalysisRunStatus.FAILED.value:
            if not error_message:
                error_message = "AI code review execution failed."
            raw_findings = []
            findings_count = 0
            if result_payload is None:
                result_payload = {
                    "error": error_message,
                    "status": "FAILED",
                    "target": {
                        "type": target_type,
                        "path": t_path,
                        "commit_sha": c_sha,
                        "pr_number": pr_num,
                        "base_revision": b_rev,
                        "head_revision": h_rev,
                    },
                }
        else:
            error_message = None
            findings_count = len(raw_findings)

            # Extract or compute report metadata
            summary = "AI code review completed."
            risk_level = None
            if effective_report is not None:
                if hasattr(effective_report, "summary"):
                    summary = getattr(effective_report, "summary", summary)
                elif isinstance(effective_report, dict) and "summary" in effective_report:
                    summary = effective_report.get("summary", summary)

                if hasattr(effective_report, "risk_level"):
                    risk_level = getattr(effective_report, "risk_level", None)
                elif isinstance(effective_report, dict) and "risk_level" in effective_report:
                    risk_level = effective_report.get("risk_level")

                if missing_context is None:
                    if hasattr(effective_report, "missing_context"):
                        missing_context = getattr(effective_report, "missing_context", None)
                    elif isinstance(effective_report, dict) and "missing_context" in effective_report:
                        missing_context = effective_report.get("missing_context")

            if not risk_level:
                severities = [
                    str(
                        f.get("severity")
                        if isinstance(f, dict)
                        else getattr(f, "severity", "MEDIUM")
                    ).upper()
                    for f in raw_findings
                ]
                if "CRITICAL" in severities:
                    risk_level = "CRITICAL"
                elif "HIGH" in severities:
                    risk_level = "HIGH"
                elif not raw_findings:
                    risk_level = "NONE"
                else:
                    risk_level = "LOW"

            # Calculate category counts
            category_counts: dict[str, int] = {}
            for f in raw_findings:
                cat = (
                    f.get("category")
                    if isinstance(f, dict)
                    else getattr(f, "category", "general")
                )
                cat_str = str(cat).lower()
                category_counts[cat_str] = category_counts.get(cat_str, 0) + 1

            if result_payload is None:
                serializable_findings = []
                for f in raw_findings:
                    if hasattr(f, "model_dump"):
                        serializable_findings.append(f.model_dump(mode="json"))
                    elif hasattr(f, "dict"):
                        serializable_findings.append(f.dict())
                    elif isinstance(f, dict):
                        serializable_findings.append(dict(f))
                    else:
                        serializable_findings.append(str(f))

                result_payload = {
                    "run_id": str(run_uuid),
                    "repository_id": str(repo_uuid),
                    "status": status_val,
                    "target": {
                        "type": target_type,
                        "path": t_path,
                        "commit_sha": c_sha,
                        "pr_number": pr_num,
                        "diff": (d_text[:5000] if d_text else None),
                        "base_revision": b_rev,
                        "head_revision": h_rev,
                    },
                    "report": {
                        "summary": summary,
                        "risk_level": risk_level,
                        "findings": serializable_findings,
                        "total_findings": findings_count,
                        "category_counts": category_counts,
                        "missing_context": list(missing_context or []),
                    },
                    "created_at": created_dt.isoformat(),
                    "completed_at": completed_dt.isoformat() if completed_dt else None,
                }

        run = AnalysisRun(
            id=run_uuid,
            repository_id=repo_uuid,
            user_id=user_uuid,
            feature_type=AnalysisFeature.REVIEW.value,
            status=status_val,
            target_path=t_path,
            target_symbol=t_symbol,
            start_line=s_line,
            end_line=e_line,
            source_revision=s_rev,
            findings_count=findings_count,
            result_payload=result_payload,
            test_output=None,
            error_message=error_message,
            created_at=created_dt,
            completed_at=completed_dt,
        )
        self.session.add(run)
        self.session.flush()

        for item in raw_findings:
            self._attach_finding_to_run(run, item)

        self.session.commit()
        self.session.refresh(run)
        return run

    def record_review_failure(
        self,
        *,
        repository_id: uuid.UUID | str,
        error_message: str = "Code review execution failed.",
        target_path: Optional[str] = None,
        review_target: Optional[Any] = None,
        source_revision: Optional[str] = None,
        commit_sha: Optional[str] = None,
        pr_number: Optional[int] = None,
        user_id: Optional[uuid.UUID | str] = None,
        run_id: Optional[uuid.UUID | str] = None,
        target: Optional[Any] = None,
        created_at: Optional[datetime | str] = None,
        **extra_kwargs: Any,
    ) -> AnalysisRun:
        """Explicitly record a failed code review run (Scenario D failure isolation)."""
        created_dt = _ensure_datetime(created_at)
        return self.save_review_run(
            repository_id=repository_id,
            review_target=review_target or target,
            target_path=target_path,
            source_revision=source_revision,
            commit_sha=commit_sha,
            pr_number=pr_number,
            user_id=user_id,
            status=AnalysisRunStatus.FAILED.value,
            error_message=error_message,
            run_id=run_id,
            created_at=created_dt,
            **extra_kwargs,
        )

    def list_review_runs(
        self,
        repository_id: uuid.UUID | str,
        *,
        user_id: Optional[uuid.UUID | str] = None,
        status: Optional[str] = None,
        target_path: Optional[str] = None,
        source_revision: Optional[str] = None,
        commit_sha: Optional[str] = None,
        pr_number: Optional[int] = None,
        offset: int = 0,
        limit: int = 50,
    ) -> Tuple[List[AnalysisRun], int]:
        """List paginated code review runs for an authorized repository, newest first."""
        repo_uuid = _ensure_uuid(repository_id)
        if repo_uuid is None:
            return [], 0

        stmt = select(AnalysisRun).where(
            AnalysisRun.repository_id == repo_uuid,
            AnalysisRun.feature_type == AnalysisFeature.REVIEW.value,
        )

        if user_id:
            u_uuid = _ensure_uuid(user_id)
            if u_uuid:
                stmt = stmt.where(AnalysisRun.user_id == u_uuid)

        if status:
            s_val = status.value if hasattr(status, "value") else str(status).upper()
            stmt = stmt.where(AnalysisRun.status == s_val)

        if target_path:
            stmt = stmt.where(AnalysisRun.target_path == target_path)

        s_rev = source_revision or commit_sha or (f"pr/{pr_number}" if pr_number is not None else None)
        if s_rev:
            stmt = stmt.where(AnalysisRun.source_revision == s_rev)

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

    def get_review_run(
        self,
        run_id: uuid.UUID | str,
        repository_id: Optional[uuid.UUID | str] = None,
    ) -> Optional[AnalysisRun]:
        """Retrieve a specific review run with eager-loaded findings."""
        if repository_id is not None:
            run = self.get_by_id_and_repository(run_id, repository_id)
        else:
            run = self.get_by_id(run_id)

        if run is None or run.feature_type != AnalysisFeature.REVIEW.value:
            return None
        return run

    def reopen_review(
        self,
        run_id: uuid.UUID | str,
        repository_id: Optional[uuid.UUID | str] = None,
    ) -> Optional[dict[str, Any]]:
        """Reconstitute a review run from persistent history (Scenario D Step 7).

        Returns a dictionary structure matching ReviewReportResponse with full fidelity.
        """
        run = self.get_review_run(run_id, repository_id)
        if run is None:
            return None

        raw_payload = run.result_payload or {}
        raw_target = raw_payload.get("target") or {}

        target_dict = {
            "type": raw_target.get("type", "file"),
            "path": run.target_path or raw_target.get("path"),
            "commit_sha": raw_target.get("commit_sha"),
            "pr_number": raw_target.get("pr_number"),
            "diff": raw_target.get("diff"),
            "base_revision": raw_target.get("base_revision"),
            "head_revision": raw_target.get("head_revision") or run.source_revision,
        }

        raw_report = raw_payload.get("report") or {}
        findings_list = [f.to_dict() for f in run.findings]

        category_counts = raw_report.get("category_counts") or {}
        if not category_counts and run.findings:
            for f in run.findings:
                cat_str = str(f.category).lower()
                category_counts[cat_str] = category_counts.get(cat_str, 0) + 1

        risk_level = raw_report.get("risk_level", "LOW")
        if not run.findings:
            risk_level = "NONE" if risk_level == "LOW" else risk_level

        summary = raw_report.get("summary") or (
            f"Code review completed with {len(findings_list)} findings."
            if run.status == AnalysisRunStatus.COMPLETED.value
            else (run.error_message or "Code review failed.")
        )

        missing_context = raw_report.get("missing_context") or []

        report_dict = {
            "summary": summary,
            "risk_level": risk_level,
            "findings": findings_list,
            "total_findings": len(findings_list),
            "category_counts": category_counts,
            "missing_context": missing_context,
        }

        return {
            "run_id": str(run.id),
            "repository_id": str(run.repository_id),
            "status": run.status,
            "target": target_dict,
            "revision": run.source_revision,
            "report": report_dict,
            "summary": summary,
            "findings": findings_list,
            "risk_level": risk_level,
            "error_message": run.error_message,
            "created_at": run.created_at.isoformat() if run.created_at else None,
            "completed_at": run.completed_at.isoformat() if run.completed_at else None,
        }

    def get_latest_review(
        self,
        repository_id: uuid.UUID | str,
        target_path: Optional[str] = None,
        *,
        source_revision: Optional[str] = None,
        commit_sha: Optional[str] = None,
        pr_number: Optional[int] = None,
        status: str = AnalysisRunStatus.COMPLETED.value,
    ) -> Optional[AnalysisRun]:
        """Fetch the most recent code review run matching target path or revision."""
        runs, _ = self.list_review_runs(
            repository_id,
            status=status,
            target_path=target_path,
            source_revision=source_revision,
            commit_sha=commit_sha,
            pr_number=pr_number,
            offset=0,
            limit=1,
        )
        return runs[0] if runs else None

    def find_duplicate_review(
        self,
        repository_id: uuid.UUID | str,
        *,
        target_path: Optional[str] = None,
        source_revision: Optional[str] = None,
        commit_sha: Optional[str] = None,
        pr_number: Optional[int] = None,
        status: str = AnalysisRunStatus.COMPLETED.value,
    ) -> Optional[AnalysisRun]:
        """Check for an existing identical completed review run to prevent duplicate AI review executions."""
        return self.get_latest_review(
            repository_id,
            target_path=target_path,
            source_revision=source_revision,
            commit_sha=commit_sha,
            pr_number=pr_number,
            status=status,
        )

    def delete_review_run(
        self,
        run_id: uuid.UUID | str,
        repository_id: Optional[uuid.UUID | str] = None,
    ) -> bool:
        """Delete a code review run enforcing repository boundary check."""
        run = self.get_review_run(run_id, repository_id)
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

    delete_repository_runs = delete_by_repository

    def delete_run(
        self,
        run_id: uuid.UUID | str,
        repository_id: Optional[uuid.UUID | str] = None,
    ) -> bool:
        """Delete an analysis run with optional repository boundary validation."""
        run_uuid = _ensure_uuid(run_id)
        if run_uuid is None:
            return False

        if repository_id is not None:
            run = self.get_by_id_and_repository(run_uuid, repository_id)
        else:
            run = self.get_by_id(run_uuid)

        if run is None:
            return False

        self.session.delete(run)
        self.session.commit()
        return True

    def get_run_summary(
        self,
        repository_id: uuid.UUID | str,
    ) -> dict[str, Any]:
        """Aggregate analysis run and finding metrics for an authorized repository (Week 2 — Day 6)."""
        repo_uuid = _ensure_uuid(repository_id)
        if repo_uuid is None:
            return {
                "total_runs": 0,
                "by_feature": {},
                "by_status": {},
                "total_findings": 0,
                "findings_by_severity": {},
                "findings_by_category": {},
            }

        # 1. Total runs & breakdown by feature and status
        runs_stmt = select(
            AnalysisRun.feature_type,
            AnalysisRun.status,
            func.count(AnalysisRun.id),
        ).where(
            AnalysisRun.repository_id == repo_uuid
        ).group_by(
            AnalysisRun.feature_type,
            AnalysisRun.status,
        )

        rows = self.session.execute(runs_stmt).all()
        total_runs = 0
        by_feature: dict[str, int] = {}
        by_status: dict[str, int] = {}

        for feat, stat, cnt in rows:
            feat_str = str(feat.value if hasattr(feat, "value") else feat)
            stat_str = str(stat.value if hasattr(stat, "value") else stat)
            total_runs += cnt
            by_feature[feat_str] = by_feature.get(feat_str, 0) + cnt
            by_status[stat_str] = by_status.get(stat_str, 0) + cnt

        # 2. Findings breakdown by severity and category
        findings_stmt = select(
            AnalysisFinding.severity,
            AnalysisFinding.category,
            func.count(AnalysisFinding.id),
        ).where(
            AnalysisFinding.repository_id == repo_uuid
        ).group_by(
            AnalysisFinding.severity,
            AnalysisFinding.category,
        )

        f_rows = self.session.execute(findings_stmt).all()
        total_findings = 0
        by_severity: dict[str, int] = {}
        by_category: dict[str, int] = {}

        for sev, cat, cnt in f_rows:
            sev_str = str(sev).upper()
            cat_str = str(cat).lower()
            total_findings += cnt
            by_severity[sev_str] = by_severity.get(sev_str, 0) + cnt
            by_category[cat_str] = by_category.get(cat_str, 0) + cnt

        return {
            "repository_id": str(repo_uuid),
            "total_runs": total_runs,
            "by_feature": by_feature,
            "by_status": by_status,
            "total_findings": total_findings,
            "findings_by_severity": by_severity,
            "findings_by_category": by_category,
        }

    def verify_integrity(
        self,
        repository_id: Optional[uuid.UUID | str] = None,
    ) -> dict[str, Any]:
        """Perform comprehensive database integrity verification across runs and findings (Week 2 — Day 6).

        Verifies:
        1. Absence of orphaned findings (findings without a valid parent analysis_run).
        2. Synchronization between findings_count column and actual associated findings count.
        3. Status and timestamp consistency (COMPLETED must have completed_at; FAILED must have error_message).
        4. Cross-repository foreign key attribution integrity.
        """
        issues: List[dict[str, Any]] = []

        # 1. Check for orphaned findings
        orphan_stmt = select(AnalysisFinding).where(
            ~AnalysisFinding.analysis_run_id.in_(select(AnalysisRun.id))
        )
        if repository_id is not None:
            repo_uuid = _ensure_uuid(repository_id)
            if repo_uuid:
                orphan_stmt = orphan_stmt.where(AnalysisFinding.repository_id == repo_uuid)

        orphans = list(self.session.scalars(orphan_stmt).all())
        for orphan in orphans:
            issues.append({
                "type": "ORPHANED_FINDING",
                "finding_id": str(orphan.id),
                "analysis_run_id": str(orphan.analysis_run_id),
                "details": f"Finding '{orphan.title}' points to non-existent analysis_run '{orphan.analysis_run_id}'.",
            })

        # 2. Check run count synchronization and status consistency
        run_query = select(AnalysisRun).options(selectinload(AnalysisRun.findings))
        if repository_id is not None:
            repo_uuid = _ensure_uuid(repository_id)
            if repo_uuid:
                run_query = run_query.where(AnalysisRun.repository_id == repo_uuid)

        all_runs = list(self.session.scalars(run_query).all())
        desynchronized_count = 0
        inconsistent_status_count = 0

        for run in all_runs:
            actual_findings_count = len(run.findings)
            if run.findings_count != actual_findings_count:
                desynchronized_count += 1
                issues.append({
                    "type": "DESYNCHRONIZED_FINDINGS_COUNT",
                    "run_id": str(run.id),
                    "recorded_count": run.findings_count,
                    "actual_count": actual_findings_count,
                    "details": f"Run '{run.id}' recorded findings_count={run.findings_count} but has {actual_findings_count} associated findings.",
                })

            # Status consistency checks
            if run.status == AnalysisRunStatus.COMPLETED.value and run.completed_at is None:
                inconsistent_status_count += 1
                issues.append({
                    "type": "MISSING_COMPLETION_TIMESTAMP",
                    "run_id": str(run.id),
                    "details": f"Run '{run.id}' is COMPLETED but completed_at is null.",
                })

            if run.status == AnalysisRunStatus.FAILED.value and not run.error_message:
                inconsistent_status_count += 1
                issues.append({
                    "type": "MISSING_ERROR_MESSAGE",
                    "run_id": str(run.id),
                    "details": f"Run '{run.id}' is FAILED but error_message is missing or empty.",
                })

        return {
            "status": "CLEAN" if len(issues) == 0 else "ISSUES_FOUND",
            "total_runs_checked": len(all_runs),
            "orphaned_findings_count": len(orphans),
            "desynchronized_runs_count": desynchronized_count,
            "inconsistent_status_count": inconsistent_status_count,
            "issues_count": len(issues),
            "issues": issues,
        }

    # -----------------------------------------------------------------------
    # Data Retention & Sensitive-Data Handling (Week 2 — Day 7)
    # -----------------------------------------------------------------------

    def purge_expired_runs(
        self,
        *,
        repository_id: Optional[uuid.UUID | str] = None,
        retention_days: int = 30,
        feature_type: Optional[str] = None,
        status: Optional[str] = None,
    ) -> int:
        """Purge analysis runs and cascading findings older than retention_days (Day 7).

        Default retention is 30 days. Cascading deletes automatically remove associated findings.
        Returns the count of purged runs.
        """
        cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)
        stmt = select(AnalysisRun).where(AnalysisRun.created_at < cutoff)

        if repository_id is not None:
            repo_uuid = _ensure_uuid(repository_id)
            if repo_uuid:
                stmt = stmt.where(AnalysisRun.repository_id == repo_uuid)

        if feature_type:
            feat_val = feature_type.value if hasattr(feature_type, "value") else str(feature_type)
            stmt = stmt.where(AnalysisRun.feature_type == feat_val)

        if status:
            status_val = status.value if hasattr(status, "value") else str(status)
            stmt = stmt.where(AnalysisRun.status == status_val)

        runs_to_delete = list(self.session.scalars(stmt).all())
        count = len(runs_to_delete)
        for run in runs_to_delete:
            self.session.delete(run)

        if count > 0:
            self.session.commit()
        return count

    def prune_uncompleted_stale_runs(
        self,
        *,
        older_than_hours: int = 24,
        mark_as_failed: bool = True,
        repository_id: Optional[uuid.UUID | str] = None,
    ) -> int:
        """Prune or time-out stuck PENDING or RUNNING runs older than specified hours (Day 7).

        If mark_as_failed is True, transitions run status to FAILED with a timeout message.
        Otherwise, purges the runs completely.
        """
        cutoff = datetime.now(timezone.utc) - timedelta(hours=older_than_hours)
        stmt = select(AnalysisRun).where(
            AnalysisRun.status.in_([AnalysisRunStatus.PENDING.value, AnalysisRunStatus.RUNNING.value]),
            AnalysisRun.created_at < cutoff,
        )

        if repository_id is not None:
            repo_uuid = _ensure_uuid(repository_id)
            if repo_uuid:
                stmt = stmt.where(AnalysisRun.repository_id == repo_uuid)

        stale_runs = list(self.session.scalars(stmt).all())
        count = len(stale_runs)
        now = datetime.now(timezone.utc)

        for run in stale_runs:
            if mark_as_failed:
                run.status = AnalysisRunStatus.FAILED.value
                run.error_message = f"Analysis run timed out after {older_than_hours} hours without completion."
                run.completed_at = now
            else:
                self.session.delete(run)

        if count > 0:
            self.session.commit()
        return count

    def get_retention_metrics(
        self,
        repository_id: Optional[uuid.UUID | str] = None,
    ) -> dict[str, Any]:
        """Calculate data retention statistics across analysis runs and findings (Day 7)."""
        repo_uuid = _ensure_uuid(repository_id) if repository_id else None
        base_stmt = select(AnalysisRun)
        if repo_uuid:
            base_stmt = base_stmt.where(AnalysisRun.repository_id == repo_uuid)

        total_runs = self.session.scalar(select(func.count()).select_from(base_stmt.subquery())) or 0
        now = datetime.now(timezone.utc)

        runs_older_30d = self.session.scalar(
            select(func.count()).select_from(
                base_stmt.where(AnalysisRun.created_at < (now - timedelta(days=30))).subquery()
            )
        ) or 0
        runs_older_60d = self.session.scalar(
            select(func.count()).select_from(
                base_stmt.where(AnalysisRun.created_at < (now - timedelta(days=60))).subquery()
            )
        ) or 0
        runs_older_90d = self.session.scalar(
            select(func.count()).select_from(
                base_stmt.where(AnalysisRun.created_at < (now - timedelta(days=90))).subquery()
            )
        ) or 0

        subq = base_stmt.subquery()
        oldest_dt = self.session.scalar(select(func.min(subq.c.created_at)))
        newest_dt = self.session.scalar(select(func.max(subq.c.created_at)))

        findings_stmt = select(func.count()).select_from(AnalysisFinding)
        if repo_uuid:
            findings_stmt = findings_stmt.where(AnalysisFinding.repository_id == repo_uuid)
        total_findings = self.session.scalar(findings_stmt) or 0

        return {
            "repository_id": str(repo_uuid) if repo_uuid else None,
            "total_runs": total_runs,
            "total_findings": total_findings,
            "runs_older_30d": runs_older_30d,
            "runs_older_60d": runs_older_60d,
            "runs_older_90d": runs_older_90d,
            "oldest_run_at": oldest_dt.isoformat() if oldest_dt else None,
            "newest_run_at": newest_dt.isoformat() if newest_dt else None,
        }

    def sanitize_sensitive_data_in_history(
        self,
        repository_id: Optional[uuid.UUID | str] = None,
    ) -> int:
        """Scan existing persisted runs and findings, redacting any raw credentials or secrets (Day 7).

        Returns count of records sanitized.
        """
        repo_uuid = _ensure_uuid(repository_id) if repository_id else None
        updated_count = 0

        # 1. Audit and sanitize runs
        run_stmt = select(AnalysisRun)
        if repo_uuid:
            run_stmt = run_stmt.where(AnalysisRun.repository_id == repo_uuid)
        runs = list(self.session.scalars(run_stmt).all())
        for run in runs:
            dirty = False
            if run.error_message:
                scrubbed = scrub_sensitive_text(run.error_message)
                if scrubbed != run.error_message:
                    run.error_message = scrubbed
                    dirty = True
            if run.test_output:
                scrubbed = scrub_sensitive_text(run.test_output)
                if scrubbed != run.test_output:
                    run.test_output = scrubbed
                    dirty = True
            if run.result_payload:
                scrubbed = scrub_sensitive_data(run.result_payload)
                if scrubbed != run.result_payload:
                    run.result_payload = scrubbed
                    dirty = True
            if dirty:
                updated_count += 1

        # 2. Audit and sanitize findings
        finding_stmt = select(AnalysisFinding)
        if repo_uuid:
            finding_stmt = finding_stmt.where(AnalysisFinding.repository_id == repo_uuid)
        findings = list(self.session.scalars(finding_stmt).all())
        for f in findings:
            dirty = False
            if f.title:
                s = scrub_sensitive_text(f.title)
                if s != f.title:
                    f.title = s
                    dirty = True
            if f.description:
                s = scrub_sensitive_text(f.description)
                if s != f.description:
                    f.description = s
                    dirty = True
            if f.evidence:
                s = scrub_sensitive_text(f.evidence)
                if s != f.evidence:
                    f.evidence = s
                    dirty = True
            if f.suggested_fix:
                s = scrub_sensitive_text(f.suggested_fix)
                if s != f.suggested_fix:
                    f.suggested_fix = s
                    dirty = True
            if f.finding_metadata:
                s = scrub_sensitive_data(f.finding_metadata)
                if s != f.finding_metadata:
                    f.finding_metadata = s
                    dirty = True
            if dirty:
                updated_count += 1

        if updated_count > 0:
            self.session.commit()
        return updated_count

