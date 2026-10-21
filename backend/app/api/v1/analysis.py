"""Developer Intelligence Suite API endpoints (Week 2).

Owner: Yug — W2, Day 1 (API Foundation & Orchestration)

Endpoints registered:
- POST /api/v1/repositories/{repository_id}/explain
- POST /api/v1/repositories/{repository_id}/detect-bugs
- POST /api/v1/repositories/{repository_id}/generate-tests
- POST /api/v1/repositories/{repository_id}/review
- GET  /api/v1/repositories/{repository_id}/analysis-runs
- GET  /api/v1/analysis-runs/{run_id}

Architectural Rules (Docs/week2.md & Docs/team_rules.md):
1. Authenticate caller via JWT (`request.state.user_id`) and enforce repository
   ownership (`RepositoryRepository(db).get_for_user(repository_id, user_id)`)
   before accessing any file metadata, database records, or AI services.
2. Validate all repository-relative file paths using `require_safe_repo_path()`
   to reject path traversal (`../`, absolute paths, backslashes, control chars)
   with HTTP 400 `INVALID_REQUEST`.
3. Verify indexed file bounds (existence, line count, max 1 MB size) when
   repository file records are present in the database session.
4. Consume downstream AI and persistence services via Protocol boundaries on
   `request.app.state` (`explanation_service`, `bug_detection_service`,
   `test_generation_service`, `code_review_service`, `analysis_run_service`).
5. Never misrepresent a provider failure or schema validation error as a
   successful empty analysis result.
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

logger = logging.getLogger(__name__)

router = APIRouter(tags=["analysis"])

MAX_ANALYZABLE_FILE_BYTES = 1_048_576  # 1 MB ceiling matching FileWalker


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
    """Authenticate, verify repository ownership, validate target, and return a grounded explanation."""
    user_id = _request_user_id(request)
    repo = _owned_repository(repository_id, request, db)
    file_record = _validate_and_normalize_code_target(repository_id, payload.target, db)

    service = _get_service(request, "explanation_service", "Code explanation")
    method = getattr(service, "explain", service) if not callable(service) else service
    if hasattr(service, "explain"):
        method = service.explain

    raw_result = await _invoke_service_method(
        method,
        repository_id,
        payload,
        user_id=user_id,
        db=db,
        file_record=file_record,
    )

    revision = payload.target.revision or getattr(repo, "default_branch", "main")
    try:
        if isinstance(raw_result, CodeExplanationResponse):
            response = raw_result
        elif isinstance(raw_result, CodeExplanation):
            response = CodeExplanationResponse(
                run_id=str(uuid4()),
                repository_id=str(repository_id),
                status="COMPLETED",
                target=payload.target,
                revision=revision,
                explanation=raw_result,
            )
        elif isinstance(raw_result, dict) and "explanation" in raw_result:
            response = CodeExplanationResponse.model_validate(
                {
                    "run_id": str(raw_result.get("run_id") or uuid4()),
                    "repository_id": str(raw_result.get("repository_id") or repository_id),
                    "status": raw_result.get("status", "COMPLETED"),
                    "target": raw_result.get("target") or payload.target,
                    "revision": raw_result.get("revision") or revision,
                    "explanation": raw_result["explanation"],
                }
            )
        else:
            explanation = CodeExplanation.model_validate(raw_result)
            response = CodeExplanationResponse(
                run_id=str(uuid4()),
                repository_id=str(repository_id),
                status="COMPLETED",
                target=payload.target,
                revision=revision,
                explanation=explanation,
            )
    except ValidationError as exc:
        logger.error("explain_output_schema_invalid", extra={"error": str(exc)})
        raise APIError(
            500,
            ErrorCode.ANALYSIS_FAILED,
            "Code explanation service returned an invalid output schema.",
            retryable=False,
        ) from exc

    if response.status == "FAILED":
        raise APIError(
            500,
            ErrorCode.ANALYSIS_FAILED,
            "Code explanation failed during execution.",
            retryable=True,
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
    """Run static and AI defect analysis on an authorized repository target."""
    user_id = _request_user_id(request)
    repo = _owned_repository(repository_id, request, db)
    file_record = _validate_and_normalize_code_target(repository_id, payload.target, db)

    service = _get_service(request, "bug_detection_service", "Bug detection")
    method = service.detect_bugs if hasattr(service, "detect_bugs") else service

    raw_result = await _invoke_service_method(
        method,
        repository_id,
        payload,
        user_id=user_id,
        db=db,
        file_record=file_record,
    )

    revision = payload.target.revision or getattr(repo, "default_branch", "main")
    try:
        if isinstance(raw_result, BugDetectionResponse):
            response = raw_result
        elif isinstance(raw_result, dict):
            findings_raw = raw_result.get("findings", [])
            response = BugDetectionResponse.model_validate(
                {
                    "run_id": str(raw_result.get("run_id") or uuid4()),
                    "repository_id": str(raw_result.get("repository_id") or repository_id),
                    "status": raw_result.get("status", "COMPLETED"),
                    "target": raw_result.get("target") or payload.target,
                    "revision": raw_result.get("revision") or revision,
                    "findings": findings_raw,
                    "total_findings": raw_result.get("total_findings", len(findings_raw)),
                    "static_findings_count": raw_result.get(
                        "static_findings_count",
                        sum(
                            1
                            for f in findings_raw
                            if (
                                f.get("source_type")
                                if isinstance(f, dict)
                                else getattr(f, "source_type", None)
                            )
                            == "STATIC"
                        ),
                    ),
                    "ai_findings_count": raw_result.get(
                        "ai_findings_count",
                        sum(
                            1
                            for f in findings_raw
                            if (
                                f.get("source_type")
                                if isinstance(f, dict)
                                else getattr(f, "source_type", None)
                            )
                             in ("AI", "COMBINED")
                        ),
                    ),
                    "missing_context": raw_result.get("missing_context", []),
                }
            )
        elif isinstance(raw_result, list):
            response = BugDetectionResponse.model_validate(
                {
                    "run_id": str(uuid4()),
                    "repository_id": str(repository_id),
                    "status": "COMPLETED",
                    "target": payload.target,
                    "revision": revision,
                    "findings": raw_result,
                    "total_findings": len(raw_result),
                }
            )
        else:
            response = BugDetectionResponse.model_validate(raw_result)
    except ValidationError as exc:
        logger.error("detect_bugs_output_schema_invalid", extra={"error": str(exc)})
        raise APIError(
            500,
            ErrorCode.ANALYSIS_FAILED,
            "Bug detection service returned an invalid output schema.",
            retryable=False,
        ) from exc

    if response.status == "FAILED":
        raise APIError(
            500,
            ErrorCode.ANALYSIS_FAILED,
            "Bug detection scan failed.",
            retryable=True,
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
    """Generate a previewable test file following the repository's test conventions."""
    user_id = _request_user_id(request)
    repo = _owned_repository(repository_id, request, db)
    file_record = _validate_and_normalize_code_target(repository_id, payload.target, db)

    service = _get_service(request, "test_generation_service", "Test generation")
    method = service.generate_tests if hasattr(service, "generate_tests") else service

    raw_result = await _invoke_service_method(
        method,
        repository_id,
        payload,
        user_id=user_id,
        db=db,
        file_record=file_record,
    )

    revision = payload.target.revision or getattr(repo, "default_branch", "main")
    try:
        if isinstance(raw_result, TestGenerationResponse):
            response = raw_result
        elif isinstance(raw_result, TestGenerationResult):
            response = TestGenerationResponse(
                run_id=str(uuid4()),
                repository_id=str(repository_id),
                status="COMPLETED",
                target=payload.target,
                revision=revision,
                result=raw_result,
            )
        elif isinstance(raw_result, dict) and "result" in raw_result:
            response = TestGenerationResponse.model_validate(
                {
                    "run_id": str(raw_result.get("run_id") or uuid4()),
                    "repository_id": str(raw_result.get("repository_id") or repository_id),
                    "status": raw_result.get("status", "COMPLETED"),
                    "target": raw_result.get("target") or payload.target,
                    "revision": raw_result.get("revision") or revision,
                    "result": raw_result["result"],
                }
            )
        else:
            test_result = TestGenerationResult.model_validate(raw_result)
            response = TestGenerationResponse(
                run_id=str(uuid4()),
                repository_id=str(repository_id),
                status="COMPLETED",
                target=payload.target,
                revision=revision,
                result=test_result,
            )
    except ValidationError as exc:
        logger.error("generate_tests_output_schema_invalid", extra={"error": str(exc)})
        raise APIError(
            500,
            ErrorCode.ANALYSIS_FAILED,
            "Test generation service returned an invalid output schema.",
            retryable=False,
        ) from exc

    if response.status == "FAILED":
        raise APIError(
            500,
            ErrorCode.ANALYSIS_FAILED,
            "Test generation failed.",
            retryable=True,
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
    """Review a file, commit SHA, PR diff, or unified diff without starting an autonomous task."""
    user_id = _request_user_id(request)
    _owned_repository(repository_id, request, db)

    if payload.target.path is not None:
        payload.target.path = require_safe_repo_path(payload.target.path)

    service = _get_service(request, "code_review_service", "AI code review")
    method = service.review if hasattr(service, "review") else service

    raw_result = await _invoke_service_method(
        method,
        repository_id,
        payload,
        user_id=user_id,
        db=db,
    )

    try:
        if isinstance(raw_result, ReviewReportResponse):
            response = raw_result
        elif isinstance(raw_result, ReviewReport):
            response = ReviewReportResponse(
                run_id=str(uuid4()),
                repository_id=str(repository_id),
                status="COMPLETED",
                target=payload.target,
                report=raw_result,
            )
        elif isinstance(raw_result, dict) and "report" in raw_result:
            response = ReviewReportResponse.model_validate(
                {
                    "run_id": str(raw_result.get("run_id") or uuid4()),
                    "repository_id": str(raw_result.get("repository_id") or repository_id),
                    "status": raw_result.get("status", "COMPLETED"),
                    "target": raw_result.get("target") or payload.target,
                    "report": raw_result["report"],
                }
            )
        else:
            report = ReviewReport.model_validate(raw_result)
            response = ReviewReportResponse(
                run_id=str(uuid4()),
                repository_id=str(repository_id),
                status="COMPLETED",
                target=payload.target,
                report=report,
            )
    except ValidationError as exc:
        logger.error("review_output_schema_invalid", extra={"error": str(exc)})
        raise APIError(
            500,
            ErrorCode.ANALYSIS_FAILED,
            "AI code review service returned an invalid output schema.",
            retryable=False,
        ) from exc

    if response.status == "FAILED":
        raise APIError(
            500,
            ErrorCode.ANALYSIS_FAILED,
            "Code review execution failed.",
            retryable=True,
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
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
) -> PaginatedAnalysisRunResponse:
    """Return paginated analysis runs scoped to a repository owned by the caller."""
    _owned_repository(repository_id, request, db)
    offset = (page - 1) * page_size

    run_service = getattr(request.app.state, "analysis_run_service", None)
    if run_service is not None and hasattr(run_service, "list_runs"):
        res = run_service.list_runs(
            repository_id,
            feature_type=feature_type,
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

    # Fallback: check if Om's AnalysisRunRepository is available in app.repositories
    try:
        from app.repositories.analysis_run_repository import AnalysisRunRepository  # type: ignore

        repo_layer = AnalysisRunRepository(db)
        items, total = repo_layer.list_by_repository(
            repository_id,
            feature_type=feature_type,
            status=status,
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
        return PaginatedAnalysisRunResponse(
            page=page,
            page_size=page_size,
            total=0,
            items=[],
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

    # Enforce strict repository authorization before returning the run payload
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
        findings=getattr(run_record, "findings", []) or [],
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
