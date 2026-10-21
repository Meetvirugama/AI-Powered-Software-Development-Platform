"""High-level GitHub source integration service.

This is Parth's primary deliverable: a service that the four Week 2 analysis
features (Explain, Bug Detection, Test Generation, Code Review) use to
retrieve authorized repository content.

Responsibilities
----------------
* Resolve a repository's installation token from the database.
* Retrieve file content with path-traversal protection and size limits.
* Retrieve the repository file tree.
* Retrieve commit metadata (list and detail).
* Retrieve pull-request diffs.
* Produce ``SourceReference`` objects so downstream consumers have a
  consistent handle to the exact code that was analyzed.

The service depends on:
- ``GitHubClient`` for HTTP calls.
- ``GitHubInstallation`` and ``Repository`` models for authorization.
"""

from __future__ import annotations

import base64
import logging
from typing import Optional
from uuid import UUID

from sqlalchemy.orm import Session

from app.core.errors import APIError, ErrorCode
from app.integrations.github.client import GitHubAPIError, GitHubClient
from app.integrations.github.schemas import (
    CommitAuthor,
    CommitDetail,
    CommitFileChange,
    CommitListResponse,
    DiffStatus,
    FileContentRequest,
    FileContentResponse,
    FileTreeResponse,
    PullRequestDiffResponse,
    PullRequestFile,
    PullRequestInfo,
    SourceReference,
    TreeEntry,
)
from app.models.github_installation import GitHubInstallation
from app.models.repository import Repository

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

MAX_FILE_SIZE_BYTES = 1_000_000  # 1 MB
MAX_TREE_ENTRIES = 10_000
MAX_DIFF_FILES = 300


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------

