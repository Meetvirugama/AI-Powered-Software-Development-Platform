"""Developer Intelligence Suite API endpoints (Week 2 — Day 1, Day 2 & Day 3).

Owner: Yug — W2, Day 1–3 (API Foundation, Code Explanation & Dedicated Bug Detection)

Endpoints registered:
- POST /api/v1/repositories/{repository_id}/explain
- POST /api/v1/repositories/{repository_id}/detect-bugs
- POST /api/v1/repositories/{repository_id}/generate-tests
- POST /api/v1/repositories/{repository_id}/review
- GET  /api/v1/repositories/{repository_id}/analysis-runs
- GET  /api/v1/analysis-runs/{run_id}
"""

from __future__ import annotations

import inspect
import logging
from datetime import datetime, timezone
from typing import Any, Protocol
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Query, Request
from pydantic import ValidationError
from sqlalchemy.orm import Session

from ai.llm.schemas import (
    LLMError,
    LLMRateLimitError,
    LLMTimeoutError,
    LLMUnavailableError,
    LLMValidationError,
)
from app.core.database import get_db
from app.core.errors import APIError, ErrorCode
from app.core.input_security import require_safe_repo_path
from app.core.secret_redaction import redact_obj
from app.models.repository import Repository
from app.models.repository_file import RepositoryFile
from app.repositories.repository_repository import RepositoryRepository
from app.schemas.analysis import (
    AnalysisFeatureType,
    AnalysisRunDetailResponse,
    AnalysisRunSummary,
    AnalysisTarget,
    BugDetectionRequest,
    BugDetectionResponse,
    CodeExplanation,
    CodeExplanationResponse,
    CodeReviewRequest,
    ExplainCodeRequest,
    PaginatedAnalysisRunResponse,
    ReviewReport,
    ReviewReportResponse,
    TestGenerationRequest,
    TestGenerationResponse,
    TestGenerationResult,
)
from app.services.bug_detection_orchestrator import (
    BuiltinStaticBugScanner,
    filter_and_rank_findings,
    merge_and_deduplicate_findings,
    normalize_and_ground_findings,
)
from app.services.code_review_orchestrator import (
    build_grounded_review_report,
    merge_and_rank_review_findings,
    normalize_and_ground_review_findings,
    resolve_review_target_and_build_context,
    run_static_review_on_changes,
)
from app.services.explanation_orchestrator import (
    MAX_ANALYZABLE_FILE_BYTES,
    ground_explanation_sources,
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


# ---------------------------------------------------------------------------
# Service Protocols (Published Day 1 Interfaces for Dev, Meet, Devu, Om)
# ---------------------------------------------------------------------------

class CodeExplanationServiceProtocol(Protocol):
    """Protocol implemented by Dev's CodeExplanationService (Day 2)."""

    async def explain(
        self,
        repository_id: UUID,
        payload: ExplainCodeRequest,
        **kwargs: Any,
    ) -> CodeExplanationResponse | CodeExplanation | dict[str, Any]: ...


class BugDetectionServiceProtocol(Protocol):
    """Protocol implemented by Dev & Devu's BugDetectionEngine (Day 3)."""

    async def detect_bugs(
        self,
        repository_id: UUID,
        payload: BugDetectionRequest,
        **kwargs: Any,
    ) -> BugDetectionResponse | dict[str, Any]: ...


class TestGenerationServiceProtocol(Protocol):
    """Protocol implemented by Dev & Prit's TestGenerationService (Day 4)."""

    async def generate_tests(
        self,
        repository_id: UUID,
        payload: TestGenerationRequest,
        **kwargs: Any,
    ) -> TestGenerationResponse | TestGenerationResult | dict[str, Any]: ...


class CodeReviewServiceProtocol(Protocol):
    """Protocol implemented by Dev & Parth's AICodeReviewEngine (Day 5)."""

    async def review(
        self,
        repository_id: UUID,
        payload: CodeReviewRequest,
        **kwargs: Any,
    ) -> ReviewReportResponse | ReviewReport | dict[str, Any]: ...


class AnalysisRunPersistenceProtocol(Protocol):
    """Protocol implemented by Om's AnalysisRunRepository / service (Day 1–5)."""

    def list_runs(
        self,
        repository_id: UUID,
        *,
        feature_type: str | None = None,
        status: str | None = None,
        offset: int = 0,
        limit: int = 20,
    ) -> tuple[list[Any], int]: ...

    def get_run(self, run_id: UUID) -> Any | None: ...


# ---------------------------------------------------------------------------
# Authentication, Ownership & Target Validation Helpers
# ---------------------------------------------------------------------------

def _request_user_id(request: Request) -> UUID:
    try:
        return UUID(str(request.state.user_id))
    except (AttributeError, ValueError) as exc:
        raise APIError(401, ErrorCode.UNAUTHORIZED, "Invalid authenticated user.") from exc


def _owned_repository(repository_id: UUID, request: Request, db: Session) -> Repository:
    user_id = _request_user_id(request)
    repository = RepositoryRepository(db).get_for_user(repository_id, user_id)
    if repository is None:
        raise APIError(
            404,
            ErrorCode.REPOSITORY_NOT_FOUND,
            "Repository does not exist or you do not have access.",
        )
    return repository


def _validate_and_normalize_code_target(
    repository_id: UUID,
    target: AnalysisTarget,
    db: Session,
) -> RepositoryFile | None:
    """Validate path safety and check indexed file bounds when DB records exist."""
    safe_path = require_safe_repo_path(target.path)
    target.path = safe_path

    if not hasattr(db, "query"):
        return None

    try:
        repo_has_files = (
            db.query(RepositoryFile.id)
            .filter(RepositoryFile.repository_id == repository_id)
            .first()
            is not None
        )
        if not repo_has_files:
            return None

        file_record = (
            db.query(RepositoryFile)
            .filter(
                RepositoryFile.repository_id == repository_id,
                RepositoryFile.path == safe_path,
            )
            .first()
        )
    except Exception:
        return None

    if file_record is None:
        raise APIError(
            404,
            ErrorCode.FILE_NOT_FOUND,
            f"Target file '{safe_path}' was not found in the indexed repository.",
        )

    if getattr(file_record, "size_bytes", 0) > MAX_ANALYZABLE_FILE_BYTES:
        raise APIError(
            413,
            ErrorCode.PAYLOAD_TOO_LARGE,
            "Target file exceeds the maximum analyzable size limit (1 MB).",
        )

    line_count = getattr(file_record, "line_count", 0) or 0
    if line_count > 0:
        if target.start_line is not None and target.start_line > line_count:
            raise APIError(
                400,
                ErrorCode.INVALID_REQUEST,
                f"start_line ({target.start_line}) exceeds file line count ({line_count}).",
            )
        if target.end_line is not None and target.end_line > line_count:
            raise APIError(
                400,
                ErrorCode.INVALID_REQUEST,
                f"end_line ({target.end_line}) exceeds file line count ({line_count}).",
            )

    return file_record


def _get_service(request: Request, attr_name: str, feature_label: str) -> Any:
    """Resolve an analysis service from `request.app.state` or raise 503."""
    service = getattr(request.app.state, attr_name, None)
    if service is None:
        raise APIError(
            503,
            ErrorCode.SERVICE_UNAVAILABLE,
            f"{feature_label} is not available because `{attr_name}` is not configured.",
            retryable=True,
        )
    return service


async def _invoke_service_method(
    method: Any,
    repository_id: UUID,
    payload: Any,
    *,
    user_id: UUID,
    db: Session,
    file_record: RepositoryFile | None = None,
    extra_kwargs: dict[str, Any] | None = None,
) -> Any:
    """Invoke a sync or async service method while passing supported keyword args."""
    kwargs: dict[str, Any] = {}
    try:
        sig = inspect.signature(method)
        params = sig.parameters
        accepts_var_kw = any(
            p.kind == inspect.Parameter.VAR_KEYWORD for p in params.values()
        )
        if accepts_var_kw or "user_id" in params:
            kwargs["user_id"] = user_id
        if accepts_var_kw or "db" in params:
            kwargs["db"] = db
        if file_record is not None and (accepts_var_kw or "file_record" in params):
            kwargs["file_record"] = file_record
        if extra_kwargs:
            for k, v in extra_kwargs.items():
                if accepts_var_kw or k in params:
                    kwargs[k] = v
    except (TypeError, ValueError):
        pass

    try:
        result = method(repository_id, payload, **kwargs)
        if inspect.isawaitable(result):
            result = await result
        return result
    except APIError:
        raise
    except (LLMTimeoutError, LLMRateLimitError, LLMUnavailableError) as exc:
        logger.warning(
            "analysis_llm_unavailable",
            extra={"repository_id": str(repository_id), "error": str(exc)},
        )
        raise APIError(
            503,
            ErrorCode.SERVICE_UNAVAILABLE,
            "AI analysis provider is temporarily unavailable. Please try again.",
            retryable=True,
        ) from exc
    except (LLMValidationError, LLMError) as exc:
        logger.error(
            "analysis_llm_validation_failed",
            extra={"repository_id": str(repository_id), "error": str(exc)},
        )
        raise APIError(
            500,
            ErrorCode.ANALYSIS_FAILED,
            "AI analysis output failed validation and could not be repaired.",
            retryable=False,
        ) from exc


# ---------------------------------------------------------------------------
# 1. Code Explanation Endpoint (POST /api/v1/repositories/{repository_id}/explain)
# ---------------------------------------------------------------------------

@router.post(
    "/repositories/{repository_id}/explain",
    response_model=CodeExplanationResponse,
    summary="Explain a file, symbol, or line range using repository context",
)
async def explain_code(
    repository_id: UUID,
    payload: ExplainCodeRequest,
    request: Request,
    db: Session = Depends(get_db),
) -> CodeExplanationResponse:
    """Execute the 9-step Week 2 Day 2 Code Explanation pipeline."""
    user_id = _request_user_id(request)
    repo = _owned_repository(repository_id, request, db)

    resolved = resolve_target_and_build_context(repository_id, repo, payload, db)
    payload.target = resolved.target

    service = _get_service(request, "explanation_service", "Code explanation")
    method = service.explain if hasattr(service, "explain") else service

    run_id = str(uuid4())
    try:
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

    grounded_explanation = ground_explanation_sources(
        explanation,
        repository_id=repository_id,
        resolved=resolved,
    )

    response = CodeExplanationResponse(
        run_id=run_id,
        repository_id=str(repository_id),
        status=status_val,
        target=resolved.target,
        revision=revision,
        explanation=grounded_explanation,
    )
    # Security (W2 Day 2): the model may copy secrets from the source code into
    # its explanation — redact before the result is returned or saved.
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


# ---------------------------------------------------------------------------
# 2. Bug Detection Endpoint (POST /api/v1/repositories/{repository_id}/detect-bugs)
# ---------------------------------------------------------------------------

@router.post(
    "/repositories/{repository_id}/detect-bugs",
    response_model=BugDetectionResponse,
    summary="Detect potential bugs using static analysis and AI reasoning",
)
async def detect_bugs(
    repository_id: UUID,
    payload: BugDetectionRequest,
    request: Request,
    db: Session = Depends(get_db),
) -> BugDetectionResponse:
    """Execute the Week 2 Day 3 Dedicated Bug Detection pipeline."""
    user_id = _request_user_id(request)
    repo = _owned_repository(repository_id, request, db)

    explain_compat_req = ExplainCodeRequest(target=payload.target, options=payload.options)
    resolved = resolve_target_and_build_context(repository_id, repo, explain_compat_req, db)
    payload.target = resolved.target

    service = _get_service(request, "bug_detection_service", "Bug detection")
    method = service.detect_bugs if hasattr(service, "detect_bugs") else service

    run_id = str(uuid4())
    try:
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
                feature_type="detect_bugs",
                status="FAILED",
                target=resolved.target,
                revision=resolved.revision,
                error_message=exc.message,
            )
        raise

    extra_static_raw: list[Any] = []
    parser_warnings: list[str] = []
    if payload.include_static:
        ext_scanner = getattr(request.app.state, "static_bug_scanner", None)
        if ext_scanner is not None:
            scan_fn = getattr(ext_scanner, "scan", ext_scanner)
            if callable(scan_fn):
                try:
                    ext_res = scan_fn(
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
            builtin_items, builtin_warns = BuiltinStaticBugScanner().scan(
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

    merged_findings = merge_and_deduplicate_findings([*grounded_static, *grounded_service])
    ranked_findings = filter_and_rank_findings(
        merged_findings,
        min_severity=payload.min_severity,
        include_static=payload.include_static,
        include_ai=payload.include_ai,
    )

    static_count = sum(
        1 for f in ranked_findings if f.source_type in ("STATIC", "COMBINED")
    )
    ai_count = sum(
        1 for f in ranked_findings if f.source_type in ("AI", "COMBINED")
    )
    merged_missing = list(
        dict.fromkeys([*resolved.missing_context, *parser_warnings, *service_missing_ctx])
    )

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
    )

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
            findings=[f.model_dump(mode="json") for f in ranked_findings],
            findings_count=len(ranked_findings),
        )

    return response


