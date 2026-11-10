"""GitHub source integration API endpoints.

These endpoints expose Parth's GitHub source integration service to the
Repository Explorer UI and canonical task endpoints. All endpoints
require authentication and verify repository ownership.

Endpoints
---------
GET  /api/v1/repositories/{id}/source/tree                         — File tree
GET  /api/v1/repositories/{id}/source/file                         — File content
GET  /api/v1/repositories/{id}/source/commits                      — Commit list
GET  /api/v1/repositories/{id}/source/commits/{sha}                — Commit detail
GET  /api/v1/repositories/{id}/source/pulls                        — Pull-request list
GET  /api/v1/repositories/{id}/source/pulls/{pr}/diff              — PR diff
GET  /api/v1/repositories/{id}/source/issues                       — Issue list (remote GitHub issues)
GET  /api/v1/repositories/{id}/source/issues/{issue_number}        — Issue detail (remote GitHub issue)
GET  /api/v1/repositories/{id}/source/pr-metadata/{task_id}        — Retrieve prepared PR metadata
GET  /api/v1/repositories/{id}/source/diff-ranges/task/{task_id}   — Get task workspace diff ranges
ALL  /api/v1/repositories/{id}/source/task/*                       — Deprecated execution surface (410 Gone)
ALL  /api/v1/repositories/{id}/source/task-workspace/*             — Deprecated workspace execution surface (410 Gone)
"""

from __future__ import annotations

import re
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.errors import APIError, ErrorCode
from app.core.secret_redaction import redact_obj
from app.integrations.github.schemas import (
    AgentBranchRequest,
    AgentBranchResponse,
    CommitDetail,
    CommitListResponse,
    FileContentResponse,
    FileTreeResponse,
    PRMetadata,
    PullRequestDiffResponse,
    PullRequestInfo,
    RemoteIssueInfo,
    TaskDiffRanges,
)
from app.integrations.github.service import GitHubSourceService

