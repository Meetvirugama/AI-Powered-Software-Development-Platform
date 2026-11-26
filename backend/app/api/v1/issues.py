"""Week 3 Day 1 (F31) — GitHub Issue Integration API Endpoints.

Owners:
- Yug (Backend orchestration & API routes: import issue, list issues, create issue from finding)
- Parth (GitHub issue integration via GitHubSourceService / GitHubService)
- Sukun (Repository & finding ownership enforcement, prompt-injection fencing, secret redaction)

Endpoints:
- POST /api/v1/repositories/{repository_id}/issues/import
- GET  /api/v1/repositories/{repository_id}/issues
- POST /api/v1/repositories/{repository_id}/issues
"""

from __future__ import annotations

import logging
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ai.services.issue_task_adapter import IssueToTaskAdapter, format_issue_from_finding
from app.api.v1.dependencies import ensure_min_role
from app.core.database import get_db, run_db
from app.models.user import UserRole
from app.core.errors import APIError, ErrorCode
from app.core.secret_redaction import redact, redact_obj
from app.integrations.github.base import GitHubIssueData
from app.integrations.github.exceptions import (
    GitHubAuthError,
    GitHubInstallationRemovedError,
    GitHubNotFoundError,
    GitHubPermissionDeniedError,
    GitHubRateLimitError,
)
from app.integrations.github.source_service import GitHubSourceService
from app.models.analysis_finding import AnalysisFinding
from app.models.github_installation import GitHubInstallation
from app.models.repository import Repository
from app.models.repository_file import RepositoryFile
from app.models.task import GitHubIssue
from app.repositories.repository_repository import RepositoryRepository
from app.repositories.task_repository import TaskRepository
from app.schemas.plan import (
    GitHubIssueCreateRequest,
    GitHubIssueImportRequest,
    GitHubIssueResponse,
    IssueImportResponse,
)
from app.schemas.task import TaskSourceReference, TaskStatus

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/repositories", tags=["github-issues"])


def _request_user_id(request: Request) -> UUID:
    try:
        return UUID(str(request.state.user_id))
    except (AttributeError, ValueError) as exc:
        raise APIError(401, ErrorCode.UNAUTHORIZED, "Authentication is required.") from exc


def _owned_repository(repository_id: UUID, request: Request, db: Session) -> tuple[Repository, UUID]:
    user_id = _request_user_id(request)
    repository = RepositoryRepository(db).get_for_user(repository_id, user_id)
    if repository is None:
        raise APIError(
            404,
            ErrorCode.REPOSITORY_NOT_FOUND,
            "Repository does not exist or you do not have access.",
        )
    return repository, user_id


def _resolve_installation_number(db: Session, repository: Repository) -> int | None:
    """Resolve numeric GitHub App installation_id if stored in github_installations."""
    try:
        inst = db.get(GitHubInstallation, repository.installation_id)
        if inst and str(inst.installation_id).isdigit():
            return int(inst.installation_id)
    except Exception as exc:
        logger.debug("Failed resolving numeric installation_id for repository: %s", exc)
    return None


def _serialize_issue(issue: GitHubIssue, task_id: str | None = None) -> GitHubIssueResponse:
    linked_task_id = task_id
    if linked_task_id is None and getattr(issue, "tasks", None):
        tasks_list = list(issue.tasks)
        if tasks_list:
            linked_task_id = str(tasks_list[0].id)

    payload = {
        "id": str(issue.id),
        "repository_id": str(issue.repository_id),
        "issue_number": issue.issue_number,
        "title": redact(issue.title),
        "body": redact(issue.body or ""),
        "state": issue.state or "open",
        "labels": [redact(str(lbl)) for lbl in (issue.labels or [])],
        "html_url": issue.html_url,
        "url": issue.html_url,
        "author": issue.author,
        "origin_finding_id": str(issue.origin_finding_id) if issue.origin_finding_id else None,
        "task_id": linked_task_id,
        "is_imported": linked_task_id is not None,
        "created_at": issue.created_at.isoformat() if issue.created_at else "",
        "updated_at": issue.updated_at.isoformat() if issue.updated_at else "",
    }
    return GitHubIssueResponse.model_validate(redact_obj(payload))