# ---------------------------------------------------------------------------
# 3. Test Generation Endpoint (POST /api/v1/repositories/{repository_id}/generate-tests)
# ---------------------------------------------------------------------------

@router.post(
    "/repositories/{repository_id}/generate-tests",
    response_model=TestGenerationResponse,
    summary="Generate framework-aware test files for a repository file or symbol",
)
async def generate_tests(
    repository_id: UUID,
    payload: TestGenerationRequest,
    request: Request,
    db: Session = Depends(get_db),
) -> TestGenerationResponse:
    """Execute the Week 2 Day 4 Framework-Aware Test Generation pipeline."""
    user_id = _request_user_id(request)
    repo = _owned_repository(repository_id, request, db)

    explain_compat_req = ExplainCodeRequest(target=payload.target, options=payload.options)
    resolved = resolve_target_and_build_context(repository_id, repo, explain_compat_req, db)
    payload.target = resolved.target

    detection, manifest_contents, all_repo_files = detect_repository_test_framework(
        repository_id=repository_id,
        target_path=resolved.target.path,
        requested_framework=payload.framework,
        db=db,
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
                error_message="Test generation failed.",
            )
        raise APIError(
            500,
            ErrorCode.ANALYSIS_FAILED,
            "Test generation failed.",
            retryable=True,
        )

    sanitized_result = validate_and_sanitize_generated_tests(
        test_result,
        repository_id=repository_id,
        resolved=resolved,
        detection=detection,
        default_proposed_path=proposed_test_path,
    )

    response = TestGenerationResponse(
        run_id=run_id,
        repository_id=str(repository_id),
        status=status_val,
        target=resolved.target,
        revision=revision,
        result=sanitized_result,
    )

    if payload.options.persist_run:
        payload_dict = response.model_dump(mode="json")
        payload_dict["test_content"] = sanitized_result.test_content
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
            findings_count=len(sanitized_result.covered_scenarios),
        )

    return response