router = APIRouter(prefix="/repositories", tags=["github-source"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _request_user_id(request: Request) -> UUID:
    """Extract the authenticated user ID from request state."""
    try:
        return UUID(request.state.user_id)
    except (AttributeError, ValueError) as exc:
        raise APIError(401, ErrorCode.UNAUTHORIZED, "Invalid authenticated user.") from exc


# ---------------------------------------------------------------------------
# File tree
# ---------------------------------------------------------------------------

@router.get(
    "/{repository_id}/source/tree",
    response_model=FileTreeResponse,
    summary="Get repository file tree",
    description="Retrieve the full file tree for an authorized repository.",
)
async def get_file_tree(
    repository_id: UUID,
    request: Request,
    ref: str | None = Query(default=None, description="Git ref (branch, tag, SHA)"),
    db: Session = Depends(get_db),
) -> FileTreeResponse:
    service = GitHubSourceService(db)
    return await service.get_file_tree(
        repository_id,
        _request_user_id(request),
        ref=ref,
    )


# ---------------------------------------------------------------------------
# File content
# ---------------------------------------------------------------------------

@router.get(
    "/{repository_id}/source/file",
    response_model=FileContentResponse,
    summary="Get file content",
    description="Retrieve the content of a specific file from an authorized repository.",
)
async def get_file_content(
    repository_id: UUID,
    request: Request,
    path: str = Query(..., min_length=1, description="Relative file path"),
    ref: str | None = Query(default=None, description="Git ref (branch, tag, SHA)"),
    start_line: int | None = Query(default=None, ge=1, description="Start line (inclusive)"),
    end_line: int | None = Query(default=None, ge=1, description="End line (inclusive)"),
    db: Session = Depends(get_db),
) -> FileContentResponse:
    from app.integrations.github.schemas import FileContentRequest

    file_request = FileContentRequest(
        path=path,
        ref=ref,
        start_line=start_line,
        end_line=end_line,
    )
    service = GitHubSourceService(db)
    resp = await service.get_file_content(
        repository_id,
        _request_user_id(request),
        file_request,
    )
    return FileContentResponse.model_validate(redact_obj(resp.model_dump(mode="json")))


# ---------------------------------------------------------------------------
# Commits
# ---------------------------------------------------------------------------

@router.get(
    "/{repository_id}/source/commits",
    response_model=CommitListResponse,
    summary="List repository commits",
    description="List commits for an authorized repository with optional filters.",
)
async def list_commits(
    repository_id: UUID,
    request: Request,
    ref: str | None = Query(default=None, description="Branch, tag, or SHA"),
    path: str | None = Query(default=None, description="Filter by file path"),
    per_page: int = Query(default=30, ge=1, le=100),
    page: int = Query(default=1, ge=1),
    db: Session = Depends(get_db),
) -> CommitListResponse:
    from app.core.input_security import require_safe_repo_path

    safe_path = require_safe_repo_path(path) if path is not None else None
    service = GitHubSourceService(db)
    resp = await service.list_commits(
        repository_id,
        _request_user_id(request),
        ref=ref,
        path=safe_path,
        per_page=per_page,
        page=page,
    )
    return CommitListResponse.model_validate(redact_obj(resp.model_dump(mode="json")))


@router.get(
    "/{repository_id}/source/commits/{sha}",
    response_model=CommitDetail,
    summary="Get commit detail",
    description="Get detailed commit information including file changes.",
)
async def get_commit_detail(
    repository_id: UUID,
    sha: str,
    request: Request,
    db: Session = Depends(get_db),
) -> CommitDetail:
    clean_sha = sha.strip()
    if not re.match(r"^[0-9a-fA-F]{7,64}$", clean_sha):
        raise APIError(
            400,
            ErrorCode.INVALID_REQUEST,
            "Invalid commit SHA format; expected a 7-to-64 character hexadecimal SHA.",
        )
    service = GitHubSourceService(db)
    resp = await service.get_commit_detail(
        repository_id,
        _request_user_id(request),
        clean_sha,
    )
    return CommitDetail.model_validate(redact_obj(resp.model_dump(mode="json")))


# ---------------------------------------------------------------------------
# Pull requests
# ---------------------------------------------------------------------------

@router.get(
    "/{repository_id}/source/pulls",
    response_model=list[PullRequestInfo],
    summary="List pull requests",
    description="List pull requests for an authorized repository.",
)
async def list_pull_requests(
    repository_id: UUID,
    request: Request,
    state: str = Query(default="open", pattern="^(open|closed|all)$"),
    per_page: int = Query(default=30, ge=1, le=100),
    page: int = Query(default=1, ge=1),
    db: Session = Depends(get_db),
) -> list[PullRequestInfo]:
    service = GitHubSourceService(db)
    items = await service.list_pull_requests(
        repository_id,
        _request_user_id(request),
        state=state,
        per_page=per_page,
        page=page,
    )
    return [PullRequestInfo.model_validate(redact_obj(p.model_dump(mode="json"))) for p in items]


@router.get(
    "/{repository_id}/source/pulls/{pr_number}/diff",
    response_model=PullRequestDiffResponse,
    summary="Get pull-request diff",
    description="Retrieve the full diff for a pull request.",
)
async def get_pull_request_diff(
    repository_id: UUID,
    pr_number: int,
    request: Request,
    db: Session = Depends(get_db),
) -> PullRequestDiffResponse:
    if pr_number < 1:
        raise APIError(
            400,
            ErrorCode.INVALID_REQUEST,
            "Pull request number must be a positive integer.",
        )
    service = GitHubSourceService(db)
    resp = await service.get_pull_request_diff(
        repository_id,
        _request_user_id(request),
        pr_number,
    )
    return PullRequestDiffResponse.model_validate(redact_obj(resp.model_dump(mode="json")))


# ---------------------------------------------------------------------------
# Agent branch creation (Compatibility endpoint for task execution)
# ---------------------------------------------------------------------------

@router.post(
    "/{repository_id}/source/agent-branch",
    response_model=AgentBranchResponse,
    summary="Create agent branch for task execution",
    description="Creates or validates an isolated agent/task-{id} branch. Canonical endpoint is /api/v1/tasks/{id}/branch.",
    deprecated=True,
)
async def create_agent_branch_endpoint(
    repository_id: UUID,
    payload: AgentBranchRequest,
    request: Request,
    db: Session = Depends(get_db),
) -> AgentBranchResponse:
    from app.services.git_branch import GitBranchService

    service = GitBranchService(db)
    result = await service.on_task_executing(
        repository_id=repository_id,
        task_id=payload.task_id,
        base_branch=payload.base_branch,
        user_id=_request_user_id(request),
    )
    return AgentBranchResponse(
        branch_name=result.branch_name,
        base_branch=result.base_branch,
        base_sha=result.base_sha,
        status=result.status,
    )


# ---------------------------------------------------------------------------
# PR Metadata (Consumed by frontend/src/services/tasks.ts)
# ---------------------------------------------------------------------------

@router.get(
    "/{repository_id}/source/pr-metadata/{task_id}",
    response_model=PRMetadata,
    summary="Retrieve prepared PR metadata",
    description="Gets stored PR metadata for a specific agent task scoped to the authorized repository.",
)
def get_pr_metadata_endpoint(
    repository_id: UUID,
    task_id: UUID,
    request: Request,
    db: Session = Depends(get_db),
) -> PRMetadata:
    from app.services.git_branch import GitBranchService

    service = GitBranchService(db)
    meta = service.get_pr_metadata(
        task_id=task_id,
        user_id=_request_user_id(request),
        repository_id=repository_id,
    )
    return PRMetadata.model_validate(redact_obj(meta.model_dump(mode="json")))


# ---------------------------------------------------------------------------
# Diff Line Ranges (Consumed by frontend/src/services/tasks.ts)
# ---------------------------------------------------------------------------

@router.get(
    "/{repository_id}/source/diff-ranges/task/{task_id}",
    response_model=TaskDiffRanges,
    summary="Get task workspace diff line ranges",
    description="Inspects active task branch diff to supply affected line ranges for BlastRadiusEngine and Yug's affected-files API.",
)
async def get_task_diff_ranges_endpoint(
    repository_id: UUID,
    task_id: UUID,
    request: Request,
    base_branch: str | None = Query(default=None, description="Optional base branch"),
    workspace_path: str | None = Query(default=None, description="Optional workspace path"),
    db: Session = Depends(get_db),
) -> TaskDiffRanges:
    from app.services.git_branch import GitBranchService

    service = GitBranchService(db)
    summary = await service.get_task_diff_ranges(
        task_id=task_id,
        workspace_path=workspace_path,
        base_branch=base_branch,
        repository_id=repository_id,
        user_id=_request_user_id(request),
    )
    return TaskDiffRanges.model_validate(redact_obj(summary.model_dump(mode="json")))


# ---------------------------------------------------------------------------
# Remote Issues Browsing (Issue #196)
# ---------------------------------------------------------------------------

@router.get(
    "/{repository_id}/source/issues",
    response_model=list[RemoteIssueInfo],
    summary="List remote repository issues",
    description="List live remote issues for an authorized repository from GitHub.",
)
async def list_remote_issues(
    repository_id: UUID,
    request: Request,
    state: str = Query(default="open", pattern="^(open|closed|all)$"),
    per_page: int = Query(default=30, ge=1, le=100),
    page: int = Query(default=1, ge=1),
    db: Session = Depends(get_db),
) -> list[RemoteIssueInfo]:
    service = GitHubSourceService(db)
    items = await service.list_issues(
        repository_id,
        _request_user_id(request),
        state=state,
        per_page=per_page,
        page=page,
    )
    return [RemoteIssueInfo.model_validate(redact_obj(item.model_dump(mode="json"))) for item in items]


@router.get(
    "/{repository_id}/source/issues/{issue_number}",
    response_model=RemoteIssueInfo,
    summary="Get remote issue detail",
    description="Retrieve details and body for a specific remote GitHub issue.",
)
async def get_remote_issue(
    repository_id: UUID,
    issue_number: int,
    request: Request,
    db: Session = Depends(get_db),
) -> RemoteIssueInfo:
    if issue_number < 1:
        raise APIError(
            400,
            ErrorCode.INVALID_REQUEST,
            "Issue number must be a positive integer.",
        )
    service = GitHubSourceService(db)
    item = await service.get_issue_detail(
        repository_id,
        _request_user_id(request),
        issue_number,
    )
    return RemoteIssueInfo.model_validate(redact_obj(item.model_dump(mode="json")))


# ---------------------------------------------------------------------------
# Deprecated Duplicate Task Execution Surfaces (Issue #196)
# ---------------------------------------------------------------------------

@router.api_route(
    "/{repository_id}/source/task/{action:path}",
    methods=["GET", "POST", "PUT", "DELETE", "PATCH"],
    deprecated=True,
    summary="Deprecated duplicate task execution surface",
    description="Deprecated duplicate task endpoint. Use canonical `/api/v1/tasks/{id}/*` endpoints instead.",
    include_in_schema=True,
)
@router.api_route(
    "/{repository_id}/source/task-workspace/{action:path}",
    methods=["GET", "POST", "PUT", "DELETE", "PATCH"],
    deprecated=True,
    summary="Deprecated duplicate task workspace execution surface",
    description="Deprecated duplicate task workspace endpoint. Use canonical `/api/v1/tasks/{id}/*` endpoints instead.",
    include_in_schema=True,
)
async def deprecated_task_source_endpoint(
    repository_id: UUID,
    action: str,
    request: Request,
) -> JSONResponse:
    """Deprecation handler informing clients to use canonical /api/v1/tasks/* execution endpoints."""
    canonical_target = "/api/v1/tasks"
    path = request.url.path
    return JSONResponse(
        status_code=410,
        content={
            "error": "DEPRECATED_ENDPOINT",
            "message": (
                f"The endpoint {path} has been deprecated and consolidated. "
                f"Please use the canonical /api/v1/tasks execution API."
            ),
            "canonical_endpoint": canonical_target,
        },
        headers={
            "X-Canonical-Endpoint": canonical_target,
            "Deprecation": "true",
        },
    )
