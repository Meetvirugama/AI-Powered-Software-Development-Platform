"""
Analysis History API endpoints.
- GET /api/v1/repositories/{repository_id}/analysis-runs
- GET /api/v1/repositories/{repository_id}/analysis-runs/summary
- GET /api/v1/analysis-runs/{run_id}
"""

from __future__ import annotations

import inspect
import logging
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, Response
from sqlalchemy.orm import Session

from app.api.v1.analysis.common import (
    ANALYSIS_ERROR_RESPONSES,
    _coerce_run_summary,
    _owned_repository,
    _request_user_id,
)
from app.core.database import get_db
from app.core.errors import APIError, ErrorCode
from app.core.secret_redaction import redact, redact_obj
from app.schemas.analysis import (
    AnalysisFeatureType,
    AnalysisRunDetailResponse,
    AnalysisRunMetricsSummaryResponse,
    PaginatedAnalysisRunResponse,
    normalize_analysis_feature_type,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["analysis"])


# ---------------------------------------------------------------------------
# 1. List Analysis Runs (GET /api/v1/repositories/{repository_id}/analysis-runs)
# ---------------------------------------------------------------------------

@router.get(
    "/repositories/{repository_id}/analysis-runs",
    response_model=PaginatedAnalysisRunResponse,
    responses=ANALYSIS_ERROR_RESPONSES,
    summary="List historical analysis runs for an authorized repository",
    description=(
        "Retrieve paginated historical analysis runs (`explain`, `detect_bugs`, `generate_tests`, `review`) "
        "for a repository owned by the authenticated user. Supports filtering by `feature_type` "
        "(including aliases `bugs` and `tests`), `status`, `target_path`, `source_revision`, and `user_id`."
    ),
)
def list_analysis_runs(
    repository_id: UUID,
    request: Request,
    feature_type: AnalysisFeatureType | None = Query(default=None),
    status: str | None = Query(default=None),
    target_path: str | None = Query(default=None),
    source_revision: str | None = Query(default=None),
    user_id: UUID | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
) -> PaginatedAnalysisRunResponse:
    """Return paginated analysis runs scoped to a repository owned by the caller."""
    _owned_repository(repository_id, request, db)
    offset = (page - 1) * page_size

    normalized_feature_type = normalize_analysis_feature_type(feature_type)

    run_service = getattr(request.app.state, "analysis_run_service", None)
    if run_service is not None and hasattr(run_service, "list_runs"):
        kwargs: dict[str, Any] = {
            "feature_type": normalized_feature_type,
            "status": status,
            "offset": offset,
            "limit": page_size,
        }
        if target_path:
            kwargs["target_path"] = target_path
        if source_revision:
            kwargs["source_revision"] = source_revision
        if user_id is not None:
            kwargs["user_id"] = user_id

        try:
            res = run_service.list_runs(repository_id, db=db, **kwargs)
        except TypeError:
            try:
                res = run_service.list_runs(repository_id, **kwargs)
            except TypeError:
                res = run_service.list_runs(
                    repository_id,
                    feature_type=normalized_feature_type,
                    status=status,
                    offset=offset,
                    limit=page_size,
                )

        if inspect.isawaitable(res):
            import asyncio
            res = asyncio.run(res)
        items, total = res
        return PaginatedAnalysisRunResponse(
            page=page,
            page_size=page_size,
            total=total,
            items=[_coerce_run_summary(item, repository_id) for item in items],
        )

    try:
        from app.repositories.analysis_run_repository import AnalysisRunRepository  # type: ignore

        repo_layer = AnalysisRunRepository(db)
        items, total = repo_layer.list_by_repository(
            repository_id,
            user_id=user_id,
            feature_type=normalized_feature_type,
            status=status,
            target_path=target_path,
            source_revision=source_revision,
            offset=offset,
            limit=page_size,
        )
        return PaginatedAnalysisRunResponse(
            page=page,
            page_size=page_size,
            total=total,
            items=[_coerce_run_summary(item, repository_id) for item in items],
        )
    except Exception as exc:
        logger.warning("analysis_runs_list_db_error", extra={"error": str(exc)})
        raise APIError(503, ErrorCode.SERVICE_UNAVAILABLE, "Analysis history temporarily unavailable.") from exc



# ---------------------------------------------------------------------------
# 2. Get Analysis Runs Summary (GET /api/v1/repositories/{repository_id}/analysis-runs/summary)
# ---------------------------------------------------------------------------

