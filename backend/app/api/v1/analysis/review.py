"""
AI Code Review API endpoint (POST /api/v1/repositories/{repository_id}/review).
"""

from __future__ import annotations

import asyncio
import inspect
import logging
from typing import Any
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Request
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.api.v1.analysis.common import (
    ANALYSIS_ERROR_RESPONSES,
    _get_service,
    _invoke_service_method,
    _owned_repository,
    _request_user_id,
)
from app.core.database import get_db
from app.core.errors import APIError, ErrorCode
from app.core.secret_redaction import redact, redact_obj
from app.core.telemetry import StageExecutionTimer
from app.schemas.analysis import (
    AnalysisTarget,
    CodeReviewRequest,
    ReviewReport,
    ReviewReportResponse,
)
from app.services.code_review_orchestrator import (
    build_grounded_review_report,
    merge_and_rank_review_findings,
    normalize_and_ground_review_findings,
    resolve_review_target_and_build_context,
    run_static_review_on_changes,
)
from app.services.explanation_orchestrator import (
    record_analysis_run,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["analysis"])


@router.post(
    "/repositories/{repository_id}/review",
    response_model=ReviewReportResponse,
    responses=ANALYSIS_ERROR_RESPONSES,
    summary="Run a standalone AI and static code review on a file, commit, PR, or diff",
    description=(
        "Execute a standalone code review across `correctness`, `security`, `performance`, "
        "`reliability`, and `maintainability` for a single file, commit SHA, GitHub Pull Request, "
        "or unified diff without starting an autonomous coding task."
    ),
)
async def review_code(
    repository_id: UUID,
    payload: CodeReviewRequest,
    request: Request,
    db: Session = Depends(get_db),
) -> ReviewReportResponse:
    """Execute the 10-step Week 2 Day 5 Standalone AI Code Review pipeline."""
    timer = StageExecutionTimer("review", context_budget=payload.options.max_context_tokens)
    user_id = _request_user_id(request)
    repo = _owned_repository(repository_id, request, db)

    with timer.measure("target_resolution_and_diff_mapping"):
        resolved = await resolve_review_target_and_build_context(
            repository_id=repository_id,
            repo=repo,
            payload=payload,
            user_id=user_id,
            db=db,
            app_state=request.app.state,
        )
        payload.target = resolved.target

    history_target = AnalysisTarget(
        type="file",
        path=resolved.target_path_summary or "diff",
        revision=resolved.revision,
    )

    service = _get_service(request, "code_review_service", "AI code review")
    method = service.review if hasattr(service, "review") else service

    run_id = str(uuid4())
    try:
        with timer.measure("llm_inference"):
            raw_result = await _invoke_service_method(
                method,
                repository_id,
                payload,
                user_id=user_id,
                db=db,
                extra_kwargs={
                    "context": resolved.intelligence_context,
                    "modified_files": resolved.modified_files,
                    "source_map": resolved.source_map,
                    "revision": resolved.revision,
                },
            )
    except APIError as exc:
        if payload.options.persist_run:
            record_analysis_run(
                request.app.state,
                db,
                run_id=run_id,
                repository_id=repository_id,
                user_id=user_id,
                feature_type="review",
                status="FAILED",
                target=history_target,
                revision=resolved.revision,
                error_message=exc.message,
            )
        raise
    except Exception as exc:
        safe_err = redact(str(exc))
        if payload.options.persist_run:
            record_analysis_run(
                request.app.state,
                db,
                run_id=run_id,
                repository_id=repository_id,
                user_id=user_id,
                feature_type="review",
                status="FAILED",
                target=history_target,
                revision=resolved.revision,
                error_message=safe_err,
            )
        raise APIError(
            500,
            ErrorCode.ANALYSIS_FAILED,
            "Code review failed during execution.",
            retryable=False,
        ) from exc

    extra_static_raw: list[Any] = []
    scanner_warnings: list[str] = []
    if payload.include_static:
        with timer.measure("static_analysis"):
            ext_reviewer = getattr(request.app.state, "static_reviewer", None)
            if ext_reviewer is not None:
                rev_fn = getattr(ext_reviewer, "review_modified_files", getattr(ext_reviewer, "review", ext_reviewer))
                if callable(rev_fn):
                    try:
                        mod_paths = [mf.file_path for mf in resolved.modified_files]
                        if inspect.iscoroutinefunction(rev_fn):
                            ext_res = await rev_fn(mod_paths)
                        else:
                            ext_res = await asyncio.to_thread(rev_fn, mod_paths)
                        if inspect.isawaitable(ext_res):
                            ext_res = await ext_res
                        if isinstance(ext_res, dict):
                            extra_static_raw.extend(ext_res.get("findings", []))
                        elif isinstance(ext_res, list):
                            extra_static_raw.extend(ext_res)
                    except Exception as exc:
                        logger.warning("external_static_reviewer_error", extra={"error": str(exc)})
                        scanner_warnings.append("External static reviewer encountered an error.")

            builtin_static, builtin_warns = await asyncio.to_thread(
                run_static_review_on_changes,
                repository_id=repository_id,
                resolved=resolved,
                app_state=request.app.state,
            )
            extra_static_raw.extend(builtin_static)
            scanner_warnings.extend(builtin_warns)

    status_val = "COMPLETED"
    try:
        if isinstance(raw_result, ReviewReportResponse):
            run_id = raw_result.run_id or run_id
            status_val = raw_result.status
            raw_report = raw_result.report
        elif isinstance(raw_result, ReviewReport):
            raw_report = raw_result
        elif isinstance(raw_result, dict) and "report" in raw_result:
            run_id = str(raw_result.get("run_id") or run_id)
            status_val = raw_result.get("status", "COMPLETED")
            raw_report = ReviewReport.model_validate(raw_result["report"])
        else:
            raw_report = ReviewReport.model_validate(raw_result)
    except (ValidationError, ValueError, TypeError) as exc:
        logger.error("review_output_schema_invalid", extra={"error": str(exc)})
        if payload.options.persist_run:
            record_analysis_run(
                request.app.state,
                db,
                run_id=run_id,
                repository_id=repository_id,
                user_id=user_id,
                feature_type="review",
                status="FAILED",
                target=history_target,
                revision=resolved.revision,
                error_message="AI code review service returned an invalid output schema.",
            )
        raise APIError(
            500,
            ErrorCode.ANALYSIS_FAILED,
            "AI code review service returned an invalid output schema.",
            retryable=False,
        ) from exc

    if status_val == "FAILED":
        if payload.options.persist_run:
            record_analysis_run(
                request.app.state,
                db,
                run_id=run_id,
                repository_id=repository_id,
                user_id=user_id,
                feature_type="review",
                status="FAILED",
                target=history_target,
                revision=resolved.revision,
                error_message="Code review execution failed.",
            )
        raise APIError(
            500,
            ErrorCode.ANALYSIS_FAILED,
            "Code review execution failed.",
            retryable=True,
        )

    with timer.measure("grounding_and_ranking"):
        grounded_ai = normalize_and_ground_review_findings(
            list(raw_report.findings),
            repository_id=repository_id,
            resolved=resolved,
        )
        grounded_static = normalize_and_ground_review_findings(
            extra_static_raw,
            repository_id=repository_id,
            resolved=resolved,
            default_source_type="STATIC",
        )

        merged_findings = merge_and_rank_review_findings(
            [*grounded_static, *grounded_ai],
            include_static=payload.include_static,
        )
        merged_missing = list(
            dict.fromkeys([*resolved.missing_context, *scanner_warnings, *raw_report.missing_context])
        )

        grounded_report = build_grounded_review_report(
            summary=raw_report.summary,
            findings=merged_findings,
            missing_context=merged_missing,
            explicit_risk_level=raw_report.risk_level,
        )

    # Security (W2 Day 5–6): Never echo raw untrusted diff text back in response.target.diff
    sanitized_target = resolved.target.model_copy(
        update={
            "diff": None,
            "path": resolved.target.path
            or (
                resolved.modified_files[0].file_path
                if len(resolved.modified_files) == 1
                else None
            ),
            "base_revision": resolved.base_revision,
            "head_revision": resolved.head_revision,
        }
    )

    ctx_tokens = getattr(resolved.intelligence_context, "total_tokens", None) if resolved else None
    prompt_tokens = getattr(raw_result, "input_tokens", None) or (ctx_tokens or 0)
    completion_tokens = getattr(raw_result, "output_tokens", None) or (len(grounded_report.findings) * 45)
    timer.record_tokens(prompt_tokens=prompt_tokens, completion_tokens=completion_tokens, context_utilized=ctx_tokens)
    stage_metrics = timer.finish().to_dict()

    response = ReviewReportResponse(
        run_id=run_id,
        repository_id=str(repository_id),
        status=status_val,
        target=sanitized_target,
        report=grounded_report,
        stage_metrics=stage_metrics,
    )
    response = ReviewReportResponse.model_validate(redact_obj(response.model_dump(mode="json")))

    if payload.options.persist_run:
        record_analysis_run(
            request.app.state,
            db,
            run_id=response.run_id,
            repository_id=repository_id,
            user_id=user_id,
            feature_type="review",
            status=response.status,
            target=history_target,
            revision=resolved.revision,
            result_payload=response.model_dump(mode="json"),
            findings=[f.model_dump(mode="json") for f in response.report.findings],
            findings_count=len(response.report.findings),
        )

    return response