# ---------------------------------------------------------------------------
# 4. Standalone AI Code Review Endpoint (POST /api/v1/repositories/{repository_id}/review)
# ---------------------------------------------------------------------------

@router.post(
    "/repositories/{repository_id}/review",
    response_model=ReviewReportResponse,
    summary="Run a standalone AI and static code review on a file, commit, PR, or diff",
)
async def review_code(
    repository_id: UUID,
    payload: CodeReviewRequest,
    request: Request,
    db: Session = Depends(get_db),
) -> ReviewReportResponse:
    """Execute the 10-step Week 2 Day 5 Standalone AI Code Review pipeline."""
    user_id = _request_user_id(request)
    repo = _owned_repository(repository_id, request, db)

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

    extra_static_raw: list[Any] = []
    scanner_warnings: list[str] = []
    if payload.include_static:
        ext_reviewer = getattr(request.app.state, "static_reviewer", None)
        if ext_reviewer is not None:
            rev_fn = getattr(ext_reviewer, "review_modified_files", getattr(ext_reviewer, "review", ext_reviewer))
            if callable(rev_fn):
                try:
                    mod_paths = [mf.file_path for mf in resolved.modified_files]
                    ext_res = rev_fn(mod_paths)
                    if inspect.isawaitable(ext_res):
                        ext_res = await ext_res
                    if isinstance(ext_res, dict):
                        extra_static_raw.extend(ext_res.get("findings", []))
                    elif isinstance(ext_res, list):
                        extra_static_raw.extend(ext_res)
                except Exception as exc:
                    logger.warning("external_static_reviewer_error", extra={"error": str(exc)})
                    scanner_warnings.append("External static reviewer encountered an error.")

        builtin_static, builtin_warns = run_static_review_on_changes(
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

    response = ReviewReportResponse(
        run_id=run_id,
        repository_id=str(repository_id),
        status=status_val,
        target=resolved.target,
        report=grounded_report,
    )

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
            findings=[f.model_dump(mode="json") for f in merged_findings],
            findings_count=len(merged_findings),
        )

    return response