def _map_github_service_exception(exc: Exception) -> APIError:
    if isinstance(exc, APIError):
        return exc
    if isinstance(exc, GitHubNotFoundError):
        return APIError(404, ErrorCode.NOT_FOUND, redact(str(exc)) or "GitHub issue or repository not found.")
    if isinstance(exc, GitHubPermissionDeniedError):
        return APIError(403, ErrorCode.FORBIDDEN, redact(str(exc)) or "Insufficient GitHub permissions.")
    if isinstance(exc, GitHubRateLimitError):
        return APIError(
            429,
            ErrorCode.GITHUB_API_ERROR,
            redact(str(exc)) or "GitHub API rate limit exceeded.",
            retryable=True,
        )
    if isinstance(exc, (GitHubAuthError, GitHubInstallationRemovedError)):
        return APIError(
            502,
            ErrorCode.GITHUB_API_ERROR,
            "GitHub App authentication failed or installation was removed.",
            retryable=False,
        )
    return APIError(
        502,
        ErrorCode.GITHUB_API_ERROR,
        f"GitHub issue operation failed: {redact(str(exc))}",
        retryable=True,
    )


@router.post(
    "/{repository_id}/issues/import",
    response_model=IssueImportResponse,
    status_code=status.HTTP_200_OK,
    summary="Import an authorized GitHub issue as a development task",
    description=(
        "Validates repository ownership, fetches issue metadata from GitHub (or reuses an already-imported issue), "
        "normalizes the issue into a validated TaskIntakePayload via IssueToTaskAdapter, and persists the task."
    ),
)
async def import_github_issue(
    repository_id: UUID,
    payload: GitHubIssueImportRequest,
    request: Request,
    db: Session = Depends(get_db),
) -> IssueImportResponse:
    ensure_min_role(request, UserRole.DEVELOPER)
    repo, user_id = await run_db(db, _owned_repository, repository_id, request, db)
    task_repo = TaskRepository(db)

    # 1. Check if issue is already imported in DB (idempotent duplicate-import protection per F31)
    def _find_existing():
        ex_issue = task_repo.get_issue_by_number(repo.id, payload.issue_number)
        if ex_issue is not None:
            ex_task = task_repo.get_task_by_issue(repo.id, ex_issue.id)
            return ex_issue, ex_task
        return None, None

    existing_issue, existing_task = await run_db(db, _find_existing)
    if existing_issue is not None and existing_task is not None:
        issue_resp = _serialize_issue(existing_issue, task_id=str(existing_task.id))
        source_ref = TaskSourceReference.model_validate(existing_task.source_ref)
        return IssueImportResponse(
            task_id=str(existing_task.id),
            repository_id=str(repo.id),
            source=source_ref,
            title=redact(existing_task.title),
            status=TaskStatus(existing_task.status),
            issue=issue_resp,
            duplicate_reused=True,
        )

    # 2. Fetch issue from GitHubService (app.state.github_service) or GitHubSourceService
    gh_issue: GitHubIssueData | None = None
    github_service = getattr(request.app.state, "github_service", None)
    inst_num = await run_db(db, _resolve_installation_number, db, repo)

    if github_service is not None and hasattr(github_service, "get_issue"):
        try:
            gh_issue = await github_service.get_issue(
                repo.owner,
                repo.name,
                payload.issue_number,
                installation_id=inst_num,
            )
        except Exception as exc:
            if payload.title is None:
                raise _map_github_service_exception(exc) from exc
    else:
        try:
            source_svc = GitHubSourceService(db)
            gh_issue = await source_svc.get_issue(repo.id, user_id, payload.issue_number)
        except APIError as exc:
            if payload.title is None and existing_issue is None:
                if exc.status_code in (403, 404, 429):
                    raise
                raise APIError(
                    exc.status_code,
                    ErrorCode.GITHUB_API_ERROR if exc.status_code >= 500 else exc.code,
                    exc.message,
                    retryable=exc.retryable,
                ) from exc

    if gh_issue is not None:
        if getattr(gh_issue, "is_pull_request", False):
            raise APIError(
                400,
                ErrorCode.INVALID_REQUEST,
                f"GitHub item #{payload.issue_number} is a pull request, not an issue.",
            )
        issue_title = gh_issue.title
        issue_body = gh_issue.body
        issue_state = gh_issue.state
        issue_labels = gh_issue.labels
        issue_url = gh_issue.html_url or f"https://github.com/{repo.owner}/{repo.name}/issues/{payload.issue_number}"
        issue_author = gh_issue.author
    elif existing_issue is not None:
        issue_title = existing_issue.title
        issue_body = existing_issue.body
        issue_state = existing_issue.state
        issue_labels = existing_issue.labels
        issue_url = existing_issue.html_url
        issue_author = existing_issue.author
    elif payload.title:
        issue_title = payload.title
        issue_body = payload.body or payload.title
        issue_state = "open"
        issue_labels = payload.labels
        issue_url = f"https://github.com/{repo.owner}/{repo.name}/issues/{payload.issue_number}"
        issue_author = None
    else:
        raise APIError(
            502,
            ErrorCode.GITHUB_API_ERROR,
            f"Unable to fetch GitHub issue #{payload.issue_number}. Ensure GitHub App credentials are configured.",
            retryable=True,
        )

    # 3. Persist GitHubIssue record, inspect repo paths, and create task
    def _persist_imported_issue_and_task():
        persisted = task_repo.upsert_github_issue(
            repository_id=repo.id,
            issue_number=payload.issue_number,
            title=issue_title,
            body=issue_body,
            state=issue_state,
            labels=issue_labels,
            html_url=issue_url,
            author=issue_author,
        )[0]
        known: list[str] = []
        if hasattr(db, "query"):
            try:
                known = [
                    r.path
                    for r in db.query(RepositoryFile.path)
                    .filter(RepositoryFile.repository_id == repo.id)
                    .limit(500)
                    .all()
                ]
            except Exception:
                known = []
        adapter = IssueToTaskAdapter()
        intake_obj = adapter.from_github_issue(
            repository_id=repo.id,
            issue_number=persisted.issue_number,
            title=persisted.title,
            body=persisted.body,
            html_url=persisted.html_url,
            labels=persisted.labels,
            base_revision=payload.base_revision or repo.default_branch or "main",
            finding_id=str(persisted.origin_finding_id) if persisted.origin_finding_id else None,
            known_repo_paths=known or None,
        )
        created_t = task_repo.create_task(
            user_id=user_id,
            intake=intake_obj,
            github_issue_id=persisted.id,
            origin_finding_id=persisted.origin_finding_id,
            initial_event_type="ISSUE_IMPORTED",
            initial_event_summary=f"Imported GitHub Issue #{persisted.issue_number}: {persisted.title}",
        )
        return persisted, intake_obj, created_t

    persisted_issue, intake, task = await run_db(db, _persist_imported_issue_and_task)

    issue_resp = _serialize_issue(persisted_issue, task_id=str(task.id))
    if gh_issue is None:
        # GitHub was unavailable: the issue number and URL above are local
        # placeholders, not a real GitHub issue. Say so instead of linking to it.
        issue_resp = issue_resp.model_copy(update={"published_to_github": False})
    return IssueImportResponse(
        task_id=str(task.id),
        repository_id=str(repo.id),
        source=intake.source,
        title=redact(task.title),
        status=TaskStatus(task.status),
        issue=issue_resp,
        duplicate_reused=False,
    )


