"""Pull request / repository review run persistence and reopen aggregate."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, List, Optional, Sequence, Tuple

from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from app.models.analysis_run import AnalysisFeature, AnalysisRun, AnalysisRunStatus
from app.repositories.analysis.base import (
    _ensure_datetime,
    _ensure_uuid,
)

from app.repositories.analysis.core import AnalysisCoreMixin


class ReviewRunMixin:
    """Code Review history operations."""

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


class ReviewRunRepository(ReviewRunMixin, AnalysisCoreMixin):
    """Standalone domain aggregate for code review history."""
