"""GitHub source integration API endpoints.

These endpoints expose Parth's GitHub source integration service to the
Repository Explorer UI and the four analysis features. All endpoints
require authentication and verify repository ownership.

Endpoints
---------
GET  /api/v1/repositories/{id}/source/tree        — File tree
GET  /api/v1/repositories/{id}/source/file         — File content
GET  /api/v1/repositories/{id}/source/commits      — Commit list
GET  /api/v1/repositories/{id}/source/commits/{sha} — Commit detail
GET  /api/v1/repositories/{id}/source/pulls        — Pull-request list
GET  /api/v1/repositories/{id}/source/pulls/{pr}/diff — PR diff
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.errors import APIError, ErrorCode
from app.integrations.github.schemas import (
    AgentBranchRequest,
    AgentBranchResponse,
    CommitDetail,
    CommitListResponse,
    FileContentResponse,
    FileTreeResponse,
    PullRequestDiffResponse,
    PullRequestInfo,
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
    return await service.get_file_content(
        repository_id,
        _request_user_id(request),
        file_request,
    )


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
    service = GitHubSourceService(db)
    return await service.list_commits(
        repository_id,
        _request_user_id(request),
        ref=ref,
        path=path,
        per_page=per_page,
        page=page,
    )


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
    service = GitHubSourceService(db)
    return await service.get_commit_detail(
        repository_id,
        _request_user_id(request),
        sha,
    )


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
    return await service.list_pull_requests(
        repository_id,
        _request_user_id(request),
        state=state,
        per_page=per_page,
        page=page,
    )


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
    service = GitHubSourceService(db)
    return await service.get_pull_request_diff(
        repository_id,
        _request_user_id(request),
        pr_number,
    )


# ---------------------------------------------------------------------------
# Agent branch creation (Day 3 execution transition)
# ---------------------------------------------------------------------------

@router.post(
    "/{repository_id}/source/agent-branch",
    response_model=AgentBranchResponse,
    status_code=status.HTTP_200_OK,
    summary="Create agent branch for task execution",
    description="Triggered when task transitions to EXECUTING. Creates agent/task-{task_id} from main.",
)
async def create_agent_branch_endpoint(
    repository_id: UUID,
    request: Request,
    body: AgentBranchRequest | None = None,
    task_id: str | None = Query(default=None, min_length=1, description="Task ID transitioning to EXECUTING"),
    base_branch: str | None = Query(default=None, description="Optional base branch (defaults to repo default)"),
    db: Session = Depends(get_db),
) -> AgentBranchResponse:
    from app.services.git_branch import GitBranchService

    effective_task_id = (body.task_id if body else None) or task_id
    if not effective_task_id:
        raise APIError(422, ErrorCode.INVALID_REQUEST, "task_id is required in request body or query parameter.")
    effective_base_branch = (body.base_branch if body and body.base_branch is not None else None) or base_branch

    service = GitBranchService(db)
    info = await service.on_task_executing(
        repository_id=repository_id,
        task_id=effective_task_id,
        user_id=_request_user_id(request),
        base_branch=effective_base_branch,
    )
    return AgentBranchResponse(
        branch_name=info.branch_name,
        base_branch=info.base_branch,
        base_sha=info.base_sha,
        status=info.status,
    )