@router.get(
    "/{repository_id}/issues",
    response_model=list[GitHubIssueResponse],
    summary="List imported and created GitHub issues for a repository",
)
async def list_repository_issues(
    repository_id: UUID,
    request: Request,
    state: str = Query(default="all", pattern="^(open|closed|all)$"),
    sync_remote: bool = Query(default=False, description="Optionally fetch live open issues from GitHub"),
    db: Session = Depends(get_db),
) -> list[GitHubIssueResponse]:
    repo, _ = await run_db(db, _owned_repository, repository_id, request, db)
    task_repo = TaskRepository(db)

    if sync_remote:
        github_service = getattr(request.app.state, "github_service", None)
        inst_num = await run_db(db, _resolve_installation_number, db, repo)
        if github_service is not None and hasattr(github_service, "list_issues"):
            try:
                remote_issues = await github_service.list_issues(
                    repo.owner,
                    repo.name,
                    state="open" if state == "all" else state,
                    installation_id=inst_num,
                )
                def _upsert_remote():
                    for ri in remote_issues:
                        task_repo.upsert_github_issue(
                            repository_id=repo.id,
                            issue_number=ri.number,
                            title=ri.title,
                            body=ri.body,
                            state=ri.state,
                            labels=ri.labels,
                            html_url=ri.html_url or f"https://github.com/{repo.owner}/{repo.name}/issues/{ri.number}",
                            author=ri.author,
                        )
                await run_db(db, _upsert_remote)
            except Exception as exc:
                logger.warning("list_repository_issues_remote_sync_warning", extra={"error": redact(str(exc))})

    def _query_local_issues():
        local_issues = task_repo.list_issues_by_repository(repo.id)
        if state != "all":
            local_issues = [i for i in local_issues if (i.state or "open").lower() == state.lower()]
        out: list[GitHubIssueResponse] = []
        for issue in local_issues:
            linked_task = task_repo.get_task_by_issue(repo.id, issue.id)
            out.append(
                _serialize_issue(issue, task_id=str(linked_task.id) if linked_task else None)
            )
        return out

    return await run_db(db, _query_local_issues)


