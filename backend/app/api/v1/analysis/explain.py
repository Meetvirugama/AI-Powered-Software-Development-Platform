"""
Code Explanation API endpoint (POST /api/v1/repositories/{repository_id}/explain).
"""

from __future__ import annotations

import logging
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
    CodeExplanation,
    CodeExplanationResponse,
    ExplainCodeRequest,
)
from app.services.explanation_orchestrator import (
    ground_explanation_sources,
    record_analysis_run,
    resolve_target_and_build_context,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["analysis"])


@router.post(
    "/repositories/{repository_id}/explain",
    response_model=CodeExplanationResponse,
    responses=ANALYSIS_ERROR_RESPONSES,
    summary="Explain a file, symbol, or line range using repository context",
    description=(
        "Generate a structured, source-grounded explanation (`purpose`, `logic_flow`, `key_symbols`, "
        "`inputs_and_outputs`, `dependencies`, `assumptions_and_limitations`, `sources`) for a file, "
        "symbol, or 1-indexed inclusive line range in an authorized repository."
    ),
)
async def explain_code(
    repository_id: UUID,
    payload: ExplainCodeRequest,
    request: Request,
    db: Session = Depends(get_db),
) -> CodeExplanationResponse:
    """Execute the 9-step Week 2 Day 2 Code Explanation pipeline."""
    timer = StageExecutionTimer("explain", context_budget=payload.options.max_context_tokens)
    user_id = _request_user_id(request)
    repo = _owned_repository(repository_id, request, db)

    with timer.measure("target_resolution_and_context"):
        resolved = resolve_target_and_build_context(repository_id, repo, payload, db)
        payload.target = resolved.target

    service = _get_service(request, "explanation_service", "Code explanation")
    method = service.explain if hasattr(service, "explain") else service

    run_id = str(uuid4())
    try:
        with timer.measure("llm_inference"):
            raw_result = await _invoke_service_method(
                method,
                repository_id,
                payload,
                user_id=user_id,
                db=db,
                file_record=resolved.file_record,
                extra_kwargs={
                    "context": resolved.intelligence_context,
                    "code_content": resolved.code_content,
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
                feature_type="explain",
                status="FAILED",
                target=resolved.target,
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
                feature_type="explain",
                status="FAILED",
                target=resolved.target,
                revision=resolved.revision,
                error_message=safe_err,
            )
        raise APIError(
            500,
            ErrorCode.ANALYSIS_FAILED,
            "Code explanation failed during execution.",
            retryable=False,
        ) from exc

    try:
        if isinstance(raw_result, CodeExplanationResponse):
            run_id = raw_result.run_id or run_id
            status_val = raw_result.status
            explanation = raw_result.explanation
            revision = raw_result.revision or resolved.revision
        elif isinstance(raw_result, CodeExplanation):
            status_val = "COMPLETED"
            explanation = raw_result
            revision = resolved.revision
        elif isinstance(raw_result, dict) and "explanation" in raw_result:
            run_id = str(raw_result.get("run_id") or run_id)
            status_val = raw_result.get("status", "COMPLETED")
            revision = raw_result.get("revision") or resolved.revision
            explanation = CodeExplanation.model_validate(raw_result["explanation"])
        else:
            status_val = "COMPLETED"
            revision = resolved.revision
            explanation = CodeExplanation.model_validate(raw_result)
    except ValidationError as exc:
        logger.error("explain_output_schema_invalid", extra={"error": str(exc)})
        if payload.options.persist_run:
            record_analysis_run(
                request.app.state,
                db,
                run_id=run_id,
                repository_id=repository_id,
                user_id=user_id,
                feature_type="explain",
                status="FAILED",
                target=resolved.target,
                revision=resolved.revision,
                error_message="Code explanation service returned an invalid output schema.",
            )
        raise APIError(
            500,
            ErrorCode.ANALYSIS_FAILED,
            "Code explanation service returned an invalid output schema.",
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
                feature_type="explain",
                status="FAILED",
                target=resolved.target,
                revision=revision,
                error_message="Code explanation failed during execution.",
            )
        raise APIError(
            500,
            ErrorCode.ANALYSIS_FAILED,
            "Code explanation failed during execution.",
            retryable=True,
        )

    with timer.measure("grounding_and_redaction"):
        grounded_explanation = ground_explanation_sources(
            explanation,
            repository_id=repository_id,
            resolved=resolved,
        )

    ctx_tokens = getattr(resolved.intelligence_context, "total_tokens", None) if resolved else None
    prompt_tokens = getattr(raw_result, "input_tokens", None) or (ctx_tokens or 0)
    completion_tokens = getattr(raw_result, "output_tokens", None) or len(str(grounded_explanation).split())
    timer.record_tokens(prompt_tokens=prompt_tokens, completion_tokens=completion_tokens, context_utilized=ctx_tokens)
    stage_metrics = timer.finish().to_dict()

    response = CodeExplanationResponse(
        run_id=run_id,
        repository_id=str(repository_id),
        status=status_val,
        target=resolved.target,
        revision=revision,
        explanation=grounded_explanation,
        stage_metrics=stage_metrics,
    )
    response = CodeExplanationResponse.model_validate(redact_obj(response.model_dump(mode="json")))

    if payload.options.persist_run:
        record_analysis_run(
            request.app.state,
            db,
            run_id=response.run_id,
            repository_id=repository_id,
            user_id=user_id,
            feature_type="explain",
            status=response.status,
            target=response.target,
            revision=response.revision,
            result_payload=response.model_dump(mode="json"),
            findings_count=0,
        )

    return response

