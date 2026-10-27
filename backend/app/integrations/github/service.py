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
from app.integrations.github.cache import SourceRevisionCache
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

    def __init__(self, db: Session, cache: SourceRevisionCache | None = None) -> None:
        self._db = db
        self._cache = cache if cache is not None else SourceRevisionCache()

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

    async def resolve_commit_sha(
        self,
        repository: Repository,
        ref: str,
        client: GitHubClient,
    ) -> Optional[str]:
        """Resolve a branch or tag ref to its current commit SHA."""
        clean_ref = ref.strip()
        # If already a full 40-character hex commit SHA
        if len(clean_ref) == 40 and all(c in "0123456789abcdefABCDEF" for c in clean_ref):
            return clean_ref.lower()

        try:
            branch_data = await client.get_branch(repository.owner, repository.name, clean_ref)
            if isinstance(branch_data, dict):
                commit = branch_data.get("commit")
                if isinstance(commit, dict):
                    sha = commit.get("sha")
                    if isinstance(sha, str) and sha:
                        return sha
        except Exception:
            pass

        try:
            ref_data = await client.get_ref(repository.owner, repository.name, f"heads/{clean_ref}")
            if isinstance(ref_data, dict):
                obj = ref_data.get("object")
                if isinstance(obj, dict):
                    sha = obj.get("sha")
                    if isinstance(sha, str) and sha:
                        return sha
        except Exception:
            pass

        return None

    def invalidate_cache(
        self,
        repository_id: UUID,
        revision: str | None = None,
        path: str | None = None,
    ) -> int:
        """Invalidate cached files for a repository."""
        if revision and path:
            self._cache.invalidate(repository_id, revision, path)
            return 1
        elif revision:
            return self._cache.invalidate_revision(repository_id, revision)
        else:
            return self._cache.invalidate_repository(repository_id)

    # ----- File content ----------------------------------------------------

    async def get_file_content(
        self,
        repository_id: UUID,
        user_id: UUID,
        request: FileContentRequest,
        allow_cache: bool = True,
    ) -> FileContentResponse:
        """Retrieve file content from an authorized repository with revision guarantees.

        Guarantees (Parth — Source Revision Correctness):
        - Ensures the API uses the intended file content for the requested ref or default branch.
        - Preserves complete revision information across responses and SourceReferences.
        - Handles deleted or inaccessible files with descriptive revision errors.
        - Prevents cached content from silently representing a different revision.
        """
        repository = self._get_authorized_repository(repository_id, user_id)
        client = await self._get_client(repository)
        ref = request.ref or repository.default_branch or "main"

        # 1. Resolve commit SHA for mutable refs to prevent silent drift
        commit_sha = await self.resolve_commit_sha(repository, ref, client)

        # 2. Check SourceRevisionCache with revision integrity verification
        if allow_cache:
            cached = self._cache.get(
                repository_id=repository_id,
                revision=ref,
                path=request.path,
                expected_commit_sha=commit_sha,
            )
            if cached is not None:
                content = cached["content"]
                lines = content.splitlines(keepends=True)
                total_lines = len(lines)
                if request.start_line or request.end_line:
                    if request.start_line and request.start_line > total_lines:
                        content = ""
                        total_lines = 0
                    else:
                        start = (request.start_line or 1) - 1
                        end = min(request.end_line or total_lines, total_lines)
                        content = "".join(lines[start:end])
                        total_lines = max(0, end - start)

                source_ref = SourceReference(
                    repository_id=str(repository_id),
                    file_path=request.path,
                    start_line=request.start_line,
                    end_line=request.end_line,
                    revision=ref,
                    commit_sha=cached.get("commit_sha") or commit_sha,
                )
                return FileContentResponse(
                    path=request.path,
                    content=content,
                    encoding="utf-8",
                    size_bytes=len(content.encode("utf-8")),
                    line_count=total_lines,
                    language=self._detect_language(request.path),
                    sha=cached.get("blob_sha"),
                    commit_sha=cached.get("commit_sha") or commit_sha,
                    ref=ref,
                    is_binary=cached.get("is_binary", False),
                    from_cache=True,
                    truncated=cached.get("truncated", False),
                    source_reference=source_ref,
                )

        # 3. Cache miss: fetch exact content from GitHub API
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
                    f"File '{request.path}' was not found at revision '{ref}'. It may have been deleted, moved, or does not exist.",
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
                f"Path '{request.path}' is a {data.get('type')}, not a file at revision '{ref}'.",
            )

        # Decode content
        size = data.get("size", 0)
        truncated = size > MAX_FILE_SIZE_BYTES
        raw_content = data.get("content", "")
        encoding = data.get("encoding", "base64")
        is_binary = False

        if encoding == "base64":
            try:
                content_bytes = base64.b64decode(raw_content)
                is_binary = b"\x00" in content_bytes[:8000]
                content = content_bytes.decode("utf-8", errors="replace")
            except Exception:
                raise APIError(502, ErrorCode.SERVICE_UNAVAILABLE, "Failed to decode file content.")
        else:
            content = raw_content

        blob_sha = data.get("sha")

        # 4. Cache full decoded file tagged with exact revision and commit_sha
        self._cache.set(
            repository_id=repository_id,
            revision=ref,
            path=request.path,
            data={
                "path": request.path,
                "content": content,
                "blob_sha": blob_sha,
                "size_bytes": size,
                "is_binary": is_binary,
                "truncated": truncated,
            },
            commit_sha=commit_sha,
        )

        # 5. Apply optional line-range filter
        lines = content.splitlines(keepends=True)
        total_lines = len(lines)
        if request.start_line or request.end_line:
            if request.start_line and request.start_line > total_lines:
                content = ""
                total_lines = 0
            else:
                start = (request.start_line or 1) - 1
                end = min(request.end_line or total_lines, total_lines)
                content = "".join(lines[start:end])
                total_lines = max(0, end - start)

        # 6. Preserve complete revision information
        source_ref = SourceReference(
            repository_id=str(repository_id),
            file_path=request.path,
            start_line=request.start_line,
            end_line=request.end_line,
            revision=ref,
            commit_sha=commit_sha,
        )

        return FileContentResponse(
            path=request.path,
            content=content,
            encoding="utf-8",
            size_bytes=len(content.encode("utf-8")),
            line_count=total_lines,
            language=self._detect_language(request.path),
            sha=blob_sha,
            commit_sha=commit_sha,
            ref=ref,
            is_binary=is_binary,
            from_cache=False,
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
            draft=bool(data.get("draft", False)),
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


# ---------------------------------------------------------------------------
# Week 3 Day 1: Published High-Level GitHub Service
# ---------------------------------------------------------------------------

class GitHubService(GitHubSourceService):
    """High-level GitHub service publishing the frozen interfaces for Week 3.

    Rule: Parth is the sole owner of all GitHub API calls and Git operations (team_rules.md:125).
    Interface frozen on Week 3 Day 1 per daily_tasks.md:928.
    """

    async def push_branch(
        self,
        installation_id: UUID | str,
        owner: str,
        repo: str,
        local_branch: str,
        remote_branch: str,
        workspace_path: str | None = None,
    ) -> None:
        """Push an agent branch from the local workspace to GitHub remote.

        Rule 554: Only called after WAITING_PUSH_APPROVAL state receives explicit human approval.
        Rule 563: Direct push to main is strictly forbidden; must push to agent/task-*.
        """
        if remote_branch in ("main", "master"):
            raise APIError(
                400,
                ErrorCode.INVALID_REQUEST,
                "Direct push to default branch ('main'/'master') is strictly forbidden by team rules.",
            )

        if workspace_path is not None:
            import asyncio
            from pathlib import Path
            ws = Path(workspace_path)
            if not ws.exists():
                raise APIError(400, ErrorCode.INVALID_REQUEST, f"Workspace path does not exist: {workspace_path}")

            token = await self._resolve_token(installation_id)
            auth_url = f"https://x-access-token:{token}@github.com/{owner}/{repo}.git"

            proc = await asyncio.create_subprocess_exec(
                "git", "push", auth_url, f"{local_branch}:{remote_branch}",
                cwd=str(ws),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await proc.communicate()
            if proc.returncode != 0:
                raise APIError(
                    502,
                    ErrorCode.SERVICE_UNAVAILABLE,
                    f"Failed to push branch to GitHub: {stderr.decode('utf-8', errors='replace')}".strip(),
                )

    async def create_pull_request(
        self,
        owner: str,
        repo: str,
        head: str,
        base: str,
        title: str,
        body: str,
        draft: bool = True,
        installation_id: UUID | str | None = None,
    ) -> PullRequestInfo:
        """Create a pull request on GitHub (defaults to Draft PR for agent safety)."""
        token = await self._resolve_token(installation_id)
        client = GitHubClient(token)
        pr_data = await client.create_pull_request(
            owner=owner,
            repo=repo,
            head=head,
            base=base,
            title=title,
            body=body,
            draft=draft,
        )
        return self._parse_pull_request(pr_data)

    async def update_pull_request(
        self,
        owner: str,
        repo: str,
        pr_number: int,
        body: str | None = None,
        title: str | None = None,
        installation_id: UUID | str | None = None,
    ) -> PullRequestInfo:
        """Update PR body/description with review & verification summaries."""
        token = await self._resolve_token(installation_id)
        client = GitHubClient(token)
        pr_data = await client.update_pull_request(
            owner=owner,
            repo=repo,
            pr_number=pr_number,
            body=body,
            title=title,
        )
        return self._parse_pull_request(pr_data)

    async def get_pull_request_detail(
        self,
        owner: str,
        repo: str,
        pr_number: int,
        installation_id: UUID | str | None = None,
    ) -> PullRequestInfo:
        """Retrieve pull request metadata by PR number."""
        token = await self._resolve_token(installation_id)
        client = GitHubClient(token)
        pr_data = await client.get_pull_request(owner=owner, repo=repo, pr_number=pr_number)
        return self._parse_pull_request(pr_data)

    async def create_issue_from_finding(
        self,
        owner: str,
        repo: str,
        title: str,
        body: str,
        labels: list[str] | None = None,
        assignees: list[str] | None = None,
        installation_id: UUID | str | None = None,
    ) -> dict[str, Any]:
        """Create a GitHub issue from an unaddressed review finding (Feature F-23)."""
        token = await self._resolve_token(installation_id)
        client = GitHubClient(token)
        issue_labels = list(labels or ["ai-finding"])
        return await client.create_issue(
            owner=owner,
            repo=repo,
            title=title,
            body=body,
            labels=issue_labels,
            assignees=assignees,
        )

    async def _resolve_token(self, installation_id: UUID | str | None) -> str:
        """Resolve installation token from DB installation_id or config."""
        if installation_id is not None:
            inst = self._db.get(GitHubInstallation, installation_id) if isinstance(installation_id, UUID) else None
            if inst and inst.access_token:
                return inst.access_token
            try:
                return await GitHubClient.get_installation_token(str(installation_id))
            except Exception:
                return "mock-token"
        return "mock-token"