@router.get(
    "/repositories/{repository_id}/analysis-runs/summary",
    response_model=AnalysisRunMetricsSummaryResponse,
    responses=ANALYSIS_ERROR_RESPONSES,
    summary="Get analysis run summary, database integrity, and retention metrics",
    description=(
        "Aggregate run counts by feature and status, database referential integrity status, "
        "and retention metrics for an authorized repository (Week 2 Day 7)."
    ),
)
def get_analysis_runs_summary(
    repository_id: UUID,
    request: Request,
    db: Session = Depends(get_db),
) -> AnalysisRunMetricsSummaryResponse:
    """Return aggregate run metrics, integrity status, and retention metrics for an owned repository."""
    _owned_repository(repository_id, request, db)

    if hasattr(db, "execute") or hasattr(db, "query"):
        try:
            from app.repositories.analysis_run_repository import AnalysisRunRepository

            repo_layer = AnalysisRunRepository(db)
            summary = repo_layer.get_run_summary(repository_id)
            integrity = repo_layer.verify_integrity(repository_id=repository_id)
            retention = repo_layer.get_retention_metrics(repository_id=repository_id)
            return AnalysisRunMetricsSummaryResponse(
                repository_id=str(repository_id),
                total_runs=int(summary.get("total_runs", 0)),
                by_feature=dict(summary.get("by_feature", {})),
                by_status=dict(summary.get("by_status", {})),
                total_findings=int(summary.get("total_findings", 0)),
                integrity_status=str(integrity.get("status", "CLEAN")),
                integrity_issues_count=int(integrity.get("issues_count", 0)),
                retention=redact_obj(retention),
            )
        except Exception as exc:
            logger.warning("analysis_runs_summary_db_error", extra={"error": str(exc)})
            raise APIError(503, ErrorCode.SERVICE_UNAVAILABLE, "Analysis summary temporarily unavailable.") from exc

    return AnalysisRunMetricsSummaryResponse(
        repository_id=str(repository_id),
        total_runs=0,
        by_feature={},
        by_status={},
        total_findings=0,
        integrity_status="CLEAN",
        integrity_issues_count=0,
        retention={"default_retention_days": 90},
    )


# ---------------------------------------------------------------------------
# 3. Export Analysis Runs Dataset (GET /api/v1/repositories/{repository_id}/analysis-runs/export)
# ---------------------------------------------------------------------------

@router.get(
    "/repositories/{repository_id}/analysis-runs/export",
    responses={
        200: {
            "description": "Evaluation dataset in JSONL, JSON, or Langfuse format for regression testing & LLM evaluation.",
            "content": {
                "application/x-ndjson": {},
                "application/json": {},
            },
        },
        **ANALYSIS_ERROR_RESPONSES,
    },
    summary="Export analysis runs and user feedback as an evaluation dataset (Issue #195)",
    description=(
        "Export historical analysis runs with findings and user feedback into standard JSONL, JSON, or Langfuse formats "
        "for regression evaluation datasets (e.g., Langfuse datasets). Supports filtering by feature_type, status, "
        "and feedback presence."
    ),
)
def export_analysis_runs_dataset(
    repository_id: UUID,
    request: Request,
    format: str = Query(default="jsonl", pattern="^(jsonl|json|langfuse)$", description="Export format: 'jsonl' (default), 'json', or 'langfuse'"),
    feature_type: AnalysisFeatureType | None = Query(default=None, description="Filter by feature type"),
    status: str | None = Query(default=None, description="Filter by status (e.g. COMPLETED, FAILED)"),
    include_feedback_only: bool = Query(default=False, description="When true, only exports runs that contain user feedback"),
    limit: int = Query(default=1000, ge=1, le=5000, description="Maximum number of runs to export"),
    db: Session = Depends(get_db),
) -> Response:
    """Export analysis runs and feedback as evaluation dataset for the authorized repository."""
    _owned_repository(repository_id, request, db)
    normalized_feature_type = normalize_analysis_feature_type(feature_type)

    run_service = getattr(request.app.state, "analysis_run_service", None)
    if run_service is None or not hasattr(run_service, "export_evaluation_dataset"):
        from app.services.analysis_run_history_service import AnalysisRunHistoryService
        run_service = AnalysisRunHistoryService()

    try:
        content = run_service.export_evaluation_dataset(
            repository_id=repository_id,
            format=format,
            feature_type=normalized_feature_type,
            status=status,
            include_feedback_only=include_feedback_only,
            limit=limit,
            db=db,
        )
    except Exception as exc:
        logger.warning("analysis_runs_export_error", extra={"error": str(exc)})
        raise APIError(503, ErrorCode.SERVICE_UNAVAILABLE, "Analysis export temporarily unavailable.") from exc

    if format == "langfuse":
        media_type = "application/x-ndjson"
        filename = f"analysis-eval-{repository_id}-langfuse.jsonl"
    elif format == "jsonl":
        media_type = "application/x-ndjson"
        filename = f"analysis-eval-{repository_id}.jsonl"
    else:
        media_type = "application/json"
        filename = f"analysis-eval-{repository_id}.json"

    return Response(
        content=content,
        media_type=media_type,
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "no-cache, no-store, must-revalidate",
        },
    )