@router.post(
    "/{repository_id}/issues",
    response_model=IssueImportResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a GitHub issue from an approved bug/review finding or requirement",
    description=(
        "Validates repository and finding ownership, formats and scrubs issue title/body, "
        "creates the issue via GitHub App tokens (or persists locally when in offline mode), "
        "and links it to a normalized Week 3 development task."
    ),
)
async def create_github_issue(
    repository_id: UUID,
    payload: GitHubIssueCreateRequest,
    request: Request,
    db: Session = Depends(get_db),
) -> IssueImportResponse:
    ensure_min_role(request, UserRole.DEVELOPER)
    repo, user_id = await run_db(db, _owned_repository, repository_id, request, db)
    task_repo = TaskRepository(db)

    finding_record: AnalysisFinding | None = None
    if payload.finding_id is not None:
        try:
            f_uuid = UUID(str(payload.finding_id))
        except (ValueError, TypeError) as exc:
            raise APIError(400, ErrorCode.INVALID_REQUEST, "Invalid finding_id UUID format.") from exc

        finding_record = await run_db(db, db.get, AnalysisFinding, f_uuid)
        # Strict cross-tenant / cross-repository ownership check (Sukun W3 Day 1)
        if finding_record is None or finding_record.repository_id != repo.id:
            raise APIError(
                404,
                ErrorCode.NOT_FOUND,
                f"Finding '{payload.finding_id}' was not found in repository '{repository_id}'.",
            )

    if finding_record is not None:
        title, body, labels = format_issue_from_finding(
            finding_record,
            custom_title=payload.title,
            custom_body=payload.body,
            extra_labels=payload.labels,
        )
    else:
        if not payload.title:
            raise APIError(
                400,
                ErrorCode.INVALID_REQUEST,
                "Either finding_id or title is required to create a GitHub issue.",
            )
        title = redact(payload.title.strip())
        body = redact((payload.body or payload.title).strip())
        labels = [redact(lbl) for lbl in payload.labels] or ["enhancement"]

    # Check if an issue was already created for this exact finding_id (idempotency)
    if finding_record is not None:
        def _find_existing_for_finding():
            stmt_existing = select(GitHubIssue).where(
                GitHubIssue.repository_id == repo.id,
                GitHubIssue.origin_finding_id == finding_record.id,
            )
            ex_for_finding = db.scalars(stmt_existing).first()
            if ex_for_finding is not None:
                ex_task = task_repo.get_task_by_issue(repo.id, ex_for_finding.id)
                return ex_for_finding, ex_task
            return None, None

        existing_for_finding, existing_task = await run_db(db, _find_existing_for_finding)
        if existing_for_finding is not None and existing_task is not None:
            issue_resp = _serialize_issue(existing_for_finding, task_id=str(existing_task.id))
            return IssueImportResponse(
                task_id=str(existing_task.id),
                repository_id=str(repo.id),
                source=TaskSourceReference.model_validate(existing_task.source_ref),
                title=redact(existing_task.title),
                status=TaskStatus(existing_task.status),
                issue=issue_resp,
                duplicate_reused=True,
            )

    gh_created: GitHubIssueData | None = None
    github_service = getattr(request.app.state, "github_service", None)
    inst_num = await run_db(db, _resolve_installation_number, db, repo)

    if github_service is not None and hasattr(github_service, "create_issue"):
        try:
            gh_created = await github_service.create_issue(
                repo.owner,
                repo.name,
                title,
                body,
                labels,
                installation_id=inst_num,
            )
        except (GitHubPermissionDeniedError, GitHubRateLimitError, GitHubNotFoundError, GitHubAuthError) as exc:
            raise _map_github_service_exception(exc) from exc
        except Exception as exc:
            logger.warning("github_service_create_issue_fallback", extra={"error": redact(str(exc))})

    def _persist_created_issue_and_task():
        if gh_created is not None:
            issue_number = gh_created.number
            html_url = gh_created.html_url or f"https://github.com/{repo.owner}/{repo.name}/issues/{issue_number}"
            issue_state = gh_created.state or "open"
            issue_labels = gh_created.labels or labels
            issue_author = gh_created.author
        else:
            max_num_stmt = select(func.max(GitHubIssue.issue_number)).where(
                GitHubIssue.repository_id == repo.id
            )
            current_max = db.scalar(max_num_stmt) or 0
            issue_number = int(current_max) + 1
            html_url = f"https://github.com/{repo.owner}/{repo.name}/issues/{issue_number}"
            issue_state = "open"
            issue_labels = labels
            issue_author = None

        persisted = task_repo.upsert_github_issue(
            repository_id=repo.id,
            issue_number=issue_number,
            title=title,
            body=body,
            state=issue_state,
            labels=issue_labels,
            html_url=html_url,
            author=issue_author,
            origin_finding_id=finding_record.id if finding_record else None,
        )[0]

        known_paths: list[str] = []
        if hasattr(db, "query"):
            try:
                known_paths = [
                    r.path
                    for r in db.query(RepositoryFile.path)
                    .filter(RepositoryFile.repository_id == repo.id)
                    .limit(500)
                    .all()
                ]
            except Exception:
                known_paths = []

        adapter = IssueToTaskAdapter()
        intake_obj = adapter.from_github_issue(
            repository_id=repo.id,
            issue_number=persisted.issue_number,
            title=persisted.title,
            body=persisted.body,
            html_url=persisted.html_url,
            labels=persisted.labels,
            base_revision=repo.default_branch or "main",
            finding_id=str(finding_record.id) if finding_record else None,
            known_repo_paths=known_paths or None,
        )
        if finding_record is not None and finding_record.file_path:
            from app.core.input_security import UnsafePathError, validate_repo_relative_path

            try:
                norm_fp = validate_repo_relative_path(finding_record.file_path)
                if norm_fp not in intake_obj.requirements[0].target_files:
                    intake_obj.requirements[0].target_files.insert(0, norm_fp)
            except UnsafePathError:
                pass

        created_t = task_repo.create_task(
            user_id=user_id,
            intake=intake_obj,
            github_issue_id=persisted.id,
            origin_finding_id=finding_record.id if finding_record else None,
            initial_event_type="ISSUE_CREATED_FROM_FINDING" if finding_record else "ISSUE_CREATED",
            initial_event_summary=(
                f"Created GitHub Issue #{persisted.issue_number} from finding '{finding_record.title}'."
                if finding_record
                else f"Created GitHub Issue #{persisted.issue_number}: {persisted.title}"
            ),
        )
        return persisted, intake_obj, created_t

    persisted_issue, intake, task = await run_db(db, _persist_created_issue_and_task)

    issue_resp = _serialize_issue(persisted_issue, task_id=str(task.id))
    if gh_created is None:
        # GitHub was unavailable: the issue number and URL above are local
        # placeholders, not a real GitHub issue. Say so instead of linking to it.
        issue_resp = issue_resp.model_copy(update={"published_to_github": False})
    return IssueImportResponse(
        task_id=str(task.id),
        repository_id=str(repo.id),
        source=intake.source,
        title=redact(task.title),
        status=TaskStatus(task.status),
        issue=issue_resp,
        duplicate_reused=False,
    )
