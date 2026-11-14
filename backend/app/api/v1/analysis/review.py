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
    _owned_repository_async,
    _request_user_id,
)
from app.core.database import get_db
from app.core.errors import APIError, ErrorCode
from app.core.secret_redaction import redact, redact_obj
from app.core.telemetry import StageExecutionTimer
from app.schemas.analysis import (
    AnalysisTarget,
    CodeReviewRequest,
    ReviewFeedbackRequest,
    ReviewFeedbackResponse,
    ReviewPublicationRequest,
    ReviewPublicationResponse,
    ReviewReport,
    ReviewReportResponse,
    ReviewSettingsResponse,
    UpdateReviewSettingsRequest,
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
    repo = await _owned_repository_async(repository_id, request, db)

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
                rev_fn = getattr(
                    ext_reviewer,
                    "review_modified_files_async",
                    getattr(ext_reviewer, "review_modified_files", getattr(ext_reviewer, "review", ext_reviewer)),
                )
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


# ---------------------------------------------------------------------------
# Code Review Publication, Feedback & Settings Endpoints (F14)
# ---------------------------------------------------------------------------

@router.post(
    "/repositories/{repository_id}/review/publish",
    response_model=ReviewPublicationResponse,
    summary="Publish review findings as inline GitHub PR comments",
)
async def publish_review_to_github(
    repository_id: UUID,
    payload: ReviewPublicationRequest,
    request: Request,
    db: Session = Depends(get_db),
) -> ReviewPublicationResponse:
    """Manually publish qualified findings from an analysis run as inline PR comments."""
    from app.models.analysis_run import AnalysisRun
    from app.services.review_publication_service import ReviewPublicationService

    user_id = _request_user_id(request)
    repo = await _owned_repository_async(repository_id, request, db)

    findings_data = []
    commit_sha = payload.commit_sha
    run_record = None

    if payload.run_id:
        try:
            r_uuid = UUID(payload.run_id)
            run_record = (
                db.query(AnalysisRun)
                .filter(AnalysisRun.id == r_uuid, AnalysisRun.repository_id == repository_id)
                .first()
            )
        except ValueError:
            pass

    if not run_record:
        run_record = (
            db.query(AnalysisRun)
            .filter(
                AnalysisRun.repository_id == repository_id,
                AnalysisRun.feature_type == "review",
                AnalysisRun.status == "COMPLETED",
            )
            .order_by(AnalysisRun.created_at.desc())
            .first()
        )

    if run_record:
        commit_sha = commit_sha or run_record.source_revision
        if run_record.findings:
            findings_data = [
                {
                    "id": str(f.id),
                    "category": f.category,
                    "severity": f.severity,
                    "confidence": f.confidence,
                    "title": f.title,
                    "description": f.description,
                    "evidence": f.evidence,
                    "suggested_fix": f.suggested_fix,
                    "source_reference": f.source_reference,
                }
                for f in run_record.findings
            ]
        elif run_record.result_payload and "report" in run_record.result_payload:
            findings_data = run_record.result_payload["report"].get("findings", [])

    github_service = getattr(request.app.state, "github_service", None)
    if not github_service:
        from app.core.config import get_settings
        from app.services.github_service import GitHubService
        github_service = GitHubService(settings=get_settings(), db=db)

    gh_installation_id = None
    if getattr(repo, "installation_id", None):
        from app.models.github_installation import GitHubInstallation
        inst = db.get(GitHubInstallation, repo.installation_id)
        if inst and inst.installation_id:
            try:
                gh_installation_id = int(inst.installation_id)
            except (ValueError, TypeError):
                gh_installation_id = inst.installation_id

    pub_service = ReviewPublicationService()
    res = await pub_service.publish_pull_request_review(
        owner=repo.owner,
        repo_name=repo.name,
        pr_number=payload.pr_number,
        commit_sha=commit_sha or "HEAD",
        findings=findings_data,
        github_service=github_service,
        repository=repo,
        installation_id=gh_installation_id,
        force_publish=payload.force_publish,
        max_comments=payload.max_comments,
        min_confidence=payload.min_confidence,
        changed_lines_only=payload.changed_lines_only,
    )

    if run_record and run_record.result_payload:
        payload_dict = dict(run_record.result_payload)
        payload_dict["review_publication"] = res.to_dict()
        run_record.result_payload = payload_dict
        db.commit()

    return ReviewPublicationResponse(
        status=res.status,
        review_id=res.review_id,
        pr_number=res.pr_number,
        commit_sha=res.commit_sha,
        published_comments_count=res.published_comments_count,
        skipped_reason=res.skipped_reason,
        error_message=res.error_message,
        published_at=res.published_at,
    )


@router.post(
    "/analysis-runs/{run_id}/findings/{finding_id}/feedback",
    response_model=ReviewFeedbackResponse,
    summary="Submit developer feedback on an AI code review finding",
)
async def submit_finding_feedback(
    run_id: str,
    finding_id: str,
    payload: ReviewFeedbackRequest,
    request: Request,
    db: Session = Depends(get_db),
) -> ReviewFeedbackResponse:
    """Submit useful/not_useful/false_positive feedback on a code review finding."""
    from app.models.analysis_finding import AnalysisFinding
    from app.services.review_feedback_service import ReviewFeedbackService

    user_id = _request_user_id(request)
    try:
        f_uuid = UUID(finding_id)
        r_uuid = UUID(run_id)
    except ValueError:
        raise APIError(400, ErrorCode.INVALID_PARAMETER, f"Invalid finding_id or run_id")

    finding = (
        db.query(AnalysisFinding)
        .filter(
            AnalysisFinding.id == f_uuid,
            AnalysisFinding.analysis_run_id == r_uuid,
        )
        .first()
    )
    if not finding:
        raise APIError(404, ErrorCode.NOT_FOUND, "Finding not found")

    await _owned_repository_async(finding.repository_id, request, db)

    feedback_svc = ReviewFeedbackService()
    feedback_entry = feedback_svc.record_feedback(
        db,
        finding_id=f_uuid,
        feedback_type=payload.feedback_type,
        user_id=user_id,
        comment=payload.comment,
    )

    stats = feedback_svc.compute_repository_feedback_stats(db, finding.repository_id)

    return ReviewFeedbackResponse(
        finding_id=finding_id,
        feedback_type=feedback_entry["feedback_type"],
        user_id=feedback_entry["user_id"],
        comment=feedback_entry["comment"],
        updated_at=feedback_entry["updated_at"],
        repository_stats=stats.to_dict(),
    )


@router.get(
    "/repositories/{repository_id}/review/settings",
    response_model=ReviewSettingsResponse,
    summary="Get repository code review settings",
)
async def get_repository_review_settings(
    repository_id: UUID,
    request: Request,
    db: Session = Depends(get_db),
) -> ReviewSettingsResponse:
    """Retrieve repository code review and PR publication settings."""
    from app.services.review_settings_service import get_repo_review_settings

    repo = await _owned_repository_async(repository_id, request, db)
    settings = get_repo_review_settings(repository_id)
    return ReviewSettingsResponse(
        repository_id=str(repository_id),
        pr_review_enabled=getattr(repo, "pr_review_enabled", False),
        pr_review_drafts=getattr(repo, "pr_review_drafts", False),
        min_confidence=settings.get("min_confidence", "medium"),
        max_comments=settings.get("max_comments", 15),
        changed_lines_only=settings.get("changed_lines_only", True),
    )


@router.patch(
    "/repositories/{repository_id}/review/settings",
    response_model=ReviewSettingsResponse,
    summary="Update repository code review settings",
)
async def update_repository_review_settings(
    repository_id: UUID,
    payload: UpdateReviewSettingsRequest,
    request: Request,
    db: Session = Depends(get_db),
) -> ReviewSettingsResponse:
    """Update repository code review and PR publication settings."""
    from app.services.review_settings_service import set_repo_review_settings

    repo = await _owned_repository_async(repository_id, request, db)
    if payload.pr_review_enabled is not None:
        repo.pr_review_enabled = payload.pr_review_enabled
    if payload.pr_review_drafts is not None:
        repo.pr_review_drafts = payload.pr_review_drafts
    db.commit()
    db.refresh(repo)

    updated_settings = set_repo_review_settings(
        repository_id,
        {
            "min_confidence": payload.min_confidence,
            "max_comments": payload.max_comments,
            "changed_lines_only": payload.changed_lines_only,
        },
    )

    return ReviewSettingsResponse(
        repository_id=str(repository_id),
        pr_review_enabled=getattr(repo, "pr_review_enabled", False),
        pr_review_drafts=getattr(repo, "pr_review_drafts", False),
        min_confidence=updated_settings["min_confidence"],
        max_comments=updated_settings["max_comments"],
        changed_lines_only=updated_settings["changed_lines_only"],
    )

