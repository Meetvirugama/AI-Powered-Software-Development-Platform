"""
Bug Detection API endpoint (POST /api/v1/repositories/{repository_id}/detect-bugs).
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
    BugDetectionRequest,
    BugDetectionResponse,
    ExplainCodeRequest,
)
from app.services.bug_detection_orchestrator import (
    BuiltinStaticBugScanner,
    filter_and_rank_findings,
    merge_and_deduplicate_findings,
    normalize_and_ground_findings,
)
from app.services.explanation_orchestrator import (
    record_analysis_run,
    resolve_target_and_build_context,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["analysis"])


@router.post(
    "/repositories/{repository_id}/detect-bugs",
    response_model=BugDetectionResponse,
    responses=ANALYSIS_ERROR_RESPONSES,
    summary="Detect potential bugs using static analysis and AI reasoning",
    description=(
        "Scan an authorized repository file, symbol, or line range using deterministic AST/static rules "
        "and AI defect reasoning. Merges overlapping findings into `COMBINED`, redacts secret values, "
        "and ranks findings by severity."
    ),
)
async def detect_bugs(
    repository_id: UUID,
    payload: BugDetectionRequest,
    request: Request,
    db: Session = Depends(get_db),
) -> BugDetectionResponse:
    """Execute the Week 2 Day 3 Dedicated Bug Detection pipeline."""
    timer = StageExecutionTimer("detect_bugs", context_budget=payload.options.max_context_tokens)
    user_id = _request_user_id(request)
    repo = _owned_repository(repository_id, request, db)

    with timer.measure("target_resolution_and_context"):
        explain_compat_req = ExplainCodeRequest(target=payload.target, options=payload.options)
        resolved = resolve_target_and_build_context(repository_id, repo, explain_compat_req, db)
        payload.target = resolved.target

    service = _get_service(request, "bug_detection_service", "Bug detection")
    method = service.detect_bugs if hasattr(service, "detect_bugs") else service

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
                    "skip_internal_static": True,
                    "_skip_engine_static": True,
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
                feature_type="detect_bugs",
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
                feature_type="detect_bugs",
                status="FAILED",
                target=resolved.target,
                revision=resolved.revision,
                error_message=safe_err,
            )
        raise APIError(
            500,
            ErrorCode.ANALYSIS_FAILED,
            "Bug detection failed during execution.",
            retryable=False,
        ) from exc

    extra_static_raw: list[Any] = []
    parser_warnings: list[str] = []
    if payload.include_static:
        with timer.measure("static_analysis"):
            ext_scanner = getattr(request.app.state, "static_bug_scanner", None)
            if ext_scanner is not None:
                scan_fn = getattr(ext_scanner, "scan", ext_scanner)
                if callable(scan_fn):
                    try:
                        if inspect.iscoroutinefunction(scan_fn):
                            ext_res = await scan_fn(
                                repository_id=repository_id,
                                file_path=resolved.target.path,
                                code_content=resolved.code_content,
                                target=resolved.target,
                            )
                        else:
                            ext_res = await asyncio.to_thread(
                                scan_fn,
                                repository_id=repository_id,
                                file_path=resolved.target.path,
                                code_content=resolved.code_content,
                                target=resolved.target,
                            )
                        if inspect.isawaitable(ext_res):
                            ext_res = await ext_res
                        if isinstance(ext_res, dict):
                            extra_static_raw.extend(ext_res.get("findings", []))
                        elif isinstance(ext_res, list):
                            extra_static_raw.extend(ext_res)
                    except Exception as exc:
                        logger.warning("external_static_scanner_error", extra={"error": str(exc)})
                        parser_warnings.append("External static scanner encountered an error.")

            if resolved.code_content:
                scanner = BuiltinStaticBugScanner()
                builtin_items, builtin_warns = await asyncio.to_thread(
                    scanner.scan,
                    file_path=resolved.target.path,
                    code_content=resolved.code_content,
                    language=(resolved.file_record.language if resolved.file_record else "Python") or "Python",
                    base_start_line=resolved.target.start_line or 1,
                    revision=resolved.revision,
                    repository_id=str(repository_id),
                )
                extra_static_raw.extend(builtin_items)
                parser_warnings.extend(builtin_warns)

    status_val = "COMPLETED"
    revision = resolved.revision
    service_missing_ctx: list[str] = []
    try:
        if isinstance(raw_result, BugDetectionResponse):
            run_id = raw_result.run_id or run_id
            status_val = raw_result.status
            revision = raw_result.revision or resolved.revision
            raw_findings_list: list[Any] = list(raw_result.findings)
            service_missing_ctx = list(raw_result.missing_context)
        elif isinstance(raw_result, dict):
            if "findings" not in raw_result and "status" not in raw_result:
                raise ValueError("Bug detection dict result must contain 'findings'.")
            run_id = str(raw_result.get("run_id") or run_id)
            status_val = raw_result.get("status", "COMPLETED")
            revision = raw_result.get("revision") or resolved.revision
            raw_findings_list = list(raw_result.get("findings", []))
            service_missing_ctx = list(raw_result.get("missing_context", []))
        elif isinstance(raw_result, list):
            raw_findings_list = list(raw_result)
        else:
            parsed_resp = BugDetectionResponse.model_validate(raw_result)
            run_id = parsed_resp.run_id or run_id
            status_val = parsed_resp.status
            revision = parsed_resp.revision or resolved.revision
            raw_findings_list = list(parsed_resp.findings)
            service_missing_ctx = list(parsed_resp.missing_context)

        if status_val == "FAILED":
            if payload.options.persist_run:
                record_analysis_run(
                    request.app.state,
                    db,
                    run_id=run_id,
                    repository_id=repository_id,
                    user_id=user_id,
                    feature_type="detect_bugs",
                    status="FAILED",
                    target=resolved.target,
                    revision=revision,
                    error_message="Bug detection scan failed.",
                )
            raise APIError(
                500,
                ErrorCode.ANALYSIS_FAILED,
                "Bug detection scan failed.",
                retryable=True,
            )

        with timer.measure("grounding_and_ranking"):
            grounded_service, _ = normalize_and_ground_findings(
                raw_findings_list,
                repository_id=repository_id,
                resolved=resolved,
            )
            grounded_static, _ = normalize_and_ground_findings(
                extra_static_raw,
                repository_id=repository_id,
                resolved=resolved,
                default_source_type="STATIC",
            )
            merged_findings = merge_and_deduplicate_findings([*grounded_static, *grounded_service])
            ranked_findings = filter_and_rank_findings(
                merged_findings,
                min_severity=payload.min_severity,
                include_static=payload.include_static,
                include_ai=payload.include_ai,
            )
    except APIError:
        raise
    except (ValidationError, ValueError, TypeError) as exc:
        logger.error("detect_bugs_output_schema_invalid", extra={"error": str(exc)})
        if payload.options.persist_run:
            record_analysis_run(
                request.app.state,
                db,
                run_id=run_id,
                repository_id=repository_id,
                user_id=user_id,
                feature_type="detect_bugs",
                status="FAILED",
                target=resolved.target,
                revision=revision,
                error_message="Bug detection service returned an invalid output schema.",
            )
        raise APIError(
            500,
            ErrorCode.ANALYSIS_FAILED,
            "Bug detection service returned an invalid output schema.",
            retryable=False,
        ) from exc

    static_count = sum(
        1 for f in ranked_findings if f.source_type in ("STATIC", "COMBINED")
    )
    ai_count = sum(
        1 for f in ranked_findings if f.source_type in ("AI", "COMBINED")
    )
    merged_missing = list(
        dict.fromkeys([*resolved.missing_context, *parser_warnings, *service_missing_ctx])
    )

    ctx_tokens = getattr(resolved.intelligence_context, "total_tokens", None) if resolved else None
    prompt_tokens = getattr(raw_result, "input_tokens", None) or (ctx_tokens or 0)
    completion_tokens = getattr(raw_result, "output_tokens", None) or len(ranked_findings) * 50
    timer.record_tokens(prompt_tokens=prompt_tokens, completion_tokens=completion_tokens, context_utilized=ctx_tokens)
    stage_metrics = timer.finish().to_dict()

    response = BugDetectionResponse(
        run_id=run_id,
        repository_id=str(repository_id),
        status=status_val,
        target=resolved.target,
        revision=revision,
        findings=ranked_findings,
        total_findings=len(ranked_findings),
        static_findings_count=static_count,
        ai_findings_count=ai_count,
        missing_context=merged_missing,
        stage_metrics=stage_metrics,
    )
    response = BugDetectionResponse.model_validate(redact_obj(response.model_dump(mode="json")))

    if payload.options.persist_run:
        record_analysis_run(
            request.app.state,
            db,
            run_id=response.run_id,
            repository_id=repository_id,
            user_id=user_id,
            feature_type="detect_bugs",
            status=response.status,
            target=response.target,
            revision=response.revision,
            result_payload=response.model_dump(mode="json"),
            findings=[f.model_dump(mode="json") for f in response.findings],
            findings_count=len(response.findings),
        )

    return response

