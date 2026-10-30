"""
Test Generation API endpoint (POST /api/v1/repositories/{repository_id}/generate-tests).
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
    ExplainCodeRequest,
    TestGenerationRequest,
    TestGenerationResponse,
    TestGenerationResult,
)
from app.services.explanation_orchestrator import (
    record_analysis_run,
    resolve_target_and_build_context,
)
from app.services.test_generation_orchestrator import (
    build_repository_test_context,
    detect_repository_test_framework,
    validate_and_sanitize_generated_tests,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["analysis"])


@router.post(
    "/repositories/{repository_id}/generate-tests",
    response_model=TestGenerationResponse,
    responses=ANALYSIS_ERROR_RESPONSES,
    summary="Generate framework-aware test files for a repository file or symbol",
    description=(
        "Detect the repository's configured test framework (`pytest`, `unittest`, or `jest`), "
        "propose a safe convention-matching test file path, generate complete previewable test code "
        "covering normal, edge_case, and failure_path scenarios, and validate syntax without executing code."
    ),
)
async def generate_tests(
    repository_id: UUID,
    payload: TestGenerationRequest,
    request: Request,
    db: Session = Depends(get_db),
) -> TestGenerationResponse:
    """Execute the Week 2 Day 4 Framework-Aware Test Generation pipeline."""
    timer = StageExecutionTimer("generate_tests", context_budget=payload.options.max_context_tokens)
    user_id = _request_user_id(request)
    repo = _owned_repository(repository_id, request, db)

    with timer.measure("target_resolution_and_context"):
        explain_compat_req = ExplainCodeRequest(target=payload.target, options=payload.options)
        resolved = resolve_target_and_build_context(repository_id, repo, explain_compat_req, db)
        payload.target = resolved.target

    with timer.measure("framework_detection"):
        detection, manifest_contents, all_repo_files = detect_repository_test_framework(
            repository_id=repository_id,
            target_path=resolved.target.path,
            requested_framework=payload.framework,
            db=db,
            preloaded_repo_files=resolved.repo_files if resolved.repo_files else None,
        )
        test_context, proposed_test_path = build_repository_test_context(
            repository_id=repository_id,
            resolved=resolved,
            detection=detection,
            manifest_contents=manifest_contents,
            all_repo_files=all_repo_files,
            token_budget=payload.options.max_context_tokens,
        )

    service = _get_service(request, "test_generation_service", "Test generation")
    method = service.generate_tests if hasattr(service, "generate_tests") else service

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
                    "context": test_context,
                    "code_content": resolved.code_content,
                    "detected_framework": detection.framework or "pytest",
                    "proposed_test_path": proposed_test_path,
                    "fixtures": list(detection.fixtures),
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
                feature_type="generate_tests",
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
                feature_type="generate_tests",
                status="FAILED",
                target=resolved.target,
                revision=resolved.revision,
                error_message=safe_err,
            )
        raise APIError(
            500,
            ErrorCode.ANALYSIS_FAILED,
            "Test generation failed during execution.",
            retryable=False,
        ) from exc

    status_val = "COMPLETED"
    revision = resolved.revision
    try:
        if isinstance(raw_result, TestGenerationResponse):
            run_id = raw_result.run_id or run_id
            status_val = raw_result.status
            revision = raw_result.revision or resolved.revision
            test_result = raw_result.result
        elif isinstance(raw_result, TestGenerationResult):
            test_result = raw_result
        elif isinstance(raw_result, dict) and "result" in raw_result:
            run_id = str(raw_result.get("run_id") or run_id)
            status_val = raw_result.get("status", "COMPLETED")
            revision = raw_result.get("revision") or resolved.revision
            test_result = TestGenerationResult.model_validate(raw_result["result"])
        else:
            if isinstance(raw_result, dict):
                raw_copy = dict(raw_result)
                raw_copy.setdefault("detected_framework", detection.framework or "pytest")
                raw_copy.setdefault("proposed_test_path", proposed_test_path)
                test_result = TestGenerationResult.model_validate(raw_copy)
            else:
                test_result = TestGenerationResult.model_validate(raw_result)
    except (ValidationError, ValueError, TypeError) as exc:
        logger.error("generate_tests_output_schema_invalid", extra={"error": str(exc)})
        if payload.options.persist_run:
            record_analysis_run(
                request.app.state,
                db,
                run_id=run_id,
                repository_id=repository_id,
                user_id=user_id,
                feature_type="generate_tests",
                status="FAILED",
                target=resolved.target,
                revision=revision,
                error_message="Test generation service returned an invalid output schema.",
            )
        raise APIError(
            500,
            ErrorCode.ANALYSIS_FAILED,
            "Test generation service returned an invalid output schema.",
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
                feature_type="generate_tests",
                status="FAILED",
                target=resolved.target,
                revision=revision,
                error_message="Test generation failed during execution.",
            )
        raise APIError(
            500,
            ErrorCode.ANALYSIS_FAILED,
            "Test generation failed.",
            retryable=True,
        )

    with timer.measure("validation_and_sanitization"):
        sanitized_result = validate_and_sanitize_generated_tests(
            test_result,
            repository_id=repository_id,
            resolved=resolved,
            detection=detection,
            default_proposed_path=proposed_test_path,
        )

    ctx_tokens = getattr(test_context, "total_tokens", None) if test_context else None
    prompt_tokens = getattr(raw_result, "input_tokens", None) or (ctx_tokens or 0)
    completion_tokens = getattr(raw_result, "output_tokens", None) or len((sanitized_result.test_content or "").split())
    timer.record_tokens(prompt_tokens=prompt_tokens, completion_tokens=completion_tokens, context_utilized=ctx_tokens)
    stage_metrics = timer.finish().to_dict()

    response = TestGenerationResponse(
        run_id=run_id,
        repository_id=str(repository_id),
        status=status_val,
        target=resolved.target,
        revision=revision,
        result=sanitized_result,
        stage_metrics=stage_metrics,
    )
    response = TestGenerationResponse.model_validate(redact_obj(response.model_dump(mode="json")))

    if payload.options.persist_run:
        payload_dict = response.model_dump(mode="json")
        payload_dict["test_content"] = response.result.test_content
        record_analysis_run(
            request.app.state,
            db,
            run_id=response.run_id,
            repository_id=repository_id,
            user_id=user_id,
            feature_type="generate_tests",
            status=response.status,
            target=response.target,
            revision=response.revision,
            result_payload=payload_dict,
            test_output=response.result.test_content,
            findings_count=len(response.result.covered_scenarios),
        )

    return response