# ---------------------------------------------------------------------------
# 5. List Analysis Runs (GET /api/v1/repositories/{repository_id}/analysis-runs)
# ---------------------------------------------------------------------------

@router.get(
    "/repositories/{repository_id}/analysis-runs",
    response_model=PaginatedAnalysisRunResponse,
    summary="List historical analysis runs for an authorized repository",
)
async def list_analysis_runs(
    repository_id: UUID,
    request: Request,
    feature_type: AnalysisFeatureType | None = Query(default=None),
    status: str | None = Query(default=None),
    target_path: str | None = Query(default=None),
    source_revision: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
) -> PaginatedAnalysisRunResponse:
    """Return paginated analysis runs scoped to a repository owned by the caller."""
    _owned_repository(repository_id, request, db)
    offset = (page - 1) * page_size

    # Normalize feature_type aliases ('bugs' -> 'detect_bugs', 'tests' -> 'generate_tests')
    normalized_feature_type = feature_type
    if feature_type == "bugs":
        normalized_feature_type = "detect_bugs"
    elif feature_type == "tests":
        normalized_feature_type = "generate_tests"

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
            res = await res
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
    except Exception:
        pass

    history_store: dict[str, dict[str, Any]] = getattr(
        request.app.state, "_analysis_run_history", {}
    )
    matching = [
        r
        for r in history_store.values()
        if str(r.get("repository_id")) == str(repository_id)
        and (normalized_feature_type is None or r.get("feature_type") == normalized_feature_type)
        and (status is None or r.get("status") == status)
        and (target_path is None or r.get("target_path") == target_path)
        and (source_revision is None or r.get("source_revision") == source_revision)
    ]
    matching.sort(key=lambda r: r.get("created_at", datetime.min), reverse=True)
    total = len(matching)
    sliced = matching[offset : offset + page_size]
    return PaginatedAnalysisRunResponse(
        page=page,
        page_size=page_size,
        total=total,
        items=[_coerce_run_summary(item, repository_id) for item in sliced],
    )