# ---------------------------------------------------------------------------
# 4. Get Analysis Run Detail (GET /api/v1/analysis-runs/{run_id})
# ---------------------------------------------------------------------------

@router.get(
    "/analysis-runs/{run_id}",
    response_model=AnalysisRunDetailResponse,
    responses=ANALYSIS_ERROR_RESPONSES,
    summary="Get a specific analysis run and its structured findings",
    description=(
        "Reopen a persisted analysis run (`explain`, `detect_bugs`, `generate_tests`, or `review`) "
        "by UUID after verifying that the authenticated user owns the associated repository."
    ),
)
def get_analysis_run(
    run_id: UUID,
    request: Request,
    db: Session = Depends(get_db),
) -> AnalysisRunDetailResponse:
    """Retrieve a persisted analysis run after verifying repository ownership."""
    _request_user_id(request)

    run_record: Any = None
    run_service = getattr(request.app.state, "analysis_run_service", None)
    if run_service is not None and hasattr(run_service, "get_run"):
        try:
            res = run_service.get_run(run_id, db=db)
        except TypeError:
            res = run_service.get_run(run_id)
        if inspect.isawaitable(res):
            import asyncio
            res = asyncio.run(res)
        run_record = res
    else:
        try:
            from app.repositories.analysis_run_repository import (
                AnalysisRunRepository,  # type: ignore
            )

            run_record = AnalysisRunRepository(db).get_by_id(run_id)
        except Exception:
            run_record = None

    if run_record is None:
        raise APIError(404, ErrorCode.ANALYSIS_RUN_NOT_FOUND, "Analysis run not found.")

    repo_id_raw = (
        run_record.get("repository_id")
        if isinstance(run_record, dict)
        else getattr(run_record, "repository_id", None)
    )
    try:
        repo_uuid = UUID(str(repo_id_raw))
    except (TypeError, ValueError) as exc:
        raise APIError(404, ErrorCode.ANALYSIS_RUN_NOT_FOUND, "Analysis run not found.") from exc

    _owned_repository(repo_uuid, request, db)

    if isinstance(run_record, AnalysisRunDetailResponse):
        return AnalysisRunDetailResponse.model_validate(redact_obj(run_record.model_dump(mode="json")))
    if isinstance(run_record, dict):
        normalized_dict = dict(redact_obj(run_record))
        if normalized_dict.get("feature_type"):
            normalized_dict["feature_type"] = normalize_analysis_feature_type(
                normalized_dict.get("feature_type")
            )
        return AnalysisRunDetailResponse.model_validate(normalized_dict)

    status_val = getattr(run_record, "status", "COMPLETED")
    if hasattr(status_val, "value"):
        status_val = status_val.value
    feature_val = getattr(run_record, "feature_type", "explain")
    if hasattr(feature_val, "value"):
        feature_val = feature_val.value
    feature_val = normalize_analysis_feature_type(feature_val) or "explain"

    raw_findings = [
        f.to_dict() if hasattr(f, "to_dict") else f
        for f in (getattr(run_record, "findings", []) or [])
    ]
    detail = AnalysisRunDetailResponse(
        id=str(getattr(run_record, "id", run_id)),
        repository_id=str(repo_uuid),
        user_id=str(getattr(run_record, "user_id", "")) or None,
        feature_type=feature_val,
        status=status_val,
        target_path=getattr(run_record, "target_path", None),
        target_symbol=getattr(run_record, "target_symbol", None),
        start_line=getattr(run_record, "start_line", None),
        end_line=getattr(run_record, "end_line", None),
        source_revision=getattr(run_record, "source_revision", None),
        findings_count=getattr(run_record, "findings_count", 0) or len(raw_findings),
        result_payload=redact_obj(getattr(run_record, "result_payload", None)),
        test_output=redact(getattr(run_record, "test_output", None)) if getattr(run_record, "test_output", None) else None,
        findings=redact_obj(raw_findings),
        error_message=redact(getattr(run_record, "error_message", None)) if getattr(run_record, "error_message", None) else None,
        created_at=getattr(run_record, "created_at", datetime.now(UTC)),
        completed_at=getattr(run_record, "completed_at", None),
    )
    return detail

