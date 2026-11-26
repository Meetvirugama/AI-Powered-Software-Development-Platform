"""
Code Explanation API endpoint (POST /api/v1/repositories/{repository_id}/explain).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
import logging
from typing import Any
from uuid import UUID, uuid4

from ai.intelligence.related_files import (
    RelatedFileDiscoveryService,
    RelatedFilesDiscoveryResponse,
)
from ai.intelligence.snapshot_manager import RepositoryIntelligenceSnapshotManager
from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.api.v1.analysis.common import (
    ANALYSIS_ERROR_RESPONSES,
    _get_service,
    _invoke_service_method,
    _owned_repository,
    _owned_repository_async,
    _request_user_id,
    fresh_analysis_session,
    make_sse_response,
    stream_analysis_events,
)
from app.core.database import get_db, run_db
from app.core.errors import APIError, ErrorCode
from app.core.input_security import require_safe_repo_path
from app.core.secret_redaction import redact, redact_obj
from app.core.stage_metrics import StageExecutionTimer
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


@router.get(
    "/repositories/{repository_id}/explain/related-files",
    response_model=RelatedFilesDiscoveryResponse,
    responses=ANALYSIS_ERROR_RESPONSES,
    summary="Discover automatically related files for a code explanation target",
    description="Traverses the repository knowledge graph to discover direct dependencies, callers, database models, schemas, and tests for a selected file/symbol.",
)
def get_related_files(
    repository_id: UUID,
    path: str,
    request: Request,
    symbol: str | None = None,
    db: Session = Depends(get_db),
) -> RelatedFilesDiscoveryResponse:
    """Discover related files and graph neighbors for a selected target file or symbol."""
    _owned_repository(repository_id, request, db)
    safe_path = require_safe_repo_path(path)

    snap_mgr = RepositoryIntelligenceSnapshotManager()
    snapshot = snap_mgr.load_latest_snapshot(repository_id)

    all_files: list[str] = []
    if not snapshot:
        from app.models.repository_file import RepositoryFile

        file_rows = (
            db.query(RepositoryFile.path)
            .filter(RepositoryFile.repository_id == repository_id)
            .all()
        )
        all_files = [r[0] for r in file_rows]

    discovery_svc = RelatedFileDiscoveryService(snapshot=snapshot)
    discovered = discovery_svc.discover_related_files(
        target_path=safe_path,
        target_symbol=symbol,
        snapshot=snapshot,
        all_repo_files=all_files,
    )
    return RelatedFilesDiscoveryResponse(
        target_path=safe_path,
        target_symbol=symbol,
        related_files=discovered,
        total_discovered=len(discovered),
    )


async def _execute_explain_pipeline(
    repository_id: UUID,
    payload: ExplainCodeRequest,
    request: Request,
    db: Session,
    *,
    service: Any | None = None,
    on_stage: Callable[[str, str], Awaitable[None]] | None = None,
) -> CodeExplanationResponse:
    """Execute the 9-step Week 2 Day 2 Code Explanation pipeline."""
    async def _stage(name: str, message: str) -> None:
        if on_stage is not None:
            await on_stage(name, message)

    timer = StageExecutionTimer("explain", context_budget=payload.options.max_context_tokens)
    user_id = _request_user_id(request)
    repo = await _owned_repository_async(repository_id, request, db)

    await _stage("retrieving_context", "Resolving target and building repository context...")
    with timer.measure("target_resolution_and_context"):
        resolved = await run_db(db, resolve_target_and_build_context, repository_id, repo, payload, db)
        payload.target = resolved.target

    await _stage("analyzing_ast", "Analyzing symbol graph and code dependencies...")
    resolved_service = service if service is not None else _get_service(request, "explanation_service", "Code explanation")
    method = resolved_service.explain if hasattr(resolved_service, "explain") else resolved_service

    run_id = str(uuid4())
    await _stage("generating_output", "Synthesizing structured explanation...")
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
            await run_db(
                db,
                record_analysis_run,
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
            await run_db(
                db,
                record_analysis_run,
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
            await run_db(
                db,
                record_analysis_run,
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
            await run_db(
                db,
                record_analysis_run,
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

    await _stage("validating_grounding", "Grounding source citations and validating output...")
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
        await run_db(
            db,
            record_analysis_run,
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
    return await _execute_explain_pipeline(repository_id, payload, request, db)


@router.post(
    "/repositories/{repository_id}/explain/stream",
    summary="Stream stage progress and result for code explanation via Server-Sent Events",
    responses={**ANALYSIS_ERROR_RESPONSES, 200: {"content": {"text/event-stream": {}}}},
)
async def explain_code_stream(
    repository_id: UUID,
    payload: ExplainCodeRequest,
    request: Request,
    db: Session = Depends(get_db),
) -> StreamingResponse:
    """Stream real-time stage progress events followed by the final CodeExplanationResponse."""
    await _owned_repository_async(repository_id, request, db)
    service = _get_service(request, "explanation_service", "Code explanation")

    async def _run(emit_stage: Callable[[str, str], Awaitable[None]]) -> CodeExplanationResponse:
        with fresh_analysis_session(request) as stream_db:
            return await _execute_explain_pipeline(
                repository_id,
                payload,
                request,
                stream_db,
                service=service,
                on_stage=emit_stage,
            )

    return make_sse_response(stream_analysis_events(_run))