# ---------------------------------------------------------------------------
# 6. Get Analysis Run Detail (GET /api/v1/analysis-runs/{run_id})
# ---------------------------------------------------------------------------

@router.get(
    "/analysis-runs/{run_id}",
    response_model=AnalysisRunDetailResponse,
    summary="Get a specific analysis run and its structured findings",
)
async def get_analysis_run(
    run_id: UUID,
    request: Request,
    db: Session = Depends(get_db),
) -> AnalysisRunDetailResponse:
    """Retrieve a persisted analysis run after verifying repository ownership."""
    _request_user_id(request)

    run_record: Any = None
    run_service = getattr(request.app.state, "analysis_run_service", None)
    if run_service is not None and hasattr(run_service, "get_run"):
        res = run_service.get_run(run_id)
        if inspect.isawaitable(res):
            res = await res
        run_record = res
    else:
        try:
            from app.repositories.analysis_run_repository import AnalysisRunRepository  # type: ignore

            run_record = AnalysisRunRepository(db).get_by_id(run_id)
        except Exception:
            run_record = None

    if run_record is None:
        history_store: dict[str, dict[str, Any]] = getattr(
            request.app.state, "_analysis_run_history", {}
        )
        run_record = history_store.get(str(run_id))

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
        return run_record
    if isinstance(run_record, dict):
        return AnalysisRunDetailResponse.model_validate(run_record)

    status_val = getattr(run_record, "status", "COMPLETED")
    if hasattr(status_val, "value"):
        status_val = status_val.value
    feature_val = getattr(run_record, "feature_type", "explain")
    if hasattr(feature_val, "value"):
        feature_val = feature_val.value

    return AnalysisRunDetailResponse(
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
        findings_count=getattr(run_record, "findings_count", 0) or 0,
        result_payload=getattr(run_record, "result_payload", None),
        findings=[
            f.to_dict() if hasattr(f, "to_dict") else f
            for f in (getattr(run_record, "findings", []) or [])
        ],
        error_message=getattr(run_record, "error_message", None),
        created_at=getattr(run_record, "created_at", datetime.now(timezone.utc)),
        completed_at=getattr(run_record, "completed_at", None),
    )


def _coerce_run_summary(item: Any, repository_id: UUID) -> AnalysisRunSummary:
    if isinstance(item, AnalysisRunSummary):
        return item
    if isinstance(item, dict):
        return AnalysisRunSummary.model_validate(item)

    status_val = getattr(item, "status", "COMPLETED")
    if hasattr(status_val, "value"):
        status_val = status_val.value
    feature_val = getattr(item, "feature_type", "explain")
    if hasattr(feature_val, "value"):
        feature_val = feature_val.value

    return AnalysisRunSummary(
        id=str(getattr(item, "id")),
        repository_id=str(getattr(item, "repository_id", repository_id)),
        user_id=str(getattr(item, "user_id", "")) or None,
        feature_type=feature_val,
        status=status_val,
        target_path=getattr(item, "target_path", None),
        target_symbol=getattr(item, "target_symbol", None),
        start_line=getattr(item, "start_line", None),
        end_line=getattr(item, "end_line", None),
        source_revision=getattr(item, "source_revision", None),
        findings_count=getattr(item, "findings_count", 0) or 0,
        error_message=getattr(item, "error_message", None),
        created_at=getattr(item, "created_at", datetime.now(timezone.utc)),
        completed_at=getattr(item, "completed_at", None),
    )
