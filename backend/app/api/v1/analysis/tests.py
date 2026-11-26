"""
Test Generation API endpoint (POST /api/v1/repositories/{repository_id}/generate-tests).
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
import inspect
import logging
from typing import Any
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.api.v1.analysis.common import (
    ANALYSIS_ERROR_RESPONSES,
    _get_service,
    _invoke_service_method,
    _owned_repository_async,
    _request_user_id,
    fresh_analysis_session,
    make_sse_response,
    stream_analysis_events,
)
from app.api.v1.dependencies import ensure_min_role
from app.core.database import get_db, run_db
from app.models.user import UserRole
from app.core.errors import APIError, ErrorCode
from app.core.secret_redaction import redact, redact_obj
from app.core.stage_metrics import StageExecutionTimer
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


def _discover_test_requirements(
    repository_id: UUID,
    payload: TestGenerationRequest,
    db: Session,
    all_repo_files: Any,
    manifest_contents: dict[str, str],
    resolved: Any,
) -> Any:
    """Query symbols/edges and compute prioritized test requirement gaps."""
    from app.models.code_symbol import CodeSymbol
    from app.models.symbol_edge import SymbolEdge as DbSymbolEdge
    from app.services.test_requirement_orchestrator import TestRequirementOrchestrator

    repo_symbols = (
        db.query(CodeSymbol).filter(CodeSymbol.repository_id == repository_id).all()
        if hasattr(db, "query")
        else []
    )
    repo_edges = (
        db.query(DbSymbolEdge).filter(DbSymbolEdge.repository_id == repository_id).all()
        if hasattr(db, "query")
        else []
    )
    file_contents = dict(manifest_contents)
    if resolved.target.path and resolved.code_content:
        file_contents[resolved.target.path] = resolved.code_content

    req_orchestrator = TestRequirementOrchestrator()
    return req_orchestrator.orchestrate_requirements(
        repository_id=repository_id,
        payload=payload,
        db=db,
        all_repo_files=all_repo_files,
        repo_symbols=repo_symbols,
        repo_edges=repo_edges,
        file_contents=file_contents,
    )


async def _execute_generate_tests_pipeline(
    repository_id: UUID,
    payload: TestGenerationRequest,
    request: Request,
    db: Session,
    *,
    service: Any | None = None,
    on_stage: Callable[[str, str], Awaitable[None]] | None = None,
) -> TestGenerationResponse:
    """Execute the Week 2 Day 4 Framework-Aware Test Generation pipeline."""
    async def _stage(name: str, message: str) -> None:
        if on_stage is not None:
            await on_stage(name, message)

    ensure_min_role(request, UserRole.DEVELOPER)
    timer = StageExecutionTimer("generate_tests", context_budget=payload.options.max_context_tokens)
    user_id = _request_user_id(request)
    repo = await _owned_repository_async(repository_id, request, db)

    await _stage("retrieving_context", "Resolving target and gathering repository context...")
    with timer.measure("target_resolution_and_context"):
        explain_compat_req = ExplainCodeRequest(target=payload.target, options=payload.options)
        resolved = await run_db(db, resolve_target_and_build_context, repository_id, repo, explain_compat_req, db)
        payload.target = resolved.target

    await _stage("detecting_framework", "Detecting test framework, fixtures, and coverage gaps...")
    with timer.measure("framework_detection"):
        detection, manifest_contents, all_repo_files = await run_db(
            db,
            detect_repository_test_framework,
            repository_id=repository_id,
            target_path=resolved.target.path,
            requested_framework=payload.framework,
            db=db,
            preloaded_repo_files=resolved.repo_files if resolved.repo_files else None,
        )
        test_context, proposed_test_path = await run_db(
            db,
            build_repository_test_context,
            repository_id=repository_id,
            resolved=resolved,
            detection=detection,
            manifest_contents=manifest_contents,
            all_repo_files=all_repo_files,
            token_budget=payload.options.max_context_tokens,
        )

    req_result = None
    with timer.measure("requirement_discovery"):
        try:
            req_result = await run_db(
                db,
                _discover_test_requirements,
                repository_id,
                payload,
                db,
                all_repo_files,
                manifest_contents,
                resolved,
            )
        except Exception as req_exc:
            logger.warning(f"Test requirement discovery encountered error: {req_exc}")

    resolved_service = service if service is not None else _get_service(request, "test_generation_service", "Test generation")
    method = resolved_service.generate_tests if hasattr(resolved_service, "generate_tests") else resolved_service

    run_id = str(uuid4())
    await _stage("generating_output", "Generating framework-aware unit and edge-case tests...")
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
                    "requirements": req_result.prioritized_gaps if req_result else [],
                },
            )
    except APIError as exc:
        if payload.options.persist_run:
            await run_db(
                db,
                record_analysis_run,
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
            await run_db(
                db,
                record_analysis_run,
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
            await run_db(
                db,
                record_analysis_run,
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
            await run_db(
                db,
                record_analysis_run,
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

    await _stage("validating_syntax", "Validating generated test syntax and coverage...")
    with timer.measure("validation_and_sanitization"):
        sanitized_result = validate_and_sanitize_generated_tests(
            test_result,
            repository_id=repository_id,
            resolved=resolved,
            detection=detection,
            default_proposed_path=proposed_test_path,
        )
        if req_result:
            update_fields: dict[str, Any] = {}
            if not sanitized_result.requirements:
                update_fields["requirements"] = req_result.requirements
            if not sanitized_result.quality_report:
                update_fields["quality_report"] = req_result.quality_report
            if not sanitized_result.missing_requirements:
                update_fields["missing_requirements"] = [
                    r.requirement_id for r in req_result.requirements if r.status in ("MISSING", "BLOCKED")
                ]
            if update_fields:
                sanitized_result = sanitized_result.model_copy(update=update_fields)

    with timer.measure("execution_and_verification"):
        if payload.run_isolated_execution:
            if (
                sanitized_result.verification_status in (None, "UNVERIFIED")
                and not sanitized_result.execution_attempted
            ):
                try:
                    verifier = getattr(request.app.state, "test_execution_verifier", None)
                    if verifier is None:
                        from app.services.test_execution_verifier import TestExecutionVerifier

                        verifier = TestExecutionVerifier()

                    # Sandbox verification is synchronous and slow (3 stability
                    # runs, two coverage passes, mutation scoring). Running it in
                    # a worker thread keeps the event loop serving other requests.
                    verify_kwargs = dict(
                        result=sanitized_result,
                        target_path=resolved.target.path or "",
                        target_source_code=resolved.code_content or "",
                        repository_id=str(repository_id),
                        base_revision=resolved.revision,
                        existing_files=manifest_contents,
                    )
                    verify_fn = verifier.verify_generated_test
                    if inspect.iscoroutinefunction(verify_fn):
                        verified_result = await verify_fn(**verify_kwargs)
                    else:
                        verified_result = await asyncio.to_thread(verify_fn, **verify_kwargs)
                        if inspect.isawaitable(verified_result):
                            verified_result = await verified_result
                    sanitized_result = verified_result
                except Exception as verif_exc:
                    logger.warning(f"Test verification pipeline error: {verif_exc}")
                    sanitized_result = sanitized_result.model_copy(
                        update={
                            "verification_status": "EXECUTION_ERROR",
                            "verification_reasons": [f"Verification runner error: {verif_exc}"],
                        }
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
        await run_db(
            db,
            record_analysis_run,
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
    return await _execute_generate_tests_pipeline(repository_id, payload, request, db)


@router.post(
    "/repositories/{repository_id}/generate-tests/stream",
    summary="Stream stage progress and result for test generation via Server-Sent Events",
    responses={**ANALYSIS_ERROR_RESPONSES, 200: {"content": {"text/event-stream": {}}}},
)
async def generate_tests_stream(
    repository_id: UUID,
    payload: TestGenerationRequest,
    request: Request,
    db: Session = Depends(get_db),
) -> StreamingResponse:
    """Stream real-time stage progress events followed by the final TestGenerationResponse."""
    ensure_min_role(request, UserRole.DEVELOPER)
    await _owned_repository_async(repository_id, request, db)
    service = _get_service(request, "test_generation_service", "Test generation")

    async def _run(emit_stage: Callable[[str, str], Awaitable[None]]) -> TestGenerationResponse:
        with fresh_analysis_session(request) as stream_db:
            return await _execute_generate_tests_pipeline(
                repository_id,
                payload,
                request,
                stream_db,
                service=service,
                on_stage=emit_stage,
            )

    return make_sse_response(stream_analysis_events(_run))