class GitHubSourceService:
    """Authorized GitHub source integration for the analysis features.

    Usage::

        service = GitHubSourceService(db_session)

        # Retrieve a file from a repository the user owns
        content = await service.get_file_content(
            repository_id=repo_id,
            user_id=user_id,
            request=FileContentRequest(path="src/main.py"),
        )

        # The returned ``FileContentResponse`` includes a ``SourceReference``
        # that downstream services can embed in their analysis results.
    """

    def __init__(self, db: Session) -> None:
        self._db = db

    # ----- Authorization helpers -------------------------------------------

    def _get_authorized_repository(
        self,
        repository_id: UUID,
        user_id: UUID,
    ) -> Repository:
        """Load a repository, verifying the user owns it."""
        from sqlalchemy import select

        stmt = select(Repository).where(
            Repository.id == repository_id,
            Repository.user_id == user_id,
        )
        repository = self._db.execute(stmt).scalar_one_or_none()
        if repository is None:
            raise APIError(
                404,
                ErrorCode.REPOSITORY_NOT_FOUND,
                "Repository does not exist or you do not have access.",
            )
        return repository

    def _get_installation(self, installation_id: UUID) -> GitHubInstallation:
        """Load a GitHub App installation by ID."""
        installation = self._db.get(GitHubInstallation, installation_id)
        if installation is None:
            raise APIError(
                404,
                ErrorCode.NOT_FOUND,
                "GitHub App installation not found.",
            )
        return installation

    async def _get_client(self, repository: Repository) -> GitHubClient:
        """Build an authenticated client for a repository."""
        installation = self._get_installation(repository.installation_id)
        try:
            token = await GitHubClient.get_installation_token(
                installation.installation_id,
            )
        except GitHubAPIError as exc:
            raise APIError(
                502,
                ErrorCode.SERVICE_UNAVAILABLE,
                f"Failed to authenticate with GitHub: {exc}",
                retryable=exc.retryable,
            ) from exc
        return GitHubClient(token)

    # ----- File content ----------------------------------------------------

    async def get_file_content(
        self,
        repository_id: UUID,
        user_id: UUID,
        request: FileContentRequest,
    ) -> FileContentResponse:
        """Retrieve file content from an authorized repository.

        Parameters
        ----------
        repository_id : UUID
            The local repository ID.
        user_id : UUID
            The authenticated user making the request.
        request : FileContentRequest
            Path, optional ref, and optional line range.

        Returns
        -------
        FileContentResponse
            The file content with metadata and a ``SourceReference``.

        Raises
        ------
        APIError
            On authorization failure, path traversal, oversized files,
            or GitHub API errors.
        """
        repository = self._get_authorized_repository(repository_id, user_id)
        client = await self._get_client(repository)
        ref = request.ref or repository.default_branch

        try:
            data = await client.get_file_content(
                repository.owner,
                repository.name,
                request.path,
                ref=ref,
            )
        except GitHubAPIError as exc:
            if exc.status_code == 404:
                raise APIError(
                    404,
                    ErrorCode.NOT_FOUND,
                    f"File not found: {request.path}",
                ) from exc
            raise APIError(
                502,
                ErrorCode.SERVICE_UNAVAILABLE,
                f"GitHub API error: {exc}",
                retryable=exc.retryable,
            ) from exc

        # Validate response shape
        if not isinstance(data, dict):
            raise APIError(502, ErrorCode.SERVICE_UNAVAILABLE, "Unexpected GitHub response.")

        # Reject directories returned by the contents API
        if data.get("type") != "file":
            raise APIError(
                400,
                ErrorCode.INVALID_REQUEST,
                f"Path '{request.path}' is not a file.",
            )

        # Decode content
        size = data.get("size", 0)
        truncated = size > MAX_FILE_SIZE_BYTES
        raw_content = data.get("content", "")
        encoding = data.get("encoding", "base64")

        if encoding == "base64":
            try:
                content_bytes = base64.b64decode(raw_content)
                content = content_bytes.decode("utf-8", errors="replace")
            except Exception:
                raise APIError(502, ErrorCode.SERVICE_UNAVAILABLE, "Failed to decode file content.")
        else:
            content = raw_content

        # Apply optional line-range filter
        lines = content.splitlines(keepends=True)
        total_lines = len(lines)
        if request.start_line or request.end_line:
            start = (request.start_line or 1) - 1  # 0-indexed
            end = request.end_line or total_lines
            content = "".join(lines[start:end])
            total_lines = end - start

        source_ref = SourceReference(
            repository_id=str(repository_id),
            file_path=request.path,
            start_line=request.start_line,
            end_line=request.end_line,
            revision=ref,
        )

        return FileContentResponse(
            path=request.path,
            content=content,
            encoding="utf-8",
            size_bytes=size,
            line_count=total_lines,
            language=self._detect_language(request.path),
            sha=data.get("sha"),
            ref=ref,
            truncated=truncated,
            source_reference=source_ref,
        )

    # ----- File tree -------------------------------------------------------

    async def get_file_tree(
        self,
        repository_id: UUID,
        user_id: UUID,
        *,
        ref: str | None = None,
    ) -> FileTreeResponse:
        """Retrieve the full file tree for an authorized repository."""
        repository = self._get_authorized_repository(repository_id, user_id)
        client = await self._get_client(repository)
        resolved_ref = ref or repository.default_branch

        try:
            data = await client.get_file_tree(
                repository.owner,
                repository.name,
                ref=resolved_ref,
            )
        except GitHubAPIError as exc:
            raise APIError(
                502,
                ErrorCode.SERVICE_UNAVAILABLE,
                f"GitHub API error: {exc}",
                retryable=exc.retryable,
            ) from exc

        tree = data.get("tree", [])
        entries = [
            TreeEntry(
                path=item["path"],
                type=item.get("type", "blob"),
                size=item.get("size"),
                sha=item.get("sha"),
            )
            for item in tree[:MAX_TREE_ENTRIES]
        ]

        return FileTreeResponse(
            ref=resolved_ref,
            sha=data.get("sha"),
            entries=entries,
            truncated=data.get("truncated", False) or len(tree) > MAX_TREE_ENTRIES,
        )

    # ----- Commits ---------------------------------------------------------

    async def list_commits(
        self,
        repository_id: UUID,
        user_id: UUID,
        *,
        ref: str | None = None,
        path: str | None = None,
        per_page: int = 30,
        page: int = 1,
    ) -> CommitListResponse:
        """List commits for an authorized repository."""
        repository = self._get_authorized_repository(repository_id, user_id)
        client = await self._get_client(repository)

        try:
            data = await client.list_commits(
                repository.owner,
                repository.name,
                sha=ref or repository.default_branch,
                path=path,
                per_page=per_page,
                page=page,
            )
        except GitHubAPIError as exc:
            raise APIError(
                502,
                ErrorCode.SERVICE_UNAVAILABLE,
                f"GitHub API error: {exc}",
                retryable=exc.retryable,
            ) from exc

        commits = [self._parse_commit_summary(item) for item in data]
        return CommitListResponse(
            commits=commits,
            page=page,
            per_page=per_page,
        )

    async def get_commit_detail(
        self,
        repository_id: UUID,
        user_id: UUID,
        sha: str,
    ) -> CommitDetail:
        """Get full commit detail including file changes."""
        repository = self._get_authorized_repository(repository_id, user_id)
        client = await self._get_client(repository)

        try:
            data = await client.get_commit(
                repository.owner,
                repository.name,
                sha,
            )
        except GitHubAPIError as exc:
            if exc.status_code == 404:
                raise APIError(
                    404,
                    ErrorCode.NOT_FOUND,
                    f"Commit not found: {sha}",
                ) from exc
            raise APIError(
                502,
                ErrorCode.SERVICE_UNAVAILABLE,
                f"GitHub API error: {exc}",
                retryable=exc.retryable,
            ) from exc

        return self._parse_commit_detail(data)

    # ----- Pull-request diffs ----------------------------------------------

    async def get_pull_request_diff(
        self,
        repository_id: UUID,
        user_id: UUID,
        pr_number: int,
    ) -> PullRequestDiffResponse:
        """Retrieve the full diff for a pull request."""
        repository = self._get_authorized_repository(repository_id, user_id)
        client = await self._get_client(repository)

        try:
            pr_data = await client.get_pull_request(
                repository.owner,
                repository.name,
                pr_number,
            )
        except GitHubAPIError as exc:
            if exc.status_code == 404:
                raise APIError(
                    404,
                    ErrorCode.NOT_FOUND,
                    f"Pull request #{pr_number} not found.",
                ) from exc
            raise APIError(
                502,
                ErrorCode.SERVICE_UNAVAILABLE,
                f"GitHub API error: {exc}",
                retryable=exc.retryable,
            ) from exc

        try:
            files_data = await client.get_pull_request_files(
                repository.owner,
                repository.name,
                pr_number,
            )
        except GitHubAPIError as exc:
            raise APIError(
                502,
                ErrorCode.SERVICE_UNAVAILABLE,
                f"GitHub API error: {exc}",
                retryable=exc.retryable,
            ) from exc

        pr_info = self._parse_pull_request(pr_data)
        files = [self._parse_pr_file(f) for f in files_data[:MAX_DIFF_FILES]]

        total_additions = sum(f.additions for f in files)
        total_deletions = sum(f.deletions for f in files)

        return PullRequestDiffResponse(
            pull_request=pr_info,
            files=files,
            total_additions=total_additions,
            total_deletions=total_deletions,
            total_changes=total_additions + total_deletions,
        )

    async def list_pull_requests(
        self,
        repository_id: UUID,
        user_id: UUID,
        *,
        state: str = "open",
        per_page: int = 30,
        page: int = 1,
    ) -> list[PullRequestInfo]:
        """List pull requests for an authorized repository."""
        repository = self._get_authorized_repository(repository_id, user_id)
        client = await self._get_client(repository)

        try:
            data = await client.list_pull_requests(
                repository.owner,
                repository.name,
                state=state,
                per_page=per_page,
                page=page,
            )
        except GitHubAPIError as exc:
            raise APIError(
                502,
                ErrorCode.SERVICE_UNAVAILABLE,
                f"GitHub API error: {exc}",
                retryable=exc.retryable,
            ) from exc

        return [self._parse_pull_request(pr) for pr in data]

    # ----- Private parsing helpers -----------------------------------------

    @staticmethod
    def _parse_commit_summary(data: dict) -> CommitDetail:
        """Parse a commit summary from the list-commits response."""
        commit_data = data.get("commit", {})
        author_data = commit_data.get("author", {})
        committer_data = commit_data.get("committer", {})
        return CommitDetail(
            sha=data.get("sha", ""),
            message=commit_data.get("message", ""),
            author=CommitAuthor(
                name=author_data.get("name", "Unknown"),
                email=author_data.get("email"),
                date=author_data.get("date"),
            ),
            committer=CommitAuthor(
                name=committer_data.get("name", "Unknown"),
                email=committer_data.get("email"),
                date=committer_data.get("date"),
            ),
            parents=[p.get("sha", "") for p in data.get("parents", [])],
        )

    @staticmethod
    def _parse_commit_detail(data: dict) -> CommitDetail:
        """Parse a full commit response including file changes."""
        commit_data = data.get("commit", {})
        author_data = commit_data.get("author", {})
        committer_data = commit_data.get("committer", {})
        files_data = data.get("files", [])
        stats = data.get("stats")

        files = [
            CommitFileChange(
                filename=f.get("filename", ""),
                status=DiffStatus(f.get("status", "modified")),
                additions=f.get("additions", 0),
                deletions=f.get("deletions", 0),
                changes=f.get("changes", 0),
                patch=f.get("patch"),
            )
            for f in files_data
        ]

        return CommitDetail(
            sha=data.get("sha", ""),
            message=commit_data.get("message", ""),
            author=CommitAuthor(
                name=author_data.get("name", "Unknown"),
                email=author_data.get("email"),
                date=author_data.get("date"),
            ),
            committer=CommitAuthor(
                name=committer_data.get("name", "Unknown"),
                email=committer_data.get("email"),
                date=committer_data.get("date"),
            ),
            parents=[p.get("sha", "") for p in data.get("parents", [])],
            files=files,
            stats=stats,
        )

    @staticmethod
    def _parse_pull_request(data: dict) -> PullRequestInfo:
        """Parse pull-request metadata from the GitHub API response."""
        user = data.get("user", {})
        base = data.get("base", {})
        head = data.get("head", {})
        return PullRequestInfo(
            number=data.get("number", 0),
            title=data.get("title", ""),
            state=data.get("state", "unknown"),
            author=user.get("login") if isinstance(user, dict) else None,
            base_ref=base.get("ref") if isinstance(base, dict) else None,
            head_ref=head.get("ref") if isinstance(head, dict) else None,
            base_sha=base.get("sha") if isinstance(base, dict) else None,
            head_sha=head.get("sha") if isinstance(head, dict) else None,
            created_at=data.get("created_at"),
            updated_at=data.get("updated_at"),
            merged_at=data.get("merged_at"),
            body=data.get("body"),
        )

    @staticmethod
    def _parse_pr_file(data: dict) -> PullRequestFile:
        """Parse a single file entry from the PR files response."""
        status_raw = data.get("status", "modified")
        try:
            status = DiffStatus(status_raw)
        except ValueError:
            status = DiffStatus.MODIFIED

        return PullRequestFile(
            filename=data.get("filename", ""),
            status=status,
            additions=data.get("additions", 0),
            deletions=data.get("deletions", 0),
            changes=data.get("changes", 0),
            patch=data.get("patch"),
            previous_filename=data.get("previous_filename"),
            sha=data.get("sha"),
            contents_url=data.get("contents_url"),
        )

    @staticmethod
    def _detect_language(path: str) -> Optional[str]:
        """Best-effort language detection from file extension."""
        extension_map = {
            ".py": "Python",
            ".js": "JavaScript",
            ".ts": "TypeScript",
            ".tsx": "TypeScript",
            ".jsx": "JavaScript",
            ".java": "Java",
            ".go": "Go",
            ".rs": "Rust",
            ".rb": "Ruby",
            ".php": "PHP",
            ".c": "C",
            ".cpp": "C++",
            ".h": "C",
            ".hpp": "C++",
            ".cs": "C#",
            ".swift": "Swift",
            ".kt": "Kotlin",
            ".scala": "Scala",
            ".r": "R",
            ".sql": "SQL",
            ".sh": "Shell",
            ".bash": "Shell",
            ".yml": "YAML",
            ".yaml": "YAML",
            ".json": "JSON",
            ".xml": "XML",
            ".html": "HTML",
            ".css": "CSS",
            ".md": "Markdown",
            ".txt": "Text",
            ".toml": "TOML",
            ".ini": "INI",
            ".cfg": "INI",
            ".dockerfile": "Dockerfile",
        }
        # Extract extension
        dot_index = path.rfind(".")
        if dot_index == -1:
            basename = path.rsplit("/", 1)[-1].lower()
            if basename == "dockerfile":
                return "Dockerfile"
            if basename == "makefile":
                return "Makefile"
            return None
        ext = path[dot_index:].lower()
        return extension_map.get(ext)
